from src.live.adversarial_gate import assess_adversarial_risk, ADVERSARIAL_GATE_VERSION


def base():
    return {
        'unique_buyers': 15,
        'top_buyer_volume_share': .25,
        'top3_buyer_volume_share': .50,
        'effective_buyers': 8.0,
        'roundtrip_wallet_share': .20,
        'net_buy_volume_ratio': .30,
        'creator_buy_share': .05,
        'recent_new_buyers': 5,
        'trade_burst_ratio': .20,
        'peak_to_entry_drawdown': -.10,
        'recent30_return': .20,
    }


def test_non_candidate_is_not_rewritten():
    a=assess_adversarial_risk(base(),'REJECT')
    assert a.status=='NOT_APPLICABLE'
    assert a.suggested_decision=='REJECT'
    assert a.version==ADVERSARIAL_GATE_VERSION


def test_clean_candidate_passes():
    a=assess_adversarial_risk(base(),'PAPER_PRIORITY')
    assert a.status=='PASS'
    assert a.suggested_decision=='PAPER_PRIORITY'
    assert a.risk_score==0


def test_netaflop_like_concentration_is_vetoed_by_multiple_independent_flags():
    x=base()
    x.update({
        'top_buyer_volume_share': .798,
        'top3_buyer_volume_share': .88,
        'effective_buyers': 1.56,
        'roundtrip_wallet_share': .875,
        'net_buy_volume_ratio': -.154,
        'recent_new_buyers': 1,
    })
    a=assess_adversarial_risk(x,'PAPER_PRIORITY')
    assert a.status=='VETO'
    assert a.suggested_decision=='PAPER_VETO'
    assert 'single_buyer_dominance' in a.critical_flags
    assert 'nominal_to_effective_buyer_collapse' in a.critical_flags
    assert 'roundtrip_with_net_sell_pressure' in a.critical_flags


def test_one_critical_flag_only_requires_review():
    x=base();x['top_buyer_volume_share']=.76
    a=assess_adversarial_risk(x,'PAPER_CANDIDATE')
    assert a.status=='REVIEW'
    assert a.suggested_decision=='PAPER_REVIEW'


def test_extreme_single_buyer_can_veto_alone():
    x=base();x['top_buyer_volume_share']=.95
    a=assess_adversarial_risk(x,'PAPER_CANDIDATE')
    assert a.status=='VETO'


def test_missing_candidate_risk_field_fails_closed():
    x=base();x.pop('effective_buyers')
    a=assess_adversarial_risk(x,'PAPER_CANDIDATE')
    assert a.status=='REVIEW_DATA'
    assert a.suggested_decision=='PAPER_REVIEW_DATA'
    assert 'effective_buyers' in a.missing_fields
