from __future__ import annotations

from types import SimpleNamespace

from helpers import make_post, openai_body

from freellmpool.models import Model, Provider
from freellmpool.panel import (
    MAX_MAX_TOKENS,
    MAX_PANEL_COUNT,
    MIN_PANEL_COUNT,
    clamp_max_tokens,
    clamp_panel_count,
    messages_from_prompt,
    render_panel_markdown,
    run_panel,
    select_panel_targets,
)
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


def _target(provider_id: str, model: str):
    return SimpleNamespace(provider=SimpleNamespace(id=provider_id), model=model)


class _RankOnlyPool:
    def __init__(self, targets):
        self.targets = targets

    def rank_targets(self, messages, **kwargs):
        self.last_rank_kwargs = kwargs
        return list(self.targets)


def test_clamps_panel_count_and_max_tokens():
    assert clamp_panel_count(0) == MIN_PANEL_COUNT
    assert clamp_panel_count(999) == MAX_PANEL_COUNT
    assert clamp_panel_count("bad") == 3
    assert clamp_max_tokens(0) == 1
    assert clamp_max_tokens(999999) == MAX_MAX_TOKENS
    assert clamp_max_tokens("bad") == 512


def test_run_panel_returns_structured_answer_records(quota):
    providers = [
        _provider("alpha", "llama-3.1-8b"),
        _provider("beta", "qwen3-32b"),
        _provider("gamma", "mistral-7b"),
    ]
    pool = Pool(providers, quota=quota, post=make_post({}))

    result = run_panel(pool, prompt="compare options", n=2)

    assert len(result.answers) == 2
    assert all(answer.ok for answer in result.answers)
    assert all(answer.provider_id and answer.model and answer.label for answer in result.answers)
    assert all(answer.latency_ms >= 0 for answer in result.answers)
    assert len({answer.family for answer in result.answers}) == 2


def test_run_panel_clamps_max_tokens_sent_to_pool(quota):
    providers = [_provider("alpha", "llama-3.1-8b"), _provider("beta", "qwen3-32b")]
    post = make_post({})
    pool = Pool(providers, quota=quota, post=post)

    result = run_panel(pool, prompt="hi", n=2, max_tokens=999999)

    assert result.max_tokens == MAX_MAX_TOKENS
    assert {call["body"]["max_tokens"] for call in post.calls} == {MAX_MAX_TOKENS}


def test_select_panel_targets_avoids_same_family_when_alternative_exists():
    targets = [
        _target("alpha", "llama-3.1-8b"),
        _target("beta", "llama-3.3-70b"),
        _target("gamma", "qwen3-32b"),
    ]

    picks = select_panel_targets(_RankOnlyPool(targets), messages_from_prompt("hi"), n=2)

    assert [(target.provider.id, target.model) for target in picks] == [
        ("alpha", "llama-3.1-8b"),
        ("gamma", "qwen3-32b"),
    ]


def test_select_panel_targets_uses_distinct_providers_when_only_one_family_exists():
    targets = [
        _target("alpha", "llama-3.1-8b"),
        _target("beta", "llama-3.3-70b"),
        _target("gamma", "llama-4-scout-17b"),
    ]

    picks = select_panel_targets(_RankOnlyPool(targets), messages_from_prompt("hi"), n=2)

    assert [target.provider.id for target in picks] == ["alpha", "beta"]


def test_run_panel_preserves_partial_failures(quota):
    providers = [_provider("alpha", "llama-3.1-8b"), _provider("beta", "qwen3-32b")]
    pool = Pool(providers, quota=quota, post=make_post({"beta.test": (500, {"error": "down"})}))

    result = run_panel(pool, prompt="hi", n=2)

    assert len(result.answers) == 2
    assert [answer.ok for answer in result.answers].count(True) == 1
    assert any(answer.error and "HTTP 500" in answer.error for answer in result.answers)


def test_run_panel_synthesis_failure_is_nonfatal(quota):
    providers = [_provider("alpha", "llama-3.1-8b"), _provider("beta", "qwen3-32b")]

    def responder(url, headers, body):
        if "Synthesize the single" in body["messages"][0]["content"]:
            return 500, {"error": "synthesis down"}
        return 200, openai_body("ok")

    pool = Pool(providers, quota=quota, post=make_post({"test": responder}))

    result = run_panel(pool, prompt="hi", n=2, synthesize=True)

    assert len(result.successful_answers) == 2
    assert result.synthesis is not None
    assert result.synthesis.error and "synthesis down" in result.synthesis.error


def test_run_panel_empty_pool_returns_empty_result(quota):
    pool = Pool([], quota=quota)

    result = run_panel(pool, prompt="hi")

    assert result.answers == ()
    assert result.selected_count == 0


def test_render_panel_markdown_includes_answers_and_synthesis(quota):
    providers = [_provider("alpha", "llama-3.1-8b"), _provider("beta", "qwen3-32b")]
    pool = Pool(providers, quota=quota, post=make_post({}))

    result = run_panel(pool, prompt="hi", n=2, synthesize=True)
    out = render_panel_markdown(result, title="freellmpool second opinion panel")

    assert "freellmpool second opinion panel" in out
    assert out.count("###") == 3
    assert "### synthesis" in out
