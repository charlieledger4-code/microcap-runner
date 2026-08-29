"""RPC enrichment for signatures observed by the raw Solana log collector."""
from __future__ import annotations
import asyncio
from typing import Any
import aiohttp


class SolanaRpc:
    def __init__(self, url: str, timeout_s: float = 20):
        self.url = url
        self.timeout_s = timeout_s
        self._id = 0

    async def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        payload = {"jsonrpc":"2.0","id":self._id,"method":method,"params":params}
        timeout = aiohttp.ClientTimeout(total=self.timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.url, json=payload) as resp:
                resp.raise_for_status()
                body = await resp.json()
        if "error" in body:
            raise RuntimeError(f"Solana RPC error: {body['error']}")
        return body.get("result")

    async def get_transaction(self, signature: str) -> dict | None:
        return await self.call("getTransaction", [signature, {
            "encoding":"json",
            "commitment":"confirmed",
            "maxSupportedTransactionVersion":0,
        }])


async def get_with_retry(rpc: SolanaRpc, signature: str, attempts: int = 4) -> dict | None:
    delay = 0.25
    for i in range(attempts):
        try:
            result = await rpc.get_transaction(signature)
            if result is not None:
                return result
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
            if i == attempts - 1:
                raise
        await asyncio.sleep(delay)
        delay = min(delay * 2, 2.0)
    return None
