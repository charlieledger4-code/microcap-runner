"""Construct the frozen free-live 60-second feature vector.

The formulas intentionally mirror ``github_phase2_stress60_lowmem.make_panel``.
Only information observed at or before decision_age_s is admitted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
import math

from src.ingest.pump_trade_event import PumpTradeEvent, SYSTEM_PROGRAM

LIVECORE_FEATURES = [
    'human_trades','buys','sells','unique_wallets','unique_buyers','unique_sellers',
    'valid_volume_sol','buy_volume_sol','sell_volume_sol','buy_sell_volume_ratio',
    'recent_trades','prior_trades','recent_buyers','prior_buyers',
    'recent_volume_sol','prior_volume_sol','tx_acceleration','buyer_acceleration',
    'volume_acceleration','last_trade_gap_sec',
    'first_price_sol','entry_price_sol','price_return','price_range_ratio','market_cap_sol',
    'creator_trades','creator_buy_volume_sol','initial_buy_sol','is_mayhem_mode',
    'hour_utc','dow_utc',
]


def _f(x, default=None):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except (TypeError,ValueError):
        return default


def event_to_trade(ev: PumpTradeEvent, launch_unix_s: float) -> dict[str, Any] | None:
    if not ev.is_sol_quote:
        return None
    sec=(ev.source_block_time if ev.source_block_time is not None else ev.timestamp)-launch_unix_s
    return {
        'signature':ev.source_signature,
        'user_wallet':ev.user,
        'is_buy':bool(ev.is_buy),
        'sol_amount':ev.sol_amount,
        'token_amount':ev.token_amount,
        'price_sol':ev.price_sol,
        'market_cap_sol':ev.market_cap_sol,
        'seconds_since_launch':float(sec),
        'ix_name':ev.ix_name,
    }


def launch_initial_trade(launch: dict[str, Any]) -> dict[str, Any] | None:
    sol=_f(launch.get('solAmount'),0.0); tok=_f(launch.get('initialBuy'),0.0)
    if not sol or not tok:
        return None
    mc=_f(launch.get('marketCapSol'))
    price=(mc/1_000_000_000) if mc and mc>0 else None
    return {
        'signature':launch.get('signature'), 'user_wallet':launch.get('traderPublicKey'),
        'is_buy':True, 'sol_amount':sol, 'token_amount':tok, 'price_sol':price,
        'market_cap_sol':mc, 'seconds_since_launch':0.0, 'ix_name':'create_initial_buy',
    }


def normalize_trades(launch: dict[str, Any], events: Iterable[PumpTradeEvent], launch_unix_s: float) -> list[dict[str, Any]]:
    out=[]
    for ev in events:
        if ev.mint != launch.get('mint'): continue
        t=event_to_trade(ev,launch_unix_s)
        if t is not None: out.append(t)
    # Creation can include a TradeEvent. Only synthesize the free launch-feed
    # initial buy if that signature was not decoded, avoiding double counting.
    sig=launch.get('signature')
    if not any(t.get('signature')==sig for t in out):
        t=launch_initial_trade(launch)
        if t is not None: out.append(t)
    # Defensive event deduplication.
    dedup={}
    for t in out:
        key=(t.get('signature'),t.get('user_wallet'),t.get('is_buy'),round(_f(t.get('sol_amount'),0.0),12),round(_f(t.get('token_amount'),0.0),6))
        dedup[key]=t
    return sorted(dedup.values(),key=lambda x:x['seconds_since_launch'])


def build_livecore_features(launch: dict[str, Any], trades: Iterable[dict[str, Any]], *, decision_age_s: float=60.0, launch_unix_s: float | None=None) -> dict[str, float | int | None]:
    """Return the exact live-core feature row for one launch.

    Trades after ``decision_age_s`` are discarded even if supplied by the caller.
    This guard is intentionally inside the feature builder to prevent accidental
    future leakage from a larger transaction fetch.
    """
    rows=[]
    for x in trades:
        sec=_f(x.get('seconds_since_launch'))
        if sec is None or sec < 0 or sec > decision_age_s: continue
        user=str(x.get('user_wallet') or '')
        human=user != SYSTEM_PROGRAM
        sol=_f(x.get('sol_amount'),0.0) or 0.0; tok=_f(x.get('token_amount'),0.0) or 0.0; p=_f(x.get('price_sol'))
        valid=bool(human and sol>0 and tok>0 and p and p>0 and .01 <= sol/(tok*p) <= 100)
        rows.append({**x,'seconds_since_launch':sec,'user_wallet':user,'human':human,'sol_amount':sol,'token_amount':tok,'price_sol':p,'valid_sol':valid})
    creator=str(launch.get('traderPublicKey') or launch.get('creator') or '')
    human=[x for x in rows if x['human']]
    buys=[x for x in human if bool(x.get('is_buy'))]; sells=[x for x in human if not bool(x.get('is_buy'))]
    valid=[x for x in human if x['valid_sol']]; vb=[x for x in valid if bool(x.get('is_buy'))]; vs=[x for x in valid if not bool(x.get('is_buy'))]
    recent=[x for x in human if x['seconds_since_launch']>30]; prior=[x for x in human if x['seconds_since_launch']<=30]
    recent_b=[x for x in recent if bool(x.get('is_buy'))]; prior_b=[x for x in prior if bool(x.get('is_buy'))]
    recent_v=[x for x in recent if x['valid_sol']]; prior_v=[x for x in prior if x['valid_sol']]
    prices=[x for x in rows if x['price_sol'] and x['price_sol']>0]
    mc_rows=[x for x in rows if _f(x.get('market_cap_sol')) and _f(x.get('market_cap_sol'))>0]
    def vol(xs): return sum(x['sol_amount'] for x in xs)
    first=prices[0]['price_sol'] if prices else None; entry=prices[-1]['price_sol'] if prices else None
    pmin=min((x['price_sol'] for x in prices),default=None); pmax=max((x['price_sol'] for x in prices),default=None)
    last=max((x['seconds_since_launch'] for x in human),default=None)
    recent_volume=vol(recent_v); prior_volume=vol(prior_v)
    dt=datetime.fromtimestamp(launch_unix_s if launch_unix_s is not None else datetime.now(tz=timezone.utc).timestamp(),tz=timezone.utc)
    row={
        'human_trades':len(human),'buys':len(buys),'sells':len(sells),
        'unique_wallets':len({x['user_wallet'] for x in human}),
        'unique_buyers':len({x['user_wallet'] for x in buys}),'unique_sellers':len({x['user_wallet'] for x in sells}),
        'valid_volume_sol':vol(valid),'buy_volume_sol':vol(vb),'sell_volume_sol':vol(vs),
        'recent_trades':len(recent),'prior_trades':len(prior),
        'recent_buyers':len({x['user_wallet'] for x in recent_b}),'prior_buyers':len({x['user_wallet'] for x in prior_b}),
        'recent_volume_sol':recent_volume,'prior_volume_sol':prior_volume,
        'first_price_sol':first,'entry_price_sol':entry,
        'market_cap_sol':_f(mc_rows[-1].get('market_cap_sol')) if mc_rows else _f(launch.get('marketCapSol')),
        'last_trade_gap_sec':decision_age_s-last if last is not None else None,
        'creator_trades':sum(1 for x in human if x['user_wallet']==creator),
        'creator_buy_volume_sol':sum(x['sol_amount'] for x in vb if x['user_wallet']==creator),
        'initial_buy_sol':_f(launch.get('solAmount'),0.0) or 0.0,
        'is_mayhem_mode':int(bool(launch.get('is_mayhem_mode',False))),
        'hour_utc':dt.hour,'dow_utc':dt.weekday(),
    }
    row['buy_sell_volume_ratio']=row['buy_volume_sol']/(row['sell_volume_sol']+.01)
    row['tx_acceleration']=(row['recent_trades']-row['prior_trades'])/(row['prior_trades']+1.0)
    row['buyer_acceleration']=(row['recent_buyers']-row['prior_buyers'])/(row['prior_buyers']+1.0)
    row['volume_acceleration']=(recent_volume-prior_volume)/(prior_volume+.01)
    row['price_return']=entry/first-1 if entry is not None and first else None
    row['price_range_ratio']=pmax/pmin if pmax is not None and pmin else None
    return {k:row.get(k) for k in LIVECORE_FEATURES}


def feature_coverage(row: dict[str, Any]) -> dict[str, Any]:
    missing=[k for k in LIVECORE_FEATURES if row.get(k) is None or (isinstance(row.get(k),float) and not math.isfinite(row[k]))]
    return {'present':len(LIVECORE_FEATURES)-len(missing),'total':len(LIVECORE_FEATURES),'fraction':(len(LIVECORE_FEATURES)-len(missing))/len(LIVECORE_FEATURES),'missing':missing}
