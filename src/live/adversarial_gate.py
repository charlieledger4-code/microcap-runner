"""Transparent post-model adversarial gate for 60-second Pump candidates.

The frozen champion model remains untouched.  This gate consumes only the
first-60-second v2 flow features and produces an independent risk assessment.
It is intentionally rule-based so every veto/review can be explained and
historically/prospectively evaluated without silently retraining the champion.

Version 1 was specified after observing the first production PAPER_PRIORITY
candidate, but before using that candidate's future outcome.  Therefore it must
be evaluated as a new policy epoch; it may not be back-applied to rewrite older
action-time decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import math

ADVERSARIAL_GATE_VERSION = "adv_gate_v1_20260829"

# These thresholds express structural concentration/coordination, not return
# targets.  A veto requires either an extreme single condition or agreement
# between multiple independent critical conditions.
THRESHOLDS = {
    "extreme_top_buyer_share": 0.90,
    "top_buyer_share": 0.75,
    "top3_buyer_share": 0.90,
    "effective_buyers": 2.50,
    "nominal_buyers_for_collapse": 8,
    "roundtrip_wallet_share": 0.70,
    "negative_net_buy_volume_ratio": -0.05,
    "creator_buy_share": 0.50,
    "recent_new_buyers": 1,
    "trade_burst_ratio": 0.50,
    "peak_to_entry_drawdown": -0.40,
    "recent30_return": -0.25,
}


def _f(row: dict[str, Any], key: str) -> float | None:
    try:
        x = float(row.get(key))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class GateAssessment:
    version: str
    status: str
    suggested_decision: str
    risk_score: int
    critical_flags: tuple[str, ...]
    warning_flags: tuple[str, ...]
    missing_fields: tuple[str, ...]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["critical_flags"] = list(self.critical_flags)
        d["warning_flags"] = list(self.warning_flags)
        d["missing_fields"] = list(self.missing_fields)
        return d


def assess_adversarial_risk(
    features: dict[str, Any],
    champion_decision: str,
) -> GateAssessment:
    """Assess manipulation/coordination risk without changing model scores.

    Non-candidates are left alone.  Candidate decisions are mapped to PASS,
    REVIEW or VETO recommendations.  Two independent critical flags are needed
    for a normal veto; >=90% single-buyer dominance is an extreme standalone
    veto.  Missing core risk fields forces REVIEW rather than optimistic pass.
    """
    if champion_decision not in ("PAPER_PRIORITY", "PAPER_CANDIDATE"):
        return GateAssessment(
            ADVERSARIAL_GATE_VERSION, "NOT_APPLICABLE", champion_decision, 0,
            (), (), (), "Champion did not produce a paper candidate."
        )

    required = (
        "top_buyer_volume_share", "top3_buyer_volume_share", "effective_buyers",
        "roundtrip_wallet_share", "net_buy_volume_ratio", "creator_buy_share",
        "recent_new_buyers", "trade_burst_ratio", "peak_to_entry_drawdown",
        "recent30_return", "unique_buyers",
    )
    vals = {k: _f(features, k) for k in required}
    missing = tuple(k for k, v in vals.items() if v is None)
    if missing:
        return GateAssessment(
            ADVERSARIAL_GATE_VERSION, "REVIEW_DATA", "PAPER_REVIEW_DATA", 99,
            (), (), missing,
            "Candidate risk vector is incomplete; fail closed to manual/shadow review."
        )

    t = THRESHOLDS
    critical: list[str] = []
    warnings: list[str] = []

    if vals["top_buyer_volume_share"] >= t["top_buyer_share"]:
        critical.append("single_buyer_dominance")
    if (
        vals["unique_buyers"] >= t["nominal_buyers_for_collapse"]
        and vals["effective_buyers"] < t["effective_buyers"]
    ):
        critical.append("nominal_to_effective_buyer_collapse")
    if (
        vals["top3_buyer_volume_share"] >= t["top3_buyer_share"]
        and vals["effective_buyers"] < 4.0
    ):
        critical.append("top3_cartel_concentration")
    if (
        vals["roundtrip_wallet_share"] >= t["roundtrip_wallet_share"]
        and vals["net_buy_volume_ratio"] <= t["negative_net_buy_volume_ratio"]
    ):
        critical.append("roundtrip_with_net_sell_pressure")
    if vals["creator_buy_share"] >= t["creator_buy_share"]:
        critical.append("creator_dominated_buy_volume")

    if vals["recent_new_buyers"] <= t["recent_new_buyers"] and vals["unique_buyers"] >= 8:
        warnings.append("little_late_independent_buyer_arrival")
    if vals["trade_burst_ratio"] >= t["trade_burst_ratio"]:
        warnings.append("five_second_burst_concentration")
    if vals["peak_to_entry_drawdown"] <= t["peak_to_entry_drawdown"]:
        warnings.append("large_pre_entry_drawdown")
    if vals["recent30_return"] <= t["recent30_return"]:
        warnings.append("negative_recent_price_path")

    extreme = vals["top_buyer_volume_share"] >= t["extreme_top_buyer_share"]
    risk_score = 2 * len(critical) + len(warnings)
    if extreme or len(critical) >= 2:
        status = "VETO"
        suggestion = "PAPER_VETO"
    elif len(critical) == 1 or len(warnings) >= 2:
        status = "REVIEW"
        suggestion = "PAPER_REVIEW"
    else:
        status = "PASS"
        suggestion = champion_decision

    explanation = (
        f"{status}: {len(critical)} critical and {len(warnings)} warning flags; "
        "champion score remains unchanged and this recommendation is tracked separately."
    )
    return GateAssessment(
        ADVERSARIAL_GATE_VERSION, status, suggestion, risk_score,
        tuple(critical), tuple(warnings), (), explanation
    )
