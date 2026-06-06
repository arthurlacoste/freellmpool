"""Metrics-aware routing: fair mode sinks failing targets, fast mode sorts by latency."""

from __future__ import annotations

from helpers import make_post

from freellmpool.router import Pool


def _names(pool, **kw):
    return [t.name for t in pool._order(pool._all_targets(**kw))]


def test_fair_default_is_least_used(providers, env, quota):
    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    order = _names(pool)
    # nothing used yet → stable least-used ordering includes every enabled target
    assert "alpha/alpha-small" in order
    assert "beta/beta-1" in order


def test_fair_default_balances_by_provider_before_model(providers, env, quota):
    quota.record("alpha", "alpha-small", 1)
    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    order = _names(pool, include=["alpha", "beta"])

    assert order.index("beta/beta-1") < order.index("alpha/alpha-big")


def test_legacy_routing_balances_by_model(providers, env, quota):
    quota.record("alpha", "alpha-small", 1)
    pool = Pool(providers, quota=quota, env=env, post=make_post({}), routing="legacy")
    order = _names(pool, include=["alpha", "beta"])

    assert order.index("alpha/alpha-big") < order.index("beta/beta-1")


def test_fair_sinks_a_failing_target(providers, env, quota):
    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    # make beta look broken
    for _ in range(3):
        pool.metrics.record_failure("beta/beta-1", "down")
    order = _names(pool)
    assert order[-1] == "beta/beta-1", order  # failing target pushed to the back


def test_fast_mode_prefers_low_latency(providers, env, quota):
    pool = Pool(providers, quota=quota, env=env, post=make_post({}), routing="fast")
    pool.metrics.record_success("beta/beta-1", 50.0)
    pool.metrics.record_success("alpha/alpha-small", 900.0)
    order = _names(pool)
    assert order.index("beta/beta-1") < order.index("alpha/alpha-small")


def test_invalid_routing_falls_back_to_fair(providers, env, quota):
    pool = Pool(providers, quota=quota, env=env, post=make_post({}), routing="nonsense")
    assert pool.routing == "fair"


def test_chat_records_success_metric(providers, env, quota):
    pool = Pool(providers, quota=quota, env=env, post=make_post({}))
    reply = pool.chat([{"role": "user", "content": "hi"}])
    st = pool.metrics.get(f"{reply.provider_id}/{reply.model}")
    assert st is not None and st.ok == 1


def test_chat_records_failure_metric_on_bad_provider(providers, env, quota):
    # alpha 500s; the pool fails over but should record alpha's failure
    post = make_post({"alpha.test": (500, {"error": "boom"})})
    pool = Pool(providers, quota=quota, env=env, post=post)
    pool.chat([{"role": "user", "content": "hi"}], providers=["alpha", "beta"])
    assert pool.metrics.get("alpha/alpha-small").fail >= 1


def test_client_error_does_not_count_as_health_failure(providers, env, quota):
    # a 400 (bad request / capability) must NOT mark the provider failing — only
    # availability failures (429/5xx/network) do.
    post = make_post({"alpha.test": (400, {"error": "unsupported"})})
    pool = Pool(providers, quota=quota, env=env, post=post)
    pool.chat([{"role": "user", "content": "hi"}], providers=["alpha", "beta"])
    st = pool.metrics.get("alpha/alpha-small")
    assert st is None or st.fail == 0  # 400 didn't poison alpha's health


def test_402_capability_error_not_health_failure(providers, env, quota):
    post = make_post({"alpha.test": (402, {"error": "upgrade required"})})
    pool = Pool(providers, quota=quota, env=env, post=post)
    pool.chat([{"role": "user", "content": "hi"}], providers=["alpha", "beta"])
    st = pool.metrics.get("alpha/alpha-small")
    assert st is None or st.fail == 0
