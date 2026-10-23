"""Explicit case state machine. Invalid transitions raise instead of silently corrupting state."""

from __future__ import annotations

from enum import Enum


class CaseState(str, Enum):
    COLLECTING_INPUT = "COLLECTING_INPUT"
    SAFETY_CHECKING = "SAFETY_CHECKING"
    URGENT_GUIDANCE = "URGENT_GUIDANCE"
    RESEARCHING = "RESEARCHING"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    MATCHING = "MATCHING"
    VERIFYING = "VERIFYING"
    PARTIAL_RESULTS = "PARTIAL_RESULTS"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    CANCELLED = "CANCELLED"
    APPROVED = "APPROVED"
    EXECUTING_ACTION = "EXECUTING_ACTION"
    CHECKING_SAVED_RESULT = "CHECKING_SAVED_RESULT"
    COMPLETED = "COMPLETED"
    RETRY_OR_ESCALATE = "RETRY_OR_ESCALATE"
    FAILED = "FAILED"


S = CaseState
TRANSITIONS: dict[CaseState, set[CaseState]] = {
    S.COLLECTING_INPUT: {S.SAFETY_CHECKING, S.CANCELLED},
    S.SAFETY_CHECKING: {S.URGENT_GUIDANCE, S.COLLECTING_INPUT, S.RESEARCHING},
    S.RESEARCHING: {S.MATCHING, S.SOURCE_UNAVAILABLE},
    S.SOURCE_UNAVAILABLE: {S.RESEARCHING, S.COLLECTING_INPUT, S.CANCELLED},
    S.MATCHING: {S.VERIFYING},
    S.VERIFYING: {S.AWAITING_APPROVAL, S.PARTIAL_RESULTS},
    S.PARTIAL_RESULTS: {S.APPROVED, S.CANCELLED, S.COLLECTING_INPUT, S.RESEARCHING},
    S.AWAITING_APPROVAL: {S.APPROVED, S.CANCELLED, S.COLLECTING_INPUT, S.RESEARCHING},
    S.APPROVED: {S.EXECUTING_ACTION},
    S.EXECUTING_ACTION: {S.CHECKING_SAVED_RESULT, S.RETRY_OR_ESCALATE},
    S.CHECKING_SAVED_RESULT: {S.COMPLETED, S.RETRY_OR_ESCALATE},
    S.RETRY_OR_ESCALATE: {S.EXECUTING_ACTION, S.FAILED},
    S.URGENT_GUIDANCE: set(),
    S.CANCELLED: set(),
    S.COMPLETED: set(),
    S.FAILED: set(),
}
TERMINAL_STATES = frozenset(s for s, nxt in TRANSITIONS.items() if not nxt)
# States in which the user is looking at a shortlist and may select / approve.
SHORTLIST_STATES = frozenset({S.AWAITING_APPROVAL, S.PARTIAL_RESULTS})


class InvalidTransition(Exception):
    pass


def can_transition(current: CaseState, target: CaseState) -> bool:
    return target in TRANSITIONS[current]


def transition(current: CaseState | str, target: CaseState) -> CaseState:
    current = CaseState(current)
    if not can_transition(current, target):
        raise InvalidTransition(f"{current.value} -> {target.value} is not allowed")
    return target
