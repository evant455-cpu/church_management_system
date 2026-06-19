"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('modules/', include('apps.module_system.urls')),
    path('billing/', include('apps.billing.urls')),
]
