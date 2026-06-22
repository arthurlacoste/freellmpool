from __future__ import annotations

from types import SimpleNamespace

import pytest

from freellmpool.mode import (
    WISE_DEFAULT_MAX_TOKENS,
    WISE_DEFAULT_ROUTING,
    default_routing_for_mode,
)
from freellmpool.models import Reply


class _EmptyQuota:
    def snapshot(self):
        return {}


class _FakeAskPool:
    quota = _EmptyQuota()

    def __init__(self, captured, env=None):
        self.captured = captured
        self.env = {"FREELLMPOOL_MODE": "wise"} if env is None else env
        self.providers = []

    def rank_targets(self, messages, **kwargs):
        self.captured["rank_messages"] = messages
        self.captured["rank"] = kwargs
        return []

    def ask(self, prompt, **kwargs):
        self.captured["prompt"] = prompt
        self.captured.update(kwargs)
        return Reply(text="ok", provider_id="fake", model="fake-model", raw={})


def test_default_routing_for_mode_preserves_explicit_choices():
    assert default_routing_for_mode({}, {}) == "fair"
    assert default_routing_for_mode({"FREELLMPOOL_MODE": "wise"}, {}) == "spread"
    assert default_routing_for_mode({}, {"mode": "wise"}) == "spread"
    assert (
        default_routing_for_mode(
            {"FREELLMPOOL_MODE": "wise", "FREELLMPOOL_ROUTING": "fast"}, {}
        )
        == "fast"
    )
    assert default_routing_for_mode({"FREELLMPOOL_MODE": "wise"}, {"routing": "quality"}) == "quality"


def test_wise_ask_applies_lower_defaults(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: _FakeAskPool(captured)))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 0

    assert captured["max_tokens"] == WISE_DEFAULT_MAX_TOKENS
    assert captured["routing"] == WISE_DEFAULT_ROUTING
    assert capsys.readouterr().out.strip() == "ok"


def test_per_command_mode_enables_wise_defaults(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    monkeypatch.delenv("FREELLMPOOL_MODE", raising=False)
    monkeypatch.setattr(
        Pool,
        "from_default_config",
        classmethod(lambda cls: _FakeAskPool(captured, env={})),
    )
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--mode", "wise"]) == 0

    assert captured["max_tokens"] == WISE_DEFAULT_MAX_TOKENS
    assert captured["routing"] == WISE_DEFAULT_ROUTING


def test_config_mode_enables_wise_defaults(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    monkeypatch.delenv("FREELLMPOOL_MODE", raising=False)
    monkeypatch.setattr(
        Pool,
        "from_default_config",
        classmethod(lambda cls: _FakeAskPool(captured, env={})),
    )
    monkeypatch.setattr("freellmpool.cli.settings", lambda _env: {"mode": "wise"})
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 0

    assert captured["max_tokens"] == WISE_DEFAULT_MAX_TOKENS
    assert captured["routing"] == WISE_DEFAULT_ROUTING


@pytest.mark.parametrize(
    ("argv", "key", "expected"),
    [
        (["ask", "hello", "--max-tokens", "2048"], "max_tokens", 2048),
        (["ask", "hello", "--routing", "fast"], "routing", "fast"),
        (["ask", "hello", "--model", "beta-1"], "model", "beta-1"),
        (["ask", "hello", "--providers", "beta,alpha"], "providers", ["beta", "alpha"]),
    ],
)
def test_wise_ask_explicit_flags_win(monkeypatch, argv, key, expected):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: _FakeAskPool(captured)))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(argv) == 0

    assert captured[key] == expected


def test_wise_ask_role_defaults_win(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: _FakeAskPool(captured)))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--role", "coder"]) == 0

    assert captured["max_tokens"] == 2048
    assert captured["routing"] == "quality"


def test_wise_exhausted_declared_quota_fails_before_provider_call(
    providers, env, quota, monkeypatch, capsys
):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    quota.record("alpha", "alpha-small", 2)
    post = make_post({})
    pool = Pool(
        providers,
        quota=quota,
        env={**env, "FREELLMPOOL_MODE": "wise"},
        post=post,
    )
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 4

    assert post.calls == []
    assert "declared local free quota is exhausted" in capsys.readouterr().err


def test_wise_ask_narrows_to_exact_declared_headroom_target(providers, env, quota, monkeypatch):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    post = make_post({"alpha.test": (500, {})})
    pool = Pool(
        providers,
        quota=quota,
        env={**env, "FREELLMPOOL_MODE": "wise"},
        post=post,
    )
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 4

    assert len(post.calls) == 1
    assert post.calls[0]["body"]["model"] == "alpha-small"


def test_wise_explicit_provider_can_override_exhausted_declared_quota(
    providers, env, quota, monkeypatch
):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    quota.record("alpha", "alpha-small", 2)
    post = make_post({})
    pool = Pool(
        providers,
        quota=quota,
        env={**env, "FREELLMPOOL_MODE": "wise"},
        post=post,
    )
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--providers", "beta"]) == 0

    assert len(post.calls) == 1
    assert "beta.test" in post.calls[0]["url"]


def test_quota_wise_status_reports_headroom_and_recommendation(
    providers, env, quota, monkeypatch, capsys
):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    quota.record("alpha", "alpha-small", 1)
    pool = Pool(providers, quota=quota, env={**env, "FREELLMPOOL_MODE": "wise"})
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))

    assert main(["quota-wise", "status"]) == 0

    out = capsys.readouterr().out
    assert "local headroom" in out
    assert "recommended mode:" in out
    assert "alpha" in out


def test_quota_wise_status_honors_config_mode(providers, env, quota, monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    pool = Pool(providers, quota=quota, env=env)
    monkeypatch.delenv("FREELLMPOOL_MODE", raising=False)
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli.settings", lambda _env: {"mode": "wise"})

    assert main(["quota-wise", "status"]) == 0

    assert "active mode:      wise" in capsys.readouterr().out


def test_tokenmax_config_mode_uses_wise_routing(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    target = SimpleNamespace(provider=SimpleNamespace(id="alpha"), model="alpha-small", rpd=0)

    class FakePool:
        env = {}
        providers = [SimpleNamespace(id="alpha")]
        quota = _EmptyQuota()

    def fake_select_targets(pool, messages, max_models=None, *, routing=None):
        captured["routing"] = routing
        return [target], 1

    def fake_fan_out(pool, messages, picks, **kwargs):
        return [("alpha/alpha-small", "ok")], []

    monkeypatch.delenv("FREELLMPOOL_MODE", raising=False)
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli.settings", lambda _env: {"mode": "wise"})
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")
    monkeypatch.setattr("freellmpool.tokenmax.select_targets", fake_select_targets)
    monkeypatch.setattr("freellmpool.tokenmax.fan_out", fake_fan_out)

    assert main(["tokenmax", "hello", "--no-synthesize"]) == 0

    assert captured["routing"] == WISE_DEFAULT_ROUTING
    assert "TOKENMAX" in capsys.readouterr().out


def test_tokenmax_mode_normal_overrides_wise_env_routing(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    target = SimpleNamespace(provider=SimpleNamespace(id="alpha"), model="alpha-small", rpd=0)

    class FakePool:
        env = {"FREELLMPOOL_MODE": "wise"}
        providers = [SimpleNamespace(id="alpha")]
        quota = _EmptyQuota()

    def fake_select_targets(pool, messages, max_models=None, *, routing=None):
        captured["routing"] = routing
        return [target], 1

    def fake_fan_out(pool, messages, picks, **kwargs):
        return [("alpha/alpha-small", "ok")], []

    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")
    monkeypatch.setattr("freellmpool.tokenmax.select_targets", fake_select_targets)
    monkeypatch.setattr("freellmpool.tokenmax.fan_out", fake_fan_out)

    assert main(["tokenmax", "hello", "--mode", "normal", "--no-synthesize"]) == 0

    assert captured["routing"] == "fair"


def test_wise_tokenmax_prefers_declared_headroom(providers, env, quota, monkeypatch, capsys):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    post = make_post({})
    pool = Pool(providers, quota=quota, env={**env, "FREELLMPOOL_MODE": "wise"}, post=post)
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["tokenmax", "hello", "--no-synthesize"]) == 0

    assert "TOKENMAX — 1 models" in capsys.readouterr().out
    assert len(post.calls) == 1
    assert "alpha.test" in post.calls[0]["url"]


def test_wise_tokenmax_synthesis_uses_declared_headroom(providers, env, quota, monkeypatch, capsys):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    post = make_post({})
    pool = Pool(providers, quota=quota, env={**env, "FREELLMPOOL_MODE": "wise"}, post=post)
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["tokenmax", "hello"]) == 0

    assert "SYNTHESIS" in capsys.readouterr().out
    assert [call["body"]["model"] for call in post.calls] == ["alpha-small", "alpha-small"]


def test_wise_tokenmax_skips_synthesis_when_declared_headroom_is_spent(
    providers, env, quota, monkeypatch, capsys
):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    quota.record("alpha", "alpha-small", 1)
    post = make_post({})
    pool = Pool(providers, quota=quota, env={**env, "FREELLMPOOL_MODE": "wise"}, post=post)
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["tokenmax", "hello"]) == 0

    assert len(post.calls) == 1
    assert "synthesis skipped" in capsys.readouterr().err


def test_wise_tokenmax_noninteractive_expensive_fanout_fails(
    quota, monkeypatch, capsys
):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.models import Model, Provider
    from freellmpool.router import Pool

    providers = [
        Provider(
            id="unknown",
            label="Unknown",
            adapter="openai",
            base_url="https://unknown.test/v1",
            auth="none",
            models=tuple(Model(f"m{i}", rpd=0) for i in range(4)),
        )
    ]
    post = make_post({})
    pool = Pool(providers, quota=quota, env={"FREELLMPOOL_MODE": "wise"}, post=post)
    monkeypatch.setenv("FREELLMPOOL_MODE", "wise")
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["tokenmax", "hello", "--max-models", "4", "--no-synthesize"]) == 4

    assert post.calls == []
    assert "wise mode refuses tokenmax fan-out" in capsys.readouterr().err
