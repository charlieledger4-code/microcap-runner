from src.live.action_forensics import summarize_action_tape


def t(sig,w,buy,sec,sol):
    return {'signature':sig,'user_wallet':w,'is_buy':buy,'seconds_since_launch':sec,'sol_amount':sol}


def test_detects_same_time_size_clusters_and_fast_roundtrips():
    rows=[
        t('s1','a',True,5.1,.1),t('s2','b',True,5.4,.1),t('s3','c',True,5.8,.1),
        t('s4','a',False,12,.08),t('s5','b',False,20,.08),
    ]
    x=summarize_action_tape(rows)
    assert x['unique_buyers']==3
    assert x['max_distinct_buyers_same_second']==3
    assert x['max_distinct_buyers_same_rounded_size']==3
    assert x['max_two_second_same_size_cluster']==3
    assert x['fast_roundtrip_wallets_10s']==1
    assert x['roundtrip_wallets']==2


def test_multi_actor_same_signature_is_visible():
    rows=[t('bundle','a',True,1,.2),t('bundle','b',True,1.1,.3)]
    assert summarize_action_tape(rows)['max_distinct_wallets_same_signature']==2
