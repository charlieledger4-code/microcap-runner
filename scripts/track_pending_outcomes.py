#!/usr/bin/env python3
"""Track matured prospective candidate/WATCH/control outcomes from the ledger.

Eligible rows are selected before outcomes:
- PAPER_CANDIDATE / PAPER_PRIORITY
- WATCH (for Q95 threshold calibration)
- deterministic random control
- deterministic near-miss control

Champion decisions, shadow adversarial-gate recommendations and action-time
forensics are carried into outcome records unchanged. History is reconstructed
from Solana transactions, Pump TradeEvents and PumpSwap events. A capped or
incomplete history produces OUTCOME_INCOMPLETE and no performance claim.
"""
from __future__ import annotations

import argparse,asyncio,json,os,time
from pathlib import Path

import aiohttp

from src.ingest.pump_trade_event import extract_trade_events_from_transaction
from src.ingest.pumpswap_event import PumpSwapPoolEvent,PumpSwapTradeEvent,extract_pumpswap_events_from_transaction
from src.live.executable_outcomes import pump_exit_points,pumpswap_exit_points,summarize_executable_path

RPC=os.environ.get('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
LAMPORTS=1_000_000_000

class Pacer:
    def __init__(self,interval=.28):self.interval=interval;self.lock=asyncio.Lock();self.next_at=0.0
    async def wait(self):
        async with self.lock:
            now=time.monotonic();d=max(0,self.next_at-now)
            if d:await asyncio.sleep(d)
            self.next_at=time.monotonic()+self.interval

async def rpc(session,pacer,method,params,retries=9):
    payload={'jsonrpc':'2.0','id':1,'method':method,'params':params};back=.5
    for attempt in range(retries):
        await pacer.wait()
        try:
            async with session.post(RPC,json=payload,timeout=aiohttp.ClientTimeout(total=25)) as r:
                text=await r.text()
                if r.status==429 or r.status>=500:
                    await asyncio.sleep(back);back=min(8,back*1.7);continue
                if r.status!=200:return None,f'http_{r.status}:{text[:160]}'
                obj=json.loads(text)
                if obj.get('error'):
                    code=(obj['error'] or {}).get('code') if isinstance(obj['error'],dict) else None
                    if code in (-32005,-32004,-32603):
                        await asyncio.sleep(back);back=min(8,back*1.7);continue
                    return None,f"rpc:{obj['error']}"
                return obj.get('result'),None
        except Exception as e:
            if attempt+1==retries:return None,f'{type(e).__name__}:{e}'
            await asyncio.sleep(back);back=min(8,back*1.7)
    return None,'retries_exhausted'

async def signatures_window(session,pacer,address,start_s,end_s,max_pages):
    before=None;selected=[];errors=[];pages=0;reached_start=False
    while pages<max_pages:
        opts={'limit':1000,'commitment':'confirmed'}
        if before:opts['before']=before
        rows,e=await rpc(session,pacer,'getSignaturesForAddress',[address,opts]);pages+=1
        if e:errors.append(e);break
        rows=rows or []
        if not rows:reached_start=True;break
        for x in rows:
            bt=x.get('blockTime')
            if x.get('err') is None and bt is not None and start_s-2<=bt<=end_s+2:selected.append(x)
        times=[x.get('blockTime') for x in rows if x.get('blockTime') is not None]
        if times and min(times)<start_s-2:reached_start=True;break
        if len(rows)<1000:reached_start=True;break
        before=rows[-1].get('signature')
        if not before:break
    d={x['signature']:x for x in selected if x.get('signature')}
    return sorted(d.values(),key=lambda x:(x.get('blockTime') or 0,x['signature'])),{
        'pages':pages,'errors':errors,'reached_start_boundary':reached_start,'page_cap_hit':pages>=max_pages and not reached_start,
    }

async def fetch_transactions(session,pacer,sigs,max_txs):
    txs=[];errors=[];truncated=len(sigs)>max_txs
    for x in sigs[:max_txs]:
        sig=x['signature'];tx,e=await rpc(session,pacer,'getTransaction',[sig,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}])
        if tx is None:errors.append({'signature':sig,'error':e or 'null_result'})
        else:txs.append((sig,tx))
    return txs,errors,truncated


def eligible(row):
    # Hard boundary: development scans from v1-v3 never enter the prospective
    # performance denominator, even if their JSON happens to contain controls.
    if row.get('scanner_version')!='stream_v4' or row.get('data_status')!='VALID':return False
    controls=row.get('prospective_controls') or {}
    return row.get('decision') in ('PAPER_PRIORITY','PAPER_CANDIDATE','WATCH') or bool(controls.get('random_control')) or bool(controls.get('near_miss_control'))


def scan_rows(ledger:Path,horizon_s:int,now_ms:int):
    found=[];root=ledger/'prospective'/'scans'
    for p in sorted(root.glob('*/scored_rows.jsonl')) if root.exists() else []:
        scan_id=p.parent.name
        for line in p.read_text().splitlines():
            if not line.strip():continue
            r=json.loads(line)
            if not eligible(r):continue
            scored=r.get('scored_ms')
            if not scored or now_ms<int(scored)+horizon_s*1000:continue
            out=ledger/'prospective'/'outcomes'/scan_id/r['mint']/f'{horizon_s}s.json'
            if out.exists():continue
            found.append((scan_id,r,out))
    return found

async def track_one(session,pacer,row,horizon_s,max_pages,max_txs,entry_network_lamports,exit_network_lamports):
    mint=row['mint'];scored_ms=int(row['scored_ms']);end_s=scored_ms/1000+horizon_s
    q=row.get('paper_curve_quote') or {};tokens=int(q.get('tokens_out_raw') or 0);gross=int(q.get('gross_quote_in_raw') or 0);entry_avg=q.get('average_price_sol')
    if tokens<=0 or gross<=0 or not entry_avg:
        return {'status':'OUTCOME_INCOMPLETE','reason':'missing_action_time_curve_quote','mint':mint,'horizon_s':horizon_s}
    entry_total=(gross+entry_network_lamports)/LAMPORTS;start_s=max(0,scored_ms/1000-120)
    msigs,mhist=await signatures_window(session,pacer,mint,start_s,end_s,max_pages)
    mtx,mtxerr,mtrunc=await fetch_transactions(session,pacer,msigs,max_txs)
    pump_events=[];pool_events=[];swap_events_from_mint=[]
    for sig,tx in mtx:
        pump_events.extend(extract_trade_events_from_transaction(tx,sig))
        for ev in extract_pumpswap_events_from_transaction(tx,sig):
            if isinstance(ev,PumpSwapPoolEvent) and ev.base_mint==mint:pool_events.append(ev)
            elif isinstance(ev,PumpSwapTradeEvent):swap_events_from_mint.append(ev)
    pool=min(pool_events,key=lambda x:x.timestamp) if pool_events else None
    swap_events=list(swap_events_from_mint);phist=None;ptxerr=[];ptrunc=False
    if pool is not None:
        psigs,phist=await signatures_window(session,pacer,pool.pool,max(start_s,pool.timestamp-2),end_s,max_pages)
        ptx,ptxerr,ptrunc=await fetch_transactions(session,pacer,psigs,max_txs)
        for sig,tx in ptx:
            for ev in extract_pumpswap_events_from_transaction(tx,sig):
                if isinstance(ev,PumpSwapTradeEvent) and ev.pool==pool.pool:swap_events.append(ev)
    sd={}
    for ev in swap_events:sd[(ev.side,ev.pool,ev.user,ev.timestamp,ev.base_amount_raw,ev.quote_amount_raw)]=ev
    swap_events=list(sd.values())
    ppoints=pump_exit_points(pump_events,mint=mint,tokens_owned_raw=tokens,entry_total_outlay_sol=entry_total,entry_average_price_sol=float(entry_avg),after_ms=scored_ms,exit_network_lamports=exit_network_lamports)
    spoints=pumpswap_exit_points(swap_events,pool=pool,tokens_owned_raw=tokens,entry_total_outlay_sol=entry_total,entry_average_price_sol=float(entry_avg),after_ms=scored_ms,exit_network_lamports=exit_network_lamports) if pool else []
    points=sorted(ppoints+spoints,key=lambda x:x.t_ms)
    complete=bool(not mhist['errors'] and mhist['reached_start_boundary'] and not mhist['page_cap_hit'] and not mtxerr and not mtrunc)
    if pool is not None:complete=complete and bool(phist and not phist['errors'] and phist['reached_start_boundary'] and not phist['page_cap_hit'] and not ptxerr and not ptrunc)
    summary=summarize_executable_path(points)
    return {
        'status':'COMPLETE' if complete else 'OUTCOME_INCOMPLETE','scanner_version':row.get('scanner_version'),'mint':mint,'name':row.get('name'),'symbol':row.get('symbol'),
        'horizon_s':horizon_s,'scored_ms':scored_ms,'cutoff_ms':int(end_s*1000),
        'decision':row.get('decision'),'audit_decision':row.get('audit_decision'),'gated_decision':row.get('gated_decision'),'operational_paper_decision':row.get('operational_paper_decision'),
        'adversarial_gate':row.get('adversarial_gate'),'action_forensics':row.get('action_forensics'),'prospective_controls':row.get('prospective_controls'),
        'entry':{
            'quote_source':'action_time_last_observed_pump_state','gross_quote_in_raw':gross,'tokens_owned_raw':tokens,'average_price_sol':entry_avg,
            'entry_network_lamports':entry_network_lamports,'entry_total_outlay_sol':entry_total,'account_rent_included':False,
            'curve_fee_source':q.get('fee_source'),'curve_total_fee_bps':q.get('total_fee_bps'),'curve_protocol_fee_bps':q.get('protocol_fee_bps'),'curve_creator_fee_bps':q.get('creator_fee_bps'),'curve_cashback_fee_bps':q.get('cashback_fee_bps'),
        },
        'migration':{'observed':pool is not None,'pool':pool.pool if pool else None,'timestamp':pool.timestamp if pool else None},
        'history_quality':{'pump':mhist,'pump_tx_errors':mtxerr,'pump_tx_truncated':mtrunc,'pumpswap':phist,'pumpswap_tx_errors':ptxerr,'pumpswap_tx_truncated':ptrunc},
        'events':{'pump_trade_events':len(pump_events),'pumpswap_trade_events':len(swap_events),'execution_points':len(points)},
        'outcome':summary if complete else None,'diagnostic_outcome_even_if_incomplete':summary,
        'guard':'Only status COMPLETE is valid for prospective statistics. Champion and gate decisions remain separate. Account-rent capital and unknown priority/Jito costs are not yet included.',
    }

async def main_async(a):
    ledger=Path(a.ledger_root);now_ms=int(time.time()*1000);todo=scan_rows(ledger,a.horizon_s,now_ms);pacer=Pacer(a.rpc_interval);results=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),headers={'User-Agent':'microcap-runner-outcomes/0.3'}) as session:
        for scan_id,row,out in todo[:a.max_rows]:
            res=await track_one(session,pacer,row,a.horizon_s,a.max_pages,a.max_txs,a.entry_network_lamports,a.exit_network_lamports)
            out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(res,indent=2));results.append({'scan_id':scan_id,'mint':row['mint'],'path':str(out),'status':res['status'],'decision':row.get('decision'),'gated_decision':row.get('gated_decision')})
    print(json.dumps({'horizon_s':a.horizon_s,'eligible_pending':len(todo),'processed':len(results),'results':results},indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('--ledger-root',required=True);p.add_argument('--horizon-s',type=int,required=True);p.add_argument('--max-rows',type=int,default=12);p.add_argument('--max-pages',type=int,default=8);p.add_argument('--max-txs',type=int,default=2500);p.add_argument('--rpc-interval',type=float,default=.28);p.add_argument('--entry-network-lamports',type=int,default=5000);p.add_argument('--exit-network-lamports',type=int,default=5000)
    asyncio.run(main_async(p.parse_args()))
if __name__=='__main__':main()
