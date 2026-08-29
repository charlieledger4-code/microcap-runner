from __future__ import annotations


def beta_binomial_mean(successes: int, trials: int, alpha: float = 1.0, beta: float = 20.0) -> float:
    """Bayesian shrinkage for rare-hit wallet skill."""
    if successes < 0 or trials < successes:
        raise ValueError("invalid counts")
    return (successes + alpha) / (trials + alpha + beta)


def effective_count(weights: list[float]) -> float:
    """Inverse Herfindahl effective number of economic actors."""
    s = sum(max(0.0,w) for w in weights)
    if s <= 0: return 0.0
    shares = [max(0.0,w)/s for w in weights]
    hhi = sum(x*x for x in shares)
    return 1.0/hhi if hhi else 0.0


def gini(values: list[float]) -> float:
    xs = sorted(max(0.0, x) for x in values)
    n = len(xs); total = sum(xs)
    if n == 0 or total == 0: return 0.0
    return (2*sum((i+1)*x for i,x in enumerate(xs))/(n*total)) - (n+1)/n
