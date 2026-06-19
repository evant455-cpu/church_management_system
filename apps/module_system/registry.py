"""
Canonical module registry -- the single source of truth for what modules
exist in this system (see module_system_mechanics_schema.md).

This is intentionally plain code, not database rows: `modules` and
`module_dependencies` are mirrors of this dict, kept in sync by
`sync_modules()` (see services.py), which runs automatically after every
`manage.py migrate` via the post_migrate signal connected in apps.py.

To add, rename, or re-describe a module: edit this dict, then run
`manage.py migrate` (even with nothing to migrate) to push the change into
the database. To change which modules depend on which, edit `depends_on`
here -- `module_dependencies` rows are fully derived from this field and
are never created or edited by hand.

Order here is arbitrary (sort_order is the actual display-order field);
grouped roughly to match the README's module table.
"""

AVAILABLE_MODULES = {
    "people": {
        "name": "People",
        "description": "Member directory, households, contacts.",
        "sort_order": 0,
        "depends_on": [],
    },
    "staff": {
        "name": "Staff",
        "description": "Staff records and roles.",
        "sort_order": 1,
        "depends_on": ["people"],
    },
    "attendance": {
        "name": "Attendance",
        "description": "Check-in, headcounts, trends.",
        "sort_order": 2,
        "depends_on": [],
    },
    "scheduling": {
        "name": "Scheduling",
        "description": "Staff and volunteer scheduling.",
        "sort_order": 3,
        "depends_on": ["people"],
    },
    "services": {
        "name": "Services",
        "description": "Service planning, order of worship.",
        "sort_order": 4,
        "depends_on": [],
    },
    "announcements": {
        "name": "Announcements",
        "description": "Church-wide communications.",
        "sort_order": 5,
        "depends_on": [],
    },
    "finances": {
        "name": "Finances",
        "description": "Giving, budgets, fund tracking.",
        "sort_order": 6,
        "depends_on": [],
    },
}
