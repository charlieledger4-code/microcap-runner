from src.live.feature60_v2 import LIVECORE_V2_FEATURES, build_livecore_v2_features


def tr(sec,user,buy,sol,price=1e-8,tok=None):
    if tok is None: tok=sol/price
    return {'seconds_since_launch':sec,'user_wallet':user,'is_buy':buy,'sol_amount':sol,'token_amount':tok,'price_sol':price,'market_cap_sol':price*1e9}


def test_v2_contract_and_concentration_features():
    launch={'traderPublicKey':'creator','solAmount':1,'marketCapSol':10,'is_mayhem_mode':False}
    rows=[
        tr(0,'creator',True,1,1e-8),
        tr(5,'a',True,2,1.1e-8),
        tr(7,'b',True,1,1.2e-8),
        tr(20,'a',False,.5,1.15e-8),
        tr(40,'c',True,1,1.3e-8),
        tr(50,'d',True,1,1.4e-8),
    ]
    f=build_livecore_v2_features(launch,rows,launch_unix_s=0)
    assert list(f)==LIVECORE_V2_FEATURES
    assert f['first10_unique_buyers']==3
    assert f['recent_new_buyers']==2
    assert 0 < f['buyer_volume_hhi'] < 1
    assert f['effective_buyers'] > 1
    assert 0 < f['top_buyer_volume_share'] < 1
    assert 0 < f['roundtrip_wallet_share'] < 1
    assert f['peak_to_entry_drawdown']==0
    assert f['recent30_return'] > 0


def test_v2_flags_single_whale_as_high_concentration():
    launch={'traderPublicKey':'creator','solAmount':9,'marketCapSol':10}
    rows=[tr(0,'creator',True,9),tr(20,'a',True,1)]
    f=build_livecore_v2_features(launch,rows,launch_unix_s=0)
    assert f['top_buyer_volume_share'] > .89
    assert f['buyer_volume_hhi'] > .8
    assert f['effective_buyers'] < 1.3
