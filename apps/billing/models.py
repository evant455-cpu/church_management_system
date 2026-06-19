from django.db import models

from apps.tenancy.models import TenantScopedModel


class Subscription(TenantScopedModel):
    """
    One row per congregation -- see subscription_billing_schema.md.

    `congregation` is overridden from TenantScopedModel's plain
    ForeignKey to a OneToOneField: the schema documents
    `congregation_id` as `not null, unique` ("one subscription per
    congregation"), and overriding a field inherited from an abstract
    base by redeclaring it under the same name is normal Django
    (https://docs.djangoproject.com/en/stable/topics/db/models/#abstract-base-classes).
    on_delete stays PROTECT, matching TenantScopedModel's documented
    rationale -- there's no supported "delete a congregation" flow.

    Created by create_subscription_record() (see services.py) as part
    of Phase 5's signup transaction -- never directly. Until that real
    signup flow exists, a congregation simply has no Subscription row;
    the access gate (module_system.access) treats that as fully blocked
    rather than fully open, so any test/dev congregation that needs to
    exercise module-owned views has to create one explicitly.
    """

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past Due"
        READ_ONLY = "read_only", "Read Only"
        CANCELED = "canceled", "Canceled"

    congregation = models.OneToOneField(
        "tenancy.Congregation",
        on_delete=models.PROTECT,
        related_name="subscription",
    )
    stripe_customer_id = models.CharField(max_length=255)
    stripe_subscription_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices)
    cancel_at_period_end = models.BooleanField(
        default=False,
        help_text=(
            "Display-only (e.g. 'your subscription ends on [date]') -- "
            "the access gate keys off `status`, not this field, since "
            "Stripe doesn't end a subscription early just because "
            "cancellation was requested."
        ),
    )
    trial_ends_at = models.DateTimeField(blank=True, null=True)
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    canceled_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions"

    def __str__(self):
        return f"{self.congregation} ({self.status})"


class SubscriptionEvent(TenantScopedModel):
    """
    Append-only audit log -- same pattern as CongregationModuleHistory.

    `stripe_event_id` carries a partial unique constraint (only enforced
    when not null, since admin_action-sourced rows don't have one) --
    the DB-level backstop for webhook idempotency, alongside the
    application-level check-before-insert in services.process_webhook_event().
    Deliberately a *global* uniqueness constraint, not scoped to
    `congregation`: Stripe event IDs (`evt_...`) are unique across the
    whole Stripe platform, not just within one customer's events.

    `event_type` is intentionally a plain CharField, not a choices=
    enum -- the schema describes it with "e.g." examples
    (trial_started, payment_succeeded, ...), not an exhaustive list, and
    Stripe's own event vocabulary is large enough that a hard-coded
    Django choices migration for every value we might ever want to log
    would be more friction than it's worth.
    """

    class Source(models.TextChoices):
        STRIPE_WEBHOOK = "stripe_webhook", "Stripe Webhook"
        ADMIN_ACTION = "admin_action", "Admin Action"

    event_type = models.CharField(max_length=50)
    source = models.CharField(max_length=20, choices=Source.choices)
    stripe_event_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="For idempotency -- Stripe can redeliver the same webhook.",
    )
    occurred_at = models.DateTimeField(
        help_text=(
            "When the event actually happened (set explicitly by the "
            "caller -- the Stripe event's own `created` timestamp for "
            "webhook-sourced rows, or timezone.now() for admin actions), "
            "not when this row was inserted -- webhooks can be retried "
            "or delayed, so the two aren't the same thing."
        )
    )

    class Meta:
        db_table = "subscription_events"
        ordering = ["-occurred_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["stripe_event_id"],
                condition=models.Q(stripe_event_id__isnull=False),
                name="uniq_subscription_event_stripe_event_id",
            ),
        ]

    def __str__(self):
        return f"{self.congregation} {self.event_type} @ {self.occurred_at}"
