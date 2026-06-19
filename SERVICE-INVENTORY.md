# Service Inventory

> Updated by the orchestrator after each work unit commit.
> Coder agents MUST read this before implementing to avoid duplicating existing services.

## Services

| Service | File | Responsibility | Key Methods |
| --- | --- | --- | --- |
| `Pool` | `src/freellmpool/router.py` | Provider selection, failover, quota/metrics-aware routing, embeddings, transcription, and stats snapshots. | `ask`, `stream`, `embed`, `transcribe`, `stats_snapshot`, `lifetime_stats` |
| Proxy server | `src/freellmpool/proxy.py` | Standard-library OpenAI-compatible HTTP gateway plus Responses and Anthropic Messages shims. | `serve`, request handlers for `/v1/chat/completions`, `/v1/responses`, `/v1/messages`, `/status` |
| MCP server | `src/freellmpool/mcp_server.py` | Local stdio MCP server exposing free-model ask, panel, second-opinion, battle, recipe, roles, tailnet info, quota-wise, tokenmax, route, model, quota, and stats tools. | `handle_request`, tool handlers, `main` |
| CLI | `src/freellmpool/cli.py` | User-facing command dispatch for ask, proxy, MCP, providers, tokenmax, health, stats, keys, and catalog workflows. | `main` |
| Tokenmax | `src/freellmpool/tokenmax.py` | Fan-out model selection/execution across many free routes and synthesis support. | `select_targets`, `fan_out` |
| Job queue | `src/freellmpool/jobs.py` | Local foreground job queue: append-only JSONL events, replay-safe cancellation, and WU-008 report integration for completed runs. | `JobStore.add`, `JobStore.cancel`, `JobStore.jobs`, `run_pending_jobs` |
| Role presets | `src/freellmpool/roles.py` | CLI ask-role presets that map user intent to routing, token, temperature, and system-prompt defaults without adding a second routing engine. | `valid_roles`, `get_role`, `format_roles` |

## Factories

| Factory | File | Creates | Used By |
| --- | --- | --- | --- |
| `Pool.from_config`-style loaders | `src/freellmpool/config.py`, `src/freellmpool/router.py` | Provider catalog, effective environment, provider/model objects, routing pool inputs. | CLI, proxy, MCP server, tests |

## Persistent State

| State | File | Responsibility |
| --- | --- | --- |
| Quota store | `src/freellmpool/quota.py` | Local per-day usage tracking for provider/model routes. |
| Stats store | `src/freellmpool/stats.py` | Lifetime token and request totals for savings/stat commands. |
| Key inventory | `src/freellmpool/key_inventory.py` | Local provider key inventory used by `freellmpool keys`. |
| Job queue | `src/freellmpool/jobs.py` | Append-only JSONL job log (`jobs.jsonl`) with replay-safe cancel tombstones. |

## Shared Modules

| Module | File | Exports | Used By |
| --- | --- | --- | --- |
| Provider catalog | `src/freellmpool/providers.toml`, `src/freellmpool/catalog.py`, `src/freellmpool/catalog_validation.py` | Provider/model metadata, validation helpers, counts. | Router, CLI, release checks, docs/tests |
| Config | `src/freellmpool/config.py` | Catalog loading, provider configuration, alias resolution, settings. | Router, proxy, CLI, MCP |
| Models/errors | `src/freellmpool/models.py`, `src/freellmpool/errors.py` | Provider/reply dataclasses and project exceptions. | All runtime paths |
| Capability/routing modes | `src/freellmpool/capability.py`, `src/freellmpool/routing_modes.py` | Prompt difficulty scoring, route aliases, routing-mode normalization. | Router, proxy, MCP |
| Observability | `src/freellmpool/metrics.py`, `src/freellmpool/observe.py`, `src/freellmpool/savings.py` | Provider health metrics, event hooks, estimated savings. | Router, proxy status, CLI/MCP stats |

## Established Patterns

- Runtime code stays dependency-light; proxy and MCP server are standard-library servers where practical.
- Provider drift should be handled through catalog updates plus tests rather than hard-coded route assumptions.
- New user-facing routes need CLI/proxy/MCP tests when they affect those surfaces.
- Docs and promotion claims should preserve the caveats: prompts go upstream, provider free tiers drift, and freellmpool does not bypass rate limits.
- Explicit CLI flags beat role defaults; `--routing auto` suppresses role routing and leaves the pool default in control.
