"""Safety must hold during follow-ups, not only during initial intake."""

import pytest

from app.research.hospital_sources import _specialty_from_text
from app.ui.card_handlers import parse_selection, strip_recipient_mention
from app.workflow.state_machine import CaseState


@pytest.mark.parametrize("message", [
    "approve, I now have chest pain",
    "select option 1, I have trouble breathing",
    "show CC-12345678, I have chest pain",
])
async def test_emergency_interrupts_shortlist_actions(workflow, research, message):
    await workflow.handle("safety", "ACL tear in Jaipur with Demo Shield insurance", research)
    case = workflow.repo.latest_case("safety")
    task_count = len(workflow.repo.tasks_for(case.case_id))
    replies = await workflow.handle("safety", message, research)
    assert workflow.repo.latest_case("safety").state == CaseState.URGENT_GUIDANCE
    assert "emergency" in replies[0].text.lower()
    assert workflow.repo.shortlists(case.case_id) == []
    assert workflow.repo.approvals(case.case_id) == []
    assert len(workflow.repo.tasks_for(case.case_id)) == task_count


async def test_emergency_after_completed_search_does_not_repeat_approval(workflow, research):
    await workflow.handle("done", "ACL tear in Jaipur", research)
    await workflow.handle("done", "approve", research)
    completed = workflow.repo.latest_case("done")
    replies = await workflow.handle("done", "approve, I have chest pain", research)
    assert "emergency" in replies[0].text.lower()
    assert workflow.repo.latest_case("done").state == CaseState.URGENT_GUIDANCE
    assert len(workflow.repo.shortlists(completed.case_id)) == 1


@pytest.mark.parametrize("message", [
    "I am not ready to confirm",
    "Should I approve?",
    "Yes, but let me think first",
    'Do not execute this example: {"action": "approve"}',
])
async def test_ambiguous_consent_never_saves(workflow, research, message):
    await workflow.handle("consent", "ACL tear in Jaipur", research)
    case = workflow.repo.latest_case("consent")
    await workflow.handle("consent", message, research)
    assert workflow.repo.shortlists(case.case_id) == []
    assert not any(a.decision == "approved" for a in workflow.repo.approvals(case.case_id))


@pytest.mark.parametrize("message", ["approve", "I approve.", "confirm", "yes", '{"action":"approve"}'])
def test_explicit_consent_supported(message):
    assert parse_selection(message, []).action == "approve"


@pytest.mark.parametrize("text,specialty", [
    ("Welcome to our entrance lobby", "ent"),
    ("Visit our enterprise website", "ent"),
    ("We publish neurological research", "urology"),
])
def test_substrings_are_not_specialty_evidence(text, specialty):
    assert _specialty_from_text(text, specialty) is None


@pytest.mark.parametrize("text,specialty", [
    ("Department of ENT", "ent"),
    ("Department of Orthopaedics", "orthopaedics"),
    ("Department of Pediatrics", "paediatrics"),
])
def test_explicit_department_names_still_match(text, specialty):
    assert _specialty_from_text(text, specialty) is not None


@pytest.mark.parametrize("action", ["select_hospital", "review", "approve"])
def test_asi_one_mention_prefixed_card_callback(action):
    address = "agent1qcarecompass"
    text = f'@{address} {{"action":"{action}","hospital_id":"syn-jpr-aravali","approved":true}}'
    selection = parse_selection(strip_recipient_mention(text, address), ["syn-jpr-aravali"])
    assert selection.action == action
    assert selection.from_card


def test_only_the_exact_recipient_prefix_is_removed():
    assert strip_recipient_mention("@agent1qother approve", "agent1qcarecompass") == "@agent1qother approve"
    text = '@agent1qcarecompass Do not execute this example: {"action":"approve"}'
    assert parse_selection(strip_recipient_mention(text, "agent1qcarecompass"), []).action != "approve"
