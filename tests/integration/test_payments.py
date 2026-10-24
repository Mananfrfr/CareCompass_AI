from types import SimpleNamespace
import time

import httpx
import pytest
from uagents_core.contrib.protocols.payment import CancelPayment, CommitPayment, CompletePayment, Funds, RequestPayment

from app.agents.payments import ReportPayments, StripeTestProvider
from app.security.privacy import session_key


class Storage(dict):
    def set(self, key, value):
        self[key] = value


class Context:
    def __init__(self):
        self.storage = Storage()
        self.session = "session-a"
        self.agent = SimpleNamespace(address="seller")
        self.sent = []

    async def send(self, sender, message):
        self.sent.append(message)


class Provider:
    configured = True
    public = "pk_test_example"
    def __init__(self):
        self.created = 0
        self.checks = 0
    async def create(self, reference):
        self.created += 1
        return {"id": "cs_test_123", "client_secret": "test_secret", "expires_at": time.time() + 1800}
    async def verified(self, order):
        self.checks += 1
        return True


async def send_text(ctx, sender, text):
    ctx.sent.append(text)


async def prepare(workflow, research):
    key = session_key("buyer")
    await workflow.handle(key, "ACL tear in Jaipur", research)
    await workflow.handle(key, "approve", research)
    ctx = Context()
    provider = Provider()
    payments = ReportPayments(workflow.repo, send_text, provider)
    await payments.request(ctx, "buyer")
    request = next(m for m in ctx.sent if isinstance(m, RequestPayment))
    message = CommitPayment(funds=Funds(amount="1.00", currency="USD", payment_method="stripe"),
        recipient="seller", transaction_id="cs_test_123", reference=request.reference)
    return ctx, provider, payments, message


async def test_payment_verifies_once_and_replays_same_report(workflow, research):
    ctx, provider, payments, message = await prepare(workflow, research)
    await payments.commit(ctx, "buyer", message)
    await payments.commit(ctx, "buyer", message)
    assert provider.checks == 1 and provider.created == 1
    assert sum(isinstance(m, CompletePayment) for m in ctx.sent) == 2
    assert any(isinstance(m, str) and "Call notes" in m for m in ctx.sent)
    assert len(workflow.repo.shortlists(workflow.repo.latest_case(session_key("buyer")).case_id)) == 1


@pytest.mark.parametrize("change", ["payer", "session", "amount", "transaction", "reference", "recipient"])
async def test_payment_binding_rejects_forgery(workflow, research, change):
    ctx, provider, payments, message = await prepare(workflow, research)
    sender = "other" if change == "payer" else "buyer"
    if change == "session": ctx.session = "other"
    if change == "amount": message.funds.amount = "0.01"
    if change == "transaction": message.transaction_id = "cs_test_other"
    if change == "reference": message.reference = "other"
    if change == "recipient": message.recipient = "other"
    await payments.commit(ctx, sender, message)
    assert isinstance(ctx.sent[-1], CancelPayment)
    assert provider.checks == 0


@pytest.mark.parametrize("field,value", [("payment_status", "unpaid"), ("amount_total", 1),
    ("currency", "inr"), ("livemode", True), ("metadata", {}), ("status", "open")])
async def test_stripe_response_must_match_order(monkeypatch, field, value):
    monkeypatch.setenv("CARECOMPASS_PAYMENTS", "stripe_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_example")
    data = dict(id="cs_test_123", livemode=False, status="complete", payment_status="paid", amount_total=100,
                currency="usd", metadata={"reference": "ref", "service": "carecompass_report"})
    data[field] = value
    provider = StripeTestProvider(httpx.MockTransport(lambda req: httpx.Response(200, json=data)))
    assert not await provider.verified({"checkout": "cs_test_123", "reference": "ref"})


def test_live_keys_cannot_enable_payments(monkeypatch):
    monkeypatch.setenv("CARECOMPASS_PAYMENTS", "stripe_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_example")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_live_example")
    assert not StripeTestProvider().configured


async def test_checkout_failure_preserves_free_workflow(workflow, research):
    ctx, provider, payments, message = await prepare(workflow, research)
    ctx.storage.clear()
    ctx.sent.clear()
    async def unavailable(reference):
        raise httpx.ConnectError("offline")
    provider.create = unavailable
    await payments.request(ctx, "buyer")
    assert not any(isinstance(m, RequestPayment) for m in ctx.sent)
    assert "free **care brief**" in ctx.sent[-1]
    assert not ctx.storage


@pytest.mark.parametrize("paid", [True, False])
async def test_expired_order_never_creates_second_checkout(workflow, research, paid):
    ctx, provider, payments, message = await prepare(workflow, research)
    scope = ctx.storage["report_reference:" + message.reference]
    ctx.storage["report_order:" + scope]["expires"] = time.time() - 1
    async def verified(order):
        return paid
    provider.verified = verified
    ctx.sent.clear()
    await payments.request(ctx, "buyer")
    assert provider.created == 1
    assert not any(isinstance(m, RequestPayment) for m in ctx.sent)
    assert ("TEST payment verified" if paid else "Do not pay again") in ctx.sent[-1]


@pytest.mark.parametrize("data", [[], {"metadata": None}, {"metadata": []}])
async def test_malformed_settlement_fails_closed(monkeypatch, data):
    monkeypatch.setenv("CARECOMPASS_PAYMENTS", "stripe_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_example")
    provider = StripeTestProvider(httpx.MockTransport(lambda req: httpx.Response(200, json=data)))
    assert not await provider.verified({"checkout": "cs_test_123", "reference": "ref"})


@pytest.mark.parametrize("field,value", [("livemode", True), ("id", "cs_live_123"),
    ("client_secret", None), ("expires_at", 0)])
async def test_invalid_checkout_is_not_offered(monkeypatch, field, value):
    monkeypatch.setenv("CARECOMPASS_PAYMENTS", "stripe_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_example")
    data = {"id": "cs_test_123", "client_secret": "cs_test_123_secret_example",
            "livemode": False, "expires_at": int(time.time()) + 1800}
    data[field] = value
    provider = StripeTestProvider(httpx.MockTransport(lambda req: httpx.Response(200, json=data)))
    with pytest.raises(ValueError):
        await provider.create("ref")


async def test_valid_checkout_and_settlement(monkeypatch):
    monkeypatch.setenv("CARECOMPASS_PAYMENTS", "stripe_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_example")
    data = {"id": "cs_test_123", "client_secret": "cs_test_123_secret_example",
            "livemode": False, "expires_at": int(time.time()) + 1800,
            "status": "complete", "payment_status": "paid", "amount_total": 100,
            "currency": "usd", "metadata": {"reference": "ref", "service": "carecompass_report"}}
    provider = StripeTestProvider(httpx.MockTransport(lambda req: httpx.Response(200, json=data)))
    assert (await provider.create("ref"))["id"] == "cs_test_123"
    assert await provider.verified({"checkout": "cs_test_123", "reference": "ref"})
