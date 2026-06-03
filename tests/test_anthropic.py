"""Anthropic Messages shim: translation + proxy route."""

from __future__ import annotations

import json
import threading
import urllib.request

from helpers import make_post, make_stream_post

from freellmpool.anthropic_shim import (
    estimate_tokens,
    reply_to_message,
    reply_to_sse,
    request_to_chat,
)
from freellmpool.config import resolve_alias
from freellmpool.models import Reply
from freellmpool.router import Pool


def test_claude_models_alias_to_auto():
    assert resolve_alias("claude-sonnet-4-20250514", {}) == "auto"
    assert resolve_alias("claude-3-5-haiku-20241022", {}) == "auto"


def test_request_to_chat_text_and_system():
    body = {
        "model": "claude-3-5-sonnet",
        "max_tokens": 50,
        "system": "be terse",
        "messages": [{"role": "user", "content": "hi"}],
    }
    chat = request_to_chat(body)
    assert chat["messages"][0] == {"role": "system", "content": "be terse"}
    assert chat["messages"][1] == {"role": "user", "content": "hi"}
    assert chat["max_tokens"] == 50


def test_request_to_chat_tools_and_tool_result():
    body = {
        "model": "claude-3-5-sonnet",
        "max_tokens": 10,
        "tools": [{"name": "get_weather", "description": "w", "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "any"},
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "weather?"}]},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "get_weather",
                        "input": {"city": "Paris"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "sunny"}],
            },
        ],
    }
    chat = request_to_chat(body)
    assert chat["tools"][0]["function"]["name"] == "get_weather"
    assert chat["tool_choice"] == "required"
    # assistant tool_use → openai tool_calls
    asst = [m for m in chat["messages"] if m["role"] == "assistant"][0]
    assert asst["tool_calls"][0]["function"]["name"] == "get_weather"
    # tool_result → openai tool message
    tool = [m for m in chat["messages"] if m["role"] == "tool"][0]
    assert tool["tool_call_id"] == "tu_1" and tool["content"] == "sunny"


def test_reply_to_message_text():
    r = Reply(text="hello", provider_id="groq", model="m", raw={})
    msg = reply_to_message(r, "claude-3-5-sonnet")
    assert msg["type"] == "message"
    assert msg["content"][0] == {"type": "text", "text": "hello"}
    assert msg["stop_reason"] == "end_turn"


def test_reply_to_message_tool_use():
    tc = [{"id": "tu_1", "type": "function", "function": {"name": "f", "arguments": '{"x": 1}'}}]
    r = Reply(text="", provider_id="groq", model="m", raw={}, message={"tool_calls": tc})
    msg = reply_to_message(r, "claude-3-5-sonnet")
    assert msg["stop_reason"] == "tool_use"
    block = msg["content"][0]
    assert block["type"] == "tool_use" and block["name"] == "f" and block["input"] == {"x": 1}


def test_reply_to_sse_sequence():
    r = Reply(text="hi", provider_id="groq", model="m", raw={})
    events = list(reply_to_sse(r, "claude-3-5-sonnet"))
    types = [e.split("\n", 1)[0] for e in events]
    assert types[0] == "event: message_start"
    assert "event: content_block_start" in types
    assert "event: content_block_delta" in types
    assert types[-1] == "event: message_stop"


def test_estimate_tokens():
    assert estimate_tokens({"messages": [{"role": "user", "content": "x" * 40}]}) >= 1


def _post(url, payload, headers=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return resp.status, json.load(resp)


def test_proxy_messages_route(providers, env, quota):
    from freellmpool.proxy import serve

    pool = Pool(
        providers, quota=quota, env=env, post=make_post({}), stream_post=make_stream_post({})
    )
    httpd = serve(pool, host="127.0.0.1", port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, body = _post(
            base + "/v1/messages",
            {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 20,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert status == 200
        assert body["type"] == "message"
        assert body["content"][0]["text"] == "ok"
        assert body["role"] == "assistant"
    finally:
        httpd.shutdown()
        httpd.server_close()
