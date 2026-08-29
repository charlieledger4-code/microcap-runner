from src.features.microstructure import Trade, derive_features
from src.features.wallets import beta_binomial_mean, effective_count, gini


def test_acceleration_positive_for_recent_burst():
    cutoff=600_000
    trades=[]
    for i in range(10): trades.append(Trade(cutoff-250_000+i*1000,f"old{i}","buy",10))
    for i in range(20): trades.append(Trade(cutoff-50_000+i*1000,f"new{i}","buy",10))
    f=derive_features(trades,cutoff)
    assert f["buyer_acceleration_60v300"] > 0


def test_wallet_metrics():
    assert 0 < beta_binomial_mean(2,2) < 1
    assert abs(effective_count([1,1,1,1])-4) < 1e-9
    assert gini([1,1,1]) == 0
