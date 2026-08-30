from dataclasses import asdict

from scripts.audit_selected_live60 import AUDIT_VERSION,event_key,tape_events
from src.ingest.pump_trade_event import PumpTradeEvent


def sample_event():
    return PumpTradeEvent(
        mint='mint',sol_amount_raw=1_000_000_000,token_amount_raw=2_000_000,
        is_buy=True,user='wallet',timestamp=123,virtual_sol_reserves_raw=30_000_000_000,
        virtual_token_reserves_raw=1_000_000_000_000,real_sol_reserves_raw=10_000_000_000,
        real_token_reserves_raw=500_000_000_000,fee_recipient='fee',fee_basis_points=95,
        fee_raw=9_500_000,creator='creator',creator_fee_basis_points=30,creator_fee_raw=3_000_000,
        track_volume=True,total_unclaimed_tokens=0,total_claimed_tokens=0,current_sol_volume_raw=0,
        last_update_timestamp=123,ix_name='buy',quote_mint='11111111111111111111111111111111',
        source_signature='sig',source_slot=99,source_block_time=123,
    )


def test_action_tape_raw_event_roundtrip_preserves_signature_identity():
    ev=sample_event();restored=tape_events({'raw_pump_events':[asdict(ev)]})
    assert AUDIT_VERSION=='ht_signature_index_missing_only_v2'
    assert len(restored)==1
    assert restored[0].source_signature=='sig'
    assert restored[0].source_block_time==123
    assert event_key(restored[0])==event_key(ev)


def test_old_tape_without_raw_events_falls_back_cleanly():
    assert tape_events({'tape_version':'action_tape_ht_v1','trades':[]})==[]
