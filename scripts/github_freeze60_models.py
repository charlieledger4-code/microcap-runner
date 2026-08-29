#!/usr/bin/env python3
"""Build deterministic frozen 60-second research models for prospective paper testing.

Important: score quantiles generated here are operational thresholds only. They are
not performance estimates because models are retrained on all historical data after
the walk-forward robustness gate has passed.
"""
from __future__ import annotations
import argparse, hashlib, json, os, time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import duckdb
import scripts.github_phase2_stress60 as b
import scripts.github_phase2_stress60_lowmem as lm

TARGETS=(5,10,25,100)
QUANTILES=(.95,.99,.995,.999)


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='reports/frozen60');a=ap.parse_args()
    out=Path(a.out);models_dir=out/'models';models_dir.mkdir(parents=True,exist_ok=True)
    root=Path(os.environ.get('RUNNER_TEMP','/tmp'))/'freeze60';t0=time.time();shards=b.acquire(root)
    con=duckdb.connect(str(root/'freeze.duckdb'));con.execute("SET threads=1");con.execute("SET memory_limit='3.6GB'");con.execute("SET preserve_insertion_order=false");(root/'spill').mkdir(exist_ok=True);con.execute(f"SET temp_directory='{root/'spill'}'")
    tg=str(root/'trades/*.parquet');tp=str(root/'tokens.parquet');mg=str(root/'migrations.parquet');pg=str(root/'postgard_snapshots.parquet');og=str(root/'postgard_outcomes.parquet')
    con.execute(f"CREATE TABLE early60 AS SELECT mint,user_wallet,is_buy,sol_amount,token_amount,price_sol,market_cap_sol,seconds_since_launch FROM read_parquet('{tg}') WHERE seconds_since_launch BETWEEN 0 AND 60")
    con.execute(f"CREATE TABLE pre AS SELECT mint,seconds_since_launch::DOUBLE sec,price_sol::DOUBLE price FROM read_parquet('{tg}') WHERE price_sol>0 AND seconds_since_launch IS NOT NULL")
    con.execute("CREATE TABLE lp AS SELECT mint,arg_max(price,sec) p FROM pre GROUP BY mint")
    con.execute(f"CREATE TABLE post AS SELECT x.mint,(coalesce(t.seconds_to_graduation,m.seconds_to_graduation)+x.seconds_since_graduation)::DOUBLE sec,(lp.p*(x.price_usd/y.price_at_grad_usd))::DOUBLE price FROM read_parquet('{pg}') x JOIN lp USING(mint) LEFT JOIN read_parquet('{tp}') t USING(mint) LEFT JOIN read_parquet('{mg}') m USING(mint) JOIN read_parquet('{og}') y USING(mint) WHERE x.price_usd>0 AND y.price_at_grad_usd>0 AND x.seconds_since_graduation>=0 AND NOT coalesce(x.incomplete_data,false) AND coalesce(t.seconds_to_graduation,m.seconds_to_graduation) IS NOT NULL")
    con.execute('CREATE VIEW price_path AS SELECT * FROM pre UNION ALL SELECT * FROM post')
    panel=b.labels(con,lm.make_panel(con,tp));panel=panel[panel.future_points>0].sort_values('detected_at').reset_index(drop=True)
    X=panel[b.ALL].replace([np.inf,-np.inf],np.nan)
    manifest={
      'model_family':'HistGradientBoostingClassifier inside median-imputation Pipeline',
      'decision_age_seconds':60,
      'features':b.ALL,
      'rows':len(panel),'trade_shards':len(shards),
      'historical_first_detected_at':str(pd.to_datetime(panel.detected_at,utc=True).min()),
      'historical_last_detected_at':str(pd.to_datetime(panel.detected_at,utc=True).max()),
      'source_repo':b.REPO,
      'build_commit':os.getenv('GITHUB_SHA'),
      'random_state':20260829,
      'threshold_note':'training-population score quantiles for prospective operational gating only; not OOS performance',
      'targets':{},'elapsed_panel_sec':time.time()-t0,
    }
    dist={}
    for col in b.ALL:
        s=pd.to_numeric(panel[col],errors='coerce').replace([np.inf,-np.inf],np.nan)
        v=s.dropna()
        dist[col]={'missing_rate':float(s.isna().mean()),'n':int(v.size)}
        if v.size:
            qs=v.quantile([.01,.05,.25,.5,.75,.95,.99])
            dist[col]['quantiles']={str(k):float(val) for k,val in qs.items()}
    for target in TARGETS:
        y=panel[f'hit_{target}x'].astype(int).to_numpy();m=b.model('hgb');m.fit(X,y);score=m.predict_proba(X)[:,1]
        path=models_dir/f'hgb_60s_{target}x.joblib';joblib.dump(m,path,compress=3)
        thresholds={str(q):float(np.quantile(score,q)) for q in QUANTILES}
        manifest['targets'][str(target)]={
          'positives':int(y.sum()),'base_rate':float(y.mean()),'model_file':path.name,
          'model_sha256':sha256(path),'score_thresholds':thresholds,
          'training_score_quantiles':thresholds,
        }
    manifest['elapsed_total_sec']=time.time()-t0
    (out/'MODEL_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    (out/'FEATURE_REFERENCE.json').write_text(json.dumps(dist,indent=2))
    (out/'FROZEN_POLICY.md').write_text('''# Frozen 60-second forward policy\n\n- Decision age: 60 seconds.\n- Research targets: 5x, 10x, 25x, 100x before a 50% drawdown.\n- Primary robust ranking diagnostic: 10x score.\n- Extreme-tail secondary diagnostic: 100x score.\n- Candidate flags are based on frozen historical score thresholds from MODEL_MANIFEST.json.\n- Historical threshold quantiles are operational gates only, never claimed as calibrated probabilities.\n- No threshold may be changed based on prospective outcomes until a pre-declared evaluation batch closes.\n- Every eligible prospective launch should be logged, including non-candidates and failures.\n- No real-money execution is authorized by this artifact.\n''')
    print(json.dumps({'rows':len(panel),'targets':manifest['targets'],'elapsed_sec':manifest['elapsed_total_sec']},indent=2))

if __name__=='__main__': main()
