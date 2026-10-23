"""Action Executor: persist an approved shortlist exactly once, then prove it was saved.

- Idempotent: the idempotency key is derived from (case, action, approved payload hash).
  A repeated approval returns the original confirmation instead of writing again (R9).
- Verified: success is reported only after reading the record back and checking the hash
  and evidence rows (R10).
- Bounded retries with backoff; after the last attempt the action is marked FAILED.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets

from app.database.models import ActionExecution
from app.database.repository import Repository, RepositoryError
from app.matching.decision_rules import r9_should_execute, r10_may_report_success
from app.schemas.actions import ActionResult, ActionStatus, ShortlistPayload
from app.schemas.evidence import Evidence
from app.workflow.approval import canonical_json, idempotency_key, payload_hash

ACTION = "save_shortlist"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_confirmation_id() -> str:
    return "CC-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


class ActionExecutor:
    def __init__(self, repo: Repository, max_attempts: int = 3, backoff_s: float = 0.2):
        self.repo = repo
        self.max_attempts = max_attempts
        self.backoff_s = backoff_s

    def verify_saved(self, confirmation_id: str, expected_hash: str, evidence_ids: set[str], case_id: str) -> list[str]:
        """Read-after-write check. Returns a list of problems (empty == verified)."""
        problems: list[str] = []
        row = self.repo.read_shortlist(confirmation_id)
        if row is None:
            return ["record not found on read-back"]
        if row.case_id != case_id:
            problems.append("record belongs to another case")
        recomputed = hashlib.sha256(row.payload_json.encode()).hexdigest()
        if recomputed != expected_hash or row.payload_hash != expected_hash:
            problems.append("stored payload does not match the approved payload")
        missing = evidence_ids - self.repo.evidence_ids(case_id)
        if missing:
            problems.append(f"{len(missing)} evidence record(s) missing")
        return problems

    async def save_shortlist(self, payload: ShortlistPayload, evidence: list[Evidence]) -> ActionResult:
        p_hash = payload_hash(payload)
        key = idempotency_key(payload.case_id, ACTION, p_hash)

        existing = self.repo.get_execution(key)
        if existing and not r9_should_execute(existing.status):
            return ActionResult(status=ActionStatus.SUCCEEDED, confirmation_id=existing.confirmation_id,
                                idempotency_key=key, verified=bool(existing.verified), duplicate=True,
                                attempts=existing.attempts, verification_details=["already completed earlier"])

        execution = existing or ActionExecution(case_id=payload.case_id, idempotency_key=key, action=ACTION,
                                                status=ActionStatus.PENDING.value, attempts=0)
        body = canonical_json(payload)
        needed_ids = {eid for item in payload.items for eid in item.evidence_ids}
        evidence = [e for e in evidence if e.evidence_id in needed_ids]
        last_error = None
        for attempt in range(1, self.max_attempts + 1):
            execution.attempts = (execution.attempts or 0) + 1
            confirmation_id = new_confirmation_id()
            write_ok = False
            try:
                self.repo.write_shortlist(payload.case_id, payload.version, body, p_hash, confirmation_id, key, evidence)
                write_ok = True
            except RepositoryError as exc:
                last_error = str(exc)
                # The unique idempotency key may mean a concurrent attempt already stored it.
                if (prior := self._find_by_key(payload.case_id, key)) is not None:
                    confirmation_id, write_ok = prior, True
            problems = self.verify_saved(confirmation_id, p_hash, needed_ids, payload.case_id) if write_ok else [last_error]
            if r10_may_report_success(write_ok, not problems):
                execution.status, execution.confirmation_id = ActionStatus.SUCCEEDED.value, confirmation_id
                execution.verified, execution.error = 1, None
                execution = self.repo.upsert_execution(execution)
                return ActionResult(status=ActionStatus.SUCCEEDED, confirmation_id=confirmation_id, idempotency_key=key,
                                    verified=True, attempts=execution.attempts,
                                    verification_details=["record read back", "payload hash matches approval",
                                                          f"{len(needed_ids)} evidence records present"])
            last_error = "; ".join(p for p in problems if p) or last_error
            execution.status, execution.error = ActionStatus.PENDING.value, last_error
            execution = self.repo.upsert_execution(execution)
            if attempt < self.max_attempts:
                await asyncio.sleep(self.backoff_s * 2 ** (attempt - 1))
        execution.status = ActionStatus.FAILED.value
        execution = self.repo.upsert_execution(execution)
        return ActionResult(status=ActionStatus.FAILED, idempotency_key=key, attempts=execution.attempts, error=last_error)

    def _find_by_key(self, case_id: str, key: str) -> str | None:
        for row in self.repo.shortlists(case_id):
            if row.idempotency_key == key:
                return row.confirmation_id
        return None
