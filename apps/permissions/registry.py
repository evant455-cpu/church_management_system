"""
Permission catalog -- the single source of truth for what (module, action)
pairs exist in this system (see roles_and_permissions_schema.md).

Deliberately kept separate from apps.module_system.registry.AVAILABLE_MODULES
rather than folding actions into that dict: module_system owns *what
modules exist and depend on what* (Phase 2's concern); this app owns *what
a user can do within an enabled module* (Phase 3's concern). Keeping them
apart means a Phase 2 file never has to change for a Phase 3 reason, and
vice versa for future module work.

`permissions.module` is a plain varchar matching convention against
AVAILABLE_MODULES keys, NOT a real foreign key -- matches the schema doc
exactly. Because of that there's no database constraint tying the two
registries together, so a test (see tests.py) asserts every module key
here is also a real key in AVAILABLE_MODULES, guarding against typos/drift.

To add a new action: add it to the relevant module's list below, then run
`manage.py migrate` (even a no-op one) to push it into the database via
sync_permissions() -- same pattern as module_system's sync_modules().
Additive only: removing an action from here does NOT delete its Permission
row (see sync_permissions() docstring in services.py for why).
"""

PERMISSION_ACTIONS = {
    "people": ["view", "edit", "manage"],
    "staff": ["view", "edit", "manage"],
    "attendance": ["view", "edit", "manage", "checkin"],
    "scheduling": ["view", "edit", "manage", "signup"],
    "services": ["view", "edit", "manage"],
    "announcements": ["view", "edit", "manage", "publish"],
    "finances": ["view", "edit", "manage"],
}

# Generic per-action description, filled in with the module name at sync
# time. Module-specific actions get their own entry; the three baseline
# actions (view/edit/manage) share one description each across modules.
ACTION_DESCRIPTIONS = {
    "view": "View {module} records.",
    "edit": "Create and update {module} records.",
    "manage": "Delete records and manage {module} configuration/settings.",
    "checkin": "Check a person in to an attendance session.",
    "signup": "Sign up for an open schedule slot (self-service -- distinct from editing others' assignments).",
    "publish": "Publish announcements to the congregation.",
}

# The five system default roles copied into every congregation (see
# copy_default_roles_to_congregation() in services.py) and their permission
# grants, per the "Default system roles" table in roles_and_permissions_schema.md.
#
# `grants` is one of:
#   "all"                          -- every permission in the catalog
#   {"modules": [<module keys>]}   -- every action for the listed modules
#   {"codes": [<exact codes>]}     -- only the listed permission codes
#
# Owner and Admin are intentionally identical here: per
# roles_and_permissions_schema.md and onboarding_sequence_schema.md, the
# only thing distinguishing Owner is congregations.owner_user_id (billing/
# account-settings access), which lives entirely outside this permission
# system -- "no separate Admin role assignment needed" because Owner's
# permission set already covers everything Admin would.
#
# Grants are NOT filtered by which modules happen to be enabled for a given
# congregation -- see module_system_mechanics_schema.md's access gate
# section: a permission simply sits inert while its module is disabled,
# rather than needing to be stripped and restored on every toggle. So
# "all" really does mean every Permission row in the catalog, full stop.
DEFAULT_ROLES = {
    "owner": {
        "name": "Owner",
        "is_deletable": False,
        "grants": "all",
    },
    "admin": {
        "name": "Admin",
        "is_deletable": True,
        "grants": "all",
    },
    "staff": {
        "name": "Staff",
        "is_deletable": True,
        "grants": {"modules": ["people", "attendance", "scheduling", "services", "announcements"]},
    },
    "finance": {
        "name": "Finance",
        "is_deletable": True,
        "grants": {"modules": ["finances"]},
    },
    "volunteer": {
        "name": "Volunteer",
        "is_deletable": True,
        "grants": {"codes": ["attendance.checkin"]},
    },
}
