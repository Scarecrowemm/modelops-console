"""Optional real OpenAI-compatible provider.

Disabled by default. Set the env vars and enable the `real-chat` model with
`scripts/enable_real_model.py`; the gateway then routes that model here.
"""

from __future__ import annotations

import json
import os
import time

import httpx

ENV_KEYS = ("MODELOPS_REAL_BASE_URL", "MODELOPS_REAL_API_KEY", "MODELOPS_REAL_MODEL")


def available() -> bool:
    return all(os.getenv(k, "").strip() for k in ENV_KEYS)


def _config() -> tuple[str, str, str]:
    base = os.getenv("MODELOPS_REAL_BASE_URL", "").rstrip("/")
    key = os.getenv("MODELOPS_REAL_API_KEY", "")
    model = os.getenv("MODELOPS_REAL_MODEL", "")
    if not (base and key and model):
        raise RuntimeError("real provider is not configured")
    return base, key, model


def call(model: dict, messages: list[dict], max_tokens: int = 256):
    from .providers import ProviderError, ProviderResult, estimate_completion_tokens, estimate_prompt_tokens

    try:
        base, key, real_model = _config()
    except RuntimeError as exc:
        raise ProviderError("500", str(exc)) from exc
    started = time.time()
    try:
        response = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": real_model, "messages": messages, "max_tokens": max_tokens},
            timeout=60,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        raise ProviderError("429" if code == 429 else "500", f"real upstream {code}") from exc
    except Exception as exc:
        raise ProviderError("timeout", f"real upstream error: {exc}") from exc

    data = response.json()
    usage = data.get("usage") or {}
    text = data["choices"][0]["message"]["content"]
    return ProviderResult(
        text=text,
        prompt_tokens=int(usage.get("prompt_tokens") or estimate_prompt_tokens(messages)),
        completion_tokens=int(usage.get("completion_tokens") or estimate_completion_tokens(text)),
        latency_ms=int((time.time() - started) * 1000),
        model_id=model["id"],
        provider_id=model["provider_id"],
    )


def stream(model: dict, messages: list[dict], max_tokens: int = 256):
    """Yield text deltas from an OpenAI-compatible SSE stream."""
    from .providers import ProviderError

    try:
        base, key, real_model = _config()
    except RuntimeError as exc:
        raise ProviderError("500", str(exc)) from exc
    try:
        with httpx.stream(
            "POST",
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": real_model, "messages": messages, "max_tokens": max_tokens, "stream": True},
            timeout=60,
        ) as response:
            if response.status_code == 429:
                raise ProviderError("429", "real upstream 429")
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError("timeout", f"real upstream stream error: {exc}") from exc
