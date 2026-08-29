#!/usr/bin/env python3
"""Annotate immutable action-time rows with the post-model adversarial gate.

The script never changes ``decision`` or model scores.  It reads only the
already-frozen action-time v2 feature vector and appends a separately versioned
recommendation.  This allows champion-vs-gate prospective comparison without
rewriting the original experiment.
"""
from __future__ import annotations

import argparse, json, time
from pathlib import Path

from src.live.adversarial_gate import assess_adversarial_risk, ADVERSARIAL_GATE_VERSION


def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--mode',choices=('shadow','active'),default='shadow');a=p.parse_args()
    path=Path(a.rows);rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    counts={};changed=0
    for r in rows:
        assessment=assess_adversarial_risk(r.get('v2_challenger_features') or {},r.get('decision') or 'REJECT')
        d=assessment.to_dict();d['mode']=a.mode;d['applied_ms']=int(time.time()*1000);d['input']='action_time_v2_challenger_features'
        r['adversarial_gate']=d
        r['gated_decision']=assessment.suggested_decision
        r['operational_paper_decision']=assessment.suggested_decision if a.mode=='active' else r.get('decision')
        if assessment.suggested_decision!=r.get('decision'):changed+=1
        counts[assessment.status]=counts.get(assessment.status,0)+1
    path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    print(json.dumps({'rows':len(rows),'gate_version':ADVERSARIAL_GATE_VERSION,'mode':a.mode,'status_counts':counts,'recommendation_changes':changed},indent=2))

if __name__=='__main__':main()
