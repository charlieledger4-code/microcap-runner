from src.ingest.pump_decoder import anchor_discriminator, b58decode, classify_instruction_data

ALPHABET="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58encode(raw: bytes) -> str:
    n=int.from_bytes(raw,'big'); chars=[]
    while n:
        n,r=divmod(n,58); chars.append(ALPHABET[r])
    zeros=len(raw)-len(raw.lstrip(b'\0'))
    return '1'*zeros + (''.join(reversed(chars)) if chars else '')


def test_buy_anchor_discriminator_matches_public_idl():
    assert list(anchor_discriminator("buy")) == [102,6,61,18,1,218,235,234]


def test_classify_v2():
    payload=anchor_discriminator("buy_v2") + b'\x00'*16
    assert classify_instruction_data(b58encode(payload)) == "buy_v2"
    assert b58decode(b58encode(payload)) == payload
