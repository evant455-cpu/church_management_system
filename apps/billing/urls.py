from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.billing_status, name="billing_status"),
    path("webhook/", views.stripe_webhook, name="stripe_webhook"),
]
