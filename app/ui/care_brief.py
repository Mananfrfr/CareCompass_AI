"""Preparation brief from the immutable saved payload; no new clinical claims."""

def care_brief(payload: dict, reference: str) -> str:
    selected = payload.get("selected_hospital_id")
    items = [i for i in payload["items"] if i["hospital_id"] == selected] if selected else payload["items"]
    lines = [f"## Care preparation brief — {reference}",
             "Based on your saved shortlist; this is not a fresh source check or a booking."]
    if payload["data_mode"] == "fixture":
        lines.append("**SYNTHETIC DEMO: fictional hospitals and insurance records. Do not contact these providers.**")
    lines += [f"Service: {payload['specialty'].replace('_', ' ')} · City: {payload['city']}",
              f"Insurer: {payload.get('insurer') or 'not provided'}"]
    for item in items:
        lines += [f"### {item['name']}", f"Address in saved record: {item['address']}",
                  f"Service evidence: {item['specialty_signal']}; confidence: {item['evidence_confidence']}",
                  "Insurance evidence: " + ", ".join(item["insurance_states"]),
                  "Sources: " + ", ".join(item["source_urls"])]
    lines += ["### Questions for the hospital",
              "- Does this exact branch currently offer the service, and when is a specialist available?",
              "- What records should I bring, and what are the consultation and investigation charges?",
              "### Questions for the insurer / TPA",
              "- Is this exact branch in my current plan's network? Please confirm the address and postcode.",
              "- What exclusions, waiting periods, co-payments and pre-authorisation steps apply?",
              "- If sources conflict, which current written confirmation can you provide?",
              "Bring your existing reports and medication list to the consultation. Share policy identifiers only "
              "through the hospital or insurer's official channels.",
              "Navigation only: no diagnosis, coverage guarantee, appointment or medical advice is provided."]
    return "\n\n".join(lines)
