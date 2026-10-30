# ModelOps Console

一个用于练习 AI 模型运营的模拟平台。包含 OpenAI 兼容网关、模型生命周期、成本看板、租户迁移和告警。

上游模型是模拟的，租户和请求也是模拟数据。网关、限流、路由、计量、迁移和告警的逻辑是真实实现的。

[![tests](https://github.com/Scarecrowemm/modelops-console/actions/workflows/ci.yml/badge.svg)](https://github.com/Scarecrowemm/modelops-console/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Scarecrowemm/modelops-console)](https://github.com/Scarecrowemm/modelops-console/releases)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

![dashboard](docs/screenshots/dashboard.png)

![demo](docs/screenshots/demo.gif)

## 为什么做

在准备 AI 模型运营岗位的面试。JD 里常写“模型上下架、成本监控、用户迁移、跨团队闭环”，只看描述没什么感觉，就做了一个能跑的小平台，把流程走一遍。

## 功能

- OpenAI 兼容 `/v1/chat/completions`，支持 SSE 流式
- 按租户做 RPM/TPM 限流，可以切 Redis
- 直连、canary 比例分流、迁移路由和失败 fallback
- 按版本化价目表计算 token 成本
- 模型生命周期：跟踪、评估、灰度、上线、下线
- 40 个租户分批迁移，支持回滚
- 调用、成本、延迟看板，日报和周报
- 告警落库，支持飞书、企业微信、邮件、Webhook

## 运行

需要 Python 3.10+。

```bash
git clone https://github.com/Scarecrowemm/modelops-console.git
cd modelops-console
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/bootstrap.py
python -m uvicorn app.main:app --port 8080
```

打开 <http://127.0.0.1:8080/dashboard>。

`bootstrap.py` 会建库、回放 1,000 条请求、跑一次评估并生成日报。看板默认看今天；第二天打开如果没数据，跑 `python scripts/daily_job.py --no-replay` 就行。

## 哪些是真的

| 部分 | 说明 |
|---|---|
| 上游模型 | 模拟。延迟和 429/500 可以配置 |
| 租户和请求 | 模拟。200 个租户，1,000 条回放 |
| 网关、限流、路由、计费 | 真实实现，有测试 |
| 生命周期、迁移、告警 | 真实实现，有测试 |
| 质量评估 | 默认模拟分，可以接 LLM-as-judge |

## 可选配置

| 变量 | 作用 |
|---|---|
| `MODELOPS_ADMIN_TOKEN` | 管理接口 token，默认 `admin-demo` |
| `MODELOPS_REAL_BASE_URL` / `_API_KEY` / `_MODEL` | 接一个真实的 OpenAI 兼容模型 |
| `MODELOPS_REDIS_URL` | 用 Redis 限流 |
| `MODELOPS_JUDGE_BASE_URL` / `_API_KEY` / `_MODEL` | 用 LLM-as-judge 打分 |
| `MODELOPS_FEISHU_WEBHOOK` / `MODELOPS_WECOM_WEBHOOK` / `MODELOPS_WEBHOOK_URL` | 告警通知 |
| `MODELOPS_SMTP_HOST` / `_USER` / `_PASSWORD` / `_TO` | 邮件告警 |

具体用法在 [`docs/real-provider.md`](docs/real-provider.md)、[`docs/redis.md`](docs/redis.md)、[`docs/llm-judge.md`](docs/llm-judge.md)、[`docs/notifications.md`](docs/notifications.md)。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/chat/completions` | OpenAI 兼容调用 |
| GET | `/v1/models` | 模型列表 |
| GET | `/api/dashboard?day=YYYY-MM-DD` | 看板数据 |
| POST | `/api/models/{id}/transition` | 生命周期流转（admin） |
| POST | `/api/evaluations/run` | 跑评估（admin） |
| POST | `/api/migrations/plan` | 生成迁移计划（admin） |
| POST | `/api/incidents` | 开事件（admin） |
| POST | `/api/reports/daily` | 生成日报（admin） |

管理接口需要 `X-Admin-Token: admin-demo`（可以用 `MODELOPS_ADMIN_TOKEN` 覆盖）。

## 目录

```
modelops-console/
├── app/
│   ├── gateway.py         # 鉴权、限流、路由、fallback、计量
│   ├── providers.py       # mock 上游
│   ├── pricing.py         # 版本化价格与成本
│   ├── lifecycle.py       # 生命周期状态机
│   ├── evaluation.py      # 评估
│   ├── migration.py       # 迁移批次
│   ├── alerts.py          # 告警计算/落库/通知
│   ├── incidents.py       # 事件闭环
│   ├── metrics.py         # 看板指标
│   └── reports.py         # 日报/周报
├── dashboard/index.html   # 运营看板
├── scripts/               # bootstrap、daily_job、replay、canary_check
├── docs/                  # 模型卡、Runbook、迁移计划、设计取舍
├── tests/                 # 32 个测试
└── .github/workflows/     # CI + 每日任务
```

## 测试

```bash
python -m pytest -q
# 32 passed
```

覆盖定价、限流、生命周期、canary、网关（含流式）、告警去重、LLM-as-judge、Redis 回退和成本对账。

## 文档

- 模型卡：[`docs/model-cards/`](docs/model-cards/)
- 事件处理：[`docs/runbook.md`](docs/runbook.md)
- 迁移计划：[`docs/migration-plan.md`](docs/migration-plan.md)
- 设计取舍：[`docs/design-decisions.md`](docs/design-decisions.md)
- 开发日志：[`docs/build-log.md`](docs/build-log.md)
- 面试用 JD 对应：[`docs/jd-mapping.md`](docs/jd-mapping.md)

## 状态

v0.2.0，早期版本，接口可能会改。

还没做：供应商账单对账、多区域、压测和容量规划。

## License

MIT
