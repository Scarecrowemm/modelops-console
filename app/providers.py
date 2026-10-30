"""Mock upstream providers with configurable latency and failure injection.

Why mock: an operations demo must be reproducible and free to run. The gateway
code path (routing, retry, fallback, metering, billing) is real; only the
upstream model is simulated. Swap `call()` for an httpx call to a real provider
and the rest of the system is unchanged.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

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


def _last_user_content(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def call(
    model: dict,
    messages: list[dict],
    max_tokens: int = 256,
    latency_scale: float = 1.0,
    force_failure: str | None = None,
) -> ProviderResult:
    model_id = model["id"]
    provider_id = model["provider_id"]

    failure = force_failure
    if failure is None:
        profile = FAILURE_PROFILE.get(provider_id, {})
        roll = random.random()
        acc = 0.0
        for err, prob in profile.items():
            acc += prob
            if roll < acc:
                failure = err
                break
    if failure:
        # A failed upstream may still take time; keep it short so demos stay snappy.
        time.sleep(max(0.0, 0.05 * latency_scale))
        raise ProviderError(failure)

    base = BASE_LATENCY_MS.get(model_id, 500)
    latency = max(20, int(base * latency_scale + random.randint(-80, 120)))
    if latency_scale > 0:
        time.sleep(latency / 1000.0)

    prompt_tokens = estimate_prompt_tokens(messages)
    user = _last_user_content(messages)[:120]
    text = f"【{model['display_name']} 模拟回复】{user}"
    completion_tokens = min(max_tokens, max(20, len(text) // 4))
    return ProviderResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency,
        model_id=model_id,
        provider_id=provider_id,
    )
