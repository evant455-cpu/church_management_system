"""
Module-system business logic: registry sync, congregation-module
initialization, and the enable/disable + cascade-confirmation flow.

Deliberately separate from models.py and views.py -- this is the one
place dependency rules live, so the toggle view and tests both call into
the same functions rather than each re-implementing a slightly different
version of "can this be enabled".
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import CongregationModule, CongregationModuleHistory, Module, ModuleDependency
from .registry import AVAILABLE_MODULES


def sync_modules():
    """
    Reconcile `modules` and `module_dependencies` against AVAILABLE_MODULES.

    Called automatically after every `manage.py migrate` via the
    post_migrate signal (see apps.py) -- also safe to call directly (e.g.
    in tests, or a future `sync_modules` management command), since it's
    a plain idempotent upsert.

    - Every key in the registry gets its Module row created or updated,
      and is_retired forced to False (covers a module being un-retired by
      reappearing in the registry).
    - Any existing Module row whose key is *not* in the registry is
      marked is_retired=True rather than deleted, preserving FK integrity
      for historical rows that reference it.
    - module_dependencies rows are added for any (module, depends_on)
      pair declared in the registry that doesn't exist yet, and removed
      for any pair that exists in the database but is no longer declared.
    """
    with transaction.atomic():
        modules_by_key = {}
        for key, meta in AVAILABLE_MODULES.items():
            module, _ = Module.objects.update_or_create(
                key=key,
                defaults={
                    "name": meta["name"],
                    "description": meta.get("description", ""),
                    "sort_order": meta.get("sort_order", 0),
                    "is_retired": False,
                },
            )
            modules_by_key[key] = module

        Module.objects.exclude(key__in=AVAILABLE_MODULES.keys()).update(is_retired=True)

        desired_pairs = set()
        for key, meta in AVAILABLE_MODULES.items():
            for dep_key in meta.get("depends_on", []):
                desired_pairs.add((key, dep_key))

        existing_pairs = set(
            ModuleDependency.objects.filter(
                module__key__in=AVAILABLE_MODULES.keys(),
                depends_on_module__key__in=AVAILABLE_MODULES.keys(),
            ).values_list("module__key", "depends_on_module__key")
        )

        for key, dep_key in desired_pairs - existing_pairs:
            ModuleDependency.objects.get_or_create(
                module=modules_by_key[key], depends_on_module=modules_by_key[dep_key]
            )

        for key, dep_key in existing_pairs - desired_pairs:
            ModuleDependency.objects.filter(
                module=modules_by_key[key], depends_on_module=modules_by_key[dep_key]
            ).delete()


def initialize_congregation_modules(congregation, enabled_keys=frozenset()):
    """
    Create one CongregationModule row per active (non-retired) module for
    a congregation, enabling whichever keys are passed in `enabled_keys`.

    This is the one explicit code path for populating congregation_modules
    -- called by Phase 5's signup transaction, by tests in this phase, and
    by a future backfill migration when a new module ships. Idempotent:
    safe to call again for a congregation that already has some rows
    (e.g. a backfill after a new module is added) -- existing rows are
    left untouched, only missing ones are created.
    """
    existing_module_ids = set(
        CongregationModule.objects.filter(congregation=congregation).values_list("module_id", flat=True)
    )
    to_create = []
    for module in Module.objects.filter(is_retired=False).exclude(id__in=existing_module_ids):
        is_enabled = module.key in enabled_keys
        to_create.append(
            CongregationModule(
                congregation=congregation,
                module=module,
                is_enabled=is_enabled,
                enabled_at=timezone.now() if is_enabled else None,
            )
        )
    CongregationModule.objects.bulk_create(to_create)


class ModuleDependencyError(Exception):
    """Raised when enabling a module is blocked by an unmet prerequisite."""


class ModuleDisableConfirmationRequired(Exception):
    """
    Raised by disable_module() when disabling would also disable one or
    more currently-enabled dependent modules and the caller hasn't passed
    confirmed=True.

    `affected` lists the *other* modules (besides the one requested) that
    would also be disabled.
    """

    def __init__(self, affected):
        self.affected = affected
        names = ", ".join(m.name for m in affected)
        super().__init__(f"Disabling this module will also disable: {names}.")


def _prerequisite_keys(module):
    return list(ModuleDependency.objects.filter(module=module).values_list("depends_on_module__key", flat=True))


def _dependents_enabled_for(congregation, module):
    """Modules currently enabled for this congregation that depend on `module`."""
    dependent_keys = ModuleDependency.objects.filter(depends_on_module=module).values_list(
        "module__key", flat=True
    )
    return list(
        Module.objects.filter(
            key__in=dependent_keys,
            congregation_modules__congregation=congregation,
            congregation_modules__is_enabled=True,
        )
    )


def enable_module(congregation, module_key, by_user):
    """
    Enable a module for a congregation, after confirming every module it
    depends on is already enabled for that congregation.

    Raises ModuleDependencyError with a clear message if a prerequisite
    isn't enabled yet (e.g. "Enable People before enabling Scheduling.").
    Already-enabled is a no-op (returns the row as-is, no history written).
    """
    cm = CongregationModule.objects.select_related("module").get(
        congregation=congregation, module__key=module_key
    )
    if cm.is_enabled:
        return cm

    prerequisite_keys = _prerequisite_keys(cm.module)
    if prerequisite_keys:
        enabled_prereqs = set(
            CongregationModule.objects.filter(
                congregation=congregation, module__key__in=prerequisite_keys, is_enabled=True
            ).values_list("module__key", flat=True)
        )
        missing = [k for k in prerequisite_keys if k not in enabled_prereqs]
        if missing:
            missing_names = ", ".join(Module.objects.filter(key__in=missing).values_list("name", flat=True))
            raise ModuleDependencyError(f"Enable {missing_names} before enabling {cm.module.name}.")

    with transaction.atomic():
        cm.is_enabled = True
        cm.enabled_at = timezone.now()
        cm.enabled_by = by_user
        cm.disabled_at = None
        cm.disabled_by = None
        cm.save(update_fields=["is_enabled", "enabled_at", "enabled_by", "disabled_at", "disabled_by"])
        CongregationModuleHistory.objects.create(
            congregation=congregation,
            module=cm.module,
            action=CongregationModuleHistory.Action.ENABLED,
            changed_by=by_user,
        )
    return cm


def disable_module(congregation, module_key, by_user, confirmed=False):
    """
    Disable a module for a congregation.

    If one or more currently-enabled modules depend on this one, raises
    ModuleDisableConfirmationRequired unless confirmed=True -- the caller
    (a view, a test) is expected to show the user that list and re-call
    with confirmed=True once they accept. On confirm, this module and
    every affected dependent are disabled together in one transaction,
    dependents first, with a history row for each. Already-disabled is a
    no-op (returns the row as-is, no history written).
    """
    cm = CongregationModule.objects.select_related("module").get(
        congregation=congregation, module__key=module_key
    )
    if not cm.is_enabled:
        return cm

    affected = _dependents_enabled_for(congregation, cm.module)
    if affected and not confirmed:
        raise ModuleDisableConfirmationRequired(affected)

    with transaction.atomic():
        # Dependents first, then the prerequisite -- the same order the
        # Postgres trigger backstop allows, so this path never trips it.
        for dependent_module in affected:
            dependent_cm = CongregationModule.objects.select_for_update().get(
                congregation=congregation, module=dependent_module
            )
            dependent_cm.is_enabled = False
            dependent_cm.disabled_at = timezone.now()
            dependent_cm.disabled_by = by_user
            dependent_cm.save(update_fields=["is_enabled", "disabled_at", "disabled_by"])
            CongregationModuleHistory.objects.create(
                congregation=congregation,
                module=dependent_module,
                action=CongregationModuleHistory.Action.DISABLED,
                changed_by=by_user,
            )

        cm.is_enabled = False
        cm.disabled_at = timezone.now()
        cm.disabled_by = by_user
        cm.save(update_fields=["is_enabled", "disabled_at", "disabled_by"])
        CongregationModuleHistory.objects.create(
            congregation=congregation,
            module=cm.module,
            action=CongregationModuleHistory.Action.DISABLED,
            changed_by=by_user,
        )

    return cm
