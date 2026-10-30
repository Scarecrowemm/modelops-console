"""Daily and weekly operations reports."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from . import config, db, evaluation, metrics


def _recommendations(data: dict) -> list[str]:
    recs: list[str] = []
    k = data["kpis"]
    if k["rate_limited_ratio"] > config.THRESHOLDS["rate_limited_ratio_max"]:
        recs.append(
            f"429 占比 {k['rate_limited_ratio']:.1%}，超过阈值；建议检查供应商配额，并把部分流量切到备用模型。"
        )
    if data["alerts"]:
        rules = {a["rule"] for a in data["alerts"]}
        if "cost_spike" in rules:
            top = data["cost_by_model"][0] if data["cost_by_model"] else None
            extra = f"，主要来自 {top['display_name']}" if top else ""
            recs.append(f"成本异常{extra}；建议按租户下钻长上下文请求占比，并对 Top 租户设置预算提醒。")
        if "p95_latency" in rules:
            slow = max(data["model_health"], key=lambda m: m["p95_latency_ms"] or 0)
            recs.append(
                f"{slow['display_name']} P95 {slow['p95_latency_ms']:.0f}ms；建议排查上游并准备 fallback。"
            )
    if data["incidents"]:
        recs.append(f"有 {len(data['incidents'])} 个未闭环事件，优先处理 P1/P2 并补齐复盘。")
    free_abuse = next(
        (t for t in data["top_tenants"] if t["tier"] == "free" and float(t["cost"] or 0) > 5),
        None,
    )
    if free_abuse:
        recs.append(
            f"免费租户 {free_abuse['name']} 单日成本 ${free_abuse['cost']:.2f}，"
            f"建议核对是否超配额使用，必要时限流或引导升级。"
        )
    if data["migrations"]["total"]:
        m = data["migrations"]
        recs.append(
            f"模型迁移完成率 {m['completion_rate']:.0%}；下一批建议先完成 20% 批次的验证，再推进 50%。"
        )
    if data["upcoming_changes"]:
        c = data["upcoming_changes"][0]
        recs.append(
            f"{c['display_name']} 将于 {c['effective_from']} 调整价格（输入 ${c['input_price_per_1k']}/1K）；建议提前评估替代模型。"
        )
    if not recs:
        recs.append("今日无高优异常；建议复核 Top 10 租户的预算消耗率，并完成一次模型健康巡检。")
    return recs[:4]


def generate_daily(day: str | None = None, out_dir=None) -> tuple[str, str]:
    data = metrics.dashboard(day)
    day = data["date"]
    k = data["kpis"]
    lines = [
        f"# AI 网关运营日报 · {day}",
        "",
        f"> 生成时间：{data['generated_at']} ｜ 数据口径：模拟平台 AIGW，{k['requests']} 次请求",
        "",
        "## 一、今日概览",
        "",
        "| 指标 | 数值 | 阈值 | 状态 |",
        "|---|---:|---:|---|",
        f"| 请求数 | {k['requests']} | — | — |",
        f"| Token 总量 | {k['tokens']:,} | — | — |",
        f"| 成本 | ${k['cost']:.2f} | — | — |",
        f"| 成功率 | {k['success_rate']:.2%} | ≥ {config.THRESHOLDS['success_rate_min']:.0%} | {'✅' if k['success_rate'] >= config.THRESHOLDS['success_rate_min'] else '⚠️'} |",
        f"| 429 占比 | {k['rate_limited_ratio']:.2%} | ≤ {config.THRESHOLDS['rate_limited_ratio_max']:.0%} | {'✅' if k['rate_limited_ratio'] <= config.THRESHOLDS['rate_limited_ratio_max'] else '⚠️'} |",
        f"| P95 延迟 | {k['p95_latency_ms']:.0f} ms | ≤ {config.THRESHOLDS['p95_latency_ms_max']} ms | {'✅' if k['p95_latency_ms'] <= config.THRESHOLDS['p95_latency_ms_max'] else '⚠️'} |",
        "",
        "## 二、成本分析",
        "",
        "| 模型 | 请求数 | 成本 | 占比 |",
        "|---|---:|---:|---:|",
    ]
    for m in data["cost_by_model"]:
        share = m["cost"] / k["cost"] if k["cost"] else 0
        lines.append(f"| {m['display_name']} (`{m['model_id']}`) | {m['requests']} | ${m['cost']:.2f} | {share:.1%} |")
    lines += ["", "**Top 租户**", "", "| 租户 | 等级 | 请求数 | 成本 |", "|---|---|---:|---:|"]
    for t in data["top_tenants"]:
        lines.append(f"| {t['name']} (`{t['tenant_id']}`) | {t['tier']} | {t['requests']} | ${t['cost']:.2f} |")

    lines += ["", "## 三、异常与事件", ""]
    if data["alerts"]:
        lines += ["| 规则 | 级别 | 说明 |", "|---|---|---|"]
        for a in data["alerts"]:
            lines.append(f"| {a['rule']} | {a['severity']} | {a['message']} |")
    else:
        lines.append("无活跃告警。")
    if data["incidents"]:
        lines += ["", "| 事件 | 级别 | 摘要 | 负责人 |", "|---|---|---|---|"]
        for i in data["incidents"]:
            lines.append(f"| {i['id']} | {i['severity']} | {i['summary']} | {i['owner']} |")

    lines += ["", "## 四、模型动态", ""]
    if data["upcoming_changes"]:
        lines += ["| 模型 | 生效日期 | 输入价/1K | 输出价/1K |", "|---|---|---:|---:|"]
        for c in data["upcoming_changes"]:
            lines.append(
                f"| {c['display_name']} (`{c['model_id']}`) | {c['effective_from']} | "
                f"${c['input_price_per_1k']:.2f} | ${c['output_price_per_1k']:.2f} |"
            )
    else:
        lines.append("无待生效的价格变更。")

    lines += ["", "## 五、迁移进度", ""]
    m = data["migrations"]
    lines.append(f"总计 {m['total']} 个租户，已完成 {m['completed']} 个（{m['completion_rate']:.0%}）。")
    lines += ["", "| 批次 | 总数 | 已完成 | 进行中 | 待开始 |", "|---|---:|---:|---:|---:|"]
    for b in m["by_batch"]:
        lines.append(
            f"| {b['batch']} | {b['total']} | {b['completed']} | {b['in_progress']} | {b['pending']} |"
        )

    lines += ["", "## 六、今日建议", ""]
    for idx, rec in enumerate(_recommendations(data), 1):
        lines.append(f"{idx}. {rec}")

    content = "\n".join(lines) + "\n"
    out_dir = out_dir or config.DOCS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"daily-report-{day}.md"
    path.write_text(content, encoding="utf-8")
    return str(path), content


def generate_weekly(day: str | None = None, out_dir=None) -> tuple[str, str]:
    end = date.fromisoformat(day) if day else date.today()
    start = end - timedelta(days=6)
    row = db.query_one(
        """
        SELECT COUNT(*) AS requests,
               COALESCE(SUM(cost), 0) AS cost,
               COALESCE(SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END), 0) AS ok
        FROM requests WHERE substr(ts, 1, 10) BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    )
    requests = int(row["requests"] or 0)
    cost = float(row["cost"] or 0)
    ok = int(row["ok"] or 0)
    evals = evaluation.latest()
    incidents = db.query(
        "SELECT severity, COUNT(*) AS n FROM incidents WHERE substr(ts,1,10) BETWEEN ? AND ? GROUP BY severity",
        (start.isoformat(), end.isoformat()),
    )
    migrations = __import__("app.migration", fromlist=["progress"]).progress()

    lines = [
        f"# AI 网关运营周报 · {start.isoformat()} ~ {end.isoformat()}",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 一、本周概览",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 请求数 | {requests:,} |",
        f"| 成本 | ${cost:.2f} |",
        f"| 成功率 | {ok / requests:.2%} |" if requests else "| 成功率 | — |",
        "",
        "## 二、模型评估",
        "",
        "| 模型 | 质量 | 通过率 | P95 | 每千次成本 |",
        "|---|---:|---:|---:|---:|",
    ]
    for e in evals:
        lines.append(
            f"| {e['display_name']} (`{e['model_id']}`) | {e['quality_score']} | "
            f"{e['pass_rate']:.1%} | {e['p95_latency_ms']:.0f}ms | ${e['cost_per_1k']:.2f} |"
        )
    lines += ["", "## 三、事件统计", ""]
    if incidents:
        lines += ["| 级别 | 数量 |", "|---|---:|"]
        for i in incidents:
            lines.append(f"| {i['severity']} | {i['n']} |")
    else:
        lines.append("本周无事件。")
    lines += [
        "",
        "## 四、迁移进度",
        "",
        f"完成率 {migrations['completion_rate']:.0%}（{migrations['completed']}/{migrations['total']}）。",
        "",
        "## 五、下周动作",
        "",
        "1. 完成 20% 迁移批次的 7 天观察，确认错误率与成本。",
        "2. 对 P95 超阈值的模型做一次上游压测。",
        "3. 复核 Top 10 租户的预算消耗率，提前发送额度提醒。",
    ]
    content = "\n".join(lines) + "\n"
    out_dir = out_dir or config.DOCS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"weekly-report-{end.isoformat()}.md"
    path.write_text(content, encoding="utf-8")
    return str(path), content
