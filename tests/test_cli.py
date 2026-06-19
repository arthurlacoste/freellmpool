"""CLI helpers that don't need network."""

from __future__ import annotations

from types import SimpleNamespace

from freellmpool.cli import _strip_fences
from freellmpool.models import Reply


def test_strip_plain_json():
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_cli_tokenmax_smoke(providers, env, quota, monkeypatch, capsys):
    """`freellmpool tokenmax` blasts the fake pool and prints every answer."""
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    pool = Pool(providers, quota=quota, env=env, post=make_post({}))  # all return "ok"
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["tokenmax", "capital of Australia?", "--no-synthesize"]) == 0
    out = capsys.readouterr().out
    assert "TOKENMAX" in out
    assert "###" in out  # at least one model's answer


def test_cli_tokenmax_synthesizes_by_default(providers, env, quota, monkeypatch, capsys):
    from helpers import make_post

    from freellmpool.cli import main
    from freellmpool.router import Pool

    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["tokenmax", "hi", "--max-models", "2"]) == 0
    out = capsys.readouterr().out
    assert "SYNTHESIS" in out  # the verdict is produced unless --no-synthesize


def test_cli_ask_passes_timeout(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["timeout"] = kwargs["timeout"]
            return Reply(text="ok", provider_id="fake", model="fake-model", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--timeout", "12.5"]) == 0

    assert captured == {"prompt": "hello", "timeout": 12.5}
    assert capsys.readouterr().out.strip() == "ok"


def test_cli_roles_lists_role_presets(capsys):
    from freellmpool.cli import main

    assert main(["roles"]) == 0

    out = capsys.readouterr().out
    assert "Available roles:" in out
    assert "coder" in out
    assert "critic" in out
    assert "second-opinion" in out


def test_cli_ask_role_applies_role_defaults(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured.update(kwargs)
            return Reply(text="ok", provider_id="fake", model="fake-model", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--role", "coder"]) == 0

    assert captured["routing"] == "quality"
    assert captured["max_tokens"] == 2048
    assert "programmer" in captured["system"].lower()
    assert capsys.readouterr().out.strip() == "ok"


def test_cli_ask_routing_override_beats_role(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured.update(kwargs)
            return Reply(text="ok", provider_id="fake", model="fake-model", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--role", "coder", "--routing", "fast"]) == 0

    assert captured["routing"] == "fast"


def test_cli_ask_routing_auto_beats_role_with_pool_default(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured.update(kwargs)
            return Reply(text="ok", provider_id="fake", model="fake-model", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--role", "coder", "--routing", "auto"]) == 0

    assert captured["routing"] is None


def test_cli_ask_without_routing_keeps_pool_default(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured.update(kwargs)
            return Reply(text="ok", provider_id="fake", model="fake-model", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello"]) == 0

    assert captured["routing"] is None
    assert captured["max_tokens"] == 1024
    assert captured["temperature"] == 0.0


def test_cli_ask_unknown_role_lists_valid_roles(monkeypatch, capsys):
    from freellmpool.cli import main

    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["ask", "hello", "--role", "missing-role"]) == 2

    err = capsys.readouterr().err
    assert "unknown role 'missing-role'" in err
    assert "Available roles:" in err
    assert "coder" in err


def test_cli_ask_role_with_explicit_model_keeps_verbose_provenance(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}

    class FakePool:
        def ask(self, prompt, **kwargs):
            captured.update(kwargs)
            return Reply(text="ok", provider_id="alpha", model="alpha-small", raw={})

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: FakePool()))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")
    monkeypatch.setattr(
        "freellmpool.cli.configured_providers",
        lambda: [SimpleNamespace(id="alpha")],
    )

    assert main(["ask", "hello", "--role", "coder", "--model", "alpha/alpha-small", "-v"]) == 0

    assert captured["providers"] == ["alpha"]
    assert captured["model"] == "alpha-small"
    err = capsys.readouterr().err
    assert "served by alpha/alpha-small" in err


def test_cli_tokenmax_passes_timeout(monkeypatch):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    fake_pool = SimpleNamespace(providers=[object()])

    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: fake_pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")
    monkeypatch.setattr(
        "freellmpool.tokenmax.select_targets",
        lambda pool, messages, max_models: ([SimpleNamespace()], 1),
    )

    def fake_fan_out(pool, messages, picks, *, max_tokens, timeout, progress=None):
        captured["timeout"] = timeout
        captured["max_tokens"] = max_tokens
        return [("fake/model", "ok")], []

    monkeypatch.setattr("freellmpool.tokenmax.fan_out", fake_fan_out)

    assert main(["tokenmax", "hello", "--timeout", "7.25", "--no-synthesize"]) == 0

    assert captured == {"timeout": 7.25, "max_tokens": 400}


def test_cli_tokenmax_passes_timeout_to_synthesis(monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.router import Pool

    captured = {}
    fake_pool = SimpleNamespace(providers=[object()])

    def fake_chat(messages, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        captured["messages"] = messages
        return Reply(text="summary", provider_id="fake", model="synth-model", raw={})

    fake_pool.chat = fake_chat
    monkeypatch.setattr(Pool, "from_default_config", classmethod(lambda cls: fake_pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")
    monkeypatch.setattr(
        "freellmpool.tokenmax.select_targets",
        lambda pool, messages, max_models: ([SimpleNamespace()], 1),
    )
    monkeypatch.setattr(
        "freellmpool.tokenmax.fan_out",
        lambda pool, messages, picks, *, max_tokens, timeout, progress=None: (
            [("fake/model", "answer")],
            [],
        ),
    )

    assert main(["tokenmax", "hello", "--timeout", "11.5"]) == 0

    assert captured["timeout"] == 11.5
    assert "answer" in captured["messages"][0]["content"]
    assert "SYNTHESIS" in capsys.readouterr().out


def test_tokenmax_fan_out_passes_timeout_to_pool_chat():
    from freellmpool.tokenmax import fan_out

    captured = {}
    target = SimpleNamespace(provider=SimpleNamespace(id="fake"), model="model-a")

    class FakePool:
        def chat(self, messages, **kwargs):
            captured["messages"] = messages
            captured["timeout"] = kwargs["timeout"]
            return Reply(text="ok", provider_id="fake", model="model-a", raw={})

    answered, failed = fan_out(
        FakePool(),
        [{"role": "user", "content": "hello"}],
        [target],
        max_tokens=50,
        timeout=3.5,
    )

    assert answered == [("fake/model-a", "ok")]
    assert failed == []
    assert captured == {
        "messages": [{"role": "user", "content": "hello"}],
        "timeout": 3.5,
    }


def test_strip_fenced_json():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_bare_fence():
    assert _strip_fences("```\nhello\n```") == "hello"


def test_cli_capacity_status_smoke(monkeypatch, capsys):
    from freellmpool.cli import main

    monkeypatch.setenv("FREELLMPOOL_KEYS_PATH", "/tmp/freellmpool-test-missing-keys.toml")
    assert main(["capacity", "status", "--target", "1", "--no-catalog-sync"]) == 0
    out = capsys.readouterr().out
    assert "LLM capacity:" in out


def test_cli_doctor_smoke(tmp_path, monkeypatch, capsys):
    from freellmpool.cli import main

    monkeypatch.setenv("FREELLMPOOL_CONFIG_FILE", str(tmp_path / "config.toml"))
    monkeypatch.setenv("FREELLMPOOL_QUOTA_PATH", str(tmp_path / "quota.json"))
    monkeypatch.setenv("FREELLMPOOL_CACHE_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setenv("FREELLMPOOL_EXTERNAL_CATALOG_PATH", str(tmp_path / "external.json"))

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "freellmpool" in out
    assert "providers:" in out
    assert "catalog: ok" in out


def test_cli_keys_checklist_smoke(monkeypatch, capsys):
    from freellmpool.cli import main

    monkeypatch.setenv("FREELLMPOOL_KEYS_PATH", "/tmp/freellmpool-test-missing-keys.toml")
    assert main(["keys", "checklist", "--target", "1"]) == 0
    out = capsys.readouterr().out
    assert "healthy providers" in out or "Manual key checklist" in out


def test_cli_keys_add_confirms_fuzzy_external_match(tmp_path, monkeypatch, capsys):
    from freellmpool.cli import main

    cache = tmp_path / "provider_catalog.json"
    user_catalog = tmp_path / "providers.toml"
    config = tmp_path / "config.toml"
    inventory = tmp_path / "keys.toml"
    cache.write_text(
        '{"providers":[{"name":"Hyperbolic","baseUrl":"https://api.hyperbolic.xyz/v1",'
        '"models":[{"id":"meta-llama/Llama-3.3-70B-Instruct","modality":"Text","rateLimit":"100 RPD"}]}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("FREELLMPOOL_EXTERNAL_CATALOG_PATH", str(cache))
    monkeypatch.setenv("FREELLMPOOL_CONFIG", str(user_catalog))
    monkeypatch.setenv("FREELLMPOOL_CONFIG_FILE", str(config))
    monkeypatch.setenv("FREELLMPOOL_KEYS_PATH", str(inventory))
    answers = iter(["y", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert main(["keys", "add", "Hyperbolc", "--value", "secret"]) == 0

    assert 'id = "hyperbolic"' in user_catalog.read_text()
    assert 'HYPERBOLIC_API_KEY = "secret"' in config.read_text()
    assert 'provider = "hyperbolic"' in inventory.read_text()
    assert "Imported external provider 'Hyperbolic'" in capsys.readouterr().out


def test_cli_keys_add_creates_manual_provider(tmp_path, monkeypatch):
    from freellmpool.cli import main

    user_catalog = tmp_path / "providers.toml"
    config = tmp_path / "config.toml"
    inventory = tmp_path / "keys.toml"
    monkeypatch.setenv("FREELLMPOOL_CONFIG", str(user_catalog))
    monkeypatch.setenv("FREELLMPOOL_CONFIG_FILE", str(config))
    monkeypatch.setenv("FREELLMPOOL_KEYS_PATH", str(inventory))
    monkeypatch.setattr("freellmpool.cli._load_or_sync_external_catalog", lambda: [])
    answers = iter(["y", "https://api.hyperbolic.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert main(["keys", "add", "Hyperbolic", "--value", "secret"]) == 0

    assert 'id = "hyperbolic"' in user_catalog.read_text()
    assert 'name = "meta-llama/Llama-3.3-70B-Instruct"' in user_catalog.read_text()
    assert 'HYPERBOLIC_API_KEY = "secret"' in config.read_text()


def test_cli_keys_add_cloudflare_prompts_for_account_id(tmp_path, monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.config import effective_env, load_catalog

    config = tmp_path / "config.toml"
    inventory = tmp_path / "keys.toml"
    monkeypatch.setenv("FREELLMPOOL_CONFIG_FILE", str(config))
    monkeypatch.setenv("FREELLMPOOL_KEYS_PATH", str(inventory))
    answers = iter(["account-123", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert main(["keys", "add", "cloudflare", "--value", "token-secret"]) == 0

    text = config.read_text()
    assert 'CLOUDFLARE_API_TOKEN = "token-secret"' in text
    assert 'CLOUDFLARE_ACCOUNT_ID = "account-123"' in text
    env = effective_env({"FREELLMPOOL_CONFIG_FILE": str(config)})
    cloudflare = next(p for p in load_catalog() if p.id == "cloudflare")
    assert cloudflare.is_configured(env)
    assert "CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID" in capsys.readouterr().out


def test_cli_keys_add_cloudflare_uses_existing_account_id(tmp_path, monkeypatch, capsys):
    from freellmpool.cli import main
    from freellmpool.config import effective_env, load_catalog

    config = tmp_path / "config.toml"
    inventory = tmp_path / "keys.toml"
    config.write_text(
        '[keys]\nCLOUDFLARE_API_TOKEN = "old-token"\nCLOUDFLARE_ACCOUNT_ID = "account-123"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FREELLMPOOL_CONFIG_FILE", str(config))
    monkeypatch.setenv("FREELLMPOOL_KEYS_PATH", str(inventory))
    prompts = []

    def answer_confirm(prompt=""):
        prompts.append(prompt)
        return "y"

    monkeypatch.setattr("builtins.input", answer_confirm)

    assert main(["keys", "add", "cloudflare", "--value", "new-token"]) == 0

    text = config.read_text()
    assert 'CLOUDFLARE_API_TOKEN = "new-token"' in text
    assert 'CLOUDFLARE_ACCOUNT_ID = "account-123"' in text
    env = effective_env({"FREELLMPOOL_CONFIG_FILE": str(config)})
    cloudflare = next(p for p in load_catalog() if p.id == "cloudflare")
    assert cloudflare.is_configured(env)
    assert len(prompts) == 1
    assert "CLOUDFLARE_ACCOUNT_ID" not in prompts[0]
    assert "Wrote: CLOUDFLARE_API_TOKEN" in capsys.readouterr().out


def test_cli_keys_add_autodiscovers_model_when_blank(tmp_path, monkeypatch):
    from freellmpool.cli import main

    user_catalog = tmp_path / "providers.toml"
    config = tmp_path / "config.toml"
    inventory = tmp_path / "keys.toml"
    monkeypatch.setenv("FREELLMPOOL_CONFIG", str(user_catalog))
    monkeypatch.setenv("FREELLMPOOL_CONFIG_FILE", str(config))
    monkeypatch.setenv("FREELLMPOOL_KEYS_PATH", str(inventory))
    monkeypatch.setattr("freellmpool.cli._load_or_sync_external_catalog", lambda: [])
    monkeypatch.setattr(
        "freellmpool.catalog.discover_openai_models",
        lambda base_url, api_key=None, timeout=10.0: ["model-a", "model-b"],
    )
    answers = iter(["y", "https://api.example.test/v1", "", "2", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert main(["keys", "add", "Example", "--value", "secret"]) == 0

    assert 'id = "example"' in user_catalog.read_text()
    assert 'name = "model-b"' in user_catalog.read_text()
    assert 'EXAMPLE_API_KEY = "secret"' in config.read_text()


def test_cli_providers_health_smoke(monkeypatch, capsys):
    from freellmpool.cli import main

    monkeypatch.setattr(
        "freellmpool.cli.cmd_providers_health",
        lambda args: print("health smoke") or 0,
    )
    assert main(["providers", "health"]) == 0
    assert "health smoke" in capsys.readouterr().out


def test_dashboard_contains_capacity(monkeypatch):
    from freellmpool.models import Model, Provider
    from freellmpool.proxy import _dashboard_html
    from freellmpool.router import Pool

    provider = Provider(
        id="demo",
        label="Demo",
        adapter="openai",
        base_url="https://example.test/v1",
        auth="none",
        models=(Model("model"),),
    )
    html = _dashboard_html(Pool([provider]))
    assert "healthy providers" in html
    assert "capacity" in html
    assert "demo" in html
