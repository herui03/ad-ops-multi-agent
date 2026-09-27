"""FastAPI app: runs, proposals, decisions, recovery, grounded sources, exports, WebSocket events.

Every state change goes through WorkflowRunner, which validates against the durable store.
The WebSocket is read-only: it streams persisted events and refuses commands, so there is no
second approval path.

Demo roles (X-Demo-Role / X-Demo-Actor headers) are self-declared labels, NOT authentication.
They are enforced server-side so the rules are visible and testable, but anyone who can reach the
server can claim any role. Do not expose this server publicly.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from backend.agents.orchestrator import WorkflowRunner
from backend.config import ROOT, Settings, get_settings
from backend.contracts import SAFE_ID, CancelBody, CreateRunBody, DecisionBody
from backend.errors import ApiError, BadRequest, Forbidden, Gone, NotFound, TooLarge
from backend.grounding import get_corpus, resolve_citation
from backend.policy import ROLES, SIM_INTEGRATION

log = logging.getLogger("adops.api")
ACTOR_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,40}$")
MAX_BODY_BYTES = 64 * 1024
DEMO_ROLE_NOTE = ("Demo roles are self-declared request headers, not authentication. They are enforced server-side "
                  "to show the rules, but they do not prove who you are.")


def identity(role: str | None, actor: str | None) -> tuple[str, str]:
    role = (role or "").strip().lower()
    if role not in ROLES:
        raise Forbidden("invalid_role", f"X-Demo-Role must be one of {sorted(ROLES)}")
    actor = (actor or f"{role}-demo").strip()
    if not ACTOR_RE.match(actor):
        raise BadRequest("invalid_actor", "X-Demo-Actor must be 1-40 characters of letters, digits, _ - .")
    return role, actor


def check_id(value: str, what: str) -> str:
    if not SAFE_ID.match(value):
        raise NotFound(f"{what}_not_found", f"{what} not found")
    return value


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection (CSV/Excel), keep the text readable."""
    s = "" if value is None else (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return "'" + s if s.startswith(FORMULA_PREFIXES) else s


def create_app(settings: Settings | None = None, runner: WorkflowRunner | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runner = runner or WorkflowRunner(settings)
        touched = app.state.runner.reconcile_on_startup()
        if touched:
            log.warning("marked %d in-flight run(s) as interrupted after restart", len(touched))
        yield
        if runner is None:
            app.state.runner.close()

    app = FastAPI(title="Ad Ops Multi-Agent (reliability demo)", version="2.0.0", lifespan=lifespan,
                  description="Simulated advertising-operations workflow with a durable human approval gate. "
                              + DEMO_ROLE_NOTE)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url, "http://localhost:5173",
                                                      "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Demo-Role", "X-Demo-Actor"])

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"error": "body_too_large",
                                                          "detail": f"request body over {MAX_BODY_BYTES} bytes"})
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        errors = [{"loc": [str(x) for x in e.get("loc", ())], "type": e.get("type")} for e in exc.errors()[:5]]
        return JSONResponse(status_code=422, content={"error": "invalid_body", "detail": "request body failed "
                                                      "validation", "errors": errors})

    def R() -> WorkflowRunner:
        return app.state.runner

    # ------------------------------------------------------------------ meta
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta():
        p = R().provider
        return {"provider_mode": p.mode, "provider_name": p.name, "provider_label": p.label,
                "integration": SIM_INTEGRATION, "roles": {k: sorted(v) for k, v in ROLES.items()},
                "role_note": DEMO_ROLE_NOTE,
                "limits": {"max_request_chars": settings.max_request_chars,
                           "max_comment_chars": settings.max_comment_chars,
                           "provider_timeout_s": settings.provider_timeout_s,
                           "provider_max_attempts": settings.provider_max_attempts,
                           "max_recoveries": settings.max_recoveries, "max_active_runs": settings.max_active_runs,
                           "high_spend_threshold": settings.high_spend_threshold,
                           "hard_budget_cap": settings.hard_budget_cap},
                "demo_faults_enabled": p.mode == "demo"}

    # ------------------------------------------------------------------ runs
    @app.post("/api/runs", status_code=202)
    def create_run(body: CreateRunBody, x_demo_role: str | None = Header(None),
                   x_demo_actor: str | None = Header(None)):
        role, actor = identity(x_demo_role, x_demo_actor)
        run = R().create_run(body.request, actor=actor, role=role,
                             demo_fault=body.demo_fault.model_dump() if body.demo_fault else None)
        return {"run": run}

    @app.get("/api/runs")
    def list_runs(limit: int = 50):
        return {"runs": R().store.list_runs(max(1, min(limit, 200)))}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return R().run_detail(check_id(run_id, "run"))

    @app.post("/api/runs/{run_id}/decisions")
    def decide(run_id: str, body: DecisionBody, x_demo_role: str | None = Header(None),
               x_demo_actor: str | None = Header(None)):
        role, actor = identity(x_demo_role, x_demo_actor)
        return R().decide(check_id(run_id, "run"), proposal_id=body.proposal_id, revision=body.revision,
                          proposal_sha256=body.proposal_sha256, decision=body.decision, comment=body.comment,
                          changes=body.changes, idempotency_key=body.idempotency_key, actor=actor, role=role)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel(run_id: str, body: CancelBody, x_demo_role: str | None = Header(None),
               x_demo_actor: str | None = Header(None)):
        role, actor = identity(x_demo_role, x_demo_actor)
        if len(body.comment) > settings.max_comment_chars:
            raise TooLarge("comment_too_long", f"comment limit is {settings.max_comment_chars} characters")
        return R().cancel(check_id(run_id, "run"), actor=actor, role=role, idempotency_key=body.idempotency_key,
                          comment=body.comment)

    @app.post("/api/runs/{run_id}/recover", status_code=202)
    def recover(run_id: str, x_demo_role: str | None = Header(None), x_demo_actor: str | None = Header(None)):
        role, actor = identity(x_demo_role, x_demo_actor)
        return R().recover(check_id(run_id, "run"), actor=actor, role=role)

    @app.get("/api/runs/{run_id}/export.json")
    def export_json(run_id: str):
        detail = R().run_detail(check_id(run_id, "run"))
        return Response(content=json.dumps(detail, indent=2, ensure_ascii=False, default=str),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}.json"',
                                 "X-Content-Type-Options": "nosniff"})

    @app.get("/api/runs/{run_id}/export.csv")
    def export_csv(run_id: str):
        d = R().run_detail(check_id(run_id, "run"))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["section", "seq_or_id", "kind", "detail"])
        w.writerow(["run", d["run_id"], d["status"], csv_safe(d["request_text"])])
        for e in d["events"]:
            w.writerow(["event", e["seq"], csv_safe(e["kind"]), csv_safe(e["data"])])
        for p in d["proposals"]:
            w.writerow(["proposal", p["proposal_id"], f"rev {p['revision']} {p['status']}", csv_safe(p["payload"])])
        for dec in d["decisions"]:
            w.writerow(["decision", dec["decision_id"], dec["decision"], csv_safe(dec["comment"])])
        for a in d["actions"]:
            w.writerow(["simulated_action", a["action_id"], a["action_type"], csv_safe(a["amount"])])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"',
                                 "X-Content-Type-Options": "nosniff"})

    # ------------------------------------------------------------------ sources and dashboard
    @app.get("/api/sources")
    def sources():
        return {"documents": get_corpus().docs()}

    @app.get("/api/source")
    def source(chunk_id: str):
        found = resolve_citation(chunk_id)
        if found is None:
            raise NotFound("chunk_not_found", "no corpus chunk with that id")
        return found

    @app.get("/api/dashboard/stats")
    def dashboard():
        s = R().store.stats()
        return {**s, "provider_mode": R().provider.mode,
                "note": "Counts are read from this instance's SQLite store. Amounts are simulated sandbox actions; "
                        "no money was spent and no ad platform was called."}

    # ------------------------------------------------------------------ retired endpoints (explicitly closed)
    @app.api_route("/api/chat", methods=["GET", "POST"])
    def legacy_chat():
        raise Gone("endpoint_removed", "use POST /api/runs")

    @app.api_route("/api/approvals/{approval_id}/decide", methods=["GET", "POST"])
    def legacy_decide(approval_id: str):
        raise Gone("endpoint_removed", "decisions go to POST /api/runs/{run_id}/decisions with proposal id, "
                   "revision, sha256 and an idempotency key")

    @app.websocket("/ws/{legacy_session_id}")
    async def legacy_ws(websocket: WebSocket, legacy_session_id: str):
        await websocket.accept()
        await websocket.send_json({"type": "error", "code": "endpoint_removed", "detail": "use /ws/runs/{run_id}"})
        await websocket.close(code=4410)

    # ------------------------------------------------------------------ websocket (read-only)
    @app.websocket("/ws/runs/{run_id}")
    async def run_events(websocket: WebSocket, run_id: str):
        await websocket.accept()
        runner = R()
        if not SAFE_ID.match(run_id) or runner.store.get_run(run_id) is None:
            await websocket.send_json({"type": "error", "code": "run_not_found", "detail": "run not found"})
            await websocket.close(code=4404)
            return
        detail = await run_in_threadpool(runner.run_detail, run_id)
        last_seq = detail["events"][-1]["seq"] if detail["events"] else 0
        await websocket.send_json({"type": "snapshot", "run": json.loads(json.dumps(detail, default=str))})
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
                except asyncio.TimeoutError:
                    raw = None
                if raw is not None:
                    await websocket.send_json(handle_ws_message(raw, run_id))
                new = runner.store.events(run_id, after_seq=last_seq)
                if new:
                    last_seq = new[-1]["seq"]
                    run = runner.store.get_run(run_id)
                    await websocket.send_json({"type": "events", "events": new, "status": run["status"]})
        except WebSocketDisconnect:
            return  # the workflow is independent of this socket; nothing to clean up

    def handle_ws_message(raw: str, run_id: str) -> dict:
        if len(raw.encode("utf-8")) > settings.max_ws_message_bytes:
            return {"type": "error", "code": "message_too_large", "detail": "message exceeds size limit"}
        try:
            msg = json.loads(raw)
        except ValueError:
            return {"type": "error", "code": "malformed_json", "detail": "message is not valid JSON"}
        if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
            return {"type": "error", "code": "invalid_message", "detail": "expected an object with a 'type' string"}
        if msg["type"] == "ping":
            return {"type": "pong"}
        return {"type": "error", "code": "unsupported_message",
                "detail": f"this socket is read-only; submit decisions via POST /api/runs/{run_id}/decisions"}

    # ------------------------------------------------------------------ built frontend (optional)
    dist = Path(ROOT) / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")

    return app


app = create_app()
