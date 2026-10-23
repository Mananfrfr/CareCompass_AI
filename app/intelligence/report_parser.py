"""Medical report understanding (text, or text extracted from a PDF).

Deterministic and provenance-preserving: each finding keeps the exact sentence and character
span it came from, and hedged or negated findings are never upgraded to confirmed ones.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from app.intelligence.care_knowledge import CONDITIONS, ConditionRule
from app.schemas.input import DocumentedFinding, FindingStatus, SourceReference

REPORT_HINTS = (
    "impression", "findings", "radiolog", "mri", "x-ray", "xray", "ct scan", "ultrasound", "usg", "report",
    "clinical history", "diagnosis", "discharge summary", "investigation", "advised", "opinion",
)
DOC_TYPES = (
    ("MRI report", r"\bmri\b|magnetic resonance"),
    ("CT report", r"\bct\b|computed tomograph"),
    ("X-ray report", r"x-?ray|radiograph"),
    ("Ultrasound report", r"ultrasound|\busg\b|sonograph"),
    ("Discharge summary", r"discharge summary"),
    ("Lab report", r"haemoglobin|hemoglobin|serum|creatinine|lab report"),
    ("Clinical note", r"clinical note|consultation|opd|prescription"),
)
HEDGES = (r"suggestive of", r"likely", r"probabl", r"possibl", r"suspect", r"cannot be (?:ruled out|excluded)",
          r"query", r"\?", r"may represent", r"consistent with", r"concern(?:ing)? for", r"versus|\bvs\.?\b",
          r"partial", r"low[- ]grade", r"equivocal")
NEGATIONS = (r"\bno (?:evidence|signs?) of\b", r"\bnegative for\b", r"\bwithout\b", r"\bnot seen\b", r"\babsent\b",
             r"\bintact\b", r"\bnormal\b", r"\bruled out\b", r"\bno\b")
MEASURE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:x\s?\d+(?:\.\d+)?\s?)?(?:mm|cm|ml|mg/dl|g/dl|%|hu|mmhg)\b", re.I)
UNREADABLE = re.compile(r"\[(?:illegible|unreadable|\?+)\]|\?{3,}|�{2,}", re.I)
RECOMMEND = re.compile(r"(?:advised?|recommend(?:ed)?|suggest(?:ed)?|refer(?:red)?|correlat\w+)[^.\n]*", re.I)


@dataclass
class ReportExtraction:
    document_type: str
    findings: list[DocumentedFinding] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def primary(self) -> tuple[ConditionRule | None, DocumentedFinding | None]:
        for status in (FindingStatus.STATED, FindingStatus.SUSPECTED):
            for f in self.findings:
                if f.status == status and f.mapped_condition:
                    rule = next(r for r in CONDITIONS if r.canonical == f.mapped_condition)
                    return rule, f
        return None, None


def looks_like_report(text: str) -> bool:
    low = text.lower()
    hits = sum(1 for h in REPORT_HINTS if h in low)
    return hits >= 2 or (hits >= 1 and len(text) > 250)


def document_type(text: str) -> str:
    low = text.lower()
    for label, pattern in DOC_TYPES:
        if re.search(pattern, low):
            return label
    return "Medical document"


def _sentences(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in re.finditer(r"[^.\n;]+[.\n;]?", text):
        s = m.group(0).strip()
        if len(s) > 3:
            out.append((s, m.start(), m.end()))
    return out


def _status(sentence: str, match_start: int) -> FindingStatus:
    low = sentence.lower()
    before = low[:match_start]
    after = low[match_start:]
    # A negation shortly before the term, or "intact"/"normal" right after it, negates it.
    if any(re.search(p + r"[^,]{0,40}$", before) for p in NEGATIONS[:-1]) or re.search(r"\bno\b[\w\s]{0,25}$", before):
        return FindingStatus.NEGATED
    if re.match(r"[\w\s\-()]{0,40}\b(?:is |appears |are )?(?:intact|normal)\b", after):
        return FindingStatus.NEGATED
    if any(re.search(p, low) for p in HEDGES):
        return FindingStatus.SUSPECTED
    return FindingStatus.STATED


def parse_report(text: str) -> ReportExtraction:
    result = ReportExtraction(document_type=document_type(text))
    for m in UNREADABLE.finditer(text):
        result.unreadable.append(f"Unreadable segment near character {m.start()}")
    for sentence, start, end in _sentences(text):
        low = sentence.lower()
        for rule in CONDITIONS:
            hit = None
            for pattern in rule.patterns:
                hit = re.search(pattern, low)
                if hit:
                    break
            if not hit:
                continue
            result.findings.append(DocumentedFinding(
                text=sentence[:300],
                status=_status(sentence, hit.start()),
                measurements=MEASURE.findall(sentence),
                mapped_condition=rule.canonical,
                source=SourceReference(origin="report", text=sentence[:300], start=start, end=end),
            ))
    for m in RECOMMEND.finditer(text):
        result.recommendations.append(m.group(0).strip()[:200])
    return result


def extract_pdf_text(data: bytes, max_pages: int = 10) -> str:
    """Extract text from a PDF (no OCR). Raises ValueError if nothing readable."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("PDF is password-protected")
    parts = []
    for page in reader.pages[:max_pages]:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if len(text) < 20:
        raise ValueError("PDF has no extractable text (it may be a scanned image)")
    return text
