from fastapi.testclient import TestClient
from backend import config
from backend.main import app,Bus
from backend.video import VideoService
import json

def test_api_validates_input_and_persists_rules(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(VideoService,'start',lambda self:None)
    monkeypatch.setattr(VideoService,'close',lambda self:None)
    with TestClient(app) as client:
        assert client.get('/api/status').status_code==200
        settings=client.get('/api/status').json()['video']['settings']
        assert client.put('/api/settings',json={**settings,'threshold':3}).status_code==422
        assert client.post('/api/video/control',json={'action':'speed','value':9}).status_code==400
        assert client.post('/api/video/upload',files={'file':('bad.txt',b'bad','text/plain')}).status_code==400
        assert client.post('/api/video/upload',files={'file':('bad.mp4',b'bad','video/mp4')}).status_code==400
        assert not list((tmp_path/'uploads').glob('*'))
        assert client.get('/api/events/missing').status_code==404
        assert client.put('/api/settings',json={**settings,'polygon':[]}).status_code==200
        assert client.get('/api/status').json()['video']['settings']['polygon']==[]

def test_event_overlay_uses_exact_frozen_frame_and_checks_its_counts(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(VideoService,'start',lambda self:None)
    monkeypatch.setattr(VideoService,'close',lambda self:None)
    with TestClient(app) as client:
        event={'event_id':'event-test','session_id':'session-test','video_seconds':1.6,'current_count':1,'track_ids':[8]}
        app.state.store.save_event(event)
        folder=tmp_path/'sessions'/'session-test';folder.mkdir(parents=True)
        rows=[{'frame':39,'video_seconds':1.56,'roi_count':2,'track_ids':[7,8],'tracks':[]},
              {'frame':40,'video_seconds':1.6,'roi_count':1,'track_ids':[8],'tracks':[{'id':8,'box':[.1,.1,.5,.6],'confidence':.8}]}]
        path=folder/'frames.jsonl';path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        result=client.get('/api/events/event-test/detection')
        assert result.status_code==200
        assert result.json()['frame']==40 and result.json()['tracks'][0]['id']==8
        rows[-1]['roi_count']=99
        path.write_text(json.dumps(rows[-1])+'\n')
        assert client.get('/api/events/event-test/detection').status_code==409
        path.unlink()
        assert client.get('/api/events/event-test/detection').status_code==404

async def test_slow_client_queue_does_not_block_publisher():
    import asyncio
    bus=Bus();queue=asyncio.Queue(maxsize=4);bus.clients.add(queue)
    for i in range(100):bus.deliver({'seq':i})
    assert queue.qsize()==4
    assert (await queue.get())['seq']==96

async def test_final_video_frame_is_not_evicted_by_token_burst():
    import asyncio
    bus=Bus();queue=asyncio.Queue(maxsize=4);bus.clients.add(queue)
    bus.deliver({'type':'frame','frame':340})
    for i in range(100):bus.deliver({'type':'token','seq':i})
    pending=[queue.get_nowait() for _ in range(queue.qsize())]
    assert any(v.get('frame')==340 for v in pending)
    for i in range(100):bus.deliver({'type':'frame','frame':i})
    assert queue.qsize()==1 and (await queue.get())['frame']==99

def test_recording_demo_rewinds_and_switches_mode_without_changing_roi_rules(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(VideoService,'start',lambda self:None)
    monkeypatch.setattr(VideoService,'close',lambda self:None)
    monkeypatch.setattr('backend.main.foreign_llama',lambda:[])
    with TestClient(app) as client:
        original=client.get('/api/status').json()['video']['settings']
        configured={**original,'polygon':[[.1,.2],[.8,.2],[.6,.9]],'trigger_seconds':2.5,'enabled':False,'auto_agent':False}
        client.put('/api/settings',json=configured)
        video=app.state.video
        for mode in ['off','on']:
            video.video_time=9;video.speed=2;video.playing=False
            video.latest_event_id='previous';video.loop_events={40:'previous'};video.latest={'old':True}
            before=video.version
            response=client.post('/api/demo/start',json={'mode':mode})
            assert response.status_code==200
            v=response.json()
            assert v['settings']=={**configured,'mode':mode,'enabled':True,'auto_agent':True}
            assert video.pending_reset==0 and v['speed']==1 and v['playing'] and v['loop']
            assert video.version==before+1 and not v['ready'] and v['latest_event_id'] is None
            assert not video.loop_events and v['loop_cycle']==1
        assert client.post('/api/demo/start',json={'mode':'fake'}).status_code==422

def test_recording_demo_rejects_busy_or_foreign_llama_without_mutation(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(VideoService,'start',lambda self:None)
    monkeypatch.setattr(VideoService,'close',lambda self:None)
    monkeypatch.setattr('backend.main.foreign_llama',lambda:[123])
    with TestClient(app) as client:
        before=app.state.video.status()
        assert client.post('/api/demo/start',json={'mode':'on'}).status_code==409
        assert app.state.video.status()==before
        monkeypatch.setattr('backend.main.foreign_llama',lambda:[])
        app.state.engine.bench_pending=True
        assert client.post('/api/demo/start',json={'mode':'on'}).status_code==409
        app.state.engine.bench_pending=False
        app.state.store.save_job({'id':'queued-test','event_id':'old','mode':'off','status':'queued'},'agent')
        assert client.post('/api/demo/start',json={'mode':'on'}).status_code==409
        assert app.state.video.status()==before

def test_new_analysis_language_is_frozen_and_invalid_actions_do_not_mutate_it(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(VideoService,'start',lambda self:None)
    monkeypatch.setattr(VideoService,'close',lambda self:None)
    monkeypatch.setattr('backend.main.foreign_llama',lambda:[])
    with TestClient(app) as client:
        video=app.state.video;video.duration=13.64
        result=client.post('/api/demo/start',json={'mode':'on','report_language':'en'})
        assert result.status_code==200 and result.json()['settings']['report_language']=='en'
        before=video.status()
        assert client.post('/api/video/control',json={'action':'seek','value':99,'report_language':'zh'}).status_code==400
        assert video.status()==before
        assert client.post('/api/demo/start',json={'mode':'on','report_language':'xx'}).status_code==422
        # Pausing or resuming preserves the already-frozen analysis language.
        client.post('/api/video/control',json={'action':'pause','report_language':'zh'})
        assert video.settings.report_language=='en'
        result=client.post('/api/video/control',json={'action':'replay','report_language':'zh'})
        assert result.json()['settings']['report_language']=='zh' and video.pending_reset==0
