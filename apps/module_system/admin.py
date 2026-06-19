from django.contrib import admin

from .models import CongregationModule, CongregationModuleHistory, Module, ModuleDependency


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "sort_order", "is_retired", "created_at")
    list_filter = ("is_retired",)
    search_fields = ("key", "name")
    readonly_fields = ("created_at",)


@admin.register(ModuleDependency)
class ModuleDependencyAdmin(admin.ModelAdmin):
    list_display = ("module", "depends_on_module", "created_at")
    readonly_fields = ("created_at",)


@admin.register(CongregationModule)
class CongregationModuleAdmin(admin.ModelAdmin):
    list_display = ("congregation", "module", "is_enabled", "enabled_at", "disabled_at")
    list_filter = ("congregation", "module", "is_enabled")
    readonly_fields = ("enabled_at", "enabled_by", "disabled_at", "disabled_by")


@admin.register(CongregationModuleHistory)
class CongregationModuleHistoryAdmin(admin.ModelAdmin):
    list_display = ("congregation", "module", "action", "changed_by", "changed_at")
    list_filter = ("congregation", "module", "action")
    readonly_fields = ("changed_at",)
