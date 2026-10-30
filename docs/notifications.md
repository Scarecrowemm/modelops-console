# 告警通知

告警由 `app/alerts.py` 计算、落库，并在 `scripts/daily_job.py` 里扫描后发送通知。
看板只展示，不会每次刷新都发消息。

## 支持四个通道（可同时开）

### 1. 通用 Webhook

```bash
$env:MODELOPS_WEBHOOK_URL="https://example.com/hook"
```

发送格式：

```json
{"text": "[P2] cost_spike: 成本环比 +93.1% ...", "alert": {...}}
```

### 2. 飞书机器人

```bash
$env:MODELOPS_FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
```

发送格式：

```json
{"msg_type": "text", "content": {"text": "[P2] ..."}}
```

### 3. 企业微信机器人

```bash
$env:MODELOPS_WECOM_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
```

发送格式：

```json
{"msgtype": "text", "text": {"content": "[P2] ..."}}
```

### 4. 邮件（SMTP）

```bash
$env:MODELOPS_SMTP_HOST="smtp.example.com"
$env:MODELOPS_SMTP_PORT="587"
$env:MODELOPS_SMTP_USER="ops@example.com"
$env:MODELOPS_SMTP_PASSWORD="app-password"
$env:MODELOPS_SMTP_TO="oncall@example.com"
$env:MODELOPS_SMTP_FROM="ops@example.com"
```

端口 587 会走 STARTTLS；其他端口按明文 SMTP 处理（本地测试用）。

## 怎么触发

```bash
python scripts/daily_job.py --count 200
```

它会：

1. 追加当天请求；
2. `alerts.scan()` 计算并落库，只对“当天同一规则还没落库”的告警发通知；
3. 写日报；
4. 检查 canary。

## 注意

- 通知失败不会中断任务，只会打印 `[alerts] ... failed`。
- 不要把 Webhook/邮箱密码写进仓库；用环境变量或本地 `.env`（已忽略）。
- 重复告警按 `rule + 当天` 去重；如果需要“恢复通知”，要再加一张 `alert_events` 表。
