import struct
from src.ingest.pump_trade_event import (
    EVENT_IX_TAG_LE, TRADE_EVENT_DISCRIMINATOR, PUMP_PROGRAM_ID, WSOL_MINT,
    b58decode, b58encode, decode_trade_event_bytes, extract_trade_events_from_transaction,
)


def u64(x): return struct.pack('<Q',x)
def i64(x): return struct.pack('<q',x)
def u16(x): return struct.pack('<H',x)
def u32(x): return struct.pack('<I',x)
def pk(seed): return bytes([seed])*32

def string(x):
    b=x.encode(); return u32(len(b))+b


def sample_bytes():
    vsol=30_100_000_000
    vtok=1_069_435_215_946_845
    body=(
        pk(1)+u64(100_000_000)+u64(3_564_784_053_155)+b'\x01'+pk(2)+i64(1_788_000_000)
        +u64(vsol)+u64(vtok)+u64(100_000_000)+u64(500_000_000_000_000)
        +pk(3)+u64(95)+u64(950_000)+pk(4)+u64(30)+u64(300_000)+b'\x01'
        +u64(0)+u64(0)+u64(100_000_000)+i64(1_788_000_000)+string('buy_v2')
        +b'\x00'+u64(0)+u64(0)+u64(20)+u64(200_000)
        +u32(1)+pk(5)+u16(2500)
        +b58decode(WSOL_MINT)+u64(100_000_000)+u64(vsol)+u64(100_000_000)
    )
    return EVENT_IX_TAG_LE+TRADE_EVENT_DISCRIMINATOR+body


def test_base58_pubkey_roundtrip():
    raw=bytes(range(32))
    assert b58decode(b58encode(raw)) == raw


def test_decode_trade_event_full_tail():
    ev=decode_trade_event_bytes(sample_bytes())
    assert ev is not None
    assert ev.is_buy is True
    assert ev.ix_name == 'buy_v2'
    assert ev.quote_mint == WSOL_MINT
    assert ev.shareholders and ev.shareholders[0]['share_bps'] == 2500
    assert ev.token_amount > 3_500_000
    assert 2e-8 < ev.price_sol < 4e-8
    assert 20 < ev.market_cap_sol < 40


def test_extract_event_from_inner_cpi_and_ignore_failed_tx():
    data=b58encode(sample_bytes())
    tx={
        'slot':123,'blockTime':1_788_000_001,
        'transaction':{'message':{'accountKeys':['payer',PUMP_PROGRAM_ID]}},
        'meta':{'err':None,'innerInstructions':[{'index':0,'instructions':[{'programIdIndex':1,'data':data,'accounts':[]}]}], 'logMessages':[]},
    }
    out=extract_trade_events_from_transaction(tx,'sig')
    assert len(out)==1 and out[0].source_signature=='sig' and out[0].source_slot==123
    tx['meta']['err']={'InstructionError':[0,'x']}
    assert extract_trade_events_from_transaction(tx,'sig') == []
