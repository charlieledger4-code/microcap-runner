"""Chain-native paper outcome tracking across Pump and PumpSwap.

This layer records observable price paths and first-passage outcomes. It does not
claim a fill merely because a reserve price touched a level; executable-price
simulation is a separate layer and can be attached through PricePoint.executable_price.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Any

from src.labels.path_labels import PricePoint, first_passage
from src.ingest.pump_trade_event import PumpTradeEvent, SYSTEM_PROGRAM, WSOL_MINT
from src.ingest.pumpswap_event import PumpSwapPoolEvent, PumpSwapTradeEvent, extract_pumpswap_events_from_transaction


@dataclass
class ObservedPoint:
    t_ms: int
    price_sol: float
    venue: str
    signature: str | None
    side: str | None = None
    executable_price_sol: float | None = None

    def label_point(self) -> PricePoint:
        return PricePoint(self.t_ms,self.price_sol,self.executable_price_sol)


def _pump_price(ev: PumpTradeEvent) -> float | None:
    if ev.quote_mint not in (None,SYSTEM_PROGRAM,WSOL_MINT) or ev.virtual_token_reserves_raw<=0:return None
    q=ev.virtual_quote_reserves_raw or ev.virtual_sol_reserves_raw
    if q<=0:return None
    return (q/1e9)/(ev.virtual_token_reserves_raw/1e6)


def pump_points(events: Iterable[PumpTradeEvent], mint: str) -> list[ObservedPoint]:
    out=[]
    for ev in events:
        if ev.mint!=mint:continue
        p=_pump_price(ev)
        t=(ev.source_block_time if ev.source_block_time is not None else ev.timestamp)
        if p and t is not None:out.append(ObservedPoint(int(t*1000),p,'pump',ev.source_signature,'buy' if ev.is_buy else 'sell'))
    return sorted(out,key=lambda x:x.t_ms)


def migration_pool_from_transaction(tx: dict[str,Any], mint: str, signature: str | None=None) -> PumpSwapPoolEvent | None:
    events=extract_pumpswap_events_from_transaction(tx,signature)
    pools=[e for e in events if isinstance(e,PumpSwapPoolEvent) and e.base_mint==mint]
    return pools[0] if pools else None


def pumpswap_points(events: Iterable[PumpSwapTradeEvent], pool: PumpSwapPoolEvent) -> list[ObservedPoint]:
    if pool.quote_mint!=WSOL_MINT:return []
    out=[]
    for ev in events:
        if ev.pool!=pool.pool:continue
        p=ev.reserve_price_quote(pool)
        t=(ev.source_block_time if ev.source_block_time is not None else ev.timestamp)
        if p and t is not None:out.append(ObservedPoint(int(t*1000),p,'pumpswap',ev.source_signature,ev.side))
    return sorted(out,key=lambda x:x.t_ms)


def merge_points(*groups: Iterable[ObservedPoint]) -> list[ObservedPoint]:
    # Dedup identical signature/venue/state timestamps while keeping deterministic order.
    d={}
    for group in groups:
        for x in group:
            d[(x.venue,x.signature,x.t_ms,x.price_sol)]=x
    return sorted(d.values(),key=lambda x:x.t_ms)


def outcome_summary(points: Iterable[ObservedPoint], entry_ms: int, entry_price_sol: float, *, targets=(2,5,10,25,50,100), drawdown=.5) -> dict[str,Any]:
    pts=sorted((x for x in points if x.t_ms>entry_ms and x.price_sol>0),key=lambda x:x.t_ms)
    labels=[x.label_point() for x in pts]
    multiples=[x.price_sol/entry_price_sol for x in pts]
    result={
        'entry_ms':entry_ms,'entry_price_sol':entry_price_sol,'future_points':len(pts),
        'last_observed_ms':pts[-1].t_ms if pts else None,
        'max_observed_multiple':max(multiples) if multiples else None,
        'terminal_observed_multiple':multiples[-1] if multiples else None,
        'targets':{},
        'guard':'Observed reserve-price path. A target hit is not an executable fill unless executable_price_sol is populated by the execution simulator.',
    }
    for target in targets:
        result['targets'][str(target)]=first_passage(labels,entry_ms,entry_price_sol,float(target),drawdown)
    return result
