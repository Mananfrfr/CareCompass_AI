"""SQLAlchemy models. SQLite for the MVP; the schema is portable to PostgreSQL/Supabase.

Raw medical reports are never stored. `request_json` holds only the structured extraction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CareCase(Base):
    __tablename__ = "care_cases"
    case_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_key: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32))
    data_mode: Mapped[str] = mapped_column(String(16))
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    asked_json: Mapped[str] = mapped_column(Text, default="{}")
    results_json: Mapped[str] = mapped_column(Text, default="[]")
    research_meta_json: Mapped[str] = mapped_column(Text, default="{}")
    shortlist_version: Mapped[int] = mapped_column(Integer, default=0)
    selected_hospital_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SourceEvidenceRow(Base):
    __tablename__ = "source_evidence"
    __table_args__ = (UniqueConstraint("case_id", "evidence_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("care_cases.case_id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[str] = mapped_column(String(40))
    claim_type: Mapped[str] = mapped_column(String(40))
    claim_value: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    source_name: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(String(2048))
    source_type: Mapped[str] = mapped_column(String(40))
    excerpt: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reliability: Mapped[str] = mapped_column(String(16))
    synthetic: Mapped[int] = mapped_column(Integer, default=0)
    insurer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    plan: Mapped[str | None] = mapped_column(String(120), nullable=True)


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    task_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("care_cases.case_id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMessage(Base):
    """Inbound message IDs (for duplicate detection) and agent-to-agent message log. No content stored."""

    __tablename__ = "agent_messages"
    __table_args__ = (UniqueConstraint("direction", "msg_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    direction: Mapped[str] = mapped_column(String(16))
    msg_type: Mapped[str] = mapped_column(String(60))
    msg_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Shortlist(Base):
    __tablename__ = "shortlists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("care_cases.case_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    confirmation_id: Mapped[str] = mapped_column(String(32), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("care_cases.case_id", ondelete="CASCADE"), index=True)
    shortlist_version: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(40))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionExecution(Base):
    __tablename__ = "action_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("care_cases.case_id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    action: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    confirmation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verified: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(60))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
