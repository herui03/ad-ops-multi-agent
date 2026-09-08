from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum
from datetime import datetime


class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    INSIGHT = "insight"
    STRATEGY = "strategy"
    CREATIVE = "creative"
    ANALYTICS = "analytics"
    COMPLIANCE = "compliance"
    CI = "ci"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"


class ChatMessage(BaseModel):
    role: str = "user"
    content: str
    agent: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    message: str
    agent_trace: list[dict] = Field(default_factory=list)
    pending_approvals: list[dict] = Field(default_factory=list)


class AgentStep(BaseModel):
    agent: AgentType
    action: str
    input_summary: str = ""
    output_summary: str = ""
    status: TaskStatus = TaskStatus.PENDING
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HumanApproval(BaseModel):
    approval_id: str
    session_id: str
    agent: AgentType
    approval_type: str
    title: str
    description: str
    data: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    human_feedback: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ApprovalDecision(BaseModel):
    approval_id: str
    decision: ApprovalStatus
    feedback: str = ""
    revised_data: dict[str, Any] = Field(default_factory=dict)
