"""Live-only coordination diagnostics from an immutable first-60s trade tape.

These diagnostics are *not* part of the frozen champion and do not alter model
scores.  They are intended for candidate review and future validation.  Every
metric is computed solely from the persisted action-time tape.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any, Iterable
import math

from src.live.feature60 import NON_HUMAN_WALLETS

FORENSICS_VERSION='action_forensics_v1'


def _f(x,default=None):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except (TypeError,ValueError):return default


def summarize_action_tape(trades:Iterable[dict[str,Any]])->dict[str,Any]:
    rows=[]
    for x in trades:
        sec=_f(x.get('seconds_since_launch'))
        user=str(x.get('user_wallet') or '')
        if sec is None or sec<0 or sec>60 or user in NON_HUMAN_WALLETS:continue
        rows.append({**x,'seconds_since_launch':sec,'user_wallet':user,'sol_amount':_f(x.get('sol_amount'),0.0) or 0.0})
    buys=[x for x in rows if bool(x.get('is_buy'))];sells=[x for x in rows if not bool(x.get('is_buy'))]
    buy_wallets={x['user_wallet'] for x in buys};all_wallets={x['user_wallet'] for x in rows}

    sig_users=defaultdict(set)
    for x in rows:
        if x.get('signature'):sig_users[str(x['signature'])].add(x['user_wallet'])
    max_sig=max((len(v) for v in sig_users.values()),default=0)

    second_users=defaultdict(set)
    for x in buys:second_users[int(x['seconds_since_launch'])].add(x['user_wallet'])
    max_second=max((len(v) for v in second_users.values()),default=0)

    # Identical rounded buy size across distinct wallets can be a coordination
    # clue; rounding is deliberately coarse enough to tolerate lamport noise.
    size_users=defaultdict(set)
    for x in buys:
        if x['sol_amount']>0:size_users[round(x['sol_amount'],4)].add(x['user_wallet'])
    max_same_size=max((len(v) for v in size_users.values()),default=0)

    time_size=defaultdict(set)
    for x in buys:
        if x['sol_amount']>0:
            time_size[(int(x['seconds_since_launch']//2),round(x['sol_amount'],4))].add(x['user_wallet'])
    max_cluster=max((len(v) for v in time_size.values()),default=0)

    first_buy={}
    first_sell={}
    for x in buys:first_buy[x['user_wallet']]=min(first_buy.get(x['user_wallet'],1e18),x['seconds_since_launch'])
    for x in sells:first_sell[x['user_wallet']]=min(first_sell.get(x['user_wallet'],1e18),x['seconds_since_launch'])
    roundtrip=[];fast=0
    for w,b in first_buy.items():
        s=first_sell.get(w)
        if s is not None and s>=b:
            d=s-b;roundtrip.append(d)
            if d<=10:fast+=1

    buy_sizes=[x['sol_amount'] for x in buys if x['sol_amount']>0]
    freq=Counter(round(x,4) for x in buy_sizes)
    same_size_trade_share=(max(freq.values())/len(buy_sizes)) if buy_sizes else 0.0

    return {
        'forensics_version':FORENSICS_VERSION,
        'human_trades':len(rows),'unique_human_wallets':len(all_wallets),'unique_buyers':len(buy_wallets),
        'max_distinct_wallets_same_signature':max_sig,
        'max_distinct_buyers_same_second':max_second,
        'same_second_buyer_share':max_second/(len(buy_wallets)+1e-12),
        'max_distinct_buyers_same_rounded_size':max_same_size,
        'same_size_trade_share':same_size_trade_share,
        'max_two_second_same_size_cluster':max_cluster,
        'two_second_same_size_cluster_share':max_cluster/(len(buy_wallets)+1e-12),
        'roundtrip_wallets':len(roundtrip),'fast_roundtrip_wallets_10s':fast,
        'fast_roundtrip_buyer_share':fast/(len(buy_wallets)+1e-12),
        'median_buy_to_sell_seconds':median(roundtrip) if roundtrip else None,
        'median_buy_sol':median(buy_sizes) if buy_sizes else 0.0,
        'guard':'Live action-time diagnostic only; not historically validated and not an operational veto input.',
    }
