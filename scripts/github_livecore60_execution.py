#!/usr/bin/env python3
"""Execution-delay/adverse-entry stress for the pre-registered live-core 60s rank.

Chronological 65/35 split with 3h embargo. Models are trained only on earlier
60-second labels; delayed/adverse outcome labels are evaluated only on later rows.
No prospective outcomes are consumed.
"""
import argparse,json,os,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd
import scripts.github_phase2_stress60 as b
import scripts.github_phase2_stress60_lowmem as lm
from scripts.github_livecore60_models import LIVE


def js(x):
    if isinstance(x,(np.integer,)):return int(x)
    if isinstance(x,(np.floating,)):return None if not np.isfinite(x) else float(x)
    if isinstance(x,pd.Timestamp):return x.isoformat()
    return x

def fit_score(tr,te,features,target_col,outcome_col='hit'):
    y=tr[target_col].astype(int).to_numpy()
    if y.sum()<5 or len(np.unique(y))<2:return None
    m=b.model();m.fit(tr[features].replace([np.inf,-np.inf],np.nan),y)
    pr=m.predict_proba(te[features].replace([np.inf,-np.inf],np.nan))[:,1]
    return b.metric(te[outcome_col].astype(int).to_numpy(),pr)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='reports/livecore60_execution');a=ap.parse_args();o=Path(a.out);o.mkdir(parents=True,exist_ok=True)
    root=Path(os.environ.get('RUNNER_TEMP','/tmp'))/'livecore60_execution';t0=time.time();b.acquire(root)
    c=duckdb.connect(str(root/'x.duckdb'));c.execute("SET threads=1");c.execute("SET memory_limit='3.6GB'");c.execute("SET preserve_insertion_order=false");(root/'spill').mkdir(exist_ok=True);c.execute(f"SET temp_directory='{root/'spill'}'")
    tg=str(root/'trades/*.parquet');tp=str(root/'tokens.parquet');mg=str(root/'migrations.parquet');pg=str(root/'postgard_snapshots.parquet');og=str(root/'postgard_outcomes.parquet')
    c.execute(f"CREATE TABLE early60 AS SELECT mint,user_wallet,is_buy,sol_amount,token_amount,price_sol,market_cap_sol,seconds_since_launch FROM read_parquet('{tg}') WHERE seconds_since_launch BETWEEN 0 AND 60")
    c.execute(f"CREATE TABLE pre AS SELECT mint,seconds_since_launch::DOUBLE sec,price_sol::DOUBLE price FROM read_parquet('{tg}') WHERE price_sol>0 AND seconds_since_launch IS NOT NULL")
    c.execute("CREATE TABLE lp AS SELECT mint,arg_max(price,sec) p FROM pre GROUP BY mint")
    c.execute(f"CREATE TABLE post AS SELECT x.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+x.seconds_since_graduation)::DOUBLE sec,(lp.p*(x.price_usd/y.price_at_grad_usd))::DOUBLE price FROM read_parquet('{pg}') x JOIN lp USING(mint) LEFT JOIN read_parquet('{tp}') t USING(mint) LEFT JOIN read_parquet('{mg}') m USING(mint) JOIN read_parquet('{og}') y USING(mint) WHERE x.price_usd>0 AND y.price_at_grad_usd>0 AND x.seconds_since_graduation>=0 AND NOT coalesce(x.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL")
    c.execute('CREATE VIEW price_path AS SELECT * FROM pre UNION ALL SELECT * FROM post')
    p=b.labels(c,lm.make_panel(c,tp));p=p[p.future_points>0].copy();p.detected_at=pd.to_datetime(p.detected_at,utc=True);p=p.sort_values('detected_at').reset_index(drop=True)
    i=int(len(p)*.65);cut=pd.to_datetime(p.iloc[i-1].detected_at,utc=True);dt=pd.to_datetime(p.detected_at,utc=True);tr=p[dt<=cut].copy();te=p[dt>=cut+pd.Timedelta(hours=3)].copy()
    res={'cutoff':cut,'n_train':len(tr),'n_test_feature_rows':len(te),'feature_contract':'live_core_free_v1','targets':{},'elapsed_to_panel_sec':time.time()-t0}
    for target in (5,10,25):
        col=f'hit_{target}x';bucket={}
        for delay in (0,15,30,45,60):
            sc=b.scenario(c,p,delay=delay,target=target);ev=te.merge(sc[['mint','hit']],on='mint',how='inner')
            bucket[f'delay_{delay}s']=fit_score(tr,ev,LIVE,col)
        for penalty in (.025,.05,.10,.20):
            sc=b.scenario(c,p,penalty=penalty,target=target);ev=te.merge(sc[['mint','hit']],on='mint',how='inner')
            bucket[f'adverse_{int(penalty*1000)/10:g}pct']=fit_score(tr,ev,LIVE,col)
        res['targets'][str(target)]=bucket
    res['guard']='Historical chronological execution stress only. Price-path labels remain theoretical until live fills/fees/liquidity are measured.';res['elapsed_sec']=time.time()-t0
    (o/'EXECUTION_STRESS.json').write_text(json.dumps(res,indent=2,default=js))
    rows=[]
    for target,scenarios in res['targets'].items():
        for name,m in scenarios.items():
            if m and m.get('top1'):rows.append({'target':int(target),'scenario':name,'n':m['n'],'base_rate':m['base_rate'],'top1_hits':m['top1']['hits'],'top1_rate':m['top1']['rate'],'top1_lift':m['top1']['lift'],'top100_hits':m['top100']['hits'],'auc':m.get('auc'),'ap':m.get('ap')})
    pd.DataFrame(rows).to_csv(o/'execution_headlines.csv',index=False);print(json.dumps({'cutoff':cut,'n_train':len(tr),'n_test':len(te),'elapsed_sec':res['elapsed_sec']},indent=2,default=js))
if __name__=='__main__':main()
