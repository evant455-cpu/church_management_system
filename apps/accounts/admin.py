from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeForm, UserCreationForm
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User

    list_display = ("email", "congregation", "person", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "is_superuser", "congregation")
    search_fields = ("email", "person__first_name", "person__last_name")
    ordering = ("email",)
    autocomplete_fields = ["person"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identity", {"fields": ("congregation", "person")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"fields": ("email", "congregation", "person", "password1", "password2")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")
    filter_horizontal = ("groups", "user_permissions")
