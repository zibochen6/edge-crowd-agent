import asyncio
import hashlib
import json
import os
import socket
import time
import uuid
import fcntl
from pathlib import Path
import httpx
from . import config
from .domain import Decision,ToolPlan
from .storage import atomic_json, dump
from .process import ManagedProcess
from .metrics import decode_tps, acceptance, parse_prometheus, metrics_delta

SYSTEM='''你是本地人群监控助手。只使用输入事件事实。人数阈值已经由确定性规则判断。
超限仅代表配置规则被触发，不代表危险、违法、身份或意图。不得推测视频未提供的信息。
用简明中文输出。工具仅可用于本地监控台，不执行物理控制。'''
DECIDE='''为已确认的人数阈值事件选择本地处置工具。仅输出 Schema JSON：event_id 复制输入，actions 依次为 create_alert、notify_operator，report_tool 为 save_report。后端按冻结事件填入已核验的 warning 告警、normal 通知参数；不生成重复的标题和说明。'''
from .prompts import report_for

ENGLISH_SYSTEM='''You are a local crowd-monitoring assistant. Use only the supplied event facts. A deterministic rule already confirmed the count threshold. Exceeding a count limit does not establish danger, illegality, identity, or intent. Do not infer unobserved behavior. Write concise English. Tools only affect the local console, never physical equipment.'''
ENGLISH_DECIDE='''Select local tools for this confirmed count-threshold event. Output only Schema JSON: copy event_id, use actions create_alert then notify_operator, and report_tool save_report. The backend binds validated warning alerts and normal-priority notifications from the frozen event; do not repeat their text.'''

def system_for(event):return ENGLISH_SYSTEM if event.get('settings',{}).get('report_language')=='en' else SYSTEM

def sha(value): return hashlib.sha256(dump(value).encode()).hexdigest()
def model_event(event):
    # The complete original stays in event.json; send only facts the model uses.
    result={k:event[k] for k in ['event_id','zone_id','current_count','threshold','video_seconds','duration_above_threshold_sec'] if k in event}
    history=event.get('count_history',[])
    selected=history[::max(1,(len(history)+6)//7)]
    if history and selected[-1]!=history[-1]:selected.append(history[-1])
    result['count_history']=[{k:h[k] for k in ['video_seconds','roi_count']} for h in selected]
    result['settings']={k:v for k,v in event.get('settings',{}).items() if k in ['trigger_seconds','recovery_count','recovery_seconds']}
    if event.get('settings',{}).get('report_language')=='en':result['settings']['report_language']='en'
    if event.get('behavior_evidence'):
        result['behavior_evidence']={k:v for k,v in event['behavior_evidence'].items() if k in ['source','window_seconds','minimum_observation_seconds','moving_count','low_displacement_count','insufficient_count','longest_continuous_roi_seconds']}
    return result

def factual_tool_arguments(event):
    eid=event['event_id'];count=event['current_count'];threshold=event['threshold']
    description=f'视频 {event["video_seconds"]:.2f} 秒，ROI 当前 {count} 人，配置阈值 {threshold} 人，持续 {event["duration_above_threshold_sec"]:.2f} 秒；仅确认配置人数阈值被触发。'
    title=f'ZONE-A 人数达到配置阈值：{count}/{threshold}'
    if event.get('settings',{}).get('report_language')=='en':
        title=f'ZONE-A count threshold met: {count}/{threshold}'
        description=f'Video {event["video_seconds"]:.2f}s, ROI count {count}, threshold {threshold}, duration {event["duration_above_threshold_sec"]:.2f}s; only the configured count threshold is confirmed.'
    return {'create_alert':{'event_id':eid,'level':'warning','title':title,'description':description},'notify_operator':{'event_id':eid,'priority':'normal','message':description},'report_tool':'save_report'}

def bind_tool_plan(text,event):
    plan=ToolPlan.model_validate_json(text)
    if plan.event_id!=event['event_id']:raise ValueError('工具计划与事件归属不一致，拒绝执行')
    return plan,Decision.model_validate(factual_tool_arguments(event))

def validate_report(text,event):
    import re
    allowed={event['current_count'],event['threshold'],*[h['roi_count'] for h in event.get('count_history',[])]}
    motion=event.get('behavior_evidence',{})
    allowed.update(motion.get(k) for k in ['moving_count','low_displacement_count','insufficient_count'] if isinstance(motion.get(k),int))
    recovery=event.get('settings',{}).get('recovery_count')
    if recovery is not None:allowed.add(recovery)
    unexpected={int(n) for n in re.findall(r'(\d+)\s*(?:人|名(?:人员)?|people|persons?)',text,re.I)}-allowed
    if unexpected:raise ValueError(f'报告包含事件依据以外的人数 {sorted(unexpected)}，拒绝保存')
    if event.get('behavior_evidence'):
        english=event.get('settings',{}).get('report_language')=='en'
        heading='Assessment' if english else '异常判断'
        section=re.search(r'###\s*'+heading+r'\s*\n([^#]+)',text,re.I)
        if not section or not re.search(r'(?<!\d)'+str(event['current_count'])+r'\s*(?:人|名|people|persons?)',section[1],re.I):
            raise ValueError('异常判断未引用触发时实际人数，拒绝保存')
        unsupported=[r'正常移动状态',r'未(?:出现|发生)[^。\n]{0,24}(?:滞留|堵塞)',r'风险解除',r'现场恢复正常',r'已经疏散',r'\b(?:no|without)\s+(?:signs?\s+of\s+)?(?:loitering|blockage|congestion|anomal(?:y|ies))\b',r'\b(?:risk|danger)\s+(?:is\s+|has\s+been\s+)?(?:cleared|resolved|eliminated)\b',r'\b(?:scene|area|people)\s+(?:is|are)\s+safe\b',r'\balready\s+(?:evacuated|dispersed)\b']
        if any(re.search(pattern,text,re.I) for pattern in unsupported):
            raise ValueError('分析包含轨迹数据无法支持的正常或安全结论，拒绝保存')
        if english and 'longest_continuous_roi_seconds' in motion:
            if not all(re.search(r'###\s*'+h,text,re.I) for h in ['Assessment','Dwell and movement','Response']):raise ValueError('English report is missing a required section')
            if not re.search(r'(?:cannot\s+confirm|does\s+not\s+establish|insufficient[^.\n]*confirm)[^.\n]*(?:loitering|blockage)',text,re.I):raise ValueError('English report omitted the brief-observation limitation')


_OWNED_PIDS=set()

def foreign_llama(owned=None):
    result=[]
    for p in Path('/proc').glob('[0-9]*'):
        try:
            cmd=(p/'cmdline').read_bytes().split(b'\0')
            name=Path(os.fsdecode(cmd[0])).name if cmd and cmd[0] else ''
            if name in ['llama-server','llama-cli'] and int(p.name)!=owned and int(p.name) not in _OWNED_PIDS: result.append(int(p.name))
        except (OSError,ValueError):pass
    return result

class Llama:
    def __init__(self,mode,folder,publish):
        self.mode=mode;self.folder=folder;self.publish=publish;self.proc=None;self.client=None;self.lease=None
    async def __aenter__(self):
        foreign=foreign_llama()
        if foreign:raise RuntimeError(f'检测到外部 llama 进程 {foreign}，请待其退出后重试')
        if not config.LLAMA.is_file() or not config.MODEL.is_file():raise RuntimeError('llama-server 或目标 GGUF 路径不存在')
        self.lease=open('/tmp/edge-crowd-agent-llm.lock','a')
        try:fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close();self.lease=None;raise RuntimeError('另一 Crowd 服务持有模型执行锁')
        self.folder.mkdir(parents=True,exist_ok=True)
        with socket.socket() as s:s.bind(('127.0.0.1',0));self.port=s.getsockname()[1]
        args=[str(config.LLAMA),'--model',str(config.MODEL),'--host','127.0.0.1','--port',str(self.port),'--n-gpu-layers','99','--ctx-size','8192','--parallel','1','--metrics','--no-webui','--no-cache-prompt','--spec-type','draft-mtp' if self.mode=='on' else 'none']
        if self.mode=='on':args+=['--spec-draft-n-max','2']
        atomic_json(self.folder/'server-command.json',args);started=time.monotonic()
        try:self.proc=await ManagedProcess.spawn(args,log_path=self.folder/'server.log')
        except BaseException:
            self.lease.close();self.lease=None;raise
        _OWNED_PIDS.add(self.proc.pid)
        self.client=httpx.AsyncClient(base_url=f'http://127.0.0.1:{self.port}',timeout=httpx.Timeout(180,connect=5))
        try:
            for _ in range(600):
                if self.proc.proc.returncode is not None:raise RuntimeError('模式启动失败: '+self.proc.tail_log(20))
                try:
                    r=await self.client.get('/health',timeout=1)
                    if r.status_code==200:break
                except httpx.HTTPError:pass
                await asyncio.sleep(.2)
            else:raise RuntimeError('模型启动超时')
            self.load_ms=(time.monotonic()-started)*1000
            self.mtp_loaded='creating MTP draft context' in self.proc.tail_log(2000)
            if self.mode=='on' and not self.mtp_loaded:raise RuntimeError('MTP 模式未出现 draft context 加载证据')
            return self
        except BaseException:
            await self.__aexit__(None,None,None);raise
    async def __aexit__(self,*args):
        if self.client:await self.client.aclose()
        if self.proc:
            await self.proc.stop(grace_s=5)
            _OWNED_PIDS.discard(self.proc.pid)
        if self.lease:self.lease.close();self.lease=None
    async def metrics(self):
        r=await self.client.get('/metrics');return parse_prometheus(r.text) if r.status_code==200 else {}
    async def generate(self,messages,folder,stage,run_id,task_t0,schema=None,max_tokens=768):
        payload={'messages':messages,'temperature':0.0,'seed':42,'max_tokens':max_tokens,'stream':True,'stream_options':{'include_usage':True},'cache_prompt':False,'chat_template_kwargs':{'enable_thinking':False}}
        if schema:payload['response_format']={'type':'json_object','schema':schema}
        atomic_json(folder/f'{stage}-request.json',payload)
        before=await self.metrics();start=time.monotonic();ttft=None;text='';timings=None;usage=None;finish=None;done=False
        with open(folder/f'{stage}-trace.jsonl','w') as trace:
            async with self.client.stream('POST','/v1/chat/completions',json=payload) as response:
                if response.status_code!=200:raise RuntimeError(f'LLM HTTP {response.status_code}: {(await response.aread()).decode()[:600]}')
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip();now=time.monotonic()
                    trace.write(dump({'t_ms':(now-start)*1000,'task_ms':(now-task_t0)*1000,'data':raw})+'\n');trace.flush()
                    if raw=='[DONE]':done=True;break
                    obj=json.loads(raw)
                    if obj.get('error'):raise RuntimeError(str(obj['error']))
                    choices=obj.get('choices') or [{}];choice=choices[0];delta=choice.get('delta') or {};content=delta.get('content') or ''
                    if content:
                        if ttft is None:ttft=(now-start)*1000
                        text+=content
                        self.publish({'type':'token','run_id':run_id,'mode':self.mode,'stage':stage,'delta':content,'task_ms':(now-task_t0)*1000})
                    timings=obj.get('timings') or timings;usage=obj.get('usage') or usage;finish=choice.get('finish_reason') or finish
        if not done or (finish=='length' and stage!='warmup'):raise RuntimeError('LLM 输出中断或达到 Token 上限')
        if foreign_llama(self.proc.pid):raise RuntimeError('检测到外部 LLM 并发，本轮不可用于公平对比')
        elapsed=(time.monotonic()-start)*1000
        after=await self.metrics();delta=metrics_delta(before,after)
        tps,source=decode_tps(timings);accept=acceptance(timings,delta)
        tokens=(timings or {}).get('predicted_n')
        if tokens is None:tokens=(usage or {}).get('completion_tokens')
        result={'text':text,'ttft_ms':ttft,'elapsed_ms':elapsed,'timings':timings,'usage':usage,'output_tokens':tokens,'decode_tokens_per_sec':tps,'decode_source':source,'draft_acceptance_rate':accept['acceptance_rate'],'draft_n':accept['draft_n'],'acceptance_source':accept['source'],'metrics_before':before,'metrics_after':after,'request_hash':sha(payload),'finish_reason':finish}
        atomic_json(folder/f'{stage}-result.json',result);return result
    async def warmup(self,folder):
        start=time.monotonic()
        await self.generate([{'role':'user','content':'Reply with the single word OK.'}],folder,'warmup','warmup',start,max_tokens=16)

class AgentEngine:
    def __init__(self,store,video,publish):
        self.store=store;self.video=video;self.publish=publish;self.lock=asyncio.Lock();self.tasks={};self.bench_pending=False;self.benchmark_task=None
    def save(self,job,kind='agent'):
        self.store.save_job(job,kind);self.publish({'type':'job','kind':kind,'job':job})
    def enqueue(self,event,mode='off'):
        job={'id':'agent-'+uuid.uuid4().hex[:10],'event_id':event['event_id'],'mode':mode,'status':'queued','created_at':time.time()}
        self.save(job);self.tasks[job['id']]=asyncio.create_task(self.production(job,event))
        return job
    async def production(self,job,event):
        try:
            while True:
                while self.bench_pending:await asyncio.sleep(.2)
                await self.lock.acquire()
                if not self.bench_pending:break
                self.lock.release()
            try:
                job['status']='running';self.save(job)
                folder=config.DATA/'agent'/job['id']
                async with Llama(job['mode'],folder,self.publish) as server:
                    result=await self.incident(server,event,folder,job['id'],'production')
                job.update(status='completed',result=result)
            finally:self.lock.release()
        except asyncio.CancelledError:job.update(status='cancelled',error='用户取消')
        except Exception as exc:job.update(status='failed',error=str(exc))
        finally:self.save(job);self.tasks.pop(job['id'],None)
    async def incident(self,server,event,folder,run_id,namespace):
        folder.mkdir(parents=True,exist_ok=True);frozen=model_event(event)
        atomic_json(folder/'event.json',event)
        t0=time.monotonic();timeline=[]
        def record(name,body):
            item={'type':name,'task_ms':(time.monotonic()-t0)*1000,**body};timeline.append(item)
            atomic_json(folder/'timeline.json',timeline)
            self.publish({**item,'type':'tool','action':name,'run_id':run_id,'mode':server.mode,'namespace':namespace})
        schema=ToolPlan.model_json_schema();schema['properties']['event_id']['const']=event['event_id']
        decide=ENGLISH_DECIDE if event.get('settings',{}).get('report_language')=='en' else DECIDE
        a=await server.generate([{'role':'system','content':system_for(event)},{'role':'user','content':decide+'\n'+dump({'event':frozen})}],folder,'decision',run_id,t0,schema=schema,max_tokens=96)
        plan,decision=bind_tool_plan(a['text'],event)
        record('decision',{'plan':plan.model_dump(),'decision':decision.model_dump()})
        tool_start=time.monotonic();receipts=[]
        for name in ['create_alert','notify_operator']:
            args=getattr(decision,name).model_dump();record('tool_start',{'name':name})
            receipt=await asyncio.wait_for(asyncio.to_thread(self.store.execute,name,args,event['event_id'],namespace),timeout=10)
            receipts.append(receipt);record('tool_complete',{'name':name,'result':receipt})
        execution=(time.monotonic()-tool_start)*1000
        b=await server.generate([{'role':'system','content':system_for(event)},{'role':'user','content':report_for(event)+'\n'+dump({'event':frozen,'tool_results':receipts})}],folder,'report',run_id,t0,max_tokens=256)
        validate_report(b['text'],event)
        if event.get('settings',{}).get('report_language')=='en':
            evidence=f'\n\n---\nEvidence: {event["event_id"]} · Video {event["video_seconds"]:.2f}s · ROI {event["current_count"]} people / threshold {event["threshold"]} · Duration {event["duration_above_threshold_sec"]:.2f}s.\n\n![Event snapshot](/api/snapshots/{event["event_id"]}.jpg)\n'
        else:evidence=f'\n\n---\n核验依据：{event["event_id"]} · 视频 {event["video_seconds"]:.2f}s · ROI {event["current_count"]} 人 / 阈值 {event["threshold"]} 人 · 持续 {event["duration_above_threshold_sec"]:.2f}s。\n\n![事件抓拍](/api/snapshots/{event["event_id"]}.jpg)\n'
        record('tool_start',{'name':'save_report'});save_start=time.monotonic()
        receipt=await asyncio.wait_for(asyncio.to_thread(self.store.execute,decision.report_tool,{'event_id':event['event_id'],'report_content':b['text']+evidence},event['event_id'],namespace),timeout=10)
        execution+=(time.monotonic()-save_start)*1000;record('tool_complete',{'name':'save_report','result':receipt})
        if server.mode=='on' and (b['draft_n'] is None or b['draft_n']<=0):raise RuntimeError('报告请求未取得实际 MTP draft 证据')
        result={'run_id':run_id,'mode':server.mode,'event_id':event['event_id'],'namespace':namespace,'status':'completed','event_hash':sha(event),'input_hash':sha(frozen),'decision_request_hash':a['request_hash'],'report_request_hash':b['request_hash'],'model_load_ms':server.load_ms,'ttft_ms':a['ttft_ms'],'report_ttft_ms':b['ttft_ms'],'tool_decision_ms':a['elapsed_ms'],'tool_execution_ms':execution,'report_generation_ms':b['elapsed_ms'],'total_task_ms':(time.monotonic()-t0)*1000,'decode_tokens_per_sec':b['decode_tokens_per_sec'],'output_tokens':b['output_tokens'],'draft_acceptance_rate':b['draft_acceptance_rate'],'decode_source':b['decode_source'],'prefill_ms':(b.get('timings') or {}).get('prompt_ms'),'report':b['text'],'decision':decision.model_dump(),'tool_plan':plan.model_dump(),'timeline':timeline,'decision_output_tokens':a['output_tokens'],'mtp_loaded':server.mtp_loaded,'analysis_version':'behavior-v3-fast'}
        result['language']=event.get('settings',{}).get('report_language','zh')
        atomic_json(folder/'result.json',result);return result
    async def cancel(self,jid):
        task=self.tasks.get(jid)
        if task:task.cancel();return True
        return False
    async def close(self):
        tasks=list(self.tasks.values())
        if self.benchmark_task:tasks.append(self.benchmark_task)
        for t in tasks:t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
