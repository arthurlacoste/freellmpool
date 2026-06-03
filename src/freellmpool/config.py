"""Configuration loading: provider catalog + user overrides.

Resolution order for the provider catalog:

1. The packaged ``providers.toml`` (the built-in catalog).
2. A user catalog at ``$FREELLMPOOL_CONFIG`` or
   ``~/.config/freellmpool/providers.toml`` if present. Providers with the same
   ``id`` override the built-ins; new ids are appended.

Only providers whose API key (and any extra env vars) are present in the
environment are returned by :func:`configured_providers`.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from .models import Model, Provider

_PACKAGED_CATALOG = Path(__file__).with_name("providers.toml")

# Common OpenAI / Anthropic model names mapped to a free target, so existing
# code (which hardcodes e.g. "gpt-4o-mini") works against freellmpool unchanged.
# "auto" means "let the pool pick the least-used free provider". Override or add
# your own with env vars, e.g.  FREELLMPOOL_ALIAS_gpt-4o-mini=groq/llama-3.3-70b-versatile
_DEFAULT_ALIASES: dict[str, str] = {
    "gpt-4o-mini": "auto",
    "gpt-4o": "auto",
    "gpt-4.1": "auto",
    "gpt-4.1-mini": "auto",
    "gpt-4.1-nano": "auto",
    "gpt-4-turbo": "auto",
    "gpt-4": "auto",
    "gpt-3.5-turbo": "auto",
    "o1-mini": "auto",
    "o3-mini": "auto",
    "o4-mini": "auto",
    "claude-3-haiku-20240307": "auto",
    "claude-3-5-haiku-latest": "auto",
    "claude-3-5-sonnet-latest": "auto",
    "claude-3-7-sonnet-latest": "auto",
    "claude-3-opus-latest": "auto",
}

_ALIAS_ENV_PREFIX = "FREELLMPOOL_ALIAS_"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def resolve_alias(name: str, env: dict[str, str] | None = None) -> str:
    """Map a well-known model name to its free target. User env overrides win;
    unknown names pass through unchanged."""
    env = env if env is not None else dict(os.environ)
    target = _norm(name)
    for key, value in env.items():
        if key.startswith(_ALIAS_ENV_PREFIX) and _norm(key[len(_ALIAS_ENV_PREFIX) :]) == target:
            return value or name
    return _DEFAULT_ALIASES.get(name, name)


def _user_catalog_path() -> Path | None:
    override = os.environ.get("FREELLMPOOL_CONFIG")
    if override:
        return Path(override).expanduser()
    default = Path.home() / ".config" / "freellmpool" / "providers.toml"
    return default if default.exists() else None


def _parse_catalog(data: dict) -> list[Provider]:
    providers: list[Provider] = []
    for row in data.get("provider", []):
        models = tuple(
            Model(name=m["name"], rpd=int(m.get("rpd", 0))) for m in row.get("models", [])
        )
        providers.append(
            Provider(
                id=row["id"],
                label=row.get("label", row["id"]),
                adapter=row.get("adapter", "openai"),
                base_url=row["base_url"].rstrip("/"),
                key_env=row.get("key_env"),
                auth=row.get("auth", "bearer"),
                key_optional=bool(row.get("key_optional", False)),
                models=models,
                extra_env=tuple(row.get("extra_env", [])),
            )
        )
    return providers


def load_catalog(path: Path | None = None) -> list[Provider]:
    """Load the full provider catalog (built-ins + user overrides)."""
    base_path = path or _PACKAGED_CATALOG
    with base_path.open("rb") as fh:
        providers = _parse_catalog(tomllib.load(fh))

    if path is None:
        user_path = _user_catalog_path()
        if user_path is not None:
            with user_path.open("rb") as fh:
                user_providers = _parse_catalog(tomllib.load(fh))
            by_id = {p.id: p for p in providers}
            for up in user_providers:
                by_id[up.id] = up
            providers = list(by_id.values())

    return providers


def configured_providers(
    catalog: list[Provider] | None = None,
    env: dict[str, str] | None = None,
) -> list[Provider]:
    """Return only providers that have a usable API key in the environment."""
    catalog = catalog if catalog is not None else load_catalog()
    env = env if env is not None else dict(os.environ)
    return [p for p in catalog if p.is_configured(env)]
