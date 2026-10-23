# Contributing

Use Python 3.10 with uv and Node.js 22 (or a compatible Node.js release).

```sh
uv sync --frozen --group dev
uv run --frozen pytest -q
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

CPU tests use temporary data and do not require TensorRT, CUDA, model weights, a video or a running Jetson. Actual inference and benchmark acceptance require a Jetson and separately configured assets. On Jetson, follow the system Python / TensorRT instructions in the README.

Add both Chinese and English messages for interface changes. Language switching must preserve video playback, event identity and ongoing tasks. Keep old reports and benchmark traces in their original language; never fabricate translations or timings.

Do not commit `.env`, credentials, model weights, videos, snapshots, event databases, machine-specific configuration or generated runtime traces. Use separate benchmark namespaces, preserve failed attempts, and verify request hashes before comparing OFF and ON.
