"""MCP server: JSON-RPC message handling (no real stdio needed)."""

from __future__ import annotations

from helpers import make_post, openai_body

from freellmpool.mcp_server import handle_message
from freellmpool.router import Pool


def _pool(providers, env, quota, post=None):
    return Pool(providers, quota=quota, env=env, post=post or make_post({}))


def test_initialize(providers, env, quota):
    pool = _pool(providers, env, quota)
    resp = handle_message(
        pool,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        version="0.6.0",
    )
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "freellmpool"
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert "tools" in resp["result"]["capabilities"]


def test_notification_gets_no_reply(providers, env, quota):
    pool = _pool(providers, env, quota)
    assert handle_message(pool, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list(providers, env, quota):
    pool = _pool(providers, env, quota)
    resp = handle_message(pool, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"free_llm_ask", "free_llm_models", "free_llm_quota"}


def test_tools_call_quota(providers, env, quota):
    pool = _pool(providers, env, quota)
    pool.ask("hi")  # record some usage
    resp = handle_message(
        pool,
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "free_llm_quota"}},
    )
    text = resp["result"]["content"][0]["text"]
    assert "usage" in text.lower()
    assert "session:" in text


def test_tools_call_ask(providers, env, quota):
    pool = _pool(providers, env, quota, post=make_post({}))  # returns "ok"
    resp = handle_message(
        pool,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "free_llm_ask", "arguments": {"prompt": "hi"}},
        },
    )
    assert resp["result"]["content"][0]["text"] == "ok"
    assert resp["result"]["isError"] is False


def test_tools_call_ask_missing_prompt(providers, env, quota):
    pool = _pool(providers, env, quota)
    resp = handle_message(
        pool,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "free_llm_ask", "arguments": {}},
        },
    )
    assert resp["result"]["isError"] is True


def test_tools_call_models(providers, env, quota):
    pool = _pool(providers, env, quota)
    resp = handle_message(
        pool,
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "free_llm_models"}},
    )
    text = resp["result"]["content"][0]["text"]
    assert "alpha/alpha-small" in text


def test_unknown_method_errors(providers, env, quota):
    pool = _pool(providers, env, quota)
    resp = handle_message(pool, {"jsonrpc": "2.0", "id": 6, "method": "bogus/method"})
    assert resp["error"]["code"] == -32601


def test_ask_failover_in_tool(providers, env, quota):
    post = make_post({"alpha.test": (500, {}), "beta.test": (200, openai_body("from beta"))})
    pool = _pool(providers, env, quota, post=post)
    resp = handle_message(
        pool,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "free_llm_ask", "arguments": {"prompt": "hi", "provider": "alpha"}},
        },
    )
    # alpha 500s and there's no beta in provider filter → tool error surfaced
    assert resp["result"]["isError"] is True


def test_parse_error_returns_neg32700():
    # serve_stdio emits a JSON-RPC parse error for invalid JSON
    import io

    from freellmpool.mcp_server import serve_stdio

    out = io.StringIO()
    import sys

    old = sys.stdout
    sys.stdin_backup = sys.stdin
    sys.stdin = io.StringIO("{ not json\n")
    sys.stdout = out
    try:
        from freellmpool.router import Pool

        serve_stdio(Pool([], env={}))
    finally:
        sys.stdout = old
        sys.stdin = sys.stdin_backup
    import json

    resp = json.loads(out.getvalue().strip())
    assert resp["error"]["code"] == -32700
    assert resp["id"] is None


def test_invalid_request_missing_method(providers, env, quota):
    from freellmpool.mcp_server import handle_message
    from freellmpool.router import Pool

    pool = Pool(providers, quota=quota, env=env)
    resp = handle_message(pool, {"jsonrpc": "2.0", "id": 5})  # has id, no method
    assert resp["error"]["code"] == -32600
    assert resp["id"] == 5
    # a non-dict is an invalid request with id null
    assert handle_message(pool, 42)["error"]["code"] == -32600


def test_batch_returns_single_json_array(providers, env, quota):
    import io
    import json
    import sys

    from freellmpool.mcp_server import serve_stdio
    from freellmpool.router import Pool

    batch = json.dumps(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no reply
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
    )
    out = io.StringIO()
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(batch + "\n")
    sys.stdout = out
    try:
        serve_stdio(Pool(providers, quota=quota, env=env))
    finally:
        sys.stdin, sys.stdout = old_in, old_out
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1  # one line, one JSON-RPC array (not 2 separate objects)
    arr = json.loads(lines[0])
    assert isinstance(arr, list) and len(arr) == 2  # notification omitted
    assert {r["id"] for r in arr} == {1, 2}
