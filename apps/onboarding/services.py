"""
Signup wizard session management + the atomic "Finish" transaction.

Wizard state across steps 1-4 lives in request.session (a plain Django
session, not a new DB model and not signed hidden fields -- see chat for
the comparison: sessions are already-wired infrastructure (Phase 0's
migrations include django.contrib.sessions), server-side by default, and
need zero new code to get expiry/cleanup). Nothing in this module writes
to congregations/people/users/etc. until complete_signup() runs.

`stripe` is imported directly here (not just apps.billing.stripe_client)
purely to catch stripe.error.StripeError -- the same precedent
apps.billing.views already sets for stripe.error.SignatureVerificationError.
"""

from __future__ import annotations

import logging

import stripe
from django.conf import settings
from django.db import transaction

from apps.billing import services as billing_services
from apps.accounts.models import User
from apps.module_system.models import CongregationModuleHistory, Module
from apps.module_system.services import initialize_congregation_modules
from apps.people.models import Person
from apps.permissions.services import assign_role_to_user, copy_default_roles_to_congregation
from apps.tenancy.models import Congregation

logger = logging.getLogger(__name__)

SESSION_KEY = "signup_wizard"
SETUP_INTENT_SESSION_KEY = "signup_wizard_setup_intent_secret"

# Steps must be completed in this order; "Finish" requires all four.
STEP_ORDER = ("account", "congregation", "payment", "modules")

# Total local-transaction attempts at "Finish" before compensating (one
# initial attempt + two retries) -- see chat: a failure at this exact
# point is most likely a transient DB blip, not a problem with the
# signer-up's input, so it's worth absorbing cheaply before resorting to
# the more drastic (and slower-to-recover-from) Stripe cancellation path.
LOCAL_TRANSACTION_MAX_ATTEMPTS = 3


class StripeSetupFailed(Exception):
    """
    Raised when create_stripe_customer_and_subscription() itself fails
    (e.g. a declined card). Nothing local has been touched at this point
    -- per onboarding_sequence_schema.md's documented "abandoned signup"
    case, this is fully safe to retry from the same Finish step with the
    same session data, no compensation needed.
    """


class SignupTransactionFailed(Exception):
    """
    Raised when the local transaction never succeeded even after
    retrying, *after* a real Stripe Customer/Subscription had already
    been created. By the time this is raised, compensation (canceling
    that Stripe subscription) has already been attempted.
    """


# --- Wizard session state ---------------------------------------------------


def get_wizard_state(session) -> dict:
    return session.get(SESSION_KEY, {})


def update_wizard_state(session, step: str, data: dict) -> None:
    state = session.get(SESSION_KEY, {})
    state[step] = data
    session[SESSION_KEY] = state


def clear_wizard_state(session) -> None:
    session.pop(SESSION_KEY, None)
    session.pop(SETUP_INTENT_SESSION_KEY, None)


def completed_steps(session) -> set:
    return set(get_wizard_state(session).keys())


def first_missing_step(session):
    """The earliest step in STEP_ORDER not yet completed, or None once all four are done."""
    done = completed_steps(session)
    for step in STEP_ORDER:
        if step not in done:
            return step
    return None


def get_or_create_setup_intent_client_secret(session) -> str:
    """
    Cache the SetupIntent's client_secret in session so re-rendering step
    3 (a page refresh, the browser back button) doesn't create a fresh
    SetupIntent with Stripe every time -- one per wizard session is
    enough. An abandoned wizard just leaves an unused SetupIntent, which
    Stripe expires on its own (onboarding_sequence_schema.md).
    """
    secret = session.get(SETUP_INTENT_SESSION_KEY)
    if not secret:
        intent = billing_services.create_setup_intent()
        secret = intent.client_secret
        session[SETUP_INTENT_SESSION_KEY] = secret
    return secret


# --- The "Finish" transaction ------------------------------------------------


def _write_signup_rows(*, account, congregation_data, modules_selected, stripe_customer, stripe_subscription):
    """
    The one atomic transaction tying everything together, in the order
    onboarding_sequence_schema.md documents. Raises on any failure --
    the caller (complete_signup) owns retry/compensation, not this
    function, so this stays a single straightforward attempt.
    """
    with transaction.atomic():
        congregation = Congregation.objects.create(**congregation_data)

        person = Person.objects.create(
            congregation=congregation,
            first_name=account["first_name"],
            last_name=account["last_name"],
        )

        user = User(congregation=congregation, person=person, email=account["email"])
        user.password = account["password_hash"]  # already hashed at step 1 -- never re-hash a hash
        user.save()

        congregation.owner_user = user
        congregation.save(update_fields=["owner_user"])

        roles_by_slug = copy_default_roles_to_congregation(congregation)
        assign_role_to_user(user, roles_by_slug["owner"])

        initialize_congregation_modules(congregation, enabled_keys=modules_selected)
        for module in Module.objects.filter(key__in=modules_selected):
            CongregationModuleHistory.objects.create(
                congregation=congregation,
                module=module,
                action=CongregationModuleHistory.Action.ENABLED,
                changed_by=user,
            )

        billing_services.create_subscription_record(
            congregation=congregation,
            stripe_customer=stripe_customer,
            stripe_subscription=stripe_subscription,
        )

    return user, congregation


def complete_signup(*, account: dict, congregation_data: dict, modules_selected, payment_method_id: str):
    """
    The "Finish" step. Two real Stripe calls happen first (outside any
    local transaction, per onboarding_sequence_schema.md), then the local
    transaction, with bounded inline retry and Stripe-cancellation
    compensation if the local side never recovers.

    Safe to call again with the same arguments after either exception --
    StripeSetupFailed means nothing local or remote exists yet; after
    SignupTransactionFailed, the prior Stripe Customer/Subscription has
    already been canceled, so a retry simply creates a fresh pair rather
    than reusing the canceled one.

    Returns (user, congregation) on success.
    """
    owner_name = f"{account['first_name']} {account['last_name']}"
    try:
        customer, stripe_subscription = billing_services.create_stripe_customer_and_subscription(
            email=account["email"],
            name=owner_name,
            payment_method_id=payment_method_id,
            price_id=settings.STRIPE_PRICE_ID,
            trial_period_days=settings.STRIPE_TRIAL_PERIOD_DAYS,
        )
    except stripe.error.StripeError as exc:
        raise StripeSetupFailed(str(exc)) from exc

    last_error = None
    for attempt in range(1, LOCAL_TRANSACTION_MAX_ATTEMPTS + 1):
        try:
            return _write_signup_rows(
                account=account,
                congregation_data=congregation_data,
                modules_selected=modules_selected,
                stripe_customer=customer,
                stripe_subscription=stripe_subscription,
            )
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any failure here means
            # retry, then compensate, regardless of the specific DB error class.
            last_error = exc
            logger.warning(
                "Signup local transaction attempt %s/%s failed for %s: %s",
                attempt,
                LOCAL_TRANSACTION_MAX_ATTEMPTS,
                account.get("email"),
                exc,
            )

    try:
        billing_services.cancel_stripe_subscription_for_compensation(stripe_subscription.id)
        logger.error(
            "Signup local transaction failed after %s attempts for %s; "
            "compensated by canceling stripe subscription %s.",
            LOCAL_TRANSACTION_MAX_ATTEMPTS,
            account.get("email"),
            stripe_subscription.id,
        )
    except Exception:
        # The documented backstop reconciliation job (a periodic sweep
        # for orphaned Stripe subscriptions with no local Subscription
        # row) isn't built in this phase -- PROJECT_PLAN.md's Phase 5
        # scope is the compensating *action*, not that job. This is the
        # one case current code can't fully recover from on its own.
        logger.critical(
            "Signup compensation FAILED -- stripe subscription %s for %s is orphaned "
            "and needs manual cleanup (no backstop reconciliation job built yet).",
            stripe_subscription.id,
            account.get("email"),
            exc_info=True,
        )

    raise SignupTransactionFailed(
        "Could not finish creating your account. Your card was not charged."
    ) from last_error
