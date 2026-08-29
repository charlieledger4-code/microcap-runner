#!/usr/bin/env python3
"""Bounded paper-only prospective probe of public Pump token-creation events.

This intentionally subscribes only to free new-token/migration streams. It never
submits a transaction and never needs a private key. Raw events are timestamped
at receipt and written append-only for latency/schema inspection.
"""
from __future__ import annotations
import argparse, asyncio, hashlib, json, time
from pathlib import Path
import websockets

URL='wss://pumpportal.fun/api/data'


def now_ms(): return time.time_ns()//1_000_000

def append(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(obj,separators=(',',':'),ensure_ascii=False)+'\n')

def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

async def collect(duration_s:int,out:Path):
    started=now_ms();deadline=time.monotonic()+duration_s;counts={'messages':0,'new_tokens':0,'migrations':0,'other':0};mints=set();errors=[]
    try:
        async with websockets.connect(URL,ping_interval=20,ping_timeout=20,max_queue=100000) as ws:
            await ws.send(json.dumps({'method':'subscribeNewToken'}));await ws.send(json.dumps({'method':'subscribeMigration'}))
            while True:
                remain=deadline-time.monotonic()
                if remain<=0:break
                try:raw=await asyncio.wait_for(ws.recv(),timeout=min(20,remain))
                except asyncio.TimeoutError:continue
                received=now_ms();counts['messages']+=1
                try:p=json.loads(raw)
                except Exception:p={'unparsed':str(raw)}
                mint=p.get('mint') if isinstance(p,dict) else None
                if mint:mints.add(str(mint))
                # Provider event schemas can evolve; preserve raw payload and classify conservatively.
                tx_type=str(p.get('txType','')).lower() if isinstance(p,dict) else ''
                if tx_type in {'create','create_v2'} or ('mint' in p and any(k in p for k in ('name','symbol','uri'))):counts['new_tokens']+=1
                elif 'migration' in tx_type or tx_type=='migrate':counts['migrations']+=1
                else:counts['other']+=1
                append(out,{'received_ms':received,'source':'pumpportal_launch_probe','payload':p})
    except Exception as e:
        errors.append(repr(e));append(out.with_suffix('.health.jsonl'),{'received_ms':now_ms(),'error':repr(e)})
    ended=now_ms();summary={'started_ms':started,'ended_ms':ended,'duration_requested_s':duration_s,'duration_actual_s':(ended-started)/1000,'counts':counts,'unique_mints':len(mints),'errors':errors}
    if out.exists():summary.update({'bytes':out.stat().st_size,'sha256':sha256(out)})
    out.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--duration',type=int,default=300);ap.add_argument('--out',default='reports/live_probe/pumpportal_events.jsonl');a=ap.parse_args()
    if not 10<=a.duration<=1800:raise SystemExit('duration must be 10..1800 seconds')
    asyncio.run(collect(a.duration,Path(a.out)))
