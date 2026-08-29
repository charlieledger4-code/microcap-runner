from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass(frozen=True)
class BasketResult:
    tickets: int
    ticket_gbp: float
    capital_gbp: float
    terminal_gbp: float
    pnl_gbp: float
    return_pct: float
    winners: int
    losers: int


def equal_ticket_basket(realized_net_multiples: Iterable[float], ticket_gbp: float = 1.0) -> dict:
    """Value a pre-registered equal-ticket paper basket from realized net multiples."""
    xs = [max(0.0, float(x)) for x in realized_net_multiples]
    if not xs:
        raise ValueError("at least one ticket is required")
    if ticket_gbp <= 0:
        raise ValueError("ticket_gbp must be positive")
    capital = len(xs) * ticket_gbp
    terminal = sum(xs) * ticket_gbp
    result = BasketResult(
        tickets=len(xs), ticket_gbp=ticket_gbp, capital_gbp=capital,
        terminal_gbp=terminal, pnl_gbp=terminal-capital,
        return_pct=(terminal/capital-1.0)*100.0,
        winners=sum(x > 1 for x in xs), losers=sum(x < 1 for x in xs),
    )
    return asdict(result)


def ladder_realized_multiple(path_high_multiple: float, final_multiple: float = 0.0,
                               ladder=((2.0, 0.20), (5.0, 0.20), (10.0, 0.20), (25.0, 0.20))) -> float:
    """Toy deterministic ladder used only for policy comparison."""
    sold = 0.0
    value = 0.0
    for target, fraction in ladder:
        if fraction < 0 or sold + fraction > 1 + 1e-12:
            raise ValueError("invalid ladder fractions")
        if path_high_multiple >= target:
            sold += fraction
            value += fraction * target
    value += (1.0 - sold) * max(0.0, final_multiple)
    return value
