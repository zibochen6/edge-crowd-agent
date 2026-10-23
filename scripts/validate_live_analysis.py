"""Verify actual video/LLM continuity and optionally start a fresh paired experiment."""
import json,time,urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8090/api'
def request(path,body=None):
    req=urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
def status():return request('/status')
start=time.time();initial=status();observations=[]
while time.time()-start<180:
    s=status();eid=s['video'].get('latest_event_id')
    event=next((e for e in s['events'] if e['event_id']==eid and e.get('behavior_evidence')),None)
    if event:break
    time.sleep(1)
else:raise RuntimeError('No real event with behavior evidence')
for mode in ['off','on']:
    jobs=[j for j in s['agent_jobs'] if j['event_id']==eid and j['mode']==mode]
    job=jobs[0] if jobs else request(f'/events/{eid}/agent',{'mode':mode})
    while time.time()-start<240:
        s=status();current=next(j for j in s['agent_jobs'] if j['id']==job['id'])
        observations.append({'t':time.time(),'video':{k:s['video'].get(k) for k in ['time','session_id','loop_cycle','playing','latest_event_id']},'mode':mode,'status':current['status']})
        if current['status'] not in ['running','queued']:break
        time.sleep(1)
    assert current['status']=='completed',current
    text=current['result']['report']
    assert all(title in text for title in (['Assessment','Dwell and movement','Response'] if event.get('settings',{}).get('report_language')=='en' else ['异常判断','停留与移动分析','处置建议'])),text
    assert not any(v in text for v in ['ROI','Tracking','create_alert','save_report',eid,'正常移动状态','风险解除','现场恢复正常','未发生长时间滞留']),text
    print(json.dumps({'mode':mode,'job_id':current['id'],'event':eid,'report':text},ensure_ascii=False),flush=True)
s=status();assert s['video']['playing'] and s['video']['loop_cycle']>=2
assert len([j for j in s['agent_jobs'] if j['event_id']==eid])==2,'Loop queued duplicate analysis jobs'
result={'event':event,'jobs':[{k:j.get(k) for k in ['id','mode','status','result']} for j in s['agent_jobs'] if j['event_id']==eid],'observations':observations,'passed':True}
if '--benchmark' in __import__('sys').argv:
    result['benchmark']=request(f'/events/{eid}/benchmark',{})
Path('data/live-analysis-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':True,'event':eid,'benchmark':result.get('benchmark',{}).get('id'),'loop_cycle':s['video']['loop_cycle']},ensure_ascii=False),flush=True)
