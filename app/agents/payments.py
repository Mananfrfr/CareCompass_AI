"""Optional AgentPaymentProtocol seller. Stripe TEST mode only; no simulated settlement.

Basic navigation and the care brief stay free. No patient data is sent to Stripe.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import httpx
from uagents import Protocol
from uagents_core.contrib.protocols.payment import (
    CancelPayment, CommitPayment, CompletePayment, Funds, RejectPayment, RequestPayment, payment_protocol_spec,
)

from app.security.privacy import session_key
from app.ui.care_brief import care_brief


class StripeTestProvider:
    def __init__(self, transport=None):
        self.secret = os.getenv("STRIPE_SECRET_KEY", "")
        self.public = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
        self.transport = transport

    @property
    def configured(self):
        return (os.getenv("CARECOMPASS_PAYMENTS", "disabled") == "stripe_test"
                and self.secret.startswith("sk_test_") and self.public.startswith("pk_test_"))

    async def create(self, reference: str):
        if not self.configured:
            raise ValueError("Stripe test mode is not configured")
        fields = {
            "ui_mode": "embedded", "redirect_on_completion": "never", "mode": "payment",
            "payment_method_types[0]": "card", "expires_at": str(int(time.time()) + 1800),
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": "100",
            "line_items[0][price_data][product_data][name]": "CareCompass preparation report — TEST",
            "line_items[0][quantity]": "1", "metadata[reference]": reference,
            "metadata[service]": "carecompass_report",
        }
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post("https://api.stripe.com/v1/checkout/sessions", data=fields,
                headers={"Authorization": f"Bearer {self.secret}", "Idempotency-Key": reference})
            response.raise_for_status()
            data = response.json()
        checkout = data.get("id", "") if isinstance(data, dict) else ""
        expiry = data.get("expires_at") if isinstance(data, dict) else None
        if not (isinstance(checkout, str) and checkout.startswith("cs_test_")
                and checkout.replace("_", "").isalnum() and data.get("livemode") is False
                and isinstance(data.get("client_secret"), str)
                and data["client_secret"].startswith(checkout + "_secret_")
                and isinstance(expiry, (int, float)) and math.isfinite(expiry) and expiry > time.time()):
            raise ValueError("Invalid test checkout response")
        return data

    async def verified(self, order: dict):
        if not self.configured:
            return False
        checkout = order["checkout"]
        if not checkout.startswith("cs_test_") or not checkout.replace("_", "").isalnum():
            return False
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.get(f"https://api.stripe.com/v1/checkout/sessions/{checkout}",
                headers={"Authorization": f"Bearer {self.secret}"})
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("metadata"), dict):
            return False
        return (data.get("id") == checkout and data.get("livemode") is False
                and data.get("status") == "complete" and data.get("payment_status") == "paid"
                and data.get("amount_total") == 100 and data.get("currency") == "usd"
                and data.get("metadata", {}).get("reference") == order["reference"]
                and data.get("metadata", {}).get("service") == "carecompass_report")


def expanded_report(payload: dict, reference: str) -> str:
    lines = [care_brief(payload, reference), "### Compare the saved options"]
    for item in payload["items"]:
        lines.append(f"- {item['rank']}. {item['name']}: suitability {item['suitability_score']:.0f}/100 "
                     f"(not a clinical-quality score); evidence confidence {item['evidence_confidence']}; "
                     f"{', '.join(item['insurance_states'])}.")
    lines += ["### Call notes to complete yourself",
              "Hospital contact / date: ____\nBranch address confirmed: ____\nSpecialist availability: ____\n"
              "Written cost estimate: ____\nInsurer reference / date: ____\nPre-authorisation requirements: ____",
              "This report organises existing evidence. It includes no new verification, clinician review, "
              "priority treatment, booking, insurance approval or hospital referral commission."]
    return "\n\n".join(lines)


class ReportPayments:
    def __init__(self, repo, send_text, provider=None):
        self.repo, self.send_text = repo, send_text
        self.provider = provider or StripeTestProvider()
        self.protocol = Protocol(spec=payment_protocol_spec, role="seller")
        self.protocol.on_message(CommitPayment)(self.commit)
        self.protocol.on_message(RejectPayment)(self.reject)
        self.lock = asyncio.Lock()

    async def request(self, ctx, sender):
        if not self.provider.configured:
            await self.send_text(ctx, sender, "Paid reports are not enabled. Basic navigation, saving and **care brief** "
                "are free. The Payment Protocol integration is a test-mode prototype awaiting seller configuration.")
            return
        case = self.repo.latest_case(session_key(sender))
        saved = self.repo.shortlists(case.case_id) if case else []
        if not saved:
            await self.send_text(ctx, sender, "Save your shortlist first. Then use **buy preparation report** "
                "to request the optional $1.00 USD test checkout.")
            return
        row = saved[-1]
        scope = hashlib.sha256(f"{sender}|{ctx.session}|{row.payload_hash}".encode()).hexdigest()
        async with self.lock:
            order = ctx.storage.get("report_order:" + scope)
            if order and order.get("completed"):
                await self.send_text(ctx, sender, expanded_report(json.loads(row.payload_json), row.confirmation_id))
                return
            if order and order["expires"] <= time.time():
                # A checkout can have settled without its commit reaching this agent.
                # Never replace it automatically and ask the user to pay twice.
                try:
                    settled = await self.provider.verified(order)
                except (httpx.HTTPError, ValueError, KeyError):
                    settled = False
                if settled:
                    order["completed"] = True
                    ctx.storage.set("report_order:" + scope, order)
                    await self.send_text(ctx, sender, "TEST payment verified. " + expanded_report(
                        json.loads(row.payload_json), row.confirmation_id))
                else:
                    await self.send_text(ctx, sender, "This test checkout expired or could not be reconciled. "
                        "No replacement checkout was created. Do not pay again; contact the operator. "
                        "Your free **care brief** remains available.")
                return
            if not order:
                reference = "report_" + uuid4().hex
                try:
                    checkout = await self.provider.create(reference)
                except (httpx.HTTPError, ValueError, KeyError):
                    await self.send_text(ctx, sender, "The test checkout service is unavailable. No payment "
                        "request was sent. Your saved shortlist and free **care brief** are still available.")
                    return
                order = {"reference": reference, "checkout": checkout["id"], "client_secret": checkout["client_secret"],
                         "owner": session_key(sender), "session": str(ctx.session), "expires": checkout["expires_at"],
                         "saved_reference": row.confirmation_id, "completed": False}
                ctx.storage.set("report_order:" + scope, order)
                ctx.storage.set("report_reference:" + reference, scope)
        await self.send_text(ctx, sender, "TEST CHECKOUT — $1.00 USD, no real money. Optional expanded comparison "
            "and call-notes report from your saved evidence, delivered here after verification. No new research, "
            "booking or coverage guarantee. Cancel to keep using all free features.")
        await ctx.send(sender, RequestPayment(
            accepted_funds=[Funds(amount="1.00", currency="USD", payment_method="stripe")],
            recipient=ctx.agent.address, deadline_seconds=max(1, int(order["expires"] - time.time())),
            reference=order["reference"], description="CareCompass expanded preparation report — TEST ONLY",
            metadata={"stripe": {"client_secret": order["client_secret"], "publishable_key": self.provider.public,
                                   "checkout_session_id": order["checkout"], "currency": "usd", "amount": "1.00"}}))

    async def commit(self, ctx, sender, msg: CommitPayment):
        async with self.lock:
            scope = ctx.storage.get("report_reference:" + (msg.reference or ""))
            order = ctx.storage.get("report_order:" + scope) if scope else None
            try:
                funds_ok = (msg.funds.currency == "USD" and msg.funds.payment_method == "stripe"
                            and Decimal(msg.funds.amount) == Decimal("1.00"))
            except (InvalidOperation, ValueError):
                funds_ok = False
            bound = (order and order["owner"] == session_key(sender) and order["session"] == str(ctx.session)
                     and msg.recipient == ctx.agent.address and msg.transaction_id == order["checkout"] and funds_ok)
            verified = False
            if bound:
                try:
                    # Even late notifications must check actual settlement; do not strand a paid order at expiry.
                    verified = order["completed"] or await self.provider.verified(order)
                except (httpx.HTTPError, ValueError, KeyError):
                    pass
            if not verified:
                await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id,
                    reason="Settlement could not be verified for this order. No report was released. Retry verification; do not pay again."))
                return
            row = self.repo.shortlist_for_session(order["saved_reference"], session_key(sender))
            if row is None:
                await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id,
                    reason="The saved record was deleted; report unavailable. Contact the operator; do not pay again."))
                return
            order["completed"] = True
            ctx.storage.set("report_order:" + scope, order)
            await ctx.send(sender, CompletePayment(transaction_id=msg.transaction_id))
            await self.send_text(ctx, sender, "TEST payment verified. " + expanded_report(json.loads(row.payload_json), row.confirmation_id))

    async def reject(self, ctx, sender, msg: RejectPayment):
        await self.send_text(ctx, sender, "Payment declined. Your free shortlist and care brief remain available.")
