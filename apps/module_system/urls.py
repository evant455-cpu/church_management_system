from django.urls import path

from . import views

app_name = "module_system"

urlpatterns = [
    path("", views.module_list, name="module_list"),
    path("<str:module_key>/toggle/", views.toggle_module, name="toggle_module"),
]
