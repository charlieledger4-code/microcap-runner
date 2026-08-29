"""Decode current PumpSwap Anchor pool/trade events from raw Solana transactions.

Layouts are taken from pump-fun/pump-public-docs ``idl/pump_amm.json``.
The decoder retains raw amounts and fee fields. Price conversion requires a
CreatePoolEvent (or equivalent pool metadata) so base/quote decimals and mints are
known; it never assumes every PumpSwap pool is SOL quoted.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import base64
from typing import Any

from src.ingest.pump_trade_event import (
    BorshReader, EVENT_IX_TAG_LE, b58decode, _combined_account_keys, _ix_program_id,
    WSOL_MINT,
)

PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
CREATE_POOL_DISCRIMINATOR = bytes([177,49,12,210,160,118,167,116])
BUY_DISCRIMINATOR = bytes([103,244,82,31,44,245,119,119])
SELL_DISCRIMINATOR = bytes([62,47,55,10,165,3,220,42])


def _i128(r: BorshReader) -> int:
    return int.from_bytes(r.take(16), 'little', signed=True)


@dataclass
class PumpSwapPoolEvent:
    timestamp: int
    index: int
    creator: str
    base_mint: str
    quote_mint: str
    base_mint_decimals: int
    quote_mint_decimals: int
    base_amount_in_raw: int
    quote_amount_in_raw: int
    pool_base_amount_raw: int
    pool_quote_amount_raw: int
    minimum_liquidity: int
    initial_liquidity: int
    lp_token_amount_out: int
    pool_bump: int
    pool: str
    lp_mint: str
    user_base_token_account: str
    user_quote_token_account: str
    coin_creator: str
    is_mayhem_mode: bool
    source_signature: str | None = None
    source_slot: int | None = None
    source_block_time: int | None = None

    def to_dict(self): return asdict(self)


@dataclass
class PumpSwapTradeEvent:
    side: str
    timestamp: int
    base_amount_raw: int
    limit_quote_amount_raw: int
    user_base_token_reserves_raw: int
    user_quote_token_reserves_raw: int
    pool_base_token_reserves_raw: int
    pool_quote_token_reserves_raw: int
    quote_amount_raw: int
    lp_fee_basis_points: int
    lp_fee_raw: int
    protocol_fee_basis_points: int
    protocol_fee_raw: int
    quote_amount_fee_adjusted_raw: int
    user_quote_amount_raw: int
    pool: str
    user: str
    user_base_token_account: str
    user_quote_token_account: str
    protocol_fee_recipient: str
    protocol_fee_recipient_token_account: str
    coin_creator: str
    coin_creator_fee_basis_points: int
    coin_creator_fee_raw: int
    cashback_fee_basis_points: int | None = None
    cashback_raw: int | None = None
    buyback_fee_basis_points: int | None = None
    buyback_fee_raw: int | None = None
    virtual_quote_reserves_raw: int | None = None
    can_boost: bool | None = None
    base_supply_raw: int | None = None
    track_volume: bool | None = None
    total_unclaimed_tokens: int | None = None
    total_claimed_tokens: int | None = None
    current_sol_volume_raw: int | None = None
    last_update_timestamp: int | None = None
    min_base_amount_out_raw: int | None = None
    ix_name: str | None = None
    source_signature: str | None = None
    source_slot: int | None = None
    source_block_time: int | None = None

    def is_sol_quote(self, pool_meta: PumpSwapPoolEvent | None) -> bool:
        return bool(pool_meta and pool_meta.quote_mint == WSOL_MINT)

    def base_amount(self, pool_meta: PumpSwapPoolEvent) -> float:
        return self.base_amount_raw / (10 ** pool_meta.base_mint_decimals)

    def quote_amount(self, pool_meta: PumpSwapPoolEvent) -> float:
        return self.quote_amount_raw / (10 ** pool_meta.quote_mint_decimals)

    def execution_price_quote(self, pool_meta: PumpSwapPoolEvent) -> float | None:
        base=self.base_amount(pool_meta); quote=self.quote_amount(pool_meta)
        return quote/base if base > 0 else None

    def reserve_price_quote(self, pool_meta: PumpSwapPoolEvent) -> float | None:
        base=self.pool_base_token_reserves_raw / (10 ** pool_meta.base_mint_decimals)
        qraw=self.pool_quote_token_reserves_raw + (self.virtual_quote_reserves_raw or 0)
        quote=qraw / (10 ** pool_meta.quote_mint_decimals)
        return quote/base if base > 0 and quote >= 0 else None

    def to_dict(self, pool_meta: PumpSwapPoolEvent | None = None) -> dict[str,Any]:
        d=asdict(self)
        if pool_meta:
            d.update({
                'base_mint':pool_meta.base_mint,'quote_mint':pool_meta.quote_mint,
                'base_amount':self.base_amount(pool_meta),'quote_amount':self.quote_amount(pool_meta),
                'execution_price_quote':self.execution_price_quote(pool_meta),
                'reserve_price_quote':self.reserve_price_quote(pool_meta),
                'is_sol_quote':self.is_sol_quote(pool_meta),
            })
        return d


def _pool(r: BorshReader) -> PumpSwapPoolEvent:
    return PumpSwapPoolEvent(
        timestamp=r.i64(), index=r.u16(), creator=r.pubkey(), base_mint=r.pubkey(), quote_mint=r.pubkey(),
        base_mint_decimals=r.u8(), quote_mint_decimals=r.u8(), base_amount_in_raw=r.u64(),
        quote_amount_in_raw=r.u64(), pool_base_amount_raw=r.u64(), pool_quote_amount_raw=r.u64(),
        minimum_liquidity=r.u64(), initial_liquidity=r.u64(), lp_token_amount_out=r.u64(),
        pool_bump=r.u8(), pool=r.pubkey(), lp_mint=r.pubkey(), user_base_token_account=r.pubkey(),
        user_quote_token_account=r.pubkey(), coin_creator=r.pubkey(), is_mayhem_mode=r.boolean(),
    )


def _buy(r: BorshReader) -> PumpSwapTradeEvent:
    ev=PumpSwapTradeEvent(
        side='buy',timestamp=r.i64(),base_amount_raw=r.u64(),limit_quote_amount_raw=r.u64(),
        user_base_token_reserves_raw=r.u64(),user_quote_token_reserves_raw=r.u64(),
        pool_base_token_reserves_raw=r.u64(),pool_quote_token_reserves_raw=r.u64(),quote_amount_raw=r.u64(),
        lp_fee_basis_points=r.u64(),lp_fee_raw=r.u64(),protocol_fee_basis_points=r.u64(),protocol_fee_raw=r.u64(),
        quote_amount_fee_adjusted_raw=r.u64(),user_quote_amount_raw=r.u64(),pool=r.pubkey(),user=r.pubkey(),
        user_base_token_account=r.pubkey(),user_quote_token_account=r.pubkey(),protocol_fee_recipient=r.pubkey(),
        protocol_fee_recipient_token_account=r.pubkey(),coin_creator=r.pubkey(),coin_creator_fee_basis_points=r.u64(),
        coin_creator_fee_raw=r.u64(),
    )
    # BuyEvent has volume tracking before the common modern tail.
    ev.track_volume=r.boolean(); ev.total_unclaimed_tokens=r.u64(); ev.total_claimed_tokens=r.u64()
    ev.current_sol_volume_raw=r.u64(); ev.last_update_timestamp=r.i64(); ev.min_base_amount_out_raw=r.u64(); ev.ix_name=r.string()
    ev.cashback_fee_basis_points=r.u64(); ev.cashback_raw=r.u64(); ev.buyback_fee_basis_points=r.u64(); ev.buyback_fee_raw=r.u64()
    ev.virtual_quote_reserves_raw=_i128(r); ev.can_boost=r.boolean(); ev.base_supply_raw=r.u64()
    return ev


def _sell(r: BorshReader) -> PumpSwapTradeEvent:
    ev=PumpSwapTradeEvent(
        side='sell',timestamp=r.i64(),base_amount_raw=r.u64(),limit_quote_amount_raw=r.u64(),
        user_base_token_reserves_raw=r.u64(),user_quote_token_reserves_raw=r.u64(),
        pool_base_token_reserves_raw=r.u64(),pool_quote_token_reserves_raw=r.u64(),quote_amount_raw=r.u64(),
        lp_fee_basis_points=r.u64(),lp_fee_raw=r.u64(),protocol_fee_basis_points=r.u64(),protocol_fee_raw=r.u64(),
        quote_amount_fee_adjusted_raw=r.u64(),user_quote_amount_raw=r.u64(),pool=r.pubkey(),user=r.pubkey(),
        user_base_token_account=r.pubkey(),user_quote_token_account=r.pubkey(),protocol_fee_recipient=r.pubkey(),
        protocol_fee_recipient_token_account=r.pubkey(),coin_creator=r.pubkey(),coin_creator_fee_basis_points=r.u64(),
        coin_creator_fee_raw=r.u64(),
    )
    ev.cashback_fee_basis_points=r.u64(); ev.cashback_raw=r.u64(); ev.buyback_fee_basis_points=r.u64(); ev.buyback_fee_raw=r.u64()
    ev.virtual_quote_reserves_raw=_i128(r); ev.can_boost=r.boolean(); ev.base_supply_raw=r.u64()
    return ev


def decode_pumpswap_event_bytes(data: bytes) -> PumpSwapPoolEvent | PumpSwapTradeEvent | None:
    if data.startswith(EVENT_IX_TAG_LE): data=data[len(EVENT_IX_TAG_LE):]
    if len(data)<8:return None
    disc=data[:8];r=BorshReader(data[8:])
    try:
        if disc==CREATE_POOL_DISCRIMINATOR:return _pool(r)
        if disc==BUY_DISCRIMINATOR:return _buy(r)
        if disc==SELL_DISCRIMINATOR:return _sell(r)
    except (ValueError,UnicodeDecodeError):
        return None
    return None


def decode_pumpswap_event_b58(data: str):
    try:return decode_pumpswap_event_bytes(b58decode(data))
    except (KeyError,ValueError):return None


def extract_pumpswap_events_from_transaction(tx: dict[str,Any], signature: str | None=None):
    meta=tx.get('meta') or {}
    if meta.get('err') is not None:return []
    keys=_combined_account_keys(tx);slot=tx.get('slot');block=tx.get('blockTime');out=[]
    for group in meta.get('innerInstructions') or []:
        for ix in group.get('instructions') or []:
            if _ix_program_id(ix,keys)!=PUMPSWAP_PROGRAM_ID or not ix.get('data'):continue
            ev=decode_pumpswap_event_b58(ix['data'])
            if ev:
                ev.source_signature=signature;ev.source_slot=slot;ev.source_block_time=block;out.append(ev)
    for line in meta.get('logMessages') or []:
        if not isinstance(line,str) or 'Program data: ' not in line:continue
        try:raw=base64.b64decode(line.split('Program data: ',1)[1].strip())
        except Exception:continue
        ev=decode_pumpswap_event_bytes(raw)
        if ev:
            ev.source_signature=signature;ev.source_slot=slot;ev.source_block_time=block;out.append(ev)
    dedup={}
    for ev in out:
        if isinstance(ev,PumpSwapPoolEvent):key=('pool',ev.pool,ev.timestamp)
        else:key=(ev.side,ev.pool,ev.user,ev.timestamp,ev.base_amount_raw,ev.quote_amount_raw)
        dedup[key]=ev
    return list(dedup.values())
