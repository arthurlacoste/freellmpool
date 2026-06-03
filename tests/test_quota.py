"""QuotaStore persistence + UTC-day reset."""

from __future__ import annotations

from datetime import UTC, datetime

from freellmpool.quota import QuotaStore


def _store(tmp_path, day):
    clock = lambda: datetime(2026, 6, day, 12, 0, tzinfo=UTC)  # noqa: E731
    return QuotaStore(path=tmp_path / "q.json", clock=clock)


def test_record_and_used(tmp_path):
    s = _store(tmp_path, 2)
    assert s.used("groq", "m") == 0
    assert s.record("groq", "m") == 1
    assert s.record("groq", "m") == 2
    assert s.used("groq", "m") == 2


def test_persists_across_instances(tmp_path):
    _store(tmp_path, 2).record("groq", "m", 4)
    assert _store(tmp_path, 2).used("groq", "m") == 4


def test_resets_at_utc_midnight(tmp_path):
    _store(tmp_path, 2).record("groq", "m", 7)
    fresh = _store(tmp_path, 3)  # next UTC day
    assert fresh.used("groq", "m") == 0


def test_over_budget(tmp_path):
    s = _store(tmp_path, 2)
    s.record("groq", "m", 3)
    assert s.over_budget("groq", "m", rpd=3) is True
    assert s.over_budget("groq", "m", rpd=5) is False
    assert s.over_budget("groq", "m", rpd=0) is False  # 0 = unmetered hint


def test_snapshot(tmp_path):
    s = _store(tmp_path, 2)
    s.record("groq", "a", 2)
    s.record("cerebras", "b", 1)
    snap = s.snapshot()
    assert snap == {"groq::a": 2, "cerebras::b": 1}


def test_record_merges_concurrent_external_writes(tmp_path):
    # Two stores share the file (as the proxy + a CLI process would). An increment
    # from store B must not clobber an increment store A persisted in between —
    # record() reloads under a cross-process lock before writing.
    a = _store(tmp_path, 2)
    b = _store(tmp_path, 2)
    a.record("groq", "m", 1)  # A writes groq::m = 1
    b.record("cerebras", "n", 1)  # B records its own key — must preserve A's
    assert b.snapshot() == {"groq::m": 1, "cerebras::n": 1}
    # and A sees B's write after a reload
    assert a.snapshot() == {"groq::m": 1, "cerebras::n": 1}
