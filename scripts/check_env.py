"""Read-only preflight. Use --cpu for development without Jetson assets."""
import argparse
import importlib
import importlib.metadata
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root))
# Match the simple KEY=value / quoted paths in .env.example without executing it.
if (root/'.env').is_file():
    for line in (root/'.env').read_text().splitlines():
        stripped=line.strip().removeprefix('export ')
        if not stripped or stripped.startswith('#') or '=' not in stripped:continue
        key,value=stripped.split('=',1);words=shlex.split(value,comments=True)
        if len(words)==1:os.environ.setdefault(key.strip(),words[0])
from backend import config
parser=argparse.ArgumentParser()
parser.add_argument('--cpu',action='store_true',help='Check portable dependencies only')
args=parser.parse_args()
checks=[]
def check(name,ok,detail):checks.append({'name':name,'ok':bool(ok),'detail':str(detail)})
check('Python 3.10',sys.version_info[:2]==(3,10),sys.version.split()[0])
check('uv',shutil.which('uv'),shutil.which('uv') or 'Install uv and add it to PATH')
for module in ['fastapi','uvicorn','pydantic','httpx','cv2','numpy','supervision']:
    try:
        loaded=importlib.import_module(module);check(module,True,getattr(loaded,'__version__','import OK'))
    except Exception as exc:check(module,False,exc)
if not args.cpu:
    for name,value in [('video',config.VIDEO),('GGUF model',config.MODEL),('llama-server',config.LLAMA)]:check(name,value.is_file(),value)
    check('detector engine or ONNX',config.ENGINE.is_file() or config.ONNX.is_file(),f'{config.ENGINE} | {config.ONNX}')
    try:
        import tensorrt
        check('TensorRT',True,tensorrt.__version__)
    except ImportError:check('TensorRT',False,'Use Jetson system Python 3.10 with --system-site-packages; ONNX CPU fallback remains available')
print(json.dumps({'passed':all(c['ok'] for c in checks),'scope':'CPU development' if args.cpu else 'Jetson deployment','checks':checks},ensure_ascii=False,indent=2))
sys.exit(0 if all(c['ok'] for c in checks) else 1)
