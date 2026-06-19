"""
The access gate -- see module_system_mechanics_schema.md and
subscription_billing_schema.md for the full three-layer design:
billing status, then module-enabled, then permission.

`access_required` is the single, extensible entry point every
module-owned view goes through. Phase 2 implemented the module check;
Phase 3 (this one) fills in the real permission check against
apps.permissions. Billing (Phase 4) remains an always-pass stub for now,
so the order is fixed once, here, rather than left to however individual
views stack decorators. The decorator's call signature and the order of
checks haven't changed since Phase 2 -- existing call sites that only
pass `module=` keep working exactly as before.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def _billing_check_passes(request):
    """Stub for Phase 4 -- always passes until subscription state exists."""
    return True


def _permission_check_passes(request, permission):
    """
    Phase 3 -- real check against the roles/permissions engine.

    permission=None means the view isn't permission-gated at all (mirrors
    module=None for the module check above) and always passes. Otherwise
    delegates to apps.permissions.services.user_has_permission(), which
    resolves the user's effective permissions (union of role grants, plus
    override-grants, minus override-revokes). is_superuser/is_staff is
    deliberately NOT special-cased here -- per apps/accounts/models.py,
    that's the platform-operator Django Admin escape hatch, fully separate
    from this in-app RBAC system.

    Imported locally, same reason _module_enabled() imports its model
    locally: avoids a hard import-time dependency between apps for what's
    otherwise just a thin app-boundary function.
    """
    if permission is None:
        return True
    from apps.permissions.services import user_has_permission

    return user_has_permission(request.user, permission)


def _module_enabled(request, module_key):
    if module_key is None:
        return True
    from .models import CongregationModule

    return CongregationModule.objects.filter(
        congregation=request.user.congregation, module__key=module_key, is_enabled=True
    ).exists()


def access_required(module=None, permission=None):
    """
    Decorator for module-owned views.

    Usage: @access_required(module="attendance", permission="attendance.checkin")
    `permission=` is now enforced for real (Phase 3) -- pass a permission
    code from apps.permissions' catalog (e.g. "finances.edit"). Omitting
    it (the Phase 2 call style) skips the permission check entirely, same
    as omitting `module=` skips the module check.

    The order checks run in is fixed inside this function -- billing,
    then module, then permission -- matching the documented access gate.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if not _billing_check_passes(request):
                raise PermissionDenied("Billing check failed.")
            if not _module_enabled(request, module):
                raise PermissionDenied(f"The '{module}' module is not enabled for your congregation.")
            if not _permission_check_passes(request, permission):
                raise PermissionDenied("You don't have permission to do that.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
