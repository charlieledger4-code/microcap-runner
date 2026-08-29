#!/usr/bin/env python3
"""Try to break the 60s historical edge: walk-forward folds, ablations, unseen creators, delay/adverse fills."""
import argparse,json,math,os,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd
from huggingface_hub import HfApi,hf_hub_download
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score,roc_auc_score

REPO='Slinky21/Pumpfun_Memecoin_Corpus'; SYS='BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s'; AGE=60; TARGETS=(5,10,25,50,100)
FLOW=['human_trades','buys','sells','unique_wallets','unique_buyers','unique_sellers','valid_volume_sol','buy_volume_sol','sell_volume_sol','buy_sell_volume_ratio','recent_trades','prior_trades','recent_buyers','prior_buyers','recent_volume_sol','prior_volume_sol','tx_acceleration','buyer_acceleration','volume_acceleration','last_trade_gap_sec']
PRICE=['first_price_sol','entry_price_sol','price_return','price_range_ratio','market_cap_sol']
CREATOR=['creator_trades','creator_buy_volume_sol','creator_past_tokens','creator_past_rugs','initial_buy_sol']
STRUCT=['initial_holder_count','initial_gini','initial_top1_pct_model','initial_top5_pct_model','initial_top10_pct_model','dev_buy_pct_model','launch_snipe_delta_sol','is_mayhem_mode','is_cashback_enabled']
CTX=['hour_utc','dow_utc']; ALL=FLOW+PRICE+CREATOR+STRUCT+CTX
SETS={'all':ALL,'no_price_mcap':[x for x in ALL if x not in PRICE],'flow_only':FLOW}
FOLDS=((.50,.60,'A'),(.60,.70,'B'),(.70,.80,'C'),(.80,1.00,'D'))

def dl(n,r): r.mkdir(parents=True,exist_ok=True); return hf_hub_download(repo_id=REPO,repo_type='dataset',filename=n,local_dir=str(r))
def acquire(r):
 f=HfApi().list_repo_files(REPO,repo_type='dataset'); s=sorted(x for x in f if x.startswith('trades/') and x.endswith('.parquet'))
 for x in ('tokens.parquet','migrations.parquet','postgard_snapshots.parquet','postgard_outcomes.parquet'): dl(x,r)
 for x in s: dl(x,r)
 return s
def q(c,s): return c.execute(s).fetchdf()
def js(x):
 if isinstance(x,(np.integer,)): return int(x)
 if isinstance(x,(np.floating,)): return None if not np.isfinite(x) else float(x)
 if isinstance(x,pd.Timestamp): return x.isoformat()
 return x
def wilson(k,n,z=1.959963984540054):
 if not n:return [None,None]
 p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [max(0,c-h),min(1,c+h)]
def metric(y,s):
 y=np.asarray(y,int);s=np.asarray(s,float);n=len(y);base=float(y.mean()) if n else None;o={'n':n,'positives':int(y.sum()),'base_rate':base}
 if not n:return o
 ix=np.argsort(s)[::-1]; k=max(1,int(n*.01)); h=int(y[ix[:k]].sum()); r=h/k; hk=int(y[ix[:min(100,n)]].sum())
 o['top1']={'n':k,'hits':h,'rate':r,'ci95':wilson(h,k),'lift':r/base if base else None};o['top100']={'n':min(100,n),'hits':hk,'rate':hk/min(100,n),'ci95':wilson(hk,min(100,n))}
 if len(np.unique(y))>1:o['ap']=float(average_precision_score(y,s));o['auc']=float(roc_auc_score(y,s))
 return o
def model(kind='hgb'):
 if kind=='logit':return Pipeline([('i',SimpleImputer(strategy='median',add_indicator=True)),('s',StandardScaler()),('m',LogisticRegression(max_iter=1000,class_weight='balanced',C=.15))])
 return Pipeline([('i',SimpleImputer(strategy='median',add_indicator=True)),('m',HistGradientBoostingClassifier(max_iter=120,learning_rate=.06,max_leaf_nodes=23,min_samples_leaf=50,l2_regularization=1,class_weight='balanced',random_state=20260829))])
def score(tr,te,feats,col,kind='hgb'):
 y=tr[col].astype(int).to_numpy()
 if len(tr)<100 or y.sum()<5 or len(np.unique(y))<2 or not len(te):return None
 m=model(kind);m.fit(tr[feats].replace([np.inf,-np.inf],np.nan),y);p=m.predict_proba(te[feats].replace([np.inf,-np.inf],np.nan))[:,1];return metric(te[col].astype(int).to_numpy(),p)

def panel(c,tp,tg):
 h=30
 return q(c,f"""WITH tok AS(SELECT mint,detected_at,creator,creator_past_tokens,creator_past_rugs,initial_buy_sol,initial_holder_count,initial_gini,CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top1_pct_corrected,initial_top1_pct) END initial_top1_pct_model,CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top5_pct_corrected,initial_top5_pct) END initial_top5_pct_model,CASE WHEN coalesce(top10_pct_suspect,false) THEN NULL ELSE coalesce(initial_top10_pct_corrected,initial_top10_pct) END initial_top10_pct_model,coalesce(dev_buy_pct_corrected,dev_buy_pct) dev_buy_pct_model,launch_snipe_delta_sol,CAST(coalesce(is_mayhem_mode,false) AS INTEGER) is_mayhem_mode,CAST(coalesce(is_cashback_enabled,false) AS INTEGER) is_cashback_enabled,extract(hour from detected_at)::INTEGER hour_utc,extract(dow from detected_at)::INTEGER dow_utc FROM read_parquet('{tp}')),x AS(SELECT r.*,tok.creator,(r.user_wallet<>'{SYS}') human,(r.sol_amount>0 AND r.token_amount>0 AND r.price_sol>0 AND r.sol_amount/(r.token_amount*r.price_sol) BETWEEN .01 AND 100) valid_sol FROM read_parquet('{tg}') r JOIN tok USING(mint) WHERE seconds_since_launch BETWEEN 0 AND 60),g AS(SELECT mint,count(*) FILTER(WHERE human) human_trades,count(*) FILTER(WHERE human AND is_buy) buys,count(*) FILTER(WHERE human AND NOT is_buy) sells,count(DISTINCT user_wallet) FILTER(WHERE human) unique_wallets,count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy) unique_buyers,count(DISTINCT user_wallet) FILTER(WHERE human AND NOT is_buy) unique_sellers,sum(CASE WHEN human AND valid_sol THEN sol_amount ELSE 0 END) valid_volume_sol,sum(CASE WHEN human AND valid_sol AND is_buy THEN sol_amount ELSE 0 END) buy_volume_sol,sum(CASE WHEN human AND valid_sol AND NOT is_buy THEN sol_amount ELSE 0 END) sell_volume_sol,count(*) FILTER(WHERE human AND seconds_since_launch>30) recent_trades,count(*) FILTER(WHERE human AND seconds_since_launch<=30) prior_trades,count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy AND seconds_since_launch>30) recent_buyers,count(DISTINCT user_wallet) FILTER(WHERE human AND is_buy AND seconds_since_launch<=30) prior_buyers,sum(CASE WHEN human AND valid_sol AND seconds_since_launch>30 THEN sol_amount ELSE 0 END) recent_volume_sol,sum(CASE WHEN human AND valid_sol AND seconds_since_launch<=30 THEN sol_amount ELSE 0 END) prior_volume_sol,arg_min(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) first_price_sol,arg_max(price_sol,seconds_since_launch) FILTER(WHERE price_sol>0) entry_price_sol,min(price_sol) FILTER(WHERE price_sol>0) min_price_sol,max(price_sol) FILTER(WHERE price_sol>0) max_price_sol,arg_max(market_cap_sol,seconds_since_launch) FILTER(WHERE market_cap_sol>0) market_cap_sol,max(seconds_since_launch) FILTER(WHERE human) last_human_sec,count(*) FILTER(WHERE human AND user_wallet=creator) creator_trades,sum(CASE WHEN human AND user_wallet=creator AND is_buy AND valid_sol THEN sol_amount ELSE 0 END) creator_buy_volume_sol FROM x GROUP BY mint) SELECT tok.*,g.*,buy_volume_sol/(sell_volume_sol+.01) buy_sell_volume_ratio,(recent_trades-prior_trades)/(prior_trades+1.0) tx_acceleration,(recent_buyers-prior_buyers)/(prior_buyers+1.0) buyer_acceleration,(recent_volume_sol-prior_volume_sol)/(prior_volume_sol+.01) volume_acceleration,entry_price_sol/first_price_sol-1 price_return,max_price_sol/nullif(min_price_sol,0) price_range_ratio,60-last_human_sec last_trade_gap_sec FROM tok JOIN g USING(mint) WHERE entry_price_sol>0""")
def labels(c,p):
 c.register('ent',p[['mint','entry_price_sol']]); ts=','.join([f"(t{t} IS NOT NULL AND (dd IS NULL OR t{t}<dd)) hit_{t}x" for t in TARGETS])
 l=q(c,f"""WITH f AS(SELECT e.mint,x.sec,x.price/e.entry_price_sol mult FROM ent e JOIN price_path x USING(mint) WHERE x.sec>60 AND x.price>0),a AS(SELECT mint,arg_max(mult,sec) terminal_multiple,min(sec) FILTER(WHERE mult<=.5) dd,min(sec) FILTER(WHERE mult>=5) t5,min(sec) FILTER(WHERE mult>=10) t10,min(sec) FILTER(WHERE mult>=25) t25,min(sec) FILTER(WHERE mult>=50) t50,min(sec) FILTER(WHERE mult>=100) t100,count(*) n FROM f GROUP BY mint) SELECT e.mint,coalesce(a.terminal_multiple,0) terminal_multiple,coalesce(a.n,0) future_points,{ts} FROM ent e LEFT JOIN a USING(mint)""");return p.merge(l,on='mint',how='left')
def fold(d,a,b):
 d=d.sort_values('detected_at').reset_index(drop=True);n=len(d);i=max(1,int(n*a));j=min(n,max(i+1,int(n*b)));cut=pd.to_datetime(d.iloc[i-1].detected_at,utc=True);end=pd.to_datetime(d.iloc[j-1].detected_at,utc=True);dt=pd.to_datetime(d.detected_at,utc=True);return d[dt<=cut].copy(),d[(dt>=cut+pd.Timedelta(hours=3))&(dt<=end)].copy(),cut,end

def scenario(c,p,delay=0,penalty=0,target=100):
 c.register('scm',p[['mint']]); et=60+delay
 d=q(c,f"""WITH ep AS(SELECT m.mint,arg_min(x.price,x.sec)*(1+{penalty}) e,min(x.sec) s FROM scm m JOIN price_path x USING(mint) WHERE x.sec>={et} AND x.sec<={et+30} AND x.price>0 GROUP BY m.mint),f AS(SELECT ep.mint,x.sec,x.price/ep.e mult FROM ep JOIN price_path x USING(mint) WHERE x.sec>ep.s AND x.price>0),a AS(SELECT mint,min(sec) FILTER(WHERE mult<=.5) dd,min(sec) FILTER(WHERE mult>={target}) tt,count(*) n FROM f GROUP BY mint) SELECT ep.mint,(a.tt IS NOT NULL AND (a.dd IS NULL OR a.tt<a.dd)) hit,coalesce(a.n,0) future_points FROM ep LEFT JOIN a USING(mint)""");return d

def eval_scenario(p,sc):
 d=p.sort_values('detected_at').reset_index(drop=True);i=int(len(d)*.65);cut=pd.to_datetime(d.iloc[i-1].detected_at,utc=True);dt=pd.to_datetime(d.detected_at,utc=True);tr=d[dt<=cut].copy();te=d[dt>=cut+pd.Timedelta(hours=3)].merge(sc[['mint','hit']],on='mint',how='inner');m=model();m.fit(tr[ALL].replace([np.inf,-np.inf],np.nan),tr.hit_100x.astype(int));pr=m.predict_proba(te[ALL].replace([np.inf,-np.inf],np.nan))[:,1];return metric(te.hit.astype(int),pr)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',default='reports/stress60');a=ap.parse_args();o=Path(a.out);o.mkdir(parents=True,exist_ok=True);r=Path(os.environ.get('RUNNER_TEMP','/tmp'))/'stress60';t0=time.time();sh=acquire(r);c=duckdb.connect(str(r/'s.duckdb'));c.execute("SET threads=4");c.execute("SET memory_limit='5GB'");(r/'spill').mkdir(exist_ok=True);c.execute(f"SET temp_directory='{r/'spill'}'");tg=str(r/'trades/*.parquet');tp=str(r/'tokens.parquet');mg=str(r/'migrations.parquet');pg=str(r/'postgard_snapshots.parquet');og=str(r/'postgard_outcomes.parquet')
 c.execute(f"CREATE TABLE pre AS SELECT mint,seconds_since_launch::DOUBLE sec,price_sol::DOUBLE price FROM read_parquet('{tg}') WHERE price_sol>0 AND seconds_since_launch IS NOT NULL");c.execute("CREATE TABLE lp AS SELECT mint,arg_max(price,sec) p FROM pre GROUP BY mint");c.execute(f"CREATE TABLE post AS SELECT x.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+x.seconds_since_graduation)::DOUBLE sec,(lp.p*(x.price_usd/y.price_at_grad_usd))::DOUBLE price FROM read_parquet('{pg}') x JOIN lp USING(mint) LEFT JOIN read_parquet('{tp}') t USING(mint) LEFT JOIN read_parquet('{mg}') m USING(mint) JOIN read_parquet('{og}') y USING(mint) WHERE x.price_usd>0 AND y.price_at_grad_usd>0 AND x.seconds_since_graduation>=0 AND NOT coalesce(x.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL");c.execute('CREATE VIEW price_path AS SELECT * FROM pre UNION ALL SELECT * FROM post')
 p=labels(c,panel(c,tp,tg));p=p[p.future_points>0].copy();p.detected_at=pd.to_datetime(p.detected_at,utc=True);res={'eligible':len(p),'target_counts':{str(t):int(p[f'hit_{t}x'].sum()) for t in TARGETS},'folds':{},'execution':{},'elapsed_to_panel_sec':time.time()-t0}
 rows=[]
 for a1,b1,nm in FOLDS:
  tr,te,cut,end=fold(p,a1,b1);seen=set(tr.creator.dropna().astype(str));u=te[~te.creator.fillna('').astype(str).isin(seen)].copy();fr={'cutoff':cut,'test_end':end,'n_train':len(tr),'n_test':len(te),'n_unseen_creator':len(u),'targets':{}}
  for t in TARGETS:
   col=f'hit_{t}x';item={'all':score(tr,te,ALL,col),'logit_all':score(tr,te,ALL,col,'logit')}
   if t in (10,100):
    item['no_price_mcap']=score(tr,te,SETS['no_price_mcap'],col);item['flow_only']=score(tr,te,FLOW,col);item['unseen_creator_all']=score(tr,u,ALL,col)
   fr['targets'][str(t)]=item
   for k,v in item.items():
    if v and v.get('top1'):rows.append({'fold':nm,'target':t,'model':k,'n_test':v['n'],'base_rate':v['base_rate'],'top1_rate':v['top1']['rate'],'top1_lift':v['top1']['lift'],'top100_hits':v['top100']['hits'],'auc':v.get('auc'),'ap':v.get('ap')})
  res['folds'][nm]=fr
 for d in (0,15,30,60):res['execution'][f'delay_{d}s']=eval_scenario(p,scenario(c,p,delay=d,target=100))
 for z in (0.05,0.10,0.20):res['execution'][f'adverse_{int(z*100)}pct']=eval_scenario(p,scenario(c,p,penalty=z,target=100))
 h=pd.DataFrame(rows);h.to_csv(o/'stress_headlines.csv',index=False);summ=[]
 if len(h):
  for (t,m),g in h.groupby(['target','model']):summ.append({'target':int(t),'model':m,'folds':len(g),'median_top1_lift':float(g.top1_lift.median()),'min_top1_lift':float(g.top1_lift.min()),'max_top1_lift':float(g.top1_lift.max()),'sum_top100_hits':int(g.top100_hits.sum())})
 res['summary']=summ;res['elapsed_sec']=time.time()-t0;res['guard']='Historical price-path stress test only; execution realism still requires live prospective fills/fees/slippage.'; (o/'STRESS_RESULT.json').write_text(json.dumps(res,indent=2,default=js));pd.DataFrame(summ).to_csv(o/'fold_summary.csv',index=False);print(json.dumps({'eligible':len(p),'elapsed_sec':res['elapsed_sec'],'summary_rows':len(summ)},indent=2))
if __name__=='__main__':main()
