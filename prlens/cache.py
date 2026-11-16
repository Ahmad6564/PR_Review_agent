"""On-disk response cache.

Tuning the filter requires running the benchmark over and over. Without caching,
every change re-issues thousands of LLM calls and iteration takes 20 minutes; with
it, unchanged hunks resolve in milliseconds. Key by a hash of the full request so a
changed prompt or model invalidates the entry automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_DEFAULT_DIR = Path(os.environ.get("PRLENS_CACHE_DIR", ".prlens_cache"))


class DiskCache:
    def __init__(self, directory: str | os.PathLike | None = None, enabled: bool = True):
        self.dir = Path(directory) if directory else _DEFAULT_DIR
        self.enabled = enabled
        if self.enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(payload: dict) -> str:
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str):
        if not self.enabled:
            return None
        p = self.dir / f"{key}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value) -> None:
        if not self.enabled:
            return
        p = self.dir / f"{key}.json"
        try:
            p.write_text(json.dumps(value, default=str), encoding="utf-8")
        except OSError:
            pass
