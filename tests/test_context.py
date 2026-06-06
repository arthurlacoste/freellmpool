"""Context-window awareness: estimation, error parsing, and routing behavior."""

from __future__ import annotations

import asyncio

import pytest
from helpers import make_post, openai_body

from freellmpool.context import context_limit_from_error, estimate_input_tokens
from freellmpool.errors import AllProvidersExhausted, ContextWindowExceeded
from freellmpool.models import Model, Provider
from freellmpool.router import Pool


def _provider(pid, host, *models):
    return Provider(
        id=pid,
        label=pid,
        adapter="openai",
        base_url=f"https://{host}/v1",
        auth="none",
        models=tuple(models),
    )


def _ctx_error(message):
    return lambda url, headers, body: (400, {"error": {"message": message}})


# --------------------------------------------------------------------------- #
# Unit: error parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "status,message,expected",
    [
        (
            400,
            "This model's maximum context length is 4096 tokens. However, you "
            "requested 5000 tokens.",
            (True, 4096),
        ),
        (413, "context window of 128,000 tokens exceeded", (True, 128000)),
        (400, "prompt is too long", (True, None)),
        (400, "Please reduce the length of the messages.", (True, None)),
        (400, "invalid 'temperature': must be <= 2", (False, None)),
        (400, "tool description string too long", (False, None)),
        (400, "you requested 5000 tokens", (False, None)),  # not a context phrase
        (500, "maximum context length is 4096 tokens", (False, None)),  # wrong status
    ],
)
def test_context_limit_from_error(status, message, expected):
    assert context_limit_from_error(status, message) == expected


# --------------------------------------------------------------------------- #
# Unit: estimation
# --------------------------------------------------------------------------- #
def test_estimate_counts_string_content():
    assert estimate_input_tokens([{"role": "user", "content": "x" * 100}]) == 25


def test_estimate_handles_multimodal_and_none_and_tools():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "y" * 40}, {"type": "image"}]},
        {"role": "assistant", "content": None},  # must not crash
    ]
    tools = [{"type": "function", "function": {"name": "f"}}]
    est = estimate_input_tokens(messages, tools)
    assert est >= 10  # 40 chars of text + serialized tools, // 4-ish


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def test_all_too_small_raises_context_window_exceeded():
    small = _provider("small", "small.test", Model("m"))
    post = make_post({"small.test": _ctx_error("maximum context length is 4096 tokens")})
    pool = Pool([small], post=post)
    with pytest.raises(ContextWindowExceeded) as ei:
        pool.chat([{"role": "user", "content": "hello"}])
    assert isinstance(ei.value, AllProvidersExhausted)  # back-compat
    assert "tokens" in str(ei.value)
    assert pool._ctx_limits["small/m"][0] == 4096  # learned the limit


def test_declared_context_skips_smaller_routes_to_bigger():
    small = _provider("small", "small.test", Model("s", context=2048))
    big = _provider("big", "big.test", Model("b", context=128000))
    post = make_post({"big.test": (200, openai_body("hi from big"))})  # small would 200 too
    pool = Pool([small, big], post=post)
    # needed = est + max_tokens; ~8000 chars -> est 2000, +1024 = 3024  (>2048, <128000)
    reply = pool.chat([{"role": "user", "content": "w" * 8000}], max_tokens=1024)
    assert reply.provider_id == "big"
    assert all("small.test" not in c["url"] for c in post.calls)  # small never called


def test_learns_from_error_then_skips_on_repeat():
    a = _provider("a", "a.test", Model("a1"))
    post = make_post({"a.test": _ctx_error("maximum context length is 4096 tokens")})
    pool = Pool([a], post=post)
    big_msg = [{"role": "user", "content": "z" * 24000}]  # est 6000, needed ~7024 > 4096
    with pytest.raises(ContextWindowExceeded):
        pool.chat(big_msg)
    assert len(post.calls) == 1 and pool._ctx_limits["a/a1"][0] == 4096
    # Second oversized request: a/a1 is now skipped proactively (not called again).
    with pytest.raises(ContextWindowExceeded):
        pool.chat(big_msg)
    assert len(post.calls) == 1


def test_non_context_400_stays_plain_exhausted():
    p = _provider("p", "p.test", Model("m"))
    post = make_post({"p.test": _ctx_error("invalid 'temperature'")})
    pool = Pool([p], post=post)
    with pytest.raises(AllProvidersExhausted) as ei:
        pool.chat([{"role": "user", "content": "hi"}])
    assert not isinstance(ei.value, ContextWindowExceeded)


def test_mixed_failure_not_reported_as_context():
    a = _provider("a", "a.test", Model("m"))
    b = _provider("b", "b.test", Model("m"))
    post = make_post(
        {
            "a.test": _ctx_error("maximum context length is 4096 tokens"),
            "b.test": lambda u, h, bd: (500, {"error": {"message": "server error"}}),
        }
    )
    pool = Pool([a, b], post=post)
    with pytest.raises(AllProvidersExhausted) as ei:
        pool.chat([{"role": "user", "content": "hi"}])
    assert not isinstance(ei.value, ContextWindowExceeded)  # a 500 also happened


def test_context_plus_429_stays_generic_exhausted():
    # A rate-limited provider might have fit — don't claim the input is too long.
    a = _provider("a", "a.test", Model("m"))
    b = _provider("b", "b.test", Model("m"))
    post = make_post(
        {
            "a.test": _ctx_error("maximum context length is 4096 tokens"),
            "b.test": lambda u, h, bd: (429, {"error": {"message": "rate limited"}}),
        }
    )
    pool = Pool([a, b], post=post)
    with pytest.raises(AllProvidersExhausted) as ei:
        pool.chat([{"role": "user", "content": "hi"}])
    assert not isinstance(ei.value, ContextWindowExceeded)


def test_learned_limit_beats_larger_declared_context():
    # declared 128k, but the provider reveals a real 4k cap -> the tighter wins.
    a = _provider("a", "a.test", Model("m", context=128000))
    post = make_post({"a.test": _ctx_error("maximum context length is 4096 tokens")})
    pool = Pool([a], post=post)
    big = [{"role": "user", "content": "z" * 24000}]  # needed ~7024: < 128000 but > 4096
    with pytest.raises(ContextWindowExceeded):
        pool.chat(big)
    assert pool._ctx_limits["a/m"][0] == 4096
    with pytest.raises(ContextWindowExceeded):
        pool.chat(big)
    assert len(post.calls) == 1  # second request skipped a/m proactively (learned 4k)


def test_config_parses_context_field(tmp_path):
    from freellmpool.config import load_catalog

    path = tmp_path / "providers.toml"
    path.write_text(
        "[[provider]]\n"
        'id = "p"\n'
        'label = "P"\n'
        'adapter = "openai"\n'
        'base_url = "https://p.test/v1"\n'
        'auth = "none"\n'
        'models = [{ name = "m", context = 8192 }, { name = "n" }]\n'
    )
    p = next(pr for pr in load_catalog(path=path) if pr.id == "p")
    assert p.model("m").context == 8192
    assert p.model("n").context is None


def test_async_parity_raises_context_window_exceeded():
    from freellmpool import AsyncPool

    small = _provider("small", "small.test", Model("m"))
    sync = make_post({"small.test": _ctx_error("maximum context length is 4096 tokens")})

    async def apost(url, headers, body, timeout):
        return sync(url, headers, body, timeout)

    async def run():
        async with AsyncPool(Pool([small]), apost=apost) as pool:
            with pytest.raises(ContextWindowExceeded):
                await pool.achat([{"role": "user", "content": "hi"}])

    asyncio.run(run())


def test_proxy_returns_413_and_skips_buffered_fallback():
    import json as _json
    import threading
    import urllib.error
    import urllib.request

    from freellmpool.proxy import serve

    small = _provider("small", "small.test", Model("m"))
    post = make_post({"small.test": _ctx_error("maximum context length is 4096 tokens")})

    def stream_post(url, headers, body, timeout):
        return 400, iter(['{"error":{"message":"maximum context length is 4096 tokens"}}'])

    pool = Pool([small], post=post, stream_post=stream_post)
    httpd = serve(pool, host="127.0.0.1", port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(payload):
        req = urllib.request.Request(
            base + "/v1/chat/completions",
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 (localhost test)
                return resp.status, _json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, _json.load(e)

    try:
        status, body = call({"model": "auto", "messages": [{"role": "user", "content": "hi"}]})
        assert status == 413
        assert body["error"]["type"] == "context_length_exceeded"

        # Streaming path: still 413, and it must NOT fall back to a buffered completion.
        post.calls.clear()
        status, body = call(
            {"model": "auto", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
        )
        assert status == 413
        assert body["error"]["type"] == "context_length_exceeded"
        assert post.calls == []  # no buffered retry
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_streaming_context_error_raises_context_window_exceeded():
    p = _provider("p", "p.test", Model("m"))

    def stream_post(url, headers, body, timeout):
        # non-200 with a context error body (drained by stream_call)
        return 400, iter(['{"error":{"message":"maximum context length is 4096 tokens"}}'])

    pool = Pool([p], stream_post=stream_post)
    gen = pool.stream_chat([{"role": "user", "content": "hi"}])
    with pytest.raises(ContextWindowExceeded):
        next(gen)


def _needs_key(pid, host):
    return Provider(
        id=pid,
        label=pid,
        adapter="openai",
        base_url=f"https://{host}/v1",
        key_env="NEEDKEY",
        models=(Model("m"),),
    )


def test_missing_key_suppresses_context_claim_sync():
    # An unconfigured provider isn't evidence the input is too long -> stay generic.
    needkey = _needs_key("needkey", "needkey.test")
    small = _provider("small", "small.test", Model("m"))
    post = make_post({"small.test": _ctx_error("maximum context length is 4096 tokens")})
    pool = Pool([needkey, small], env={}, post=post)
    with pytest.raises(AllProvidersExhausted) as ei:
        pool.chat([{"role": "user", "content": "hi"}])
    assert not isinstance(ei.value, ContextWindowExceeded)


def test_missing_key_suppresses_context_claim_async():
    from freellmpool import AsyncPool

    needkey = _needs_key("needkey", "needkey.test")
    small = _provider("small", "small.test", Model("m"))
    sync = make_post({"small.test": _ctx_error("maximum context length is 4096 tokens")})

    async def apost(url, headers, body, timeout):
        return sync(url, headers, body, timeout)

    async def run():
        async with AsyncPool(Pool([needkey, small], env={}), apost=apost) as pool:
            with pytest.raises(AllProvidersExhausted) as ei:
                await pool.achat([{"role": "user", "content": "hi"}])
            assert not isinstance(ei.value, ContextWindowExceeded)

    asyncio.run(run())


def test_missing_key_suppresses_context_claim_stream():
    needkey = _needs_key("needkey", "needkey.test")
    small = _provider("small", "small.test", Model("m"))

    def stream_post(url, headers, body, timeout):
        return 400, iter(['{"error":{"message":"maximum context length is 4096 tokens"}}'])

    pool = Pool([needkey, small], env={}, stream_post=stream_post)
    gen = pool.stream_chat([{"role": "user", "content": "hi"}])
    with pytest.raises(AllProvidersExhausted) as ei:
        next(gen)
    assert not isinstance(ei.value, ContextWindowExceeded)


def test_stream_error_drain_is_bounded():
    # An unbounded/huge error body must not be read in full (would hang here).
    from freellmpool.client import stream_call
    from freellmpool.errors import ProviderHTTPError

    consumed = {"n": 0}

    def infinite(url, headers, body, timeout):
        def gen():
            while True:
                consumed["n"] += 1
                yield "x" * 50

        return 400, gen()

    p = _provider("p", "p.test", Model("m"))
    g = stream_call(
        p, "m", [{"role": "user", "content": "hi"}], api_key=None, env={}, stream_post=infinite
    )
    with pytest.raises(ProviderHTTPError) as ei:
        next(g)
    # ~500 bytes / 50 per chunk -> ~10 chunks: a positive, bounded read (not 0, not infinite).
    assert 0 < consumed["n"] <= 20
    assert "x" in str(ei.value)  # the drained prefix reached the error message
