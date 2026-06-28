"""
Thin wrapper around the `stripe` SDK -- the *only* module in this
codebase allowed to import `stripe` directly. Everything else (services,
views, webhooks) calls through here.

Why this exists, rather than calling `stripe.SetupIntent.create(...)`
etc. directly from services.py: tests can mock these few functions by
name (`mock.patch("apps.billing.stripe_client.create_setup_intent")`)
instead of patching Stripe SDK call signatures at every call site, and
a future change to API version pinning, retry/backoff behavior, or
error normalization has exactly one place to live. Same separation
module_system draws between models.py/services.py and registry.py.

Nothing in here makes a real network call during the test suite --
every function below is mocked at this module's boundary in tests.
"""

from __future__ import annotations

import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

# Deliberately not pinning stripe.api_version here -- picking a specific
# dated version string without a real Stripe account to verify it
# against would be worse than leaving it on the account's configured
# default (which is what happens if we don't set it). Pin this once a
# real Stripe account exists and the current version has been confirmed
# in the Stripe Dashboard.


def create_setup_intent():
    """
    Step 3 of the signup wizard (onboarding_sequence_schema.md) --
    validates a card via Stripe Elements *before* any Customer or
    Subscription exists, and before any congregation row exists either.
    Takes no tenant argument for that reason.
    """
    return stripe.SetupIntent.create(usage="off_session")


def create_customer(*, email: str, name: str, payment_method_id: str):
    """Attaches the already-validated PaymentMethod as the default for invoices."""
    return stripe.Customer.create(
        email=email,
        name=name,
        payment_method=payment_method_id,
        invoice_settings={"default_payment_method": payment_method_id},
    )


def create_subscription(*, customer_id: str, price_id: str, trial_period_days: int):
    return stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}],
        trial_period_days=trial_period_days,
    )


def cancel_subscription(stripe_subscription_id: str):
    """
    Compensating action for Phase 5: cancels an orphaned Stripe
    subscription if the local DB transaction fails after
    create_customer()/create_subscription() already succeeded.
    """
    return stripe.Subscription.cancel(stripe_subscription_id)


def delete_customer(stripe_customer_id: str):
    """
    The other half of Phase 5's compensation. Canceling the subscription
    alone leaves the Customer (and the PaymentMethod create_customer()
    attached to it) behind -- and a PaymentMethod can only ever be
    attached to one Customer. Without this, a retry against the same
    cached payment_method_id (onboarding's session data is deliberately
    kept across a failed Finish attempt) fails with "already been
    attached to a customer", since the orphaned Customer from the failed
    attempt is still holding onto it. Deleting the Customer detaches it
    and frees it up for the retry.
    """
    return stripe.Customer.delete(stripe_customer_id)


def construct_webhook_event(payload: bytes, sig_header: str, webhook_secret: str):
    """
    Verifies the Stripe-Signature header and returns the parsed Event.
    Raises ValueError (malformed payload) or
    stripe.error.SignatureVerificationError (bad/missing signature) --
    the webhook view is responsible for catching both and responding
    with 400 rather than letting either propagate as a 500.
    """
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
