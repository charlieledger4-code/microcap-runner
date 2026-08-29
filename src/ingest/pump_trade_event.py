"""Decode Pump Anchor ``TradeEvent`` CPI instructions from raw Solana transactions.

Truth-layer intent: this module depends only on the public Pump IDL/Borsh layout and
Solana getTransaction JSON. It does not require a paid vendor trade feed.

Current Pump public IDL (TradeEvent) fields are versioned by best-effort optional
tail parsing so older events remain readable.  Raw amounts are retained alongside
normalized SOL/token values; downstream code must not silently score non-SOL quote
mints as if they were SOL.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import base64
import hashlib
import struct
from typing import Any, Iterable

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
WSOL_MINT = "So11111111111111111111111111111111111111112"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
EVENT_IX_TAG_LE = bytes.fromhex("e445a52e51cb9a1d")
TRADE_EVENT_DISCRIMINATOR = hashlib.sha256(b"event:TradeEvent").digest()[:8]
TOKEN_DECIMALS_DEFAULT = 6
SOL_DECIMALS = 9

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}


def b58decode(value: str) -> bytes:
    n = 0
    for c in value:
        n = n * 58 + _B58_IDX[c]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(value) - len(value.lstrip("1"))
    return b"\0" * pad + raw


def b58encode(value: bytes) -> str:
    pad = len(value) - len(value.lstrip(b"\0"))
    n = int.from_bytes(value, "big")
    chars: list[str] = []
    while n:
        n, r = divmod(n, 58)
        chars.append(_B58[r])
    return "1" * pad + ("".join(reversed(chars)) if chars else "")


class BorshReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError(f"truncated borsh payload at {self.pos}, need {n}, remaining {self.remaining}")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int: return self.take(1)[0]
    def boolean(self) -> bool: return bool(self.u8())
    def u16(self) -> int: return struct.unpack("<H", self.take(2))[0]
    def u32(self) -> int: return struct.unpack("<I", self.take(4))[0]
    def u64(self) -> int: return struct.unpack("<Q", self.take(8))[0]
    def i64(self) -> int: return struct.unpack("<q", self.take(8))[0]
    def pubkey(self) -> str: return b58encode(self.take(32))
    def string(self) -> str:
        n = self.u32()
        return self.take(n).decode("utf-8", errors="replace")


@dataclass
class PumpTradeEvent:
    mint: str
    sol_amount_raw: int
    token_amount_raw: int
    is_buy: bool
    user: str
    timestamp: int
    virtual_sol_reserves_raw: int
    virtual_token_reserves_raw: int
    real_sol_reserves_raw: int
    real_token_reserves_raw: int
    fee_recipient: str
    fee_basis_points: int
    fee_raw: int
    creator: str
    creator_fee_basis_points: int
    creator_fee_raw: int
    track_volume: bool
    total_unclaimed_tokens: int
    total_claimed_tokens: int
    current_sol_volume_raw: int
    last_update_timestamp: int
    ix_name: str
    mayhem_mode: bool | None = None
    cashback_fee_basis_points: int | None = None
    cashback_raw: int | None = None
    buyback_fee_basis_points: int | None = None
    buyback_fee_raw: int | None = None
    quote_mint: str | None = None
    quote_amount_raw: int | None = None
    virtual_quote_reserves_raw: int | None = None
    real_quote_reserves_raw: int | None = None
    shareholders: list[dict[str, Any]] | None = None
    source_signature: str | None = None
    source_slot: int | None = None
    source_block_time: int | None = None

    @property
    def token_amount(self) -> float:
        return self.token_amount_raw / 10**TOKEN_DECIMALS_DEFAULT

    @property
    def sol_amount(self) -> float:
        return self.sol_amount_raw / 10**SOL_DECIMALS

    @property
    def is_sol_quote(self) -> bool:
        # Older event versions had no quote_mint tail and were SOL-only.
        return self.quote_mint in (None, WSOL_MINT)

    @property
    def price_sol(self) -> float | None:
        if not self.is_sol_quote or self.virtual_token_reserves_raw <= 0:
            return None
        quote_raw = self.virtual_quote_reserves_raw or self.virtual_sol_reserves_raw
        if quote_raw <= 0:
            return None
        quote_sol = quote_raw / 10**SOL_DECIMALS
        token_units = self.virtual_token_reserves_raw / 10**TOKEN_DECIMALS_DEFAULT
        return quote_sol / token_units if token_units else None

    @property
    def market_cap_sol(self) -> float | None:
        p = self.price_sol
        # Pump's canonical base-token supply is 1B whole tokens for the population
        # used by the frozen historical model.  Noncanonical variants are flagged
        # upstream rather than silently forced through this value.
        return p * 1_000_000_000 if p is not None else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update({"token_amount": self.token_amount, "sol_amount": self.sol_amount,
                  "price_sol": self.price_sol, "market_cap_sol": self.market_cap_sol,
                  "is_sol_quote": self.is_sol_quote})
        return d


def _optional(reader: BorshReader, fn, default=None):
    if reader.remaining <= 0:
        return default
    try:
        return fn()
    except ValueError:
        reader.pos = len(reader.data)
        return default


def decode_trade_event_bytes(data: bytes) -> PumpTradeEvent | None:
    """Decode an Anchor TradeEvent from event-CPI or direct event bytes.

    ``emit_cpi!`` layout is EVENT_IX_TAG_LE + event discriminator + Borsh body.
    ``emit!``/event-coder bytes may start directly with the event discriminator.
    """
    if data.startswith(EVENT_IX_TAG_LE):
        data = data[len(EVENT_IX_TAG_LE):]
    if not data.startswith(TRADE_EVENT_DISCRIMINATOR):
        return None
    r = BorshReader(data[len(TRADE_EVENT_DISCRIMINATOR):])
    try:
        ev = PumpTradeEvent(
            mint=r.pubkey(), sol_amount_raw=r.u64(), token_amount_raw=r.u64(),
            is_buy=r.boolean(), user=r.pubkey(), timestamp=r.i64(),
            virtual_sol_reserves_raw=r.u64(), virtual_token_reserves_raw=r.u64(),
            real_sol_reserves_raw=r.u64(), real_token_reserves_raw=r.u64(),
            fee_recipient=r.pubkey(), fee_basis_points=r.u64(), fee_raw=r.u64(),
            creator=r.pubkey(), creator_fee_basis_points=r.u64(), creator_fee_raw=r.u64(),
            track_volume=r.boolean(), total_unclaimed_tokens=r.u64(),
            total_claimed_tokens=r.u64(), current_sol_volume_raw=r.u64(),
            last_update_timestamp=r.i64(), ix_name=r.string(),
        )
    except ValueError:
        return None

    # Tail fields were appended over protocol upgrades. Parse only if present.
    ev.mayhem_mode = _optional(r, r.boolean)
    ev.cashback_fee_basis_points = _optional(r, r.u64)
    ev.cashback_raw = _optional(r, r.u64)
    ev.buyback_fee_basis_points = _optional(r, r.u64)
    ev.buyback_fee_raw = _optional(r, r.u64)
    if r.remaining >= 4:
        try:
            n = r.u32(); shareholders=[]
            for _ in range(n):
                shareholders.append({"address": r.pubkey(), "share_bps": r.u16()})
            ev.shareholders = shareholders
        except ValueError:
            r.pos = len(r.data)
    ev.quote_mint = _optional(r, r.pubkey)
    ev.quote_amount_raw = _optional(r, r.u64)
    ev.virtual_quote_reserves_raw = _optional(r, r.u64)
    ev.real_quote_reserves_raw = _optional(r, r.u64)
    return ev


def decode_trade_event_b58(data_b58: str) -> PumpTradeEvent | None:
    try:
        return decode_trade_event_bytes(b58decode(data_b58))
    except (KeyError, ValueError):
        return None


def _combined_account_keys(tx: dict[str, Any]) -> list[str]:
    msg = ((tx.get("transaction") or {}).get("message") or {})
    raw = msg.get("accountKeys") or []
    keys=[]
    for k in raw:
        keys.append(k.get("pubkey") if isinstance(k,dict) else k)
    loaded = ((tx.get("meta") or {}).get("loadedAddresses") or {})
    keys.extend(loaded.get("writable") or [])
    keys.extend(loaded.get("readonly") or [])
    return [str(k) for k in keys if k is not None]


def _ix_program_id(ix: dict[str, Any], keys: list[str]) -> str | None:
    if ix.get("programId"):
        return str(ix["programId"])
    i=ix.get("programIdIndex")
    return keys[i] if isinstance(i,int) and 0 <= i < len(keys) else None


def extract_trade_events_from_transaction(tx: dict[str, Any], signature: str | None = None) -> list[PumpTradeEvent]:
    """Extract and deduplicate Pump TradeEvents from getTransaction JSON."""
    meta=tx.get("meta") or {}
    if meta.get("err") is not None:
        return []
    keys=_combined_account_keys(tx)
    slot=tx.get("slot"); block_time=tx.get("blockTime")
    out=[]
    for group in meta.get("innerInstructions") or []:
        for ix in group.get("instructions") or []:
            if _ix_program_id(ix,keys) != PUMP_PROGRAM_ID or not ix.get("data"):
                continue
            ev=decode_trade_event_b58(ix["data"])
            if ev:
                ev.source_signature=signature; ev.source_slot=slot; ev.source_block_time=block_time
                out.append(ev)

    # Fallback for normal emit! log data.  Avoid duplicate events if a provider
    # supplies both representations.
    for line in meta.get("logMessages") or []:
        if not isinstance(line,str) or "Program data: " not in line:
            continue
        try:
            raw=base64.b64decode(line.split("Program data: ",1)[1].strip())
        except Exception:
            continue
        ev=decode_trade_event_bytes(raw)
        if ev:
            ev.source_signature=signature; ev.source_slot=slot; ev.source_block_time=block_time
            out.append(ev)

    dedup={}
    for ev in out:
        key=(ev.mint,ev.user,ev.timestamp,ev.is_buy,ev.token_amount_raw,ev.sol_amount_raw,ev.quote_amount_raw)
        dedup[key]=ev
    return list(dedup.values())
