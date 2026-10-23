from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Optional

GGUF_MAGIC = b"GGUF"

# GGUF metadata value types
_GGUF_UINT8 = 0
_GGUF_INT8 = 1
_GGUF_UINT16 = 2
_GGUF_INT16 = 3
_GGUF_UINT32 = 4
_GGUF_INT32 = 5
_GGUF_FLOAT32 = 6
_GGUF_BOOL = 7
_GGUF_STRING = 8
_GGUF_ARRAY = 9
_GGUF_UINT64 = 10
_GGUF_INT64 = 11
_GGUF_FLOAT64 = 12

_FIXED_SIZES = {
    _GGUF_UINT8: 1,
    _GGUF_INT8: 1,
    _GGUF_UINT16: 2,
    _GGUF_INT16: 2,
    _GGUF_UINT32: 4,
    _GGUF_INT32: 4,
    _GGUF_FLOAT32: 4,
    _GGUF_BOOL: 1,
    _GGUF_UINT64: 8,
    _GGUF_INT64: 8,
    _GGUF_FLOAT64: 8,
}

_SCALAR_FORMATS = {
    _GGUF_UINT8: "<B",
    _GGUF_INT8: "<b",
    _GGUF_UINT16: "<H",
    _GGUF_INT16: "<h",
    _GGUF_UINT32: "<I",
    _GGUF_INT32: "<i",
    _GGUF_FLOAT32: "<f",
    _GGUF_UINT64: "<Q",
    _GGUF_INT64: "<q",
    _GGUF_FLOAT64: "<d",
}

_MAX_STRING = 4 * 1024 * 1024
_MAX_ARRAY_ITEMS = 50_000_000
_MAX_TENSORS = 1_000_000


class GgufError(RuntimeError):
    pass


def _read_exact(f: BinaryIO, n: int) -> bytes:
    if n < 0:
        raise GgufError("negative read length")
    data = f.read(n)
    if len(data) != n:
        raise GgufError(f"truncated GGUF file: wanted {n} bytes, got {len(data)}")
    return data


def _read_u32(f: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(f, 4))[0]


def _read_u64(f: BinaryIO) -> int:
    return struct.unpack("<Q", _read_exact(f, 8))[0]


def _read_string(f: BinaryIO) -> str:
    n = _read_u64(f)
    if n > _MAX_STRING:
        raise GgufError(f"GGUF string too large: {n}")
    return _read_exact(f, n).decode("utf-8", errors="replace")


def _skip(f: BinaryIO, n: int, file_size: int) -> None:
    if n < 0:
        raise GgufError("negative skip")
    pos = f.tell()
    if pos + n > file_size:
        raise GgufError("truncated GGUF file while skipping")
    f.seek(n, os.SEEK_CUR)


def _skip_value(f: BinaryIO, value_type: int, file_size: int, depth: int = 0) -> None:
    if depth > 8:
        raise GgufError("GGUF metadata nesting too deep")
    if value_type in _FIXED_SIZES:
        _skip(f, _FIXED_SIZES[value_type], file_size)
        return
    if value_type == _GGUF_STRING:
        n = _read_u64(f)
        if n > _MAX_STRING:
            raise GgufError(f"GGUF string too large: {n}")
        _skip(f, n, file_size)
        return
    if value_type == _GGUF_ARRAY:
        elem_type = _read_u32(f)
        count = _read_u64(f)
        if count > _MAX_ARRAY_ITEMS:
            raise GgufError(f"GGUF array too large: {count}")
        if elem_type in _FIXED_SIZES:
            _skip(f, _FIXED_SIZES[elem_type] * count, file_size)
            return
        for _ in range(count):
            _skip_value(f, elem_type, file_size, depth + 1)
        return
    raise GgufError(f"unsupported GGUF value type: {value_type}")


def _read_value(f: BinaryIO, value_type: int, file_size: int) -> Any:
    if value_type in _SCALAR_FORMATS:
        fmt = _SCALAR_FORMATS[value_type]
        return struct.unpack(fmt, _read_exact(f, struct.calcsize(fmt)))[0]
    if value_type == _GGUF_BOOL:
        return bool(_read_exact(f, 1)[0])
    if value_type == _GGUF_STRING:
        return _read_string(f)
    if value_type == _GGUF_ARRAY:
        elem_type = _read_u32(f)
        count = _read_u64(f)
        # Do not materialise tokenizer arrays.  Record the shape and skip.
        if elem_type in _FIXED_SIZES:
            _skip(f, _FIXED_SIZES[elem_type] * count, file_size)
        else:
            for _ in range(count):
                _skip_value(f, elem_type, file_size, 1)
        return {"__gguf_array__": True, "elem_type": elem_type, "count": count}
    raise GgufError(f"unsupported GGUF value type: {value_type}")


def probe_gguf(path: str | Path) -> dict[str, Any]:
    """Read the GGUF header/metadata/tensor-info section only.

    This never reads tensor data, so it is fast even for multi-GB models.
    """
    path = Path(path)
    file_size = path.stat().st_size
    with open(path, "rb") as f:
        magic = _read_exact(f, 4)
        if magic != GGUF_MAGIC:
            raise GgufError(f"not a GGUF file (magic={magic!r})")
        version = _read_u32(f)
        if version < 2 or version > 3:
            raise GgufError(f"unsupported GGUF version: {version}")
        tensor_count = _read_u64(f)
        kv_count = _read_u64(f)
        if tensor_count > _MAX_TENSORS:
            raise GgufError(f"too many tensors: {tensor_count}")
        if kv_count > 1_000_000:
            raise GgufError(f"too many metadata keys: {kv_count}")

        metadata: dict[str, Any] = {}
        array_shapes: dict[str, dict[str, Any]] = {}
        for _ in range(kv_count):
            key = _read_string(f)
            value_type = _read_u32(f)
            if value_type == _GGUF_ARRAY:
                elem_type = _read_u32(f)
                count = _read_u64(f)
                if count > _MAX_ARRAY_ITEMS:
                    raise GgufError(f"GGUF array too large: {count}")
                array_shapes[key] = {"elem_type": elem_type, "count": count}
                if elem_type in _FIXED_SIZES:
                    _skip(f, _FIXED_SIZES[elem_type] * count, file_size)
                else:
                    for _ in range(count):
                        _skip_value(f, elem_type, file_size, 1)
            else:
                value = _read_value(f, value_type, file_size)
                metadata[key] = value

        tensor_names: list[str] = []
        for _ in range(tensor_count):
            name = _read_string(f)
            n_dims = _read_u32(f)
            if n_dims > 8:
                raise GgufError(f"invalid tensor dimensions: {n_dims}")
            dims = [_read_u64(f) for _ in range(n_dims)]
            tensor_type = _read_u32(f)
            offset = _read_u64(f)
            tensor_names.append(name)
            # Keep the info reachable for debugging without bloating the cache.
            if len(tensor_names) <= 8:
                metadata.setdefault("__tensor_info_sample__", []).append(
                    {
                        "name": name,
                        "n_dims": n_dims,
                        "dims": dims,
                        "type": tensor_type,
                        "offset": offset,
                    }
                )

    arch = metadata.get("general.architecture")
    if not isinstance(arch, str):
        arch = ""
    name = metadata.get("general.name")
    if not isinstance(name, str):
        name = path.stem

    def _int_key(suffix: str) -> Optional[int]:
        if arch:
            value = metadata.get(f"{arch}.{suffix}")
            if isinstance(value, (int, float)):
                return int(value)
        # Fallback: any key ending with the suffix.
        for key, value in metadata.items():
            if key.endswith("." + suffix) and isinstance(value, (int, float)):
                return int(value)
        return None

    nextn_layers = _int_key("nextn_predict_layers")
    n_layer = _int_key("n_layer")
    context_length = _int_key("context_length")
    embedding_length = _int_key("embedding_length")

    nextn_tensors = [n for n in tensor_names if "nextn" in n.lower()]
    has_mtp = bool(nextn_tensors) and (nextn_layers is None or nextn_layers > 0)

    return {
        "path": str(path),
        "size": file_size,
        "version": version,
        "tensor_count": tensor_count,
        "kv_count": kv_count,
        "architecture": arch,
        "name": name,
        "file_type": metadata.get("general.file_type"),
        "context_length": context_length,
        "n_layer": n_layer,
        "embedding_length": embedding_length,
        "nextn_predict_layers": nextn_layers,
        "nextn_tensors": nextn_tensors,
        "nextn_tensor_count": len(nextn_tensors),
        "has_mtp": has_mtp,
        "metadata": {
            k: v
            for k, v in metadata.items()
            if not k.startswith("__") and isinstance(v, (str, int, float, bool))
        },
        "array_shapes": array_shapes,
    }


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_model_info(
    path: str | Path,
    cache_path: str | Path,
    *,
    compute_hash: bool = True,
) -> dict[str, Any]:
    path = Path(path)
    cache_path = Path(cache_path)
    try:
        stat = path.stat()
    except OSError as exc:
        raise GgufError(f"model file not readable: {path}: {exc}") from exc

    cached: Optional[dict[str, Any]] = None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None

    if (
        cached
        and cached.get("path") == str(path)
        and cached.get("size") == stat.st_size
        and cached.get("mtime_ns") == stat.st_mtime_ns
        and (not compute_hash or cached.get("sha256"))
    ):
        return cached

    probe = probe_gguf(path)
    sha = cached.get("sha256") if cached and cached.get("sha256") else None
    if compute_hash and not sha:
        sha = sha256_file(path)
    info = {
        **probe,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha,
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".model-info-", dir=str(cache_path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, cache_path)
    except OSError:
        pass
    return info