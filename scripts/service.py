import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from backend.process import read_proc_starttime, is_owned,read_proc_cmdline
path=ROOT/'data'/'service.json';path.parent.mkdir(parents=True,exist_ok=True)
action=sys.argv[1] if len(sys.argv)>1 else 'start'
record=json.loads(path.read_text()) if path.exists() else None
alive=record and is_owned(record['pid'],record['starttime']) and 'backend.main' in read_proc_cmdline(record['pid'])
if action=='stop':
    if alive:
        os.kill(record['pid'],signal.SIGTERM)
        for _ in range(150):
            if not is_owned(record['pid'],record['starttime']) or not read_proc_cmdline(record['pid']):break
            time.sleep(.1)
        else:
            if is_owned(record['pid'],record['starttime']) and 'backend.main' in read_proc_cmdline(record['pid']):
                os.kill(record['pid'],signal.SIGKILL)
                print('已强制停止本项目拥有的后端进程。')
    path.unlink(missing_ok=True);print('Edge Crowd Agent 已停止；数据保留。')
elif action=='status':print(json.dumps({'running':bool(alive),'process':record},ensure_ascii=False))
elif alive:print('Edge Crowd Agent 已在运行。')
else:
    import socket
    port=os.environ.get('CROWD_PORT','8090')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',int(port)))==0:raise SystemExit(f'端口 {port} 被其他服务占用；未停止未知进程。')
    with open(ROOT/'data'/'service.log','ab',buffering=0) as log:
        proc=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','backend.main'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    time.sleep(.1)
    path.write_text(json.dumps({'pid':proc.pid,'starttime':read_proc_starttime(proc.pid)}))
    from urllib.request import urlopen
    for _ in range(100):
        if proc.poll() is not None:raise SystemExit((ROOT/'data/service.log').read_text()[-3000:])
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/status',timeout=1) as r:
                if r.status==200:print(f'Edge Crowd Agent 已启动：http://{os.environ.get("CROWD_PUBLIC_HOST","127.0.0.1")}:{port}');break
        except OSError:pass
        time.sleep(.2)
    else:raise SystemExit('启动健康检查超时，请查看 data/service.log')
