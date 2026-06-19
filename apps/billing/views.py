import stripe
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.module_system.access import access_required

from . import services, stripe_client
from .access import owner_required
from .models import Subscription


@access_required(billing_exempt=True)
@owner_required
def billing_status(request):
    """
    Minimal, unstyled Owner-only billing screen -- enough to exercise the
    billing_exempt carve-out and the Owner-only check through a real
    HTTP request, the same role Phase 2's module_list played for the
    module-enabled check. Real billing UI (card re-entry, invoices,
    "Reactivate" button wired to a real Stripe call) is future-phase
    polish; this phase's job is the gate, not the UI.
    """
    subscription = Subscription.objects.filter(congregation=request.user.congregation).first()
    return render(request, "billing/billing_status.html", {"subscription": subscription})


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    Stripe webhook receiver. No access_required/login_required here --
    Stripe is the caller, not a logged-in browser session. Signature
    verification (via the STRIPE_WEBHOOK_SECRET) is what stands in for
    authentication.

    Always returns quickly with 200 once the event is verified, even if
    process_webhook_event() decides there's nothing to do (unrecognized
    type, duplicate delivery, or a subscription we don't have a local
    row for yet) -- a 200 tells Stripe "received, don't retry"; only a
    bad signature or malformed payload is actually an error worth
    telling Stripe about via a non-2xx status.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe_client.construct_webhook_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponseBadRequest("Invalid payload or signature.")

    services.process_webhook_event(event)
    return HttpResponse(status=200)
