from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ExecutablePoint:
    timestamp_ms: int
    executable_multiple: float


def target_before_drawdown(points: Iterable[ExecutablePoint], target_multiple: float, drawdown_floor: float) -> dict:
    """First-passage label on an executable-return path, starting from 1.0x.

    drawdown_floor=0.5 means the target must be reached before executable value
    falls to 0.5x. Timestamp ordering is enforced to prevent accidental leakage.
    """
    if target_multiple <= 1:
        raise ValueError("target_multiple must be >1")
    if not 0 < drawdown_floor < 1:
        raise ValueError("drawdown_floor must be in (0,1)")
    pts = list(points)
    if any(b.timestamp_ms < a.timestamp_ms for a, b in zip(pts, pts[1:])):
        raise ValueError("points must be chronological")
    for p in pts:
        if p.executable_multiple <= drawdown_floor:
            return {"hit": False, "event": "drawdown", "event_ms": p.timestamp_ms}
        if p.executable_multiple >= target_multiple:
            return {"hit": True, "event": "target", "event_ms": p.timestamp_ms}
    return {"hit": False, "event": "censored", "event_ms": None}
