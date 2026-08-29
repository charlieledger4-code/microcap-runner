from __future__ import annotations
from dataclasses import dataclass

@dataclass
class PricePoint:
    t_ms: int
    price: float
    executable_price: float | None = None


def first_passage(points: list[PricePoint], entry_ms: int, entry_price: float, upside: float, drawdown: float) -> dict:
    """Label whether upside multiple occurs before adverse drawdown.

    `upside=10` and `drawdown=0.5` => 10x before a 50% loss from entry.
    Strictly uses points after the decision/entry timestamp.
    """
    future = sorted((p for p in points if p.t_ms > entry_ms), key=lambda p:p.t_ms)
    up_px = entry_price * upside
    down_px = entry_price * (1.0-drawdown)
    for p in future:
        px = p.executable_price if p.executable_price is not None else p.price
        if px <= down_px:
            return {"hit": False, "event":"drawdown", "event_ms":p.t_ms}
        if px >= up_px:
            return {"hit": True, "event":"target", "event_ms":p.t_ms}
    return {"hit": False, "event":"censored", "event_ms": future[-1].t_ms if future else None}
