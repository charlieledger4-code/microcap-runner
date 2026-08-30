#!/usr/bin/env python3
"""Summarize progress toward the frozen forward-experiment sample gates."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--ledger-root',required=True);p.add_argument('--config',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.ledger_root);cfg=json.loads(Path(a.config).read_text());scanroot=root/'prospective'/'scans'
    population=0;selected=0;valid_candidates=0;valid_random=0;ht_runs=0;sentinel_runs=0
    for d in sorted(scanroot.iterdir()) if scanroot.exists() else []:
        if not d.is_dir():continue
        pop=d/'population_scores.jsonl';rows=d/'scored_rows.jsonl'
        if pop.exists():
            ps=[x for x in pop.read_text().splitlines() if x.strip()];population+=len(ps);ht_runs+=1
        elif rows.exists():
            ps=[x for x in rows.read_text().splitlines() if x.strip()];population+=len(ps);sentinel_runs+=1
        if rows.exists():
            for line in rows.read_text().splitlines():
                if not line.strip():continue
                r=json.loads(line);selected+=1
                if r.get('data_status')!='VALID':continue
                if r.get('decision') in ('PAPER_PRIORITY','PAPER_CANDIDATE'):valid_candidates+=1
                if (r.get('prospective_controls') or {}).get('random_control'):valid_random+=1
    complete24=0;candidate_hits10=0;random_hits10=0;candidate_complete=0;random_complete=0
    outroot=root/'prospective'/'outcomes'
    for f in outroot.glob('*/*/86400s.json') if outroot.exists() else []:
        try:r=json.loads(f.read_text())
        except Exception:continue
        if r.get('status')!='COMPLETE':continue
        complete24+=1;hit=bool((((r.get('outcome') or {}).get('executable_targets') or {}).get('10') or {}).get('hit'))
        if r.get('decision') in ('PAPER_PRIORITY','PAPER_CANDIDATE'):
            candidate_complete+=1;candidate_hits10+=int(hit)
        if (r.get('prospective_controls') or {}).get('random_control'):
            random_complete+=1;random_hits10+=int(hit)
    interim=cfg['interim_gate'];primary=cfg['primary_gate']
    result={'generated_ms':int(time.time()*1000),'experiment_id':cfg['experiment_id'],'population_launches':population,'ht_runs':ht_runs,'sentinel_runs':sentinel_runs,
            'selected_rows':selected,'valid_champion_candidates':valid_candidates,'valid_random_controls':valid_random,
            'complete_24h_outcomes':complete24,'candidate_complete_24h':candidate_complete,'candidate_executable_10x_hits_24h':candidate_hits10,
            'random_complete_24h':random_complete,'random_executable_10x_hits_24h':random_hits10,
            'interim_ready':population>=interim['min_population_launches'] and valid_candidates>=interim['min_valid_champion_candidates'],
            'primary_sample_ready':population>=primary['min_population_launches'] and valid_candidates>=primary['min_valid_champion_candidates'] and valid_random>=primary['min_valid_random_controls'] and candidate_hits10>=primary['min_candidate_executable_10x_hits'],
            'targets':{'interim_population':interim['min_population_launches'],'primary_population':primary['min_population_launches'],
                       'primary_candidates':primary['min_valid_champion_candidates'],'primary_random_controls':primary['min_valid_random_controls']},
            'guard':'Progress only; reaching a sample gate is not evidence of profitability.'}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
