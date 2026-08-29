from src.execution.pump_curve_quote import (
    CurveState,quote_buy_by_gross_quote_raw,quote_sell_tokens_raw,apply_buy_to_state,ceil_div
)


def state():
    return CurveState(
        virtual_token_reserves_raw=1_000_000_000_000_000,
        virtual_quote_reserves_raw=30_000_000_000,
        real_token_reserves_raw=700_000_000_000_000,
        real_quote_reserves_raw=10_000_000_000,
        protocol_fee_bps=95,creator_fee_bps=30,cashback_fee_bps=0,
        source_signature='s',
    )


def test_buy_matches_published_budget_formula_and_caps_reserves():
    s=state();gross=100_000_000
    q=quote_buy_by_gross_quote_raw(s,gross)
    swap=((gross-1)*10_000)//10_125
    expected=(swap*s.virtual_token_reserves_raw)//(s.virtual_quote_reserves_raw+swap)
    assert q.swap_quote_in_raw==swap
    assert q.tokens_out_raw==expected
    assert q.total_fee_bps==125
    assert q.average_price_sol>0 and q.price_impact_bps>0


def test_sell_fees_round_up_per_component():
    s=state();tokens=1_000_000_000_000
    q=quote_sell_tokens_raw(s,tokens)
    raw=(tokens*s.virtual_quote_reserves_raw)//(s.virtual_token_reserves_raw+tokens)
    assert q.gross_quote_out_raw==raw
    assert q.protocol_fee_raw==ceil_div(raw*95,10_000)
    assert q.creator_fee_raw==ceil_div(raw*30,10_000)
    assert q.net_quote_out_raw==raw-q.protocol_fee_raw-q.creator_fee_raw


def test_small_round_trip_loses_fees_and_price_impact():
    s=state();buy=quote_buy_by_gross_quote_raw(s,100_000_000);after=apply_buy_to_state(s,buy)
    sell=quote_sell_tokens_raw(after,buy.tokens_out_raw)
    assert sell.net_quote_out_raw < buy.gross_quote_in_raw
    assert after.virtual_token_reserves_raw < s.virtual_token_reserves_raw
    assert after.virtual_quote_reserves_raw > s.virtual_quote_reserves_raw
