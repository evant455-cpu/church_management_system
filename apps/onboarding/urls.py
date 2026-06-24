from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("", views.step_account, name="start"),
    path("account/", views.step_account, name="step_account"),
    path("congregation/", views.step_congregation, name="step_congregation"),
    path("payment/", views.step_payment, name="step_payment"),
    path("modules/", views.step_modules, name="step_modules"),
    path("finish/", views.finish, name="finish"),
]
