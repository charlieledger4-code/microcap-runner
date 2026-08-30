#!/usr/bin/env python3
"""Prospective drift monitor for the frozen live-core model.

Uses all action-time scores, including non-audited rejects.  Frozen score
threshold occupancy is compared with its training quantile expectation; feature
missingness and live score quantiles are also recorded.  This never retrains or
moves thresholds.
"""
from __future__ import annotations
import argparse,json,math,time
from pathlib import Path

EXPECTED={'0.95':.05,'0.99':.01,'0.995':.005,'0.999':.001}

def q(vals,p):
    if not vals:return None
    x=sorted(vals);i=(len(x)-1)*p;lo=int(math.floor(i));hi=int(math.ceil(i))
    return x[lo] if lo==hi else x[lo]*(hi-i)+x[hi]*(i-lo)

def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--manifest',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    rows=[json.loads(x) for x in Path(a.rows).read_text().splitlines() if x.strip()];m=json.loads(Path(a.manifest).read_text())
    n=len(rows);features=m['features'];score10=[];miss={f:0 for f in features}
    for r in rows:
        try:score10.append(float(r['scores']['10']['score']))
        except Exception:pass
        fr=r.get('features') or {}
        for f in features:
            v=fr.get(f)
            if v is None or (isinstance(v,float) and not math.isfinite(v)):miss[f]+=1
    thresholds=m['targets']['10']['score_thresholds'];occ={}
    severe=False
    for name,t in thresholds.items():
        hit=sum(s>=float(t) for s in score10);rate=hit/len(score10) if score10 else None;exp=EXPECTED.get(name)
        z=None
        if exp is not None and score10:
            se=math.sqrt(exp*(1-exp)/len(score10));z=(rate-exp)/se if se else None
            if z is not None and abs(z)>=4:severe=True
        occ[name]={'threshold':t,'n':len(score10),'hits':hit,'rate':rate,'expected_rate':exp,'z_vs_training_quantile':z}
    missing={f:{'count':c,'rate':c/n if n else None} for f,c in miss.items() if c}
    if any(v['rate'] is not None and v['rate']>.05 for v in missing.values()):severe=True
    result={'generated_ms':int(time.time()*1000),'rows':n,'score10_quantiles':{str(x):q(score10,x) for x in (.1,.25,.5,.75,.9,.95,.99)},
            'frozen_threshold_occupancy':occ,'feature_missingness':missing,
            'status':'REGIME_DRIFT' if severe else ('INSUFFICIENT_SAMPLE' if n<100 else 'NO_SEVERE_DRIFT'),
            'guard':'Diagnostic only. Drift status cannot retrain the model or change frozen thresholds.'}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
