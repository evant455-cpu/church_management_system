"""
Signup wizard views -- one Django view per step (account, congregation,
payment, modules) plus the final "Finish" view. Plain server-rendered
forms throughout, no JS framework -- the one unavoidable bit of browser
JS is step 3's Stripe Elements card field, and that's Stripe's own
drop-in widget, not custom interactivity built here. Real production
styling/polish is explicitly out of scope for this phase.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.urls import reverse

from . import services
from .forms import AccountForm, CongregationForm, ModuleSelectionForm, PaymentMethodForm

_STEP_URL_NAMES = {
    "account": "onboarding:step_account",
    "congregation": "onboarding:step_congregation",
    "payment": "onboarding:step_payment",
    "modules": "onboarding:step_modules",
}


def _redirect_to_current_step(request):
    """Anyone hitting a step out of order (or Finish before it's ready) gets bounced to wherever they actually left off."""
    missing = services.first_missing_step(request.session)
    return redirect(_STEP_URL_NAMES.get(missing, "onboarding:step_account"))


def step_account(request):
    state = services.get_wizard_state(request.session)
    if request.method == "POST":
        form = AccountForm(request.POST)
        if form.is_valid():
            services.update_wizard_state(request.session, "account", form.session_data())
            return redirect("onboarding:step_congregation")
    else:
        initial = {k: v for k, v in state.get("account", {}).items() if k != "password_hash"}
        form = AccountForm(initial=initial)
    return render(request, "onboarding/step_account.html", {"form": form})


def step_congregation(request):
    if "account" not in services.completed_steps(request.session):
        return redirect("onboarding:step_account")

    state = services.get_wizard_state(request.session)
    if request.method == "POST":
        form = CongregationForm(request.POST)
        if form.is_valid():
            services.update_wizard_state(request.session, "congregation", form.session_data())
            return redirect("onboarding:step_payment")
    else:
        form = CongregationForm(initial=state.get("congregation", {}))
    return render(request, "onboarding/step_congregation.html", {"form": form})


def step_payment(request):
    if "congregation" not in services.completed_steps(request.session):
        return redirect("onboarding:step_congregation")

    if request.method == "POST":
        form = PaymentMethodForm(request.POST)
        if form.is_valid():
            services.update_wizard_state(request.session, "payment", form.session_data())
            return redirect("onboarding:step_modules")
    else:
        form = PaymentMethodForm()

    client_secret = services.get_or_create_setup_intent_client_secret(request.session)
    return render(
        request,
        "onboarding/step_payment.html",
        {
            "form": form,
            "client_secret": client_secret,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        },
    )


def step_modules(request):
    if "payment" not in services.completed_steps(request.session):
        return redirect("onboarding:step_payment")

    state = services.get_wizard_state(request.session)
    if request.method == "POST":
        form = ModuleSelectionForm(request.POST)
        if form.is_valid():
            services.update_wizard_state(request.session, "modules", form.session_data())
            return redirect("onboarding:finish")
    else:
        form = ModuleSelectionForm(initial={"modules": state.get("modules", {}).get("modules", [])})
    return render(request, "onboarding/step_modules.html", {"form": form})


def finish(request):
    """
    GET shows a review screen; POST actually runs the Stripe calls + the
    local transaction. Splitting these means a page refresh on this step
    never double-submits a card charge -- the dangerous part only ever
    runs on an explicit POST, mirroring the same GET/POST split every
    other step already uses for its own (much smaller) write.
    """
    if services.first_missing_step(request.session) is not None:
        return _redirect_to_current_step(request)

    state = services.get_wizard_state(request.session)

    if request.method == "POST":
        try:
            user, congregation = services.complete_signup(
                account=state["account"],
                congregation_data=state["congregation"],
                modules_selected=state["modules"]["modules"],
                payment_method_id=state["payment"]["payment_method_id"],
            )
        except services.StripeSetupFailed as exc:
            return render(
                request,
                "onboarding/finish_error.html",
                {"message": str(exc)},
                status=400,
            )
        except services.SignupTransactionFailed as exc:
            return render(
                request,
                "onboarding/finish_error.html",
                {"message": str(exc)},
                status=500,
            )

        services.clear_wizard_state(request.session)
        login(request, user)
        return redirect(reverse("home"))

    return render(request, "onboarding/finish_review.html", {"state": state})
