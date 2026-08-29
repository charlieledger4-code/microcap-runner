#!/usr/bin/env python3
"""Bounded prospective proof: free launch stream -> public Solana RPC -> Pump TradeEvent -> 60s features.

Paper/research only. No wallet, signing, or transaction submission code exists here.
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

async def rpc(session:aiohttp.ClientSession, method:str, params:list[Any], retries:int=6):
    payload={'jsonrpc':'2.0','id':1,'method':method,'params':params}
    delay=.3
    for attempt in range(retries):
        try:
            async with session.post(RPC,json=payload,timeout=aiohttp.ClientTimeout(total=20)) as r:
                text=await r.text()
                if r.status==429 or r.status>=500:
                    await asyncio.sleep(delay); delay=min(delay*2,5); continue
                if r.status!=200: return None, f'http_{r.status}:{text[:200]}'
                obj=json.loads(text)
                if obj.get('error'): return None, f"rpc:{obj['error']}"
                return obj.get('result'),None
        except Exception as e:
            if attempt+1==retries:return None,f'{type(e).__name__}:{e}'
            await asyncio.sleep(delay);delay=min(delay*2,5)
    return None,'retries_exhausted'

async def collect_launches(seconds:int,max_mints:int):
    launches=[]; errors=[]; start=time.time()
    try:
        async with websockets.connect(WS,ping_interval=20,ping_timeout=20,max_size=2**20) as ws:
            await ws.send(json.dumps({'method':'subscribeNewToken'}))
            while time.time()-start<seconds and len(launches)<max_mints:
                try: msg=await asyncio.wait_for(ws.recv(),timeout=max(1,seconds-(time.time()-start)))
                except asyncio.TimeoutError: break
                recv_ms=int(time.time()*1000); obj=json.loads(msg)
                if obj.get('txType')=='create' and obj.get('mint'):
                    launches.append({'received_ms':recv_ms,**obj})
    except Exception as e: errors.append(f'{type(e).__name__}:{e}')
    return launches,errors

async def fetch_one(session,launch,decision_age:int,grace:int,tx_limit:int):
    mint=launch['mint']; errs=[]
    create_tx,err=await rpc(session,'getTransaction',[launch['signature'],{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
    if err:errs.append({'stage':'create_tx','error':err})
    launch_s=(create_tx or {}).get('blockTime') or launch['received_ms']/1000.0
    target=launch_s+decision_age+grace
    sleep=max(0,target-time.time())
    if sleep: await asyncio.sleep(sleep)
    sigs,err=await rpc(session,'getSignaturesForAddress',[mint,{'limit':tx_limit,'commitment':'confirmed'}])
    if err: errs.append({'stage':'signatures','error':err}); sigs=[]
    cutoff=launch_s+decision_age
    keep=[]
    for x in sigs or []:
        bt=x.get('blockTime')
        if x.get('err') is None and bt is not None and launch_s-2 <= bt <= cutoff+2:
            keep.append(x['signature'])
    if launch['signature'] not in keep:keep.append(launch['signature'])
    events=[]; tx_ok=0
    sem=asyncio.Semaphore(2)
    async def gettx(sig):
        async with sem:
            result,e=await rpc(session,'getTransaction',[sig,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
            await asyncio.sleep(.08)
            return sig,result,e
    for batch_start in range(0,len(keep),8):
        got=await asyncio.gather(*(gettx(s) for s in keep[batch_start:batch_start+8]))
        for sig,tx,e in got:
            if e: errs.append({'stage':'transaction','signature':sig,'error':e});continue
            if not tx:continue
            tx_ok+=1; events.extend(extract_trade_events_from_transaction(tx,sig))
    trades=normalize_trades(launch,events,launch_s)
    features=build_livecore_features(launch,trades,decision_age_s=decision_age,launch_unix_s=launch_s)
    return {
        'mint':mint,'name':launch.get('name'),'symbol':launch.get('symbol'),'creator':launch.get('traderPublicKey'),
        'launch_signature':launch.get('signature'),'launch_received_ms':launch['received_ms'],'launch_block_time':launch_s,
        'decision_age_s':decision_age,'signature_count':len(keep),'transactions_fetched':tx_ok,
        'trade_events_decoded':len(events),'normalized_trades':len(trades),'feature_coverage':feature_coverage(features),
        'features':features,'errors':errs,
        'event_sample':[e.to_dict() for e in events[:5]],
    }

async def main_async(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);started=int(time.time()*1000)
    launches,launch_errors=await collect_launches(args.collect_s,args.max_mints)
    timeout=aiohttp.ClientTimeout(total=30);connector=aiohttp.TCPConnector(limit=4)
    async with aiohttp.ClientSession(timeout=timeout,connector=connector,headers={'User-Agent':'microcap-runner-research/0.1'}) as session:
        results=await asyncio.gather(*(fetch_one(session,x,args.age_s,args.grace_s,args.tx_limit) for x in launches)) if launches else []
    (out/'launches.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in launches))
    (out/'feature_rows.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in results))
    summary={'started_ms':started,'ended_ms':int(time.time()*1000),'rpc':RPC,'launches':len(launches),'launch_errors':launch_errors,'mints_with_decoded_trade_events':sum(r['trade_events_decoded']>0 for r in results),'total_trade_events':sum(r['trade_events_decoded'] for r in results),'coverage':[{r['mint']:r['feature_coverage']} for r in results],'rpc_error_count':sum(len(r['errors']) for r in results),'guard':'Prospective decoder/feature-parity probe only. No candidate selection and no trading.'}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='reports/live60_onchain');ap.add_argument('--collect-s',type=int,default=25);ap.add_argument('--max-mints',type=int,default=3);ap.add_argument('--age-s',type=int,default=60);ap.add_argument('--grace-s',type=int,default=8);ap.add_argument('--tx-limit',type=int,default=250);args=ap.parse_args();asyncio.run(main_async(args))
if __name__=='__main__':main()
