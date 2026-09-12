"""LLM provider chain with a circuit breaker.

All three free tiers speak the OpenAI chat-completions shape (Gemini via its
compatibility endpoint), so this is one request builder and a list, not three
vendor SDKs to make three POSTs.

A provider that rate-limits or errors is taken out of the rotation for a cooldown
rather than retried into the ground. If every provider is open, the caller falls
back to the deterministic baseline. There is no state in which triage returns
nothing.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import httpx

COOLDOWN_SECONDS = 120.0
TIMEOUT_SECONDS = 20.0


@dataclass
class Provider:
    name: str
    env_key: str
    url: str
    model: str
    open_until: float = field(default=0.0)

    @property
    def key(self) -> str | None:
        return os.environ.get(self.env_key)

    @property
    def available(self) -> bool:
        return bool(self.key) and time.monotonic() >= self.open_until

    def trip(self) -> None:
        self.open_until = time.monotonic() + COOLDOWN_SECONDS


# Order is the fallback order. Free tiers, all of them.
CHAIN: list[Provider] = [
    Provider("gemini", "GEMINI_API_KEY",
             "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
             "gemini-2.0-flash"),
    Provider("mistral", "MISTRAL_API_KEY",
             "https://api.mistral.ai/v1/chat/completions",
             "mistral-small-latest"),
    Provider("groq", "GROQ_API_KEY",
             "https://api.groq.com/openai/v1/chat/completions",
             "llama-3.3-70b-versatile"),
]


class AllProvidersDown(RuntimeError):
    pass


def any_available() -> bool:
    return any(p.available for p in CHAIN)


def complete_json(system: str, user: str) -> tuple[dict, str, int]:
    """Ask the chain for a JSON object. Returns (parsed, provider_name, latency_ms).

    Raises AllProvidersDown if every provider is missing a key, cooling down, or
    failing. The caller is expected to fall back to the baseline, not to crash.
    """
    errors: list[str] = []
    for p in CHAIN:
        if not p.available:
            continue
        started = time.monotonic()
        try:
            resp = httpx.post(
                p.url,
                headers={"Authorization": f"Bearer {p.key}"},
                json={
                    "model": p.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.0,  # triage is not a creative task
                    "response_format": {"type": "json_object"},
                },
                timeout=TIMEOUT_SECONDS,
            )
            if resp.status_code in (408, 429) or resp.status_code >= 500:
                p.trip()
                errors.append(f"{p.name}: HTTP {resp.status_code}, cooling down")
                continue
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            latency = int((time.monotonic() - started) * 1000)
            return json.loads(content), p.name, latency
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as exc:
            p.trip()
            errors.append(f"{p.name}: {type(exc).__name__}")

    raise AllProvidersDown("; ".join(errors) or "no provider key configured")
