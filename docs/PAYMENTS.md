# Optional preparation report / Payment Protocol

Status: implemented sandbox integration, disabled by default. No seller account is configured and no real checkout has been demonstrated. This is not yet evidence for a working payment bonus.

## Product and proposed monetization

Free: emergency guidance, hospital navigation, evidence and conflicts, saving/retrieving the shortlist, and `care brief`.

Optional prototype: `buy preparation report` requests a **$1.00 USD test checkout** for an expanded comparison and reusable call-notes report, delivered in the conversation. The proposed business model charges for organising evidence into a preparation report, not medical advice, referrals, insurer approval, booking or priority care. The report uses saved evidence; it does not claim new research. Price and demand are unvalidated. No real-money production sales are enabled.

## Implementation

The coordinator publishes Fetch's `AgentPaymentProtocol` with the seller role. It sends `RequestPayment`; handles `CommitPayment` and `RejectPayment`; and replies with `CompletePayment` only after retrieving Stripe's Checkout Session server-side, or `CancelPayment` when verification fails.

The order binds the payer, chat session, recipient, reference, exact amount/currency/payment method, and Stripe Checkout ID. Settlement must be paid, complete, test-mode and tied to this order's metadata. Repeated commits return the same report without creating another checkout or charging again. Persisted order records contain saved-reference IDs, not copies of health reports. A deleted shortlist cannot be recovered through the paid report.

Only test keys are accepted. Configuration:

```
CARECOMPASS_PAYMENTS=stripe_test
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
```

Keep these in private `.env`. Do not commit them. Stripe receives a generic product name and random order reference, no medical concern, hospital, insurer, report text or policy ID.

## Validation and limits

Automated tests exercise order binding, forged/mismatched commits, settlement checks, replay and live-key rejection using fake providers/HTTP responses. These are not real payment tests. Before claiming a demo, configure a Stripe sandbox and manually complete the test checkout, then verify report delivery and rejection paths.

Fetch's official Stripe example warns that embedded checkout is supported in the Agentverse inspector and may not render in ordinary ASI:One chat. Verify the actual target UI; do not claim an entirely in-chat paid journey until observed.

Production remains disabled pending seller onboarding, payment UI compatibility, refunds/support, retention/deletion policy for order metadata, reconciliation of paid-but-undelivered orders, taxes/currency/consumer disclosures, and price validation. There is no refund API or live-money mode in this prototype.

References: [Fetch Stripe example](https://innovationlab.fetch.ai/resources/docs/examples/agent-transaction/stripe-horoscope-payment-protocol), [Payment Protocol](https://uagents.fetch.ai/docs/guides/agent-payment-protocol).

## Hardening verified on 24 October

Checkout creation validates a test session ID, test mode, client-secret binding and expiry. Provider failures produce a recoverable message without a payment request. Malformed settlement data fails closed. An expired order is reconciled before any action: a verified paid order delivers its report; otherwise no replacement checkout is created and the user is told not to pay again. `*_data.json` agent storage is git-ignored because it can contain checkout metadata. These paths are covered by mocked-provider tests, not live Stripe transactions.

## Fixes on 24 October (evening)

- **RequestPayment metadata** now follows Fetch's Stripe example: `metadata.stripe` carries `client_secret`, `publishable_key`, `checkout_session_id`, `id`, `currency`, `amount`, `amount_cents` and `ui_mode: "embedded"`, and `metadata.service` names the product. All values are strings, because `uagents_core`'s `RequestPayment.metadata` only accepts `str | dict[str, str]` (an integer `amount_cents` would fail validation).
- **No more permanent lock-out after expiry.** Previously an expired, unpaid checkout blocked the paid report for that shortlist forever. Now the agent asks Stripe: if the session is *paid*, the report is delivered; if Stripe reports it `expired` **and** `unpaid` for this order's reference, the old reference is revoked and one fresh checkout is issued (no double charge is possible); in any other state the user is told not to pay again.
- **Trigger phrases**: `buy report`, `get the preparation report`, `purchase premium report`, `pay for report` and the original `buy preparation report`.
- Tests: `test_confirmed_expired_unpaid_checkout_is_reissued_once`, `test_request_metadata_matches_fetch_stripe_shape`.
