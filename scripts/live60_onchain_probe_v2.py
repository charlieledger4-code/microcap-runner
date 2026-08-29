#!/usr/bin/env python3
"""Prospective free-RPC 60s reconstruction with explicit completeness gates.

Version 2 deliberately prefers completeness over speed: signatures are swept three
times after the decision boundary and transactions are fetched under a global rate
limiter. Any incomplete candidate is DATA_INVALID rather than silently imputed.
Paper/research only.
"""
from __future__ import annotations
import argparse, asyncio, json, os, time
from pathlib import Path
from typing import Any
import aiohttp, websockets

from src.ingest.pump_trade_event import extract_trade_events_from_transaction
from src.live.feature60 import normalize_trades, build_livecore_features, feature_coverage

WS=os.environ.get('PUMPPORTAL_WSS_URL','wss://pumpportal.fun/api/data')
RPC=os.environ.get('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')

class Pacer:
    def __init__(self, interval=.28):
        self.interval=interval; self.lock=asyncio.Lock(); self.next_at=0.0
    async def wait(self):
        async with self.lock:
            now=time.monotonic(); delay=max(0,self.next_at-now)
            if delay:await asyncio.sleep(delay)
            self.next_at=time.monotonic()+self.interval

async def rpc(session, pacer, method, params, retries=8):
    payload={'jsonrpc':'2.0','id':1,'method':method,'params':params}; back=.5
    for attempt in range(retries):
        await pacer.wait()
        try:
            async with session.post(RPC,json=payload,timeout=aiohttp.ClientTimeout(total=25)) as r:
                text=await r.text()
                if r.status==429 or r.status>=500:
                    await asyncio.sleep(back);back=min(back*1.7,8);continue
                if r.status!=200:return None,f'http_{r.status}:{text[:180]}'
                obj=json.loads(text)
                if obj.get('error'):
                    code=(obj['error'] or {}).get('code') if isinstance(obj['error'],dict) else None
                    if code in (-32005,-32004,-32603):
                        await asyncio.sleep(back);back=min(back*1.7,8);continue
                    return None,f"rpc:{obj['error']}"
                return obj.get('result'),None
        except Exception as e:
            if attempt+1==retries:return None,f'{type(e).__name__}:{e}'
            await asyncio.sleep(back);back=min(back*1.7,8)
    return None,'retries_exhausted'

async def collect_launches(seconds,max_mints):
    launches=[];errors=[];start=time.time()
    try:
        async with websockets.connect(WS,ping_interval=20,ping_timeout=20,max_size=2**20) as ws:
            await ws.send(json.dumps({'method':'subscribeNewToken'}))
            while time.time()-start<seconds and len(launches)<max_mints:
                try:msg=await asyncio.wait_for(ws.recv(),timeout=max(1,seconds-(time.time()-start)))
                except asyncio.TimeoutError:break
                recv=int(time.time()*1000);obj=json.loads(msg)
                if obj.get('txType')=='create' and obj.get('mint'):launches.append({'received_ms':recv,**obj})
    except Exception as e:errors.append(f'{type(e).__name__}:{e}')
    return launches,errors

async def main_async(a):
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);started=int(time.time()*1000)
    launches,launch_errors=await collect_launches(a.collect_s,a.max_mints)
    pacer=Pacer(a.rpc_interval);timeout=aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout,headers={'User-Agent':'microcap-runner-research/0.2'}) as session:
        # Establish launch block time one-by-one; missing creation truth invalidates that mint.
        states=[]
        for launch in launches:
            tx,e=await rpc(session,pacer,'getTransaction',[launch['signature'],{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
            launch_s=(tx or {}).get('blockTime')
            states.append({'launch':launch,'create_tx':tx,'create_error':e,'launch_s':launch_s})
        valid_times=[s['launch_s'] for s in states if s['launch_s']]
        if valid_times:
            await asyncio.sleep(max(0,max(valid_times)+a.age_s+a.grace_s-time.time()))

        # Three independent history sweeps expose RPC indexing lag. Only signatures
        # whose blockTime belongs to the first-minute observation window are kept.
        for state in states:
            state['sweeps']=[];state['sweep_errors']=[]
            if not state['launch_s']:continue
            previous=set();cut=state['launch_s']+a.age_s
            for i in range(a.sweeps):
                sigs,e=await rpc(session,pacer,'getSignaturesForAddress',[state['launch']['mint'],{'limit':a.tx_limit,'commitment':'confirmed'}])
                if e:state['sweep_errors'].append({'sweep':i,'error':e});sigs=[]
                cur={x['signature'] for x in (sigs or []) if x.get('err') is None and x.get('blockTime') is not None and state['launch_s']-2 <= x['blockTime'] <= cut+2}
                cur.add(state['launch']['signature'])
                state['sweeps'].append({'count':len(cur),'added_vs_previous':len(cur-previous),'signatures':cur})
                previous |= cur
                if i+1<a.sweeps:await asyncio.sleep(a.sweep_gap_s)
            state['expected']=set().union(*(x['signatures'] for x in state['sweeps'])) if state['sweeps'] else {state['launch']['signature']}

        # Fetch each transaction only once globally, at conservative request rate.
        all_sigs=set().union(*(s.get('expected',set()) for s in states)) if states else set()
        txmap={};txerr={}
        for sig in sorted(all_sigs):
            # Creation payload already supplies the initial-buy observation, but we
            # still fetch creation tx above to anchor block time. Reuse it here.
            reused=next((s['create_tx'] for s in states if s['launch']['signature']==sig and s['create_tx']),None)
            if reused is not None:txmap[sig]=reused;continue
            tx,e=await rpc(session,pacer,'getTransaction',[sig,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
            if tx is not None:txmap[sig]=tx
            else:txerr[sig]=e or 'null_result'

        results=[]
        for state in states:
            l=state['launch']; expected=state.get('expected',set()); available=[s for s in expected if s in txmap]
            events=[]
            for sig in available:events.extend(extract_trade_events_from_transaction(txmap[sig],sig))
            trades=normalize_trades(l,events,state['launch_s'] or l['received_ms']/1000)
            feat=build_livecore_features(l,trades,decision_age_s=a.age_s,launch_unix_s=state['launch_s'] or l['received_ms']/1000)
            fetch_fraction=len(available)/len(expected) if expected else 0.0
            last_added=(state['sweeps'][-1]['added_vs_previous'] if state.get('sweeps') else None)
            # For sweep 0 everything is "added" by definition; stability only means
            # no newly indexed old signatures in the final repeat sweep.
            stable=bool(len(state.get('sweeps',[]))>=2 and last_added==0)
            quality={
                'create_tx_ok':state['create_tx'] is not None,'history_sweeps':len(state.get('sweeps',[])),
                'history_stable_final_sweep':stable,'final_sweep_added_old_signatures':last_added,
                'expected_signatures':len(expected),'transactions_available':len(available),
                'transaction_fetch_fraction':fetch_fraction,'transaction_fetch_failures':len(expected)-len(available),
                'sweep_errors':state.get('sweep_errors',[]),'feature_coverage':feature_coverage(feat),
            }
            quality['data_valid']=bool(quality['create_tx_ok'] and not quality['sweep_errors'] and stable and fetch_fraction>=a.min_fetch_fraction)
            results.append({
                'mint':l['mint'],'name':l.get('name'),'symbol':l.get('symbol'),'creator':l.get('traderPublicKey'),
                'launch_signature':l.get('signature'),'launch_received_ms':l['received_ms'],'launch_block_time':state['launch_s'],
                'decision_age_s':a.age_s,'data_status':'VALID' if quality['data_valid'] else 'DATA_INVALID',
                'data_quality':quality,'trade_events_decoded':len(events),'normalized_trades':len(trades),
                'features':feat,'failed_signatures':{s:txerr.get(s) for s in expected if s not in txmap},
                'event_sample':[e.to_dict() for e in events[:8]],
            })
    def serial_state(s):
        return {'mint':s['launch']['mint'],'sweeps':[{k:(sorted(v) if k=='signatures' else v) for k,v in x.items()} for x in s.get('sweeps',[]) ]}
    (out/'launches.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in launches))
    (out/'feature_rows.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in results))
    (out/'sweep_audit.jsonl').write_text(''.join(json.dumps(serial_state(s),separators=(',',':'))+'\n' for s in states))
    summary={'started_ms':started,'ended_ms':int(time.time()*1000),'rpc':RPC,'launches':len(launches),'launch_errors':launch_errors,'valid_mints':sum(r['data_status']=='VALID' for r in results),'invalid_mints':sum(r['data_status']!='VALID' for r in results),'total_trade_events':sum(r['trade_events_decoded'] for r in results),'total_expected_signatures':sum(r['data_quality']['expected_signatures'] for r in results),'total_available_transactions':sum(r['data_quality']['transactions_available'] for r in results),'global_fetch_fraction':(sum(r['data_quality']['transactions_available'] for r in results)/sum(r['data_quality']['expected_signatures'] for r in results)) if sum(r['data_quality']['expected_signatures'] for r in results) else None,'guard':'Prospective reconstruction/completeness probe only. DATA_INVALID rows cannot be scored or paper-traded.'}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='reports/live60_onchain_v2');p.add_argument('--collect-s',type=int,default=20);p.add_argument('--max-mints',type=int,default=2);p.add_argument('--age-s',type=int,default=60);p.add_argument('--grace-s',type=int,default=10);p.add_argument('--tx-limit',type=int,default=300);p.add_argument('--sweeps',type=int,default=3);p.add_argument('--sweep-gap-s',type=float,default=3);p.add_argument('--rpc-interval',type=float,default=.28);p.add_argument('--min-fetch-fraction',type=float,default=.98);a=p.parse_args();asyncio.run(main_async(a))
if __name__=='__main__':main()
