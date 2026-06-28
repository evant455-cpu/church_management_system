"""
Billing business logic: the Stripe SetupIntent -> Customer -> Subscription
scaffolding Phase 5's signup transaction will call, and the webhook
event processor that keeps `Subscription.status` in sync with Stripe.

Mirrors module_system's split: stripe_client.py is the only place that
talks to Stripe; this file is the only place that decides what those
calls mean for our own data.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.utils import timezone

from . import stripe_client
from .models import Subscription, SubscriptionEvent

# Stripe's status vocabulary is richer than our 5-state model (see
# subscription_billing_schema.md) -- this is the one place that
# collapses it down. The original Stripe event type is still logged
# verbatim into SubscriptionEvent for full audit fidelity regardless of
# how it gets mapped here.
STRIPE_STATUS_MAP = {
    "trialing": Subscription.Status.TRIALING,
    "active": Subscription.Status.ACTIVE,
    "past_due": Subscription.Status.PAST_DUE,
    # Stripe's automatic retries are exhausted but the subscription
    # hasn't been deleted -- this *is* our read_only state.
    "unpaid": Subscription.Status.READ_ONLY,
    "canceled": Subscription.Status.CANCELED,
    # First invoice payment hasn't completed yet (e.g. still needs 3DS
    # confirmation). Our SetupIntent step should make this rare, but if
    # it happens, treat it like past_due rather than locking the
    # congregation out of an account it just tried to create.
    "incomplete": Subscription.Status.PAST_DUE,
    # The above never resolved within Stripe's window -- it never
    # became a real subscription.
    "incomplete_expired": Subscription.Status.CANCELED,
    # Pause-collection isn't a feature this app exposes, but map
    # defensively in case it's ever set from the Stripe Dashboard.
    "paused": Subscription.Status.READ_ONLY,
}

# Stripe event types this app updates Subscription.status from -- ones
# that carry (or imply) the subscription's own status.
_STATUS_BEARING_EVENT_TYPES = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}

# Stripe event types logged purely for audit fidelity -- they don't
# carry a subscription status, so they never mutate Subscription.status
# (avoids two competing sources of truth for what `status` means).
_INVOICE_EVENT_TYPES = {
    "invoice.payment_succeeded": "payment_succeeded",
    "invoice.payment_failed": "payment_failed",
}

_STATUSES_NEEDING_RECOVERY = frozenset(
    {Subscription.Status.READ_ONLY, Subscription.Status.CANCELED, Subscription.Status.PAST_DUE}
)
_STATUSES_MEANING_RECOVERED = frozenset({Subscription.Status.ACTIVE, Subscription.Status.TRIALING})


def _to_datetime(unix_ts):
    if unix_ts is None:
        return None
    return datetime.datetime.fromtimestamp(unix_ts, tz=datetime.timezone.utc)


def _subscription_period(stripe_subscription):
    """
    Stripe's Basil API version (2025-03-31) removed current_period_start
    and current_period_end from the top-level Subscription object --
    they now live on each subscription item instead. See
    https://docs.stripe.com/changelog/basil/2025-03-31/deprecate-subscription-current-period-start-and-end.

    This app only ever creates a single-item subscription (one price,
    no add-ons -- subscription_billing_schema.md's single-tier model),
    so the first item's period is the subscription's period for our
    purposes. Returns (None, None) if items are missing entirely rather
    than raising, since a malformed/partial webhook payload shouldn't
    crash event processing.
    """
    items_data = (stripe_subscription.get("items") or {}).get("data") or []
    if not items_data:
        return None, None
    first_item = items_data[0]
    return first_item.get("current_period_start"), first_item.get("current_period_end")


# --- Signup-flow scaffolding (called by Phase 5) ---------------------------


def create_setup_intent():
    """Thin pass-through -- kept here so Phase 5 imports services, never stripe_client, directly."""
    return stripe_client.create_setup_intent()


def create_stripe_customer_and_subscription(*, email, name, payment_method_id, price_id, trial_period_days):
    """
    The two real Stripe calls made on signup's "Finish" step, *before*
    the local DB transaction opens (onboarding_sequence_schema.md).

    Returns (customer, subscription) -- the raw Stripe objects, so the
    caller can pull ids/trial_end/current_period_start/end out of
    `subscription` for create_subscription_record() inside the local
    transaction. Raises whatever stripe.error.StripeError subclass on
    failure -- safe to let propagate, since nothing local exists yet at
    this point (per the documented "fully safe, nothing dangerous on
    either side" abandonment case).
    """
    customer = stripe_client.create_customer(email=email, name=name, payment_method_id=payment_method_id)
    subscription = stripe_client.create_subscription(
        customer_id=customer.id, price_id=price_id, trial_period_days=trial_period_days
    )
    return customer, subscription


def cancel_stripe_subscription_for_compensation(stripe_subscription_id):
    """
    Phase 5's compensating action if the local transaction fails *after*
    create_stripe_customer_and_subscription() already succeeded. Phase 5
    is responsible for the retry/backstop-reconciliation-job behavior
    documented in onboarding_sequence_schema.md if this call itself
    fails -- not built here, this is just the primitive it needs.
    """
    return stripe_client.cancel_subscription(stripe_subscription_id)


def delete_stripe_customer_for_compensation(stripe_customer_id):
    """
    The other half of compensation -- see stripe_client.delete_customer()
    for why this has to happen too, not just the subscription
    cancellation above.
    """
    return stripe_client.delete_customer(stripe_customer_id)


def create_subscription_record(*, congregation, stripe_customer, stripe_subscription):
    """
    Local DB half of signup's "Finish" transaction. Deliberately does
    NOT open its own transaction.atomic() block -- this composes inside
    Phase 5's single larger transaction (alongside congregations,
    people, users, roles, congregation_modules, ...), rather than
    fighting it for atomicity. Callers in this phase's tests wrap it
    themselves.
    """
    period_start, period_end = _subscription_period(stripe_subscription)
    subscription = Subscription.objects.create(
        congregation=congregation,
        stripe_customer_id=stripe_customer.id,
        stripe_subscription_id=stripe_subscription.id,
        status=STRIPE_STATUS_MAP.get(stripe_subscription.status, Subscription.Status.TRIALING),
        trial_ends_at=_to_datetime(stripe_subscription.trial_end),
        current_period_start=_to_datetime(period_start),
        current_period_end=_to_datetime(period_end),
    )
    SubscriptionEvent.objects.create(
        congregation=congregation,
        event_type="trial_started",
        source=SubscriptionEvent.Source.ADMIN_ACTION,
        occurred_at=timezone.now(),
    )
    return subscription


# --- Webhook processing -----------------------------------------------------


def process_webhook_event(event):
    """
    Idempotently apply one *already signature-verified* Stripe event to
    local state (the webhook view is responsible for verification --
    this function trusts `event` completely).

    Returns True if newly processed, False if it was a no-op: either a
    duplicate delivery (Stripe redelivers the same event on transient
    failures) caught by the same stripe_event_id check the DB's partial
    unique constraint backs up, or simply an event type this app doesn't
    act on. Unrecognized types are intentionally not logged at all --
    Stripe's webhook vocabulary is large, and an unhandled type isn't an
    error condition worth an audit row.
    """
    if SubscriptionEvent.objects.filter(stripe_event_id=event.id).exists():
        return False

    if event.type in _STATUS_BEARING_EVENT_TYPES:
        return _process_subscription_status_event(event)
    if event.type in _INVOICE_EVENT_TYPES:
        return _process_invoice_event(event)
    return False


def _process_subscription_status_event(event):
    stripe_subscription_id = event.data.object.id
    with transaction.atomic():
        try:
            subscription = Subscription.objects.select_for_update().get(
                stripe_subscription_id=stripe_subscription_id
            )
        except Subscription.DoesNotExist:
            # A webhook for a subscription we don't have a local row for
            # yet -- e.g. it arrived before Phase 5's local commit landed.
            # Nothing to update; not an error.
            return False

        old_status = subscription.status
        if event.type == "customer.subscription.deleted":
            new_status = Subscription.Status.CANCELED
        else:
            new_status = STRIPE_STATUS_MAP.get(event.data.object.status, old_status)

        if old_status in _STATUSES_NEEDING_RECOVERY and new_status in _STATUSES_MEANING_RECOVERED:
            app_event_type = "reactivated"
        elif event.type == "customer.subscription.deleted":
            app_event_type = "canceled"
        elif event.type == "customer.subscription.created":
            app_event_type = "trial_started" if new_status == Subscription.Status.TRIALING else "status_changed"
        else:
            app_event_type = "status_changed"

        subscription.status = new_status
        cancel_at_period_end = event.data.object.get("cancel_at_period_end")
        if cancel_at_period_end is not None:
            subscription.cancel_at_period_end = cancel_at_period_end
        trial_end = event.data.object.get("trial_end")
        if trial_end is not None:
            subscription.trial_ends_at = _to_datetime(trial_end)
        period_start, period_end = _subscription_period(event.data.object)
        if period_start is not None:
            subscription.current_period_start = _to_datetime(period_start)
        if period_end is not None:
            subscription.current_period_end = _to_datetime(period_end)
        if new_status == Subscription.Status.CANCELED and old_status != Subscription.Status.CANCELED:
            subscription.canceled_at = timezone.now()
        subscription.save()

        SubscriptionEvent.objects.create(
            congregation=subscription.congregation,
            event_type=app_event_type,
            source=SubscriptionEvent.Source.STRIPE_WEBHOOK,
            stripe_event_id=event.id,
            occurred_at=_to_datetime(event.created),
        )
    return True


def _process_invoice_event(event):
    stripe_subscription_id = event.data.object.get("subscription")
    if not stripe_subscription_id:
        return False
    try:
        subscription = Subscription.objects.get(stripe_subscription_id=stripe_subscription_id)
    except Subscription.DoesNotExist:
        return False

    SubscriptionEvent.objects.create(
        congregation=subscription.congregation,
        event_type=_INVOICE_EVENT_TYPES[event.type],
        source=SubscriptionEvent.Source.STRIPE_WEBHOOK,
        stripe_event_id=event.id,
        occurred_at=_to_datetime(event.created),
    )
    return True
