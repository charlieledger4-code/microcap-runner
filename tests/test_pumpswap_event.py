import struct
from src.ingest.pump_trade_event import EVENT_IX_TAG_LE, b58decode, b58encode, WSOL_MINT
from src.ingest.pumpswap_event import (
    CREATE_POOL_DISCRIMINATOR, BUY_DISCRIMINATOR, SELL_DISCRIMINATOR,
    decode_pumpswap_event_bytes, PumpSwapPoolEvent, PumpSwapTradeEvent,
)

def u8(x):return bytes([x])
def u16(x):return struct.pack('<H',x)
def u32(x):return struct.pack('<I',x)
def u64(x):return struct.pack('<Q',x)
def i64(x):return struct.pack('<q',x)
def i128(x):return int(x).to_bytes(16,'little',signed=True)
def pk(n):return bytes([n])*32
def s(x):b=x.encode();return u32(len(b))+b

def pool_bytes():
    body=(i64(100)+u16(0)+pk(1)+pk(2)+b58decode(WSOL_MINT)+u8(6)+u8(9)+u64(1000)+u64(1000)+u64(500_000_000_000_000)+u64(30_000_000_000)+u64(1)+u64(2)+u64(3)+u8(7)+pk(4)+pk(5)+pk(6)+pk(7)+pk(8)+u8(0))
    return EVENT_IX_TAG_LE+CREATE_POOL_DISCRIMINATOR+body

def buy_bytes():
    body=(i64(101)+u64(1_000_000)+u64(100_000_000)+u64(2)+u64(3)+u64(499_000_000_000_000)+u64(31_000_000_000)+u64(31_000_000)+u64(20)+u64(20_000)+u64(5)+u64(5_000)+u64(31_020_000)+u64(31_030_000)+pk(4)+pk(9)+pk(10)+pk(11)+pk(12)+pk(13)+pk(8)+u64(10)+u64(10_000)+u8(1)+u64(0)+u64(0)+u64(1)+i64(101)+u64(900_000)+s('buy')+u64(0)+u64(0)+u64(0)+u64(0)+i128(0)+u8(0)+u64(1_000_000_000_000_000))
    return EVENT_IX_TAG_LE+BUY_DISCRIMINATOR+body

def sell_bytes():
    body=(i64(102)+u64(2_000_000)+u64(100_000)+u64(2)+u64(3)+u64(501_000_000_000_000)+u64(29_000_000_000)+u64(120_000)+u64(20)+u64(20_000)+u64(5)+u64(5_000)+u64(130_000)+u64(110_000)+pk(4)+pk(9)+pk(10)+pk(11)+pk(12)+pk(13)+pk(8)+u64(10)+u64(10_000)+u64(0)+u64(0)+u64(0)+u64(0)+i128(0)+u8(0)+u64(1_000_000_000_000_000))
    return EVENT_IX_TAG_LE+SELL_DISCRIMINATOR+body

def test_decode_pool_and_buy_sell_events():
    p=decode_pumpswap_event_bytes(pool_bytes())
    assert isinstance(p,PumpSwapPoolEvent)
    assert p.quote_mint==WSOL_MINT and p.base_mint_decimals==6 and p.quote_mint_decimals==9
    buy=decode_pumpswap_event_bytes(buy_bytes());sell=decode_pumpswap_event_bytes(sell_bytes())
    assert isinstance(buy,PumpSwapTradeEvent) and buy.side=='buy' and buy.ix_name=='buy'
    assert isinstance(sell,PumpSwapTradeEvent) and sell.side=='sell'
    assert buy.execution_price_quote(p)==0.031
    assert sell.execution_price_quote(p)==0.06
    assert buy.reserve_price_quote(p)>0 and sell.reserve_price_quote(p)>0
