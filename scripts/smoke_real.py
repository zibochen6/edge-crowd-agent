"""Exercise the deployed real video/Agent pipeline, optionally five-pair benchmark."""
import argparse
import json
import time
import urllib.request

p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8090');p.add_argument('--benchmark',action='store_true');p.add_argument('--wait',action='store_true');args=p.parse_args()
def api(path,body=None,method='POST'):
    request=urllib.request.Request(args.url+'/api'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'},method=method if body is not None else 'GET')
    return json.load(urllib.request.urlopen(request,timeout=20))
def wait_job(jid,kind,timeout=1800):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        s=api('/status');job=next(j for j in s[kind] if j['id']==jid)
        if job['status'] not in ['queued','running']:return job
        time.sleep(2)
    raise TimeoutError(jid)
s=api('/status');original=s['video']['settings'];original_loop=s['video'].get('loop',True);before={e['event_id'] for e in s['events']}
try:
    api('/video/control',{'action':'loop','value':0})
    api('/settings',{**original,'auto_agent':False},'PUT');api('/video/control',{'action':'speed','value':4});api('/video/control',{'action':'replay'})
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        time.sleep(.5);s=api('/status')
        if s['video']['error']:raise RuntimeError(s['video']['error'])
        if not s['video']['playing'] and s['video']['time']>s['video']['duration']-.1:break
    else:raise TimeoutError('video detection')
    events=[e for e in s['events'] if e['event_id'] not in before]
    if not events:raise RuntimeError('本配置未触发真实事件；请调整 ROI 或阈值后重试')
    event=events[0];print('真实事件',event['event_id'],'ROI',event['current_count'],'时间',event['video_seconds'],flush=True)
    job=api(f'/events/{event["event_id"]}/agent',{'mode':'off'});job=wait_job(job['id'],'agent_jobs',300)
    if job['status']!='completed':raise RuntimeError(job.get('error'))
    print('真实 Agent 工具完成',job['id'],flush=True)
    if args.benchmark:
        bench=api(f'/events/{event["event_id"]}/benchmark',{});print('Benchmark',bench['id'],flush=True)
        if args.wait:
            bench=wait_job(bench['id'],'benchmarks');print(json.dumps(bench.get('summary'),ensure_ascii=False,indent=2))
            if bench['status']!='completed':raise RuntimeError(bench.get('error'))
finally:
    api('/settings',original,'PUT');api('/video/control',{'action':'speed','value':1});api('/video/control',{'action':'loop','value':int(original_loop)})

    if original_loop:api('/video/control',{'action':'replay'})
