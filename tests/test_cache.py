"""Response cache + Pool integration."""

from __future__ import annotations

from helpers import make_post

from freellmpool.cache import Cache
from freellmpool.router import Pool


def test_cache_get_put_and_ttl(tmp_path):
    t = [100.0]
    c = Cache(ttl=50.0, path=tmp_path / "c.db", clock=lambda: t[0])
    key = c.make_key([{"role": "user", "content": "hi"}], None, None, 1024, 0.0, None)
    assert c.get(key) is None
    c.put(key, {"text": "cached"})
    assert c.get(key)["text"] == "cached"
    t[0] = 200.0  # 100s later, ttl 50 → expired
    assert c.get(key) is None


def test_pool_uses_cache(providers, env, quota, tmp_path):
    cache = Cache(ttl=999.0, path=tmp_path / "c.db")
    post = make_post({})  # returns "ok", counts calls
    pool = Pool(providers, quota=quota, env=env, post=post, cache=cache)

    r1 = pool.ask("hello")
    assert r1.text == "ok" and not r1.cached
    n_after_first = len(post.calls)

    r2 = pool.ask("hello")  # identical → served from cache, no new provider call
    assert r2.text == "ok" and r2.cached
    assert len(post.calls) == n_after_first  # no extra network call
    assert pool.stats["cache_hits"] == 1


def test_cache_distinguishes_prompts(providers, env, quota, tmp_path):
    cache = Cache(ttl=999.0, path=tmp_path / "c.db")
    post = make_post({})
    pool = Pool(providers, quota=quota, env=env, post=post, cache=cache)
    pool.ask("first")
    pool.ask("second")  # different prompt → not a cache hit
    assert pool.stats["cache_hits"] == 0


def test_cache_disabled_by_default(providers, env, quota):
    post = make_post({})
    pool = Pool(providers, quota=quota, env=env, post=post)  # no cache
    pool.ask("hello")
    pool.ask("hello")
    assert len(post.calls) == 2  # both hit the provider
