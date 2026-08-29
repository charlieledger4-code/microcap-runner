#!/usr/bin/env python3
"""Train/stress a live-core v2 challenger with manipulation-resistant flow features.

The v1 frozen model remains champion. This script uses historical data only and
applies a predeclared promotion gate; prospective outcomes are never read here.
"""
from __future__ import annotations

import argparse, hashlib, json, os, time
from pathlib import Path
import joblib
import duckdb
import numpy as np
import pandas as pd

import scripts.github_phase2_stress60 as b
import scripts.github_phase2_stress60_lowmem as lm
from src.live.feature60 import LIVECORE_FEATURES
from src.live.feature60_v2 import LIVECORE_V2_EXTRA_FEATURES, LIVECORE_V2_FEATURES

TARGETS=(5,10,25,100)
SYS2='11111111111111111111111111111111'


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


def extra_panel(c: duckdb.DuckDBPyConnection, tp: str) -> pd.DataFrame:
    return c.execute(f"""
    WITH tok AS (
      SELECT mint,creator FROM read_parquet('{tp}')
    ), x AS (
      SELECT e.*,tok.creator,
        (e.user_wallet NOT IN ('{b.SYS}','{SYS2}')) human,
        (e.sol_amount>0 AND e.token_amount>0 AND e.price_sol>0
          AND e.sol_amount/(e.token_amount*e.price_sol) BETWEEN .01 AND 100) valid_sol
      FROM early60 e JOIN tok USING(mint)
    ), w AS (
      SELECT mint,user_wallet,
        sum(CASE WHEN valid_sol AND is_buy THEN sol_amount ELSE 0 END) buy_vol,
        max(CASE WHEN is_buy THEN 1 ELSE 0 END) has_buy,
        max(CASE WHEN NOT is_buy THEN 1 ELSE 0 END) has_sell,
        max(CASE WHEN is_buy AND seconds_since_launch<=30 THEN 1 ELSE 0 END) prior_buy,
        max(CASE WHEN is_buy AND seconds_since_launch>30 THEN 1 ELSE 0 END) recent_buy
      FROM x WHERE human GROUP BY mint,user_wallet
    ), w0 AS (
      SELECT *,sum(buy_vol) OVER(PARTITION BY mint) total_buy,
        count(*) FILTER(WHERE buy_vol>0) OVER(PARTITION BY mint) positive_buyers,
        row_number() OVER(PARTITION BY mint ORDER BY buy_vol DESC,user_wallet) rn
      FROM w
    ), wg AS (
      SELECT mint,
        sum(CASE WHEN buy_vol>0 AND total_buy>0 THEN pow(buy_vol/total_buy,2) ELSE 0 END) buyer_volume_hhi,
        CASE WHEN sum(CASE WHEN buy_vol>0 AND total_buy>0 THEN pow(buy_vol/total_buy,2) ELSE 0 END)>0
          THEN 1.0/sum(CASE WHEN buy_vol>0 AND total_buy>0 THEN pow(buy_vol/total_buy,2) ELSE 0 END) ELSE 0 END effective_buyers,
        CASE WHEN max(positive_buyers)>1 THEN
          -sum(CASE WHEN buy_vol>0 AND total_buy>0 THEN (buy_vol/total_buy)*ln(buy_vol/total_buy) ELSE 0 END)/ln(max(positive_buyers))
          ELSE 0 END buyer_volume_entropy,
        max(CASE WHEN rn=1 AND total_buy>0 THEN buy_vol/total_buy ELSE 0 END) top_buyer_volume_share,
        sum(CASE WHEN rn<=3 THEN buy_vol ELSE 0 END)/nullif(max(total_buy),0) top3_buyer_volume_share,
        sum(CASE WHEN has_buy=1 AND has_sell=1 THEN 1 ELSE 0 END)::DOUBLE/count(*) roundtrip_wallet_share,
        sum(CASE WHEN recent_buy=1 AND prior_buy=0 THEN 1 ELSE 0 END) recent_new_buyers,
        sum(CASE WHEN recent_buy=1 THEN 1 ELSE 0 END) recent_buyer_wallets
      FROM w0 GROUP BY mint
    ), bg AS (
      SELECT mint,
        count(*) FILTER(WHERE human AND is_buy) buys2,
        count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy) unique_buyers2,
        sum(CASE WHEN human AND valid_sol AND is_buy THEN sol_amount ELSE 0 END) buy_vol,
        sum(CASE WHEN human AND valid_sol AND NOT is_buy THEN sol_amount ELSE 0 END) sell_vol,
        sum(CASE WHEN human AND valid_sol AND is_buy AND user_wallet=creator THEN sol_amount ELSE 0 END) creator_buy_vol,
        count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy AND seconds_since_launch<=10) first10_unique_buyers,
        sum(CASE WHEN human AND valid_sol AND seconds_since_launch<=10 THEN sol_amount ELSE 0 END) first10_volume_sol,
        median(sol_amount) FILTER(WHERE human AND valid_sol AND is_buy) median_buy_sol,
        max(sol_amount) FILTER(WHERE human AND valid_sol AND is_buy) max_buy_sol,
        avg(sol_amount) FILTER(WHERE human AND valid_sol AND is_buy) avg_buy_sol,
        stddev_pop(sol_amount) FILTER(WHERE human AND valid_sol AND is_buy) sd_buy_sol,
        count(DISTINCT least(floor(seconds_since_launch/5),11)) FILTER(WHERE human) active_5s_bins,
        count(*) FILTER(WHERE human) human_trades2,
        arg_min(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) first_p,
        arg_max(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) entry_p,
        arg_max(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0 AND seconds_since_launch<=30) p30,
        max(price_sol) FILTER(WHERE price_sol>0) peak_p
      FROM x GROUP BY mint
    ), bins AS (
      SELECT mint,least(floor(seconds_since_launch/5),11) bin,count(*) n
      FROM x WHERE human GROUP BY mint,bin
    ), binmax AS (SELECT mint,max(n) max_5s_trade_count FROM bins GROUP BY mint)
    SELECT bg.mint,
      unique_buyers2/(buys2+1e-12) unique_buyer_trade_ratio,
      (buy_vol-sell_vol)/(buy_vol+sell_vol+.01) net_buy_volume_ratio,
      creator_buy_vol/(buy_vol+.01) creator_buy_share,
      coalesce(wg.buyer_volume_hhi,0) buyer_volume_hhi,
      coalesce(wg.effective_buyers,0) effective_buyers,
      coalesce(wg.buyer_volume_entropy,0) buyer_volume_entropy,
      coalesce(wg.top_buyer_volume_share,0) top_buyer_volume_share,
      coalesce(wg.top3_buyer_volume_share,0) top3_buyer_volume_share,
      coalesce(wg.roundtrip_wallet_share,0) roundtrip_wallet_share,
      first10_unique_buyers,first10_volume_sol,
      coalesce(wg.recent_new_buyers,0) recent_new_buyers,
      coalesce(wg.recent_new_buyers,0)/(coalesce(wg.recent_buyer_wallets,0)+1e-12) recent_new_buyer_share,
      coalesce(median_buy_sol,0) median_buy_sol,coalesce(max_buy_sol,0) max_buy_sol,
      CASE WHEN avg_buy_sol>0 THEN coalesce(sd_buy_sol,0)/avg_buy_sol ELSE 0 END buy_size_cv,
      active_5s_bins,coalesce(binmax.max_5s_trade_count,0) max_5s_trade_count,
      coalesce(binmax.max_5s_trade_count,0)/(human_trades2+1e-12) trade_burst_ratio,
      entry_p/nullif(peak_p,0)-1 peak_to_entry_drawdown,
      p30/nullif(first_p,0)-1 first30_return,
      entry_p/nullif(p30,0)-1 recent30_return,
      (entry_p/nullif(p30,0)-1)-(p30/nullif(first_p,0)-1) return_acceleration
    FROM bg LEFT JOIN wg USING(mint) LEFT JOIN binmax USING(mint)
    """).fetchdf()


def promotion_gate(df: pd.DataFrame) -> dict:
    """Predeclared historical gate for challenger eligibility.

    Primary objective is 10x top-1% enrichment. V2 must improve median lift by
    >=5%, retain at least 75% of v1 lift in every fold, keep minimum lift >=1.5,
    and capture at least as many aggregate top-1% 10x hits.
    """
    g=df[df.target==10]
    v1=g[g.model=='v1'].set_index('fold'); v2=g[g.model=='v2'].set_index('fold')
    common=sorted(set(v1.index)&set(v2.index))
    if len(common)<4:
        return {'passed':False,'reason':'missing comparable folds'}
    a=v1.loc[common]; z=v2.loc[common]
    checks={
        'median_lift_improves_5pct':float(z.top1_lift.median()) >= 1.05*float(a.top1_lift.median()),
        'min_lift_at_least_1_5':float(z.top1_lift.min()) >= 1.5,
        'no_fold_below_75pct_v1':bool((z.top1_lift >= .75*a.top1_lift).all()),
        'aggregate_top1_hits_not_worse':int(z.top1_hits.sum()) >= int(a.top1_hits.sum()),
    }
    return {
        'passed':all(checks.values()),'checks':checks,
        'v1_median_lift':float(a.top1_lift.median()),'v2_median_lift':float(z.top1_lift.median()),
        'v1_min_lift':float(a.top1_lift.min()),'v2_min_lift':float(z.top1_lift.min()),
        'v1_top1_hits':int(a.top1_hits.sum()),'v2_top1_hits':int(z.top1_hits.sum()),
    }


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='reports/livecore60_v2');args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);(out/'models').mkdir(exist_ok=True)
    root=Path(os.environ.get('RUNNER_TEMP','/tmp'))/'livecore60_v2';t0=time.time();shards=b.acquire(root)
    c=duckdb.connect(str(root/'v2.duckdb'));c.execute("SET threads=1");c.execute("SET memory_limit='3.6GB'");c.execute("SET preserve_insertion_order=false")
    (root/'spill').mkdir(exist_ok=True);c.execute(f"SET temp_directory='{root/'spill'}'")
    tg=str(root/'trades/*.parquet');tp=str(root/'tokens.parquet');mg=str(root/'migrations.parquet');pg=str(root/'postgard_snapshots.parquet');og=str(root/'postgard_outcomes.parquet')
    c.execute(f"CREATE TABLE early60 AS SELECT mint,user_wallet,is_buy,sol_amount,token_amount,price_sol,market_cap_sol,seconds_since_launch FROM read_parquet('{tg}') WHERE seconds_since_launch BETWEEN 0 AND 60")
    c.execute(f"CREATE TABLE pre AS SELECT mint,seconds_since_launch::DOUBLE sec,price_sol::DOUBLE price FROM read_parquet('{tg}') WHERE price_sol>0 AND seconds_since_launch IS NOT NULL")
    c.execute("CREATE TABLE lp AS SELECT mint,arg_max(price,sec) p FROM pre GROUP BY mint")
    c.execute(f"CREATE TABLE post AS SELECT x.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+x.seconds_since_graduation)::DOUBLE sec,(lp.p*(x.price_usd/y.price_at_grad_usd))::DOUBLE price FROM read_parquet('{pg}') x JOIN lp USING(mint) LEFT JOIN read_parquet('{tp}') t USING(mint) LEFT JOIN read_parquet('{mg}') m USING(mint) JOIN read_parquet('{og}') y USING(mint) WHERE x.price_usd>0 AND y.price_at_grad_usd>0 AND x.seconds_since_graduation>=0 AND NOT coalesce(x.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL")
    c.execute('CREATE VIEW price_path AS SELECT * FROM pre UNION ALL SELECT * FROM post')

    base=lm.make_panel(c,tp); extra=extra_panel(c,tp); panel=base.merge(extra,on='mint',how='left')
    missing=[x for x in LIVECORE_V2_FEATURES if x not in panel.columns]
    if missing: raise RuntimeError(f'v2 feature contract missing: {missing}')
    p=b.labels(c,panel);p=p[p.future_points>0].copy();p.detected_at=pd.to_datetime(p.detected_at,utc=True)

    rows=[];folds={}
    for a1,b1,nm in b.FOLDS:
        tr,te,cut,end=b.fold(p,a1,b1); fr={'cutoff':cut,'test_end':end,'n_train':len(tr),'n_test':len(te),'targets':{}}
        for target in TARGETS:
            col=f'hit_{target}x'; one={}
            for name,features in [('v1',LIVECORE_FEATURES),('v2',LIVECORE_V2_FEATURES)]:
                m=b.score(tr,te,features,col);one[name]=m
                if m and m.get('top1'):
                    rows.append({'fold':nm,'target':target,'model':name,'n_test':m['n'],'base_rate':m['base_rate'],'top1_hits':m['top1']['hits'],'top1_rate':m['top1']['rate'],'top1_lift':m['top1']['lift'],'top100_hits':m['top100']['hits'],'auc':m.get('auc'),'ap':m.get('ap')})
            fr['targets'][str(target)]=one
        folds[nm]=fr
    df=pd.DataFrame(rows);df.to_csv(out/'folds.csv',index=False);gate=promotion_gate(df)

    manifest={'decision_age_seconds':60,'model_family':'HistGradientBoostingClassifier','feature_contract':'live_core_free_v2_challenger','features':LIVECORE_V2_FEATURES,'extra_features':LIVECORE_V2_EXTRA_FEATURES,'rows':len(p),'trade_shards':len(shards),'historical_first_detected_at':str(p.detected_at.min()),'historical_last_detected_at':str(p.detected_at.max()),'source_repo':b.REPO,'promotion_gate':gate,'targets':{},'guard':'Historical challenger only. V1 remains champion; v2 cannot replace it without this historical gate plus a separate prospective challenger evaluation.'}
    X=p[LIVECORE_V2_FEATURES].replace([np.inf,-np.inf],np.nan)
    for target in TARGETS:
        y=p[f'hit_{target}x'].astype(int).to_numpy();m=b.model();m.fit(X,y);score=m.predict_proba(X)[:,1]
        f=out/'models'/f'hgb_livecore_v2_60s_{target}x.joblib';joblib.dump(m,f,compress=3)
        manifest['targets'][str(target)]={'positives':int(y.sum()),'base_rate':float(y.mean()),'model_file':f.name,'model_sha256':sha256(f),'score_thresholds':{str(q):float(np.quantile(score,q)) for q in (.95,.99,.995,.999)}}
    manifest['elapsed_sec']=time.time()-t0
    (out/'V2_MANIFEST.json').write_text(json.dumps(manifest,indent=2,default=js))
    (out/'V2_GATE.json').write_text(json.dumps(gate,indent=2))
    print(json.dumps({'rows':len(p),'gate':gate,'elapsed_sec':manifest['elapsed_sec']},indent=2))

if __name__=='__main__':main()
