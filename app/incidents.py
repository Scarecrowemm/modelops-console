"""Incident templates and closure tracking."""

from __future__ import annotations

from datetime import datetime

from . import db

TEMPLATES = {
    "rate_limit_storm": {
        "severity": "P2",
        "summary": "上游 429 率超过 10%",
        "detection": "429 率 > 10%，持续 5 分钟",
        "mitigation": ["切换备用模型", "对 Top 租户限流", "联系供应商确认配额"],
        "root_cause_hint": "供应商配额调整或流量突增",
        "actions": ["确认供应商配额", "调整路由权重", "通知受影响租户"],
    },
    "upstream_timeout": {
        "severity": "P2",
        "summary": "上游 P95 延迟超过 2 倍基线",
        "detection": "P95 > 2 × 7 日基线，持续 10 分钟",
        "mitigation": ["切备用上游", "降低超时阈值", "暂停非关键任务"],
        "root_cause_hint": "上游容量不足或网络抖动",
        "actions": ["联系供应商", "复盘超时阈值", "更新 Runbook"],
    },
    "cost_spike": {
        "severity": "P3",
        "summary": "单日成本环比超过 20%",
        "detection": "日成本环比 > 20% 或单位请求成本 > 1.5 倍",
        "mitigation": ["定位 Top 租户", "检查长上下文占比", "临时限流"],
        "root_cause_hint": "长上下文请求激增或价格变更",
        "actions": ["核对价目表版本", "给租户发提醒", "增加预算告警"],
    },
    "quality_regression": {
        "severity": "P2",
        "summary": "模型质量回退，通过率下降",
        "detection": "评测通过率环比下降 > 5 个百分点",
        "mitigation": ["回滚模型版本", "切备用模型", "抽样人工复核"],
        "root_cause_hint": "供应商静默更新或提示词变更",
        "actions": ["复跑评测集", "对比版本差异", "更新模型卡"],
    },
    "key_leak": {
        "severity": "P1",
        "summary": "API Key 泄露或异常调用",
        "detection": "单 Key 调用量突增 / 异地 IP / 异常模型组合",
        "mitigation": ["立即吊销 Key", "限制租户", "排查调用来源"],
        "root_cause_hint": "Key 硬编码、仓库泄露或内部流转",
        "actions": ["轮换 Key", "通知租户", "做安全复盘"],
    },
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def open_incident(
    incident_type: str,
    model_id: str | None = None,
    provider_id: str | None = None,
    owner: str = "on-call",
    summary: str | None = None,
) -> dict:
    tpl = TEMPLATES.get(incident_type)
    if not tpl:
        raise ValueError(f"unknown incident type: {incident_type}")
    today = datetime.now().strftime("%Y%m%d")
    row = db.query_one("SELECT COUNT(*) AS n FROM incidents WHERE id LIKE ?", (f"INC-{today}-%",))
    seq = int(row["n"] or 0) + 1
    incident_id = f"INC-{today}-{seq:03d}"
    db.execute(
        """
        INSERT INTO incidents (id, ts, type, severity, model_id, provider_id, status, owner, summary)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (incident_id, _now(), incident_type, tpl["severity"], model_id, provider_id,
         "open", owner, summary or tpl["summary"]),
    )
    return get(incident_id)


def close_incident(incident_id: str, root_cause: str, action_items: str) -> dict:
    db.execute(
        "UPDATE incidents SET status = 'closed', root_cause = ?, action_items = ?, closed_at = ? WHERE id = ?",
        (root_cause, action_items, _now(), incident_id),
    )
    return get(incident_id)


def get(incident_id: str) -> dict:
    row = db.query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not row:
        raise ValueError(f"incident {incident_id} not found")
    return row


def list_incidents(status: str | None = None) -> list[dict]:
    if status:
        return db.query("SELECT * FROM incidents WHERE status = ? ORDER BY ts DESC", (status,))
    return db.query("SELECT * FROM incidents ORDER BY ts DESC")


def templates() -> dict:
    return TEMPLATES
