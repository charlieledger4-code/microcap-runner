import pytest
from src.models.leakage import assert_admissible_columns, assert_completion_benchmark_columns


def test_future_columns_are_rejected():
    with pytest.raises(ValueError):
        assert_admissible_columns(["holder_count", "max_future_return"])


def test_completion_proxy_columns_are_rejected():
    with pytest.raises(ValueError):
        assert_completion_benchmark_columns(["holder_count", "market_cap"])


def test_legitimate_point_in_time_fields_are_allowed():
    assert_completion_benchmark_columns(["holder_count", "fresh_wallet_rate", "age_seconds"])
