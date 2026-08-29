"""PumpSwap reserve-state paper quote primitives.

Uses effective quote reserves = real quote vault + virtual quote reserves, as
required by Pump's current AMM docs. Sell payout is capped by the real quote vault
for boost-compatible states. Fees are rounded up per component.
"""
from __future__ import annotations

from dataclasses import dataclass,asdict
from typing import Any

from src.ingest.pumpswap_event import PumpSwapPoolEvent,PumpSwapTradeEvent
from src.ingest.pump_trade_event import WSOL_MINT
from src.execution.pump_curve_quote import BPS,ceil_div


@dataclass(frozen=True)
class PumpSwapState:
    pool:str
    base_mint:str
    quote_mint:str
    base_decimals:int
    quote_decimals:int
    base_reserve_raw:int
    real_quote_reserve_raw:int
    virtual_quote_reserve_raw:int
    lp_fee_bps:int
    protocol_fee_bps:int
    creator_fee_bps:int
    cashback_fee_bps:int=0
    observed_timestamp:int|None=None
    source_signature:str|None=None

    @property
    def effective_quote_reserve_raw(self)->int:
        return int(self.real_quote_reserve_raw+self.virtual_quote_reserve_raw)


@dataclass(frozen=True)
class PumpSwapSellQuote:
    base_in_raw:int
    gross_quote_out_raw:int
    net_quote_out_raw:int
    lp_fee_raw:int
    protocol_fee_raw:int
    creator_fee_raw:int
    cashback_fee_raw:int
    total_fee_raw:int
    liquidity_limited:bool
    average_price_quote:float|None
    state_signature:str|None
    def to_dict(self)->dict[str,Any]:return asdict(self)


def state_from_trade(pool:PumpSwapPoolEvent,ev:PumpSwapTradeEvent)->PumpSwapState|None:
    if ev.pool!=pool.pool:return None
    return PumpSwapState(
        pool=pool.pool,base_mint=pool.base_mint,quote_mint=pool.quote_mint,
        base_decimals=pool.base_mint_decimals,quote_decimals=pool.quote_mint_decimals,
        base_reserve_raw=int(ev.pool_base_token_reserves_raw),real_quote_reserve_raw=int(ev.pool_quote_token_reserves_raw),
        virtual_quote_reserve_raw=int(ev.virtual_quote_reserves_raw or 0),lp_fee_bps=int(ev.lp_fee_basis_points or 0),
        protocol_fee_bps=int(ev.protocol_fee_basis_points or 0),creator_fee_bps=int(ev.coin_creator_fee_basis_points or 0),
        cashback_fee_bps=int(ev.cashback_fee_basis_points or 0),
        observed_timestamp=int(ev.source_block_time if ev.source_block_time is not None else ev.timestamp),source_signature=ev.source_signature,
    )


def _fee(amount:int,bps:int)->int:return ceil_div(amount*bps,BPS) if amount>0 and bps>0 else 0


def quote_sell_base_raw(state:PumpSwapState,base_in_raw:int)->PumpSwapSellQuote:
    x=int(base_in_raw)
    if x<=0:raise ValueError('base_in_raw must be positive')
    if state.base_reserve_raw<=0 or state.effective_quote_reserve_raw<=0:raise ValueError('invalid pool reserves')
    theoretical=(x*state.effective_quote_reserve_raw)//(state.base_reserve_raw+x)
    limited=theoretical>state.real_quote_reserve_raw
    gross=min(theoretical,state.real_quote_reserve_raw)
    lp=_fee(gross,state.lp_fee_bps);protocol=_fee(gross,state.protocol_fee_bps);creator=_fee(gross,state.creator_fee_bps);cash=_fee(gross,state.cashback_fee_bps)
    total=min(gross,lp+protocol+creator+cash);net=max(0,gross-total)
    base=x/(10**state.base_decimals);quote=net/(10**state.quote_decimals)
    avg=quote/base if base>0 else None
    return PumpSwapSellQuote(x,gross,net,lp,protocol,creator,cash,total,limited,avg,state.source_signature)


def is_sol_quote(state:PumpSwapState)->bool:return state.quote_mint==WSOL_MINT
