"""
Billing's own, narrower authorization check -- deliberately separate
from module_system.access.access_required's three-layer gate.

roles_and_permissions_schema.md's default-roles table documents billing/
account settings as "handled outside the module-permission system" --
Owner gets it, Admin explicitly does not, and no role grant or override
can add it, because there's no `billing.*` permission in the catalog at
all to grant. So this isn't routed through access_required's
`permission=` layer (Phase 3's RBAC); it's a direct identity check
against `congregations.owner_user_id`, the same single source of truth
roles_and_permissions_schema.md designates for "is this the owner?"
everywhere else (billing, account deletion, ownership transfer).
"""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def owner_required(view_func):
    """
    Restricts a view to whoever `congregation.owner_user_id` currently
    points at -- not merely someone holding the Owner *role* (those are
    usually but not necessarily the same user; user_roles is informational
    here, owner_user_id is authoritative). Safe to use standalone, but in
    practice is stacked under @access_required(billing_exempt=True) on
    every billing view, so the authentication check below rarely fires:
    it exists so this decorator doesn't assume an unverified request.user.
    """

    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if request.user.congregation.owner_user_id != request.user.id:
            raise PermissionDenied("Only the congregation owner can access billing settings.")
        return view_func(request, *args, **kwargs)

    return wrapped
