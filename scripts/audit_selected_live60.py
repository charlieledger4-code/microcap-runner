#!/usr/bin/env python3
"""RPC-audit only the outcome-independent subset selected from a HT scan."""
from __future__ import annotations
import argparse,asyncio,json,os,time
from pathlib import Path
import aiohttp

from src.ingest.pump_trade_event import extract_trade_events_from_transaction
from src.live.feature60 import normalize_trades,build_livecore_features,feature_coverage
from src.live.feature60_v2 import build_livecore_v2_features
from src.live.scoring import LiveCoreScorer

RPC=os.environ.get('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')

class Pacer:
    def __init__(self,interval=.22):self.interval=interval;self.lock=asyncio.Lock();self.next=0.0
    async def wait(self):
        async with self.lock:
            now=time.monotonic();d=max(0,self.next-now)
            if d:await asyncio.sleep(d)
            self.next=time.monotonic()+self.interval

async def rpc(s,p,method,params,retries=9):
    back=.5;payload={'jsonrpc':'2.0','id':1,'method':method,'params':params}
    for attempt in range(retries):
        await p.wait()
        try:
            async with s.post(RPC,json=payload,timeout=aiohttp.ClientTimeout(total=25)) as r:
                text=await r.text()
                if r.status==429 or r.status>=500:
                    await asyncio.sleep(back);back=min(8,back*1.7);continue
                if r.status!=200:return None,f'http_{r.status}:{text[:160]}'
                o=json.loads(text)
                if o.get('error'):
                    code=(o['error'] or {}).get('code') if isinstance(o['error'],dict) else None
                    if code in (-32005,-32004,-32603):
                        await asyncio.sleep(back);back=min(8,back*1.7);continue
                    return None,f"rpc:{o['error']}"
                return o.get('result'),None
        except Exception as e:
            if attempt+1==retries:return None,f'{type(e).__name__}:{e}'
            await asyncio.sleep(back);back=min(8,back*1.7)
    return None,'retries_exhausted'

async def audit_one(s,p,row,launch,scorer,a):
    sig=launch.get('signature');create,ce=await rpc(s,p,'getTransaction',[sig,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
    launch_s=(create or {}).get('blockTime')
    if create is None or launch_s is None:
        return False,{'create_tx_ok':False,'create_error':ce or 'null_create'},None,None,None
    cut=launch_s+a.age_s;prev=set();sweeps=[];errors=[]
    for i in range(a.sweeps):
        xs,e=await rpc(s,p,'getSignaturesForAddress',[row['mint'],{'limit':a.tx_limit,'commitment':'confirmed'}])
        if e:errors.append({'sweep':i,'error':e});xs=[]
        cur={x['signature'] for x in (xs or []) if x.get('err') is None and x.get('blockTime') is not None and launch_s-2<=x['blockTime']<=cut+2}
        cur.add(sig);sweeps.append({'count':len(cur),'added_vs_previous':len(cur-prev)});prev|=cur
        if i+1<a.sweeps:await asyncio.sleep(a.sweep_gap_s)
    expected=prev;stable=bool(len(sweeps)>=2 and sweeps[-1]['added_vs_previous']==0)
    truncated=len(expected)>a.max_txs;txs=[];txerr={}
    for x in sorted(expected)[:a.max_txs]:
        tx,e=await rpc(s,p,'getTransaction',[x,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
        if tx is None:txerr[x]=e or 'null_result'
        else:txs.append((x,tx))
    fraction=len(txs)/len(expected) if expected else 0.0
    valid=bool(not errors and stable and not truncated and fraction>=a.min_fraction)
    ev=[]
    for x,tx in txs:ev.extend(extract_trade_events_from_transaction(tx,x))
    trades=normalize_trades(launch,ev,launch_s)
    f1=build_livecore_features(launch,trades,decision_age_s=a.age_s,launch_unix_s=launch_s)
    f2=build_livecore_v2_features(launch,trades,decision_age_s=a.age_s,launch_unix_s=launch_s)
    score=scorer.score(f1)
    q={'create_tx_ok':True,'create_error':ce,'launch_block_time':launch_s,'history_sweeps':len(sweeps),
       'history_stable_final_sweep':stable,'sweep_errors':errors,'expected_signatures':len(expected),
       'transactions_retrieved':len(txs),'transaction_failures':len(txerr),'signature_retrieval_fraction':fraction,
       'tx_cap_hit':truncated,'failed_transactions':txerr,'audit_valid':valid}
    return valid,q,f1,f2,score

async def main_async(a):
    rows_path=Path(a.rows);launch_path=Path(a.launches)
    rows=[json.loads(x) for x in rows_path.read_text().splitlines() if x.strip()]
    launches={x['mint']:x for x in (json.loads(y) for y in launch_path.read_text().splitlines() if y.strip())}
    scorer=LiveCoreScorer(a.bundle);p=Pacer(a.rpc_interval);selected=[r for r in rows if (r.get('audit_selection') or {}).get('selected')]
    async with aiohttp.ClientSession(headers={'User-Agent':'microcap-runner-ht-audit/0.1'}) as s:
        for r in selected:
            launch=launches.get(r['mint'])
            if not launch:
                r['audit_status']='INVALID';r['data_status']='DATA_INVALID';r['data_quality']={'audit_valid':False,'reason':'missing_launch_payload'};continue
            valid,q,f1,f2,score=await audit_one(s,p,r,launch,scorer,a)
            r['audit_status']='CONFIRMED' if valid else 'INVALID';r['data_status']='VALID' if valid else 'DATA_INVALID';r['data_quality']=q
            r['audit_features']=f1;r['audit_v2_challenger_features']=f2;r['audit_scores']=score and score['scores'];r['audit_decision']=score and score['decision'];r['audit_scored_ms']=int(time.time()*1000)
            try:r['audit_10x_score_delta']=float(score['scores']['10']['score'])-float(r['scores']['10']['score'])
            except Exception:r['audit_10x_score_delta']=None
            r['audit_decision_changed']=bool(score and score['decision']!=r['decision'])
            r['audit_feature_coverage']=feature_coverage(f1) if f1 else None
    rows_path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    print(json.dumps({'rows':len(rows),'selected':len(selected),'valid':sum(r.get('data_status')=='VALID' for r in selected),
                      'invalid':sum(r.get('data_status')=='DATA_INVALID' for r in selected),'not_audited':len(rows)-len(selected)},indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--launches',required=True);p.add_argument('--bundle',required=True)
    p.add_argument('--age-s',type=int,default=60);p.add_argument('--sweeps',type=int,default=3);p.add_argument('--sweep-gap-s',type=float,default=2)
    p.add_argument('--tx-limit',type=int,default=1000);p.add_argument('--max-txs',type=int,default=750);p.add_argument('--rpc-interval',type=float,default=.22)
    p.add_argument('--min-fraction',type=float,default=.98);asyncio.run(main_async(p.parse_args()))
if __name__=='__main__':main()
