from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, Optional

Number = Optional[float]


def _as_float(value: Any) -> Number:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def extract_timings(timings: Any) -> dict[str, Any]:
    """Normalise the llama-server timings object.

    Values that the server did not report are kept as None.  We never invent a
    zero for a missing metric.
    """
    if not isinstance(timings, dict):
        return {
            "prompt_n": None,
            "prompt_ms": None,
            "prompt_per_second": None,
            "predicted_n": None,
            "predicted_ms": None,
            "predicted_per_second": None,
            "draft_n": None,
            "draft_n_accepted": None,
            "cache_n": None,
        }
    out = {
        "prompt_n": _as_int(timings.get("prompt_n")),
        "prompt_ms": _as_float(timings.get("prompt_ms")),
        "prompt_per_second": _as_float(timings.get("prompt_per_second")),
        "predicted_n": _as_int(timings.get("predicted_n")),
        "predicted_ms": _as_float(timings.get("predicted_ms")),
        "predicted_per_second": _as_float(timings.get("predicted_per_second")),
        "draft_n": _as_int(timings.get("draft_n")),
        "draft_n_accepted": _as_int(timings.get("draft_n_accepted")),
        "cache_n": _as_int(timings.get("cache_n")),
    }
    return out


def decode_tps(timings: Any) -> tuple[Number, Optional[str]]:
    t = extract_timings(timings)
    if t["predicted_per_second"] is not None:
        return t["predicted_per_second"], "server_timings"
    n = t["predicted_n"]
    ms = t["predicted_ms"]
    if n is not None and ms is not None and ms > 0:
        return n / (ms / 1000.0), "backend_computed"
    return None, None


def acceptance(timings: Any, metrics_delta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return draft acceptance statistics.

    Primary source: per-request timings (draft_n / draft_n_accepted).
    Fallback: delta of the Prometheus counters around the formal request.
    """
    t = extract_timings(timings)
    draft_n = t["draft_n"]
    accepted = t["draft_n_accepted"]
    source = "server_timings"

    if draft_n is None and metrics_delta:
        draft_n = _as_int(metrics_delta.get("draft_tokens"))
        accepted = _as_int(metrics_delta.get("accepted_tokens"))
        source = "metrics_delta"

    if draft_n is None:
        return {
            "draft_n": None,
            "draft_n_accepted": None,
            "acceptance_rate": None,
            "mean_accepted_length": None,
            "source": None,
        }

    if accepted is None:
        return {
            "draft_n": draft_n,
            "draft_n_accepted": None,
            "acceptance_rate": None,
            "mean_accepted_length": None,
            "source": source,
        }

    rate = accepted / draft_n if draft_n > 0 else None
    mean_len = None
    drafts = None
    if metrics_delta:
        drafts = _as_int(metrics_delta.get("drafts"))
    if rate is not None and drafts and drafts > 0:
        mean_len = 1.0 + accepted / drafts
    return {
        "draft_n": draft_n,
        "draft_n_accepted": accepted,
        "acceptance_rate": rate,
        "mean_accepted_length": mean_len,
        "source": source if draft_n > 0 else None,
    }


def speedup(baseline_tps: Number, mtp_tps: Number) -> Number:
    if baseline_tps is None or mtp_tps is None:
        return None
    if baseline_tps <= 0:
        return None
    return mtp_tps / baseline_tps


def verdict(value: Number, threshold: float = 0.03) -> str:
    if value is None:
        return "unknown"
    if value >= 1.0 + threshold:
        return "mtp_faster"
    if value <= 1.0 - threshold:
        return "mtp_slower"
    return "similar"


def summarise(values: Iterable[Number]) -> Optional[dict[str, Any]]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return None
    return {
        "count": len(clean),
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
    }


def parse_prometheus(text: str) -> dict[str, float]:
    """Parse the subset of Prometheus text we need.

    Keys are the exact metric name (including labels, if any).  Label-free
    counters are also available under their bare name.
    """
    out: dict[str, float] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            metric, value = line.rsplit(None, 1)
            parsed = float(value)
        except (ValueError, IndexError):
            continue
        out[metric] = parsed
        base = metric.split("{", 1)[0]
        if "{" not in metric:
            out[base] = parsed
    return out


def metrics_delta(before: dict[str, float], after: dict[str, float]) -> dict[str, Any]:
    mapping = {
        "prompt_tokens": "llamacpp:prompt_tokens_total",
        "predicted_tokens": "llamacpp:tokens_predicted_total",
        "prompt_seconds": "llamacpp:prompt_seconds_total",
        "predicted_seconds": "llamacpp:tokens_predicted_seconds_total",
        "draft_tokens": "llamacpp:spec_decode_num_draft_tokens_total",
        "accepted_tokens": "llamacpp:spec_decode_num_accepted_tokens_total",
        "drafts": "llamacpp:spec_decode_num_drafts_total",
    }
    out: dict[str, Any] = {}
    for key, metric in mapping.items():
        b = before.get(metric)
        a = after.get(metric)
        if b is None or a is None:
            out[key] = None
        elif a < b:
            out[key] = None  # counter reset / server restart
        else:
            out[key] = a - b

    per_position: dict[str, float] = {}
    prefix = "llamacpp:spec_decode_num_accepted_tokens_per_pos_total"
    for key, value in after.items():
        if not key.startswith(prefix):
            continue
        if key in before and value >= before[key]:
            per_position[key] = value - before[key]
    out["accepted_per_position"] = per_position
    out["raw_before"] = before
    out["raw_after"] = after
    return out


def run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    timings = run.get("timings")
    t = extract_timings(timings)
    tps, tps_source = decode_tps(timings)
    acc = acceptance(timings, run.get("metrics_delta"))
    return {
        "decode_tps": tps,
        "decode_tps_source": tps_source,
        "prompt_n": t["prompt_n"],
        "prompt_ms": t["prompt_ms"],
        "prompt_per_second": t["prompt_per_second"],
        "predicted_n": t["predicted_n"],
        "predicted_ms": t["predicted_ms"],
        "predicted_per_second": t["predicted_per_second"],
        "cache_n": t["cache_n"],
        "ttft_ms": run.get("ttft_ms"),
        "first_content_ms": run.get("first_content_ms"),
        "e2e_ms": run.get("e2e_ms"),
        "acceptance": acc,
    }


def summarise_mode(runs: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    successful = [r for r in runs if r.get("mode") == mode and r.get("status") == "completed"]
    failed = [
        r
        for r in runs
        if r.get("mode") == mode and r.get("status") in ("failed", "interrupted")
    ]
    cancelled = [r for r in runs if r.get("mode") == mode and r.get("status") == "cancelled"]
    metrics = [run_metrics(r) for r in successful]
    tps_values = [m["decode_tps"] for m in metrics]
    ttft_values = [m["ttft_ms"] for m in metrics]
    e2e_values = [m["e2e_ms"] for m in metrics]
    token_values = [m["predicted_n"] for m in metrics]
    acceptance_values = [
        m["acceptance"]["acceptance_rate"] for m in metrics
    ]
    return {
        "mode": mode,
        "runs": len(successful),
        "failures": len(failed),
        "cancelled": len(cancelled),
        "decode_tps": summarise(tps_values),
        "ttft_ms": summarise(ttft_values),
        "e2e_ms": summarise(e2e_values),
        "predicted_n": summarise(token_values),
        "acceptance_rate": summarise(acceptance_values),
        "per_run": metrics,
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = summarise_mode(runs, "baseline")
    mtp = summarise_mode(runs, "mtp")
    pairs: list[dict[str, Any]] = []
    by_index: dict[int, dict[str, dict[str, Any]]] = {}
    for run in runs:
        if run.get("status") != "completed":
            continue
        idx = run.get("run_index")
        mode = run.get("mode")
        if idx is None or mode not in ("baseline", "mtp"):
            continue
        by_index.setdefault(idx, {})[mode] = run

    for idx in sorted(by_index):
        group = by_index[idx]
        b = group.get("baseline")
        m = group.get("mtp")
        if not b or not m:
            continue
        bm = run_metrics(b)
        mm = run_metrics(m)
        p = {
            "run_index": idx,
            "baseline_tps": bm["decode_tps"],
            "mtp_tps": mm["decode_tps"],
            "speedup": speedup(bm["decode_tps"], mm["decode_tps"]),
            "baseline_e2e_ms": bm["e2e_ms"],
            "mtp_e2e_ms": mm["e2e_ms"],
            "e2e_delta_ms": (
                mm["e2e_ms"] - bm["e2e_ms"]
                if bm["e2e_ms"] is not None and mm["e2e_ms"] is not None
                else None
            ),
            "baseline_ttft_ms": bm["ttft_ms"],
            "mtp_ttft_ms": mm["ttft_ms"],
            "baseline_tokens": bm["predicted_n"],
            "mtp_tokens": mm["predicted_n"],
            "token_delta": (
                mm["predicted_n"] - bm["predicted_n"]
                if bm["predicted_n"] is not None and mm["predicted_n"] is not None
                else None
            ),
            "acceptance_rate": mm["acceptance"]["acceptance_rate"],
        }
        pairs.append(p)

    speedups = [p["speedup"] for p in pairs]
    speedup_stats = summarise(speedups)
    median_speedup = speedup_stats["median"] if speedup_stats else None
    return {
        "baseline": baseline,
        "mtp": mtp,
        "pairs": pairs,
        "speedup": speedup_stats,
        "speedup_median": median_speedup,
        "verdict": verdict(median_speedup),
        "total_runs": len(runs),
        "failed_runs": sum(
            1 for r in runs if r.get("status") in ("failed", "interrupted")
        ),
        "cancelled_runs": sum(1 for r in runs if r.get("status") == "cancelled"),
    }


def metric_or_na(value: Any) -> Any:
    return value if value is not None else "N/A"