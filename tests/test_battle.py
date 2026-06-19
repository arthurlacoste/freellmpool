from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from helpers import make_post, openai_body

from freellmpool.battle import render_battle_markdown, run_battle
from freellmpool.models import Model, Provider
from freellmpool.proxy import _playground_html, serve
from freellmpool.router import Pool


def _provider(provider_id: str, *models: str) -> Provider:
    return Provider(
        id=provider_id,
        label=provider_id.title(),
        adapter="openai",
        base_url=f"https://{provider_id}.test/v1",
        auth="none",
        models=tuple(Model(model) for model in models),
    )


def test_battle_renders_side_by_side_markdown_with_fake_providers(quota):
    pool = Pool(
        [
            _provider("alpha", "llama-3.1-8b"),
            _provider("beta", "qwen3-32b"),
            _provider("gamma", "mistral-7b"),
        ],
        quota=quota,
        post=make_post({}),
    )

    result = run_battle(pool, "compare release notes")
    out = render_battle_markdown(result)

    assert len(result.answers) == 3
    assert "| model | result |" in out
    assert "`alpha/llama-3.1-8b`" in out
    assert "ok" in out


def test_battle_caps_requested_count_and_runs_fewer_when_needed(quota):
    pool = Pool(
        [_provider("alpha", "llama-3.1-8b"), _provider("beta", "qwen3-32b")],
        quota=quota,
        post=make_post({}),
    )

    result = run_battle(pool, "hi", n=99)

    assert result.requested_count == 99
    assert result.selected_count == 2
    assert result.truncated is True


def test_battle_preserves_per_model_failures(quota):
    pool = Pool(
        [_provider("alpha", "llama-3.1-8b"), _provider("beta", "qwen3-32b")],
        quota=quota,
        post=make_post({"beta.test": (500, {"error": "down"})}),
    )

    result = run_battle(pool, "hi", n=2)
    out = render_battle_markdown(result)

    assert len(result.answers) == 2
    assert len(result.successful_answers) == 1
    assert "failed:" in out
    assert "HTTP 500" in out


def test_battle_synthesize_reuses_panel_synthesis_path(quota):
    providers = [_provider("alpha", "llama-3.1-8b"), _provider("beta", "qwen3-32b")]

    def responder(_url, _headers, body):
        if "Synthesize the single" in body["messages"][0]["content"]:
            return 200, openai_body("best combined answer")
        return 200, openai_body("individual answer")

    pool = Pool(providers, quota=quota, post=make_post({"test": responder}))

    result = run_battle(pool, "hi", n=2, synthesize=True)

    assert result.synthesis is not None
    assert result.synthesis.text == "best combined answer"


def test_cli_battle_prints_markdown_and_warnings(providers, env, quota, monkeypatch, capsys):
    from freellmpool.cli import main

    pool = Pool(providers[:2], quota=quota, env=env, post=make_post({}))
    monkeypatch.setattr("freellmpool.cli.Pool.from_default_config", classmethod(lambda cls: pool))
    monkeypatch.setattr("freellmpool.cli._read_stdin", lambda: "")

    assert main(["battle", "compare", "--models", "99"]) == 0

    captured = capsys.readouterr()
    assert "# freellmpool battle" in captured.out
    assert "| model | result |" in captured.out
    assert "only 2 configured provider" in captured.err
    assert "after requesting 99" in captured.err


def test_playground_html_has_no_external_assets():
    html = _playground_html()

    assert "fetch('/freellmpool/battle'" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()
    assert "<script src" not in html.lower()
    assert "<link" not in html.lower()
    assert "<img" not in html.lower()
    for marker in ("react", "vue", "svelte"):
        assert marker not in html.lower()


def test_cli_playground_prints_existing_proxy_url(providers, env, quota, monkeypatch, capsys):
    from freellmpool.cli import main

    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    httpd = serve(pool, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    monkeypatch.setattr("freellmpool.cli.Pool.from_default_config", lambda: (_ for _ in ()).throw(AssertionError("must not start proxy")))
    try:
        assert main(["playground", "--port", str(port)]) == 0
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert capsys.readouterr().out.strip() == f"http://127.0.0.1:{port}/playground"


def test_cli_playground_uses_configured_proxy_key(providers, env, quota, monkeypatch, capsys):
    from freellmpool.cli import main

    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    httpd = serve(pool, host="127.0.0.1", port=0, api_key="secret")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    monkeypatch.setenv("FREELLMPOOL_PROXY_KEY", "secret")
    try:
        assert main(["playground", "--port", str(port)]) == 0
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert capsys.readouterr().out.strip() == f"http://127.0.0.1:{port}/playground"


def test_cli_playground_rejects_non_playground_service(capsys):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from freellmpool.cli import main

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/healthz":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, _format, *args):
            return

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        assert main(["playground", "--port", str(port)]) == 3
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert "no proxy reachable" in capsys.readouterr().err


def test_proxy_battle_endpoint_requires_auth_and_returns_answers(providers, env, quota):
    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    httpd = serve(pool, host="127.0.0.1", port=0, api_key="secret")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    body = json.dumps(
        {"prompt": "hi", "models": 2, "max_tokens": 64, "routing": "fast", "synthesize": True}
    ).encode()
    try:
        req = urllib.request.Request(
            base + "/freellmpool/battle",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)  # noqa: S310
            raise AssertionError("expected auth failure")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        authed = urllib.request.Request(
            base + "/freellmpool/battle",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
        )
        with urllib.request.urlopen(authed) as resp:  # noqa: S310
            payload = json.load(resp)
        assert {"answers", "synthesis", "truncated", "markdown"}.issubset(payload)
        assert len(payload["answers"]) == 2
        assert payload["max_tokens"] == 64
        assert payload["truncated"] is False
        assert payload["synthesis"]["text"] == "ok"
        assert payload["markdown"].startswith("# freellmpool battle")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_proxy_playground_route_serves_self_contained_html(providers, env, quota):
    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    httpd = serve(pool, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/playground") as resp:  # noqa: S310
            html = resp.read().decode()
        assert "freellmpool playground" in html
        assert "fetch('/freellmpool/battle'" in html
    finally:
        httpd.shutdown()
        httpd.server_close()
