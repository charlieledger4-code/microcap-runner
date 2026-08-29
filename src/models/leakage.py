from __future__ import annotations

# Globally invalid because they encode the future target/outcome itself.
BANNED_GLOBAL_EXACT = {
    "path_completed", "graduated", "rugged", "rug_detected",
    "max_future_return", "max_executable_future_return",
}
BANNED_GLOBAL_SUBSTRINGS = (
    "future_", "outcome", "label", "target_return", "time_to_",
)

# For the recent point-in-time *completion* benchmark, these can make the task
# tautological or nearly so because they encode bonding-curve progress/proximity.
# They are NOT globally banned for economic future-return models when timestamped.
COMPLETION_PROXY_EXACT = {
    "progress", "first_progress", "max_progress", "max_progress_path",
    "progress_at_first_sighting", "curve_progress", "bonding_curve_progress",
    "y_theta_70",
    "market_cap", "usd_market_cap", "market_cap_sol", "price", "liquidity",
    "vault_implied_volume_sol", "vault",
}


def assert_admissible_columns(columns: list[str]) -> None:
    bad = []
    for c in columns:
        low = c.lower()
        if low in BANNED_GLOBAL_EXACT or any(s in low for s in BANNED_GLOBAL_SUBSTRINGS):
            bad.append(c)
    if bad:
        raise ValueError(f"future/outcome leakage columns detected: {sorted(bad)}")


def assert_completion_benchmark_columns(columns: list[str]) -> None:
    assert_admissible_columns(columns)
    bad = [c for c in columns if c.lower() in COMPLETION_PROXY_EXACT]
    if bad:
        raise ValueError(f"graduation/completion proxy columns detected: {sorted(bad)}")


def assert_tau_before_decision(decision_ms: float, tau_by_field: dict[str, float | None]) -> None:
    late = {k:v for k,v in tau_by_field.items() if v is not None and v > decision_ms}
    if late:
        raise ValueError(f"features unavailable at decision time: {late}")
