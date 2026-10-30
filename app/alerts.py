"""Alert computation, persistence and optional webhook notification."""

from __future__ import annotations

import os
import smtplib
from datetime import date, datetime, timedelta
from email.message import EmailMessage

import httpx

from . import config, db


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _yesterday_cost(day: str) -> float:
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    row = db.query_one("SELECT COALESCE(SUM(cost), 0) AS c FROM requests WHERE ts LIKE ?", (prev + "%",))
    return float(row["c"] or 0)


def compute(day: str, kpis: dict) -> list[dict]:
    """Compute alerts from the current KPI snapshot (no persistence)."""
    out: list[dict] = []
    if kpis["requests"] and kpis["success_rate"] < config.THRESHOLDS["success_rate_min"]:
        out.append({
            "rule": "success_rate", "severity": "P2",
            "message": f"成功率 {kpis['success_rate']:.1%}，低于阈值 {config.THRESHOLDS['success_rate_min']:.0%}",
            "triggered_at": _now(),
        })
    if kpis["requests"] and kpis["rate_limited_ratio"] > config.THRESHOLDS["rate_limited_ratio_max"]:
        out.append({
            "rule": "rate_limit", "severity": "P2",
            "message": f"429 占比 {kpis['rate_limited_ratio']:.1%}，超过阈值 {config.THRESHOLDS['rate_limited_ratio_max']:.0%}",
            "triggered_at": _now(),
        })
    if kpis["requests"] and kpis["p95_latency_ms"] > config.THRESHOLDS["p95_latency_ms_max"]:
        out.append({
            "rule": "p95_latency", "severity": "P3",
            "message": f"P95 {kpis['p95_latency_ms']:.0f}ms，超过阈值 {config.THRESHOLDS['p95_latency_ms_max']}ms",
            "triggered_at": _now(),
        })
    prev = _yesterday_cost(day)
    if prev > 0 and (kpis["cost"] - prev) / prev > config.THRESHOLDS["cost_wow_max"]:
        out.append({
            "rule": "cost_spike", "severity": "P2",
            "message": f"成本环比 +{(kpis['cost'] - prev) / prev:.1%}，昨日 ${prev:.2f} → 今日 ${kpis['cost']:.2f}",
            "triggered_at": _now(),
        })
    free = db.query_one(
        """
        SELECT r.tenant_id, t.name, ROUND(SUM(r.cost), 2) AS cost
        FROM requests r JOIN tenants t ON t.id = r.tenant_id
        WHERE r.ts LIKE ? AND t.tier = 'free'
        GROUP BY r.tenant_id ORDER BY cost DESC LIMIT 1
        """,
        (day + "%",),
    )
    if free and float(free["cost"] or 0) > 5:
        out.append({
            "rule": "free_tier_cost", "severity": "P2",
            "message": f"免费租户 {free['name']} 单日成本 ${free['cost']:.2f}，超过免费额度",
            "triggered_at": _now(),
        })
    return out


def current(day: str, kpis: dict) -> list[dict]:
    """Dynamic alerts first, then persisted open alerts not already covered."""
    dynamic = compute(day, kpis)
    rules = {a["rule"] for a in dynamic}
    persisted = db.query(
        """
        SELECT rule, severity, message, triggered_at FROM alerts
        WHERE status = 'open' AND substr(triggered_at, 1, 10) = ?
        ORDER BY triggered_at DESC
        """,
        (day,),
    )
    return dynamic + [a for a in persisted if a["rule"] not in rules]


def _post(url: str, payload: dict) -> None:
    try:
        httpx.post(url, json=payload, timeout=5)
    except Exception as exc:  # notification must never break the scan
        print(f"[alerts] webhook failed: {exc}")


def _send_email(text: str) -> None:
    host = os.getenv("MODELOPS_SMTP_HOST", "").strip()
    to = os.getenv("MODELOPS_SMTP_TO", "").strip()
    if not host or not to:
        return
    port = int(os.getenv("MODELOPS_SMTP_PORT", "587"))
    user = os.getenv("MODELOPS_SMTP_USER", "")
    password = os.getenv("MODELOPS_SMTP_PASSWORD", "")
    message = EmailMessage()
    message["Subject"] = "[ModelOps] alert"
    message["From"] = os.getenv("MODELOPS_SMTP_FROM", user or "modelops@localhost")
    message["To"] = to
    message.set_content(text)
    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            if port == 587:
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
    except Exception as exc:
        print(f"[alerts] email failed: {exc}")


def notify(alert: dict) -> None:
    text = f"[{alert['severity']}] {alert['rule']}: {alert['message']}"
    generic = os.getenv("MODELOPS_WEBHOOK_URL", "").strip()
    if generic:
        _post(generic, {"text": text, "alert": alert})
    feishu = os.getenv("MODELOPS_FEISHU_WEBHOOK", "").strip()
    if feishu:
        _post(feishu, {"msg_type": "text", "content": {"text": text}})
    wecom = os.getenv("MODELOPS_WECOM_WEBHOOK", "").strip()
    if wecom:
        _post(wecom, {"msgtype": "text", "text": {"content": text}})
    _send_email(text)


def scan(day: str | None = None) -> list[dict]:
    """Persist new alerts for the day and notify. Returns only new alerts."""
    from . import metrics  # local import avoids a module cycle

    day = day or date.today().isoformat()
    kpis = metrics._kpis(day)
    new_alerts = []
    for alert in compute(day, kpis):
        exists = db.query_one(
            """
            SELECT id FROM alerts
            WHERE rule = ? AND status = 'open' AND substr(triggered_at, 1, 10) = ?
            """,
            (alert["rule"], day),
        )
        if exists:
            continue
        db.execute(
            "INSERT INTO alerts (rule, severity, message, triggered_at, status) VALUES (?,?,?,?, 'open')",
            (alert["rule"], alert["severity"], alert["message"], alert["triggered_at"]),
        )
        notify(alert)
        new_alerts.append(alert)
    return new_alerts
