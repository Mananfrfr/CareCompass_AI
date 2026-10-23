"""Attachment intake for ACP ResourceContent.

Supported: PDF with a text layer, plain text. Images are acknowledged but not OCR'd (no
verified OCR integration) - the user is asked to paste the key lines instead.
Every fetch goes through SafeFetcher (SSRF checks on each redirect hop, size cap).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.report_parser import extract_pdf_text
from app.research.source_fetcher import FetchError, SafeFetcher
from app.security.validation import UnsafeURLError

MAX_ATTACHMENT_BYTES = 8_000_000


@dataclass
class AttachmentResult:
    text: str | None
    message: str | None  # user-facing note when we could not read it


async def read_attachment(url: str, mime_hint: str, fetcher: SafeFetcher) -> AttachmentResult:
    hint = (mime_hint or "").lower()
    if hint.startswith("image/"):
        return AttachmentResult(None, "I can't read text from images yet. Please paste the *Findings* / *Impression* "
                                      "lines from the report (you can remove your name and ID numbers).")
    try:
        doc = await fetcher.fetch(url)
    except UnsafeURLError:
        return AttachmentResult(None, "That attachment link isn't one I'm allowed to open. Please paste the report text instead.")
    except FetchError:
        return AttachmentResult(None, "I couldn't download that attachment. Please paste the relevant report text instead.")
    ctype = (doc.content_type or hint).lower()
    if "pdf" in ctype or doc.body[:5] == b"%PDF-":
        try:
            return AttachmentResult(extract_pdf_text(doc.body), None)
        except Exception as exc:  # noqa: BLE001 - pypdf raises many types for malformed files
            return AttachmentResult(None, f"I couldn't read that PDF ({str(exc)[:80]}). Please paste the key lines instead.")
    if ctype.startswith("text/"):
        return AttachmentResult(doc.text[:20000], None)
    if ctype.startswith("image/"):
        return AttachmentResult(None, "I can't read text from images yet. Please paste the key lines from the report.")
    return AttachmentResult(None, "That file type isn't supported. Please send a PDF or paste the report text.")


def attachment_fetcher(user_agent: str) -> SafeFetcher:
    # Attachments are user-provided content, not crawled pages: robots.txt does not apply.
    return SafeFetcher(user_agent, max_bytes=MAX_ATTACHMENT_BYTES, respect_robots=False)
