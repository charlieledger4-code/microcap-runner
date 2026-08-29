from src.live.scoring import score_tier


def test_score_tier_uses_frozen_quantiles_in_descending_order():
    t={'0.95':.5,'0.99':.7,'0.995':.8,'0.999':.9}
    assert score_tier(.49,t)=='BELOW_Q95'
    assert score_tier(.5,t)=='Q95'
    assert score_tier(.75,t)=='Q99'
    assert score_tier(.85,t)=='Q995'
    assert score_tier(.95,t)=='Q999'
