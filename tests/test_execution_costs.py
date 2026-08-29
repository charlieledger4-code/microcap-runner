from src.execution.costs import (
    RoundTripAssumptions,
    expected_round_trip,
    solana_tx_fee_lamports,
)


def test_solana_base_and_priority_fee_formula():
    # 1 signature = 5,000 lamports. 300k CUs * 10 micro-lamports/CU = 3 lamports.
    assert solana_tx_fee_lamports(
        signatures=1,
        compute_unit_limit=300_000,
        compute_unit_price_micro_lamports=10,
    ) == 5_003


def test_default_pump_round_trip_has_two_fee_haircuts():
    r = expected_round_trip(1.0, 1.0)
    expected = (1 - 0.0125) ** 2
    assert abs(r.expected_net_multiple - expected) < 1e-12


def test_fixed_costs_matter_more_for_tiny_tickets():
    a = RoundTripAssumptions(entry_network_cost_sol=.00001, exit_network_cost_sol=.00001)
    small = expected_round_trip(.001, 2.0, a).expected_net_multiple
    large = expected_round_trip(1.0, 2.0, a).expected_net_multiple
    assert small < large
