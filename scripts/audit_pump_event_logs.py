#!/usr/bin/env python3
"""Audit one real Pump transaction for directly log-decodable TradeEvent bytes."""
import asyncio,base64,json,os
import aiohttp
from src.ingest.pump_trade_event import decode_trade_event_bytes, extract_trade_events_from_transaction

RPC=os.environ.get('SOLANA_RPC_URL','https://api.mainnet-beta.solana.com')
SIG=os.environ.get('AUDIT_SIGNATURE','2tZgNjRkkj1LU6jyQZGurShaVwKLL9WR4pTtdm53Dx3rcwXG3LektwhQXpCMkXYDCTTLHGryaSZTKBA7bE3eBcWm')

async def main():
    payload={'jsonrpc':'2.0','id':1,'method':'getTransaction','params':[SIG,{'encoding':'json','commitment':'confirmed','maxSupportedTransactionVersion':0}]}
    async with aiohttp.ClientSession() as s:
        async with s.post(RPC,json=payload,timeout=30) as r: obj=await r.json()
    tx=obj.get('result');
    if not tx: raise RuntimeError(obj)
    logs=(tx.get('meta') or {}).get('logMessages') or []; program_data=[];decoded=[]
    for line in logs:
        if 'Program data: ' not in line:continue
        enc=line.split('Program data: ',1)[1].strip();program_data.append(enc)
        try:ev=decode_trade_event_bytes(base64.b64decode(enc))
        except Exception:ev=None
        if ev:decoded.append(ev.to_dict())
    all_events=extract_trade_events_from_transaction(tx,SIG)
    out={'signature':SIG,'slot':tx.get('slot'),'block_time':tx.get('blockTime'),'log_lines':len(logs),'program_data_lines':len(program_data),'trade_events_decoded_directly_from_logs':len(decoded),'trade_events_decoded_total_including_inner_cpi':len(all_events),'direct_event_samples':decoded[:3],'log_prefixes':[x[:180] for x in logs if 'Program data: ' in x][:10]}
    print(json.dumps(out,indent=2))
    open('event_log_audit.json','w').write(json.dumps(out,indent=2))
asyncio.run(main())
