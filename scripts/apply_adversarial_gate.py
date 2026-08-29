#!/usr/bin/env python3
"""Annotate immutable action-time rows with rejected-veto diagnostics.

Historical walk-forward validation of ``adv_gate_v1_20260829`` failed its
predeclared promotion gate: it removed too many genuine 10x winners and reduced
precision.  Therefore this script is permanently diagnostic-only for v1.  It
never changes ``decision``, model scores, or ``operational_paper_decision``.
"""
from __future__ import annotations

import argparse, json, time
from pathlib import Path

from src.live.adversarial_gate import assess_adversarial_risk, ADVERSARIAL_GATE_VERSION

HISTORICAL_VALIDATION_STATUS='REJECTED_OPERATIONAL_VETO'
HISTORICAL_VALIDATION_RUN=33261646892


def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--mode',choices=('shadow',),default='shadow');a=p.parse_args()
    path=Path(a.rows);rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    counts={};changed=0
    for r in rows:
        assessment=assess_adversarial_risk(r.get('v2_challenger_features') or {},r.get('decision') or 'REJECT')
        d=assessment.to_dict();d.update({
            'mode':'diagnostic_only','applied_ms':int(time.time()*1000),
            'input':'action_time_v2_challenger_features',
            'historical_validation_status':HISTORICAL_VALIDATION_STATUS,
            'historical_validation_run':HISTORICAL_VALIDATION_RUN,
            'guard':'This rule failed historical promotion and is prohibited from changing the operational decision.',
        })
        r['adversarial_gate']=d
        r['gated_decision']=assessment.suggested_decision  # counterfactual research label only
        r['operational_paper_decision']=r.get('decision')
        if assessment.suggested_decision!=r.get('decision'):changed+=1
        counts[assessment.status]=counts.get(assessment.status,0)+1
    path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    print(json.dumps({
        'rows':len(rows),'gate_version':ADVERSARIAL_GATE_VERSION,
        'historical_validation_status':HISTORICAL_VALIDATION_STATUS,
        'status_counts':counts,'counterfactual_recommendation_changes':changed,
        'operational_changes':0,
    },indent=2))

if __name__=='__main__':main()
