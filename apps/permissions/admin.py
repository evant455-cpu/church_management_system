from django.contrib import admin

from .models import Permission, Role, RolePermission, UserPermissionOverride, UserRole


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "module", "action", "created_at")
    list_filter = ("module",)
    search_fields = ("code", "module", "action")
    readonly_fields = ("created_at",)


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0
    autocomplete_fields = ("permission",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "congregation", "is_system_default", "is_deletable")
    list_filter = ("congregation", "is_system_default", "is_deletable")
    search_fields = ("name", "slug")
    readonly_fields = ("created_at", "updated_at")
    inlines = [RolePermissionInline]


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "congregation", "created_at")
    list_filter = ("congregation", "role")
    search_fields = ("user__email", "role__name")
    readonly_fields = ("created_at",)


@admin.register(UserPermissionOverride)
class UserPermissionOverrideAdmin(admin.ModelAdmin):
    list_display = ("user", "permission", "effect", "created_by", "congregation", "created_at")
    list_filter = ("congregation", "effect")
    search_fields = ("user__email", "permission__code")
    readonly_fields = ("created_at", "updated_at")
