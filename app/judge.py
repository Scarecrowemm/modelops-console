"""Optional LLM-as-judge scoring.

Enabled by setting MODELOPS_JUDGE_BASE_URL / API_KEY / MODEL. If unset (or the
call fails), evaluation falls back to the simulated quality score.
"""

from __future__ import annotations

import os
import re

import httpx

RUBRIC = """你是模型评测员。请根据任务和回答，从准确性、完整性、格式三个维度打分。
1-10 的整数，10 最好。只输出一个数字，不要解释。

任务：{prompt}
回答：{response}
"""


def available() -> bool:
    return all(
        os.getenv(k, "").strip()
        for k in ("MODELOPS_JUDGE_BASE_URL", "MODELOPS_JUDGE_API_KEY", "MODELOPS_JUDGE_MODEL")
    )


def score(prompt: str, response: str) -> float | None:
    if not available():
        return None
    base = os.getenv("MODELOPS_JUDGE_BASE_URL", "").rstrip("/")
    key = os.getenv("MODELOPS_JUDGE_API_KEY", "")
    model = os.getenv("MODELOPS_JUDGE_MODEL", "")
    try:
        result = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": RUBRIC.format(prompt=prompt, response=response)}],
                "max_tokens": 8,
                "temperature": 0,
            },
            timeout=30,
        )
        result.raise_for_status()
        text = result.json()["choices"][0]["message"]["content"]
        match = re.search(r"\b(10|[1-9])\b", text)
        return float(match.group(1)) if match else None
    except Exception:
        return None
