"""Versioned Pump/PumpSwap fee math for paper execution.

Pump has announced a dynamic market-cap-tier fee regime effective 2026-09-01
20:00 UTC.  The tier values are deliberately *not* hard-coded here: the live
system should consume a contemporaneous on-chain/SDK fee-config snapshot so a
future tier update cannot silently stale the simulator.

The algorithms below mirror Pump's published SDK/reference logic:
- bonding-curve market cap = virtual_quote_reserves * mint_supply / virtual_token_reserves
- canonical PumpSwap market cap = quote_reserve * base_supply / base_reserve
- choose first tier below first threshold, otherwise highest threshold <= market cap.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable

DYNAMIC_FEE_ACTIVATION = datetime(2026, 9, 1, 20, 0, 0, tzinfo=timezone.utc)
LEGACY_PUMP_TOTAL_FEE_BPS = 125.0


class DynamicFeeConfigRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class FeesBps:
    protocol_fee_bps: float
    creator_fee_bps: float
    lp_fee_bps: float = 0.0

    @property
    def total_bps(self) -> float:
        return float(self.protocol_fee_bps + self.creator_fee_bps + self.lp_fee_bps)

    def to_dict(self) -> dict:
        return {**asdict(self), "total_bps": self.total_bps}


@dataclass(frozen=True)
class FeeTier:
    market_cap_lamports_threshold: int
    fees: FeesBps


def _positive_int(x: int, name: str) -> int:
    x = int(x)
    if x <= 0:
        raise ValueError(f"{name} must be positive")
    return x


def bonding_curve_market_cap_lamports(
    *, mint_supply_raw: int, virtual_sol_reserves_raw: int, virtual_token_reserves_raw: int
) -> int:
    supply = _positive_int(mint_supply_raw, "mint_supply_raw")
    quote = _positive_int(virtual_sol_reserves_raw, "virtual_sol_reserves_raw")
    base = _positive_int(virtual_token_reserves_raw, "virtual_token_reserves_raw")
    return quote * supply // base


def pumpswap_market_cap_lamports(
    *, base_supply_raw: int, base_reserve_raw: int, quote_reserve_raw: int
) -> int:
    supply = _positive_int(base_supply_raw, "base_supply_raw")
    base = _positive_int(base_reserve_raw, "base_reserve_raw")
    quote = _positive_int(quote_reserve_raw, "quote_reserve_raw")
    return quote * supply // base


def calculate_fee_tier(tiers: Iterable[FeeTier], market_cap_lamports: int) -> FeesBps:
    rows = sorted(list(tiers), key=lambda x: x.market_cap_lamports_threshold)
    if not rows:
        raise DynamicFeeConfigRequired("fee tier list is empty")
    mc = int(market_cap_lamports)
    if mc < rows[0].market_cap_lamports_threshold:
        return rows[0].fees
    for tier in reversed(rows):
        if mc >= tier.market_cap_lamports_threshold:
            return tier.fees
    return rows[0].fees


def effective_curve_fees(
    *,
    observed_at: datetime,
    market_cap_lamports: int | None = None,
    fee_tiers: Iterable[FeeTier] | None = None,
    legacy_total_fee_bps: float = LEGACY_PUMP_TOTAL_FEE_BPS,
) -> FeesBps:
    """Return fee assumptions valid at ``observed_at``.

    Before activation the public legacy total is returned as a single protocol
    bucket for execution accounting. After activation, absence of a tier snapshot
    is a hard error: callers may not silently carry the 1.25% flat fee forward.
    """
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    at = observed_at.astimezone(timezone.utc)
    if at < DYNAMIC_FEE_ACTIVATION:
        return FeesBps(protocol_fee_bps=float(legacy_total_fee_bps), creator_fee_bps=0.0, lp_fee_bps=0.0)
    if market_cap_lamports is None or fee_tiers is None:
        raise DynamicFeeConfigRequired(
            "dynamic Pump fees active: contemporaneous market cap and fee tiers are required"
        )
    return calculate_fee_tier(fee_tiers, int(market_cap_lamports))
