"""Integer Pump bonding-curve quote primitives for paper execution.

The math mirrors Pump SDK/reference behavior rather than applying a generic AMM
haircut to chart price. Buy budgets include fees; fees are removed before the
constant-product swap. Sell outputs are computed from the curve and fees are
removed afterwards.

No transaction is signed or submitted by this module.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from src.ingest.pump_trade_event import PumpTradeEvent, SYSTEM_PROGRAM, WSOL_MINT

BPS=10_000
LAMPORTS_PER_SOL=1_000_000_000
TOKEN_SCALE=1_000_000

# Current official Pump bonding-curve schedule (pump.fun/docs/fees, updated
# 2026-05-20): protocol 0.95% + creator 0.30% = 1.25% total for SOL/USDC curves.
# Some live TradeEvent variants have surfaced zeroed fee-bps fields. Treating
# those zeros literally understates paper execution cost, so native-curve quote
# states fall back to the documented schedule until the event layout is proven.
CURRENT_PROTOCOL_FEE_BPS=95
CURRENT_CREATOR_FEE_BPS=30
CURRENT_TOTAL_FEE_BPS=125


def ceil_div(a:int,b:int)->int:
    if a<0 or b<=0:raise ValueError('ceil_div expects a>=0,b>0')
    return (a+b-1)//b


@dataclass(frozen=True)
class CurveState:
    virtual_token_reserves_raw:int
    virtual_quote_reserves_raw:int
    real_token_reserves_raw:int
    real_quote_reserves_raw:int
    protocol_fee_bps:int
    creator_fee_bps:int=0
    cashback_fee_bps:int=0
    quote_is_sol:bool=True
    observed_timestamp:int|None=None
    source_signature:str|None=None
    fee_source:str='explicit_state'

    @property
    def total_fee_bps(self)->int:
        # buyback_fee_basis_points in current TradeEvent is a routing/share of a
        # fee component, not another user-level charge; do not add it here.
        return int(self.protocol_fee_bps+self.creator_fee_bps+self.cashback_fee_bps)


@dataclass(frozen=True)
class BuyQuote:
    gross_quote_in_raw:int
    swap_quote_in_raw:int
    tokens_out_raw:int
    total_fee_bps:int
    protocol_fee_bps:int
    creator_fee_bps:int
    cashback_fee_bps:int
    fee_source:str
    implied_fee_raw:int
    average_price_sol:float|None
    price_impact_bps:float|None
    capacity_limited:bool
    state_signature:str|None

    def to_dict(self)->dict[str,Any]:return asdict(self)


@dataclass(frozen=True)
class SellQuote:
    tokens_in_raw:int
    gross_quote_out_raw:int
    net_quote_out_raw:int
    protocol_fee_bps:int
    creator_fee_bps:int
    cashback_fee_bps:int
    fee_source:str
    protocol_fee_raw:int
    creator_fee_raw:int
    cashback_fee_raw:int
    total_fee_raw:int
    average_price_sol:float|None
    price_impact_bps:float|None
    liquidity_limited:bool
    state_signature:str|None

    def to_dict(self)->dict[str,Any]:return asdict(self)


def state_from_trade_event(ev:PumpTradeEvent)->CurveState|None:
    """Use post-trade reserves/rates emitted by Pump as a quote state.

    Zeroed fee-bps fields are not accepted as a zero-fee market. Current Pump
    documentation specifies 1.25% total bonding-curve fees, so for native-SOL
    curve events with all fee fields zero we apply the documented 95/30 bps
    protocol/creator split. Fee provenance is retained on every downstream quote
    so fallback-derived paper fills can be separated from event-derived fills.
    """
    if ev.quote_mint not in (None,SYSTEM_PROGRAM,WSOL_MINT):return None
    quote=ev.virtual_quote_reserves_raw or ev.virtual_sol_reserves_raw
    realq=ev.real_quote_reserves_raw if ev.real_quote_reserves_raw is not None else ev.real_sol_reserves_raw
    if quote<=0 or ev.virtual_token_reserves_raw<=0:return None
    pf=max(0,int(ev.fee_basis_points or 0))
    cf=max(0,int(ev.creator_fee_basis_points or 0))
    cash=max(0,int(ev.cashback_fee_basis_points or 0))
    fee_source='trade_event'
    if pf+cf+cash==0:
        pf=CURRENT_PROTOCOL_FEE_BPS
        cf=CURRENT_CREATOR_FEE_BPS
        fee_source='documented_curve_fallback_2026_05_20'
    return CurveState(
        virtual_token_reserves_raw=int(ev.virtual_token_reserves_raw),
        virtual_quote_reserves_raw=int(quote),
        real_token_reserves_raw=max(0,int(ev.real_token_reserves_raw)),
        real_quote_reserves_raw=max(0,int(realq)),
        protocol_fee_bps=pf,
        creator_fee_bps=cf,
        cashback_fee_bps=cash,
        quote_is_sol=True,
        observed_timestamp=int(ev.source_block_time if ev.source_block_time is not None else ev.timestamp),
        source_signature=ev.source_signature,
        fee_source=fee_source,
    )


def spot_price_sol(state:CurveState)->float|None:
    if not state.quote_is_sol or state.virtual_token_reserves_raw<=0:return None
    return (state.virtual_quote_reserves_raw/LAMPORTS_PER_SOL)/(state.virtual_token_reserves_raw/TOKEN_SCALE)


def quote_buy_by_gross_sol(state:CurveState,gross_sol:float)->BuyQuote:
    gross=int(round(float(gross_sol)*LAMPORTS_PER_SOL))
    return quote_buy_by_gross_quote_raw(state,gross)


def quote_buy_by_gross_quote_raw(state:CurveState,gross_quote_raw:int)->BuyQuote:
    """Quote tokens for a maximum all-in quote budget.

    Pump SDK algebra for a budget inclusive of fees:
      swap_in = ((gross - 1) * 10000) // (10000 + total_fee_bps)
      token_out = swap_in * virtual_tokens // (virtual_quote + swap_in)
    and token output is capped by real reserves.
    """
    gross=int(gross_quote_raw)
    if gross<=1:raise ValueError('gross quote budget must exceed 1 base unit')
    if not state.quote_is_sol:raise ValueError('only native-SOL quote is supported here')
    if state.virtual_quote_reserves_raw<=0 or state.virtual_token_reserves_raw<=0:raise ValueError('invalid curve reserves')
    fee_bps=state.total_fee_bps
    swap=((gross-1)*BPS)//(BPS+fee_bps)
    theoretical=(swap*state.virtual_token_reserves_raw)//(state.virtual_quote_reserves_raw+swap)
    tokens=min(theoretical,state.real_token_reserves_raw)
    limited=tokens<theoretical
    implied=max(0,gross-swap)
    avg=(gross/LAMPORTS_PER_SOL)/(tokens/TOKEN_SCALE) if tokens>0 else None
    spot=spot_price_sol(state)
    impact=((avg/spot)-1)*BPS if avg is not None and spot else None
    return BuyQuote(
        gross,swap,tokens,fee_bps,state.protocol_fee_bps,state.creator_fee_bps,
        state.cashback_fee_bps,state.fee_source,implied,avg,impact,limited,state.source_signature
    )


def _fee(raw:int,bps:int)->int:
    return ceil_div(int(raw)*int(bps),BPS) if raw>0 and bps>0 else 0


def quote_sell_tokens_raw(state:CurveState,tokens_in_raw:int)->SellQuote:
    tokens=int(tokens_in_raw)
    if tokens<=0:raise ValueError('tokens_in_raw must be positive')
    if not state.quote_is_sol:raise ValueError('only native-SOL quote is supported here')
    if state.virtual_quote_reserves_raw<=0 or state.virtual_token_reserves_raw<=0:raise ValueError('invalid curve reserves')
    raw=(tokens*state.virtual_quote_reserves_raw)//(state.virtual_token_reserves_raw+tokens)
    limited=raw>state.real_quote_reserves_raw
    raw=min(raw,state.real_quote_reserves_raw)
    pf=_fee(raw,state.protocol_fee_bps);cf=_fee(raw,state.creator_fee_bps);cash=_fee(raw,state.cashback_fee_bps)
    total=min(raw,pf+cf+cash);net=max(0,raw-total)
    avg=(net/LAMPORTS_PER_SOL)/(tokens/TOKEN_SCALE) if tokens>0 else None
    spot=spot_price_sol(state)
    impact=(1-(avg/spot))*BPS if avg is not None and spot else None
    return SellQuote(
        tokens,raw,net,state.protocol_fee_bps,state.creator_fee_bps,state.cashback_fee_bps,
        state.fee_source,pf,cf,cash,total,avg,impact,limited,state.source_signature
    )


def apply_buy_to_state(state:CurveState,q:BuyQuote)->CurveState:
    """Approximate post-buy curve state for capacity/round-trip research.

    Virtual quote grows by the swap (fee-excluded) amount and virtual/real token
    reserves fall by tokens_out. This is not a transaction emulator; it is a
    deterministic reserve transition for small-ticket paper capacity curves.
    """
    if q.tokens_out_raw>state.real_token_reserves_raw:raise ValueError('quote exceeds real token reserves')
    return CurveState(
        virtual_token_reserves_raw=state.virtual_token_reserves_raw-q.tokens_out_raw,
        virtual_quote_reserves_raw=state.virtual_quote_reserves_raw+q.swap_quote_in_raw,
        real_token_reserves_raw=state.real_token_reserves_raw-q.tokens_out_raw,
        real_quote_reserves_raw=state.real_quote_reserves_raw+q.swap_quote_in_raw,
        protocol_fee_bps=state.protocol_fee_bps,creator_fee_bps=state.creator_fee_bps,
        cashback_fee_bps=state.cashback_fee_bps,quote_is_sol=state.quote_is_sol,
        observed_timestamp=state.observed_timestamp,source_signature=state.source_signature,
        fee_source=state.fee_source,
    )
