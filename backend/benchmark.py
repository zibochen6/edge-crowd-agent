import asyncio
import csv
import hashlib
import json
import statistics
import subprocess
import time
import uuid
from collections import Counter
from . import config
from .agent import Llama, sha
from .gguf_probe import probe_gguf,sha256_file
from .process import ManagedProcess
from .storage import atomic_json

FIELDS=['ttft_ms','tool_decision_ms','tool_execution_ms','report_generation_ms','total_task_ms','decode_tokens_per_sec','output_tokens','draft_acceptance_rate','prefill_ms','model_load_ms']
def summarize(runs):
    result={}
    for mode in ['off','on']:
        valid=[r for r in runs if r['mode']==mode and r['status']=='completed']
        result[mode]={'valid':len(valid),'failed':sum(r['mode']==mode and r['status']!='completed' for r in runs)}
        for field in FIELDS:
            values=[r[field] for r in valid if isinstance(r.get(field),(int,float))]
            result[mode][field]={'mean':statistics.mean(values),'median':statistics.median(values),'min':min(values),'max':max(values)} if values else None
    pairs=[]
    for index in sorted(set(r['pair'] for r in runs)):
        members={r['mode']:r for r in runs if r['pair']==index and r['status']=='completed'}
        if set(members)!={'off','on'}:continue
        a,b=members['off'],members['on']
        if a['decision_request_hash']!=b['decision_request_hash'] or a['report_request_hash']!=b['report_request_hash']:continue
        pairs.append({'pair':index,'decode_speedup':b['decode_tokens_per_sec']/a['decode_tokens_per_sec'] if a.get('decode_tokens_per_sec') and b.get('decode_tokens_per_sec') else None,'task_speedup':a['total_task_ms']/b['total_task_ms']})
    result['pairs']=pairs
    for key in ['decode_speedup','task_speedup']:
        values=[p[key] for p in pairs if p[key] is not None]
        result[key]=statistics.median(values) if values else None
    result['accepted']=all(result[m]['valid']>=5 for m in ['off','on']) and len(pairs)>=5
    return result

def environment():
    result={'captured_at':time.time(),'model':str(config.MODEL),'engine':str(config.ENGINE),'video':str(config.VIDEO),'model_sha256':sha256_file(config.MODEL),'engine_sha256':sha256_file(config.ENGINE) if config.ENGINE.exists() else None,'video_sha256':sha256_file(config.VIDEO),'mtp':{k:v for k,v in probe_gguf(config.MODEL).items() if k in ['has_mtp','nextn_tensors','nextn_predict_layers','size']}}
    result['source_hashes']={str(p.relative_to(config.ROOT)):sha256_file(p) for p in (config.ROOT/'backend').glob('*.py')}
    result['uv_lock_sha256']=sha256_file(config.ROOT/'uv.lock')
    import importlib.metadata as metadata
    result['python_dependencies']={name:metadata.version(name) for name in ['fastapi','pydantic','numpy','opencv-python','supervision']}
    for name,cmd in [('power_mode',['/usr/sbin/nvpmodel','-q']),('llama_version',[str(config.LLAMA),'--version']),('memory',['free','-b']),('system',['uname','-a'])]:
        result[name]=subprocess.run(cmd,capture_output=True,text=True,timeout=10).stdout.strip()
    return result

def snapshot_sources(folder,env):
    files={**env['source_hashes'],'uv.lock':env['uv_lock_sha256']}
    for relative,expected in files.items():
        content=(config.ROOT/relative).read_bytes()
        if hashlib.sha256(content).hexdigest()!=expected:raise RuntimeError('采集后源码发生变更，拒绝使用不一致的实验版本')
        target=folder/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    atomic_json(folder/'source-snapshot-manifest.json',{'files':files,'method':'copied_and_sha256_verified_before_runs'})

def start(engine,event):
    if engine.bench_pending:raise ValueError('已有实验进行中')
    engine.bench_pending=True
    job={'id':'bench-'+uuid.uuid4().hex[:10],'event_id':event['event_id'],'status':'queued','runs':[],'created_at':time.time(),'method':'sequential_alternating_AB_BA','required_valid_per_mode':5}
    engine.save(job,'benchmark');engine.benchmark_task=asyncio.create_task(run(engine,event,job));return job

async def run(engine,event,job):
    folder=config.DATA/'benchmarks'/job['id'];folder.mkdir(parents=True,exist_ok=True)
    sampler=None
    try:
        async with engine.lock:
            with engine.video.lock:engine.video.hold=True
            await asyncio.to_thread(engine.video.idle.wait,10)
            if not engine.video.idle.is_set():raise RuntimeError('检测 worker 未进入空闲状态')
            job['status']='running';engine.save(job,'benchmark')
            env=await asyncio.to_thread(environment)
            await asyncio.to_thread(snapshot_sources,folder,env)
            atomic_json(folder/'environment.json',env);atomic_json(folder/'event.json',event)
            job['input_hash']=sha(event);job['environment']=env
            sampler=await ManagedProcess.spawn(['/usr/bin/tegrastats','--interval','500'],log_path=folder/'tegrastats.log')
            for pair in range(1,11):
                modes=['off','on'] if pair%2 else ['on','off']
                pair_runs=[]
                for mode in modes:
                    rid=f'{job["id"]}-p{pair}-{mode}';target=folder/rid
                    entry={'run_id':rid,'mode':mode,'pair':pair,'status':'running','started_at':time.time()}
                    job['current']=entry;engine.save(job,'benchmark')
                    try:
                        async with Llama(mode,target,engine.publish) as server:
                            await server.warmup(target)
                            entry.update(await engine.incident(server,event,target,rid,rid))
                        entry['finished_at']=time.time()
                    except asyncio.CancelledError:
                        entry.update(status='cancelled',error='用户取消');job['runs'].append(entry);atomic_json(target/'result.json',entry);raise
                    except Exception as exc:
                        entry.update(status='failed',error=str(exc),finished_at=time.time())
                    atomic_json(target/'result.json',entry);job['runs'].append(entry);pair_runs.append(entry)
                    job['summary']=summarize(job['runs']);engine.save(job,'benchmark');atomic_json(folder/'result.json',job)
                if all(r['status']=='completed' for r in pair_runs):
                    a,b=pair_runs
                    if a['decision_request_hash']!=b['decision_request_hash'] or a['report_request_hash']!=b['report_request_hash']:
                        for r in pair_runs:r.update(status='failed',error='两种模式输入不一致，拒绝计入配对统计');atomic_json(folder/r['run_id']/'result.json',r)
                job['summary']=summarize(job['runs'])
                if job['summary']['accepted']:break
            job['status']='completed' if job['summary']['accepted'] else 'failed'
            if job['status']=='failed':job['error']='未获得五组有效配对结果；失败记录已保留'
    except asyncio.CancelledError:job.update(status='cancelled',error='用户取消实验')
    except Exception as exc:job.update(status='failed',error=str(exc))
    finally:
        if sampler:await sampler.stop(grace_s=3)
        with engine.video.lock:engine.video.hold=False
        engine.bench_pending=False;job['finished_at']=time.time();job['summary']=summarize(job['runs']);job.pop('current',None)
        engine.save(job,'benchmark');atomic_json(folder/'result.json',job)
        with open(folder/'runs.csv','w',newline='') as f:
            fields=['run_id','pair','mode','status','error']+FIELDS
            writer=csv.DictWriter(f,fields,extrasaction='ignore');writer.writeheader();writer.writerows(job['runs'])
