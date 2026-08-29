from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ConstantProductPool:
    base_reserve: float
    quote_reserve: float
    fee_bps: float = 125.0

    def __post_init__(self):
        if self.base_reserve <= 0 or self.quote_reserve <= 0:
            raise ValueError("reserves must be positive")
        if not 0 <= self.fee_bps < 10_000:
            raise ValueError("fee_bps out of range")

    def buy_base(self, quote_in: float) -> tuple[float, float]:
        """Return (base_out, average quote/base execution price)."""
        if quote_in <= 0:
            raise ValueError("quote_in must be positive")
        q = quote_in * (1 - self.fee_bps/10_000)
        k = self.base_reserve * self.quote_reserve
        new_q = self.quote_reserve + q
        new_b = k / new_q
        out = self.base_reserve - new_b
        return out, quote_in/out if out > 0 else math.inf

    def sell_base(self, base_in: float) -> tuple[float, float]:
        """Return (quote_out, average quote/base execution price)."""
        if base_in <= 0:
            raise ValueError("base_in must be positive")
        b = base_in * (1 - self.fee_bps/10_000)
        k = self.base_reserve * self.quote_reserve
        new_b = self.base_reserve + b
        new_q = k/new_b
        out = self.quote_reserve - new_q
        return out, out/base_in


def net_multiple(entry_cost: float, exit_value: float, fixed_costs: float = 0.0) -> float:
    if entry_cost <= 0:
        raise ValueError("entry_cost must be positive")
    if fixed_costs < 0:
        raise ValueError("fixed_costs must be non-negative")
    return max(0.0, exit_value-fixed_costs)/entry_cost
