"""Opt-in real-device test: interrupt ONLY a verified child llama-server.

Run on the Jetson after the normal benchmark; creates failed/cancelled test jobs.
"""
import json
import os
from pathlib import Path
import signal
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from backend.process import is_owned,read_proc_cmdline,read_proc_starttime

BASE='http://127.0.0.1:8090/api'
def api(path,body=None,method='POST'):
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method if body is not None else 'GET')
    return json.load(urllib.request.urlopen(req,timeout=15))
def wait_for(predicate,timeout=90):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        value=predicate()
        if value:return value
        time.sleep(.2)
    raise TimeoutError('real fault verification timed out')
def find_job(jid):return next(j for j in api('/status')['agent_jobs'] if j['id']==jid)
def active_request(jid):
    p=ROOT/'data/agent'/jid/'decision-trace.jsonl'
    return p.exists() and p.stat().st_size>0

initial=api('/status');original=initial['video']['settings'];eid=initial['events'][0]['event_id']
if any(j['status'] in ['queued','running'] for j in initial['benchmarks']):raise SystemExit('先等待 Benchmark 完成')
if initial['agent_busy']:raise SystemExit('先等待 Agent 空闲')
result={}
try:
    api('/settings',{**original,'auto_agent':False,'enabled':False},'PUT')
    for phase in ['disconnect','cancel']:
        api('/video/control',{'action':'speed','value':1});api('/video/control',{'action':'replay'})
        jid=api('/events/'+eid+'/agent',{'mode':'off'})['id']
        wait_for(lambda:active_request(jid))
        before=api('/status')['video'];backend=json.loads((ROOT/'data/service.json').read_text())
        assert is_owned(backend['pid'],backend['starttime'])
        children=[]
        for path in Path('/proc').glob('[0-9]*'):
            try:
                raw=(path/'stat').read_text();parent=int(raw.rsplit(')',1)[1].split()[1]);cmd=read_proc_cmdline(int(path.name))
                if parent==backend['pid'] and Path(cmd.split()[0]).name=='llama-server':children.append(int(path.name))
            except (OSError,ValueError,IndexError):pass
        assert len(children)==1,children
        pid=children[0];starttime=read_proc_starttime(pid)
        if phase=='disconnect':
            assert is_owned(pid,starttime)
            os.kill(pid,signal.SIGTERM)
        else:api('/agent/'+jid+'/cancel',{})
        terminal=wait_for(lambda:(j if (j:=find_job(jid))['status'] not in ['queued','running'] else None),20)
        time.sleep(1)
        after=api('/status')['video']
        assert terminal['status']==('failed' if phase=='disconnect' else 'cancelled'),terminal
        assert after['session_id']==before['session_id'] and after['time']>before['time']+.2
        assert not is_owned(pid,starttime)
        assert api('/events/'+eid)['event_id']==eid
        result[phase]={'job_id':jid,'status':terminal['status'],'error':terminal.get('error'),'before_video_seconds':before['time'],'after_video_seconds':after['time'],'owned_llama_pid':pid,'owned_llama_starttime':starttime,'video_continued':True,'event_preserved':True,'process_exited':True}
        print(json.dumps({phase:result[phase]},ensure_ascii=False),flush=True)
finally:
    api('/video/control',{'action':'pause'});api('/settings',original,'PUT')
    (ROOT/'data/fault-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
