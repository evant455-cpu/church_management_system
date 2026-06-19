from django.db import models

from apps.tenancy.models import TenantScopedModel


class Module(models.Model):
    """
    System-wide, auto-synced from AVAILABLE_MODULES on every `migrate` --
    see registry.py and services.sync_modules(). Never edited by hand and
    never deleted: a module that's removed from the registry gets
    is_retired=True instead, preserving FK integrity for any historical
    rows (permissions, congregation_modules, history) that reference it.
    """

    key = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)
    is_retired = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "modules"
        ordering = ["sort_order", "key"]

    def __str__(self):
        return self.name


class ModuleDependency(models.Model):
    """
    System-wide, auto-synced alongside Module from each registry entry's
    `depends_on` list. Fully derived data -- never created or edited
    directly, only ever through sync_modules().
    """

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="dependencies")
    depends_on_module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="dependents")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "module_dependencies"
        constraints = [
            models.UniqueConstraint(
                fields=["module", "depends_on_module"], name="uniq_module_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(module=models.F("depends_on_module")),
                name="module_dependency_not_self",
            ),
        ]

    def __str__(self):
        return f"{self.module} depends on {self.depends_on_module}"


class CongregationModule(TenantScopedModel):
    """
    One row per (congregation, module) pair. Populated via
    services.initialize_congregation_modules() -- never an "absent" state
    to special-case in queries; a congregation either has a row that's
    enabled or a row that's disabled, always one or the other.

    No created_at/updated_at -- not in the documented schema for this
    table (enabled_at/disabled_at already capture the meaningful instants).
    """

    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name="congregation_modules")
    is_enabled = models.BooleanField(default=False)
    enabled_at = models.DateTimeField(blank=True, null=True)
    enabled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
        help_text="Nullable audit attribution -- losing the user shouldn't block the row from existing.",
    )
    disabled_at = models.DateTimeField(blank=True, null=True)
    disabled_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        db_table = "congregation_modules"
        constraints = [
            models.UniqueConstraint(fields=["congregation", "module"], name="uniq_congregation_module"),
        ]

    def __str__(self):
        return f"{self.congregation} / {self.module} ({'on' if self.is_enabled else 'off'})"


class CongregationModuleHistory(TenantScopedModel):
    """Append-only audit log -- every toggle event, forever. Never updated, never deleted."""

    class Action(models.TextChoices):
        ENABLED = "enabled", "Enabled"
        DISABLED = "disabled", "Disabled"

    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name="history_entries")
    action = models.CharField(max_length=10, choices=Action.choices)
    changed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Not null, PROTECT -- an audit trail must never silently lose who made the change.",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "congregation_module_history"
        ordering = ["-changed_at"]
        verbose_name_plural = "congregation module history"

    def __str__(self):
        return f"{self.congregation} {self.action} {self.module} @ {self.changed_at}"
