"""
The access gate -- see module_system_mechanics_schema.md and
subscription_billing_schema.md for the full three-layer design:
billing status, then module-enabled, then permission.

`access_required` is the single, extensible entry point every
module-owned view goes through. This phase only implements the module
check; billing (Phase 4) and permission (Phase 3) are wired in as
always-pass stubs so the order is fixed once, here, rather than left to
however individual views stack decorators. Later phases fill in the stub
bodies -- the decorator's call signature and the order of checks don't
change.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def _billing_check_passes(request):
    """Stub for Phase 4 -- always passes until subscription state exists."""
    return True


def _permission_check_passes(request, permission):
    """Stub for Phase 3 -- always passes until roles/permissions exist."""
    return True


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

    Usage (this phase): @access_required(module="attendance")
    Usage (once Phase 3 lands): @access_required(module="attendance", permission="attendance.checkin")

    The order checks run in is fixed inside this function -- billing,
    then module, then permission -- matching the documented access gate.
    Existing call sites that only pass `module=` keep working unchanged
    when `permission=` starts being enforced.
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
