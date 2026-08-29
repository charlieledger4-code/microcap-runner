"""Raw Solana program-log collector using standard logsSubscribe.

One subscription is created per monitored program because Solana's `mentions`
filter supports one pubkey per subscription. Full transaction decoding should
be layered on top through getTransaction or a provider transaction stream.
"""
from __future__ import annotations
import argparse, asyncio, json, os
from pathlib import Path
import websockets
from .common import append_jsonl, now_ms

PROGRAMS = {
    "pump": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "pumpswap": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    "meteora_dbc": "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",
}

async def run(wss_url: str, out: Path, commitment: str = "processed") -> None:
    backoff = 1
    while True:
        try:
            async with websockets.connect(wss_url, ping_interval=25, ping_timeout=20, max_queue=50000) as ws:
                ids = {}
                req_id = 1
                for name, pubkey in PROGRAMS.items():
                    ids[req_id] = name
                    req = {"jsonrpc":"2.0","id":req_id,"method":"logsSubscribe","params":[{"mentions":[pubkey]},{"commitment":commitment}]}
                    await ws.send(json.dumps(req))
                    req_id += 1
                backoff = 1
                async for raw in ws:
                    received_ms = now_ms()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = {"unparsed": str(raw)}
                    append_jsonl(out, {"received_ms": received_ms, "source":"solana_logs", "payload":msg})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            append_jsonl(out.with_suffix(".health.jsonl"), {"received_ms":now_ms(),"status":"error","error":repr(exc)})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/raw/solana_logs.jsonl")
    p.add_argument("--wss", default=os.getenv("SOLANA_WSS_URL", "wss://api.mainnet-beta.solana.com"))
    args = p.parse_args()
    asyncio.run(run(args.wss, Path(args.out)))
