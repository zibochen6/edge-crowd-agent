# Edge Crowd Agent

[English](README.md) · [简体中文](README.zh-CN.md)

运行在 NVIDIA Jetson 的本地人群监控与自动处置演示：真实视频检测、区域当前人数告警、端侧 LLM 分析、本地工具，以及可追溯的 MTP OFF / ON 对照实验。

主屏固定为**左侧实时视频、右侧 LLM 分析**，适合单屏录制。页头支持 **中文 / English**，选择会保留；新一轮分析使用所选语言生成，历史报告保留原文并标注原始语言。

## 功能

- YOLO11n TensorRT FP16 + ByteTrack；GPU 推理不可用时使用同一 ONNX 的 OpenCV CPU 后端并标明降级。
- 以检测框底部中心点判断是否在归一化 ROI 内，只用区域**当前人数**触发，不用累计入区次数。
- 状态机按连续视频时间运行：默认 ≥5 人持续 1.5 秒告警，≤3 人持续 2 秒恢复，冷却 10 秒。暂停冻结计时；定位、重播、配置变更重置会话。
- 先保存不可变事件、原始抓拍和 SQLite 记录，再异步请求 LLM。模型输出精简 JSON 工具计划和三段中文或英文分析。
- 工具只写本地告警、操作员提醒和报告，不发送外部消息，不控制物理设备；有白名单、参数与事件归属校验、幂等、取消及重试。
- MTP 对照使用同一冻结事件、Prompt、Schema、采样设置，顺序运行，交替次序，至少五组有效配对；保留失败、原始 SSE 和指标来源。

## 已验证环境

Jetson AGX Orin 32GB；JetPack 6.2.1 / CUDA 12.6 / TensorRT 10.3；**uv + 系统 Python 3.10**；llama.cpp `31288c9`；含 MTP 张量的 Qwen3.5-4B Q4_K_M GGUF；已有 YOLO11n FP16 引擎及对应 ONNX。

仓库包含源码和说明，不包含模型、视频、引擎、事件数据库、抓拍及原始运行记录。请自行准备资产并配置路径；TensorRT 引擎必须兼容目标设备。当前直接执行现有引擎，无需安装 PyTorch；如需重新导出模型，可参考 [Seeed PyTorch 教程](https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners/tree/main/3-Basic-Tools-and-Getting-Started/3.5-Pytorch)。

## 在 Jetson 上启动

先安装 Git、Node.js 22 / npm 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)，保留 JetPack 自带 CUDA / TensorRT。

```sh
git clone https://github.com/zibochen6/edge-crowd-agent.git
cd edge-crowd-agent
cp .env.example .env
```

编辑 `.env`，填写实际的 `CROWD_VIDEO`、`CROWD_MODEL`、`CROWD_LLAMA`、`CROWD_ENGINE`、`CROWD_ONNX` 路径；远程访问时设置 `CROWD_PUBLIC_HOST` 为设备地址。

```sh
bash scripts/setup.sh
npm ci --prefix frontend
npm run build --prefix frontend
bash start.sh
```

打开 `http://JETSON_IP:8090`。设备本机访问使用 `http://127.0.0.1:8090`。

```sh
bash start.sh status
bash start.sh stop
.venv/bin/python scripts/check_env.py
```

环境脚本使用 `uv venv --python /usr/bin/python3.10 --system-site-packages .venv` 和 `uv sync --frozen --inexact --python /usr/bin/python3.10`，继承系统 TensorRT 绑定。不要用无关的 PyPI 包替换 JetPack 库；可通过 `PYTHON_BIN`、`UV_BIN` 指定工具路径。

停止仅清理本项目拥有的进程，保留 `data/` 中的事件和实验。

## 分别录制 OFF / ON

1. 页头选择语言，再选择 **MTP OFF**。准备自己的录屏工具，点击**开始本轮演示**。
2. 系统保留当前 ROI、人数及恢复规则，从视频 0 秒、1× 速度开始新会话；真实人数达到阈值后，只执行所选模式。
3. 本轮完成后选择 **MTP ON**，再次点击**开始本轮演示**，录制第二段。执行中锁定模式和重开按钮，避免串入另一轮结果。
4. 可点击**全屏**；桌面已检查 1280×720 至 1920×1080。项目本身不录屏。

切换界面语言不会重启视频、跟踪或正在运行的分析。下一轮演示、重播/定位、配置变更及新上传视频会使用所选语言；重试历史事件保留其冻结语言。

两次录像分别来自独立检测事件。严谨性能比较请对**同一冻结事件**运行配对实验，详见[演示指南](docs/demo-guide.md)。

## 对照实验和历史实测

**历史对照 → 查看统计与原始记录**提供各轮状态、回放与 JSON / CSV / Trace 导出。独占实测期间暂停检测计算并显示原因，结束后恢复；普通分析不暂停检测。

原验证设备、原**中文** `behavior-v3-fast` Prompt、同一冻结事件的五组配对结果（中位数）：

| 指标 | OFF | ON |
|---|---:|---:|
| 完整任务（模型加载另计） | 7.42 秒 | 4.66 秒 |
| 工具决策 | 1.95 秒 | 1.39 秒 |
| 报告生成 | 5.41 秒 | 3.24 秒 |
| 报告 Decode | 25.46 tok/s | 50.60 tok/s |
| 模型加载 | 3.56 秒 | 5.05 秒 |

优化前为 18.96 / 12.08 秒。主要减少重复工具文案生成、输入长度和报告篇幅，不应全部归因于 MTP。[汇总记录](docs/measurements/behavior-v3-fast.json)和[验收记录](docs/acceptance.md)保留测量背景；原始运行证据保留在原部署环境，未随源码公开。不同语言、模型、视频及设备需重新测量。

OFF 显式关闭 speculative decoding；ON 使用 `draft-mtp`、depth 2；两者禁用 Prompt cache，temperature 0、seed 42、单实例。预热及加载单列，采集真实 SSE 和服务端 Token/计时，校验配对请求哈希，不把 chunk 当 Token，不隐藏失败记录。

## 开发、测试和远程同步

普通电脑上的 CPU 测试不需要模型、视频或 TensorRT：

```sh
uv sync --frozen --group dev
uv run --frozen pytest -q
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

前端开发连接已有后端：

```sh
CROWD_API_URL=http://JETSON_IP:8090 npm run dev --prefix frontend
```

GitHub Actions 自动执行 Python 3.10 测试、翻译覆盖检查、Pipeline 时序检查及前端构建。`scripts/` 中真实设备测试需手动执行，会产生实际任务与事件，请先看文件说明。

远程同步：

```sh
CROWD_SSH=seeed@JETSON_IP \
CROWD_REMOTE_DIR=/home/seeed/mtp_demo/edge-crowd-agent \
bash scripts/deploy.sh
```

先在远程准备好 `.env` 和资产。同步保留远程 `.env` 与数据，不上传本地 Git 目录、虚拟环境和数据。

接口文档：`http://JETSON_IP:8090/docs`。项目包含 `backend/`、`frontend/`、`scripts/`、`tests/`、环境模板和依赖锁文件。部署问题见[故障排查](docs/troubleshooting.md)，开发约定见[CONTRIBUTING](CONTRIBUTING.md)。

当前为单视频、单 ROI、本地提醒。位移来自画面归一化跟踪，不是物理速度或动作识别；短时观察不能认定身份、意图、长期滞留、打斗、跌倒或现场安全。
