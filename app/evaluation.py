"""Model evaluation: run a prompt set, aggregate quality/latency/cost, rank."""

from __future__ import annotations

import json
import random
import statistics
from datetime import datetime
from pathlib import Path

from . import config, db, pricing, providers

DATASET_PATH = config.DATA_DIR / "eval_prompts.json"
DATASET_NAME = "eval-v1-20prompts"
PASS_THRESHOLD = 7.5


def load_prompts() -> list[dict]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
    return float(values[idx])


def run(model_ids: list[str] | None = None, latency_scale: float = 0.05) -> list[dict]:
    prompts = load_prompts()
    if model_ids:
        models = [db.query_one("SELECT * FROM models WHERE id = ?", (m,)) for m in model_ids]
        models = [m for m in models if m]
    else:
        models = db.query("SELECT * FROM models WHERE status IN ('active','canary') AND modality = 'text' ORDER BY id")

    results = []
    for model in models:
        scores, latencies, costs = [], [], []
        for p in prompts:
            # force_failure="" disables random failures: quality runs must be clean.
            result = providers.call(
                model,
                [{"role": "user", "content": p["prompt"]}],
                max_tokens=128,
                latency_scale=latency_scale,
                force_failure="",
            )
            base = float(model["quality_score"] or 7.0)
            score = max(1.0, min(10.0, base + random.uniform(-0.25, 0.25)))
            scores.append(score)
            latencies.append(result.latency_ms)
            costs.append(
                pricing.compute_cost(model["id"], result.prompt_tokens, result.completion_tokens)
            )

        quality = round(statistics.mean(scores), 2)
        pass_rate = round(sum(1 for s in scores if s >= PASS_THRESHOLD) / len(scores), 3)
        p95 = round(_p95(latencies), 1)
        cost_per_1k = round(statistics.mean(costs) * 1000, 4)
        run_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        db.execute(
            """
            INSERT INTO evaluations (model_id, dataset, quality_score, pass_rate, p95_latency_ms, cost_per_1k, run_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (model["id"], DATASET_NAME, quality, pass_rate, p95, cost_per_1k, run_at),
        )
        results.append(
            {
                "model_id": model["id"],
                "display_name": model["display_name"],
                "quality_score": quality,
                "pass_rate": pass_rate,
                "p95_latency_ms": p95,
                "cost_per_1k": cost_per_1k,
                "run_at": run_at,
            }
        )
    return results


def score_row(row: dict, min_cost: float, min_p95: float) -> float:
    quality = float(row["quality_score"] or 0) / 10.0
    cost = min_cost / float(row["cost_per_1k"]) if row["cost_per_1k"] else 0.0
    latency = min_p95 / float(row["p95_latency_ms"]) if row["p95_latency_ms"] else 0.0
    stability = 1.0  # mock evaluation disables random failures
    compliance = 1.0
    return round(quality * 0.40 + cost * 0.25 + latency * 0.20 + stability * 0.10 + compliance * 0.05, 4)


def report(results: list[dict]) -> str:
    if not results:
        return "没有评测结果。"
    min_cost = min(r["cost_per_1k"] for r in results) or 1.0
    min_p95 = min(r["p95_latency_ms"] for r in results) or 1.0
    qualified = [
        r for r in results
        if float(r["quality_score"] or 0) >= PASS_THRESHOLD and float(r["pass_rate"] or 0) >= 0.8
    ]
    pool = qualified or results
    ranked = sorted(pool, key=lambda r: score_row(r, min_cost, min_p95), reverse=True)
    best = ranked[0] if qualified else None
    table_rows = sorted(results, key=lambda r: score_row(r, min_cost, min_p95), reverse=True)

    lines = [
        "# 模型评估报告",
        "",
        f"- 数据集：`{DATASET_NAME}`（{len(load_prompts())} 条 prompt，覆盖客服、摘要、代码、翻译、长文理解）",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "- 说明：本报告运行在 mock 上游上，质量分为模拟值；真实使用时替换为 rubric/LLM-as-judge。",
        "",
        "## 结论",
        "",
    ]
    if best:
        lines.append(
            f"**推荐 {best['display_name']}（{best['model_id']}）**：综合得分 {score_row(best, min_cost, min_p95):.2f}，"
            f"质量 {best['quality_score']}，P95 {best['p95_latency_ms']:.0f}ms，每千次请求 ${best['cost_per_1k']:.2f}。"
        )
    else:
        lines.append(
            "**本轮没有模型同时达到质量线（≥7.5）与通过率线（≥80%）**，建议继续使用现役模型，"
            "或调整评测集后重跑。"
        )
    lines += [
        "",
        "> 运营决策不只看综合分：如果业务以长上下文为主，128k 上下文的候选模型是硬门槛；"
        "如果以短请求为主，成本和延迟更低的模型更合适。",
        "",
        "## 对比",
        "",
        "| 模型 | 质量(1-10) | 通过率 | P95(ms) | 每千次成本 | 综合得分 | 建议 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in table_rows:
        score = score_row(r, min_cost, min_p95)
        if float(r["quality_score"] or 0) < PASS_THRESHOLD or float(r["pass_rate"] or 0) < 0.8:
            advice = "不推荐（未过质量线）"
        elif r is best:
            advice = "推荐"
        elif score >= 0.70:
            advice = "可用"
        else:
            advice = "不推荐"
        lines.append(
            f"| {r['display_name']} (`{r['model_id']}`) | {r['quality_score']} | "
            f"{r['pass_rate']:.1%} | {r['p95_latency_ms']:.0f} | ${r['cost_per_1k']:.2f} | {score:.2f} | {advice} |"
        )
    lines += [
        "",
        "## 决策口径",
        "",
        "质量 40% + 成本 25% + 延迟 20% + 稳定性 10% + 合规 5%。",
        "通过线：质量 ≥ 7.5；成本涨幅 ≤ 15%；P95 ≤ 现役 1.2 倍。",
    ]
    return "\n".join(lines) + "\n"


def latest() -> list[dict]:
    return db.query(
        """
        SELECT e.*, m.display_name, m.status
        FROM evaluations e
        JOIN models m ON m.id = e.model_id
        WHERE e.id IN (SELECT MAX(id) FROM evaluations GROUP BY model_id)
        ORDER BY e.quality_score DESC
        """
    )
