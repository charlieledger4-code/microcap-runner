from src.execution.pumpswap_quote import PumpSwapState,quote_sell_base_raw


def test_effective_quote_reserves_and_real_vault_cap():
    s=PumpSwapState(
        pool='p',base_mint='b',quote_mint='q',base_decimals=6,quote_decimals=9,
        base_reserve_raw=500_000_000_000_000,real_quote_reserve_raw=20_000_000_000,
        virtual_quote_reserve_raw=5_000_000_000,lp_fee_bps=20,protocol_fee_bps=5,
        creator_fee_bps=5,cashback_fee_bps=0,source_signature='sig')
    q=quote_sell_base_raw(s,1_000_000_000_000)
    theoretical=(1_000_000_000_000*25_000_000_000)//(501_000_000_000_000)
    assert q.gross_quote_out_raw==theoretical
    assert q.net_quote_out_raw<q.gross_quote_out_raw
    assert q.average_price_quote>0


def test_boost_style_virtual_reserve_cannot_pay_more_than_real_vault():
    s=PumpSwapState(
        pool='p',base_mint='b',quote_mint='q',base_decimals=6,quote_decimals=9,
        base_reserve_raw=1,real_quote_reserve_raw=100,virtual_quote_reserve_raw=1_000_000,
        lp_fee_bps=0,protocol_fee_bps=0,creator_fee_bps=0)
    q=quote_sell_base_raw(s,1_000_000)
    assert q.gross_quote_out_raw==100
    assert q.liquidity_limited is True
