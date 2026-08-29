#!/usr/bin/env python3
"""Mark predeclared prospective controls without using future outcomes.

- random_control: one audit-valid launch chosen uniformly/deterministically by SHA-256(run_key|mint), independent of model score
- near_miss_control: highest 10x score below the frozen Q95 threshold

Selections depend only on information available at decision time and are written
before any outcome tracking begins. The random control may itself be a model
candidate; excluding candidates would bias the control base rate downward.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

SELECTION_VERSION='sha256_random_all_valid_v2+max_below_q95_v1'


def h(run_key: str, mint: str) -> str:
    return hashlib.sha256(f'{run_key}|{mint}'.encode()).hexdigest()


def score10(row):
    try:return float(row['scores']['10']['score'])
    except Exception:return float('-inf')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--rows',required=True);ap.add_argument('--run-key',required=True);a=ap.parse_args()
    p=Path(a.rows);rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    valid=[r for r in rows if r.get('data_status')=='VALID']
    random_pick=min(valid,key=lambda r:h(a.run_key,r['mint'])) if valid else None
    below=[r for r in valid if (r.get('scores',{}).get('10',{}).get('tier')=='BELOW_Q95')]
    near=max(below,key=score10) if below else None
    for r in rows:
        r['prospective_controls']={
            'random_control':bool(random_pick and r['mint']==random_pick['mint']),
            'near_miss_control':bool(near and r['mint']==near['mint']),
            'selection_version':SELECTION_VERSION,
            'run_key':a.run_key,
        }
    p.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    print(json.dumps({'rows':len(rows),'valid_rows':len(valid),'random_control':random_pick and random_pick['mint'],'near_miss_control':near and near['mint'],'selection_version':SELECTION_VERSION},indent=2))

if __name__=='__main__':main()
