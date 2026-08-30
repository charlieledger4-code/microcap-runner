#!/usr/bin/env python3
"""RPC-audit only the outcome-independent subset selected from a HT scan.

Audit v2 treats confirmed Solana signature history as the completeness index.  If
an action tape contains raw Pump events observed live, confirmed signatures
already represented in that tape are reused directly and only missing signatures
are fetched with ``getTransaction``.  Older tapes without raw events fall back to
full transaction retrieval.
"""
from __future__ import annotations
import argparse,asyncio,json,os,time
from pathlib import Path
import aiohttp

from src.ingest.pump_trade_event import PumpTradeEvent,extract_trade_events_from_transaction
from src.live.feature60 import normalize_trades,build_livecore_features,feature_coverage
from src.live.feature60_v2 import build_livecore_v2_features
from src.live.scoring import LiveCoreScorer

RPC=os.environ.get('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
AUDIT_VERSION='ht_signature_index_missing_only_v2'

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


def tape_events(tape):
    out=[]
    for x in (tape or {}).get('raw_pump_events') or []:
        try:out.append(PumpTradeEvent(**x))
        except Exception:continue
    return out


def event_key(ev):
    return (ev.source_signature,ev.mint,ev.user,ev.timestamp,ev.is_buy,ev.token_amount_raw,ev.sol_amount_raw,ev.quote_amount_raw)


async def audit_one(s,p,row,launch,tape,scorer,a):
    sig=launch.get('signature');create,ce=await rpc(s,p,'getTransaction',[sig,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
    launch_s=(create or {}).get('blockTime')
    if create is None or launch_s is None:
        return False,{'audit_version':AUDIT_VERSION,'create_tx_ok':False,'create_error':ce or 'null_create'},None,None,None
    cut=launch_s+a.age_s;prev=set();sweeps=[];errors=[];signature_cap_hit=False
    for i in range(a.sweeps):
        xs,e=await rpc(s,p,'getSignaturesForAddress',[row['mint'],{'limit':a.tx_limit,'commitment':'confirmed'}])
        if e:errors.append({'sweep':i,'error':e});xs=[]
        eligible=[x for x in (xs or []) if x.get('err') is None and x.get('blockTime') is not None and launch_s-2<=x['blockTime']<=cut+2]
        cur={x['signature'] for x in eligible};cur.add(sig)
        times=[x['blockTime'] for x in eligible]
        if len(xs or [])>=a.tx_limit and (not times or min(times)>launch_s-2):signature_cap_hit=True
        sweeps.append({'count':len(cur),'added_vs_previous':len(cur-prev)});prev|=cur
        if i+1<a.sweeps:await asyncio.sleep(a.sweep_gap_s)
    expected=prev;stable=bool(len(sweeps)>=2 and sweeps[-1]['added_vs_previous']==0)

    raw=tape_events(tape)
    confirmed_stream=[ev for ev in raw if ev.source_signature in expected]
    stream_sigs={ev.source_signature for ev in confirmed_stream if ev.source_signature}
    # Creation is represented by the immutable launch payload / initial-buy row;
    # confirmation of the creation transaction above is enough to account for it.
    stream_sigs.add(sig)
    missing=sorted(expected-stream_sigs)
    fetch_cap_hit=len(missing)>a.max_txs
    txs=[];txerr={}
    for x in missing[:a.max_txs]:
        tx,e=await rpc(s,p,'getTransaction',[x,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
        if tx is None:txerr[x]=e or 'null_result'
        else:txs.append((x,tx))

    accounted=stream_sigs|{x for x,_ in txs}
    fraction=len(accounted&expected)/len(expected) if expected else 0.0
    valid=bool(not errors and stable and not signature_cap_hit and not fetch_cap_hit and fraction>=a.min_fraction)

    ev=list(confirmed_stream)
    for x,tx in txs:ev.extend(extract_trade_events_from_transaction(tx,x))
    dedup={event_key(x):x for x in ev};ev=list(dedup.values())
    trades=normalize_trades(launch,ev,launch_s)
    f1=build_livecore_features(launch,trades,decision_age_s=a.age_s,launch_unix_s=launch_s)
    f2=build_livecore_v2_features(launch,trades,decision_age_s=a.age_s,launch_unix_s=launch_s)
    score=scorer.score(f1)
    q={'audit_version':AUDIT_VERSION,'create_tx_ok':True,'create_error':ce,'launch_block_time':launch_s,'history_sweeps':len(sweeps),
       'history_stable_final_sweep':stable,'sweep_errors':errors,'signature_index_cap_hit':signature_cap_hit,
       'expected_signatures':len(expected),'stream_confirmed_signatures_reused':len(stream_sigs&expected),
       'missing_signatures_requested':len(missing),'transactions_fetched_for_gaps':len(txs),'transaction_failures':len(txerr),
       'signature_accounting_fraction':fraction,'tx_fetch_cap_hit':fetch_cap_hit,'failed_transactions':txerr,
       'raw_stream_events_reused':len(confirmed_stream),'audit_valid':valid,
       'guard':'Confirmed signature index defines completeness; raw action-time events are reused only for signatures present in confirmed history.'}
    return valid,q,f1,f2,score

async def main_async(a):
    rows_path=Path(a.rows);launch_path=Path(a.launches);tape_path=Path(a.tapes) if a.tapes else None
    rows=[json.loads(x) for x in rows_path.read_text().splitlines() if x.strip()]
    launches={x['mint']:x for x in (json.loads(y) for y in launch_path.read_text().splitlines() if y.strip())}
    tapes={}
    if tape_path and tape_path.exists():
        tapes={x['mint']:x for x in (json.loads(y) for y in tape_path.read_text().splitlines() if y.strip())}
    scorer=LiveCoreScorer(a.bundle);p=Pacer(a.rpc_interval);selected=[r for r in rows if (r.get('audit_selection') or {}).get('selected')]
    async with aiohttp.ClientSession(headers={'User-Agent':'microcap-runner-ht-audit/0.2'}) as s:
        for r in selected:
            launch=launches.get(r['mint'])
            if not launch:
                r['audit_status']='INVALID';r['data_status']='DATA_INVALID';r['data_quality']={'audit_version':AUDIT_VERSION,'audit_valid':False,'reason':'missing_launch_payload'};continue
            valid,q,f1,f2,score=await audit_one(s,p,r,launch,tapes.get(r['mint']),scorer,a)
            r['audit_status']='CONFIRMED' if valid else 'INVALID';r['data_status']='VALID' if valid else 'DATA_INVALID';r['data_quality']=q
            r['audit_features']=f1;r['audit_v2_challenger_features']=f2;r['audit_scores']=score and score['scores'];r['audit_decision']=score and score['decision'];r['audit_scored_ms']=int(time.time()*1000)
            try:r['audit_10x_score_delta']=float(score['scores']['10']['score'])-float(r['scores']['10']['score'])
            except Exception:r['audit_10x_score_delta']=None
            r['audit_decision_changed']=bool(score and score['decision']!=r['decision'])
            r['audit_feature_coverage']=feature_coverage(f1) if f1 else None
    rows_path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    qs=[r.get('data_quality') or {} for r in selected]
    print(json.dumps({'audit_version':AUDIT_VERSION,'rows':len(rows),'selected':len(selected),
                      'valid':sum(r.get('data_status')=='VALID' for r in selected),'invalid':sum(r.get('data_status')=='DATA_INVALID' for r in selected),
                      'not_audited':len(rows)-len(selected),'expected_signatures':sum(int(q.get('expected_signatures') or 0) for q in qs),
                      'stream_signatures_reused':sum(int(q.get('stream_confirmed_signatures_reused') or 0) for q in qs),
                      'gap_transactions_fetched':sum(int(q.get('transactions_fetched_for_gaps') or 0) for q in qs)},indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--launches',required=True);p.add_argument('--tapes');p.add_argument('--bundle',required=True)
    p.add_argument('--age-s',type=int,default=60);p.add_argument('--sweeps',type=int,default=3);p.add_argument('--sweep-gap-s',type=float,default=2)
    p.add_argument('--tx-limit',type=int,default=1000);p.add_argument('--max-txs',type=int,default=750);p.add_argument('--rpc-interval',type=float,default=.22)
    p.add_argument('--min-fraction',type=float,default=.98);asyncio.run(main_async(p.parse_args()))
if __name__=='__main__':main()
