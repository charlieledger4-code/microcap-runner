#!/usr/bin/env python3
"""Build a compact permanent ledger package from a full HT scan artifact."""
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    src=Path(a.run_dir);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(x) for x in (src/'scored_rows.jsonl').read_text().splitlines() if x.strip()]
    tapes={x['mint']:x for x in (json.loads(y) for y in (src/'action_trade_tapes.jsonl').read_text().splitlines() if y.strip())}
    selected=[r for r in rows if (r.get('audit_selection') or {}).get('selected')]
    population=[]
    for r in rows:
        population.append({'mint':r.get('mint'),'name':r.get('name'),'symbol':r.get('symbol'),'launch_received_ms':r.get('launch_received_ms'),
                           'scored_ms':r.get('scored_ms'),'decision_latency_ms':r.get('decision_latency_ms'),'decision':r.get('decision'),
                           'scores':r.get('scores'),'data_status':r.get('data_status'),'audit_status':r.get('audit_status'),
                           'audit_selection':r.get('audit_selection'),'prospective_controls':r.get('prospective_controls')})
    (out/'population_scores.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in population))
    (out/'scored_rows.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in selected))
    (out/'action_trade_tapes.jsonl').write_text(''.join(json.dumps(tapes[x['mint']],separators=(',',':'))+'\n' for x in selected if x['mint'] in tapes))
    for name in ('SUMMARY.json','DRIFT.json','RUN_METADATA.json'):
        if (src/name).exists():shutil.copy2(src/name,out/name)
    (out/'PACKAGE.json').write_text(json.dumps({'population_rows':len(rows),'selected_rows':len(selected),'selected_tapes':sum(x['mint'] in tapes for x in selected),
                                               'guard':'Permanent ledger stores all scores compactly and full details only for outcome-independent audited selections.'},indent=2))
    print(json.dumps({'population_rows':len(rows),'selected_rows':len(selected)},indent=2))
if __name__=='__main__':main()
