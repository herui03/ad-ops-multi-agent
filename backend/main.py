from __future__ import annotations
import json
import uuid
from contextlib import asynccontextmanager 

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import get_settings
from backend.agents.orchestrator import Orchestrator
from backend.memory.shared_memory import get_memory
from backend.models.schemas import ApprovalDecision
from backend.rag import init_rag

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("[Server] Initializing RAG...")
    init_rag()
    print("[Server] RAG ready")
    yield
    # --- Shutdown (optional cleanup) ---
    print("[Server] Shutting down")

app = FastAPI(
    title="Ad Ops Multi-Agent System",
    description="AI multi-agent assistant for a digital advertising sales & operations team",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = Orchestrator()
memory = get_memory()
ws_connections: dict[str, WebSocket] = {}

@app.get("/")
async def root():
    return {"status": "ok", "service": "Ad Ops Multi-Agent System"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


class ChatBody(BaseModel):
    session_id: str = ""
    message: str


@app.post("/api/chat")
async def chat(body: ChatBody):
    session_id = body.session_id or str(uuid.uuid4())[:12]

    ws = ws_connections.get(session_id)
    ws_callback = None
    if ws:
        async def ws_callback(data):
            try:
                await ws.send_json(data)
            except Exception:
                pass

    result = await orchestrator.run(
        session_id=session_id,
        user_input=body.message,
        ws_callback=ws_callback,
    )
    return result


@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    messages = memory.get_session(session_id)
    return {"session_id": session_id, "messages": messages}


@app.get("/api/sessions/{session_id}/approvals")
async def get_approvals(session_id: str):
    approvals = memory.get_pending_approvals(session_id)
    return {"session_id": session_id, "approvals": approvals}


@app.post("/api/approvals/{approval_id}/decide")
async def decide_approval(approval_id: str, decision: ApprovalDecision):
    memory.resolve_approval(
        approval_id=approval_id,
        decision=decision.decision.value,
        feedback=decision.feedback,
    )
    return {"approval_id": approval_id, "status": decision.decision.value, "message": "Decision recorded"}


@app.get("/api/dashboard/stats")
async def dashboard_stats():
    return {
        "active_campaigns": 12,
        "total_clients": 48,
        "monthly_spend_cny": 2_850_000,
        "avg_roas": 2.8,
        "pending_approvals": 3,
        "agents": [
            {"name": "insight", "label": "Insight", "calls_today": 23, "avg_latency_ms": 1200},
            {"name": "strategy", "label": "Strategy", "calls_today": 18, "avg_latency_ms": 1800},
            {"name": "creative", "label": "Creative", "calls_today": 31, "avg_latency_ms": 1500},
            {"name": "analytics", "label": "Analytics", "calls_today": 45, "avg_latency_ms": 900},
            {"name": "compliance", "label": "Compliance", "calls_today": 28, "avg_latency_ms": 400},
            {"name": "ci", "label": "Competitive Intel", "calls_today": 8, "avg_latency_ms": 1400},
        ],
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    ws_connections[session_id] = websocket

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "chat":
                async def ws_cb(payload):
                    await websocket.send_json(payload)

                result = await orchestrator.run(
                    session_id=session_id,
                    user_input=msg["message"],
                    ws_callback=ws_cb,
                )
                await websocket.send_json({"type": "chat_response", "data": result})

            elif msg.get("type") == "approval_decision":
                memory.resolve_approval(
                    approval_id=msg["approval_id"],
                    decision=msg["decision"],
                    feedback=msg.get("feedback", ""),
                )
                await websocket.send_json({"type": "approval_resolved", "approval_id": msg["approval_id"]})

    except WebSocketDisconnect:
        ws_connections.pop(session_id, None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.backend_host, port=settings.backend_port, reload=True)
