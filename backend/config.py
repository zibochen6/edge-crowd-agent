import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv('CROWD_DATA', str(ROOT / 'data')))
ASSETS = Path(os.getenv('CROWD_ASSETS', '/home/seeed/mtp_demo'))
VIDEO = Path(os.getenv('CROWD_VIDEO', str(ASSETS / 'people-walking.mp4')))
MODEL = Path(os.getenv('CROWD_MODEL', str(ASSETS / 'models/Qwen3.5-4B-Q4_K_M.gguf')))
LLAMA = Path(os.getenv('CROWD_LLAMA', '/home/seeed/llama.cpp/build/bin/llama-server'))
DETECTION = Path(os.getenv('CROWD_DETECTION', '/home/seeed/workspace/mobile_robot_ws/modules/m04-ai-vision-and-edge-acceleration/models/m4/detection'))
ENGINE = Path(os.getenv('CROWD_ENGINE', str(DETECTION / 'engines/yolo11n_fp16.engine')))
ONNX = Path(os.getenv('CROWD_ONNX', str(DETECTION / 'onnx/yolo11n.onnx')))
PORT = int(os.getenv('CROWD_PORT', '8090'))

def initialize():
    for name in ['', 'snapshots', 'reports', 'benchmarks', 'sessions', 'agent', 'uploads']:
        (DATA / name).mkdir(parents=True, exist_ok=True)
