# Roadmap

Where freellmpool is going, and why. freellmpool ships user-visible product
features first; reliability work is the support layer that keeps those features
honest. Public commands, MCP tools, and docs stay in sync through the release
checks in `scripts/check_release_ready.py`.

This is a living document -- priorities shift with what users hit. Issues and
PRs against any item are welcome (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

Every item below is judged against three questions:

1. **Does it solve a real free-tier pain?** (caps, degradation, flakiness)
2. **Does it deepen the library / coding-agent / MCP identity?**
3. **Is it honest?** Conservative metrics, opt-in everything, no overclaiming.

## North star

freellmpool is the **free-tier pool as a Python library** -- and the **free
backend for coding agents** (Claude Code, Codex, Cursor, aider, Cline). It's
something you `pip install` and `import`, run as a local proxy, or hand to an
agent over MCP -- not a server you have to operate.

## Already shipped

- **Three API surfaces:** OpenAI Chat Completions, OpenAI Responses (Codex),
  Anthropic Messages (Claude Code) -- plus embeddings and audio transcription
  (Whisper, `/v1/audio/transcriptions`).
- **Keyless first run:** can answer without signup when keyless providers are up;
  add keys to grow capacity.
- **Provider-first fair routing** (+ `spread` / `fast` / `quality` / `legacy` /
  `model` / `model-fast`; `spread` spreads load across whole tiers and is the
  best default for agentic loops), per-provider cooldown on 429, and
  never-truncate context escalation.
- **MCP server** (`freellmpool mcp`) -- free models as a tool for Claude
  Desktop / Cursor / Claude Code.
- **Capacity tools:** `capacity status`, `providers health`, `keys add` /
  `keys checklist`.
- **Honest "estimated cost avoided" metric** (`savings.py`, Claude Opus 4.8
  rates) and cumulative `pool.stats`.
- **Library ergonomics:** sync `Pool` + async `AsyncPool`, `on_event` hooks, a
  plugin system (`register_provider` / `register_adapter`), optional response
  cache.

## Top 10 feature map

Kimi K2.7 Code and MiniMax M3 reviewed this plan on 2026-06-19 and pushed it
toward explicit product features instead of generic infrastructure.

| # | Feature | Work unit |
|---|---|---|
| 1 | First-run init wizard | WU-002 |
| 2 | Agent profiles, including Metaswarm | WU-003 |
| 3 | Roles instead of model IDs | WU-004 |
| 4 | Battle and local playground | WU-005 |
| 5 | Recipe library | WU-007 |
| 6 | Background job queue | WU-009 |
| 7 | Second-opinion everywhere | WU-006 |
| 8 | Tailnet / LAN gateway | WU-001 |
| 9 | Shareable run reports | WU-008 |
| 10 | Quota-wise "use my free quota wisely" mode | WU-010 |

WU-011 exposes the same UX through MCP tools, and WU-012 brings docs and
release checks in line with the shipped commands.

## Milestones

### M1: Tailnet + first-run win

- WU-001 Tailnet gateway mode
- WU-002 Init wizard
- WU-003 Agent profiles (Metaswarm)
- WU-004 Role-based asking
- WU-010 Quota-wise mode

Demo:

```bash
freellmpool init --agent metaswarm --tailnet
freellmpool tailnet serve
freellmpool profile doctor metaswarm
FREELLMPOOL_MODE=wise freellmpool ask --role cheap "summarize this"
```

### M2: Comparison + second opinion

- WU-005 Battle CLI and local playground
- WU-006 Second-opinion everywhere

Demo:

```bash
freellmpool ask --role coder "write a pytest for this function"
freellmpool ask --second-opinion "is this implementation plan sound?"
freellmpool battle "which launch post is strongest?"
freellmpool playground
```

### M3: Workflows that produce artifacts

- WU-007 Recipes
- WU-008 Reports
- WU-009 Jobs

Demo:

```bash
freellmpool recipe run pr-review --input patch.diff
freellmpool jobs add --recipe repo-summary --path src/freellmpool
freellmpool jobs run
freellmpool report last --html --open
```

### M4: Agent-native UX + docs/release readiness

- WU-011 MCP UX tools
- WU-012 Docs and release readiness

Demo: Claude Desktop/Cursor/Claude Code call `free_llm_recipe`, `free_llm_battle`,
`free_llm_second_opinion`, `free_llm_quota_wise`, and `free_llm_tailnet_info`
directly through MCP.

## Product direction

The Top 10 feature map above is the release plan. The themes below are the
longer product direction that shaped it and points beyond it.

### Now -- flagship work

**Degradation-aware, quality-tiered routing.** Free tiers' strongest models have
the smallest daily caps, so a naive pool gets weaker as the day fills. Route by
*prompt difficulty*: send hard prompts to the best high-cap model still
available, trivial ones to fast/cheap models -- so effective quality stays high
for longer. Starts with cheap heuristics (length, code blocks, reasoning cues),
with a tiny optional classifier later. Extends the existing `_order()` +
`Metrics` + `QuotaStore`.

**Quota pacing (all-day budget routing).** Spread consumption so you don't burn
your best models by noon. Aware of each model's RPD/TPD, it reserves headroom
and paces toward the UTC-midnight reset, so the pool stays steady across a full
day. Pairs with quality-tiered routing.

**Free-first, explicit paid fallback.** When every free tier is exhausted or
failing, optionally fall back to the user's *own* paid key so production never
hard-fails. Free-first, paid safety net, opt-in, and explicit; it never dilutes
the free-by-default experience and never routes silently to paid providers.
(Tracked as Quota-wise mode in the feature map and hardened in the addendum
below.)

**Tool-call & structured-output fidelity across providers.** Coding agents live
or die on tool calls surviving a failover between heterogeneous providers
(OpenAI / Anthropic / Gemini shapes). Harden and test that translation, and add
a structured-output mode that validates JSON and retries/repairs (or routes to
models known-good at JSON).

**Visual & observability layer.** `freellmpool top` -- a terminal live view:
per-provider tokens/sec and failover as it happens (fed by `on_event` +
`Metrics`). A zero-dependency shareable **SVG summary** (tokens served,
estimated cost avoided, TPS leaderboard). Persist cumulative stats across runs
so the avoided-cost / tokens-pooled number grows over time (and can drive a
README badge).

### Next -- deepen the identity

**Declarative per-call routing knobs.**
`pool.ask(prompt, quality="best"|"fast"|"cheap", max_latency=..., min_context=...,
prefer=[...])` -- give library users direct, per-request control over routing.

**Richer MCP toolbox.** Beyond "ask": `list_models`,
`cheapest_capable_model`, `route_info`, and an ensemble / second-opinion tool
that asks several free models and compares or synthesizes.

**Agent profiles + a preflight doctor.** Per-agent tuned routing (e.g. map a
coding agent's small/fast model to the fast tier and its main model to the
quality tier) and `freellmpool code <agent> --check` to verify tool-calls /
context / streaming work against the current pool before you start.

**Smarter, persistent response cache.** Make the cache persistent and add
exact-prompt (and optional semantic) hits. On free tiers every cache hit is
reclaimed quota -- this directly extends daily capacity.

**Multimodal.** Vision input, and keyless image generation via a keyless
provider -- a free image surface alongside text.

### Later -- trust, observability, and parity-worth-having

- **Routing transparency headers** (`X-Routed-Via`, `X-Fallback-Attempts`) and
  an `on_event` -> OpenTelemetry / JSONL exporter.
- **Multiple keys per provider, for failover only, when the user brings their
  own.** Pooling across different providers is legitimate; stacking multiple
  accounts on a single provider may violate that provider's terms -- that's the
  user's call, and freellmpool won't market it as limit-circumvention. This is
  governed by the No rate-limit bypass policy below.
- **Optional encrypted key storage** at rest, for proxy/server deployments.
- **Speculative / hedged requests** for latency-critical calls (opt-in; spends
  extra quota for lower tail latency).

## Kimi/M3 Top-10 Planning Addendum

*Kimi/M3 Top-10 Planning Addendum, 2026-06-19, as adopted by this project.*

### What was adopted

- Keep the approved work-unit structure. Closed WUs are treated as shipped
  slices; the addendum guides dependent WUs, docs, and follow-up hardening.
- Keep `second-opinion` as a role name only after WU-006 provides the panel helper.
- Keep `panel.py` focused on provider/model/latency/text/error records. Report
  and cost-class enrichment belongs in WU-008 `RunRecord` artifacts.
- Keep the stdlib-first constraint. None of these refinements authorize a new
  runtime dependency.

### Fresh reconciliation, 2026-06-19

After a first round returned `NEEDS_REVISION`, both Kimi K2.7 and MiniMax M3
passed the revised plan. The items below are project requirements, not optional
polish:

1. **Versioned public surfaces.** `init --json`, `recipe list --json`, bundled
   recipe JSON, job JSONL events, and `RunRecord` artifacts all expose a stable
   schema version. Consumers must ignore unknown future keys; tests pin the
   current required keys.
2. **Closed-set contracts.** Role/profile fields use a closed vocabulary:
   `client_kind`, `cost_class` in `{free, metered, paid}`, role names, routing
   modes, and report feature types. Unknown values fail clearly at parse/validation
   boundaries.
3. **Override precedence is explicit.** `--model`, `--providers`, `--routing`,
   and `--max-tokens` win over role/profile/mode defaults, and human-facing output
   shows when an override happened.
4. **One multi-model fan-out primitive.** `panel.py` is used by CLI, MCP,
   `battle`, recipes, reports, and jobs -- not parallel implementations.
5. **Wise-mode guards are policy.** Expensive free-quota operations prompt in
   interactive mode, fail in non-interactive mode unless `--yes` is passed, and
   never fall through to paid providers without an explicit paid selection.
6. **Append-only local state.** Jobs and reports live in JSONL event streams.
   Replay semantics are defined from the stream, not from fragile mutable pointer
   files.
7. **No rate-limit bypass.** The tool never creates accounts, rotates identities,
   shares keys, or evades provider limits. Quota helpers use local counters only.

## Verification standard

All work units in this plan are verified with `PYTHONPATH=src` so tests exercise
the checkout directly:

```bash
PYTHONPATH=src python3 -m pytest tests/test_faq.py tests/test_agents.py tests/test_cli.py
PYTHONPATH=src python3 scripts/check_release_ready.py --skip-build
PYTHONPATH=src python3 scripts/check_release_ready.py
```

The release script now creates an isolated checker environment before running
`twine check`, so host-level packaging-tool drift does not block the full smoke.

## Principles

- **Free-tier-native.** Routing, pacing, and caching are designed *around* caps
  and degradation, not bolted on after.
- **Library-first.** It should embed in your stack (apps, agents, notebooks),
  not just sit beside it.
- **Honest by default.** Conservative cost math, clear caveats, and **opt-in**
  for anything that spends paid quota or leaves the machine (no silent
  telemetry).
