"""FastAPI entry point for ModelOps Console."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from . import config, db, evaluation, gateway, incidents, lifecycle, metrics, migration, reports

app = FastAPI(
    title="ModelOps Console",
    version="0.1.0",
    description="AI 模型运营控制台：网关计量、生命周期、评估、迁移、事件与日报。",
)
app.mount("/static", StaticFiles(directory=str(config.DASHBOARD_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")


class ChatMessage(BaseModel):
    role: str
    content: Any = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    stream: bool | None = None


class TransitionRequest(BaseModel):
    to: str
    reason: str = ""
    actor: str = "ops"


class EvalRequest(BaseModel):
    models: list[str] | None = None
    judge: bool = False


class MigrationPlanRequest(BaseModel):
    from_model: str
    to_model: str
    tenants: list[str] | None = None


class IncidentRequest(BaseModel):
    type: str
    model_id: str | None = None
    provider_id: str | None = None
    owner: str = "on-call"
    summary: str | None = None


class IncidentCloseRequest(BaseModel):
    root_cause: str
    action_items: str


@app.get("/")
def root() -> dict:
    return {"name": "ModelOps Console", "dashboard": "/dashboard", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version, "db": str(config.DB_PATH)}


def _gateway_error_response(exc: gateway.GatewayError, request_id: str) -> JSONResponse:
    headers = {"X-Request-Id": request_id}
    if exc.retry_after:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "type": exc.error_type,
                "message": exc.message,
                "request_id": request_id,
            }
        },
        headers=headers,
    )


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest, authorization: str | None = Header(default=None)):
    request_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    try:
        if req.stream:
            ctx, iterator, first = gateway.start_stream(
                req.model_dump(), authorization, request_id=request_id
            )
            headers = gateway.stream_headers(ctx)
            headers["Cache-Control"] = "no-cache"
            headers["X-Accel-Buffering"] = "no"
            return StreamingResponse(
                gateway.stream_events(ctx, iterator, first),
                media_type="text/event-stream",
                headers=headers,
            )
        body, headers = gateway.handle_chat(req.model_dump(), authorization, request_id=request_id)
        return JSONResponse(content=body, headers=headers)
    except gateway.GatewayError as exc:
        return _gateway_error_response(exc, request_id)


@app.get("/v1/models")
def list_models() -> dict:
    return gateway.list_models()


@app.get("/api/dashboard")
def api_dashboard(day: str | None = Query(default=None)) -> dict:
    return metrics.dashboard(day)


@app.get("/api/models")
def api_models() -> list[dict]:
    return db.query(
        """
        SELECT m.*, p.input_price_per_1k, p.output_price_per_1k, p.currency, p.effective_from
        FROM models m
        LEFT JOIN model_pricing p ON p.model_id = m.id AND p.effective_from = (
            SELECT MAX(effective_from) FROM model_pricing
            WHERE model_id = m.id AND effective_from <= date('now')
        )
        ORDER BY m.provider_id, m.id
        """
    )


@app.get("/api/models/{model_id}/history")
def api_model_history(model_id: str) -> list[dict]:
    return lifecycle.history(model_id)


@app.post("/api/models/{model_id}/transition", dependencies=[Depends(require_admin)])
def api_transition(model_id: str, req: TransitionRequest) -> dict:
    try:
        return lifecycle.transition(model_id, req.to, req.reason, req.actor)
    except lifecycle.LifecycleError as exc:
        raise HTTPException(status_code=409, detail={"message": exc.message, "details": exc.details})


@app.post("/api/evaluations/run", dependencies=[Depends(require_admin)])
def api_run_evaluation(req: EvalRequest) -> dict:
    results = evaluation.run(req.models, use_judge=req.judge)
    report = evaluation.report(results)
    path = config.DOCS_DIR / "evaluation-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return {"results": results, "report_path": str(path), "report": report}


@app.get("/api/evaluations")
def api_evaluations() -> list[dict]:
    return evaluation.latest()


@app.post("/api/migrations/plan", dependencies=[Depends(require_admin)])
def api_plan_migration(req: MigrationPlanRequest) -> dict:
    return migration.plan(req.from_model, req.to_model, req.tenants)


@app.get("/api/migrations")
def api_migrations() -> dict:
    return migration.progress()


@app.post("/api/migrations/batches/{batch}/complete", dependencies=[Depends(require_admin)])
def api_complete_batch(batch: str) -> dict:
    updated = migration.complete_batch(batch)
    return {"updated": updated, "progress": migration.progress()}


@app.post("/api/migrations/batches/{batch}/rollback", dependencies=[Depends(require_admin)])
def api_rollback_batch(batch: str) -> dict:
    updated = migration.rollback_batch(batch)
    return {"updated": updated, "progress": migration.progress()}


@app.get("/api/incidents")
def api_incidents(status: str | None = None) -> list[dict]:
    return incidents.list_incidents(status)


@app.get("/api/incidents/templates")
def api_incident_templates() -> dict:
    return incidents.templates()


@app.post("/api/incidents", dependencies=[Depends(require_admin)])
def api_open_incident(req: IncidentRequest) -> dict:
    try:
        return incidents.open_incident(req.type, req.model_id, req.provider_id, req.owner, req.summary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/incidents/{incident_id}/close", dependencies=[Depends(require_admin)])
def api_close_incident(incident_id: str, req: IncidentCloseRequest) -> dict:
    try:
        return incidents.close_incident(incident_id, req.root_cause, req.action_items)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/reports/daily", dependencies=[Depends(require_admin)])
def api_daily_report(day: str | None = None) -> dict:
    path, content = reports.generate_daily(day)
    return {"path": path, "content": content}


@app.post("/api/reports/weekly", dependencies=[Depends(require_admin)])
def api_weekly_report(day: str | None = None) -> dict:
    path, content = reports.generate_weekly(day)
    return {"path": path, "content": content}


@app.get("/dashboard")
def dashboard_page():
    return FileResponse(config.DASHBOARD_DIR / "index.html")
