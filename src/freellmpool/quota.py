"""Persistent, per-provider/model/day request counters.

Counters live in a JSON file (default ``~/.config/freellmpool/quota.json``) and
reset at UTC midnight. They are advisory: freellmpool uses them to spread load
and to skip providers that have hit their free-tier daily hint, but it never
guarantees a provider's real server-side limit.

The store is intentionally tiny and dependency-free so it can be embedded in
tests with an explicit path and a fixed clock.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path


def _utc_day(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).strftime("%Y-%m-%d")


def default_quota_path() -> Path:
    override = os.environ.get("FREELLMPOOL_QUOTA_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "freellmpool" / "quota.json"


class QuotaStore:
    """A small JSON-backed counter keyed by (day, provider_id, model)."""

    def __init__(self, path: Path | None = None, clock: Callable[[], datetime] | None = None):
        self.path = path or default_quota_path()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()  # the proxy is threaded; guard read-modify-write
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Unique temp name so concurrent savers never clobber each other's temp.
        tmp = self.path.with_suffix(f"{self.path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def _today(self) -> dict:
        day = _utc_day(self._clock())
        bucket = self._data.get(day)
        if bucket is None:
            # New UTC day → drop stale buckets to keep the file small.
            self._data = {day: {}}
            bucket = self._data[day]
        return bucket

    @staticmethod
    def _key(provider_id: str, model: str) -> str:
        return f"{provider_id}::{model}"

    def used(self, provider_id: str, model: str) -> int:
        with self._lock:
            return int(self._today().get(self._key(provider_id, model), 0))

    def record(self, provider_id: str, model: str, n: int = 1) -> int:
        with self._lock:
            bucket = self._today()
            key = self._key(provider_id, model)
            bucket[key] = int(bucket.get(key, 0)) + n
            count = bucket[key]
            try:
                self._save()
            except OSError:
                # Quota is advisory — never let a persistence hiccup abort an
                # otherwise-successful completion.
                pass
            return count

    def over_budget(self, provider_id: str, model: str, rpd: int) -> bool:
        """True if a positive rpd hint exists and today's use meets/exceeds it."""
        if rpd <= 0:
            return False
        return self.used(provider_id, model) >= rpd

    def snapshot(self) -> dict[str, int]:
        """Today's counters as a flat {provider::model: count} dict."""
        with self._lock:
            return dict(self._today())
