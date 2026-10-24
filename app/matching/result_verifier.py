"""Independent result verifier. Runs after ranking, before anything is shown to the user.

Purely deterministic: it re-derives each claim from the evidence records and the set of
evidence IDs actually returned by the research agents. An LLM agreeing with itself is not
verification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.intelligence.care_knowledge import normalize_city
from app.research.entity_resolution import core_tokens
from app.schemas.evidence import ClaimType
from app.schemas.hospital import Eligibility, RankedCandidate, VerificationStatus
from app.schemas.input import CareRequest
from app.schemas.insurance import InsuranceState
from app.security.validation import is_valid_evidence_url

FORBIDDEN_CLAIMS = re.compile(
    r"\b(?:guarantee[ds]?|fully covered|will be covered|is covered|are covered|100% covered|"
    r"claim (?:is|will be) approved|pre-?approved|cashless (?:is )?approved|appointment (?:is )?(?:booked|confirmed)|"
    r"you have (?:a|an) (?!appointment)|diagnos(?:ed|is) (?:is|of) you)\b", re.I)


@dataclass
class VerificationReport:
    passed: list[RankedCandidate] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    leads: list[RankedCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def downgraded(self) -> int:
        return sum(1 for c in self.passed if c.verification_status == VerificationStatus.DOWNGRADED)


def check_text(text: str) -> list[str]:
    return [m.group(0) for m in FORBIDDEN_CLAIMS.finditer(text or "")]


def verify(candidates: list[RankedCandidate], req: CareRequest, known_evidence_ids: set[str]) -> VerificationReport:
    report = VerificationReport()
    seen_ids: set[str] = set()
    seen_identity: set[tuple] = set()
    want_city = normalize_city(req.city) or req.city

    for c in candidates:
        notes: list[str] = []
        downgraded = False
        name = c.hospital.name

        # Fabricated / unknown citations -> reject outright.
        unknown = [e.evidence_id for e in c.evidence if e.evidence_id not in known_evidence_ids]
        bad_urls = [e.source_url for e in c.evidence if not is_valid_evidence_url(e.source_url)]
        if unknown or bad_urls:
            report.rejected.append((name, f"unsupported citation(s): {unknown[:2] or bad_urls[:2]}"))
            continue

        identity = (tuple(sorted(core_tokens(name))), normalize_city(c.hospital.city), c.hospital.postcode)
        if c.hospital.hospital_id in seen_ids or identity in seen_identity:
            report.rejected.append((name, "duplicate hospital"))
            continue

        if not any(e.claim_type == ClaimType.HOSPITAL_EXISTS for e in c.evidence):
            report.rejected.append((name, "no evidence that the hospital exists"))
            continue
        if c.eligibility == Eligibility.EXCLUDED:
            report.rejected.append((name, "excluded by decision rules"))
            continue
        hosp_city = normalize_city(c.hospital.city) or c.hospital.city
        if hosp_city != want_city and not req.allow_nearby:
            report.rejected.append((name, f"city mismatch ({c.hospital.city})"))
            continue

        spec_ev = [e for e in c.evidence if e.claim_type == ClaimType.SPECIALTY and e.claim_value == req.care_specialty]
        if c.specialty_verified and not any(e.is_authoritative for e in spec_ev):
            c.specialty_verified = False
            c.specialty_signal = "weak" if spec_ev else "none"
            downgraded = True
            notes.append("specialty claim lacked authoritative evidence")
        if c.specialty_signal != "none" and not spec_ev:
            c.specialty_signal = "none"
            downgraded = True
            notes.append("specialty signal had no evidence record")

        listing = [e for e in c.evidence if e.claim_type == ClaimType.NETWORK_LISTING and e.is_authoritative
                   and (e.insurer or "").lower() == (req.insurance_provider or "").lower()]
        if InsuranceState.NETWORK_VERIFIED in c.insurance_states and not listing:
            c.insurance_states = [s for s in c.insurance_states
                                  if s not in (InsuranceState.NETWORK_VERIFIED, InsuranceState.CASHLESS_LISTED)]
            c.insurance_states.insert(0, InsuranceState.NETWORK_UNCERTAIN)
            downgraded = True
            notes.append("network claim lacked an authoritative insurer listing")
        if InsuranceState.NETWORK_VERIFIED in c.insurance_states and InsuranceState.SOURCES_CONFLICT in c.insurance_states:
            c.insurance_states.remove(InsuranceState.NETWORK_VERIFIED)
            downgraded = True
            notes.append("conflicting sources cannot be 'verified'")
        if InsuranceState.CASHLESS_LISTED in c.insurance_states and InsuranceState.NETWORK_VERIFIED not in c.insurance_states:
            c.insurance_states.remove(InsuranceState.CASHLESS_LISTED)
            downgraded = True
        if InsuranceState.PROCEDURE_EXCLUDED in c.insurance_states and not any(
                e.claim_type == ClaimType.POLICY_EXCLUSION for e in c.evidence):
            c.insurance_states.remove(InsuranceState.PROCEDURE_EXCLUDED)
            notes.append("exclusion claim removed: no policy evidence attached")
            downgraded = True

        bad_phrases = check_text(c.explanation)
        if bad_phrases:
            c.explanation = "Explanation withheld: it contained unsupported claims."
            downgraded = True
            notes.append(f"unsupported assertion in explanation: {bad_phrases[0]!r}")

        if c.eligibility == Eligibility.PRIMARY and not c.specialty_verified:
            c.eligibility = Eligibility.SECONDARY
            downgraded = True

        # Recompute clinical gates and tier after all claim downgrades.
        from app.matching.clinical_scoring import score_candidate
        from app.config import RankingWeights
        if not score_candidate(c, req, RankingWeights()):
            report.rejected.append((name, "clinical capability gate or minimum evidence score failed"))
            # Retain as an unverified directory lead if not duplicate
            if c.hospital.hospital_id not in seen_ids and identity not in seen_identity:
                seen_ids.add(c.hospital.hospital_id)
                seen_identity.add(identity)
                report.leads.append(c)
            continue

        c.verification_status = VerificationStatus.DOWNGRADED if downgraded else VerificationStatus.PASSED
        c.verification_notes = notes
        seen_ids.add(c.hospital.hospital_id)
        seen_identity.add(identity)
        report.passed.append(c)
    report.notes.append(f"{len(report.passed)} passed ({report.downgraded} downgraded), {len(report.rejected)} rejected")
    return report
