import base64, json, struct

from src.ingest.pump_log_events import parse_logs_notification, trade_events_from_logs
from src.ingest.pump_trade_event import EVENT_IX_TAG_LE, TRADE_EVENT_DISCRIMINATOR, WSOL_MINT, b58decode


def u64(x): return struct.pack('<Q',x)
def i64(x): return struct.pack('<q',x)
def u16(x): return struct.pack('<H',x)
def u32(x): return struct.pack('<I',x)
def pk(seed): return bytes([seed])*32
def string(x):
    b=x.encode(); return u32(len(b))+b


def sample_bytes():
    vsol=30_100_000_000; vtok=1_069_435_215_946_845
    body=(pk(1)+u64(100_000_000)+u64(3_564_784_053_155)+b'\x01'+pk(2)+i64(1_788_000_000)
          +u64(vsol)+u64(vtok)+u64(100_000_000)+u64(500_000_000_000_000)
          +pk(3)+u64(95)+u64(950_000)+pk(4)+u64(30)+u64(300_000)+b'\x01'
          +u64(0)+u64(0)+u64(100_000_000)+i64(1_788_000_000)+string('buy_v2')
          +b'\x00'+u64(0)+u64(0)+u64(20)+u64(200_000)+u32(1)+pk(5)+u16(2500)
          +b58decode(WSOL_MINT)+u64(100_000_000)+u64(vsol)+u64(100_000_000))
    return EVENT_IX_TAG_LE+TRADE_EVENT_DISCRIMINATOR+body


def test_trade_event_decodes_directly_from_program_data_log():
    line='Program data: '+base64.b64encode(sample_bytes()).decode()
    out=trade_events_from_logs(['Program log: x',line],signature='sig',slot=123)
    assert len(out)==1
    assert out[0].source_signature=='sig' and out[0].source_slot==123
    assert out[0].source_block_time==out[0].timestamp
    assert out[0].ix_name=='buy_v2'


def test_logs_notification_parser_rejects_failed_and_normalizes_success():
    line='Program data: '+base64.b64encode(sample_bytes()).decode()
    msg={'method':'logsNotification','params':{'result':{'context':{'slot':321},'value':{'signature':'abc','err':None,'logs':[line]}}}}
    env=parse_logs_notification(msg,received_ms=42)
    assert env and env['received_ms']==42 and env['signature']=='abc' and len(env['events'])==1
    msg['params']['result']['value']['err']={'InstructionError':[0,'x']}
    assert parse_logs_notification(msg,received_ms=42) is None
