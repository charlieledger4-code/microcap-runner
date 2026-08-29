#!/usr/bin/env python3
"""Stream-v4 scanner plus immutable action-time trade-tape persistence.

This is a thin instrumentation wrapper around ``live60_stream_scan_v4``.  It
captures the *first* feature-construction call for each mint, which is the
immutable action-time snapshot, and writes the normalized trades used by that
snapshot.  Later RPC-audit feature reconstruction is deliberately ignored by the
capture hook so future/backfilled data cannot enter the action tape.
"""
from __future__ import annotations

import argparse, asyncio, json
from pathlib import Path

import scripts.live60_stream_scan_v4 as v4


async def main_async(a):
    captured={}
    original=v4._score_snapshot

    def wrapped(scorer,launch,events,launch_anchor_s,age_s):
        result=original(scorer,launch,events,launch_anchor_s,age_s)
        mint=launch.get('mint')
        if mint and mint not in captured:
            trades=result[0]
            captured[mint]={
                'tape_version':'action_tape_v1',
                'mint':mint,
                'name':launch.get('name'),'symbol':launch.get('symbol'),
                'launch_received_ms':launch.get('received_ms'),
                'decision_age_s':age_s,
                'trade_count':len(trades),
                'trades':trades,
                'guard':'Captured from first action-time feature construction only; RPC audit calls cannot overwrite this tape.',
            }
        return result

    v4._score_snapshot=wrapped
    try:
        await v4.main_async(a)
    finally:
        v4._score_snapshot=original
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    p=out/'action_trade_tapes.jsonl'
    p.write_text(''.join(json.dumps(captured[k],separators=(',',':'))+'\n' for k in sorted(captured)))
    print(json.dumps({'tape_version':'action_tape_v1','mints':len(captured),'trades':sum(x['trade_count'] for x in captured.values())},indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='reports/live60_stream_v4');p.add_argument('--bundle',required=True)
    p.add_argument('--collect-s',type=int,default=30);p.add_argument('--max-mints',type=int,default=12);p.add_argument('--age-s',type=int,default=60)
    p.add_argument('--paper-ticket-sol',type=float,default=.01);p.add_argument('--tx-limit',type=int,default=500);p.add_argument('--sweeps',type=int,default=3)
    p.add_argument('--sweep-gap-s',type=float,default=2);p.add_argument('--rpc-interval',type=float,default=.28);p.add_argument('--min-accounting-fraction',type=float,default=.98)
    asyncio.run(main_async(p.parse_args()))

if __name__=='__main__':main()
