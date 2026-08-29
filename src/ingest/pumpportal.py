"""Raw PumpPortal launch/migration collector.

PumpPortal is an optional third-party low-latency discovery source. The raw chain
collector remains the source of truth. New-token/migration subscriptions are
free according to the provider docs; trade subscriptions are metered.
"""
from __future__ import annotations
import argparse, asyncio, json, os
from pathlib import Path
import websockets
from .common import append_jsonl, now_ms

URL = "wss://pumpportal.fun/api/data"

async def run(out: Path, api_key: str | None = None) -> None:
    uri = URL + (f"?api-key={api_key}" if api_key else "")
    backoff = 1
    while True:
        try:
            async with websockets.connect(uri, ping_interval=25, ping_timeout=20, max_queue=10000) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                backoff = 1
                async for raw in ws:
                    received_ms = now_ms()
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {"unparsed": str(raw)}
                    append_jsonl(out, {"received_ms": received_ms, "source": "pumpportal", "payload": payload})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            append_jsonl(out.with_suffix(".health.jsonl"), {"received_ms": now_ms(), "status": "error", "error": repr(exc)})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/raw/pumpportal_events.jsonl")
    args = p.parse_args()
    asyncio.run(run(Path(args.out), os.getenv("PUMPPORTAL_API_KEY")))
