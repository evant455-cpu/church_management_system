from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.people.models import Person
from apps.permissions.models import Permission, Role, RolePermission, UserPermissionOverride, UserRole
from apps.permissions.registry import DEFAULT_ROLES, PERMISSION_ACTIONS
from apps.permissions.services import (
    CrossTenantAssignmentError,
    assign_role_to_user,
    clear_permission_override,
    copy_default_roles_to_congregation,
    get_effective_permission_codes,
    set_permission_override,
    sync_permissions,
    unassign_role_from_user,
    user_has_permission,
)
from apps.tenancy.models import Congregation


class PermissionsTestCase(TestCase):
    """
    Shared fixture, mirrors module_system's ModuleSystemTestCase. The
    permission catalog already exists by the time any test runs -- the
    test database is created via `migrate`, which fires the post_migrate
    signal that calls sync_permissions() automatically, same as
    production. No setUp() boilerplate needed to seed it.
    """

    def setUp(self):
        self.congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        self.person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )
        self.user = User.objects.create_user(
            email="ada@example.com",
            password="s3cret-pass",
            congregation=self.congregation,
            person=self.person,
        )


# --- Catalog sync --------------------------------------------------------


class SyncPermissionsTests(TestCase):
    def test_catalog_matches_registry(self):
        expected = {
            f"{module}.{action}" for module, actions in PERMISSION_ACTIONS.items() for action in actions
        }
        actual = set(Permission.objects.values_list("code", flat=True))
        self.assertEqual(actual, expected)

    def test_sync_is_idempotent(self):
        before = Permission.objects.count()
        sync_permissions()
        sync_permissions()
        self.assertEqual(Permission.objects.count(), before)

    def test_sync_does_not_delete_actions_no_longer_in_the_registry(self):
        # Additive-only, unlike module_system's sync_modules() -- there's
        # no is_retired-style field here, and deleting could orphan live
        # role_permissions/override rows.
        Permission.objects.create(module="people", action="export", code="people.export")
        sync_permissions()
        self.assertTrue(Permission.objects.filter(code="people.export").exists())

    def test_registry_module_keys_are_real_modules(self):
        # Guards against drift between the two registries -- permissions.module
        # is a plain varchar convention against AVAILABLE_MODULES, not a real FK.
        from apps.module_system.registry import AVAILABLE_MODULES

        self.assertTrue(set(PERMISSION_ACTIONS.keys()).issubset(AVAILABLE_MODULES.keys()))

    def test_scheduling_has_a_signup_action_distinct_from_edit(self):
        # Explicitly called out in scheduling_schema.md as needing its own action.
        codes = set(Permission.objects.values_list("code", flat=True))
        self.assertIn("scheduling.signup", codes)
        self.assertIn("scheduling.edit", codes)


# --- copy_default_roles_to_congregation ----------------------------------


class CopyDefaultRolesTests(PermissionsTestCase):
    def test_creates_five_roles(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        self.assertEqual(set(roles.keys()), {"owner", "admin", "staff", "finance", "volunteer"})
        self.assertEqual(Role.objects.filter(congregation=self.congregation).count(), 5)

    def test_role_names_and_slugs_match_registry(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        for slug, spec in DEFAULT_ROLES.items():
            self.assertEqual(roles[slug].slug, slug)
            self.assertEqual(roles[slug].name, spec["name"])

    def test_owner_role_is_not_deletable_others_are(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        self.assertFalse(roles["owner"].is_deletable)
        for slug in ("admin", "staff", "finance", "volunteer"):
            self.assertTrue(roles[slug].is_deletable)

    def test_all_five_are_marked_system_default(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        self.assertTrue(all(role.is_system_default for role in roles.values()))

    def test_owner_and_admin_get_every_permission_in_the_catalog(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        all_codes = set(Permission.objects.values_list("code", flat=True))
        for slug in ("owner", "admin"):
            codes = set(
                Permission.objects.filter(role_permissions__role=roles[slug]).values_list("code", flat=True)
            )
            self.assertEqual(codes, all_codes)

    def test_staff_role_covers_the_documented_modules_but_not_finances(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        codes = set(
            Permission.objects.filter(role_permissions__role=roles["staff"]).values_list("code", flat=True)
        )
        modules = {code.split(".", 1)[0] for code in codes}
        self.assertEqual(modules, {"people", "attendance", "scheduling", "services", "announcements"})

    def test_finance_role_gets_only_finances_permissions(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        codes = set(
            Permission.objects.filter(role_permissions__role=roles["finance"]).values_list("code", flat=True)
        )
        self.assertEqual(codes, {"finances.view", "finances.edit", "finances.manage"})

    def test_volunteer_role_gets_only_attendance_checkin(self):
        roles = copy_default_roles_to_congregation(self.congregation)
        codes = set(
            Permission.objects.filter(role_permissions__role=roles["volunteer"]).values_list("code", flat=True)
        )
        self.assertEqual(codes, {"attendance.checkin"})

    def test_idempotent_re_running_does_not_duplicate_or_error(self):
        copy_default_roles_to_congregation(self.congregation)
        copy_default_roles_to_congregation(self.congregation)
        self.assertEqual(Role.objects.filter(congregation=self.congregation).count(), 5)
        owner = Role.objects.get(congregation=self.congregation, slug="owner")
        self.assertEqual(RolePermission.objects.filter(role=owner).count(), Permission.objects.count())

    def test_roles_are_congregation_scoped_and_independently_editable(self):
        other = Congregation.objects.create(name="Other Chapel", timezone="UTC")
        copy_default_roles_to_congregation(self.congregation)
        copy_default_roles_to_congregation(other)
        self.assertEqual(Role.objects.filter(congregation=self.congregation).count(), 5)
        self.assertEqual(Role.objects.filter(congregation=other).count(), 5)

        staff_a = Role.objects.get(congregation=self.congregation, slug="staff")
        staff_a.name = "Custom Staff Name"
        staff_a.save()
        staff_b = Role.objects.get(congregation=other, slug="staff")
        self.assertEqual(staff_b.name, "Staff")


# --- assign_role_to_user / unassign_role_from_user ------------------------


class AssignRoleToUserTests(PermissionsTestCase):
    def setUp(self):
        super().setUp()
        self.roles = copy_default_roles_to_congregation(self.congregation)

    def test_assigns_role_successfully(self):
        user_role = assign_role_to_user(self.user, self.roles["staff"])
        self.assertEqual(user_role.congregation_id, self.user.congregation_id)
        self.assertTrue(UserRole.objects.filter(user=self.user, role=self.roles["staff"]).exists())

    def test_idempotent_reassigning_the_same_role_is_a_noop(self):
        assign_role_to_user(self.user, self.roles["staff"])
        assign_role_to_user(self.user, self.roles["staff"])
        self.assertEqual(UserRole.objects.filter(user=self.user, role=self.roles["staff"]).count(), 1)

    def test_user_can_hold_multiple_roles(self):
        assign_role_to_user(self.user, self.roles["staff"])
        assign_role_to_user(self.user, self.roles["finance"])
        self.assertEqual(UserRole.objects.filter(user=self.user).count(), 2)

    def test_cross_tenant_assignment_is_rejected(self):
        other = Congregation.objects.create(name="Other Chapel", timezone="UTC")
        other_roles = copy_default_roles_to_congregation(other)
        with self.assertRaises(CrossTenantAssignmentError):
            assign_role_to_user(self.user, other_roles["staff"])
        self.assertFalse(UserRole.objects.filter(user=self.user).exists())

    def test_unassign_removes_the_role(self):
        assign_role_to_user(self.user, self.roles["staff"])
        unassign_role_from_user(self.user, self.roles["staff"])
        self.assertFalse(UserRole.objects.filter(user=self.user, role=self.roles["staff"]).exists())

    def test_unassign_of_a_role_never_held_is_a_noop(self):
        unassign_role_from_user(self.user, self.roles["staff"])  # never raises


# --- Effective permission resolution -------------------------------------


class EffectivePermissionsTests(PermissionsTestCase):
    def setUp(self):
        super().setUp()
        self.roles = copy_default_roles_to_congregation(self.congregation)

    def test_user_with_no_roles_has_no_permissions(self):
        self.assertEqual(get_effective_permission_codes(self.user), set())
        self.assertFalse(user_has_permission(self.user, "people.view"))

    def test_volunteer_role_grants_only_checkin(self):
        assign_role_to_user(self.user, self.roles["volunteer"])
        self.assertEqual(get_effective_permission_codes(self.user), {"attendance.checkin"})
        self.assertTrue(user_has_permission(self.user, "attendance.checkin"))
        self.assertFalse(user_has_permission(self.user, "attendance.edit"))

    def test_multiple_roles_union_together(self):
        assign_role_to_user(self.user, self.roles["finance"])
        assign_role_to_user(self.user, self.roles["volunteer"])
        codes = get_effective_permission_codes(self.user)
        self.assertIn("finances.edit", codes)
        self.assertIn("attendance.checkin", codes)

    def test_owner_role_grants_every_permission_in_the_catalog(self):
        assign_role_to_user(self.user, self.roles["owner"])
        self.assertEqual(
            get_effective_permission_codes(self.user), set(Permission.objects.values_list("code", flat=True))
        )

    def test_override_grant_adds_a_permission_no_role_provides(self):
        assign_role_to_user(self.user, self.roles["volunteer"])
        people_view = Permission.objects.get(code="people.view")
        set_permission_override(self.user, people_view, UserPermissionOverride.Effect.GRANT, created_by=self.user)
        self.assertTrue(user_has_permission(self.user, "people.view"))

    def test_override_revoke_removes_a_permission_a_role_grants(self):
        assign_role_to_user(self.user, self.roles["finance"])
        finances_manage = Permission.objects.get(code="finances.manage")
        self.assertTrue(user_has_permission(self.user, "finances.manage"))
        set_permission_override(
            self.user, finances_manage, UserPermissionOverride.Effect.REVOKE, created_by=self.user
        )
        self.assertFalse(user_has_permission(self.user, "finances.manage"))
        # the rest of the finance role's grants are untouched
        self.assertTrue(user_has_permission(self.user, "finances.edit"))

    def test_setting_an_override_twice_updates_in_place_not_a_duplicate(self):
        people_view = Permission.objects.get(code="people.view")
        set_permission_override(self.user, people_view, UserPermissionOverride.Effect.GRANT, created_by=self.user)
        set_permission_override(self.user, people_view, UserPermissionOverride.Effect.REVOKE, created_by=self.user)
        self.assertEqual(
            UserPermissionOverride.objects.filter(user=self.user, permission=people_view).count(), 1
        )
        self.assertFalse(user_has_permission(self.user, "people.view"))

    def test_clearing_an_override_falls_back_to_role_resolution(self):
        assign_role_to_user(self.user, self.roles["finance"])
        finances_manage = Permission.objects.get(code="finances.manage")
        set_permission_override(
            self.user, finances_manage, UserPermissionOverride.Effect.REVOKE, created_by=self.user
        )
        self.assertFalse(user_has_permission(self.user, "finances.manage"))
        clear_permission_override(self.user, finances_manage)
        self.assertTrue(user_has_permission(self.user, "finances.manage"))

    def test_permissions_do_not_leak_across_congregations(self):
        other = Congregation.objects.create(name="Other Chapel", timezone="UTC")
        other_person = Person.objects.create(congregation=other, first_name="Bea", last_name="Smith")
        other_user = User.objects.create_user(
            email="bea@example.com", password="s3cret-pass", congregation=other, person=other_person
        )
        other_roles = copy_default_roles_to_congregation(other)
        assign_role_to_user(other_user, other_roles["owner"])

        self.assertTrue(user_has_permission(other_user, "finances.manage"))
        # self.user holds no role in their own (different) congregation,
        # and must not inherit anything from the other tenant's Owner.
        self.assertFalse(user_has_permission(self.user, "finances.manage"))


# --- Model-level constraints ----------------------------------------------


class ModelConstraintTests(PermissionsTestCase):
    def test_duplicate_slug_within_same_congregation_rejected(self):
        Role.objects.create(congregation=self.congregation, name="Owner", slug="owner")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Role.objects.create(congregation=self.congregation, name="Owner Copy", slug="owner")

    def test_same_slug_across_different_congregations_is_allowed(self):
        other = Congregation.objects.create(name="Other Chapel", timezone="UTC")
        Role.objects.create(congregation=self.congregation, name="Owner", slug="owner")
        Role.objects.create(congregation=other, name="Owner", slug="owner")  # must not raise

    def test_duplicate_role_permission_rejected(self):
        role = Role.objects.create(congregation=self.congregation, name="Owner", slug="owner")
        permission = Permission.objects.get(code="people.view")
        RolePermission.objects.create(role=role, permission=permission)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RolePermission.objects.create(role=role, permission=permission)

    def test_duplicate_user_role_rejected(self):
        role = Role.objects.create(congregation=self.congregation, name="Owner", slug="owner")
        UserRole.objects.create(user=self.user, role=role, congregation_id=self.congregation.id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserRole.objects.create(user=self.user, role=role, congregation_id=self.congregation.id)

    def test_duplicate_user_permission_override_rejected(self):
        permission = Permission.objects.get(code="people.view")
        UserPermissionOverride.objects.create(
            user=self.user,
            permission=permission,
            congregation_id=self.congregation.id,
            effect=UserPermissionOverride.Effect.GRANT,
            created_by=self.user,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserPermissionOverride.objects.create(
                    user=self.user,
                    permission=permission,
                    congregation_id=self.congregation.id,
                    effect=UserPermissionOverride.Effect.REVOKE,
                    created_by=self.user,
                )
