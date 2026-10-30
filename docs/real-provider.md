# 接一个真实模型（可选）

这个项目默认用 mock 上游，原因很实际：

- 不花钱：1,000 条回放如果打真实 API，成本不可控。
- 可复现：mock 的延迟、429、500 是可控的，测试才能稳定。
- 不碰数据：不需要把任何真实用户内容发给第三方。

但面试时你可能想说“我至少跑通过一条真实链路”。这里给一条最小路径，不改动主 demo。

## 1. 用 Ollama（本地、免费）

```bash
ollama serve
ollama pull qwen2.5:7b
```

设置环境变量：

```bash
# Windows PowerShell
$env:OPENAI_BASE_URL="http://127.0.0.1:11434/v1"
$env:OPENAI_API_KEY="ollama"
$env:OPENAI_MODEL="qwen2.5:7b"

python scripts/real_smoke.py
```

## 2. 用任意 OpenAI 兼容 API

```bash
$env:OPENAI_BASE_URL="https://api.siliconflow.cn/v1"
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_MODEL="Qwen/Qwen2.5-7B-Instruct"

python scripts/real_smoke.py
```

脚本会打印模型名、延迟、token usage 和回复的前 300 字。它不写数据库，也不影响 mock demo。

## 3. 把真实模型接进网关（代码位置）

现在 `app/providers.py` 的 `call()` 是 mock。要接真实模型，加一个分支即可：

```python
def call_real(model, messages, max_tokens=256):
    base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    key = os.getenv("OPENAI_API_KEY", "")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model["version"], "messages": messages, "max_tokens": max_tokens},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return ProviderResult(
        text=data["choices"][0]["message"]["content"],
        prompt_tokens=data["usage"]["prompt_tokens"],
        completion_tokens=data["usage"]["completion_tokens"],
        latency_ms=...,
        model_id=model["id"],
        provider_id=model["provider_id"],
    )
```

然后在 `models` 表里加一条 `provider_id='prov_real'` 的模型，并把 `call()` 按 `provider_id` 分流。

## 注意

- 不要拿真实 API 跑 `scripts/replay.py --count 1000`，会真扣费。
- 不要把真实用户内容写进 `requests` 表；这个 demo 的表结构默认只存 token 数和成本，不存 prompt 原文。
- 真实 API 的 429/超时行为和 mock 不一样，接上后要重新跑一次压测。
