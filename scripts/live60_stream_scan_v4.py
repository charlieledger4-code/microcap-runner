#!/usr/bin/env python3
"""Prospective 60s scanner: WebSocket decision first, RPC audit second.

The action-time record is built only from information observed by the 60-second
boundary.  Slow RPC completeness checks happen *after* that decision and cannot
change the original decision field.  They may invalidate the row for research or
produce an audited comparison score, but they never rewrite hindsight into the
original action-time record.

Paper/research only. No signing or transaction submission exists here.
"""
from __future__ import annotations

import argparse, asyncio, json, os, time
from collections import defaultdict
from pathlib import Path

import aiohttp, websockets

from src.ingest.pump_log_events import iter_pump_trade_events
from src.ingest.pump_trade_event import extract_trade_events_from_transaction
from src.live.feature60 import normalize_trades, build_livecore_features, feature_coverage
from src.live.feature60_v2 import build_livecore_v2_features
from src.live.scoring import LiveCoreScorer
from src.execution.pump_curve_quote import state_from_trade_event, quote_buy_by_gross_sol

PUMPPORTAL_WS=os.environ.get('PUMPPORTAL_WSS_URL','wss://pumpportal.fun/api/data')
SOLANA_RPC=os.environ.get('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
SOLANA_WSS=os.environ.get('SOLANA_WSS_URL','wss://api.mainnet-beta.solana.com')


class Pacer:
    def __init__(self,interval=.25):self.interval=interval;self.lock=asyncio.Lock();self.next_at=0.0
    async def wait(self):
        async with self.lock:
            now=time.monotonic();delay=max(0,self.next_at-now)
            if delay:await asyncio.sleep(delay)
            self.next_at=time.monotonic()+self.interval


async def rpc(session,pacer,method,params,retries=9):
    payload={'jsonrpc':'2.0','id':1,'method':method,'params':params};back=.5
    for attempt in range(retries):
        await pacer.wait()
        try:
            async with session.post(SOLANA_RPC,json=payload,timeout=aiohttp.ClientTimeout(total=25)) as r:
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


def _event_time_ms(ev):
    t=ev.source_block_time if ev.source_block_time is not None else ev.timestamp
    return int(t*1000)


def _score_snapshot(scorer,launch,events,launch_anchor_s,age_s):
    trades=normalize_trades(launch,events,launch_anchor_s)
    f1=build_livecore_features(launch,trades,decision_age_s=age_s,launch_unix_s=launch_anchor_s)
    f2=build_livecore_v2_features(launch,trades,decision_age_s=age_s,launch_unix_s=launch_anchor_s)
    score=scorer.score(f1)
    return trades,f1,f2,score


async def main_async(a):
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);scorer=LiveCoreScorer(a.bundle)
    started_ms=int(time.time()*1000);stop_logs=asyncio.Event();events_by_mint=defaultdict(list);log_stats={'envelopes':0,'events':0}
    states={};decision_tasks=[]

    async def log_worker():
        async for env in iter_pump_trade_events(SOLANA_WSS,commitment='processed',stop_event=stop_logs):
            log_stats['envelopes']+=1
            for ev in env['events']:
                events_by_mint[ev.mint].append(ev);log_stats['events']+=1

    async def action_time_decision(launch):
        mint=launch['mint'];boundary_ms=launch['received_ms']+int(a.age_s*1000)
        await asyncio.sleep(max(0,(boundary_ms-int(time.time()*1000))/1000))
        # Snapshot the direct stream exactly once. Later events are never admitted
        # to the action-time record, even though the global log worker continues.
        observed=[ev for ev in list(events_by_mint.get(mint,[])) if _event_time_ms(ev)<=boundary_ms]
        anchor_s=launch['received_ms']/1000.0
        trades,f1,f2,score=_score_snapshot(scorer,launch,observed,anchor_s,a.age_s)
        scored_ms=int(time.time()*1000)
        last_state=None
        for ev in sorted(observed,key=lambda e:(_event_time_ms(e),e.source_slot or 0)):
            st=state_from_trade_event(ev)
            if st is not None:last_state=st
        quote=None
        if last_state is not None:
            try:quote=quote_buy_by_gross_sol(last_state,a.paper_ticket_sol).to_dict()
            except Exception:quote=None
        states[mint]['action']={
            'scanner_version':'stream_v4','mint':mint,'name':launch.get('name'),'symbol':launch.get('symbol'),'creator':launch.get('traderPublicKey'),
            'launch_signature':launch.get('signature'),'launch_received_ms':launch['received_ms'],'decision_age_basis':'observer_received_time',
            'decision_age_s':a.age_s,'decision_boundary_ms':boundary_ms,'scored_ms':scored_ms,'decision_latency_ms':scored_ms-boundary_ms,
            'direct_trade_events_at_decision':len(observed),'normalized_trades_at_decision':len(trades),
            'features':f1,'v2_challenger_features':f2,'feature_coverage':feature_coverage(f1),
            'decision':score['decision'],'scores':score['scores'],'model_contract':score['model_contract'],'rule_version':score.get('rule_version'),
            'reference_entry_price_sol':f1.get('entry_price_sol'),'paper_curve_quote':quote,'paper_ticket_sol':a.paper_ticket_sol,
            'data_status':'PROVISIONAL_STREAM','guard':'Immutable action-time decision. RPC audit occurs later and cannot rewrite this decision.',
        }

    def on_launch(launch):
        states[launch['mint']]={'launch':launch};decision_tasks.append(asyncio.create_task(action_time_decision(launch)))

    log_task=asyncio.create_task(log_worker());await asyncio.sleep(.4)
    launches,launch_errors=await collect_launches(a.collect_s,a.max_mints,on_launch)
    if decision_tasks:await asyncio.gather(*decision_tasks)
    # Stop accepting events before auditing so audit/backfill cannot leak into the
    # original action-time event snapshot.
    stop_logs.set();log_task.cancel()
    try:await log_task
    except asyncio.CancelledError:pass

    pacer=Pacer(a.rpc_interval)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),headers={'User-Agent':'microcap-runner-research/0.4'}) as session:
        for launch in launches:
            mint=launch['mint'];rec=states[mint]['action'];create_tx,ce=await rpc(session,pacer,'getTransaction',[launch['signature'],{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
            launch_s=(create_tx or {}).get('blockTime');sweeps=[];sweep_errors=[];previous=set()
            if launch_s is not None:
                cut=launch_s+a.age_s
                for i in range(a.sweeps):
                    sigs,se=await rpc(session,pacer,'getSignaturesForAddress',[mint,{'limit':a.tx_limit,'commitment':'confirmed'}])
                    if se:sweep_errors.append({'sweep':i,'error':se});sigs=[]
                    cur={x['signature'] for x in (sigs or []) if x.get('err') is None and x.get('blockTime') is not None and launch_s-2<=x['blockTime']<=cut+2}
                    cur.add(launch['signature']);sweeps.append({'count':len(cur),'added_vs_previous':len(cur-previous),'signatures':sorted(cur)});previous|=cur
                    if i+1<a.sweeps:await asyncio.sleep(a.sweep_gap_s)
            expected=set().union(*(set(x['signatures']) for x in sweeps)) if sweeps else ({launch['signature']} if launch.get('signature') else set())
            # Direct stream data is frozen by the action record's scored_ms. We can
            # use current buffer only for signatures whose event timestamp was <=
            # the action-time observer boundary.
            boundary_ms=rec['decision_boundary_ms']
            direct=[ev for ev in list(events_by_mint.get(mint,[])) if _event_time_ms(ev)<=boundary_ms]
            direct_sigs={ev.source_signature for ev in direct if ev.source_signature}
            txmap={};txerr={};backfill=[]
            if create_tx is not None:txmap[launch['signature']]=create_tx
            for sig in sorted(expected-direct_sigs-set(txmap)):
                tx,te=await rpc(session,pacer,'getTransaction',[sig,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
                if tx is not None:txmap[sig]=tx;backfill.extend(extract_trade_events_from_transaction(tx,sig))
                else:txerr[sig]=te or 'null_result'
            accounted=(direct_sigs&expected)|set(txmap);fraction=len(accounted)/len(expected) if expected else 0.0
            stable=bool(len(sweeps)>=2 and sweeps[-1]['added_vs_previous']==0)
            valid=bool(create_tx is not None and launch_s is not None and not sweep_errors and stable and fraction>=a.min_accounting_fraction)
            audit_score=None;audit_features=None;audit_trades=[]
            if launch_s is not None:
                audit_events=direct+backfill
                audit_trades,audit_features,_,audit_score=_score_snapshot(scorer,launch,audit_events,launch_s,a.age_s)
            q={
                'create_tx_ok':create_tx is not None,'create_error':ce,'launch_block_time':launch_s,
                'launch_observation_latency_ms':(launch['received_ms']-int(launch_s*1000)) if launch_s is not None else None,
                'history_sweeps':len(sweeps),'history_stable_final_sweep':stable,'final_sweep_added_old_signatures':sweeps[-1]['added_vs_previous'] if sweeps else None,
                'sweep_errors':sweep_errors,'expected_signatures':len(expected),'direct_event_signatures':len(direct_sigs&expected),
                'backfill_transactions':len(txmap),'backfill_failures':len(txerr),'signature_accounting_fraction':fraction,
                'audit_valid':valid,'failed_backfills':txerr,
            }
            rec['audit_status']='CONFIRMED' if valid else 'INVALID';rec['data_status']='VALID' if valid else 'DATA_INVALID';rec['data_quality']=q
            rec['audit_scored_ms']=int(time.time()*1000);rec['audit_features']=audit_features;rec['audit_normalized_trades']=len(audit_trades)
            rec['audit_decision']=audit_score and audit_score['decision'];rec['audit_scores']=audit_score and audit_score['scores']
            if audit_score:
                try:rec['audit_10x_score_delta']=float(audit_score['scores']['10']['score'])-float(rec['scores']['10']['score'])
                except Exception:rec['audit_10x_score_delta']=None
                rec['audit_decision_changed']=audit_score['decision']!=rec['decision']
            else:
                rec['audit_10x_score_delta']=None;rec['audit_decision_changed']=None

    results=[states[x['mint']]['action'] for x in launches if x['mint'] in states and 'action' in states[x['mint']]]
    (out/'launches.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in launches))
    (out/'scored_rows.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in results))
    valid=[r for r in results if r['data_status']=='VALID'];lats=sorted(r['decision_latency_ms'] for r in results)
    deltas=[abs(r['audit_10x_score_delta']) for r in valid if r.get('audit_10x_score_delta') is not None]
    summary={
        'started_ms':started_ms,'ended_ms':int(time.time()*1000),'scanner_version':'stream_v4','launches':len(launches),'launch_errors':launch_errors,
        'valid_mints':len(valid),'invalid_mints':len(results)-len(valid),'decisions':{},'direct_log_stats':log_stats,
        'median_action_latency_ms':lats[len(lats)//2] if lats else None,'max_action_latency_ms':max(lats) if lats else None,
        'median_abs_audit_10x_score_delta':sorted(deltas)[len(deltas)//2] if deltas else None,
        'audit_decision_changes':sum(bool(r.get('audit_decision_changed')) for r in valid),
        'direct_signature_fraction':(sum(r.get('data_quality',{}).get('direct_event_signatures',0) for r in results)/sum(r.get('data_quality',{}).get('expected_signatures',0) for r in results)) if sum(r.get('data_quality',{}).get('expected_signatures',0) for r in results) else None,
        'guard':'Action-time decisions are immutable. Audit status is outcome-independent data-quality evidence recorded later.',
    }
    for r in results:summary['decisions'][r['decision']]=summary['decisions'].get(r['decision'],0)+1
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='reports/live60_stream_v4');p.add_argument('--bundle',required=True)
    p.add_argument('--collect-s',type=int,default=30);p.add_argument('--max-mints',type=int,default=12);p.add_argument('--age-s',type=int,default=60)
    p.add_argument('--paper-ticket-sol',type=float,default=.01);p.add_argument('--tx-limit',type=int,default=500);p.add_argument('--sweeps',type=int,default=3)
    p.add_argument('--sweep-gap-s',type=float,default=2);p.add_argument('--rpc-interval',type=float,default=.28);p.add_argument('--min-accounting-fraction',type=float,default=.98)
    asyncio.run(main_async(p.parse_args()))

if __name__=='__main__':main()
