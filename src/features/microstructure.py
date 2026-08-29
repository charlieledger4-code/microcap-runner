from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Trade:
    t_ms: int
    wallet: str
    side: str
    quote_usd: float
    price_usd: float | None = None


def _window(trades: list[Trade], cutoff_ms: int, seconds: int) -> list[Trade]:
    lo = cutoff_ms - seconds * 1000
    return [x for x in trades if lo < x.t_ms <= cutoff_ms]


def window_features(trades: list[Trade], cutoff_ms: int, seconds: int) -> dict[str, float]:
    xs = _window(trades, cutoff_ms, seconds)
    buys = [x for x in xs if x.side == "buy"]
    sells = [x for x in xs if x.side == "sell"]
    return {
        f"buys_{seconds}s": len(buys),
        f"sells_{seconds}s": len(sells),
        f"volume_{seconds}s": sum(abs(x.quote_usd) for x in xs),
        f"buy_volume_{seconds}s": sum(abs(x.quote_usd) for x in buys),
        f"sell_volume_{seconds}s": sum(abs(x.quote_usd) for x in sells),
        f"unique_buyers_{seconds}s": len({x.wallet for x in buys if x.wallet}),
        f"unique_sellers_{seconds}s": len({x.wallet for x in sells if x.wallet}),
        f"tx_rate_{seconds}s": len(xs) / seconds,
    }


def acceleration(short_value: float, short_seconds: float, long_value: float, long_seconds: float) -> float:
    return short_value / short_seconds - long_value / long_seconds


def derive_features(trades: list[Trade], cutoff_ms: int) -> dict[str, float]:
    out = {}
    for w in (15, 30, 60, 120, 300, 600):
        out.update(window_features(trades, cutoff_ms, w))
    out["buyer_velocity_60s"] = out["unique_buyers_60s"] / 60.0
    out["buyer_acceleration_60v300"] = acceleration(out["unique_buyers_60s"],60,out["unique_buyers_300s"],300)
    out["volume_velocity_60s"] = out["volume_60s"] / 60.0
    out["volume_acceleration_60v300"] = acceleration(out["volume_60s"],60,out["volume_300s"],300)
    out["tx_acceleration_60v300"] = out["tx_rate_60s"] - out["tx_rate_300s"]
    out["buy_sell_volume_ratio_60s"] = (out["buy_volume_60s"] + 1e-9) / (out["sell_volume_60s"] + 1e-9)
    return out


def attention_to_repricing(buyer_growth: float, volume_growth: float, abs_price_return: float) -> float:
    return (max(0.0,buyer_growth) + max(0.0,volume_growth)) / (1.0 + abs(abs_price_return))
