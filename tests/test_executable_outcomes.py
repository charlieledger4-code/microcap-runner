from src.live.executable_outcomes import ExecutablePoint,summarize_executable_path


def p(t,obs,exe):return ExecutablePoint(t,'pump',str(t),obs,obs,exe,exe,False)


def test_executable_target_can_fail_when_observed_price_touches():
    pts=[p(1,1.2,1.1),p(2,10.2,8.0),p(3,.4,.35)]
    s=summarize_executable_path(pts,targets=(10,),drawdown=.5)
    assert s['observed_targets']['10']['hit'] is True
    assert s['executable_targets']['10']['hit'] is False
    assert s['executable_targets']['10']['event']=='drawdown'


def test_target_before_drawdown_is_order_sensitive():
    pts=[p(1,2.2,2.05),p(2,.3,.3)]
    s=summarize_executable_path(pts,targets=(2,),drawdown=.5)
    assert s['executable_targets']['2']['hit'] is True
