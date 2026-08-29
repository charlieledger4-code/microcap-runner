from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def append_jsonl(path: str | Path, obj: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
