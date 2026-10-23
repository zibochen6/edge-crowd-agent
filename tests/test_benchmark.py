from backend.benchmark import summarize
from backend.metrics import decode_tps,acceptance

def run(pair,mode,**kwargs):
    return {'run_id':f'{pair}-{mode}','pair':pair,'mode':mode,'status':'completed','total_task_ms':200 if mode=='off' else 100,'decode_tokens_per_sec':20 if mode=='off' else 30,'decision_request_hash':'same-a','report_request_hash':'same-b',**kwargs}
def test_five_valid_pairs_required():
    rows=[run(p,m) for p in range(5) for m in ['off','on']]
    result=summarize(rows);assert result['accepted'];assert result['decode_speedup']==1.5 and result['task_speedup']==2
    rows[0]['status']='failed';assert not summarize(rows)['accepted'];assert summarize(rows)['off']['failed']==1
def test_different_inputs_not_paired():
    rows=[run(1,'off'),run(1,'on',report_request_hash='different')]
    assert summarize(rows)['pairs']==[]
def test_missing_metrics_remain_na():
    assert decode_tps(None)==(None,None)
    assert acceptance({'draft_n':0,'draft_n_accepted':0})['acceptance_rate'] is None
def test_service_timings_only():
    assert decode_tps({'predicted_n':10,'predicted_ms':500})[0]==20
    assert acceptance({'draft_n':10,'draft_n_accepted':7})['acceptance_rate']==.7

def test_source_archive_matches_environment_and_refuses_changed_code(tmp_path,monkeypatch):
    import hashlib,json,pytest
    from backend import config
    from backend.benchmark import snapshot_sources
    root=tmp_path/'project';(root/'backend').mkdir(parents=True)
    (root/'backend/agent.py').write_text('version=3\n')
    (root/'uv.lock').write_text('locked\n')
    monkeypatch.setattr(config,'ROOT',root)
    env={'source_hashes':{'backend/agent.py':hashlib.sha256((root/'backend/agent.py').read_bytes()).hexdigest()},'uv_lock_sha256':hashlib.sha256((root/'uv.lock').read_bytes()).hexdigest()}
    snapshot_sources(tmp_path/'run',env)
    assert (tmp_path/'run/source/backend/agent.py').read_bytes()==(root/'backend/agent.py').read_bytes()
    assert json.loads((tmp_path/'run/source-snapshot-manifest.json').read_text())['files']['uv.lock']==env['uv_lock_sha256']
    (root/'backend/agent.py').write_text('changed\n')
    with pytest.raises(RuntimeError,match='源码发生变更'):snapshot_sources(tmp_path/'invalid',env)
