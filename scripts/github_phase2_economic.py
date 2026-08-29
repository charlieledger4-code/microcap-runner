#!/usr/bin/env python3
"""Full Phase-2 economic tail study on Slinky21 Pump.fun lifecycle data.

Principles:
- fixed decision ages: 30/60/120/180/300/600 seconds;
- reconstruct features from raw trades only up to each decision age;
- exclude System Program accounting rows from human-flow/wallet features;
- invalidate corrupted sol_amount rows for volume, while retaining valid price rows;
- stitch post-graduation native-price snapshots only after a continuity audit;
- labels are first-passage future multiples before a -50% drawdown;
- chronological train/test split with embargo;
- no peak/entry/graduation/future fields are predictors.

The result is still a historical price-path study, not a claim of executable P&L.
"""
from __future__ import annotations
import argparse, json, math, os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb
from huggingface_hub import HfApi, hf_hub_download
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss

REPO="Slinky21/Pumpfun_Memecoin_Corpus"
SYSTEM_WALLET="BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"
AGES=(30,60,120,180,300,600)
TARGETS=(2,5,10,25,50,100)
TOP_FRACS=(0.001,0.005,0.01,0.05)

FEATURE_COLS=[
 "human_trades","buys","sells","unique_wallets","unique_buyers","unique_sellers",
 "valid_volume_sol","buy_volume_sol","sell_volume_sol","buy_sell_volume_ratio",
 "recent_trades","prior_trades","recent_buyers","prior_buyers","recent_volume_sol","prior_volume_sol",
 "tx_acceleration","buyer_acceleration","volume_acceleration",
 "first_price_sol","entry_price_sol","price_return","price_range_ratio","market_cap_sol",
 "last_trade_gap_sec","creator_trades","creator_buy_volume_sol",
 "creator_past_tokens","creator_past_rugs","initial_buy_sol","initial_holder_count","initial_gini",
 "initial_top1_pct_model","initial_top5_pct_model","initial_top10_pct_model","dev_buy_pct_model",
 "launch_snipe_delta_sol","is_mayhem_mode","is_cashback_enabled","data_quality_score",
 "hour_utc","dow_utc","regime_id"
]


def hf_download(name: str, root: Path)->Path:
    root.mkdir(parents=True,exist_ok=True)
    return Path(hf_hub_download(repo_id=REPO, repo_type="dataset", filename=name, local_dir=str(root)))


def setup_data(root: Path)->dict:
    files=HfApi().list_repo_files(REPO,repo_type="dataset")
    trades=sorted(x for x in files if x.startswith("trades/") and x.endswith(".parquet"))
    core={name:hf_download(name,root) for name in ("tokens.parquet","migrations.parquet","postgard_snapshots.parquet")}
    for name in trades:
        hf_download(name,root)
    return {"root":root,"trade_files":trades,**core}


def q(con, sql):
    return con.execute(sql).fetchdf()


def jsonable(v):
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,)): return None if not np.isfinite(v) else float(v)
    if isinstance(v,(pd.Timestamp,)): return v.isoformat()
    return v


def percentile_metrics(y,score,frac):
    n=len(y); k=max(1,int(math.floor(n*frac)))
    order=np.argsort(np.asarray(score))[::-1][:k]
    base=float(np.mean(y)); sel=float(np.mean(np.asarray(y)[order]))
    positives=int(np.sum(y)); captured=int(np.sum(np.asarray(y)[order]))
    return {"fraction":frac,"n":k,"base_rate":base,"selected_rate":sel,
            "lift":sel/base if base>0 else None,"tail_recall":captured/positives if positives else None,
            "positives_selected":captured,"positives_total":positives}


def eval_scores(y,score):
    y=np.asarray(y,dtype=int); score=np.asarray(score,dtype=float)
    out={"n":len(y),"positives":int(y.sum()),"base_rate":float(y.mean()) if len(y) else None}
    if len(np.unique(y))>1:
        out.update({"average_precision":float(average_precision_score(y,score)),"roc_auc":float(roc_auc_score(y,score))})
        if np.all((score>=0)&(score<=1)):
            out["brier"]=float(brier_score_loss(y,score))
    out["enrichment"]=[percentile_metrics(y,score,f) for f in TOP_FRACS]
    return out


def random_top100(y, repeats=500, seed=20260829):
    rng=np.random.default_rng(seed); y=np.asarray(y,dtype=int); k=min(100,len(y))
    vals=[]
    if k==0: return None
    for _ in range(repeats): vals.append(float(y[rng.choice(len(y),k,replace=False)].mean()))
    a=np.array(vals)
    return {"k":k,"mean_hit_rate":float(a.mean()),"p05":float(np.quantile(a,.05)),"p50":float(np.quantile(a,.5)),"p95":float(np.quantile(a,.95))}


def fit_and_eval(df, target_col):
    df=df.sort_values("detected_at").copy()
    n=len(df); cut=max(1,int(n*.65)); cutoff=pd.to_datetime(df.iloc[cut-1].detected_at,utc=True)
    embargo_end=cutoff+pd.Timedelta(hours=3)
    tr=df[pd.to_datetime(df.detected_at,utc=True)<=cutoff].copy()
    te=df[pd.to_datetime(df.detected_at,utc=True)>=embargo_end].copy()
    ytr=tr[target_col].astype(int).to_numpy(); yte=te[target_col].astype(int).to_numpy()
    Xtr=tr[FEATURE_COLS].replace([np.inf,-np.inf],np.nan); Xte=te[FEATURE_COLS].replace([np.inf,-np.inf],np.nan)
    result={"split":{"n_train":len(tr),"n_test":len(te),"cutoff":cutoff.isoformat(),"embargo_end":embargo_end.isoformat(),
                     "train_rate":float(ytr.mean()) if len(ytr) else None,"test_rate":float(yte.mean()) if len(yte) else None}}
    # Transparent heuristic: flow + acceleration + price confirmation, with concentration penalty.
    def heuristic(x):
        z=(np.log1p(x.unique_buyers.fillna(0))*1.2 + np.log1p(x.valid_volume_sol.fillna(0))*0.7 +
           np.tanh(x.buyer_acceleration.fillna(0))*0.8 + np.tanh(x.volume_acceleration.fillna(0))*0.6 +
           np.clip(x.price_return.fillna(0),-1,3)*0.35 - np.clip(x.initial_top10_pct_model.fillna(0)/100,0,1)*0.5)
        return np.asarray(z,float)
    result["heuristic"]=eval_scores(yte,heuristic(te))
    if len(np.unique(ytr))<2 or ytr.sum()<5 or yte.sum()<1:
        result["model_note"]="insufficient positive examples for stable supervised model"
        result["random_top100"]=random_top100(yte)
        return result
    logit=Pipeline([("imp",SimpleImputer(strategy="median",add_indicator=True)),("sc",StandardScaler()),
                    ("m",LogisticRegression(max_iter=1000,class_weight="balanced",C=.15))])
    logit.fit(Xtr,ytr); pl=logit.predict_proba(Xte)[:,1]
    result["logistic"]=eval_scores(yte,pl)
    hgb=HistGradientBoostingClassifier(max_iter=180,learning_rate=.06,max_leaf_nodes=31,min_samples_leaf=40,
                                       l2_regularization=1.0,class_weight="balanced",random_state=20260829)
    hgb.fit(Xtr,ytr); ph=hgb.predict_proba(Xte)[:,1]
    result["hist_gradient_boosting"]=eval_scores(yte,ph)
    # Top-100 basket diagnostic for the target-before-drawdown event. This is path-only, pre-fee.
    idx=np.argsort(ph)[::-1][:min(100,len(te))]
    top=te.iloc[idx]
    hit=top[target_col].astype(int).to_numpy()
    policy=np.where(hit==1,float(target_col.split("x")[0]),np.where(top.drawdown_first.astype(bool).to_numpy(),.5,top.terminal_multiple.fillna(0).clip(0,float(target_col.split("x")[0])).to_numpy()))
    result["top100_path_policy"]={"n":len(top),"hits":int(hit.sum()),"gross_multiple_sum":float(policy.sum()),
                                    "mean_return_multiple":float(policy.mean()),"starting_stake_units":float(len(top)),
                                    "ending_value_units":float(policy.sum()),"note":"price-path diagnostic; excludes fees/slippage/failed fills"}
    result["random_top100"]=random_top100(yte)
    return result


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out",default="reports/economic_phase2")
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    cache=Path(os.environ.get("RUNNER_TEMP",str(Path.cwd()/"data"/"tmp")))/"microcap_economic"
    t0=time.time(); meta=setup_data(cache)
    db=cache/"economic.duckdb"; con=duckdb.connect(str(db));
    con.execute("SET threads=4"); con.execute("SET memory_limit='5GB'"); con.execute(f"SET temp_directory='{str(cache/'ducktmp')}'")
    trades_glob=str(cache/"trades"/"*.parquet").replace("'","''")
    tokens=str(cache/"tokens.parquet").replace("'","''")
    migrations=str(cache/"migrations.parquet").replace("'","''")
    post=str(cache/"postgard_snapshots.parquet").replace("'","''")
    # Corpus-level coverage/audit.
    audit={}
    audit["downloads_sec"]=time.time()-t0
    audit["trade_shards"]=len(meta["trade_files"])
    audit["tracking_minutes_quantiles"]=q(con,f"""SELECT quantile_cont(date_diff('second',detected_at,tracking_expires_at)/60.0,[.1,.25,.5,.75,.9,.95,.99]) q FROM read_parquet('{tokens}')""").iloc[0,0].tolist()
    audit["trade_quality"]=q(con,f"""SELECT count(*) total_rows, count(DISTINCT mint) traded_mints,
        count(*) FILTER(WHERE user_wallet='{SYSTEM_WALLET}') system_rows,
        count(*) FILTER(WHERE price_sol IS NULL OR price_sol<=0) bad_price_rows,
        count(*) FILTER(WHERE sol_amount IS NULL OR sol_amount<=0) bad_sol_rows,
        count(*) FILTER(WHERE sol_amount>0 AND token_amount>0 AND price_sol>0 AND sol_amount/(token_amount*price_sol) NOT BETWEEN .01 AND 100) inconsistent_sol_rows
        FROM read_parquet('{trades_glob}')""").to_dict(orient="records")[0]
    # Continuity audit: last bonding-curve price vs first valid post-grad native price.
    cont=q(con,f"""
      WITH lp AS (SELECT mint,arg_max(price_sol,seconds_since_launch) last_pre
                  FROM read_parquet('{trades_glob}') WHERE price_sol>0 GROUP BY mint),
           fp AS (SELECT mint,arg_min(price_native,seconds_since_graduation) first_post
                  FROM read_parquet('{post}') WHERE price_native>0 AND NOT coalesce(incomplete_data,false) GROUP BY mint),
           r AS (SELECT fp.mint, first_post/last_pre ratio FROM fp JOIN lp USING(mint) WHERE last_pre>0 AND first_post>0)
      SELECT count(*) n, quantile_cont(ratio,[.01,.1,.25,.5,.75,.9,.99]) q,
             avg(CASE WHEN ratio BETWEEN .1 AND 10 THEN 1 ELSE 0 END) within_10x,
             avg(CASE WHEN ratio BETWEEN .5 AND 2 THEN 1 ELSE 0 END) within_2x FROM r
    """)
    audit["postgrad_native_continuity"]={"n":int(cont.iloc[0].n),"quantiles":cont.iloc[0].q.tolist(),"within_10x":float(cont.iloc[0].within_10x),"within_2x":float(cont.iloc[0].within_2x)}
    median_ratio=audit["postgrad_native_continuity"]["quantiles"][3]
    if not (0.1 <= median_ratio <= 10):
        raise RuntimeError(f"post-grad native-price continuity failed: median ratio={median_ratio}")
    Path(out,"corpus_audit.json").write_text(json.dumps(audit,indent=2,default=jsonable))
    # Materialize a narrow valid-price path to prevent repeated 6GB projections.
    con.execute(f"""CREATE OR REPLACE TABLE pre_price AS
      SELECT mint, seconds_since_launch::DOUBLE sec, price_sol::DOUBLE price
      FROM read_parquet('{trades_glob}') WHERE price_sol IS NOT NULL AND price_sol>0 AND seconds_since_launch IS NOT NULL""")
    con.execute(f"""CREATE OR REPLACE TABLE post_price AS
      SELECT p.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+p.seconds_since_graduation)::DOUBLE sec,
             p.price_native::DOUBLE price
      FROM read_parquet('{post}') p
      LEFT JOIN read_parquet('{tokens}') t USING(mint)
      LEFT JOIN read_parquet('{migrations}') m USING(mint)
      WHERE p.price_native IS NOT NULL AND p.price_native>0 AND p.seconds_since_graduation IS NOT NULL
        AND NOT coalesce(p.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL""")
    con.execute("CREATE OR REPLACE VIEW price_path AS SELECT * FROM pre_price UNION ALL SELECT * FROM post_price")
    results={"audit":audit,"ages":{}}
    for age in AGES:
        print(f"=== age {age}s ===",flush=True); half=age/2.0
        # Human microstructure up to the decision time. Invalid sol_amount rows do not contribute volume.
        sql=f"""
        WITH tok AS (
          SELECT mint,detected_at,creator,creator_past_tokens,creator_past_rugs,initial_buy_sol,initial_holder_count,initial_gini,
            CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top1_pct_corrected,initial_top1_pct) END initial_top1_pct_model,
            CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top5_pct_corrected,initial_top5_pct) END initial_top5_pct_model,
            CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top10_pct_corrected,initial_top10_pct) END initial_top10_pct_model,
            coalesce(dev_buy_pct_corrected,dev_buy_pct) dev_buy_pct_model,launch_snipe_delta_sol,
            CAST(coalesce(is_mayhem_mode,false) AS INTEGER) is_mayhem_mode,CAST(coalesce(is_cashback_enabled,false) AS INTEGER) is_cashback_enabled,data_quality_score,
            extract(hour from detected_at)::INTEGER hour_utc,extract(dow from detected_at)::INTEGER dow_utc,
            CASE WHEN detected_at < TIMESTAMPTZ '2026-06-10' THEN 0 WHEN detected_at < TIMESTAMPTZ '2026-06-21' THEN 1
                 WHEN detected_at < TIMESTAMPTZ '2026-06-24' THEN 2 WHEN detected_at < TIMESTAMPTZ '2026-07-04' THEN 3 ELSE 4 END regime_id
          FROM read_parquet('{tokens}')
        ), t AS (
          SELECT r.*, tok.creator,
            (r.user_wallet <> '{SYSTEM_WALLET}') human,
            (r.sol_amount>0 AND r.token_amount>0 AND r.price_sol>0 AND r.sol_amount/(r.token_amount*r.price_sol) BETWEEN .01 AND 100) valid_sol
          FROM read_parquet('{trades_glob}') r JOIN tok USING(mint) WHERE r.seconds_since_launch BETWEEN 0 AND {age}
        ), agg AS (
          SELECT mint,
            count(*) FILTER(WHERE human) human_trades,
            count(*) FILTER(WHERE human AND is_buy) buys,count(*) FILTER(WHERE human AND NOT is_buy) sells,
            count(DISTINCT user_wallet) FILTER(WHERE human) unique_wallets,
            count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy) unique_buyers,
            count(DISTINCT user_wallet) FILTER(WHERE human AND NOT is_buy) unique_sellers,
            sum(CASE WHEN human AND valid_sol THEN sol_amount ELSE 0 END) valid_volume_sol,
            sum(CASE WHEN human AND valid_sol AND is_buy THEN sol_amount ELSE 0 END) buy_volume_sol,
            sum(CASE WHEN human AND valid_sol AND NOT is_buy THEN sol_amount ELSE 0 END) sell_volume_sol,
            count(*) FILTER(WHERE human AND seconds_since_launch>{half}) recent_trades,
            count(*) FILTER(WHERE human AND seconds_since_launch<={half}) prior_trades,
            count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy AND seconds_since_launch>{half}) recent_buyers,
            count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy AND seconds_since_launch<={half}) prior_buyers,
            sum(CASE WHEN human AND valid_sol AND seconds_since_launch>{half} THEN sol_amount ELSE 0 END) recent_volume_sol,
            sum(CASE WHEN human AND valid_sol AND seconds_since_launch<={half} THEN sol_amount ELSE 0 END) prior_volume_sol,
            arg_min(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) first_price_sol,
            arg_max(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) entry_price_sol,
            min(price_sol) FILTER(WHERE price_sol>0) min_price_sol,max(price_sol) FILTER(WHERE price_sol>0) max_price_sol,
            arg_max(market_cap_sol,seconds_since_launch) FILTER(WHERE market_cap_sol>0) market_cap_sol,
            max(seconds_since_launch) FILTER(WHERE human) last_human_sec,
            count(*) FILTER(WHERE human AND user_wallet=creator) creator_trades,
            sum(CASE WHEN human AND user_wallet=creator AND is_buy AND valid_sol THEN sol_amount ELSE 0 END) creator_buy_volume_sol
          FROM t GROUP BY mint
        )
        SELECT tok.*, {age}::INTEGER decision_age_sec, agg.*,
          buy_volume_sol/(sell_volume_sol+0.01) buy_sell_volume_ratio,
          (recent_trades-prior_trades)/(prior_trades+1.0) tx_acceleration,
          (recent_buyers-prior_buyers)/(prior_buyers+1.0) buyer_acceleration,
          (recent_volume_sol-prior_volume_sol)/(prior_volume_sol+0.01) volume_acceleration,
          entry_price_sol/first_price_sol-1 price_return,max_price_sol/nullif(min_price_sol,0) price_range_ratio,
          {age}-last_human_sec last_trade_gap_sec
        FROM tok JOIN agg USING(mint) WHERE agg.entry_price_sol>0
        """
        feat=q(con,sql)
        # Future path labels. One path scan/join per age keeps peak memory bounded.
        con.register("entries_df",feat[["mint","entry_price_sol"]])
        lbl=q(con,f"""
          WITH fut AS (
            SELECT e.mint,p.sec,p.price,e.entry_price_sol,p.price/e.entry_price_sol mult
            FROM entries_df e JOIN price_path p ON p.mint=e.mint WHERE p.sec>{age} AND p.price>0
          ), a AS (
            SELECT mint,max(mult) max_future_multiple,arg_max(mult,sec) terminal_multiple,
              min(sec) FILTER(WHERE mult<=.5) drawdown_time,
              min(sec) FILTER(WHERE mult>=2) t2,min(sec) FILTER(WHERE mult>=5) t5,min(sec) FILTER(WHERE mult>=10) t10,
              min(sec) FILTER(WHERE mult>=25) t25,min(sec) FILTER(WHERE mult>=50) t50,min(sec) FILTER(WHERE mult>=100) t100,
              max(sec) last_future_sec,count(*) future_price_points
            FROM fut GROUP BY mint
          )
          SELECT e.mint,coalesce(a.max_future_multiple,0) max_future_multiple,coalesce(a.terminal_multiple,0) terminal_multiple,
             a.last_future_sec,coalesce(a.future_price_points,0) future_price_points,a.drawdown_time,
             (a.drawdown_time IS NOT NULL) drawdown_first,
             (t2 IS NOT NULL AND (drawdown_time IS NULL OR t2<drawdown_time)) hit_2x,
             (t5 IS NOT NULL AND (drawdown_time IS NULL OR t5<drawdown_time)) hit_5x,
             (t10 IS NOT NULL AND (drawdown_time IS NULL OR t10<drawdown_time)) hit_10x,
             (t25 IS NOT NULL AND (drawdown_time IS NULL OR t25<drawdown_time)) hit_25x,
             (t50 IS NOT NULL AND (drawdown_time IS NULL OR t50<drawdown_time)) hit_50x,
             (t100 IS NOT NULL AND (drawdown_time IS NULL OR t100<drawdown_time)) hit_100x
          FROM entries_df e LEFT JOIN a USING(mint)
        """)
        con.unregister("entries_df")
        panel=feat.merge(lbl,on="mint",how="left")
        for c in [f"hit_{t}x" for t in TARGETS]: panel[c]=panel[c].fillna(False).astype(bool)
        panel["drawdown_first"]=panel["drawdown_first"].fillna(False).astype(bool)
        panel["max_future_multiple"]=panel.max_future_multiple.fillna(0); panel["terminal_multiple"]=panel.terminal_multiple.fillna(0)
        # Preserve an aggregated, auditable panel rather than source raw data.
        panel.to_parquet(out/f"panel_age_{age}s.parquet",index=False)
        age_res={"eligible_tokens":len(panel),"label_rates":{f"hit_{t}x":float(panel[f'hit_{t}x'].mean()) for t in TARGETS},"models":{}}
        for target in TARGETS:
            col=f"hit_{target}x"; print(f"  target {target}x positives={int(panel[col].sum())}",flush=True)
            age_res["models"][col]=fit_and_eval(panel,col)
        results["ages"][str(age)]=age_res
        Path(out,"economic_metrics_partial.json").write_text(json.dumps(results,indent=2,default=jsonable))
    results["elapsed_sec"]=time.time()-t0
    Path(out,"economic_metrics.json").write_text(json.dumps(results,indent=2,default=jsonable))
    # Compact headline table: best HGB top-1% enrichment per age/target.
    rows=[]
    for age,ar in results["ages"].items():
      for col,mr in ar["models"].items():
        h=mr.get("hist_gradient_boosting")
        if not h: continue
        top1=next(x for x in h["enrichment"] if abs(x["fraction"]-.01)<1e-9)
        rows.append({"age_sec":int(age),"target":col,"base_rate":h["base_rate"],"top1_rate":top1["selected_rate"],"top1_lift":top1["lift"],
                     "test_positives":h["positives"],"ap":h.get("average_precision"),"auc":h.get("roc_auc"),
                     "top100_hits":mr.get("top100_path_policy",{}).get("hits"),"top100_end_units":mr.get("top100_path_policy",{}).get("ending_value_units")})
    pd.DataFrame(rows).to_csv(out/"headline_enrichment.csv",index=False)
    print(json.dumps({"elapsed_sec":results["elapsed_sec"],"headline_rows":rows},indent=2,default=jsonable))

if __name__=="__main__": main()
