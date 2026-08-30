#!/usr/bin/env python3
"""Preselect the expensive RPC-audit subset for high-throughput scans.

Selection uses action-time information only.  It never reads outcomes.  Random
controls are sampled from the entire captured population, independent of score.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

VERSION='ht_audit_selection_v1'

def h(key,mint,salt=''):
    return hashlib.sha256(f'{key}|{salt}|{mint}'.encode()).hexdigest()

def score10(r):
    try:return float(r['scores']['10']['score'])
    except Exception:return float('-inf')

def take_hash(rows,n,key,salt):return sorted(rows,key=lambda r:h(key,r['mint'],salt))[:max(0,n)]

def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--run-key',required=True)
    p.add_argument('--random-controls',type=int,default=10);p.add_argument('--near-misses',type=int,default=3)
    p.add_argument('--watch-audit',type=int,default=10);p.add_argument('--reject-audit',type=int,default=5)
    p.add_argument('--max-candidates',type=int,default=30);a=p.parse_args()
    path=Path(a.rows);rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    candidates=sorted([r for r in rows if r.get('decision') in ('PAPER_PRIORITY','PAPER_CANDIDATE')],key=score10,reverse=True)[:a.max_candidates]
    watches=[r for r in rows if r.get('decision')=='WATCH'];rejects=[r for r in rows if r.get('decision')=='REJECT']
    below=[r for r in rows if (r.get('scores',{}).get('10',{}).get('tier')=='BELOW_Q95')]
    randoms=take_hash(rows,a.random_controls,a.run_key,'random_all')
    watch_pick=take_hash(watches,a.watch_audit,a.run_key,'watch')
    reject_pick=take_hash(rejects,a.reject_audit,a.run_key,'reject_quality')
    near=sorted(below,key=score10,reverse=True)[:a.near_misses]
    tags={}
    def add(xs,tag):
        for r in xs:tags.setdefault(r['mint'],set()).add(tag)
    add(candidates,'champion_candidate');add(randoms,'random_control');add(watch_pick,'watch_sample');add(reject_pick,'reject_quality_sample');add(near,'near_miss_control')
    for r in rows:
        ts=sorted(tags.get(r['mint'],set()))
        r['audit_selection']={'selected':bool(ts),'reasons':ts,'selection_version':VERSION,'run_key':a.run_key}
        r['prospective_controls']={'random_control':'random_control' in ts,'near_miss_control':'near_miss_control' in ts,
                                   'watch_sample':'watch_sample' in ts,'selection_version':VERSION,'run_key':a.run_key}
        r['audit_status']='SELECTED_PENDING' if ts else 'NOT_SELECTED'
    path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    print(json.dumps({'version':VERSION,'rows':len(rows),'selected':sum(bool(tags.get(r['mint'])) for r in rows),
                      'candidates':len(candidates),'random_controls':len(randoms),'watch_sample':len(watch_pick),
                      'near_misses':len(near),'reject_quality_sample':len(reject_pick)},indent=2))
if __name__=='__main__':main()
