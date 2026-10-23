# Edge Crowd Agent

[English](README.md) · [简体中文](README.zh-CN.md)

A local crowd-monitoring and response demo for NVIDIA Jetson: real video detection, current ROI occupancy alerts, an on-device LLM, validated local tools, and reproducible MTP OFF / ON experiments.

The recording console keeps **live video on the left** and **LLM analysis on the right**. Choose **中文 / English** in the header; the choice is remembered. New demo sessions generate analysis in the selected language. Existing reports remain unchanged and are marked with their original language when it differs from the interface.

## What it does

- Detects and tracks people using YOLO11n TensorRT FP16 and ByteTrack. The same ONNX model supplies an explicitly marked OpenCV CPU fallback.
- Counts the people **currently inside a normalized polygon**, using the bottom-center of each detection box. Cumulative entries never trigger an alert.
- Uses video time for `NORMAL → PENDING → ALERT → RECOVERY → NORMAL`: default count ≥5 for 1.5 s, recovery ≤3 for 2 s, cooldown 10 s.
- Saves the immutable event, original snapshot and SQLite record **before** requesting the LLM. The LLM produces a compact JSON tool plan and a short report grounded in actual counts and movement evidence.
- Executes only `create_alert`, `notify_operator` and `save_report`. These update the local console; they do not control physical equipment or send external messages.
- Supports cancellation, retries, event ownership validation and idempotency keyed by `(namespace, event_id, tool_name)`.
- Runs OFF / ON sequentially against the same frozen input, preserves failures and raw SSE, and requires five valid pairs for acceptance. Recorded replay is clearly labeled.

## Validated environment

| Component | Original validation device |
|---|---|
| Hardware | Jetson AGX Orin 32 GB |
| JetPack / CUDA / TensorRT | 6.2.1 / 12.6 / 10.3 |
| Python | **System Python 3.10**, managed with **uv** |
| LLM | Qwen3.5-4B Q4_K_M GGUF, containing MTP tensors |
| llama.cpp | `31288c9`, built with CUDA and `draft-mtp` support |
| Detection | Existing YOLO11n TensorRT FP16 engine + matching ONNX |
| Input video | 1920×1080, 25 FPS, 341 frames |

Model weights, inference engines, videos, event databases, snapshots and raw runtime traces are **not included**. Configure your own assets; TensorRT engines must match the target Jetson / TensorRT environment. This project runs the existing engine directly and does not require PyTorch for inference. PyTorch installation, if needed for model export, is covered by the [Seeed Jetson tutorial](https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners/tree/main/3-Basic-Tools-and-Getting-Started/3.5-Pytorch).

## Start on Jetson

Install Git, Node.js 22 with npm, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Keep the device's JetPack CUDA / TensorRT installation.

```sh
git clone https://github.com/zibochen6/edge-crowd-agent.git
cd edge-crowd-agent
cp .env.example .env
```

Edit `.env`: set `CROWD_VIDEO`, `CROWD_MODEL`, `CROWD_LLAMA`, `CROWD_ENGINE` and `CROWD_ONNX` to your actual files. Set `CROWD_PUBLIC_HOST` to your Jetson address when accessing it remotely.

```sh
bash scripts/setup.sh
npm ci --prefix frontend
npm run build --prefix frontend
bash start.sh
```

Open `http://JETSON_IP:8090`. On the Jetson itself, use `http://127.0.0.1:8090`.

```sh
bash start.sh status
bash start.sh stop
```

Stop only cleans up this project's owned processes; saved data stays in `data/`.

The setup script uses `uv venv --python /usr/bin/python3.10 --system-site-packages .venv` and `uv sync --frozen --inexact --python /usr/bin/python3.10`. Use **system Python**, so the environment can import Debian's TensorRT bindings. Do not replace JetPack libraries with unrelated PyPI packages. `PYTHON_BIN` and `UV_BIN` can override tool locations.

Read-only environment checks:

```sh
.venv/bin/python scripts/check_env.py
```

## Record OFF and ON

1. Select a language in the header. Choose **MTP OFF**, prepare your recorder, then click **Start demo**.
2. The current ROI and rules are preserved. Detection starts at video time zero, at 1× speed, in a new session. An actual count alert triggers the selected LLM mode.
3. Once the run finishes, select **MTP ON** and start a new demo for the second recording. The mode and restart controls are locked while a task runs.
4. Use **Fullscreen** if needed. Desktop layouts were checked from 1280×720 to 1920×1080. The project does not record your screen.

The two recordings use separate real detection events. For rigorous speed comparisons, run a **benchmark on one frozen event**, not two independent demos. See [demo guide](docs/demo-guide.en.md).

Language switching itself does not restart playback, tracking or ongoing generation. New demo, replay, seek, region/rule changes and uploaded videos use the selected language for new events. Retrying a historical event preserves its frozen language.

## Benchmarks and measured latency

**History → Statistics & raw records** provides experiments, all attempts, JSON / CSV / Trace export and raw-timestamp replay. A benchmark pauses detection computation to give the LLM exclusive access, then resumes it; normal response tasks do not pause detection.

For the original **Chinese** `behavior-v3-fast` prompt, five valid pairs on the same frozen event produced these medians:

| Metric | MTP OFF | MTP ON |
|---|---:|---:|
| Complete task, excluding model loading | 7.42 s | 4.66 s |
| Tool decision | 1.95 s | 1.39 s |
| Report generation | 5.41 s | 3.24 s |
| Report decode | 25.46 tok/s | 50.60 tok/s |
| Model loading, separate | 3.56 s | 5.05 s |

The earlier longer workflow took 18.96 / 12.08 s. The reduction comes from shorter inputs, a compact tool plan and a concise report; it is not solely an MTP speedup. These are historical measurements, not a guarantee for another language, model, video or device. [Aggregate records](docs/measurements/behavior-v3-fast.json) and [validation notes](docs/acceptance.md) describe the experiment. Raw runtime evidence remains with the original deployment; generate your own traces to reproduce results.

OFF uses `--spec-type none`; ON uses `--spec-type draft-mtp --spec-draft-n-max 2`. Both disable prompt cache, use temperature 0 / seed 42, one slot and the same model. Experiments alternate OFF→ON / ON→OFF, restart and warm up each mode, and verify paired request hashes. Token counts and decode / acceptance metrics come from server data, never from counting SSE chunks. Shorter output is not presented as higher decoding throughput.

## Development and tests

Portable CPU tests do not need a model, video, TensorRT or Jetson:

```sh
uv sync --frozen --group dev
uv run --frozen pytest -q
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

On a development computer, point Vite at a running backend:

```sh
CROWD_API_URL=http://JETSON_IP:8090 npm run dev --prefix frontend
```

GitHub Actions checks Python 3.10 tests, localization coverage, Pipeline trace behavior, TypeScript and the production build. Real-device smoke tests in `scripts/` are opt-in and may create tasks, events and experiments; see their docstrings.

Optional remote synchronization (configure the target first):

```sh
CROWD_SSH=seeed@JETSON_IP \
CROWD_REMOTE_DIR=/home/seeed/mtp_demo/edge-crowd-agent \
bash scripts/deploy.sh
```

The deploy script preserves the remote `.env` and runtime data and excludes the local Git directory and virtual environments. Provision `.env` and assets on the remote device before the first deployment.

## Project structure

```text
backend/             FastAPI, video worker, tracking, events, Agent and benchmarks
frontend/src/        React / TypeScript recording console and translations
scripts/             Setup, owned service lifecycle, preflight and real-device checks
tests/               Portable backend tests
.github/workflows/   CPU tests and frontend build
.env.example         Asset paths and service configuration template
uv.lock              Locked Python dependencies
```

API documentation: `http://JETSON_IP:8090/docs`. Core routes: `/api/status`, `/api/demo/start`, `/api/video/control`, `/api/settings`, `/api/events/{event_id}`, `/api/benchmarks/*` and `/ws`. WebSocket previews contain a JPEG and metadata from the same real frame; every source frame is processed, while preview delivery is limited to about 10 Hz for remote responsiveness.

This is a single-video, single-region local demo. Movement is based on normalized tracked displacement, not physical speed or action recognition. Brief observations cannot establish identity, intent, prolonged loitering, fighting, falling or scene safety. See [troubleshooting](docs/troubleshooting.md) and [contributing](CONTRIBUTING.md).
