from datetime import datetime, timezone
from src.live.feature60 import build_livecore_features, LIVECORE_FEATURES, SLINKY_SYSTEM_WALLET, event_to_trade
from src.ingest.pump_trade_event import SYSTEM_PROGRAM, PumpTradeEvent


def tr(sec,user,buy,sol,tok,price,mc=30):
    return {'seconds_since_launch':sec,'user_wallet':user,'is_buy':buy,'sol_amount':sol,'token_amount':tok,'price_sol':price,'market_cap_sol':mc}


def test_livecore_filters_future_and_system_rows_and_matches_duckdb_dow():
    # 2026-08-30 is Sunday; DuckDB extract(dow) uses Sunday=0.
    launch_s=datetime(2026,8,30,12,0,tzinfo=timezone.utc).timestamp()
    launch={'traderPublicKey':'creator','solAmount':0.1,'is_mayhem_mode':False,'marketCapSol':30}
    rows=[
        tr(0,'creator',True,.03,1_000_000,3e-8),
        tr(20,'a',True,.03,1_000_000,3e-8),
        tr(40,'b',False,.03,1_000_000,3e-8),
        tr(45,SLINKY_SYSTEM_WALLET,False,.03,1_000_000,3e-8),
        tr(50,SYSTEM_PROGRAM,True,.03,1_000_000,3e-8),
        tr(70,'future',True,30,1_000_000,3e-5,30000),
    ]
    f=build_livecore_features(launch,rows,launch_unix_s=launch_s)
    assert list(f) == LIVECORE_FEATURES
    assert f['human_trades']==3
    assert f['buys']==2 and f['sells']==1
    assert f['prior_trades']==2 and f['recent_trades']==1
    assert f['creator_trades']==1
    assert f['entry_price_sol']==3e-8
    assert f['market_cap_sol']==30
    assert f['dow_utc']==0


def test_native_sol_system_program_quote_sentinel_is_admissible():
    ev=PumpTradeEvent(
        mint='m',sol_amount_raw=1_000_000_000,token_amount_raw=10_000_000,is_buy=True,user='u',timestamp=100,
        virtual_sol_reserves_raw=30_000_000_000,virtual_token_reserves_raw=1_000_000_000_000_000,
        real_sol_reserves_raw=1,real_token_reserves_raw=1,fee_recipient='f',fee_basis_points=0,fee_raw=0,
        creator='c',creator_fee_basis_points=0,creator_fee_raw=0,track_volume=False,total_unclaimed_tokens=0,
        total_claimed_tokens=0,current_sol_volume_raw=0,last_update_timestamp=0,ix_name='buy',
        quote_mint=SYSTEM_PROGRAM,quote_amount_raw=1_000_000_000,virtual_quote_reserves_raw=30_000_000_000,
        real_quote_reserves_raw=1,source_block_time=100,
    )
    t=event_to_trade(ev,99)
    assert t is not None and t['seconds_since_launch']==1
    assert t['price_sol'] is not None and t['market_cap_sol'] is not None


def test_livecore_acceleration_formulas():
    launch={'traderPublicKey':'creator','solAmount':0.1}
    rows=[tr(10,'a',True,.03,1_000_000,3e-8),tr(40,'b',True,.03,1_000_000,3e-8),tr(45,'c',True,.03,1_000_000,3e-8)]
    f=build_livecore_features(launch,rows,launch_unix_s=0)
    assert f['tx_acceleration']==0.5  # (2-1)/(1+1)
    assert f['buyer_acceleration']==0.5
