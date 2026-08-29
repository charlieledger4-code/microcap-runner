"""Candidate live-core v2 feature contract.

This module extends, but never mutates, the frozen ``live_core_free_v1`` contract.
Every additional field is reconstructable from the same first-60-second on-chain
trade stream.  The additions focus on actor independence, concentration, burst
patterns and path shape so coordinated/bot activity is less likely to masquerade
as organic buyer acceleration.
"""
from __future__ import annotations

from collections import defaultdict
import math
from statistics import median
from typing import Any, Iterable

from .feature60 import LIVECORE_FEATURES, NON_HUMAN_WALLETS, build_livecore_features

LIVECORE_V2_EXTRA_FEATURES = [
    'unique_buyer_trade_ratio',
    'net_buy_volume_ratio',
    'creator_buy_share',
    'buyer_volume_hhi',
    'effective_buyers',
    'buyer_volume_entropy',
    'top_buyer_volume_share',
    'top3_buyer_volume_share',
    'roundtrip_wallet_share',
    'first10_unique_buyers',
    'first10_volume_sol',
    'recent_new_buyers',
    'recent_new_buyer_share',
    'median_buy_sol',
    'max_buy_sol',
    'buy_size_cv',
    'active_5s_bins',
    'max_5s_trade_count',
    'trade_burst_ratio',
    'peak_to_entry_drawdown',
    'first30_return',
    'recent30_return',
    'return_acceleration',
]
LIVECORE_V2_FEATURES = LIVECORE_FEATURES + LIVECORE_V2_EXTRA_FEATURES


def _f(x, default=None):
    try:
        y=float(x)
        return y if math.isfinite(y) else default
    except (TypeError,ValueError):
        return default


def _clean_rows(trades: Iterable[dict[str,Any]], decision_age_s: float) -> list[dict[str,Any]]:
    rows=[]
    for x in trades:
        sec=_f(x.get('seconds_since_launch'))
        if sec is None or sec < 0 or sec > decision_age_s:
            continue
        user=str(x.get('user_wallet') or '')
        human=user not in NON_HUMAN_WALLETS
        sol=_f(x.get('sol_amount'),0.0) or 0.0
        tok=_f(x.get('token_amount'),0.0) or 0.0
        price=_f(x.get('price_sol'))
        valid=bool(human and sol>0 and tok>0 and price and price>0 and .01 <= sol/(tok*price) <= 100)
        rows.append({**x,'seconds_since_launch':sec,'user_wallet':user,'human':human,
                     'sol_amount':sol,'token_amount':tok,'price_sol':price,'valid_sol':valid})
    rows.sort(key=lambda r:r['seconds_since_launch'])
    return rows


def _safe_ratio(a: float, b: float, eps: float=1e-12) -> float:
    return float(a/(b+eps))


def build_livecore_v2_features(
    launch: dict[str,Any], trades: Iterable[dict[str,Any]], *, decision_age_s: float=60.0,
    launch_unix_s: float | None=None,
) -> dict[str,float|int|None]:
    trades=list(trades)
    base=build_livecore_features(launch,trades,decision_age_s=decision_age_s,launch_unix_s=launch_unix_s)
    rows=_clean_rows(trades,decision_age_s)
    human=[x for x in rows if x['human']]
    valid=[x for x in human if x['valid_sol']]
    buys=[x for x in human if bool(x.get('is_buy'))]
    sells=[x for x in human if not bool(x.get('is_buy'))]
    vb=[x for x in valid if bool(x.get('is_buy'))]
    vs=[x for x in valid if not bool(x.get('is_buy'))]
    creator=str(launch.get('traderPublicKey') or launch.get('creator') or '')

    buy_by_wallet=defaultdict(float)
    for x in vb: buy_by_wallet[x['user_wallet']]+=x['sol_amount']
    total_buy=sum(buy_by_wallet.values())
    shares=sorted((v/total_buy for v in buy_by_wallet.values()),reverse=True) if total_buy>0 else []
    hhi=sum(p*p for p in shares)
    effective=(1.0/hhi) if hhi>0 else 0.0
    if len(shares)>1:
        entropy=-sum(p*math.log(p) for p in shares if p>0)/math.log(len(shares))
    else:
        entropy=0.0

    buy_wallets={x['user_wallet'] for x in buys}; sell_wallets={x['user_wallet'] for x in sells}
    prior_buyers={x['user_wallet'] for x in buys if x['seconds_since_launch']<=30}
    recent_buyers={x['user_wallet'] for x in buys if x['seconds_since_launch']>30}
    recent_new=recent_buyers-prior_buyers

    buy_sizes=[x['sol_amount'] for x in vb]
    mean_buy=sum(buy_sizes)/len(buy_sizes) if buy_sizes else 0.0
    variance=sum((x-mean_buy)**2 for x in buy_sizes)/len(buy_sizes) if buy_sizes else 0.0
    cv=math.sqrt(variance)/mean_buy if mean_buy>0 else 0.0

    bins=defaultdict(int)
    for x in human:
        # 0..11 for a 60-second decision horizon; clamp the exact boundary into 11.
        b=min(max(int(x['seconds_since_launch']//5),0),11)
        bins[b]+=1
    active_bins=len(bins); max_bin=max(bins.values(),default=0)

    prices=[x for x in rows if x['price_sol'] and x['price_sol']>0]
    first=prices[0]['price_sol'] if prices else None
    entry=prices[-1]['price_sol'] if prices else None
    p30_rows=[x for x in prices if x['seconds_since_launch']<=30]
    p30=p30_rows[-1]['price_sol'] if p30_rows else first
    peak=max((x['price_sol'] for x in prices),default=None)
    r1=(p30/first-1) if p30 is not None and first else None
    r2=(entry/p30-1) if entry is not None and p30 else None

    buy_vol=sum(x['sol_amount'] for x in vb); sell_vol=sum(x['sol_amount'] for x in vs)
    extra={
        'unique_buyer_trade_ratio':len(buy_wallets)/(len(buys)+1e-12),
        'net_buy_volume_ratio':(buy_vol-sell_vol)/(buy_vol+sell_vol+.01),
        'creator_buy_share':sum(x['sol_amount'] for x in vb if x['user_wallet']==creator)/(buy_vol+.01),
        'buyer_volume_hhi':hhi,
        'effective_buyers':effective,
        'buyer_volume_entropy':entropy,
        'top_buyer_volume_share':shares[0] if shares else 0.0,
        'top3_buyer_volume_share':sum(shares[:3]) if shares else 0.0,
        'roundtrip_wallet_share':len(buy_wallets&sell_wallets)/(len(buy_wallets|sell_wallets)+1e-12),
        'first10_unique_buyers':len({x['user_wallet'] for x in buys if x['seconds_since_launch']<=10}),
        'first10_volume_sol':sum(x['sol_amount'] for x in valid if x['seconds_since_launch']<=10),
        'recent_new_buyers':len(recent_new),
        'recent_new_buyer_share':len(recent_new)/(len(recent_buyers)+1e-12),
        'median_buy_sol':median(buy_sizes) if buy_sizes else 0.0,
        'max_buy_sol':max(buy_sizes,default=0.0),
        'buy_size_cv':cv,
        'active_5s_bins':active_bins,
        'max_5s_trade_count':max_bin,
        'trade_burst_ratio':max_bin/(len(human)+1e-12),
        'peak_to_entry_drawdown':entry/peak-1 if entry is not None and peak else None,
        'first30_return':r1,
        'recent30_return':r2,
        'return_acceleration':r2-r1 if r1 is not None and r2 is not None else None,
    }
    row={**base,**extra}
    return {k:row.get(k) for k in LIVECORE_V2_FEATURES}
