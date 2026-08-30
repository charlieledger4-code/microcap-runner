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
