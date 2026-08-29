#!/usr/bin/env python3
"""Historical walk-forward validation of the post-model adversarial veto.

Primary question: among v1 champion top-1% 10x candidates, can the transparent
first-60s manipulation gate remove suspicious candidates while preserving rare
winners?  Thresholds and the promotion criterion live in code before this study
is run.  This script never reads prospective outcomes.
"""
from __future__ import annotations

import argparse, json, os, time
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

import scripts.github_phase2_stress60 as b
import scripts.github_phase2_stress60_lowmem as lm
import scripts.github_livecore60_v2_models as v2
from src.live.feature60 import LIVECORE_FEATURES
from src.live.adversarial_gate import assess_adversarial_risk, ADVERSARIAL_GATE_VERSION, THRESHOLDS


def js(x):
    if isinstance(x,(np.integer,)):return int(x)
    if isinstance(x,(np.floating,)):return None if not np.isfinite(x) else float(x)
    if isinstance(x,pd.Timestamp):return x.isoformat()
    return x


def fold_gate(tr:pd.DataFrame,te:pd.DataFrame)->dict:
    y=tr.hit_10x.astype(int).to_numpy()
    m=b.model();m.fit(tr[LIVECORE_FEATURES].replace([np.inf,-np.inf],np.nan),y)
    scores=m.predict_proba(te[LIVECORE_FEATURES].replace([np.inf,-np.inf],np.nan))[:,1]
    n=max(1,int(len(te)*.01));order=np.argsort(scores)[::-1][:n]
    top=te.iloc[order].copy();top['champion_score']=scores[order]
    statuses=[]
    for _,r in top.iterrows():
        a=assess_adversarial_risk(r.to_dict(),'PAPER_CANDIDATE')
        statuses.append(a.status)
    top['gate_status']=statuses
    retained=top[top.gate_status!='VETO'];vetoed=top[top.gate_status=='VETO']
    hits=int(top.hit_10x.sum());rh=int(retained.hit_10x.sum());vh=int(vetoed.hit_10x.sum())
    original_rate=hits/len(top) if len(top) else 0.0
    retained_rate=rh/len(retained) if len(retained) else 0.0
    return {
        'n_test':len(te),'top1_n':len(top),'top1_hits':hits,'top1_rate':original_rate,
        'retained_n':len(retained),'retained_hits':rh,'retained_rate':retained_rate,
        'vetoed_n':len(vetoed),'vetoed_hits':vh,'vetoed_rate':vh/len(vetoed) if len(vetoed) else None,
        'candidate_retention':len(retained)/len(top) if len(top) else None,
        'winner_retention':rh/hits if hits else None,
        'precision_ratio':retained_rate/original_rate if original_rate else None,
        'status_counts':top.gate_status.value_counts().to_dict(),
    }


def promotion_gate(folds:list[dict])->dict:
    top_n=sum(x['top1_n'] for x in folds);hits=sum(x['top1_hits'] for x in folds)
    retained_n=sum(x['retained_n'] for x in folds);retained_hits=sum(x['retained_hits'] for x in folds)
    orig=hits/top_n if top_n else 0.0;new=retained_hits/retained_n if retained_n else 0.0
    candidate_retention=retained_n/top_n if top_n else 1.0
    winner_retention=retained_hits/hits if hits else 0.0
    eligible_folds=[x for x in folds if x['top1_hits']>=3]
    fold_floor=all((x['retained_hits']/x['top1_hits'])>=.67 for x in eligible_folds)
    checks={
        'removes_at_least_5pct_candidates':candidate_retention<=.95,
        'retains_at_least_90pct_winners':winner_retention>=.90,
        'improves_precision_at_least_5pct':new>=1.05*orig if orig else False,
        'no_material_fold_winner_collapse':fold_floor,
    }
    return {
        'passed':all(checks.values()),'checks':checks,
        'top1_n':top_n,'top1_hits':hits,'original_rate':orig,
        'retained_n':retained_n,'retained_hits':retained_hits,'retained_rate':new,
        'candidate_retention':candidate_retention,'winner_retention':winner_retention,
        'precision_ratio':new/orig if orig else None,
    }


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='reports/adversarial_gate');a=ap.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);t0=time.time()
    root=Path(os.environ.get('RUNNER_TEMP','/tmp'))/'adv_gate';shards=b.acquire(root)
    c=duckdb.connect(str(root/'gate.duckdb'));c.execute("SET threads=1");c.execute("SET memory_limit='3.6GB'");c.execute("SET preserve_insertion_order=false")
    (root/'spill').mkdir(exist_ok=True);c.execute(f"SET temp_directory='{root/'spill'}'")
    tg=str(root/'trades/*.parquet');tp=str(root/'tokens.parquet');mg=str(root/'migrations.parquet');pg=str(root/'postgard_snapshots.parquet');og=str(root/'postgard_outcomes.parquet')
    c.execute(f"CREATE TABLE early60 AS SELECT mint,user_wallet,is_buy,sol_amount,token_amount,price_sol,market_cap_sol,seconds_since_launch FROM read_parquet('{tg}') WHERE seconds_since_launch BETWEEN 0 AND 60")
    c.execute(f"CREATE TABLE pre AS SELECT mint,seconds_since_launch::DOUBLE sec,price_sol::DOUBLE price FROM read_parquet('{tg}') WHERE price_sol>0 AND seconds_since_launch IS NOT NULL")
    c.execute("CREATE TABLE lp AS SELECT mint,arg_max(price,sec) p FROM pre GROUP BY mint")
    c.execute(f"CREATE TABLE post AS SELECT x.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+x.seconds_since_graduation)::DOUBLE sec,(lp.p*(x.price_usd/y.price_at_grad_usd))::DOUBLE price FROM read_parquet('{pg}') x JOIN lp USING(mint) LEFT JOIN read_parquet('{tp}') t USING(mint) LEFT JOIN read_parquet('{mg}') m USING(mint) JOIN read_parquet('{og}') y USING(mint) WHERE x.price_usd>0 AND y.price_at_grad_usd>0 AND x.seconds_since_graduation>=0 AND NOT coalesce(x.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL")
    c.execute('CREATE VIEW price_path AS SELECT * FROM pre UNION ALL SELECT * FROM post')
    panel=lm.make_panel(c,tp).merge(v2.extra_panel(c,tp),on='mint',how='left')
    p=b.labels(c,panel);p=p[p.future_points>0].copy();p.detected_at=pd.to_datetime(p.detected_at,utc=True)
    folds=[]
    for a1,b1,nm in b.FOLDS:
        tr,te,cut,end=b.fold(p,a1,b1);r=fold_gate(tr,te);r.update({'fold':nm,'cutoff':cut,'test_end':end});folds.append(r)
    gate=promotion_gate(folds)
    result={
        'gate_version':ADVERSARIAL_GATE_VERSION,'thresholds':THRESHOLDS,'target':'10x before 0.5x drawdown',
        'candidate_universe':'v1 champion top 1% score within each chronological fold',
        'folds':folds,'promotion_gate':gate,'eligible_rows':len(p),'trade_shards':len(shards),
        'elapsed_sec':time.time()-t0,
        'guard':'Historical validation only. Passing makes the veto eligible for a new prospective policy epoch; it does not rewrite prior prospective decisions.'
    }
    (out/'GATE_STUDY.json').write_text(json.dumps(result,indent=2,default=js))
    pd.DataFrame(folds).to_csv(out/'folds.csv',index=False)
    print(json.dumps({'gate_version':ADVERSARIAL_GATE_VERSION,'promotion_gate':gate,'elapsed_sec':result['elapsed_sec']},indent=2))

if __name__=='__main__':main()
