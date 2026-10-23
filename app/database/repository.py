"""Data access. Every case lookup is scoped by session_key so one user can never read another's case."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    ActionExecution,
    AgentMessage,
    AgentTask,
    Approval,
    AuditEvent,
    CareCase,
    Shortlist,
    SourceEvidenceRow,
)
from app.schemas.evidence import Evidence
from app.workflow.state_machine import TERMINAL_STATES, CaseState


class RepositoryError(Exception):
    pass


class Repository:
    def __init__(self, session_factory: sessionmaker):
        self.sf = session_factory
        # Test hook: number of upcoming shortlist writes that should fail (simulated DB outage).

        self.fail_shortlist_writes: int = 0

    # --- inbound de-duplication -------------------------------------------------------
    def record_inbound(self, session_key: str, msg_id: str, msg_type: str = "ChatMessage") -> bool:
        """Returns False if this message id was already processed."""
        with self.sf() as s:
            s.add(AgentMessage(session_key=session_key, direction="inbound", msg_type=msg_type, msg_id=msg_id))
            try:
                s.commit()
                return True
            except IntegrityError:
                s.rollback()
                return False

    def log_agent_message(self, session_key: str, case_id: str, direction: str, msg_type: str, msg_id: str) -> None:
        with self.sf() as s:
            s.add(AgentMessage(session_key=session_key, case_id=case_id, direction=direction, msg_type=msg_type, msg_id=msg_id))
            try:
                s.commit()
            except IntegrityError:
                s.rollback()

    # --- cases ------------------------------------------------------------------------
    def create_case(self, session_key: str, data_mode: str) -> CareCase:
        case = CareCase(case_id="case_" + uuid.uuid4().hex[:16], session_key=session_key,
                        state=CaseState.COLLECTING_INPUT.value, data_mode=data_mode)
        with self.sf() as s:
            s.add(case)
            s.commit()
        return case

    def get_case(self, case_id: str, session_key: str) -> CareCase | None:
        with self.sf() as s:
            return s.scalar(select(CareCase).where(CareCase.case_id == case_id, CareCase.session_key == session_key))

    def active_case(self, session_key: str) -> CareCase | None:
        terminal = [st.value for st in TERMINAL_STATES]
        with self.sf() as s:
            return s.scalar(select(CareCase).where(CareCase.session_key == session_key, CareCase.state.not_in(terminal))
                            .order_by(CareCase.updated_at.desc()).limit(1))

    def latest_case(self, session_key: str) -> CareCase | None:
        with self.sf() as s:
            return s.scalar(select(CareCase).where(CareCase.session_key == session_key)
                            .order_by(CareCase.updated_at.desc()).limit(1))

    def save_case(self, case: CareCase) -> None:
        case.updated_at = datetime.now(timezone.utc)
        with self.sf() as s:
            s.merge(case)
            s.commit()

    def delete_session_data(self, session_key: str) -> int:
        with self.sf() as s:
            ids = list(s.scalars(select(CareCase.case_id).where(CareCase.session_key == session_key)))
            for model in (SourceEvidenceRow, AgentTask, Shortlist, Approval, ActionExecution, AuditEvent):
                s.execute(delete(model).where(model.case_id.in_(ids)))
            s.execute(delete(AgentMessage).where(AgentMessage.session_key == session_key))
            s.execute(delete(CareCase).where(CareCase.session_key == session_key))
            s.commit()
            return len(ids)

    # --- research bookkeeping ---------------------------------------------------------
    def record_task(self, case_id: str, task_id: str, agent: str, status: str, attempts: int,
                    latency_ms: int | None, error: str | None) -> None:
        with self.sf() as s:
            s.merge(AgentTask(task_id=task_id, case_id=case_id, agent=agent, status=status, attempts=attempts,
                              latency_ms=latency_ms, error=error, completed_at=datetime.now(timezone.utc)))
            s.commit()

    def tasks_for(self, case_id: str) -> list[AgentTask]:
        with self.sf() as s:
            return list(s.scalars(select(AgentTask).where(AgentTask.case_id == case_id)))

    def audit(self, case_id: str | None, trace_id: str, event_type: str, **detail) -> None:
        with self.sf() as s:
            s.add(AuditEvent(case_id=case_id, trace_id=trace_id, event_type=event_type,
                             detail_json=json.dumps(detail, default=str)[:8000]))
            s.commit()

    def audit_events(self, case_id: str) -> list[AuditEvent]:
        with self.sf() as s:
            return list(s.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id)))

    # --- approvals and actions --------------------------------------------------------
    def record_approval(self, case_id: str, version: int, payload_hash: str, decision: str, action: str) -> None:
        with self.sf() as s:
            s.add(Approval(case_id=case_id, shortlist_version=version, payload_hash=payload_hash,
                           decision=decision, action=action))
            s.commit()

    def approvals(self, case_id: str) -> list[Approval]:
        with self.sf() as s:
            return list(s.scalars(select(Approval).where(Approval.case_id == case_id)))

    def get_execution(self, idempotency_key: str) -> ActionExecution | None:
        with self.sf() as s:
            return s.scalar(select(ActionExecution).where(ActionExecution.idempotency_key == idempotency_key))

    def upsert_execution(self, execution: ActionExecution) -> ActionExecution:
        with self.sf() as s:
            merged = s.merge(execution)
            s.commit()
            return merged

    def executions(self, case_id: str) -> list[ActionExecution]:
        with self.sf() as s:
            return list(s.scalars(select(ActionExecution).where(ActionExecution.case_id == case_id)))

    def write_shortlist(self, case_id: str, version: int, payload_json: str, payload_hash: str,
                        confirmation_id: str, idempotency_key: str, evidence: list[Evidence]) -> None:
        """Shortlist + its evidence in ONE transaction: either everything is stored or nothing is."""
        if self.fail_shortlist_writes > 0:
            self.fail_shortlist_writes -= 1
            raise RepositoryError("simulated database write failure")
        with self.sf() as s:
            try:
                s.add(Shortlist(case_id=case_id, version=version, payload_json=payload_json, payload_hash=payload_hash,
                                confirmation_id=confirmation_id, idempotency_key=idempotency_key))
                existing = set(s.scalars(select(SourceEvidenceRow.evidence_id).where(SourceEvidenceRow.case_id == case_id)))
                for e in evidence:
                    if e.evidence_id in existing:
                        continue
                    existing.add(e.evidence_id)
                    s.add(SourceEvidenceRow(
                        case_id=case_id, evidence_id=e.evidence_id, claim_type=e.claim_type.value,
                        claim_value=e.claim_value[:200], subject=e.subject[:300], source_name=e.source_name[:300],
                        source_url=e.source_url, source_type=e.source_type.value, excerpt=e.excerpt[:2000],
                        retrieved_at=e.retrieved_at, reliability=e.reliability.value, synthetic=int(e.synthetic),
                        insurer=e.insurer, plan=e.plan))
                s.commit()
            except Exception as exc:
                s.rollback()
                raise RepositoryError(f"shortlist write failed: {type(exc).__name__}") from exc

    def read_shortlist(self, confirmation_id: str) -> Shortlist | None:
        with self.sf() as s:
            return s.scalar(select(Shortlist).where(Shortlist.confirmation_id == confirmation_id))

    def shortlist_for_session(self, confirmation_id: str, session_key: str) -> Shortlist | None:
        with self.sf() as s:
            return s.scalar(select(Shortlist).join(CareCase, CareCase.case_id == Shortlist.case_id)
                            .where(Shortlist.confirmation_id == confirmation_id, CareCase.session_key == session_key))

    def shortlists(self, case_id: str) -> list[Shortlist]:
        with self.sf() as s:
            return list(s.scalars(select(Shortlist).where(Shortlist.case_id == case_id)))

    def evidence_ids(self, case_id: str) -> set[str]:
        with self.sf() as s:
            return set(s.scalars(select(SourceEvidenceRow.evidence_id).where(SourceEvidenceRow.case_id == case_id)))
