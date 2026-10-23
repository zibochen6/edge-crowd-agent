import asyncio
import json
import pytest
from backend import config
from backend.agent import AgentEngine,factual_tool_arguments,model_event,validate_report,bind_tool_plan
from backend.storage import Store

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    event={'event_id':'EVT-test','current_count':6,'full_count':25,'threshold':5,'video_seconds':2.0,'duration_above_threshold_sec':1.5,'count_history':[{'video_seconds':1.0,'roi_count':6,'full_count':25}]}
    store=Store(tmp_path/'test.sqlite');store.save_event(event)
    engine=AgentEngine(store,None,lambda item:None)
    yield store,engine,event,tmp_path
    store.db.close()

class Server:
    mode='off';load_ms=1;mtp_loaded=False
    def __init__(self,event,bad=False):self.event=event;self.bad=bad;self.requests=[]
    async def generate(self,messages,folder,stage,*a,**kw):
        self.requests.append(messages)
        text='bad json' if self.bad else json.dumps({'event_id':self.event['event_id'],'actions':['create_alert','notify_operator'],'report_tool':'save_report'}) if stage=='decision' else '# 事件报告\nROI当前6人，阈值5人，只能确认配置超限，不能判断人员意图。'
        return {'text':text,'elapsed_ms':1,'request_hash':'test','output_tokens':12,'ttft_ms':.1,'draft_n':0,'decode_tokens_per_sec':10,'decode_source':'server_timings','draft_acceptance_rate':None,'timings':{'prompt_ms':.2}}

def test_model_input_excludes_confusing_full_count(setup):
    _,_,event,_=setup
    assert 'full_count' not in json.dumps(model_event(event))

def test_report_accepts_configured_recovery_but_not_invented_people(setup):
    _,_,event,_=setup;event['settings']={'recovery_count':3}
    validate_report('事件发生时6人，阈值5人；恢复条件3人。',event)
    with pytest.raises(ValueError):validate_report('事件发生时25人。',event)

async def test_invalid_json_never_executes_tools(setup):
    store,engine,event,folder=setup
    with pytest.raises(ValueError):await engine.incident(Server(event,True),event,folder,'test','test')
    assert store.tool_rows(event['event_id'],'test')==[]

async def test_foreign_event_plan_rejected_before_any_tool(setup):
    store,engine,event,folder=setup
    other={**event,'event_id':'EVT-foreign'}
    with pytest.raises(ValueError,match='归属不一致'):await engine.incident(Server(other),event,folder,'test','test')
    assert store.tool_rows(event['event_id'],'test')==[]

@pytest.mark.parametrize('changes',[
    {'actions':['shell','notify_operator']},
    {'actions':['create_alert','create_alert']},
    {'actions':['create_alert']},
    {'report_tool':'shell'},
    {'description':'untrusted parameter override'},
])
def test_compact_plan_cannot_override_tools_or_event_facts(setup,changes):
    _,_,event,_=setup
    plan={'event_id':event['event_id'],'actions':['create_alert','notify_operator'],'report_tool':'save_report',**changes}
    with pytest.raises(ValueError):bind_tool_plan(json.dumps(plan),event)

def test_backend_binds_complete_validated_arguments_from_frozen_event(setup):
    _,_,event,_=setup
    plan,decision=bind_tool_plan(json.dumps({'event_id':event['event_id'],'actions':['create_alert','notify_operator'],'report_tool':'save_report'}),event)
    assert decision.model_dump()==factual_tool_arguments(event)
    assert decision.create_alert.event_id==event['event_id']
    assert '6' in decision.create_alert.description and '25' not in decision.create_alert.description

async def test_real_tool_order_and_canonical_receipts(setup):
    store,engine,event,folder=setup;server=Server(event)
    result=await engine.incident(server,event,folder,'test','test')
    assert result['status']=='completed'
    assert [x['name'] for x in store.tool_rows(event['event_id'],'test')]==['create_alert','notify_operator','save_report']
    assert (folder/'reports/test/EVT-test.md').is_file()
    report_input=server.requests[1][-1]['content']
    assert 'test-' not in report_input and 'created_at' not in report_input

async def test_task_cancellation_releases_queue(setup):
    _,engine,event,_=setup
    engine.bench_pending=True
    job=engine.enqueue(event)
    await asyncio.sleep(.01)
    assert await engine.cancel(job['id'])
    await asyncio.sleep(.01)
    assert job['status']=='cancelled' and not engine.lock.locked()

async def test_mode_start_failure_is_explicit_and_process_cleaned(tmp_path,monkeypatch):
    from backend.agent import Llama,_OWNED_PIDS
    model=tmp_path/'test.gguf';model.write_bytes(b'not-loaded')
    monkeypatch.setattr(config,'MODEL',model)
    from pathlib import Path
    monkeypatch.setattr(config,'LLAMA',Path('/usr/bin/false'))
    with pytest.raises(RuntimeError,match='模式启动失败'):
        async with Llama('on',tmp_path/'run',lambda x:None):pass
    assert not _OWNED_PIDS

def test_report_rejects_unsupported_behavior_and_safety_claims(setup):
    _,_,event,_=setup;event['behavior_evidence']={'moving_count':5,'low_displacement_count':1,'insufficient_count':0}
    for text in ['人员处于正常移动状态。','未发生长时间滞留或堵塞。','人数下降后风险解除。','此时现场恢复正常。']:
        with pytest.raises(ValueError,match='无法支持'):validate_report('### 异常判断\n区域6人达到阈值。\n'+text,event)
    validate_report('### 异常判断\n区域6人达到阈值。\n5名人员位移明显、1名人员位移较小。短时观测不足以确认是否长期滞留或通行堵塞。',event)


def test_report_examples_use_current_event_numbers(setup):
    from backend.prompts import report_for
    _,_,event,_=setup
    event.update(current_count=7,behavior_evidence={'moving_count':3,'low_displacement_count':2,'insufficient_count':2,'longest_continuous_roi_seconds':1.8})
    prompt=report_for(event)
    assert '触发时区域内7人达到5人阈值' in prompt
    assert '3人位移明显、2人位移较小' in prompt
    assert '另有2人观察不足' in prompt
    assert '1.80秒' in prompt
    assert '关注事项' not in prompt
    assert '跟踪观察到5人位移明显、1人位移较小' not in prompt
    with pytest.raises(ValueError,match='实际人数'):
        validate_report('### 异常判断\n区域6人达到阈值。',event)


def test_compact_evidence_preserves_current_counts_and_timeline_endpoints(setup):
    _,_,event,_=setup
    event['count_history']=[{'video_seconds':i/25,'roi_count':5+i%3,'full_count':25,'track_ids':[1,2]} for i in range(80)]
    event['behavior_evidence']={'moving_count':5,'low_displacement_count':1,'insufficient_count':0,'longest_continuous_roi_seconds':1.52,'tracks':[{'track_id':1}]}
    compact=model_event(event)
    assert compact['current_count']==6 and len(compact['count_history'])<=8
    assert compact['count_history'][0]['video_seconds']==0 and compact['count_history'][-1]['video_seconds']==79/25
    assert 'tracks' not in compact['behavior_evidence'] and 'track_ids' not in json.dumps(compact)
    assert compact['behavior_evidence']['longest_continuous_roi_seconds']==1.52

def test_english_prompt_and_factual_arguments_use_frozen_language(setup):
    from backend.prompts import report_for
    from backend.agent import system_for
    _,_,event,_=setup
    event['settings']={'report_language':'en','recovery_count':3,'recovery_seconds':2}
    event['behavior_evidence']={'moving_count':5,'low_displacement_count':1,'insufficient_count':0,'longest_continuous_roi_seconds':1.52}
    prompt=report_for(event)
    assert '### Assessment' in prompt and '6 people' in prompt
    assert '1.52 s' in prompt and 'at most 3 people for 2 s' in prompt
    assert 'English' in system_for(event)
    args=factual_tool_arguments(event)
    assert args['create_alert']['title']=='ZONE-A count threshold met: 6/5'
    assert model_event(event)['settings']['report_language']=='en'
    validate_report(prompt.split('### Assessment')[0]+'### Assessment'+prompt.split('### Assessment',1)[1],event)
    for claim in ['There is no blockage.','The area is safe.','Risk is resolved.','People already dispersed.']:
        with pytest.raises(ValueError,match='无法支持'):validate_report('### Assessment\n6 people met the threshold.\n'+claim,event)
    with pytest.raises(ValueError):validate_report('### Assessment\n25 people met the threshold.',event)

def test_english_report_requires_explicit_short_observation_boundary(setup):
    _,_,event,_=setup
    event['settings']={'report_language':'en'}
    event['behavior_evidence']={'moving_count':5,'low_displacement_count':1,'insufficient_count':0,'longest_continuous_roi_seconds':1.52}
    incomplete='### Assessment\n6 people met threshold 5.\n### Dwell and movement\n5 people moving; longest visibility 1.52 s.\n### Response\nVerify on site.'
    with pytest.raises(ValueError,match='brief-observation limitation'):validate_report(incomplete,event)
    validate_report(incomplete+' Brief tracking cannot confirm prolonged loitering or blockage.',event)
