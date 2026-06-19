from django.contrib import admin

from .models import Subscription, SubscriptionEvent


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "congregation",
        "status",
        "stripe_customer_id",
        "stripe_subscription_id",
        "trial_ends_at",
        "current_period_end",
    )
    list_filter = ("status",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ("congregation", "event_type", "source", "stripe_event_id", "occurred_at")
    list_filter = ("source", "event_type")
