#!/usr/bin/env python3
"""Leakage-safe fixed-age economic tail study, v2.

Post-graduation paths are stitched by relative USD return from the recorded
price-at-graduation, anchored to the last valid bonding-curve SOL price. This
avoids treating DEX quote-unit discontinuities as fake 10x/100x events.
"""
from __future__ import annotations
import argparse,json,math,os,time
from pathlib import Path
import numpy as np,pandas as pd,duckdb
from huggingface_hub import HfApi,hf_hub_download
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss

REPO="Slinky21/Pumpfun_Memecoin_Corpus"
SYSTEM="BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"
AGES=(30,60,120,180,300,600); TARGETS=(2,5,10,25,50,100); FRACS=(.001,.005,.01,.05)
FEATURES=[
 "human_trades","buys","sells","unique_wallets","unique_buyers","unique_sellers",
 "valid_volume_sol","buy_volume_sol","sell_volume_sol","buy_sell_volume_ratio",
 "recent_trades","prior_trades","recent_buyers","prior_buyers","recent_volume_sol","prior_volume_sol",
 "tx_acceleration","buyer_acceleration","volume_acceleration","first_price_sol","entry_price_sol",
 "price_return","price_range_ratio","market_cap_sol","last_trade_gap_sec","creator_trades","creator_buy_volume_sol",
 "creator_past_tokens","creator_past_rugs","initial_buy_sol","initial_holder_count","initial_gini",
 "initial_top1_pct_model","initial_top5_pct_model","initial_top10_pct_model","dev_buy_pct_model",
 "launch_snipe_delta_sol","is_mayhem_mode","is_cashback_enabled","hour_utc","dow_utc"
]

def dl(name,root):
 root.mkdir(parents=True,exist_ok=True); return Path(hf_hub_download(repo_id=REPO,repo_type="dataset",filename=name,local_dir=str(root)))

def acquire(root):
 files=HfApi().list_repo_files(REPO,repo_type="dataset"); shards=sorted(x for x in files if x.startswith("trades/") and x.endswith(".parquet"))
 for x in ("tokens.parquet","migrations.parquet","postgard_snapshots.parquet","postgard_outcomes.parquet"): dl(x,root)
 for x in shards: dl(x,root)
 return shards

def q(c,s): return c.execute(s).fetchdf()
def js(x):
 if isinstance(x,(np.integer,)): return int(x)
 if isinstance(x,(np.floating,)): return None if not np.isfinite(x) else float(x)
 if isinstance(x,pd.Timestamp): return x.isoformat()
 return x

def enrich(y,s,f):
 y=np.asarray(y,int);s=np.asarray(s,float);k=max(1,int(len(y)*f));idx=np.argsort(s)[::-1][:k];b=float(y.mean());r=float(y[idx].mean());pos=int(y.sum());cap=int(y[idx].sum())
 return {"fraction":f,"n":k,"base_rate":b,"selected_rate":r,"lift":r/b if b else None,"tail_recall":cap/pos if pos else None,"positives_selected":cap,"positives_total":pos}
def evaluate(y,s):
 y=np.asarray(y,int);s=np.asarray(s,float);o={"n":len(y),"positives":int(y.sum()),"base_rate":float(y.mean()),"enrichment":[enrich(y,s,f) for f in FRACS]}
 if len(np.unique(y))>1:
  o["average_precision"]=float(average_precision_score(y,s));o["roc_auc"]=float(roc_auc_score(y,s))
  if np.all((s>=0)&(s<=1)):o["brier"]=float(brier_score_loss(y,s))
 return o
def random100(y,n=1000):
 y=np.asarray(y,int);k=min(100,len(y));rng=np.random.default_rng(20260829);a=np.array([y[rng.choice(len(y),k,False)].mean() for _ in range(n)])
 return {"k":k,"mean_rate":float(a.mean()),"p05":float(np.quantile(a,.05)),"p50":float(np.quantile(a,.5)),"p95":float(np.quantile(a,.95))}
def model(df,target):
 col=f"hit_{target}x";df=df.sort_values("detected_at").copy();cut=max(1,int(len(df)*.65));ct=pd.to_datetime(df.iloc[cut-1].detected_at,utc=True);ee=ct+pd.Timedelta(hours=3)
 dt=pd.to_datetime(df.detected_at,utc=True);tr=df[dt<=ct].copy();te=df[dt>=ee].copy();yt=tr[col].astype(int).to_numpy();yv=te[col].astype(int).to_numpy();X=tr[FEATURES].replace([np.inf,-np.inf],np.nan);V=te[FEATURES].replace([np.inf,-np.inf],np.nan)
 o={"split":{"n_train":len(tr),"n_test":len(te),"cutoff":ct.isoformat(),"embargo_end":ee.isoformat(),"train_rate":float(yt.mean()),"test_rate":float(yv.mean())},"random_top100":random100(yv)}
 hs=np.log1p(te.unique_buyers.fillna(0))*1.2+np.log1p(te.valid_volume_sol.fillna(0))*.7+np.tanh(te.buyer_acceleration.fillna(0))*.8+np.tanh(te.volume_acceleration.fillna(0))*.6+np.clip(te.price_return.fillna(0),-1,3)*.35-np.clip(te.initial_top10_pct_model.fillna(0)/100,0,1)*.5
 o["heuristic"]=evaluate(yv,hs)
 if len(np.unique(yt))<2 or yt.sum()<5 or yv.sum()<1:return o
 lr=Pipeline([("i",SimpleImputer(strategy="median",add_indicator=True)),("s",StandardScaler()),("m",LogisticRegression(max_iter=1000,class_weight="balanced",C=.15))]);lr.fit(X,yt);o["logistic"]=evaluate(yv,lr.predict_proba(V)[:,1])
 gb=HistGradientBoostingClassifier(max_iter=180,learning_rate=.06,max_leaf_nodes=31,min_samples_leaf=40,l2_regularization=1,class_weight="balanced",random_state=20260829);gb.fit(X,yt);p=gb.predict_proba(V)[:,1];o["hist_gradient_boosting"]=evaluate(yv,p)
 ix=np.argsort(p)[::-1][:min(100,len(te))];top=te.iloc[ix];hit=top[col].astype(int).to_numpy();pol=np.where(hit==1,float(target),np.where(top.drawdown_first.astype(bool).to_numpy(),.5,top.terminal_multiple.fillna(0).clip(0,float(target)).to_numpy()))
 o["top100_path_policy"]={"n":len(top),"hits":int(hit.sum()),"start_units":float(len(top)),"end_units":float(pol.sum()),"mean_multiple":float(pol.mean()),"note":"historical price path only; no fees/slippage/fill failures"}
 return o

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--out",default="reports/economic_phase2_v2");a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True);root=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"microcap_econ_v2";t0=time.time();shards=acquire(root)
 con=duckdb.connect(str(root/"e.duckdb"));con.execute("SET threads=4");con.execute("SET memory_limit='5GB'");(root/"spill").mkdir(exist_ok=True);con.execute(f"SET temp_directory='{root/'spill'}'")
 tg=str(root/"trades/*.parquet");tp=str(root/"tokens.parquet");mg=str(root/"migrations.parquet");pg=str(root/"postgard_snapshots.parquet");og=str(root/"postgard_outcomes.parquet")
 audit={"download_sec":time.time()-t0,"trade_shards":len(shards)}
 audit["tracking_minutes_q"]=q(con,f"SELECT quantile_cont(date_diff('second',detected_at,tracking_expires_at)/60.0,[.1,.25,.5,.75,.9,.95,.99]) q FROM read_parquet('{tp}')").iloc[0].q.tolist()
 audit["trade_quality"]=q(con,f"""SELECT count(*) total_rows,count(DISTINCT mint) traded_mints,count(*) FILTER(WHERE user_wallet='{SYSTEM}') system_rows,count(*) FILTER(WHERE price_sol IS NULL OR price_sol<=0) bad_price_rows,count(*) FILTER(WHERE sol_amount IS NULL OR sol_amount<=0) bad_sol_rows,count(*) FILTER(WHERE sol_amount>0 AND token_amount>0 AND price_sol>0 AND sol_amount/(token_amount*price_sol) NOT BETWEEN .01 AND 100) inconsistent_sol_rows FROM read_parquet('{tg}')""").to_dict('records')[0]
 con.execute(f"CREATE TABLE pre_price AS SELECT mint,seconds_since_launch::DOUBLE sec,price_sol::DOUBLE price FROM read_parquet('{tg}') WHERE price_sol>0 AND seconds_since_launch IS NOT NULL")
 con.execute("CREATE TABLE last_pre AS SELECT mint,arg_max(price,sec) last_pre_price,max(sec) last_pre_sec FROM pre_price GROUP BY mint")
 # Two audits: raw native discontinuity and USD change from the recorded graduation anchor.
 nat=q(con,f"""WITH fp AS(SELECT mint,arg_min(price_native,seconds_since_graduation) v FROM read_parquet('{pg}') WHERE price_native>0 AND NOT coalesce(incomplete_data,false) GROUP BY mint),r AS(SELECT v/last_pre_price z FROM fp JOIN last_pre USING(mint) WHERE v>0 AND last_pre_price>0) SELECT count(*) n,quantile_cont(z,[.01,.1,.25,.5,.75,.9,.99]) q FROM r""")
 usd=q(con,f"""WITH fp AS(SELECT mint,arg_min(price_usd,seconds_since_graduation) v FROM read_parquet('{pg}') WHERE price_usd>0 AND NOT coalesce(incomplete_data,false) GROUP BY mint),r AS(SELECT fp.v/o.price_at_grad_usd z FROM fp JOIN read_parquet('{og}') o USING(mint) WHERE fp.v>0 AND o.price_at_grad_usd>0) SELECT count(*) n,quantile_cont(z,[.01,.1,.25,.5,.75,.9,.99]) q FROM r""")
 audit["raw_native_first_post_over_last_pre"]={"n":int(nat.iloc[0].n),"q":nat.iloc[0].q.tolist()};audit["first_post_usd_over_grad_usd"]={"n":int(usd.iloc[0].n),"q":usd.iloc[0].q.tolist()}
 # Label-only post-grad path: anchor relative USD moves to last valid pre-grad price.
 con.execute(f"""CREATE TABLE post_price AS SELECT p.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+p.seconds_since_graduation)::DOUBLE sec,(lp.last_pre_price*(p.price_usd/o.price_at_grad_usd))::DOUBLE price FROM read_parquet('{pg}') p JOIN last_pre lp USING(mint) LEFT JOIN read_parquet('{tp}') t USING(mint) LEFT JOIN read_parquet('{mg}') m USING(mint) JOIN read_parquet('{og}') o USING(mint) WHERE p.price_usd>0 AND o.price_at_grad_usd>0 AND p.seconds_since_graduation>=0 AND NOT coalesce(p.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL""")
 con.execute("CREATE VIEW price_path AS SELECT * FROM pre_price UNION ALL SELECT * FROM post_price")
 Path(out,"corpus_audit.json").write_text(json.dumps(audit,indent=2,default=js));res={"audit":audit,"label_definition":"future price multiple reaches target before <=0.5x; post-grad USD return anchored to last pre-grad SOL price at graduation","ages":{}}
 for age in AGES:
  print(f"AGE {age}",flush=True);h=age/2
  feat=q(con,f"""WITH tok AS(SELECT mint,detected_at,creator,creator_past_tokens,creator_past_rugs,initial_buy_sol,initial_holder_count,initial_gini,CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top1_pct_corrected,initial_top1_pct) END initial_top1_pct_model,CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top5_pct_corrected,initial_top5_pct) END initial_top5_pct_model,CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top10_pct_corrected,initial_top10_pct) END initial_top10_pct_model,coalesce(dev_buy_pct_corrected,dev_buy_pct) dev_buy_pct_model,launch_snipe_delta_sol,CAST(coalesce(is_mayhem_mode,false) AS INTEGER) is_mayhem_mode,CAST(coalesce(is_cashback_enabled,false) AS INTEGER) is_cashback_enabled,extract(hour from detected_at)::INTEGER hour_utc,extract(dow from detected_at)::INTEGER dow_utc FROM read_parquet('{tp}')),x AS(SELECT r.*,tok.creator,(r.user_wallet<>'{SYSTEM}') human,(r.sol_amount>0 AND r.token_amount>0 AND r.price_sol>0 AND r.sol_amount/(r.token_amount*r.price_sol) BETWEEN .01 AND 100) valid_sol FROM read_parquet('{tg}') r JOIN tok USING(mint) WHERE seconds_since_launch BETWEEN 0 AND {age}),g AS(SELECT mint,count(*) FILTER(WHERE human) human_trades,count(*) FILTER(WHERE human AND is_buy) buys,count(*) FILTER(WHERE human AND NOT is_buy) sells,count(DISTINCT user_wallet) FILTER(WHERE human) unique_wallets,count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy) unique_buyers,count(DISTINCT user_wallet) FILTER(WHERE human AND NOT is_buy) unique_sellers,sum(CASE WHEN human AND valid_sol THEN sol_amount ELSE 0 END) valid_volume_sol,sum(CASE WHEN human AND valid_sol AND is_buy THEN sol_amount ELSE 0 END) buy_volume_sol,sum(CASE WHEN human AND valid_sol AND NOT is_buy THEN sol_amount ELSE 0 END) sell_volume_sol,count(*) FILTER(WHERE human AND seconds_since_launch>{h}) recent_trades,count(*) FILTER(WHERE human AND seconds_since_launch<={h}) prior_trades,count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy AND seconds_since_launch>{h}) recent_buyers,count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy AND seconds_since_launch<={h}) prior_buyers,sum(CASE WHEN human AND valid_sol AND seconds_since_launch>{h} THEN sol_amount ELSE 0 END) recent_volume_sol,sum(CASE WHEN human AND valid_sol AND seconds_since_launch<={h} THEN sol_amount ELSE 0 END) prior_volume_sol,arg_min(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) first_price_sol,arg_max(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) entry_price_sol,min(price_sol) FILTER(WHERE price_sol>0) min_price_sol,max(price_sol) FILTER(WHERE price_sol>0) max_price_sol,arg_max(market_cap_sol,seconds_since_launch) FILTER(WHERE market_cap_sol>0) market_cap_sol,max(seconds_since_launch) FILTER(WHERE human) last_human_sec,count(*) FILTER(WHERE human AND user_wallet=creator) creator_trades,sum(CASE WHEN human AND user_wallet=creator AND is_buy AND valid_sol THEN sol_amount ELSE 0 END) creator_buy_volume_sol FROM x GROUP BY mint) SELECT tok.*,g.*,buy_volume_sol/(sell_volume_sol+.01) buy_sell_volume_ratio,(recent_trades-prior_trades)/(prior_trades+1.0) tx_acceleration,(recent_buyers-prior_buyers)/(prior_buyers+1.0) buyer_acceleration,(recent_volume_sol-prior_volume_sol)/(prior_volume_sol+.01) volume_acceleration,entry_price_sol/first_price_sol-1 price_return,max_price_sol/nullif(min_price_sol,0) price_range_ratio,{age}-last_human_sec last_trade_gap_sec FROM tok JOIN g USING(mint) WHERE entry_price_sol>0""")
  con.register("ent",feat[["mint","entry_price_sol"]]);lab=q(con,f"""WITH f AS(SELECT e.mint,p.sec,p.price/e.entry_price_sol mult FROM ent e JOIN price_path p USING(mint) WHERE p.sec>{age} AND p.price>0),a AS(SELECT mint,max(mult) max_future_multiple,arg_max(mult,sec) terminal_multiple,min(sec) FILTER(WHERE mult<=.5) dd,min(sec) FILTER(WHERE mult>=2) t2,min(sec) FILTER(WHERE mult>=5) t5,min(sec) FILTER(WHERE mult>=10) t10,min(sec) FILTER(WHERE mult>=25) t25,min(sec) FILTER(WHERE mult>=50) t50,min(sec) FILTER(WHERE mult>=100) t100,max(sec) last_future_sec,count(*) future_points FROM f GROUP BY mint) SELECT e.mint,coalesce(max_future_multiple,0) max_future_multiple,coalesce(terminal_multiple,0) terminal_multiple,last_future_sec,coalesce(future_points,0) future_points,(dd IS NOT NULL) drawdown_first,(t2 IS NOT NULL AND(dd IS NULL OR t2<dd)) hit_2x,(t5 IS NOT NULL AND(dd IS NULL OR t5<dd)) hit_5x,(t10 IS NOT NULL AND(dd IS NULL OR t10<dd)) hit_10x,(t25 IS NOT NULL AND(dd IS NULL OR t25<dd)) hit_25x,(t50 IS NOT NULL AND(dd IS NULL OR t50<dd)) hit_50x,(t100 IS NOT NULL AND(dd IS NULL OR t100<dd)) hit_100x FROM ent e LEFT JOIN a USING(mint)""");con.unregister("ent")
  p=feat.merge(lab,on="mint",how="left");p.drawdown_first=p.drawdown_first.fillna(False).astype(bool);p.terminal_multiple=p.terminal_multiple.fillna(0)
  for t in TARGETS:p[f"hit_{t}x"]=p[f"hit_{t}x"].fillna(False).astype(bool)
  (root/f"panel_{age}.parquet").parent.mkdir(exist_ok=True);p.to_parquet(root/f"panel_{age}.parquet",index=False)
  ar={"eligible_tokens":len(p),"label_rates":{f"hit_{t}x":float(p[f'hit_{t}x'].mean()) for t in TARGETS},"models":{}}
  for t in TARGETS:print(f" target {t} positives {int(p[f'hit_{t}x'].sum())}",flush=True);ar["models"][f"hit_{t}x"]=model(p,t)
  res["ages"][str(age)]=ar;Path(out,"economic_metrics_partial.json").write_text(json.dumps(res,indent=2,default=js))
 res["elapsed_sec"]=time.time()-t0;Path(out,"economic_metrics.json").write_text(json.dumps(res,indent=2,default=js))
 rows=[]
 for age,ar in res["ages"].items():
  for target,m in ar["models"].items():
   h=m.get("hist_gradient_boosting");
   if not h:continue
   x=next(z for z in h["enrichment"] if z["fraction"]==.01);rows.append({"age_sec":int(age),"target":target,"base_rate":h["base_rate"],"top1_rate":x["selected_rate"],"top1_lift":x["lift"],"test_positives":h["positives"],"ap":h.get("average_precision"),"auc":h.get("roc_auc"),"top100_hits":m.get("top100_path_policy",{}).get("hits"),"top100_end_units":m.get("top100_path_policy",{}).get("end_units")})
 pd.DataFrame(rows).to_csv(out/"headline_enrichment.csv",index=False);print(json.dumps({"elapsed_sec":res["elapsed_sec"],"rows":rows},indent=2,default=js))
if __name__=="__main__":main()
