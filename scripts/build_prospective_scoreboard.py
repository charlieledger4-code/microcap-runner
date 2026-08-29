#!/usr/bin/env python3
"""Aggregate immutable prospective executable outcomes into a research scoreboard.

Only ``status=COMPLETE`` outcome files are admitted.  Groups may overlap (for
example a deterministic random control can also happen to be a champion
candidate); overlap is retained rather than silently changing the random sample.
"""
from __future__ import annotations

import argparse,json,math,time
from pathlib import Path
from statistics import median

TARGETS=('2','5','10','25','50','100')


def wilson(k,n,z=1.959963984540054):
    if not n:return [None,None]
    p=k/n;d=1+z*z/n;c=(p+z*z/(2*n))/d
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0,c-h),min(1,c+h)]


def groups(x):
    out=['all_complete']
    d=x.get('decision');ctrl=x.get('prospective_controls') or {};gate=x.get('adversarial_gate') or {}
    if d in ('PAPER_PRIORITY','PAPER_CANDIDATE'):out.append('champion_candidate')
    if d=='PAPER_PRIORITY':out.append('champion_priority')
    if d=='PAPER_CANDIDATE':out.append('champion_candidate_nonpriority')
    if d=='WATCH':out.append('watch')
    if ctrl.get('random_control'):out.append('random_control')
    if ctrl.get('near_miss_control'):out.append('near_miss_control')
    if d in ('PAPER_PRIORITY','PAPER_CANDIDATE') and gate.get('status')=='VETO':out.append('candidate_gate_veto_counterfactual')
    if d in ('PAPER_PRIORITY','PAPER_CANDIDATE') and gate.get('status')!='VETO':out.append('candidate_gate_retained_counterfactual')
    return out


def summarize(rows):
    vals=[];terminal=[];liq=0
    for x in rows:
        o=x.get('outcome') or {}
        m=o.get('max_executable_multiple');t=o.get('terminal_executable_multiple')
        if isinstance(m,(int,float)) and math.isfinite(m):vals.append(float(m))
        if isinstance(t,(int,float)) and math.isfinite(t):terminal.append(float(t))
        liq+=int(o.get('liquidity_limited_points') or 0)
    r={'n':len(rows),'with_max_executable':len(vals),'with_terminal_executable':len(terminal),'liquidity_limited_points':liq}
    if vals:r.update({'median_max_executable_multiple':median(vals),'mean_max_executable_multiple':sum(vals)/len(vals),'max_executable_multiple':max(vals)})
    if terminal:r.update({'median_terminal_executable_multiple':median(terminal),'mean_terminal_executable_multiple':sum(terminal)/len(terminal)})
    r['targets']={}
    for target in TARGETS:
        eligible=0;hits=0
        for x in rows:
            e=((x.get('outcome') or {}).get('executable_targets') or {}).get(target)
            if not e:continue
            eligible+=1;hits+=int(bool(e.get('hit')))
        rate=hits/eligible if eligible else None
        r['targets'][target]={'n':eligible,'hits':hits,'rate':rate,'ci95':wilson(hits,eligible)}
    return r


def main():
    p=argparse.ArgumentParser();p.add_argument('--ledger-root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.ledger_root);records=[]
    for f in sorted((root/'prospective'/'outcomes').glob('*/*/*.json')) if (root/'prospective'/'outcomes').exists() else []:
        try:x=json.loads(f.read_text())
        except Exception:continue
        if x.get('status')!='COMPLETE':continue
        x['_path']=str(f.relative_to(root));records.append(x)
    by_h={}
    for x in records:by_h.setdefault(str(x.get('horizon_s')),[]).append(x)
    result={'generated_ms':int(time.time()*1000),'complete_outcome_files':len(records),'horizons':{},'guard':'Derived scoreboard only. Immutable scan/outcome files remain the source of truth; incomplete outcomes are excluded.'}
    for h,rows in sorted(by_h.items(),key=lambda z:int(z[0])):
        names=sorted({g for x in rows for g in groups(x)})
        sm={g:summarize([x for x in rows if g in groups(x)]) for g in names}
        comparisons={}
        for target in TARGETS:
            c=((sm.get('champion_candidate') or {}).get('targets') or {}).get(target) or {}
            r=((sm.get('random_control') or {}).get('targets') or {}).get(target) or {}
            cr=c.get('rate');rr=r.get('rate')
            comparisons[target]={'candidate_vs_random_lift':(cr/rr if cr is not None and rr not in (None,0) else None),'candidate_rate':cr,'random_rate':rr}
        result['horizons'][h]={'groups':sm,'comparisons':comparisons}
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2))
    print(json.dumps({'complete_outcome_files':len(records),'horizons':list(result['horizons'])},indent=2))

if __name__=='__main__':main()
