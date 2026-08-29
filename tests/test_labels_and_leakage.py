import pytest
from src.labels.path_labels import PricePoint, first_passage
from src.models.leakage import assert_admissible_columns, assert_tau_before_decision


def test_target_before_drawdown():
    pts=[PricePoint(101,1.2),PricePoint(102,2.1),PricePoint(103,0.4)]
    assert first_passage(pts,100,1,2,0.5)["hit"] is True


def test_drawdown_before_target():
    pts=[PricePoint(101,0.49),PricePoint(102,10)]
    assert first_passage(pts,100,1,10,0.5)["event"] == "drawdown"


def test_leakage_guard():
    with pytest.raises(ValueError): assert_admissible_columns(["holder_count","future_10x"])
    with pytest.raises(ValueError): assert_tau_before_decision(100,{"social":101})
