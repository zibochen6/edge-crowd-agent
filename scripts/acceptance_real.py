"""Run the default video with automatic real Agent handling; record evidence."""
import json
from pathlib import Path
import time
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
BASE='http://127.0.0.1:8090/api'
def api(path,body=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=15))

initial=api('/status');before={e['event_id'] for e in initial['events']}
assert initial['video']['settings']['auto_agent'] and initial['video']['settings']['enabled']
assert not initial['agent_busy']
try:
    api('/video/control',{'action':'loop','value':0});api('/video/control',{'action':'speed','value':1});api('/video/control',{'action':'replay'})
    observations=[];event=None;job=None;deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        s=api('/status');video=s['video']
        if video['error']:raise RuntimeError(video['error'])
        new=[e for e in s['events'] if e['event_id'] not in before]
        if new:
            event=new[0];job=next((j for j in s['agent_jobs'] if j['event_id']==event['event_id']),None)
        observations.append({'wall_time':time.time(),'video_seconds':video['time'],'playing':video['playing'],'agent_status':job['status'] if job else None})
        if job and job['status'] in ['failed','cancelled','interrupted']:raise RuntimeError(job.get('error'))
        if job and job['status']=='completed' and not video['playing'] and video['time']>video['duration']-.1:break
        time.sleep(.25)
    else:raise TimeoutError('automatic pipeline')
    session=event['session_id'];records=[json.loads(x) for x in (ROOT/'data/sessions'/session/'frames.jsonl').read_text().splitlines()]
    detail=api('/events/'+event['event_id']);during=[o['video_seconds'] for o in observations if o['agent_status']=='running' and o['playing']]
    assert len(records)==341
    assert len([e for e in s['events'] if e['session_id']==session])==1
    assert len(during)>2 and max(during)-min(during)>1
    assert {t['name'] for t in detail['tools'] if t['state']=='completed'}=={'create_alert','notify_operator','save_report'}
    assert (ROOT/'data/snapshots'/f'{event["event_id"]}.jpg').is_file()
    assert (ROOT/'data/reports/production'/f'{event["event_id"]}.md').is_file()
    result={'event_id':event['event_id'],'agent_job_id':job['id'],'session_id':session,'frames':len(records),'event_count':1,'video_source':video['source'],'config':video['settings'],'max_full_count':max(r['full_count'] for r in records),'max_roi_count':max(r['roi_count'] for r in records),'mean_detection_ms':sum(r['detection_ms'] for r in records)/len(records),'video_advanced_while_llm_running_seconds':max(during)-min(during),'tools':detail['tools'],'agent_result':job['result'],'observations':observations,'accepted':True}
    (ROOT/'data/automatic-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ['observations','agent_result','tools','config']},ensure_ascii=False),flush=True)
finally:
    api('/video/control',{'action':'loop','value':int(initial['video'].get('loop',True))})
    if initial['video'].get('loop',True):api('/video/control',{'action':'replay'})
