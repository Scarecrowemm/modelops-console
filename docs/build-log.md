# 开发日志

> 记录这个项目是怎么一步步搭起来的，以及每一步的取舍。
> 不是“事后包装”，是给自己看的进度记录。

## 2026-10-29

**目标**：先把“一次请求 → 一条账单 → 一张看板”跑通。

- 定数据模型：providers / models / model_pricing / tenants / api_keys / requests / evaluations / migrations / lifecycle_events / incidents / alerts。
- 写网关：OpenAI 兼容接口、租户 Key、RPM/TPM、路由、fallback、token 计量。
- 写定价：`effective_from` 版本化价目表，按请求时间取价。
- 写 mock 上游：延迟 + 429/500/504 注入。
- 第一次跑通：一条请求返回 200，`X-Cost` 有值，`requests` 表有记录。
- 写测试：定价、限流、网关鉴权、fallback、429。

**踩坑**：

- SQLite 在 Windows 上会被进程锁住，测试重置数据库时 `PermissionError`；后来给 `reset_db()` 加了重试，并修了 `migration.complete_batch` 没关连接的问题。
- 成本对账一开始有 0.000001 的浮点差；后来统一 `round(..., 6)`。

## 2026-10-30

**目标**：把“运营”补上——生命周期、评估、迁移、事件、看板、日报。

- 生命周期状态机 + 门槛：evaluating→approved、canary→active、active→deprecating、deprecating→offline。
- 评估：20 条 prompt，质量/通过率/P95/每千次成本，质量线 7.5 + 通过率 80%。
- 迁移：40 个租户分 5%/20%/50%/100%，网关按迁移表路由。
- 事件：5 类模板 + Runbook + 复盘样例。
- 看板：6 个 KPI、成本趋势、模型健康、Top 租户、生命周期、迁移、待生效变更、事件。
- 日报/周报：自动生成 Markdown。
- 回放 1,000 条请求，成本对账 0 差异。
- 文档：模型卡、迁移计划、RACI、复盘、JD 对应。

**后来又补的**：

- canary 百分比分流 + 自动升降级（`scripts/canary_check.py`）；
- 告警落库 + Webhook（`app/alerts.py`）；
- 一键 bootstrap、每日任务、GitHub Actions；
- 把 README 改成学生个人项目的语气，补了“设计取舍”和“学习笔记”。

## 2026-10-30 · 第二版

**目标**：把“还没做的”补掉。

- 流式 SSE：抽了 `_prepare()`，普通和流式共用鉴权/限流/路由；`start_stream()` 在第一个 chunk 前可 fallback；`stream_events()` 发 `chat.completion.chunk`，最后发 usage 和 `[DONE]`。
- 真实上游：`prov_real` + `real-chat`，配置 `MODELOPS_REAL_*` 后用 `scripts/enable_real_model.py` 启用；支持 OpenAI 兼容接口和 Ollama。
- Redis 限流：设置 `MODELOPS_REDIS_URL` 切换；连不上自动回退到进程内。
- LLM-as-judge：配置 `MODELOPS_JUDGE_*` 后，评估可用 `--judge`；失败回退模拟分。
- 通知：飞书/企业微信/邮件/通用 Webhook。
- 测试从 27 增加到 32。

**当前状态**：MVP+，32 个测试通过，可以本地跑，也可以每天在 GitHub Actions 里跑一次。

**下一步**：

- 供应商账单对账；
- 多区域与 SLA 记分卡；
- 压测与容量规划。
