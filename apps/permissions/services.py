"""
Permissions business logic: permission-catalog sync, the default-role-copy
service, role/override assignment, and effective-permission resolution.

Deliberately separate from models.py and access.py -- this is the one
place the actual RBAC rules live, so the access gate and tests both call
into the same functions rather than each re-implementing a slightly
different version of "does this user have permission X".
"""

from __future__ import annotations

from django.db import transaction

from .models import Permission, Role, RolePermission, UserPermissionOverride, UserRole
from .registry import ACTION_DESCRIPTIONS, DEFAULT_ROLES, PERMISSION_ACTIONS


def sync_permissions():
    """
    Reconcile the `permissions` table against registry.PERMISSION_ACTIONS.

    Called automatically after every `manage.py migrate` via the
    post_migrate signal (see apps.py) -- also safe to call directly (e.g.
    in tests), since it's a plain idempotent upsert.

    Unlike sync_modules(), this never "retires" or removes rows for
    actions no longer declared in the registry: the `permissions` table
    has no is_retired-style field in the documented schema, and
    role_permissions/user_permission_overrides rows may already reference
    a given Permission, so silently deleting one out from under live RBAC
    data would be far more dangerous than module_system's equivalent
    cleanup. If an action is genuinely retired, the operational story is
    "stop referencing it" (no role grants it any more), not "delete the
    catalog row" -- a manual data-migration concern if it ever comes up,
    not something this function does automatically.
    """
    for module, actions in PERMISSION_ACTIONS.items():
        for action in actions:
            code = f"{module}.{action}"
            description = ACTION_DESCRIPTIONS.get(action, "").format(module=module)
            Permission.objects.update_or_create(
                code=code,
                defaults={"module": module, "action": action, "description": description},
            )


class CrossTenantAssignmentError(Exception):
    """Raised when a role assignment would cross congregation boundaries."""


def copy_default_roles_to_congregation(congregation):
    """
    Create the five system default roles (+ their role_permissions) for a
    congregation, per registry.DEFAULT_ROLES.

    Idempotent -- get_or_create per role slug and per (role, permission)
    pair, so re-running for a congregation that already has some or all of
    these rows is a safe no-op for what already exists, same idempotency
    contract as module_system's initialize_congregation_modules().

    Does NOT touch user_roles -- assigning the new owner the Owner role is
    the signup service's job (Phase 5). In this phase, tests and the shell
    do that by hand via assign_role_to_user(), the same way Phase 1 created
    congregations/users by hand before a signup wizard existed.

    Returns a dict of {slug: Role} so a caller (e.g. a future signup
    service) can immediately grab roles["owner"] to assign.
    """
    all_permission_codes = set(Permission.objects.values_list("code", flat=True))

    roles_by_slug = {}
    with transaction.atomic():
        for slug, spec in DEFAULT_ROLES.items():
            role, _ = Role.objects.get_or_create(
                congregation=congregation,
                slug=slug,
                defaults={
                    "name": spec["name"],
                    "is_system_default": True,
                    "is_deletable": spec["is_deletable"],
                },
            )
            roles_by_slug[slug] = role

            grants = spec["grants"]
            if grants == "all":
                codes = all_permission_codes
            elif "modules" in grants:
                codes = {c for c in all_permission_codes if c.split(".", 1)[0] in grants["modules"]}
            else:
                codes = set(grants["codes"])

            permission_ids = set(Permission.objects.filter(code__in=codes).values_list("id", flat=True))
            existing_permission_ids = set(
                RolePermission.objects.filter(role=role).values_list("permission_id", flat=True)
            )
            to_create = [
                RolePermission(role=role, permission_id=pid)
                for pid in permission_ids - existing_permission_ids
            ]
            RolePermission.objects.bulk_create(to_create)

    return roles_by_slug


def assign_role_to_user(user, role):
    """
    Assign a role to a user.

    Checks user.congregation_id == role.congregation_id before insert --
    the documented app-level guard "alongside RLS" (RLS itself deferred,
    see chat) -- and raises CrossTenantAssignmentError rather than letting
    a cross-tenant row get written.

    Idempotent via the (user, role) unique constraint: get_or_create
    rather than create, so re-assigning an already-held role is a safe
    no-op instead of an IntegrityError.
    """
    if user.congregation_id != role.congregation_id:
        raise CrossTenantAssignmentError(f"{user} belongs to a different congregation than {role}.")
    user_role, _ = UserRole.objects.get_or_create(
        user=user, role=role, defaults={"congregation_id": user.congregation_id}
    )
    return user_role


def unassign_role_from_user(user, role):
    """Remove a role from a user, if held. No-op if the user doesn't hold it."""
    UserRole.objects.filter(user=user, role=role).delete()


def set_permission_override(user, permission, effect, created_by):
    """
    Grant or revoke a single permission for a user, overriding whatever
    their role(s) would otherwise resolve to.

    One row per (user, permission) per the documented unique constraint --
    update_or_create rather than create, so calling this again for the
    same pair updates `effect` in place instead of erroring.
    """
    override, _ = UserPermissionOverride.objects.update_or_create(
        user=user,
        permission=permission,
        defaults={
            "congregation_id": user.congregation_id,
            "effect": effect,
            "created_by": created_by,
        },
    )
    return override


def clear_permission_override(user, permission):
    """Remove a standing override, if any -- the user falls back to pure role resolution."""
    UserPermissionOverride.objects.filter(user=user, permission=permission).delete()


def get_effective_permission_codes(user) -> set[str]:
    """
    A user's effective permissions = (union of all permissions from all
    roles assigned to them) plus any override-granted permissions minus
    any override-revoked permissions -- see roles_and_permissions_schema.md.

    Every join here is defensively re-filtered by user.congregation_id,
    even though user_roles/user_permission_overrides already carry a
    denormalized congregation_id that should always agree with it
    (enforced at insert time by assign_role_to_user() /
    set_permission_override() above) -- belt-and-suspenders against a
    future bug that writes a cross-tenant row some other way, in lieu of
    RLS actually enforcing this at the database level yet.
    """
    role_ids = UserRole.objects.filter(
        user=user, congregation_id=user.congregation_id
    ).values_list("role_id", flat=True)

    granted = set(
        Permission.objects.filter(role_permissions__role_id__in=role_ids).values_list("code", flat=True)
    )

    overrides = UserPermissionOverride.objects.filter(
        user=user, congregation_id=user.congregation_id
    ).select_related("permission")
    for override in overrides:
        if override.effect == UserPermissionOverride.Effect.GRANT:
            granted.add(override.permission.code)
        else:
            granted.discard(override.permission.code)

    return granted


def user_has_permission(user, permission_code: str) -> bool:
    """
    The single entry point access.py's permission-check layer calls.

    Recomputed fresh on every call rather than cached -- simplest correct
    thing for now; if this ever shows up as a real bottleneck, caching
    per-request (or per-user with explicit invalidation on role/override
    changes) is the natural next step, not something to build speculatively
    here.
    """
    return permission_code in get_effective_permission_codes(user)
