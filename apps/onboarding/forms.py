"""
Plain (non-Model) forms for each step of the signup wizard.

Deliberately not ModelForms: no Congregation, Person, or User row exists
yet at any step before "Finish" -- per onboarding_sequence_schema.md,
nothing is written to the database until the atomic transaction at the
end. Each form only validates input shape; `session_data()` returns the
plain dict that gets stashed into the session (see services.py).
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import make_password

from apps.accounts.models import User
from apps.module_system.registry import AVAILABLE_MODULES
from apps.tenancy.models import validate_timezone


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


class CongregationForm(forms.Form):
    """Step 2 -- congregation profile, matching tenancy.Congregation field-for-field."""

    name = forms.CharField(max_length=200)
    timezone = forms.CharField(max_length=50, help_text="IANA name, e.g. 'America/Chicago'.")
    address_line1 = forms.CharField(max_length=255, required=False)
    address_line2 = forms.CharField(max_length=255, required=False)
    city = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=100, required=False)
    postal_code = forms.CharField(max_length=20, required=False)
    country = forms.CharField(max_length=100, required=False)
    size_category = forms.CharField(max_length=30, required=False)

    _OPTIONAL_FIELDS = (
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
        "size_category",
    )

    def clean_timezone(self):
        value = self.cleaned_data["timezone"]
        # Reuses tenancy.models.validate_timezone rather than re-implementing
        # the same zoneinfo.available_timezones() check a second time --
        # it raises django.core.exceptions.ValidationError, which is the
        # exact same class forms.ValidationError aliases.
        validate_timezone(value)
        return value

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
