from django.db import models

from apps.tenancy.models import TenantScopedModel


class Permission(models.Model):
    """
    Global, system-wide catalog -- NOT tenant-scoped. The set of possible
    actions is the same for every congregation, derived from the module
    registry already defined in code.

    Synced from registry.PERMISSION_ACTIONS by services.sync_permissions()
    (wired to post_migrate in apps.py, same pattern as module_system's
    sync_modules()). Never edited by hand.

    `module` matches a key in apps.module_system.registry.AVAILABLE_MODULES
    by convention, but is a plain varchar here, not a real foreign key --
    matches the schema doc exactly, and keeps this app from taking a hard
    dependency on module_system's models.
    """

    module = models.CharField(max_length=50)
    action = models.CharField(max_length=50)
    code = models.CharField(
        max_length=100,
        unique=True,
        help_text='"{module}.{action}", e.g. "finances.edit" -- convenience field for lookups/checks in code.',
    )
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "permissions"
        ordering = ["module", "action"]

    def __str__(self):
        return self.code


class Role(TenantScopedModel):
    """
    Tenant-scoped. Either a congregation's own editable copy of a system
    default role (is_system_default=True, created by
    services.copy_default_roles_to_congregation()) or a fully custom role
    a congregation creates later (is_system_default=False) -- structurally
    identical either way, so no special-cased code path for either kind.

    Editing one congregation's copy of e.g. "Staff" never affects any
    other congregation's "Staff" role, since each congregation owns its
    own row here.
    """

    name = models.CharField(max_length=100, help_text='Display name, editable by the congregation (e.g. "Staff").')
    slug = models.SlugField(
        max_length=50,
        help_text="Stable identifier set at creation (e.g. 'owner', 'admin') -- used for business rules, not display.",
    )
    is_system_default = models.BooleanField(
        default=False,
        help_text="True if this role originated from the system template set (still independently editable per congregation).",
    )
    is_deletable = models.BooleanField(
        default=True,
        help_text="False for 'owner' -- every congregation must always have an Owner role.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "roles"
        constraints = [
            models.UniqueConstraint(
                fields=["congregation", "slug"], name="uniq_role_congregation_slug"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.congregation})"


class RolePermission(models.Model):
    """
    Join table: which permissions a role grants.

    Not itself tenant-scoped (no congregation field) -- role.congregation
    already pins this to a tenant, and denormalizing it here would add
    nothing a join couldn't already give us, unlike user_roles/
    user_permission_overrides below where the denormalization buys fast
    RLS-style filtering directly off the user. CASCADE on both FKs: this
    is a pure relationship record, not historical data, same reasoning as
    person_households' join-table CASCADEs.
    """

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="role_permissions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "role_permissions"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission"),
        ]

    def __str__(self):
        return f"{self.role} -> {self.permission}"


class UserRole(TenantScopedModel):
    """
    Which role(s) a user holds. A user may hold more than one role (e.g.
    Staff + Finance).

    `congregation` (from TenantScopedModel) is denormalized from
    role.congregation -- per the schema doc, for fast filtering and to
    guard against cross-tenant assignment bugs. Kept in sync by
    services.assign_role_to_user(), the one code path meant to create
    these rows, which checks user.congregation_id == role.congregation_id
    before insert -- the documented app-level guard "alongside RLS" (RLS
    itself deferred to a future cross-cutting pass, see chat).

    CASCADE on both FKs: an assignment record, not historical data --
    deleting the user or the role should clean these up rather than block
    on them.
    """

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_roles")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_roles"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="uniq_user_role"),
        ]

    def __str__(self):
        return f"{self.user} -> {self.role}"


class UserPermissionOverride(TenantScopedModel):
    """
    Per-user exceptions layered on top of role-derived permissions, for
    cases where a role is almost right but one person needs an exception.

    `congregation` (from TenantScopedModel) is denormalized from
    user.congregation, same rationale as UserRole above. created_by uses
    PROTECT -- an audit trail must never silently lose who made the
    change, same pattern as CongregationModuleHistory.changed_by.
    """

    class Effect(models.TextChoices):
        GRANT = "grant", "Grant"
        REVOKE = "revoke", "Revoke"

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="permission_overrides")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="user_overrides")
    effect = models.CharField(max_length=10, choices=Effect.choices)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Audit trail -- who made this override.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_permission_overrides"
        constraints = [
            models.UniqueConstraint(fields=["user", "permission"], name="uniq_user_permission_override"),
        ]

    def __str__(self):
        return f"{self.user} {self.effect} {self.permission}"
