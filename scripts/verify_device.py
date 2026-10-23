"""Validate real detections and trace accounting. Does not synthesize events."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend import config
from backend.agent import sha
from backend.metrics import decode_tps, acceptance,metrics_delta

parser=argparse.ArgumentParser();parser.add_argument('--benchmark');parser.add_argument('--session');args=parser.parse_args()
if args.session:
    path=config.DATA/'sessions'/args.session
    rows=[json.loads(line) for line in (path/'frames.jsonl').read_text().splitlines()]
    assert rows and all(b['frame']==a['frame']+1 for a,b in zip(rows,rows[1:]))
    assert all(len(r['track_ids'])==r['roi_count'] and len(set(r['track_ids']))==r['roi_count'] for r in rows)
    print(json.dumps({'session':args.session,'frames':len(rows),'max_full_count':max(r['full_count'] for r in rows),'max_roi_count':max(r['roi_count'] for r in rows),'mean_detection_ms':sum(r['detection_ms'] for r in rows)/len(rows)},ensure_ascii=False))
if args.benchmark:
    folder=config.DATA/'benchmarks'/args.benchmark;job=json.loads((folder/'result.json').read_text());seen={};valid=[]
    for run in job['runs']:
        if run['status']!='completed':continue
        target=folder/run['run_id'];seen.setdefault(run['pair'],{})[run['mode']]=run
        for phase in ['decision','report']:
            request=json.loads((target/f'{phase}-request.json').read_text())
            assert sha(request)==run[f'{phase}_request_hash']
            trace=[json.loads(x) for x in (target/f'{phase}-trace.jsonl').read_text().splitlines()]
            assert trace[-1]['data']=='[DONE]'
            objects=[json.loads(x['data']) for x in trace if x['data']!='[DONE]']
            timings=next((o['timings'] for o in reversed(objects) if o.get('timings')),None)
            if phase=='report':
                assert decode_tps(timings)[0]==run['decode_tokens_per_sec']
                assert timings['predicted_n']==run['output_tokens']
                result=json.loads((target/f'{phase}-result.json').read_text())
                delta=metrics_delta(result['metrics_before'],result['metrics_after'])
                assert acceptance(timings,delta)['acceptance_rate']==run['draft_acceptance_rate']
        valid.append(run)
    for members in seen.values():
        if set(members)=={'off','on'}:
            assert all(members['off'][key]==members['on'][key] for key in ['event_hash','input_hash','decision_request_hash','report_request_hash'])
    assert sum(r['mode']=='off' for r in valid)>=5 and sum(r['mode']=='on' for r in valid)>=5
    assert job['summary']['accepted']
    print(json.dumps({'benchmark':args.benchmark,'valid_runs':len(valid),'trace_verified':True,'summary':job['summary']},ensure_ascii=False))
