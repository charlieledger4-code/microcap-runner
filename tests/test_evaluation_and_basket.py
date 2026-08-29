from src.models.evaluation import ranking_metrics
from src.execution.paper_basket import equal_ticket_basket, ladder_realized_multiple
from src.labels.economic_labels import ExecutablePoint, target_before_drawdown


def test_enrichment_tail():
    y = [0]*98 + [1,1]
    scores = list(range(98)) + [1000,999]
    m = ranking_metrics(y, scores, fractions=(0.02,))[0]
    assert m["selected_rate"] == 1.0
    assert m["enrichment"] == 50.0
    assert m["extreme_tail_recall"] == 1.0


def test_100_ticket_example():
    r = equal_ticket_basket([0]*97 + [100,100,100], 1.0)
    assert r["capital_gbp"] == 100
    assert r["terminal_gbp"] == 300
    assert r["return_pct"] == 200


def test_economic_first_passage():
    pts = [ExecutablePoint(1, 1.2), ExecutablePoint(2, 2.5), ExecutablePoint(3, 0.2)]
    assert target_before_drawdown(pts, 2.0, 0.5)["hit"] is True


def test_ladder_does_not_count_unreached_targets():
    assert ladder_realized_multiple(6.0, final_multiple=1.0) == 2.0
