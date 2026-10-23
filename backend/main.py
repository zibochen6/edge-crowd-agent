import asyncio
import io
import json
import re
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel,Field
from . import config
from .domain import Settings
from .storage import Store
from .video import VideoService
from .agent import AgentEngine,foreign_llama
from . import benchmark

class Bus:
    def __init__(self):self.clients=set();self.loop=asyncio.get_running_loop()
    def publish(self,item):self.loop.call_soon_threadsafe(self.deliver,item)
    def deliver(self,item):
        for q in self.clients:
            pending=[]
            while not q.empty():pending.append(q.get_nowait())
            if item.get('type')=='frame':pending=[v for v in pending if v.get('type')!='frame']
            pending.append(item)
            while len(pending)>q.maxsize:
                discard=next((i for i,v in enumerate(pending) if v.get('type') not in ['frame','event']),0)
                pending.pop(discard)
            for value in pending:q.put_nowait(value)

@asynccontextmanager
async def lifespan(app):
    config.initialize();store=Store();bus=Bus()
    video=VideoService(store,bus.publish,lambda e,m:bus.loop.call_soon_threadsafe(app.state.engine.enqueue,e,m))
    engine=AgentEngine(store,video,bus.publish)
    app.state.store=store;app.state.bus=bus;app.state.video=video;app.state.engine=engine
    video.start()
    yield
    await engine.close();await asyncio.to_thread(video.close);store.db.close()

app=FastAPI(title='Edge Crowd Agent',lifespan=lifespan)
app.add_middleware(GZipMiddleware,minimum_size=1000)

def safe_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise HTTPException(400,'无效标识符')
    return value
def get_event(eid):
    try:return app.state.store.event(safe_id(eid))
    except KeyError:raise HTTPException(404,'事件不存在')
def get_job(jid,kind):
    for j in app.state.store.jobs(kind):
        if j['id']==safe_id(jid):return j
    raise HTTPException(404,'任务不存在')

@app.get('/api/status')
async def status(compact:bool=False):
    events=app.state.store.events();jobs=app.state.store.jobs('agent');benchmarks=app.state.store.jobs('benchmark')
    if compact:
        events=[{k:v for k,v in e.items() if k not in ['count_history']} for e in events]
        benchmarks=[{k:v for k,v in b.items() if k!='environment'} for b in benchmarks]
    return {'video':app.state.video.status(),'events':events,'agent_jobs':jobs,'benchmarks':benchmarks,'foreign_llama':foreign_llama(),'agent_busy':app.state.engine.lock.locked(),'tool_calling':'JSON Schema + validated backend dispatch','model':'Qwen3.5-4B Q4_K_M','hardware':'Jetson AGX Orin 32GB'}

class Control(BaseModel):
    action:Literal['play','pause','speed','replay','rerun','seek','loop']
    value:float|None=None
    report_language:Literal['zh','en']|None=None
@app.post('/api/video/control')
async def control(body:Control):
    if app.state.video.closed:raise HTTPException(503,app.state.video.error or '视频 worker 已退出')
    try:
        video=app.state.video
        with video.lock:
            # Validate before changing language; an invalid seek/speed must not reset a session.
            if body.action=='seek' and (body.value is None or not 0<=body.value<video.duration):raise ValueError('定位超出视频范围')
            if body.action in ['replay','rerun','seek'] and body.report_language and body.report_language!=video.settings.report_language:
                video.configure(video.settings.model_copy(update={'report_language':body.report_language}))
            return video.control(body.action,body.value)
    except ValueError as exc:raise HTTPException(400,str(exc))
@app.put('/api/settings')
async def settings(body:Settings):return app.state.video.configure(body)
@app.post('/api/video/upload')
async def upload(file:UploadFile,report_language:Literal['zh','en']|None=Form(None)):
    if not (file.filename or '').lower().endswith('.mp4'):raise HTTPException(400,'只接受 MP4')
    path=config.DATA/'uploads'/f'{uuid.uuid4().hex}.mp4';total=0
    try:
        with open(path,'wb') as out:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if total>1024**3:raise HTTPException(413,'视频上限 1 GiB')
                out.write(chunk)
        await asyncio.to_thread(app.state.video.load,path,report_language)
    except ValueError as exc:
        path.unlink(missing_ok=True);raise HTTPException(400,str(exc))
    except BaseException:path.unlink(missing_ok=True);raise
    finally:await file.close()
    return app.state.video.status()
@app.get('/api/events/{eid}')
async def event(eid:str):
    e=get_event(eid)
    with app.state.store.lock:ack=app.state.store.db.execute('SELECT at FROM acknowledgements WHERE event_id=?',(eid,)).fetchone()
    return {**e,'tools':app.state.store.tool_rows(eid),'acknowledged_at':ack[0] if ack else None}
class AgentRequest(BaseModel):mode:Literal['off','on']='off'
class DemoRequest(AgentRequest):report_language:Literal['zh','en']='zh'
@app.post('/api/demo/start')
async def demo_start(body:DemoRequest):
    engine=app.state.engine;video=app.state.video
    if video.closed:raise HTTPException(503,video.error or '视频 worker 已退出')
    if engine.lock.locked() or engine.bench_pending or any(j['status'] in ['queued','running'] for j in app.state.store.jobs('agent')):
        raise HTTPException(409,'请等待当前处置或实验完成，再开始新一轮演示')
    if foreign_llama():raise HTTPException(409,'外部 llama 正在运行，请待其退出后开始演示')
    if not video.settings.polygon:raise HTTPException(400,'请先设置监控区域')
    return video.start_demo(body.mode,body.report_language)
@app.post('/api/events/{eid}/agent')
async def agent(eid:str,body:AgentRequest):return app.state.engine.enqueue(get_event(eid),body.mode)
@app.post('/api/events/{eid}/ack')
async def ack(eid:str):
    get_event(eid)
    with app.state.store.lock,app.state.store.db:app.state.store.db.execute('INSERT OR REPLACE INTO acknowledgements VALUES(?,?)',(eid,time.time()))
    return {'event_id':eid,'status':'acknowledged'}
@app.get('/api/events/{eid}/detection')
async def event_detection(eid:str):
    e=get_event(eid)
    def read_record():
        path=config.DATA/'sessions'/safe_id(e['session_id'])/'frames.jsonl'
        if path.is_file():
            with path.open() as f:
                for line in f:
                    row=json.loads(line)
                    if abs(row['video_seconds']-e['video_seconds'])>1e-6:continue
                    if row['roi_count']!=e['current_count'] or sorted(row['track_ids'])!=sorted(e['track_ids']):
                        raise HTTPException(409,'事件与逐帧检测依据不一致')
                    return {k:row[k] for k in ['frame','video_seconds','roi_count','track_ids','tracks']}
        raise HTTPException(404,'该事件的逐帧检测记录不可用')
    return {'event_id':eid,'source':'recorded_frame',**await asyncio.to_thread(read_record)}
@app.post('/api/agent/{jid}/cancel')
async def cancel(jid:str):return {'cancelled':await app.state.engine.cancel(safe_id(jid))}
@app.post('/api/events/{eid}/benchmark')
async def bench(eid:str):
    if app.state.engine.bench_pending:raise HTTPException(409,'实验已在运行')
    if foreign_llama():raise HTTPException(409,'外部 llama 正在运行，请待其退出后重试')
    return benchmark.start(app.state.engine,get_event(eid))
@app.post('/api/benchmarks/{jid}/cancel')
async def cancel_bench(jid:str):
    job=get_job(jid,'benchmark')
    if job['status'] in ['queued','running'] and app.state.engine.benchmark_task:app.state.engine.benchmark_task.cancel()
    return {'status':'cancel_requested'}
@app.get('/api/benchmarks/{jid}')
async def benchmark_detail(jid:str):return get_job(jid,'benchmark')
@app.get('/api/benchmarks/{jid}/replay')
async def replay(jid:str,pair:int=1):
    job=get_job(jid,'benchmark');result={}
    for run in job['runs']:
        if run['pair']!=pair or run['status']!='completed':continue
        folder=config.DATA/'benchmarks'/jid/run['run_id'];trace=[]
        for stage in ['decision','report']:
            with open(folder/f'{stage}-trace.jsonl') as f:
                for line in f:
                    row=json.loads(line)
                    if row['data']=='[DONE]':continue
                    obj=json.loads(row['data']);choices=obj.get('choices') or [{}];content=(choices[0].get('delta') or {}).get('content')
                    if content:trace.append({'task_ms':row['task_ms'],'stage':stage,'delta':content,'type':'token'})
        trace.extend(run['timeline']);result[run['mode']]={'run':run,'trace':sorted(trace,key=lambda r:r['task_ms'])}
    if set(result)!={'off','on'}:raise HTTPException(409,'该组两种模式尚未全部有效完成')
    return {'label':'Recorded Run Replay','modes':result}
@app.get('/api/benchmarks/{jid}/export')
async def export(jid:str):
    get_job(jid,'benchmark');folder=config.DATA/'benchmarks'/jid
    def archive():
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob('*'):
                if p.is_file():z.write(p,str(p.relative_to(folder)))
        return output.getvalue()
    return Response(await asyncio.to_thread(archive),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{jid}.zip"'})
@app.get('/api/sessions/{sid}/counts.csv')
async def counts(sid:str):
    path=config.DATA/'sessions'/safe_id(sid)/'counts.csv'
    if not path.is_file():raise HTTPException(404,'人数时间序列不存在')
    return FileResponse(path,filename=f'{sid}-counts.csv')
@app.get('/api/snapshots/{eid}.jpg')
async def snapshot(eid:str):get_event(eid);return FileResponse(config.DATA/'snapshots'/f'{eid}.jpg')
@app.get('/api/reports/{eid}')
async def report(eid:str,namespace:str='production',download:bool=False):
    get_event(eid);path=config.DATA/'reports'/safe_id(namespace)/f'{eid}.md'
    if not path.is_file():raise HTTPException(404,'报告尚未生成')
    return FileResponse(path,media_type='text/markdown; charset=utf-8',filename=f'{eid}.md' if download else None)
@app.websocket('/ws')
async def ws(socket:WebSocket):
    await socket.accept();q=asyncio.Queue(maxsize=4);app.state.bus.clients.add(q)
    async def send():
        while True:await socket.send_json(await q.get())
    async def receive():
        while True:await socket.receive_text()
    tasks=[]
    try:
        if app.state.video.latest:await socket.send_json(app.state.video.latest)
        tasks=[asyncio.create_task(send()),asyncio.create_task(receive())]
        await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect,RuntimeError):pass
    finally:
        for t in tasks:t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        app.state.bus.clients.discard(q)

dist=config.ROOT/'frontend'/'dist'
if dist.exists():app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=config.PORT,ws='websockets',timeout_graceful_shutdown=3)
