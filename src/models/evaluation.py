from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable
import numpy as np


@dataclass(frozen=True)
class RankingMetric:
    fraction: float
    selected_n: int
    base_rate: float
    selected_rate: float
    enrichment: float | None
    extreme_tail_recall: float


def ranking_metrics(y_true: Iterable[int | bool], scores: Iterable[float], fractions=(0.001, 0.005, 0.01, 0.05)) -> list[dict]:
    """Precision/lift/recall in the top-ranked tail."""
    y = np.asarray(list(y_true), dtype=int)
    p = np.asarray(list(scores), dtype=float)
    if y.size == 0 or y.size != p.size:
        raise ValueError("y_true and scores must be equal-length and non-empty")
    if not np.all(np.isfinite(p)):
        raise ValueError("scores must be finite")
    order = np.argsort(p)[::-1]
    base = float(y.mean())
    positives = int(y.sum())
    out: list[dict] = []
    for frac in fractions:
        if not 0 < frac <= 1:
            raise ValueError("fractions must be in (0, 1]")
        k = max(1, int(np.ceil(y.size * frac)))
        chosen = y[order[:k]]
        rate = float(chosen.mean())
        recall = float(chosen.sum() / positives) if positives else 0.0
        out.append(asdict(RankingMetric(
            fraction=float(frac), selected_n=k, base_rate=base,
            selected_rate=rate, enrichment=(rate/base if base else None),
            extreme_tail_recall=recall,
        )))
    return out


def random_precision_interval(y_true: Iterable[int | bool], k: int, draws: int = 5000, seed: int = 7) -> dict:
    """Monte-Carlo matched-random benchmark for precision@k."""
    y = np.asarray(list(y_true), dtype=int)
    if not 1 <= k <= len(y):
        raise ValueError("k out of bounds")
    rng = np.random.default_rng(seed)
    rates = np.empty(draws, dtype=float)
    for i in range(draws):
        idx = rng.choice(len(y), size=k, replace=False)
        rates[i] = y[idx].mean()
    return {
        "mean": float(rates.mean()),
        "p05": float(np.quantile(rates, 0.05)),
        "p50": float(np.quantile(rates, 0.50)),
        "p95": float(np.quantile(rates, 0.95)),
        "draws": int(draws),
    }
