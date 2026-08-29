"""Low-latency Pump TradeEvent decoding from Solana ``logsSubscribe``.

Pump emits Anchor event bytes in ``Program data: <base64>`` log lines.  Those
bytes are sufficient to reconstruct the current TradeEvent without fetching the
full transaction.  This module is deliberately small and deterministic so the
live scanner can use WebSocket events as its fast path while retaining RPC
signature/transaction sweeps as an independent completeness audit/backfill.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, AsyncIterator, Iterable

import websockets

from .pump_trade_event import PUMP_PROGRAM_ID, PumpTradeEvent, decode_trade_event_bytes

DEFAULT_WSS = "wss://api.mainnet-beta.solana.com"


def trade_events_from_logs(
    logs: Iterable[str],
    *,
    signature: str | None = None,
    slot: int | None = None,
) -> list[PumpTradeEvent]:
    """Decode and deduplicate Pump TradeEvents from Solana log strings."""
    out: list[PumpTradeEvent] = []
    for line in logs or []:
        if not isinstance(line, str) or "Program data: " not in line:
            continue
        try:
            raw = base64.b64decode(line.split("Program data: ", 1)[1].strip())
        except Exception:
            continue
        ev = decode_trade_event_bytes(raw)
        if ev is None:
            continue
        ev.source_signature = signature
        ev.source_slot = slot
        # logsSubscribe has no blockTime. TradeEvent.timestamp is protocol-native
        # Unix time and is therefore the best chain-native timing fallback.
        ev.source_block_time = ev.timestamp
        out.append(ev)

    dedup: dict[tuple[Any, ...], PumpTradeEvent] = {}
    for ev in out:
        key = (
            ev.mint,
            ev.user,
            ev.timestamp,
            ev.is_buy,
            ev.token_amount_raw,
            ev.sol_amount_raw,
            ev.quote_amount_raw,
        )
        dedup[key] = ev
    return list(dedup.values())


def parse_logs_notification(msg: dict[str, Any], *, received_ms: int | None = None) -> dict[str, Any] | None:
    """Normalize one ``logsNotification`` into a compact event envelope."""
    if msg.get("method") != "logsNotification":
        return None
    params = msg.get("params") or {}
    result = params.get("result") or {}
    context = result.get("context") or {}
    value = result.get("value") or {}
    if value.get("err") is not None:
        return None
    signature = value.get("signature")
    slot = context.get("slot")
    events = trade_events_from_logs(value.get("logs") or [], signature=signature, slot=slot)
    if not events:
        return None
    return {
        "received_ms": int(received_ms if received_ms is not None else time.time() * 1000),
        "signature": signature,
        "slot": slot,
        "events": events,
    }


async def iter_pump_trade_events(
    wss_url: str = DEFAULT_WSS,
    *,
    commitment: str = "processed",
    stop_event: asyncio.Event | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield decoded Pump event envelopes, reconnecting on transient failures.

    The generator intentionally emits only successfully decoded TradeEvents.
    Consumers should maintain a separate health/completeness audit; WebSocket
    delivery alone is never treated as proof that all first-minute trades were
    observed.
    """
    backoff = 0.5
    while stop_event is None or not stop_event.is_set():
        try:
            async with websockets.connect(
                wss_url,
                ping_interval=20,
                ping_timeout=20,
                max_queue=100_000,
                max_size=2**22,
            ) as ws:
                req = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "logsSubscribe",
                    "params": [{"mentions": [PUMP_PROGRAM_ID]}, {"commitment": commitment}],
                }
                await ws.send(json.dumps(req))
                # Consume the subscription acknowledgement before notifications.
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
                ack = json.loads(raw)
                if ack.get("error"):
                    raise RuntimeError(f"logsSubscribe failed: {ack['error']}")
                backoff = 0.5
                while stop_event is None or not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    received_ms = int(time.time() * 1000)
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    env = parse_logs_notification(msg, received_ms=received_ms)
                    if env is not None:
                        yield env
        except asyncio.CancelledError:
            raise
        except Exception:
            if stop_event is not None and stop_event.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.8, 10.0)
