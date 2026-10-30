"""Smoke-test a real OpenAI-compatible endpoint.

This script is optional: the demo runs on mock upstreams. Use it to prove that
the gateway's request shape works against a real model, without sending the
1,000-request replay to a paid API.

Environment:
    OPENAI_BASE_URL   e.g. https://api.siliconflow.cn/v1
    OPENAI_API_KEY    your key
    OPENAI_MODEL      e.g. Qwen/Qwen2.5-7B-Instruct

Usage:
    python scripts/real_smoke.py
"""

from __future__ import annotations

import os
import time

import httpx


def main() -> int:
    base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    key = os.getenv("OPENAI_API_KEY", "")
    model = os.getenv("OPENAI_MODEL", "")
    if not (base and key and model):
        print("Set OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL first.")
        print("Example (Ollama):")
        print("  OPENAI_BASE_URL=http://127.0.0.1:11434/v1")
        print("  OPENAI_API_KEY=ollama")
        print("  OPENAI_MODEL=qwen2.5:7b")
        return 0

    started = time.time()
    response = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "用一句话解释 token 是什么"}],
            "max_tokens": 64,
        },
        timeout=60,
    )
    latency = int((time.time() - started) * 1000)
    response.raise_for_status()
    data = response.json()
    print(f"model={data.get('model')} latency={latency}ms usage={data.get('usage')}")
    print(data["choices"][0]["message"]["content"][:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
