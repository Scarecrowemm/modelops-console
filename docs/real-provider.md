# 接一个真实模型（可选）

默认上游是 mock，原因很实际：

- 不花钱：1,000 条回放如果打真实 API，成本不可控。
- 可复现：mock 的延迟、429、500 是可控的，测试才能稳定。
- 不碰数据：不需要把任何内容发给第三方。

但你可以用一条真实链路验证网关的请求格式。代码已经接好了，只是默认关闭。

## 1. 配置环境变量

```bash
# Windows PowerShell
$env:MODELOPS_REAL_BASE_URL="http://127.0.0.1:11434/v1"
$env:MODELOPS_REAL_API_KEY="ollama"
$env:MODELOPS_REAL_MODEL="qwen2.5:7b"
```

也可以用任意 OpenAI 兼容 API：

```bash
$env:MODELOPS_REAL_BASE_URL="https://api.siliconflow.cn/v1"
$env:MODELOPS_REAL_API_KEY="sk-..."
$env:MODELOPS_REAL_MODEL="Qwen/Qwen2.5-7B-Instruct"
```

## 2. 先冒烟

```bash
python scripts/real_smoke.py
```

它会打印模型名、延迟、token usage 和回复前 300 字。

## 3. 在网关里启用

```bash
python scripts/enable_real_model.py
```

这个脚本会：

- 插入 `prov_real` 供应商；
- 插入 `real-chat` 模型（状态 `active`）；
- 插入一条占位价目（$0.50 / $1.50 每 1K，真实价格请自己改）；
- 打印一条 curl 示例。

然后请求时把 `model` 换成 `real-chat`：

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-tenant-001-demo" \
  -H "Content-Type: application/json" \
  -d '{"model":"real-chat","messages":[{"role":"user","content":"你好"}]}'
```

流式也可以：

```bash
curl -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-tenant-001-demo" \
  -H "Content-Type: application/json" \
  -d '{"model":"real-chat","messages":[{"role":"user","content":"你好"}],"stream":true}'
```

## 4. 代码路径

- `app/providers.py` 里，`provider_id == "prov_real"` 的模型会走 `app/real_provider.py`。
- `real_provider.call()` 用 `httpx.post` 调 `/chat/completions`，读 `usage`。
- `real_provider.stream()` 用 `httpx.stream` 解析 SSE，逐个 `delta.content` 返回。
- 真实上游的 429/超时会被转换成 `ProviderError`，网关的 fallback 逻辑照常生效。

## 注意

- 不要拿真实 API 跑 `scripts/replay.py --count 1000`，会真扣费。
- `real-chat` 的价目是占位值，成本看板会按它算；接真实业务前先改 `model_pricing`。
- 真实 API 的 429/超时行为和 mock 不一样，接上后要重新跑一次压测。
- 不要把真实用户内容写进 `requests` 表；这个 demo 默认只存 token 数和成本，不存 prompt 原文。
