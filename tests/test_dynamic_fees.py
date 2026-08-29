import pytest

from src.execution.dynamic_fees import (
    DynamicFeeConfigRequired, FeeTier, FeesBps,
    bonding_curve_market_cap_lamports, pumpswap_market_cap_lamports,
    calculate_fee_tier, effective_curve_fees, effective_pumpswap_fees,
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


def test_current_curve_fee_is_flat_125_bps():
    got=effective_curve_fees()
    assert got.protocol_fee_bps==95
    assert got.creator_fee_bps==30
    assert got.lp_fee_bps==0
    assert got.total_bps==125


def test_pumpswap_noncanonical_is_flat_and_canonical_is_fail_closed_without_tiers():
    flat=effective_pumpswap_fees(canonical=False)
    assert flat.protocol_fee_bps==5
    assert flat.creator_fee_bps==0
    assert flat.lp_fee_bps==25
    assert flat.total_bps==30
    with pytest.raises(DynamicFeeConfigRequired):
        effective_pumpswap_fees(canonical=True)
    tiers=[FeeTier(0,FeesBps(93,30,2)),FeeTier(420_000_000_000,FeesBps(5,95,20))]
    got=effective_pumpswap_fees(canonical=True,market_cap_lamports=500_000_000_000,fee_tiers=tiers)
    assert got.total_bps==120
