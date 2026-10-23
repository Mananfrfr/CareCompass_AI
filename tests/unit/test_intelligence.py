"""Intent extraction, safety routing, report parsing, questions, ASI1 client (Tests 6-9)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import openai
import pytest

from app.config import Settings
from app.intelligence.asi1_client import ASI1Client, ASI1Unavailable
from app.intelligence.intent_parser import IntentParser, LLMExtraction, merge_llm, rule_extract
from app.intelligence.question_engine import plan_questions
from app.intelligence.report_parser import extract_pdf_text, parse_report
from app.intelligence.safety_router import assess
from app.schemas.input import FindingStatus, InputType, Urgency

ACL_REPORT = (
    "MRI RIGHT KNEE\nPatient name: Test Person\nUHID: 99887766\n"
    "Findings: Complete tear of the anterior cruciate ligament with bone bruise measuring 12 x 8 mm.\n"
    "Medial meniscus is intact. Lateral meniscus: possible small tear [illegible].\n"
    "Impression: Complete ACL tear. Possible low-grade MCL sprain.\nAdvised orthopaedic consultation."
)


def test_06_known_condition_maps_to_specialty_without_asking_specialty():
    req = rule_extract("I have kidney stones and live in Jaipur.")
    assert req.input_type == InputType.KNOWN_CONDITION
    assert req.reported_condition == "Kidney stone" and req.care_specialty == "urology"
    assert req.city == "Jaipur" and req.insurance_provider is None
    plan = plan_questions(req)
    assert plan.ready  # insurance is optional: research proceeds without asking


def test_07_symptoms_only_routes_without_diagnosis():
    req = rule_extract("I've had knee pain for two weeks.")
    assert req.input_type == InputType.SYMPTOMS and req.reported_condition is None
    assert req.care_specialty == "orthopaedics" and req.duration == "two weeks"
    assert "not a diagnosis" in req.specialty_rationale
    plan = plan_questions(req)
    assert not plan.ready and plan.fields == ["city", "insurance"]
    assert assess("I've had knee pain for two weeks.").urgency == Urgency.ROUTINE


@pytest.mark.parametrize("text", [
    "Sudden severe chest pain and difficulty breathing.",
    "my father's face is drooping and his speech is slurred",
    "I can't breathe properly",
    "she fainted and is unconscious",
])
def test_08_emergency_stops_routine_flow(text):
    a = assess(text)
    assert a.urgency == Urgency.EMERGENCY and "112" in a.guidance


def test_safety_negation_and_self_harm():
    assert assess("no chest pain, just knee pain").urgency == Urgency.ROUTINE
    a = assess("I want to end my life")
    assert a.is_emergency and "14416" in a.guidance
    assert assess("I can't put weight on my ankle").urgency == Urgency.PROMPT


def test_09_report_extraction_preserves_uncertainty_and_negation():
    ex = parse_report(ACL_REPORT)
    assert ex.document_type == "MRI report"
    statuses = {(f.mapped_condition, f.status) for f in ex.findings}
    assert ("ACL tear", FindingStatus.STATED) in statuses
    assert ("Meniscus tear", FindingStatus.NEGATED) in statuses  # "intact"
    assert ("Meniscus tear", FindingStatus.SUSPECTED) in statuses  # "possible small tear"
    acl = next(f for f in ex.findings if f.mapped_condition == "ACL tear" and "12 x 8 mm" in f.text)
    assert "12 x 8 mm" in acl.measurements
    assert acl.source.start is not None and ACL_REPORT[acl.source.start:acl.source.end].strip().startswith("Findings")
    assert ex.unreadable and any("orthopaedic" in r.lower() for r in ex.recommendations)
    req = rule_extract(ACL_REPORT + "\nI am in Jaipur.")
    assert req.input_type == InputType.MEDICAL_REPORT and req.care_specialty == "orthopaedics"
    assert req.reported_condition == "ACL tear" and req.city == "Jaipur"


def test_report_hedged_only_is_not_upgraded():
    req = rule_extract("Ultrasound abdomen. Impression: findings suggestive of a renal calculus. Clinical correlation advised.")
    assert req.reported_condition == "possible Kidney stone"
    assert req.extraction_confidence < 0.9


def test_report_contradicting_user_claim_is_flagged():
    req = rule_extract("I have an ACL tear", report_text="MRI knee. Findings: ACL is intact. Impression: normal study.")
    assert any("ACL" in n for n in req.unreadable_notes)


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_text_extraction():
    text = extract_pdf_text(_minimal_pdf("Impression: Complete ACL tear of the right knee"))
    assert "ACL tear" in text
    with pytest.raises(ValueError):
        extract_pdf_text(_minimal_pdf(""))


def test_insurer_and_city_aliases():
    req = rule_extract("Kidney stone, Bangalore, insured with Max Bupa, plan Health Companion Gold")
    assert req.city == "Bengaluru" and req.insurance_provider == "Niva Bupa"
    assert rule_extract("ACL tear in Jaipur, Sample Care Health").insurance_provider == "Sample Care Health"
    assert rule_extract("no insurance, knee pain in Pune").insurance_declined


def test_llm_fields_must_be_grounded_in_user_text():
    text = "my stomach has been hurting after meals for a month, I'm in Pune"
    base = rule_extract(text)
    llm = LLMExtraction(input_type="symptoms", symptoms=["stomach pain after meals"], city="Mumbai",
                        insurer="Star Health", suggested_specialty="gastroenterology")
    merged = merge_llm(base, llm, text)
    assert merged.city == "Pune"  # model's "Mumbai" was not in the text
    assert merged.insurance_provider is None  # hallucinated insurer rejected
    assert merged.care_specialty == "gastroenterology" and merged.extraction_method == "rules+asi1"
    bad = merge_llm(rule_extract("hello"), LLMExtraction(suggested_specialty="not_a_specialty", condition="x"), "hello")
    assert bad.care_specialty is None


class FakeCompletions:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        if out == "SLOW":
            await asyncio.sleep(5)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out))])


def fake_client(outputs):
    completions = FakeCompletions(outputs)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


async def test_asi1_structured_output_validated_and_repaired():
    client, comp = fake_client(["not json at all", '```json\n{"input_type": "known_condition", "condition": "kidney stone"}\n```'])
    asi = ASI1Client(replace(Settings(), asi1_api_key="x"), client=client)
    out = await asi.structured("sys", "user", LLMExtraction)
    assert out.condition == "kidney stone" and comp.calls == 2


async def test_asi1_failures_become_unavailable(monkeypatch):
    import httpx
    req = httpx.Request("POST", "https://api.asi1.ai/v1/chat/completions")
    auth = openai.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    client, comp = fake_client([auth])
    asi = ASI1Client(replace(Settings(), asi1_api_key="x"), client=client)
    with pytest.raises(ASI1Unavailable):
        await asi.chat("s", "u")
    assert comp.calls == 1  # auth errors are not retried
    client, comp = fake_client(["SLOW", "SLOW"])
    asi = ASI1Client(replace(Settings(), asi1_api_key="x", asi1_timeout_s=0.05), client=client, max_attempts=2)
    with pytest.raises(ASI1Unavailable):
        await asi.chat("s", "u")
    assert comp.calls == 2  # bounded retries


async def test_intent_parser_falls_back_to_rules_when_asi1_fails():
    client, _ = fake_client(["garbage", "still garbage"])
    parser = IntentParser(ASI1Client(replace(Settings(), asi1_api_key="x"), client=client))
    req = await parser.parse("I have a kidney stone in Delhi")
    assert req.care_specialty == "urology" and req.extraction_method == "rules"
