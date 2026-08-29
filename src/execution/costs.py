"""Execution-cost primitives for paper research.

The functions here are deterministic accounting tools, not a trading engine.
Defaults reflect Pump's documented 1.25% bonding-curve fee as of 2026-05-20
and Solana's documented 5,000 lamport/signature base fee. Priority fees, Jito
tips, slippage and failure rates must be supplied from contemporaneous data.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math

LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_PUMP_CURVE_FEE_BPS = 125.0
DEFAULT_SOLANA_BASE_LAMPORTS_PER_SIGNATURE = 5_000


def solana_tx_fee_lamports(
    *,
    signatures: int = 1,
    compute_unit_limit: int = 0,
    compute_unit_price_micro_lamports: int = 0,
    jito_tip_lamports: int = 0,
    base_lamports_per_signature: int = DEFAULT_SOLANA_BASE_LAMPORTS_PER_SIGNATURE,
) -> int:
    """Return base + priority + explicit Jito tip in lamports.

    Solana priority fee = ceil(CU_price * CU_limit / 1_000_000) lamports.
    A Jito tip is not a Solana protocol fee, but it is an execution cost and is
    therefore included when provided.
    """
    if min(signatures, compute_unit_limit, compute_unit_price_micro_lamports,
           jito_tip_lamports, base_lamports_per_signature) < 0:
        raise ValueError("fee inputs must be non-negative")
    base = signatures * base_lamports_per_signature
    priority = math.ceil(compute_unit_limit * compute_unit_price_micro_lamports / 1_000_000)
    return int(base + priority + jito_tip_lamports)


def solana_tx_fee_sol(**kwargs) -> float:
    return solana_tx_fee_lamports(**kwargs) / LAMPORTS_PER_SOL


@dataclass(frozen=True)
class RoundTripAssumptions:
    entry_protocol_fee_bps: float = DEFAULT_PUMP_CURVE_FEE_BPS
    exit_protocol_fee_bps: float = DEFAULT_PUMP_CURVE_FEE_BPS
    entry_adverse_bps: float = 0.0
    exit_adverse_bps: float = 0.0
    entry_network_cost_sol: float = 0.0
    exit_network_cost_sol: float = 0.0
    failed_entry_probability: float = 0.0
    failed_exit_probability: float = 0.0

    def validate(self) -> None:
        vals = (
            self.entry_protocol_fee_bps, self.exit_protocol_fee_bps,
            self.entry_adverse_bps, self.exit_adverse_bps,
            self.entry_network_cost_sol, self.exit_network_cost_sol,
        )
        if any(v < 0 for v in vals):
            raise ValueError("cost assumptions must be non-negative")
        for p in (self.failed_entry_probability, self.failed_exit_probability):
            if not 0 <= p <= 1:
                raise ValueError("failure probabilities must be in [0,1]")
        for bps in (self.entry_protocol_fee_bps, self.exit_protocol_fee_bps,
                    self.entry_adverse_bps, self.exit_adverse_bps):
            if bps >= 10_000:
                raise ValueError("basis-point haircut must be < 10000")


@dataclass(frozen=True)
class RoundTripResult:
    initial_sol: float
    gross_price_multiple: float
    expected_terminal_sol: float
    expected_net_multiple: float
    expected_pnl_sol: float
    protocol_and_adverse_entry_factor: float
    protocol_and_adverse_exit_factor: float
    assumptions: dict


def expected_round_trip(
    initial_sol: float,
    gross_price_multiple: float,
    assumptions: RoundTripAssumptions = RoundTripAssumptions(),
) -> RoundTripResult:
    """Expected-value accounting for a buy then sell around a gross price path.

    This deliberately separates percentage haircuts from fixed network costs.
    Failure probabilities are expectation-level penalties, not a substitute for
    event-level Monte Carlo or empirical landing models.
    """
    assumptions.validate()
    if initial_sol <= 0:
        raise ValueError("initial_sol must be positive")
    if gross_price_multiple < 0:
        raise ValueError("gross_price_multiple must be non-negative")

    entry_factor = (1 - assumptions.entry_protocol_fee_bps / 10_000) * (
        1 - assumptions.entry_adverse_bps / 10_000
    )
    exit_factor = (1 - assumptions.exit_protocol_fee_bps / 10_000) * (
        1 - assumptions.exit_adverse_bps / 10_000
    )

    # An attempted entry always incurs its configured network cost. If it lands,
    # the remaining notional obtains exposure after protocol/adverse haircuts.
    after_entry_fixed = max(0.0, initial_sol - assumptions.entry_network_cost_sol)
    landed_entry_value = after_entry_fixed * entry_factor
    expected_exposed = landed_entry_value * (1 - assumptions.failed_entry_probability)

    pre_exit = expected_exposed * gross_price_multiple
    landed_exit_value = pre_exit * exit_factor
    expected_after_exit_landing = landed_exit_value * (1 - assumptions.failed_exit_probability)

    # Exit network cost is only economically relevant when an exit is attempted;
    # this simple EV primitive assumes an attempt whenever entry exposure exists.
    expected_exit_fixed = assumptions.exit_network_cost_sol * (1 - assumptions.failed_entry_probability)
    terminal = max(0.0, expected_after_exit_landing - expected_exit_fixed)
    mult = terminal / initial_sol
    return RoundTripResult(
        initial_sol=float(initial_sol),
        gross_price_multiple=float(gross_price_multiple),
        expected_terminal_sol=float(terminal),
        expected_net_multiple=float(mult),
        expected_pnl_sol=float(terminal - initial_sol),
        protocol_and_adverse_entry_factor=float(entry_factor),
        protocol_and_adverse_exit_factor=float(exit_factor),
        assumptions=asdict(assumptions),
    )
