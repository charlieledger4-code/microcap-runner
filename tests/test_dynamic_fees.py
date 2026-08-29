from datetime import datetime, timezone
import pytest

from src.execution.dynamic_fees import (
    DYNAMIC_FEE_ACTIVATION, DynamicFeeConfigRequired, FeeTier, FeesBps,
    bonding_curve_market_cap_lamports, pumpswap_market_cap_lamports,
    calculate_fee_tier, effective_curve_fees,
)


def test_market_cap_formulas_use_integer_protocol_math():
    assert bonding_curve_market_cap_lamports(
        mint_supply_raw=1_000_000_000_000_000,
        virtual_sol_reserves_raw=30_000_000_000,
        virtual_token_reserves_raw=1_000_000_000_000_000,
    ) == 30_000_000_000
    assert pumpswap_market_cap_lamports(
        base_supply_raw=1_000_000_000_000_000,
        base_reserve_raw=500_000_000_000_000,
        quote_reserve_raw=20_000_000_000,
    ) == 40_000_000_000


def test_fee_tier_matches_published_highest_threshold_rule():
    tiers=[
        FeeTier(10,FeesBps(100,20,0)),
        FeeTier(100,FeesBps(80,20,10)),
        FeeTier(1000,FeesBps(50,10,20)),
    ]
    assert calculate_fee_tier(tiers,1).total_bps==120
    assert calculate_fee_tier(tiers,99).total_bps==120
    assert calculate_fee_tier(tiers,100).total_bps==110
    assert calculate_fee_tier(tiers,5000).total_bps==80


def test_post_activation_fee_config_is_fail_closed():
    before=DYNAMIC_FEE_ACTIVATION.replace(hour=19)
    assert effective_curve_fees(observed_at=before).total_bps==125
    with pytest.raises(DynamicFeeConfigRequired):
        effective_curve_fees(observed_at=DYNAMIC_FEE_ACTIVATION)
    tiers=[FeeTier(0,FeesBps(90,10,0))]
    got=effective_curve_fees(observed_at=DYNAMIC_FEE_ACTIVATION,market_cap_lamports=1,fee_tiers=tiers)
    assert got.total_bps==100
