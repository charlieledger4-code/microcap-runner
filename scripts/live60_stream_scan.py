#!/usr/bin/env python3
"""WebSocket-first 60-second prospective Pump scanner.

Fast path: decode Pump TradeEvents directly from Solana logsSubscribe.
Truth/completeness path: repeat mint signature-index sweeps and fetch only
signatures missing from the WebSocket event stream.  Each mint is finalized and
scored independently near its 60-second boundary instead of waiting for the whole
batch. Paper/research only.
"""
from __future__ import annotations

import argparse, asyncio, json, os, time
from collections import defaultdict
from pathlib import Path
from typing import Any

import aiohttp
import websockets

from src.ingest.pump_log_events import iter_pump_trade_events
from src.ingest.pump_trade_event import extract_trade_events_from_transaction
from src.live.feature60 import normalize_trades, build_livecore_features, feature_coverage
from src.live.feature60_v2 import build_livecore_v2_features
from src.live.scoring import LiveCoreScorer

PUMPPORTAL_WS=os.environ.get('PUMPPORTAL_WSS_URL','wss://pumpportal.fun/api/data')
SOLANA_RPC=os.environ.get('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
SOLANA_WSS=os.environ.get('SOLANA_WSS_URL','wss://api.mainnet-beta.solana.com')


class Pacer:
    def __init__(self,interval=.22):self.interval=interval;self.lock=asyncio.Lock();self.next_at=0.0
    async def wait(self):
        async with self.lock:
            now=time.monotonic();delay=max(0,self.next_at-now)
            if delay:await asyncio.sleep(delay)
            self.next_at=time.monotonic()+self.interval


async def rpc(session,pacer,method,params,retries=8):
    payload={'jsonrpc':'2.0','id':1,'method':method,'params':params};back=.35
    for attempt in range(retries):
        await pacer.wait()
        try:
            async with session.post(SOLANA_RPC,json=payload,timeout=aiohttp.ClientTimeout(total=20)) as r:
                text=await r.text()
                if r.status==429 or r.status>=500:
                    await asyncio.sleep(back);back=min(back*1.7,6);continue
                if r.status!=200:return None,f'http_{r.status}:{text[:160]}'
                obj=json.loads(text)
                if obj.get('error'):
                    code=(obj['error'] or {}).get('code') if isinstance(obj['error'],dict) else None
                    if code in (-32005,-32004,-32603):
                        await asyncio.sleep(back);back=min(back*1.7,6);continue
                    return None,f"rpc:{obj['error']}"
                return obj.get('result'),None
        except Exception as e:
            if attempt+1==retries:return None,f'{type(e).__name__}:{e}'
            await asyncio.sleep(back);back=min(back*1.7,6)
    return None,'retries_exhausted'


async def collect_launches(seconds,max_mints,on_launch):
    launches=[];errors=[];start=time.time()
    try:
        async with websockets.connect(PUMPPORTAL_WS,ping_interval=20,ping_timeout=20,max_size=2**20) as ws:
            await ws.send(json.dumps({'method':'subscribeNewToken'}))
            while time.time()-start<seconds and len(launches)<max_mints:
                try:raw=await asyncio.wait_for(ws.recv(),timeout=max(1,seconds-(time.time()-start)))
                except asyncio.TimeoutError:break
                recv=int(time.time()*1000)
                try:obj=json.loads(raw)
                except json.JSONDecodeError:continue
                if obj.get('txType')=='create' and obj.get('mint'):
                    launch={'received_ms':recv,**obj};launches.append(launch);on_launch(launch)
    except Exception as e:errors.append(f'{type(e).__name__}:{e}')
    return launches,errors


async def main_async(a):
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    scorer=LiveCoreScorer(a.bundle)
    started_ms=int(time.time()*1000);stop_logs=asyncio.Event();events_by_mint=defaultdict(list);log_stats={'envelopes':0,'events':0}
    states={};final_tasks=[];pacer=Pacer(a.rpc_interval)
    session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),headers={'User-Agent':'microcap-runner-research/0.3'})

    async def log_worker():
        async for env in iter_pump_trade_events(SOLANA_WSS,commitment='processed',stop_event=stop_logs):
            log_stats['envelopes']+=1
            for ev in env['events']:
                events_by_mint[ev.mint].append(ev);log_stats['events']+=1

    async def finalize(launch):
        mint=launch['mint'];st=states[mint]
        create_tx,e=await rpc(session,pacer,'getTransaction',[launch['signature'],{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
        st['create_tx_ok']=create_tx is not None;st['create_error']=e
        launch_s=(create_tx or {}).get('blockTime')
        # Fail closed if exact chain time is unavailable; received time is retained only diagnostically.
        st['launch_s']=launch_s
        if launch_s is None:
            st['result']={'mint':mint,'name':launch.get('name'),'symbol':launch.get('symbol'),'data_status':'DATA_INVALID','decision':'DATA_INVALID','reason':'missing_creation_block_time','launch':launch}
            return
        decision_boundary_ms=int((launch_s+a.age_s)*1000)
        await asyncio.sleep(max(0,(decision_boundary_ms+a.grace_ms-int(time.time()*1000))/1000))

        sweeps=[];sweep_errors=[];previous=set();cut=launch_s+a.age_s
        for i in range(a.sweeps):
            sigs,se=await rpc(session,pacer,'getSignaturesForAddress',[mint,{'limit':a.tx_limit,'commitment':'confirmed'}])
            if se:sweep_errors.append({'sweep':i,'error':se});sigs=[]
            cur={x['signature'] for x in (sigs or []) if x.get('err') is None and x.get('blockTime') is not None and launch_s-2<=x['blockTime']<=cut+2}
            cur.add(launch['signature'])
            sweeps.append({'count':len(cur),'added_vs_previous':len(cur-previous),'signatures':sorted(cur)})
            previous|=cur
            if i+1<a.sweeps:await asyncio.sleep(a.sweep_gap_s)
        expected=set().union(*(set(x['signatures']) for x in sweeps)) if sweeps else {launch['signature']}

        direct=[ev for ev in list(events_by_mint.get(mint,[])) if launch_s-2<=ev.timestamp<=cut+2]
        direct_sigs={ev.source_signature for ev in direct if ev.source_signature}
        txmap={launch['signature']:create_tx};txerr={};backfill=[]
        for sig in sorted(expected-direct_sigs-{launch['signature']}):
            tx,te=await rpc(session,pacer,'getTransaction',[sig,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
            if tx is not None:
                txmap[sig]=tx;backfill.extend(extract_trade_events_from_transaction(tx,sig))
            else:txerr[sig]=te or 'null_result'
        accounted=(direct_sigs&expected)|set(txmap)
        fraction=len(accounted)/len(expected) if expected else 0.0
        stable=bool(len(sweeps)>=2 and sweeps[-1]['added_vs_previous']==0)
        events=direct+backfill
        trades=normalize_trades(launch,events,launch_s)
        f1=build_livecore_features(launch,trades,decision_age_s=a.age_s,launch_unix_s=launch_s)
        f2=build_livecore_v2_features(launch,trades,decision_age_s=a.age_s,launch_unix_s=launch_s)
        quality={
            'create_tx_ok':create_tx is not None,'history_sweeps':len(sweeps),'history_stable_final_sweep':stable,
            'final_sweep_added_old_signatures':sweeps[-1]['added_vs_previous'] if sweeps else None,
            'expected_signatures':len(expected),'direct_event_signatures':len(direct_sigs&expected),
            'backfill_transactions_fetched':len(txmap)-1,'backfill_failures':len(txerr),
            'signature_accounting_fraction':fraction,'sweep_errors':sweep_errors,'feature_coverage_v1':feature_coverage(f1),
        }
        valid=bool(create_tx is not None and not sweep_errors and stable and fraction>=a.min_accounting_fraction)
        scored_ms=int(time.time()*1000)
        score=scorer.score(f1) if valid else {'decision':'DATA_INVALID','scores':{},'model_contract':scorer.manifest.get('feature_contract')}
        st['result']={
            'scanner_version':'stream_v3','scored_ms':scored_ms,'mint':mint,'name':launch.get('name'),'symbol':launch.get('symbol'),
            'creator':launch.get('traderPublicKey'),'launch_signature':launch.get('signature'),'launch_received_ms':launch['received_ms'],
            'launch_block_time':launch_s,'decision_age_s':a.age_s,'decision_boundary_ms':decision_boundary_ms,
            'decision_latency_ms':scored_ms-decision_boundary_ms,'launch_observation_latency_ms':launch['received_ms']-int(launch_s*1000),
            'data_status':'VALID' if valid else 'DATA_INVALID','data_quality':quality,'direct_trade_events':len(direct),
            'backfilled_trade_events':len(backfill),'normalized_trades':len(trades),'features':f1,'v2_challenger_features':f2,
            'decision':score.get('decision'),'scores':score.get('scores',{}),'model_contract':score.get('model_contract'),
            'rule_version':score.get('rule_version'),'failed_backfills':txerr,'sweeps':sweeps,
            'reference_entry_price_sol':f1.get('entry_price_sol'),
            'guard':'Prospective paper rank. reference_entry_price_sol is the 60s observed state, not a claimed executable fill.',
        }

    def on_launch(launch):
        mint=launch['mint'];states[mint]={'launch':launch};final_tasks.append(asyncio.create_task(finalize(launch)))

    log_task=asyncio.create_task(log_worker())
    launches,launch_errors=await collect_launches(a.collect_s,a.max_mints,on_launch)
    if final_tasks:await asyncio.gather(*final_tasks)
    stop_logs.set();log_task.cancel()
    try:await log_task
    except asyncio.CancelledError:pass
    await session.close()

    results=[states[x['mint']].get('result') for x in launches if states.get(x['mint'],{}).get('result')]
    (out/'launches.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in launches))
    (out/'scored_rows.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in results))
    summary={
        'started_ms':started_ms,'ended_ms':int(time.time()*1000),'scanner_version':'stream_v3','rpc':SOLANA_RPC,'wss':SOLANA_WSS,
        'launches':len(launches),'launch_errors':launch_errors,'valid_mints':sum(x['data_status']=='VALID' for x in results),
        'invalid_mints':sum(x['data_status']!='VALID' for x in results),'decisions':{},'direct_log_stats':log_stats,
        'median_decision_latency_ms':None,'p95_decision_latency_ms':None,
        'guard':'Every observed launch is retained. DATA_INVALID rows are never paper candidates.',
    }
    for x in results:summary['decisions'][x['decision']]=summary['decisions'].get(x['decision'],0)+1
    lats=sorted(x['decision_latency_ms'] for x in results if x['data_status']=='VALID')
    if lats:
        summary['median_decision_latency_ms']=lats[len(lats)//2]
        summary['p95_decision_latency_ms']=lats[min(len(lats)-1,int(.95*(len(lats)-1)))]
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='reports/live60_stream');p.add_argument('--bundle',required=True)
    p.add_argument('--collect-s',type=int,default=30);p.add_argument('--max-mints',type=int,default=12);p.add_argument('--age-s',type=int,default=60)
    p.add_argument('--grace-ms',type=int,default=800);p.add_argument('--tx-limit',type=int,default=400);p.add_argument('--sweeps',type=int,default=3)
    p.add_argument('--sweep-gap-s',type=float,default=1.5);p.add_argument('--rpc-interval',type=float,default=.22);p.add_argument('--min-accounting-fraction',type=float,default=.98)
    asyncio.run(main_async(p.parse_args()))

if __name__=='__main__':main()
