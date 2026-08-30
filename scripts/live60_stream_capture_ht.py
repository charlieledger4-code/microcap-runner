#!/usr/bin/env python3
"""High-throughput prospective live60 capture.

Scores every observed Pump launch at the immutable observer+60s boundary from the
WebSocket event stream.  No RPC audit is performed here: expensive chain audits
are delegated to ``audit_selected_live60.py`` for a preselected subset.

Paper/research only. No signing or transaction submission exists here.
"""
from __future__ import annotations

import argparse,asyncio,json,os,time
from collections import defaultdict
from pathlib import Path

import websockets

from src.ingest.pump_log_events import iter_pump_trade_events
from src.live.feature60 import normalize_trades,build_livecore_features,feature_coverage
from src.live.feature60_v2 import build_livecore_v2_features
from src.live.scoring import LiveCoreScorer
from src.execution.pump_curve_quote import state_from_trade_event,quote_buy_by_gross_sol

PUMPPORTAL_WS=os.environ.get('PUMPPORTAL_WSS_URL','wss://pumpportal.fun/api/data')
SOLANA_WSS=os.environ.get('SOLANA_WSS_URL','wss://api.mainnet-beta.solana.com')


def event_ms(ev):
    t=ev.source_block_time if ev.source_block_time is not None else ev.timestamp
    return int(t*1000)


async def main_async(a):
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    scorer=LiveCoreScorer(a.bundle);started_ms=int(time.time()*1000)
    active={};events=defaultdict(list);decisions=[];tapes=[];launches=[];tasks=[]
    stop=asyncio.Event();stats={'log_envelopes':0,'pump_events':0,'matched_events':0}

    async def log_worker():
        async for env in iter_pump_trade_events(SOLANA_WSS,commitment='processed',stop_event=stop):
            stats['log_envelopes']+=1
            for ev in env['events']:
                stats['pump_events']+=1
                if ev.mint in active:
                    events[ev.mint].append(ev);stats['matched_events']+=1

    async def decide(launch):
        mint=launch['mint'];boundary=launch['received_ms']+int(a.age_s*1000)
        await asyncio.sleep(max(0,(boundary-int(time.time()*1000))/1000))
        observed=[e for e in list(events.get(mint,[])) if event_ms(e)<=boundary]
        anchor=launch['received_ms']/1000.0
        tr=normalize_trades(launch,observed,anchor)
        f1=build_livecore_features(launch,tr,decision_age_s=a.age_s,launch_unix_s=anchor)
        f2=build_livecore_v2_features(launch,tr,decision_age_s=a.age_s,launch_unix_s=anchor)
        score=scorer.score(f1);scored=int(time.time()*1000)
        last=None
        for ev in sorted(observed,key=lambda e:(event_ms(e),e.source_slot or 0)):
            st=state_from_trade_event(ev)
            if st is not None:last=st
        quote=None
        if last is not None:
            try:
                quote=quote_buy_by_gross_sol(last,a.paper_ticket_sol).to_dict()
                quote.update({'protocol_fee_bps':last.protocol_fee_bps,'creator_fee_bps':last.creator_fee_bps,
                              'cashback_fee_bps':last.cashback_fee_bps,'fee_source':'trade_event_or_documented_curve_fallback'})
            except Exception:pass
        row={
            'scanner_version':'stream_ht_v1','mint':mint,'name':launch.get('name'),'symbol':launch.get('symbol'),
            'creator':launch.get('traderPublicKey'),'launch_signature':launch.get('signature'),
            'launch_received_ms':launch['received_ms'],'decision_age_s':a.age_s,'decision_boundary_ms':boundary,
            'scored_ms':scored,'decision_latency_ms':scored-boundary,'direct_trade_events_at_decision':len(observed),
            'normalized_trades_at_decision':len(tr),'features':f1,'v2_challenger_features':f2,
            'feature_coverage':feature_coverage(f1),'decision':score['decision'],'scores':score['scores'],
            'model_contract':score['model_contract'],'rule_version':score.get('rule_version'),
            'paper_curve_quote':quote,'paper_ticket_sol':a.paper_ticket_sol,
            'data_status':'STREAM_ONLY_UNAUDITED','audit_status':'NOT_SELECTED_YET',
            'guard':'Immutable action-time score. Expensive RPC audit is performed only after outcome-independent selection.',
        }
        decisions.append(row)
        tapes.append({'tape_version':'action_tape_ht_v1','mint':mint,'launch_received_ms':launch['received_ms'],
                      'decision_boundary_ms':boundary,'trade_count':len(tr),'trades':tr,
                      'guard':'Exact normalized tape used for the action-time score.'})
        active.pop(mint,None);events.pop(mint,None)

    log_task=asyncio.create_task(log_worker());await asyncio.sleep(.5)
    errors=[];start=time.time()
    try:
        async with websockets.connect(PUMPPORTAL_WS,ping_interval=20,ping_timeout=20,max_size=2**20) as ws:
            await ws.send(json.dumps({'method':'subscribeNewToken'}))
            while time.time()-start<a.collect_s and len(launches)<a.max_mints:
                remain=max(1,a.collect_s-(time.time()-start))
                try:raw=await asyncio.wait_for(ws.recv(),timeout=remain)
                except asyncio.TimeoutError:break
                recv=int(time.time()*1000)
                try:obj=json.loads(raw)
                except json.JSONDecodeError:continue
                if obj.get('txType')=='create' and obj.get('mint'):
                    launch={'received_ms':recv,**obj};launches.append(launch);active[obj['mint']]=launch
                    tasks.append(asyncio.create_task(decide(launch)))
    except Exception as e:errors.append(f'{type(e).__name__}:{e}')
    if tasks:await asyncio.gather(*tasks)
    stop.set();log_task.cancel()
    try:await log_task
    except asyncio.CancelledError:pass

    decisions.sort(key=lambda r:(r['launch_received_ms'],r['mint']))
    tapes.sort(key=lambda r:(r['launch_received_ms'],r['mint']))
    (out/'launches.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in launches))
    (out/'scored_rows.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in decisions))
    (out/'action_trade_tapes.jsonl').write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in tapes))
    lats=sorted(r['decision_latency_ms'] for r in decisions);dc={}
    for r in decisions:dc[r['decision']]=dc.get(r['decision'],0)+1
    summary={'scanner_version':'stream_ht_v1','started_ms':started_ms,'ended_ms':int(time.time()*1000),
             'collect_s_requested':a.collect_s,'launches':len(launches),'scored':len(decisions),'errors':errors,
             'decisions':dc,'median_action_latency_ms':lats[len(lats)//2] if lats else None,
             'max_action_latency_ms':max(lats) if lats else None,'stream_stats':stats,
             'guard':'All launches are scored; only a predeclared subset is RPC-audited later.'}
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--bundle',required=True)
    p.add_argument('--collect-s',type=int,default=3000);p.add_argument('--max-mints',type=int,default=5000)
    p.add_argument('--age-s',type=int,default=60);p.add_argument('--paper-ticket-sol',type=float,default=.01)
    asyncio.run(main_async(p.parse_args()))
if __name__=='__main__':main()
