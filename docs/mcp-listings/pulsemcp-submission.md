# PulseMCP Submission Copy

## Server

freellmpool

## Repository

https://github.com/0xzr/freellmpool

## server.json

https://github.com/0xzr/freellmpool/blob/main/server.json

## Description

Local stdio MCP server for pooling free LLM provider tiers. freellmpool exposes
tools for one-shot asks, multi-model panels, agent-facing second-opinion flows,
Markdown battle comparisons, bundled recipes, role presets, Tailscale Tailnet
setup hints, quota-wise local headroom advice, all-model `tokenmax`, routing
explanations, model discovery, quota status, and lifetime free-token stats.

## Tool names

- `free_llm_ask`
- `free_llm_panel`
- `free_llm_second_opinion`
- `free_llm_battle`
- `free_llm_recipe`
- `free_llm_roles`
- `free_llm_tailnet_info`
- `free_llm_quota_wise`
- `tokenmax`
- `free_llm_route`
- `free_llm_models`
- `free_llm_quota`
- `free_llm_stats`

## Install

```json
{
  "mcpServers": {
    "freellmpool": {
      "command": "uvx",
      "args": ["freellmpool", "mcp"]
    }
  }
}
```

## Classification suggestions

- Community
- AI & Machine Learning
- Coding Agents
- Developer Tools

## Maintainer / ownership

GitHub owner: `0xzr`

The repository includes `server.json` using the official MCP server schema and a
PyPI stdio package entry for `freellmpool`.
