"""Mock upstream providers with configurable latency and failure injection.

Why mock: an operations demo must be reproducible and free to run. The gateway
code path (routing, retry, fallback, metering, billing) is real; only the
upstream model is simulated. Swap `call()`/`stream_call()` for an httpx call to
a real provider and the rest of the system is unchanged.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from . import real_provider

BASE_LATENCY_MS = {
    "gpt-4o-mini": 420,
    "gpt-4o": 900,
    "deepseek-chat": 520,
    "deepseek-chat-v3": 480,
    "qwen-plus": 460,
    "glm-4": 500,
    "llama-3.1-8b": 300,
    "text-embedding-3-small": 120,
}

# provider_id -> {error_type: probability}
FAILURE_PROFILE = {
    "prov_openai": {"429": 0.010, "500": 0.005, "timeout": 0.002},
    "prov_domestic": {"429": 0.030, "500": 0.010, "timeout": 0.005},
    "prov_selfhost": {"429": 0.005, "500": 0.020, "timeout": 0.010},
    "prov_real": {"429": 0.000, "500": 0.000, "timeout": 0.000},
}

ERROR_STATUS = {"429": 429, "500": 500, "timeout": 504}


class ProviderError(Exception):
    def __init__(self, error_type: str, message: str | None = None):
        self.error_type = error_type
        self.status_code = ERROR_STATUS.get(error_type, 502)
        super().__init__(message or error_type)


@dataclass
class ProviderResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    model_id: str
    provider_id: str


def estimate_prompt_tokens(messages: list[dict]) -> int:
    chars = 0
    for m in messages:
        chars += len(str(m.get("content", "")))
    return max(1, chars // 4 + 8)


def estimate_completion_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _last_user_content(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def mock_text(model: dict, messages: list[dict]) -> str:
    user = _last_user_content(messages)[:120]
    return f"【{model['display_name']} 模拟回复】{user}"


def _choose_failure(provider_id: str, force_failure: str | None) -> str | None:
    # An empty string means "disable failures" (used by evaluation runs).
    if force_failure is not None:
        return force_failure or None
    profile = FAILURE_PROFILE.get(provider_id, {})
    roll = random.random()
    acc = 0.0
    for err, prob in profile.items():
        acc += prob
        if roll < acc:
            return err
    return None


def call(
    model: dict,
    messages: list[dict],
    max_tokens: int = 256,
    latency_scale: float = 1.0,
    force_failure: str | None = None,
) -> ProviderResult:
    if model["provider_id"] == "prov_real":
        return real_provider.call(model, messages, max_tokens)

    failure = _choose_failure(model["provider_id"], force_failure)
    if failure:
        time.sleep(max(0.0, 0.05 * latency_scale))
        raise ProviderError(failure)

    base = BASE_LATENCY_MS.get(model["id"], 500)
    latency = max(20, int(base * latency_scale + random.randint(-80, 120)))
    if latency_scale > 0:
        time.sleep(latency / 1000.0)

    text = mock_text(model, messages)
    return ProviderResult(
        text=text,
        prompt_tokens=estimate_prompt_tokens(messages),
        completion_tokens=min(max_tokens, estimate_completion_tokens(text)),
        latency_ms=latency,
        model_id=model["id"],
        provider_id=model["provider_id"],
    )


def stream_call(
    model: dict,
    messages: list[dict],
    max_tokens: int = 256,
    latency_scale: float = 0.1,
    force_failure: str | None = None,
):
    """Yield text deltas. Raises ProviderError before the first chunk on failure."""
    if model["provider_id"] == "prov_real":
        yield from real_provider.stream(model, messages, max_tokens)
        return

    failure = _choose_failure(model["provider_id"], force_failure)
    if failure:
        time.sleep(max(0.0, 0.05 * latency_scale))
        raise ProviderError(failure)

    text = mock_text(model, messages)
    # A small delay per chunk makes the stream visible in a browser demo.
    for i in range(0, len(text), 8):
        time.sleep(max(0.0, 0.02 * latency_scale))
        yield text[i:i + 8]
