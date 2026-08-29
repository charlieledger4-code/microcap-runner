#!/usr/bin/env python3
"""Stress-test and freeze a 60s model using only fields reconstructable from free live launch + on-chain trade events.

This is intentionally separate from the already-frozen full 41-feature research model.
No prospective outcomes are consumed by this script.
"""
import argparse, hashlib, json, os, time
from pathlib import Path
import joblib
import duckdb
import numpy as np
import pandas as pd

import scripts.github_phase2_stress60 as b
import scripts.github_phase2_stress60_lowmem as lm

# Exact live-core contract. Every field can be constructed from:
# - PumpPortal free subscribeNewToken payload (launch metadata), or
# - Pump TradeEvent CPI data fetched from Solana RPC, or
# - the decision timestamp.
LIVE = [
    'human_trades','buys','sells','unique_wallets','unique_buyers','unique_sellers',
    'valid_volume_sol','buy_volume_sol','sell_volume_sol','buy_sell_volume_ratio',
    'recent_trades','prior_trades','recent_buyers','prior_buyers',
    'recent_volume_sol','prior_volume_sol','tx_acceleration','buyer_acceleration',
    'volume_acceleration','last_trade_gap_sec',
    'first_price_sol','entry_price_sol','price_return','price_range_ratio','market_cap_sol',
    'creator_trades','creator_buy_volume_sol','initial_buy_sol','is_mayhem_mode',
    'hour_utc','dow_utc',
]
TARGETS=(5,10,25,100)

def js(x):
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,)): return None if not np.isfinite(x) else float(x)
    if isinstance(x,pd.Timestamp): return x.isoformat()
    return x

def sha256(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''): h.update(chunk)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='reports/livecore60'); a=ap.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True); (out/'models').mkdir(exist_ok=True)
    root=Path(os.environ.get('RUNNER_TEMP','/tmp'))/'livecore60'; t0=time.time()
    shards=b.acquire(root)
    c=duckdb.connect(str(root/'livecore.duckdb'))
    c.execute("SET threads=1"); c.execute("SET memory_limit='3.6GB'"); c.execute("SET preserve_insertion_order=false")
    (root/'spill').mkdir(exist_ok=True); c.execute(f"SET temp_directory='{root/'spill'}'")
    tg=str(root/'trades/*.parquet'); tp=str(root/'tokens.parquet'); mg=str(root/'migrations.parquet'); pg=str(root/'postgard_snapshots.parquet'); og=str(root/'postgard_outcomes.parquet')
    c.execute(f"CREATE TABLE early60 AS SELECT mint,user_wallet,is_buy,sol_amount,token_amount,price_sol,market_cap_sol,seconds_since_launch FROM read_parquet('{tg}') WHERE seconds_since_launch BETWEEN 0 AND 60")
    c.execute(f"CREATE TABLE pre AS SELECT mint,seconds_since_launch::DOUBLE sec,price_sol::DOUBLE price FROM read_parquet('{tg}') WHERE price_sol>0 AND seconds_since_launch IS NOT NULL")
    c.execute("CREATE TABLE lp AS SELECT mint,arg_max(price,sec) p FROM pre GROUP BY mint")
    c.execute(f"CREATE TABLE post AS SELECT x.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+x.seconds_since_graduation)::DOUBLE sec,(lp.p*(x.price_usd/y.price_at_grad_usd))::DOUBLE price FROM read_parquet('{pg}') x JOIN lp USING(mint) LEFT JOIN read_parquet('{tp}') t USING(mint) LEFT JOIN read_parquet('{mg}') m USING(mint) JOIN read_parquet('{og}') y USING(mint) WHERE x.price_usd>0 AND y.price_at_grad_usd>0 AND x.seconds_since_graduation>=0 AND NOT coalesce(x.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL")
    c.execute('CREATE VIEW price_path AS SELECT * FROM pre UNION ALL SELECT * FROM post')
    p=b.labels(c,lm.make_panel(c,tp)); p=p[p.future_points>0].copy(); p.detected_at=pd.to_datetime(p.detected_at,utc=True)
    missing=[x for x in LIVE if x not in p.columns]
    if missing: raise RuntimeError(f'live-core feature contract missing columns: {missing}')

    rows=[]; folds={}
    for a1,b1,nm in b.FOLDS:
        tr,te,cut,end=b.fold(p,a1,b1); fr={'cutoff':cut,'test_end':end,'n_train':len(tr),'n_test':len(te),'targets':{}}
        for target in TARGETS:
            col=f'hit_{target}x'
            live=b.score(tr,te,LIVE,col)
            full=b.score(tr,te,b.ALL,col)
            fr['targets'][str(target)]={'live_core':live,'full_reference':full}
            for name,v in [('live_core',live),('full_reference',full)]:
                if v and v.get('top1'):
                    rows.append({'fold':nm,'target':target,'model':name,'n_test':v['n'],'base_rate':v['base_rate'],'top1_rate':v['top1']['rate'],'top1_lift':v['top1']['lift'],'top100_hits':v['top100']['hits'],'auc':v.get('auc'),'ap':v.get('ap')})
        folds[nm]=fr
    df=pd.DataFrame(rows); df.to_csv(out/'folds.csv',index=False)
    summary=[]
    for (target,name),g in df.groupby(['target','model']):
        summary.append({'target':int(target),'model':name,'folds':len(g),'median_top1_lift':float(g.top1_lift.median()),'min_top1_lift':float(g.top1_lift.min()),'max_top1_lift':float(g.top1_lift.max()),'sum_top100_hits':int(g.top100_hits.sum()),'aggregate_selected':int((g.n_test*.01).astype(int).clip(lower=1).sum())})
    pd.DataFrame(summary).to_csv(out/'summary.csv',index=False)

    manifest={'decision_age_seconds':60,'model_family':'HistGradientBoostingClassifier inside median-imputation Pipeline','feature_contract':'live_core_free_v1','features':LIVE,'rows':len(p),'trade_shards':len(shards),'historical_first_detected_at':str(p.detected_at.min()),'historical_last_detected_at':str(p.detected_at.max()),'source_repo':b.REPO,'random_state':20260829,'targets':{},'fold_summary':summary,'guard':'This model is frozen before consuming any prospective trade outcomes. Thresholds are training-score quantiles, not calibrated probabilities.'}
    X=p[LIVE].replace([np.inf,-np.inf],np.nan)
    for target in TARGETS:
        y=p[f'hit_{target}x'].astype(int).to_numpy(); m=b.model(); m.fit(X,y); score=m.predict_proba(X)[:,1]
        f=out/'models'/f'hgb_livecore_60s_{target}x.joblib'; joblib.dump(m,f,compress=3)
        manifest['targets'][str(target)]={'positives':int(y.sum()),'base_rate':float(y.mean()),'model_file':f.name,'model_sha256':sha256(f),'score_thresholds':{str(q):float(np.quantile(score,q)) for q in (.95,.99,.995,.999)}}
    manifest['elapsed_sec']=time.time()-t0
    (out/'LIVECORE_MANIFEST.json').write_text(json.dumps(manifest,indent=2,default=js))
    (out/'LIVECORE_POLICY.md').write_text('''# Frozen free-live 60-second policy\n\n- Decision age: 60 seconds after observed launch.\n- Inputs: only launch metadata, Pump TradeEvent data obtainable from Solana, and UTC decision time.\n- No holder API, creator-history vendor feed, social data, or prospective outcomes are required.\n- Targets: 5x, 10x, 25x, 100x before -50% drawdown.\n- Primary rank: 10x live-core score. Secondary tail rank: 100x live-core score.\n- Candidate thresholds come only from LIVECORE_MANIFEST.json and may not be tuned on an open prospective batch.\n- Full 41-feature frozen model remains a separate research reference; it must not be silently mixed with this model.\n- Paper-only. No real-money execution is authorized.\n''')
    print(json.dumps({'rows':len(p),'summary':summary,'elapsed_sec':manifest['elapsed_sec']},indent=2))

if __name__=='__main__': main()
