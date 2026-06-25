"""
Plain (non-Model) forms for each step of the signup wizard.

Deliberately not ModelForms: no Congregation, Person, or User row exists
yet at any step before "Finish" -- per onboarding_sequence_schema.md,
nothing is written to the database until the atomic transaction at the
end. Each form only validates input shape; `session_data()` returns the
plain dict that gets stashed into the session (see services.py).
"""

from __future__ import annotations

import zoneinfo

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import make_password

from apps.accounts.models import User
from apps.module_system.registry import AVAILABLE_MODULES


class AccountForm(forms.Form):
    """
    Step 1 -- the owner's name (becomes their `people` row) plus login
    credentials (becomes their `users` row). The two are collected
    together here even though they land in two different tables at
    "Finish", since from the signer-up's point of view it's just "create
    my account."
    """

    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    email = forms.EmailField()
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords don't match.")
        elif password1:
            # No saved User to validate against yet -- an unsaved, throwaway
            # instance lets UserAttributeSimilarityValidator still compare
            # against the email being entered right now. Same pattern
            # Django's own UserCreationForm uses internally.
            try:
                password_validation.validate_password(password1, User(email=cleaned.get("email", "")))
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def session_data(self) -> dict:
        """
        Never store the plaintext password, not even server-side, not
        even for the few minutes a wizard session lives -- hash it
        immediately and discard the plaintext the moment this form
        finishes validating.
        """
        return {
            "first_name": self.cleaned_data["first_name"],
            "last_name": self.cleaned_data["last_name"],
            "email": self.cleaned_data["email"],
            "password_hash": make_password(self.cleaned_data["password1"]),
        }


def _grouped_timezone_choices():
    """
    Groups by IANA area prefix (Africa/, America/, Etc/, ...) so the
    dropdown isn't one flat 400+ item list -- Django's ChoiceField/Select
    natively renders a list of (group_label, [(value, label), ...]) as
    <optgroup>s. Built from zoneinfo.available_timezones() directly (the
    same source tenancy.models.validate_timezone() checks against), so
    every option here is guaranteed valid -- no second list to keep in
    sync, and no path for an invalid value to reach the model.

    A handful of legacy top-level names (no "/" at all -- "UTC", "CET",
    "Singapore", and similar backward-compatibility aliases) don't have a
    real area prefix to group by. Without handling them, each one becomes
    its own single-item group named after itself, which renders as visual
    noise. They're still fully selectable (nothing here narrows what's
    valid), just bucketed under one "Other" group instead.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for tz in sorted(zoneinfo.available_timezones()):
        area = tz.split("/", 1)[0] if "/" in tz else "Other"
        groups.setdefault(area, []).append((tz, tz))
    # "Other" last rather than wherever it'd alphabetically fall --
    # it's a catch-all, not a real region, so it reads better at the end.
    other = groups.pop("Other", None)
    ordered = sorted(groups.items())
    if other:
        ordered.append(("Other", other))
    return ordered


TIMEZONE_CHOICES = _grouped_timezone_choices()

# Congregation size, for onboarding personalization only (see
# people_households_users_schema.md / README) -- not used to gate
# anything functionally. Ranges chosen to roughly track the commonly
# cited congregational-research breakpoints (family/pastoral/program/
# corporate-sized), rounded to numbers that read cleanly in a dropdown.
# The stored value is the range string itself, matching the
# `size_category` examples ("1-50", "51-200") documented in the schema.
SIZE_CATEGORY_CHOICES = [
    ("", "Prefer not to say"),
    ("1-50", "Small (1–50)"),
    ("51-200", "Medium (51–200)"),
    ("201-500", "Large (201–500)"),
    ("501+", "Very Large (501+)"),
]


class CongregationForm(forms.Form):
    """Step 2 -- congregation profile, matching tenancy.Congregation field-for-field."""

    name = forms.CharField(max_length=200)
    timezone = forms.ChoiceField(
        choices=TIMEZONE_CHOICES,
        help_text="Pick the zone where your congregation actually meets.",
    )
    address_line1 = forms.CharField(max_length=255, required=False)
    address_line2 = forms.CharField(max_length=255, required=False)
    city = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=100, required=False)
    postal_code = forms.CharField(max_length=20, required=False)
    country = forms.CharField(max_length=100, required=False)
    size_category = forms.ChoiceField(choices=SIZE_CATEGORY_CHOICES, required=False)

    _OPTIONAL_FIELDS = (
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
        "size_category",
    )

    def session_data(self) -> dict:
        data = dict(self.cleaned_data)
        for field in self._OPTIONAL_FIELDS:
            if not data.get(field):
                data[field] = None
        return data


class PaymentMethodForm(forms.Form):
    """
    Step 3 -- card validation.

    `payment_method_id` is populated client-side by Stripe.js after it
    confirms the SetupIntent (see templates/onboarding/step_payment.html)
    -- the card number itself never reaches this server, only Stripe's
    resulting PaymentMethod id.
    """

    payment_method_id = forms.CharField(widget=forms.HiddenInput)

    def session_data(self) -> dict:
        return {"payment_method_id": self.cleaned_data["payment_method_id"]}


class ModuleSelectionForm(forms.Form):
    """Step 4 -- which modules to enable at signup, with dependency validation."""

    modules = forms.MultipleChoiceField(
        choices=[(key, meta["name"]) for key, meta in AVAILABLE_MODULES.items()],
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="You can change this any time after signup from the module settings page.",
    )

    def clean_modules(self):
        selected = set(self.cleaned_data["modules"])
        missing = {}
        for key in selected:
            unmet = [dep for dep in AVAILABLE_MODULES[key].get("depends_on", []) if dep not in selected]
            if unmet:
                missing[key] = unmet
        if missing:
            details = "; ".join(
                f"{AVAILABLE_MODULES[key]['name']} needs "
                f"{', '.join(AVAILABLE_MODULES[dep]['name'] for dep in deps)} enabled too"
                for key, deps in missing.items()
            )
            raise forms.ValidationError(f"Some selected modules need a prerequisite enabled: {details}.")
        return selected

    def session_data(self) -> dict:
        return {"modules": sorted(self.cleaned_data["modules"])}
