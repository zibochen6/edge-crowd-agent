# Troubleshooting / 故障排查

| Symptom / 问题 | Check / 检查 |
|---|---|
| TensorRT import fails / 无法导入 | Use `/usr/bin/python3.10` and a uv environment with `--system-site-packages`; run `bash scripts/setup.sh`. Keep JetPack libraries. 使用系统 Python，保留 JetPack 库。 |
| No video/model / 无资产 | Copy `.env.example` to `.env`; configure actual readable `CROWD_VIDEO`, `CROWD_MODEL`, `CROWD_LLAMA`, `CROWD_ENGINE` and `CROWD_ONNX` files. Run `scripts/check_env.py`. |
| TensorRT engine fails / 引擎不兼容 | Use an engine built for the device's TensorRT/GPU. The matching ONNX enables the labeled CPU fallback. 使用兼容引擎或同一 ONNX 的 CPU 降级。 |
| MTP start fails / MTP 启动失败 | Verify llama.cpp supports `draft-mtp` and the GGUF has MTP tensors; inspect the task's `server.log`. Do not replace a missing MTP implementation with a fake speedup. |
| External LLM detected / 发现外部模型 | Wait for the unrelated instance to exit or stop it yourself. This project only stops processes it owns. |
| Port occupied / 端口冲突 | Set a free `CROWD_PORT`; the service refuses to kill an unknown owner. |
| Cannot connect / 网络不通 | Use your device's reachable address and configured port. Local development defaults to `127.0.0.1`; set `CROWD_API_URL` when using Vite remotely. |
| English interface, Chinese old report / 界面英文但旧报告中文 | Historical reports remain original. Select English and start a **new demo** for a new English report. 已有事件不会被静默改写。 |
| Count changes but no new report / 循环未重复分析 | Automatic looping reuses the same short-clip event. Start a new demo, replay manually, or change the region/rules for a fresh session. |
| Video pauses during benchmark / 实验时视频暂停 | Expected: fair experiments temporarily hold detection computation. It resumes after the experiment. Normal analysis keeps detection running. |
| Longer latency / 时延较长 | Model loading is separate from task time. Current video load, report language/length, model and hardware affect latency. Compare frozen inputs and inspect raw server timings. |

`data/service.log` holds backend logs. `data/agent/<id>/` and `data/benchmarks/<id>/` hold requests, outputs, command lines and traces. `data/crowd.sqlite` holds persisted events/jobs/tool receipts. Stopping the service preserves these files.

The dashboard is intended for a trusted local network and has no built-in authentication. Place it behind authentication before exposing it beyond that environment. / 页面用于可信本地网络；如需对外开放，请先配置访问认证。
