#!/usr/bin/env python3
"""Mark predeclared prospective controls without using future outcomes.

- random_control: one valid non-candidate chosen by SHA-256(run_key|mint)
- near_miss_control: highest 10x score below the frozen Q95 threshold

Selections depend only on information available at decision time and are written
before any outcome tracking begins.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path


def h(run_key: str, mint: str) -> str:
    return hashlib.sha256(f'{run_key}|{mint}'.encode()).hexdigest()


def score10(row):
    try:return float(row['scores']['10']['score'])
    except Exception:return float('-inf')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--rows',required=True);ap.add_argument('--run-key',required=True);a=ap.parse_args()
    p=Path(a.rows);rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    valid=[r for r in rows if r.get('data_status')=='VALID']
    non_candidates=[r for r in valid if r.get('decision') not in ('PAPER_PRIORITY','PAPER_CANDIDATE')]
    random_pick=min(non_candidates,key=lambda r:h(a.run_key,r['mint'])) if non_candidates else None
    below=[r for r in valid if (r.get('scores',{}).get('10',{}).get('tier')=='BELOW_Q95')]
    near=max(below,key=score10) if below else None
    for r in rows:
        r['prospective_controls']={
            'random_control':bool(random_pick and r['mint']==random_pick['mint']),
            'near_miss_control':bool(near and r['mint']==near['mint']),
            'selection_version':'sha256_random_v1+max_below_q95_v1',
            'run_key':a.run_key,
        }
    p.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    print(json.dumps({'rows':len(rows),'random_control':random_pick and random_pick['mint'],'near_miss_control':near and near['mint']},indent=2))

if __name__=='__main__':main()
