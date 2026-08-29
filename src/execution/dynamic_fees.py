"""Current Pump/PumpSwap fee math for paper execution.

Current public Pump documentation (last updated 2026-05-20) specifies:
- Pump bonding curves: flat 1.25% total fee = 0.95% protocol + 0.30% creator.
- Canonical PumpSwap pools: market-cap-tier fees.
- Non-canonical PumpSwap pools: flat 0.30% total = 0.05% protocol + 0.25% LP.

The market-cap formulas and tier selection below mirror Pump's published SDK/
reference logic. Canonical PumpSwap callers must provide a contemporaneous tier
snapshot rather than silently assuming stale tiers.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable

PUMP_CURVE_PROTOCOL_FEE_BPS = 95.0
PUMP_CURVE_CREATOR_FEE_BPS = 30.0
PUMP_CURVE_TOTAL_FEE_BPS = 125.0
PUMPSWAP_NONCANONICAL_PROTOCOL_FEE_BPS = 5.0
PUMPSWAP_NONCANONICAL_LP_FEE_BPS = 25.0


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


def effective_curve_fees(*, observed_at: datetime | None = None) -> FeesBps:
    """Return the current documented Pump bonding-curve fee split.

    ``observed_at`` is retained for audit metadata/API compatibility; current
    public docs do not describe a future activation switch for the curve fee.
    """
    return FeesBps(
        protocol_fee_bps=PUMP_CURVE_PROTOCOL_FEE_BPS,
        creator_fee_bps=PUMP_CURVE_CREATOR_FEE_BPS,
        lp_fee_bps=0.0,
    )


def effective_pumpswap_fees(
    *,
    canonical: bool,
    market_cap_lamports: int | None = None,
    fee_tiers: Iterable[FeeTier] | None = None,
) -> FeesBps:
    """Return current PumpSwap fees.

    Non-canonical pools use the documented flat 0.30% schedule. Canonical pools
    require the current market cap and contemporaneous fee-tier configuration;
    missing tier data is a hard error so execution estimates cannot silently use
    stale market-cap bands.
    """
    if not canonical:
        return FeesBps(
            protocol_fee_bps=PUMPSWAP_NONCANONICAL_PROTOCOL_FEE_BPS,
            creator_fee_bps=0.0,
            lp_fee_bps=PUMPSWAP_NONCANONICAL_LP_FEE_BPS,
        )
    if market_cap_lamports is None or fee_tiers is None:
        raise DynamicFeeConfigRequired(
            "canonical PumpSwap fees require contemporaneous market cap and fee tiers"
        )
    return calculate_fee_tier(fee_tiers, int(market_cap_lamports))
