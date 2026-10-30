"""Versioned pricing and cost calculation."""

from __future__ import annotations

from datetime import date, datetime

from . import db


class PricingError(Exception):
    pass


def get_price(model_id: str, at: datetime | date | None = None) -> dict:
    if at is None:
        at = datetime.now()
    day = at.date().isoformat() if isinstance(at, datetime) else at.isoformat()
    row = db.query_one(
        """
        SELECT model_id, effective_from, input_price_per_1k, output_price_per_1k, currency
        FROM model_pricing
        WHERE model_id = ? AND effective_from <= ?
        ORDER BY effective_from DESC
        LIMIT 1
        """,
        (model_id, day),
    )
    if not row:
        raise PricingError(f"no pricing for {model_id} at {day}")
    return row


def compute_cost(
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    at: datetime | date | None = None,
) -> float:
    p = get_price(model_id, at)
    cost = (
        prompt_tokens / 1000.0 * float(p["input_price_per_1k"])
        + completion_tokens / 1000.0 * float(p["output_price_per_1k"])
    )
    return round(cost, 6)


def upcoming_changes(today: date | None = None) -> list[dict]:
    today = today or date.today()
    return db.query(
        """
        SELECT mp.model_id, m.display_name, mp.effective_from,
               mp.input_price_per_1k, mp.output_price_per_1k, mp.currency
        FROM model_pricing mp
        JOIN models m ON m.id = mp.model_id
        WHERE mp.effective_from > ?
        ORDER BY mp.effective_from
        """,
        (today.isoformat(),),
    )


def current_price_table() -> list[dict]:
    today = date.today().isoformat()
    return db.query(
        """
        SELECT m.id AS model_id, m.display_name, m.status, m.provider_id,
               p.input_price_per_1k, p.output_price_per_1k, p.currency, p.effective_from
        FROM models m
        JOIN model_pricing p ON p.model_id = m.id
        WHERE p.effective_from = (
            SELECT MAX(effective_from) FROM model_pricing
            WHERE model_id = m.id AND effective_from <= ?
        )
        ORDER BY m.provider_id, m.id
        """,
        (today,),
    )
