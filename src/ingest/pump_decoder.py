"""Minimal Pump instruction classifier for raw Solana transactions.

This classifies Anchor instruction discriminators without pretending to decode all
arguments/accounts yet. Discriminators are deterministic SHA256("global:<name>")[:8]
and are checked against Pump's public IDL semantics in tests.
"""
from __future__ import annotations
import hashlib

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_IDX = {c:i for i,c in enumerate(_ALPHABET)}


def b58decode(value: str) -> bytes:
    n = 0
    for ch in value:
        if ch not in _IDX:
            raise ValueError(f"invalid base58 character: {ch!r}")
        n = n * 58 + _IDX[ch]
    raw = n.to_bytes((n.bit_length()+7)//8, "big") if n else b""
    zeros = len(value) - len(value.lstrip("1"))
    return b"\x00" * zeros + raw


def anchor_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


PUMP_INSTRUCTION_DISCRIMINATORS = {
    anchor_discriminator(name): name for name in (
        "create", "create_v2", "buy", "buy_v2", "sell", "sell_v2", "migrate"
    )
}


def classify_instruction_data(data_b58: str | None) -> str | None:
    if not data_b58:
        return None
    raw = b58decode(data_b58)
    if len(raw) < 8:
        return None
    return PUMP_INSTRUCTION_DISCRIMINATORS.get(raw[:8])


def _account_keys(message: dict) -> list[str]:
    keys = message.get("accountKeys", [])
    out = []
    for key in keys:
        if isinstance(key, str):
            out.append(key)
        elif isinstance(key, dict):
            out.append(str(key.get("pubkey", "")))
        else:
            out.append(str(key))
    return out


def classify_transaction(tx_result: dict) -> list[dict]:
    """Return Pump instruction occurrences in top-level and inner instructions."""
    if not tx_result:
        return []
    transaction = tx_result.get("transaction", {})
    message = transaction.get("message", {})
    keys = _account_keys(message)
    found: list[dict] = []

    def inspect(ix: dict, *, outer_index: int | None, inner: bool) -> None:
        pidx = ix.get("programIdIndex")
        pid = keys[pidx] if isinstance(pidx, int) and 0 <= pidx < len(keys) else ix.get("programId")
        if pid != PUMP_PROGRAM_ID:
            return
        name = classify_instruction_data(ix.get("data"))
        found.append({
            "instruction": name or "unknown_pump_instruction",
            "outer_index": outer_index,
            "inner": inner,
            "accounts": ix.get("accounts", []),
            "data": ix.get("data"),
        })

    for i, ix in enumerate(message.get("instructions", [])):
        inspect(ix, outer_index=i, inner=False)

    for group in (tx_result.get("meta") or {}).get("innerInstructions") or []:
        outer = group.get("index")
        for ix in group.get("instructions", []):
            inspect(ix, outer_index=outer, inner=True)
    return found
