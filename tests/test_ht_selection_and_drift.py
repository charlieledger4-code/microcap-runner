import scripts.select_ht_audit_set as sel
import scripts.build_live_drift as drift


def test_hash_selection_is_deterministic_and_score_independent():
    rows=[{'mint':f'm{i}','scores':{'10':{'score':i/10}}} for i in range(20)]
    a=[x['mint'] for x in sel.take_hash(rows,5,'run','random_all')]
    b=[x['mint'] for x in sel.take_hash(list(reversed(rows)),5,'run','random_all')]
    assert a==b
    assert len(a)==5 and len(set(a))==5


def test_quantile_helper_is_bounded_and_interpolates():
    x=[0.0,1.0,2.0,3.0,4.0]
    assert drift.q(x,0)==0.0
    assert drift.q(x,1)==4.0
    assert drift.q(x,.5)==2.0
    assert 2.0 < drift.q(x,.75) <= 3.0


def test_zero_trade_price_missingness_is_structural_not_pipeline_drift():
    row={'features':{'human_trades':0}}
    assert drift.missing_kind('first_price_sol',row)=='structural_no_human_trades'
    assert drift.missing_kind('entry_price_sol',row)=='structural_no_human_trades'
    assert drift.missing_kind('last_trade_gap_sec',row)=='structural_no_human_trades'
    assert drift.missing_kind('market_cap_sol',row)=='unexpected'
    assert drift.missing_kind('first_price_sol',{'features':{'human_trades':3}})=='unexpected'
