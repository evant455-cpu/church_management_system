import zoneinfo

from django.core.exceptions import ValidationError
from django.db import models


def validate_timezone(value):
    """Restrict to real IANA zone names without pulling in a new dependency."""
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f"{value!r} is not a recognized IANA timezone name.")


class TenantScopedModel(models.Model):
    """
    Abstract base for every tenant-scoped table: just the `congregation` FK.

    Every concrete subclass gets its own implicitly-named reverse accessor
    (e.g. `congregation.person_set`), since Django derives the default
    related_name from the *concrete* model name even when the field is
    defined on a shared abstract base -- no %(class)s gymnastics needed
    here because we're not overriding related_name.

    on_delete=PROTECT: there's no supported "delete a congregation" flow
    anywhere in this system yet (cancellation -> read_only/canceled status,
    never a row deletion), so the safe default is to block it outright
    rather than silently cascading a tenant's entire dataset away.
    """

    congregation = models.ForeignKey(
        "tenancy.Congregation",
        on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True


class Congregation(models.Model):
    """
    See onboarding_sequence_schema.md for why `owner_user` is nullable:
    a congregation needs a user to exist before it can be created, and a
    user needs a congregation to exist before *it* can be created. Postgres
    can defer FK checks within a transaction but not NOT NULL checks, so
    the "always has exactly one owner" guarantee is an application
    invariant (enforced by the signup service in Phase 5; enforced by hand
    via the shell/admin for this phase's testing), not a DB constraint.
    """

    name = models.CharField(max_length=200)
    owner_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="owned_congregations",
        help_text=(
            "The single source of truth for ownership -- this is what's "
            "actually checked anywhere 'is this the owner?' matters "
            "(billing, account deletion, transferring ownership), not a "
            "count of Owner-role assignments. Nullable only to break the "
            "creation-order circular dependency; the application always "
            "sets this immediately after creating a congregation."
        ),
    )
    timezone = models.CharField(
        max_length=50,
        validators=[validate_timezone],
        help_text="IANA timezone name, needed to correctly interpret service/schedule/attendance timestamps.",
    )
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    size_category = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text="e.g. '1-50', '51-200' -- optional, for onboarding personalization.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "congregations"

    def __str__(self):
        return self.name
