#!/usr/bin/env python3
"""Apply the immutable live-core model bundle to prospective feature rows.

DATA_INVALID rows are retained and never scored. Raw model outputs are ranking
scores, not calibrated probabilities. Paper-only.
"""
import argparse,json,time
from pathlib import Path
from src.live.scoring import LiveCoreScorer


def main():
    p=argparse.ArgumentParser();p.add_argument('--features',required=True);p.add_argument('--bundle',required=True);p.add_argument('--out',required=True);p.add_argument('--model-run-id',default='33256093695');a=p.parse_args()
    scorer=LiveCoreScorer(a.bundle);rows=[]
    for line in Path(a.features).read_text().splitlines():
        if not line.strip():continue
        r=json.loads(line);record={
            'scored_ms':int(time.time()*1000),'mint':r.get('mint'),'name':r.get('name'),'symbol':r.get('symbol'),
            'launch_signature':r.get('launch_signature'),'launch_block_time':r.get('launch_block_time'),
            'decision_age_s':r.get('decision_age_s'),'data_status':r.get('data_status'),'data_quality':r.get('data_quality'),
            'model_run_id':a.model_run_id,'feature_contract':scorer.manifest['feature_contract'],
            'model_sha256':{t:s['model_sha256'] for t,s in scorer.manifest['targets'].items()},
            'scores':None,'decision':'DATA_INVALID','features':r.get('features'),
        }
        if r.get('data_status')=='VALID' and (r.get('data_quality') or {}).get('data_valid'):
            result=scorer.score(r['features']);record.update(result)
        rows.append(record)
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in rows))
    summary={'rows':len(rows),'valid_scored':sum(x['decision']!='DATA_INVALID' for x in rows),'decisions':{},'model_run_id':a.model_run_id,'guard':'Prospective paper ranking only; scores are not calibrated probabilities.'}
    for x in rows:summary['decisions'][x['decision']]=summary['decisions'].get(x['decision'],0)+1
    (out.parent/'SCORE_SUMMARY.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
