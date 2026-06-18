from django.contrib import admin

from .models import Congregation


@admin.register(Congregation)
class CongregationAdmin(admin.ModelAdmin):
    list_display = ("name", "owner_user", "timezone", "size_category", "created_at")
    search_fields = ("name",)
    list_filter = ("timezone",)
    readonly_fields = ("created_at", "updated_at")
