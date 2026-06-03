"""The Pool: provider selection and failover.

A :class:`Pool` holds the configured providers, a quota store, and the
strategy for ordering candidate (provider, model) targets. :meth:`ask` walks
that ordered list, calling each target until one succeeds, recording quota use
and per-day budgets as it goes.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from . import client as _client
from .client import PostFn, default_post
from .config import configured_providers, load_catalog
from .errors import AllProvidersExhausted, NoProvidersConfigured, ProviderHTTPError
from .models import Provider, Reply
from .quota import QuotaStore


@dataclass(frozen=True)
class Target:
    """A concrete (provider, model) pair the router can call."""

    provider: Provider
    model: str
    rpd: int

    @property
    def name(self) -> str:
        return f"{self.provider.id}/{self.model}"


class Pool:
    def __init__(
        self,
        providers: list[Provider],
        *,
        quota: QuotaStore | None = None,
        env: dict[str, str] | None = None,
        post: PostFn = default_post,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ):
        self.providers = providers
        self.quota = quota or QuotaStore()
        self.env = env if env is not None else dict(os.environ)
        self._post = post
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or time.monotonic
        # provider_id -> monotonic time until which to deprioritize after a 429
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_lock = threading.Lock()

    def _mark_cooldown(self, provider_id: str, now: float) -> None:
        until = now + self.cooldown_seconds
        with self._cooldown_lock:
            self._cooldown_until[provider_id] = max(
                self._cooldown_until.get(provider_id, 0.0), until
            )

    def _cooled(self, provider_id: str, now: float) -> bool:
        with self._cooldown_lock:
            return self._cooldown_until.get(provider_id, 0.0) > now

    # ---- construction -------------------------------------------------

    @classmethod
    def from_default_config(
        cls,
        *,
        env: dict[str, str] | None = None,
        quota: QuotaStore | None = None,
        post: PostFn = default_post,
    ) -> Pool:
        env = env if env is not None else dict(os.environ)
        providers = configured_providers(load_catalog(), env)
        return cls(providers, quota=quota, env=env, post=post)

    # ---- candidate ordering -------------------------------------------

    def _all_targets(
        self,
        include: Iterable[str] | None = None,
        model: str | None = None,
    ) -> list[Target]:
        include_set = {p.strip() for p in include} if include else None
        targets: list[Target] = []
        for provider in self.providers:
            if include_set is not None and provider.id not in include_set:
                continue
            for m in provider.models:
                if model is not None and m.name != model:
                    continue
                targets.append(Target(provider, m.name, m.rpd))
        return targets

    def _order(self, targets: list[Target]) -> list[Target]:
        """Least-used-first ordering, so load spreads across free tiers.

        Targets already over their daily budget hint are pushed to the back
        (they may still be tried if everything else fails).
        """

        def sort_key(t: Target) -> tuple[int, int]:
            used = self.quota.used(t.provider.id, t.model)
            over = 1 if (t.rpd > 0 and used >= t.rpd) else 0
            return (over, used)

        return sorted(targets, key=sort_key)

    # ---- the main entrypoint ------------------------------------------

    def ask(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 90.0,
        tools: list | None = None,
        tool_choice=None,
    ) -> Reply:
        """Send ``prompt`` to the first provider that succeeds.

        ``model`` / ``providers`` optionally restrict the candidate set.
        Raises :class:`NoProvidersConfigured` if nothing is usable, or
        :class:`AllProvidersExhausted` if every candidate failed.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(
            messages,
            model=model,
            providers=providers,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            tools=tools,
            tool_choice=tool_choice,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        providers: Iterable[str] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        timeout: float = 90.0,
        tools: list | None = None,
        tool_choice=None,
    ) -> Reply:
        """Like :meth:`ask` but takes raw OpenAI-style ``messages``."""
        if not self.providers:
            raise NoProvidersConfigured(
                "no provider has an API key set; see .env.example for the env vars"
            )

        targets = self._order(self._all_targets(include=providers, model=model))
        if not targets:
            raise NoProvidersConfigured("no candidate (provider, model) matched the given filters")

        # Providers recently rate-limited (429) are tried last, not skipped — so
        # a transient cooldown never makes a request fail outright.
        now = self._clock()
        available = [t for t in targets if not self._cooled(t.provider.id, now)]
        cooled = [t for t in targets if self._cooled(t.provider.id, now)]
        sequence = available + cooled

        attempts: list[tuple[str, str]] = []
        rate_limited: set[str] = set()  # providers that 429'd during THIS request
        for target in sequence:
            if target.provider.id in rate_limited:
                # Already 429'd this request — don't waste calls on its other models.
                attempts.append((target.name, "skipped (provider rate-limited this request)"))
                continue
            api_key = target.provider.api_key(self.env)
            if api_key is None and not target.provider.keyless:  # pragma: no cover
                attempts.append((target.name, "missing api key"))
                continue
            try:
                reply = _client.call(
                    target.provider,
                    target.model,
                    messages,
                    api_key=api_key,
                    env=self.env,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                    tools=tools,
                    tool_choice=tool_choice,
                    post=self._post,
                )
            except ProviderHTTPError as exc:
                if exc.status == 429:
                    self._mark_cooldown(target.provider.id, now)
                    rate_limited.add(target.provider.id)
                attempts.append((target.name, str(exc)))
                continue
            except Exception as exc:  # network error, etc. — try the next one
                attempts.append((target.name, f"{type(exc).__name__}: {exc}"))
                continue

            has_tool_calls = bool(reply.message and reply.message.get("tool_calls"))
            if not reply.text and not has_tool_calls:
                attempts.append((target.name, "empty completion"))
                continue

            self.quota.record(target.provider.id, target.model)
            reply.attempts = len(attempts) + 1
            return reply

        raise AllProvidersExhausted(attempts)
