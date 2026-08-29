from src.live.outcomes import ObservedPoint, outcome_summary, merge_points


def test_outcome_target_before_drawdown_and_max_multiple():
    pts=[ObservedPoint(1100,1.2,'pump','a'),ObservedPoint(1200,5.1,'pump','b'),ObservedPoint(1300,.4,'pump','c')]
    r=outcome_summary(pts,1000,1.0,targets=(2,5,10),drawdown=.5)
    assert r['targets']['2']['hit'] is True
    assert r['targets']['5']['hit'] is True
    assert r['targets']['10']['hit'] is False and r['targets']['10']['event']=='drawdown'
    assert r['max_observed_multiple']==5.1


def test_merge_points_orders_cross_venue_path():
    a=[ObservedPoint(1200,2,'pumpswap','x')]
    b=[ObservedPoint(1100,1.5,'pump','y')]
    assert [x.venue for x in merge_points(a,b)]==['pump','pumpswap']
