"""Run the OpenAI SDK against a local freellmpool proxy.

Prereqs:
    pip install freellmpool openai
    export GROQ_API_KEY=...           # or any provider key (see docs/ACCOUNTS.md)
    freellmpool proxy --port 8080       # in another terminal

Then:
    python examples/agent_openai_sdk.py
"""

from __future__ import annotations

import os

from openai import OpenAI


def main() -> None:
    client = OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "http://localhost:8080/v1"),
        api_key="anything",  # freellmpool ignores the key
    )

    resp = client.chat.completions.create(
        model="auto",  # "auto" | "groq" | "groq/llama-3.3-70b-versatile" | ...
        messages=[
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "Name three uses for a load balancer."},
        ],
    )
    print(resp.choices[0].message.content)
    served_by = getattr(resp, "model", "?")
    print(f"\n[served by {served_by}]")


if __name__ == "__main__":
    main()
