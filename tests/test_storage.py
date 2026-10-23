import pytest
from backend import config
from backend.storage import Store

@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    s=Store(tmp_path/'test.sqlite');s.save_event({'event_id':'EVT-test','current_count':6});yield s;s.db.close()
def args():return {'event_id':'EVT-test','level':'warning','title':'人数超限','description':'ROI 当前6人，阈值5人。'}
def test_idempotence_and_namespace(store):
    a=store.execute('create_alert',args(),'EVT-test');b=store.execute('create_alert',args(),'EVT-test')
    assert a==b and len(store.tool_rows('EVT-test'))==1
    assert store.tool_rows('EVT-test')[0]['attempts']==1
    store.execute('create_alert',args(),'EVT-test','bench-test')
    assert len(store.tool_rows('EVT-test','bench-test'))==1
def test_whitelist_and_event_ownership(store):
    with pytest.raises(ValueError):store.execute('shell',{},'EVT-test')
    with pytest.raises(ValueError):store.execute('create_alert',{**args(),'event_id':'other'},'EVT-test')
    with pytest.raises(ValueError):store.execute('create_alert',{**args(),'command':'x'},'EVT-test')
def test_report_persist_and_no_path_escape(store):
    text='# 报告\n人数6人，配置阈值5人，只能确认人数超限。'
    store.execute('save_report',{'event_id':'EVT-test','report_content':text},'EVT-test')
    assert (config.DATA/'reports/production/EVT-test.md').read_text()==text
    with pytest.raises(ValueError):store.execute('save_report',{'event_id':'EVT-test','report_content':text},'EVT-test','../x')
def test_restart_interrupted(tmp_path):
    s=Store(tmp_path/'r.sqlite');s.save_job({'id':'job','status':'running'},'agent');s.db.close()
    s=Store(tmp_path/'r.sqlite');assert s.jobs('agent')[0]['status']=='interrupted';s.db.close()
