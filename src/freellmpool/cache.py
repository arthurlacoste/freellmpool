"""Opt-in response cache (sqlite) — skip re-asking the same thing.

Off by default. Enable with a positive TTL via ``FREELLMPOOL_CACHE_TTL`` (seconds)
or ``[settings] cache_ttl`` in config.toml. Handy for dev/test loops where the
same prompts run repeatedly: it saves quota and answers instantly.

Keyed on a hash of (messages, model, providers, max_tokens, temperature, tools),
so only *identical* requests hit the cache. Standard-library sqlite3, no deps.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path


def default_cache_path() -> Path:
    override = os.environ.get("FREELLMPOOL_CACHE_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "freellmpool" / "cache.db"


class Cache:
    def __init__(
        self, ttl: float, path: Path | None = None, clock: Callable[[], float] | None = None
    ):
        self.ttl = ttl
        self.path = path or default_cache_path()
        self._clock = clock or time.time
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # `with sqlite3.connect()` manages the transaction but NOT the connection,
        # so every call must also close() it (via contextlib.closing) or it leaks a
        # file handle until GC. `, con` keeps the transaction-commit behavior.
        with closing(self._conn()) as con, con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, created REAL)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def make_key(
        messages, model, providers, max_tokens, temperature, tools, tool_choice=None
    ) -> str:
        payload = json.dumps(
            {
                "messages": messages,
                "model": model,
                "providers": sorted(providers) if providers else None,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "tools": tools,
                "tool_choice": tool_choice,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        cutoff = self._clock() - self.ttl
        try:
            with closing(self._conn()) as con:
                row = con.execute(
                    "SELECT value, created FROM cache WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.Error:
            return None
        if not row or row[1] < cutoff:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, ValueError):
            return None

    def put(self, key: str, value: dict) -> None:
        try:
            with closing(self._conn()) as con, con:
                con.execute(
                    "INSERT OR REPLACE INTO cache (key, value, created) VALUES (?, ?, ?)",
                    (key, json.dumps(value), self._clock()),
                )
        except sqlite3.Error:
            pass  # cache is best-effort — never break a request over it
