"""Gateway core: auth -> route -> rate limit -> call -> meter -> bill.

Both the non-streaming (`handle_chat`) and streaming (`start_stream` +
`stream_events`) paths share `_prepare`, so auth/rate-limit/routing cannot
drift between them.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time
import uuid
from datetime import datetime

from . import config, db, pricing, providers, ratelimit


class GatewayError(Exception):
    def __init__(self, status_code: int, error_type: str, message: str, retry_after: int | None = None):
        self.status_code = status_code
        self.error_type = error_type
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _log(
    *,
    request_id: str,
    ts: str,
    tenant_id: str,
    key_id: str | None,
    requested_model: str,
    model_id: str,
    provider_id: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost: float = 0.0,
    latency_ms: int = 0,
    status_code: int = 200,
    error_type: str | None = None,
    route_reason: str = "direct",
    fallback_from: str | None = None,
    cached: int = 0,
) -> None:
    db.execute(
        """
        INSERT INTO requests (
            request_id, ts, tenant_id, key_id, requested_model, model_id, provider_id,
            prompt_tokens, completion_tokens, cost, latency_ms, status_code, error_type,
            route_reason, fallback_from, cached
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            request_id, ts, tenant_id, key_id, requested_model, model_id, provider_id,
            prompt_tokens, completion_tokens, cost, latency_ms, status_code, error_type,
            route_reason, fallback_from, cached,
        ),
    )


def authenticate(authorization: str | None) -> tuple[dict, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise GatewayError(401, "missing_api_key", "Missing Authorization: Bearer <key>")
    key_id = authorization.split(" ", 1)[1].strip()
    row = db.query_one(
        """
        SELECT k.key_id, k.status AS key_status, t.*
        FROM api_keys k JOIN tenants t ON t.id = k.tenant_id
        WHERE k.key_id = ?
        """,
        (key_id,),
    )
    if not row or row["key_status"] != "active":
        raise GatewayError(401, "invalid_api_key", "Invalid or disabled API key")
    return row, key_id


def get_model(model_id: str) -> dict:
    row = db.query_one("SELECT * FROM models WHERE id = ?", (model_id,))
    if not row:
        raise GatewayError(404, "model_not_found", f"Model {model_id!r} not found")
    return row


def _migration_override(tenant_id: str, requested_model: str) -> str | None:
    row = db.query_one(
        """
        SELECT to_model FROM migrations
        WHERE tenant_id = ? AND from_model = ? AND status IN ('pending','in_progress')
        ORDER BY id LIMIT 1
        """,
        (tenant_id, requested_model),
    )
    return row["to_model"] if row else None


def _canary_candidate(model: dict, tenant_id: str) -> dict | None:
    if model["status"] != "active":
        return None
    row = db.query_one(
        """
        SELECT * FROM models
        WHERE provider_id = ? AND status = 'canary' AND canary_percent > 0 AND id != ?
        ORDER BY quality_score DESC LIMIT 1
        """,
        (model["provider_id"], model["id"]),
    )
    if not row:
        return None
    bucket = int(hashlib.sha256(tenant_id.encode("utf-8")).hexdigest(), 16) % 10000 / 10000.0
    return row if bucket < float(row["canary_percent"]) else None


def _ensure_available(model: dict, tenant_id: str, requested_model: str) -> str:
    status = model["status"]
    if status == "active":
        return "direct"
    if status == "canary":
        if _migration_override(tenant_id, requested_model) == model["id"]:
            return "migration"
        raise GatewayError(409, "model_in_canary", f"Model {model['id']} is in canary and not enabled for tenant {tenant_id}")
    raise GatewayError(409, "model_not_available", f"Model {model['id']} status is {status}")


def _prepare(payload: dict, authorization: str | None, request_id: str) -> dict:
    ts = _now()
    tenant, key_id = authenticate(authorization)
    tenant_id = tenant["id"]

    requested_model = str(payload.get("model") or "").strip()
    if not requested_model:
        raise GatewayError(400, "invalid_request", "model is required")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise GatewayError(400, "invalid_request", "messages must be a non-empty array")

    max_tokens = payload.get("max_tokens", config.DEFAULT_MAX_TOKENS)
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        max_tokens = config.DEFAULT_MAX_TOKENS
    max_tokens = min(max_tokens, 4096)

    requested = get_model(requested_model)
    if requested["modality"] == "embedding":
        raise GatewayError(400, "wrong_endpoint", "Use /v1/embeddings for embedding models")

    route_reason = _ensure_available(requested, tenant_id, requested_model)
    actual_model_id = requested_model
    fallback_from: str | None = None

    if route_reason == "direct":
        override = _migration_override(tenant_id, requested_model)
        if override:
            actual_model_id = override
            fallback_from = requested_model
            route_reason = "migration"
        else:
            canary = _canary_candidate(requested, tenant_id)
            if canary:
                actual_model_id = canary["id"]
                fallback_from = requested_model
                route_reason = "canary"

    actual = get_model(actual_model_id)
    if actual["status"] not in ("active", "canary"):
        raise GatewayError(409, "model_not_available", f"Model {actual_model_id} status is {actual['status']}")

    estimated = providers.estimate_prompt_tokens(messages) + max_tokens
    decision = ratelimit.limiter.check(
        tenant_id, int(tenant["rpm_limit"]), int(tenant["tpm_limit"]), estimated
    )
    if not decision.allowed:
        _log(
            request_id=request_id, ts=ts, tenant_id=tenant_id, key_id=key_id,
            requested_model=requested_model, model_id=actual_model_id,
            provider_id=actual["provider_id"], status_code=429,
            error_type=decision.reason, route_reason=route_reason,
            fallback_from=fallback_from,
        )
        raise GatewayError(
            429,
            decision.reason or "rate_limited",
            f"Tenant rate limit exceeded ({decision.reason}); retry in {decision.retry_after}s",
            retry_after=decision.retry_after,
        )

    return {
        "request_id": request_id,
        "ts": ts,
        "tenant": tenant,
        "tenant_id": tenant_id,
        "key_id": key_id,
        "requested_model": requested_model,
        "actual": actual,
        "actual_model_id": actual_model_id,
        "route_reason": route_reason,
        "fallback_from": fallback_from,
        "messages": messages,
        "max_tokens": max_tokens,
        "estimated": estimated,
        "started": time.time(),
    }


def _fail(ctx: dict, message: str, error_type: str = "upstream_error", status: int = 502) -> GatewayError:
    ratelimit.limiter.adjust(ctx["tenant_id"], -ctx["estimated"])
    _log(
        request_id=ctx["request_id"], ts=ctx["ts"], tenant_id=ctx["tenant_id"],
        key_id=ctx["key_id"], requested_model=ctx["requested_model"],
        model_id=ctx["actual_model_id"], provider_id=ctx["actual"]["provider_id"],
        status_code=status, error_type=error_type,
        route_reason=ctx["route_reason"], fallback_from=ctx["fallback_from"],
        latency_ms=int((time.time() - ctx["started"]) * 1000),
    )
    return GatewayError(status, error_type, message)


def _call_with_fallback(ctx: dict) -> tuple[providers.ProviderResult, str, str | None]:
    actual = ctx["actual"]
    try:
        result = providers.call(actual, ctx["messages"], ctx["max_tokens"])
        return result, ctx["route_reason"], ctx["fallback_from"]
    except providers.ProviderError as first_error:
        fallback_id = actual.get("fallback_model")
        if not fallback_id or fallback_id == actual["id"]:
            raise _fail(ctx, f"Upstream {actual['id']} failed: {first_error.error_type}")
        fallback = get_model(fallback_id)
        try:
            result = providers.call(fallback, ctx["messages"], ctx["max_tokens"])
            return result, "fallback", actual["id"]
        except providers.ProviderError as second_error:
            raise _fail(ctx, f"Both {actual['id']} and {fallback_id} failed ({second_error.error_type})")


def handle_chat(payload: dict, authorization: str | None, request_id: str | None = None) -> tuple[dict, dict]:
    request_id = request_id or "chatcmpl-" + uuid.uuid4().hex[:24]
    ctx = _prepare(payload, authorization, request_id)
    result, route_reason, fallback_from = _call_with_fallback(ctx)

    actual_total = result.prompt_tokens + result.completion_tokens
    ratelimit.limiter.adjust(ctx["tenant_id"], actual_total - ctx["estimated"])

    cost = pricing.compute_cost(result.model_id, result.prompt_tokens, result.completion_tokens)
    _log(
        request_id=ctx["request_id"], ts=ctx["ts"], tenant_id=ctx["tenant_id"],
        key_id=ctx["key_id"], requested_model=ctx["requested_model"],
        model_id=result.model_id, provider_id=result.provider_id,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
        cost=cost, latency_ms=result.latency_ms, status_code=200,
        route_reason=route_reason, fallback_from=fallback_from,
    )

    body = {
        "id": ctx["request_id"],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": actual_total,
        },
    }
    headers = {
        "X-Request-Id": ctx["request_id"],
        "X-Model": result.model_id,
        "X-Provider": result.provider_id,
        "X-Cost": f"{cost:.6f}",
        "X-Route-Reason": route_reason,
    }
    if fallback_from:
        headers["X-Fallback-From"] = fallback_from
    return body, headers


def start_stream(payload: dict, authorization: str | None, request_id: str | None = None) -> tuple[dict, object, str]:
    request_id = request_id or "chatcmpl-" + uuid.uuid4().hex[:24]
    ctx = _prepare(payload, authorization, request_id)
    actual = ctx["actual"]

    try:
        iterator = providers.stream_call(actual, ctx["messages"], ctx["max_tokens"])
        first = next(iterator)
        return ctx, iterator, first
    except StopIteration:
        raise _fail(ctx, "Upstream returned an empty stream")
    except providers.ProviderError as first_error:
        fallback_id = actual.get("fallback_model")
        if not fallback_id or fallback_id == actual["id"]:
            raise _fail(ctx, f"Upstream {actual['id']} failed: {first_error.error_type}")
        fallback = get_model(fallback_id)
        try:
            iterator = providers.stream_call(fallback, ctx["messages"], ctx["max_tokens"])
            first = next(iterator)
            ctx["actual"] = fallback
            ctx["actual_model_id"] = fallback_id
            ctx["route_reason"] = "fallback"
            ctx["fallback_from"] = actual["id"]
            return ctx, iterator, first
        except (StopIteration, providers.ProviderError) as second_error:
            raise _fail(ctx, f"Both {actual['id']} and {fallback_id} failed ({second_error})")


def stream_headers(ctx: dict) -> dict:
    headers = {
        "X-Request-Id": ctx["request_id"],
        "X-Model": ctx["actual"]["id"],
        "X-Provider": ctx["actual"]["provider_id"],
        "X-Route-Reason": ctx["route_reason"],
    }
    if ctx["fallback_from"]:
        headers["X-Fallback-From"] = ctx["fallback_from"]
    return headers


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def stream_events(ctx: dict, iterator, first: str):
    request_id = ctx["request_id"]
    model_id = ctx["actual"]["id"]
    created = int(time.time())

    yield _sse({
        "id": request_id, "object": "chat.completion.chunk", "created": created, "model": model_id,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    })

    parts: list[str] = []
    try:
        for chunk in itertools.chain([first], iterator):
            if not chunk:
                continue
            parts.append(chunk)
            yield _sse({
                "id": request_id, "object": "chat.completion.chunk", "created": created, "model": model_id,
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
            })
    except Exception as exc:
        ratelimit.limiter.adjust(ctx["tenant_id"], -ctx["estimated"])
        _log(
            request_id=request_id, ts=ctx["ts"], tenant_id=ctx["tenant_id"],
            key_id=ctx["key_id"], requested_model=ctx["requested_model"],
            model_id=model_id, provider_id=ctx["actual"]["provider_id"],
            status_code=502, error_type="stream_error",
            route_reason=ctx["route_reason"], fallback_from=ctx["fallback_from"],
            latency_ms=int((time.time() - ctx["started"]) * 1000),
        )
        yield _sse({"error": {"type": "stream_error", "message": str(exc)}})
        yield "data: [DONE]\n\n"
        return

    text = "".join(parts)
    prompt_tokens = providers.estimate_prompt_tokens(ctx["messages"])
    completion_tokens = providers.estimate_completion_tokens(text) if text else 0
    total_tokens = prompt_tokens + completion_tokens
    ratelimit.limiter.adjust(ctx["tenant_id"], total_tokens - ctx["estimated"])
    cost = pricing.compute_cost(model_id, prompt_tokens, completion_tokens)
    latency_ms = int((time.time() - ctx["started"]) * 1000)
    _log(
        request_id=request_id, ts=ctx["ts"], tenant_id=ctx["tenant_id"],
        key_id=ctx["key_id"], requested_model=ctx["requested_model"],
        model_id=model_id, provider_id=ctx["actual"]["provider_id"],
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        cost=cost, latency_ms=latency_ms, status_code=200,
        route_reason=ctx["route_reason"], fallback_from=ctx["fallback_from"],
    )
    yield _sse({
        "id": request_id, "object": "chat.completion.chunk", "created": created, "model": model_id,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens},
    })
    yield "data: [DONE]\n\n"


def list_models() -> dict:
    rows = db.query("SELECT id, provider_id, modality FROM models WHERE status IN ('active','canary') ORDER BY id")
    return {
        "object": "list",
        "data": [
            {"id": r["id"], "object": "model", "owned_by": r["provider_id"], "modality": r["modality"]}
            for r in rows
        ],
    }
