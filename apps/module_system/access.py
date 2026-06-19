"""
The access gate -- see module_system_mechanics_schema.md and
subscription_billing_schema.md for the full three-layer design:
billing status, then module-enabled, then permission.

`access_required` is the single, extensible entry point every
module-owned view goes through. Phase 2 implemented the module check,
Phase 3 the permission check (against apps.permissions), and Phase 4
the billing check (this phase) -- all three layers are now real. The
decorator's call signature and the order of checks haven't changed
since Phase 2: existing call sites that only pass `module=` keep
working exactly as before.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

# HTTP methods that read but don't write -- see "Where this sits in the
# access gate" in subscription_billing_schema.md: read_only/canceled
# blocks writes account-wide, reads still work.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _billing_check_passes(request):
    """
    Layer 3. trialing/active/past_due is full access. read_only/canceled
    blocks writes but lets reads through.

    Fails closed on a missing Subscription row, by deliberate choice
    (see chat for the Phase 4 discussion): in production this can only
    happen pre-Phase-5, since the real signup transaction always creates
    a Subscription row in the same atomic block it creates the
    congregation in -- the same invariant pattern as
    congregations.owner_user_id. The only way to hit the DoesNotExist
    branch is test/dev data created directly via shell without going
    through that flow, and the explicit choice is that such data doesn't
    get a free pass -- it has to create a Subscription row like any
    other test fixture exercising a module-owned view (see
    module_system.tests.ModuleSystemTestCase).
    """
    from apps.billing.models import Subscription

    try:
        subscription = Subscription.objects.get(congregation=request.user.congregation)
    except Subscription.DoesNotExist:
        return False

    if subscription.status in (Subscription.Status.READ_ONLY, Subscription.Status.CANCELED):
        return request.method in SAFE_METHODS
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


def access_required(module=None, permission=None, billing_exempt=False):
    """
    Decorator for module-owned views.

    Usage (feature modules): @access_required(module="attendance", permission="attendance.checkin")
    Usage (billing's own views): @access_required(billing_exempt=True)

    `permission=` is enforced for real (Phase 3) -- pass a permission code
    from apps.permissions' catalog (e.g. "finances.edit"). Omitting it
    skips the permission check entirely, same as omitting `module=` skips
    the module check.

    The order checks run in is fixed inside this function -- billing,
    then module, then permission -- matching the documented access gate.

    billing_exempt=True skips layer 3 entirely. Reserved for billing's
    own views (apps.billing.views), which must stay reachable even while
    a congregation is read_only/canceled -- that's the whole point of
    those views existing (re-enter a card, reactivate). Those views then
    enforce their own stricter check instead
    (apps.billing.access.owner_required) rather than anything routed
    through this decorator's `permission=` layer, since billing/account
    settings are documented as handled outside the module-permission
    system altogether.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if not billing_exempt and not _billing_check_passes(request):
                raise PermissionDenied("Billing check failed -- this congregation's account needs attention.")
            if not _module_enabled(request, module):
                raise PermissionDenied(f"The '{module}' module is not enabled for your congregation.")
            if not _permission_check_passes(request, permission):
                raise PermissionDenied("You don't have permission to do that.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
