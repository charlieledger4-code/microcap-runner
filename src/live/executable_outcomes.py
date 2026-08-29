"""Executable-value paper paths across Pump and PumpSwap.

Given a simulated entry quote and later protocol reserve states, compute what the
same token amount could be sold for after protocol fees and configured network
fees. This is materially stricter than a reserve-price touch.
"""
from __future__ import annotations

from dataclasses import dataclass,asdict
from typing import Iterable,Any

from src.ingest.pump_trade_event import PumpTradeEvent
from src.ingest.pumpswap_event import PumpSwapPoolEvent,PumpSwapTradeEvent
from src.execution.pump_curve_quote import state_from_trade_event,quote_sell_tokens_raw,spot_price_sol,LAMPORTS_PER_SOL
from src.execution.pumpswap_quote import state_from_trade as pumpswap_state,quote_sell_base_raw,is_sol_quote


@dataclass(frozen=True)
class ExecutablePoint:
    t_ms:int
    venue:str
    signature:str|None
    observed_price_sol:float|None
    observed_price_multiple:float|None
    executable_exit_sol:float|None
    executable_multiple:float|None
    liquidity_limited:bool=False
    def to_dict(self)->dict[str,Any]:return asdict(self)


def _first_passage(points:list[tuple[int,float]],target:float,drawdown:float=.5)->dict[str,Any]:
    for t,m in sorted(points):
        if m<=1-drawdown:return {'hit':False,'event':'drawdown','event_ms':t,'multiple':m}
        if m>=target:return {'hit':True,'event':'target','event_ms':t,'multiple':m}
    return {'hit':False,'event':'censored','event_ms':points[-1][0] if points else None,'multiple':points[-1][1] if points else None}


def pump_exit_points(
    events:Iterable[PumpTradeEvent],*,mint:str,tokens_owned_raw:int,entry_total_outlay_sol:float,
    entry_average_price_sol:float,after_ms:int,exit_network_lamports:int=5000,
)->list[ExecutablePoint]:
    out=[]
    for ev in events:
        if ev.mint!=mint:continue
        t=int((ev.source_block_time if ev.source_block_time is not None else ev.timestamp)*1000)
        if t<=after_ms:continue
        st=state_from_trade_event(ev)
        if st is None:continue
        try:q=quote_sell_tokens_raw(st,tokens_owned_raw)
        except Exception:continue
        spot=spot_price_sol(st);proceeds=max(0.0,(q.net_quote_out_raw-exit_network_lamports)/LAMPORTS_PER_SOL)
        out.append(ExecutablePoint(
            t,'pump',ev.source_signature,spot,(spot/entry_average_price_sol if spot and entry_average_price_sol>0 else None),
            proceeds,(proceeds/entry_total_outlay_sol if entry_total_outlay_sol>0 else None),q.liquidity_limited))
    return sorted(out,key=lambda x:x.t_ms)


def pumpswap_exit_points(
    events:Iterable[PumpSwapTradeEvent],*,pool:PumpSwapPoolEvent,tokens_owned_raw:int,
    entry_total_outlay_sol:float,entry_average_price_sol:float,after_ms:int,exit_network_lamports:int=5000,
)->list[ExecutablePoint]:
    out=[]
    for ev in events:
        t=int((ev.source_block_time if ev.source_block_time is not None else ev.timestamp)*1000)
        if t<=after_ms:continue
        st=pumpswap_state(pool,ev)
        if st is None or not is_sol_quote(st):continue
        try:q=quote_sell_base_raw(st,tokens_owned_raw)
        except Exception:continue
        effective=st.effective_quote_reserve_raw/(10**st.quote_decimals);base=st.base_reserve_raw/(10**st.base_decimals)
        spot=(effective/base) if base>0 else None
        proceeds=max(0.0,(q.net_quote_out_raw-exit_network_lamports)/LAMPORTS_PER_SOL)
        out.append(ExecutablePoint(
            t,'pumpswap',ev.source_signature,spot,(spot/entry_average_price_sol if spot and entry_average_price_sol>0 else None),
            proceeds,(proceeds/entry_total_outlay_sol if entry_total_outlay_sol>0 else None),q.liquidity_limited))
    return sorted(out,key=lambda x:x.t_ms)


def summarize_executable_path(
    points:Iterable[ExecutablePoint],*,targets=(2,5,10,25,50,100),drawdown=.5,
)->dict[str,Any]:
    pts=sorted(points,key=lambda x:x.t_ms)
    obs=[(x.t_ms,x.observed_price_multiple) for x in pts if x.observed_price_multiple is not None]
    exe=[(x.t_ms,x.executable_multiple) for x in pts if x.executable_multiple is not None]
    return {
        'future_points':len(pts),'last_observed_ms':pts[-1].t_ms if pts else None,
        'max_observed_price_multiple':max((m for _,m in obs),default=None),
        'max_executable_multiple':max((m for _,m in exe),default=None),
        'terminal_executable_multiple':exe[-1][1] if exe else None,
        'observed_targets':{str(t):_first_passage(obs,float(t),drawdown) for t in targets},
        'executable_targets':{str(t):_first_passage(exe,float(t),drawdown) for t in targets},
        'liquidity_limited_points':sum(x.liquidity_limited for x in pts),
        'guard':'Executable multiple uses protocol reserve-state sell quotes plus configured network fee. It is still a paper quote, not proof a transaction would have landed at that state.',
    }
