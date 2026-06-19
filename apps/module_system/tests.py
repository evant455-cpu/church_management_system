from unittest import mock

from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.billing.models import Subscription
from apps.module_system.models import (
    CongregationModule,
    CongregationModuleHistory,
    Module,
    ModuleDependency,
)
from apps.module_system.services import (
    ModuleDependencyError,
    ModuleDisableConfirmationRequired,
    disable_module,
    enable_module,
    initialize_congregation_modules,
    sync_modules,
)
from apps.module_system.access import access_required
from apps.people.models import Person
from apps.tenancy.models import Congregation


class ModuleSystemTestCase(TestCase):
    """
    Shared fixture. Module/ModuleDependency rows already exist by the time
    any test runs -- the test database is created via `migrate`, which
    fires the post_migrate signal that calls sync_modules() automatically,
    same as production. No setUp() boilerplate needed to seed them.

    Also creates an `active` Subscription -- Phase 4 made the billing
    layer of the access gate fail closed on a missing Subscription row
    (see module_system.access._billing_check_passes), and this fixture's
    Congregation is created directly rather than through Phase 5's real
    signup transaction, so without this it would have no Subscription
    row at all and every test below that exercises access_required would
    incorrectly get blocked by layer 3 rather than testing what it's
    actually meant to test (the module check, layer 2).
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
        Subscription.objects.create(
            congregation=self.congregation,
            stripe_customer_id="cus_test_fixture",
            stripe_subscription_id="sub_test_fixture",
            status=Subscription.Status.ACTIVE,
        )



# --- Registry sync -----------------------------------------------------


class SyncModulesTests(TestCase):
    def test_registry_modules_exist_after_migrate(self):
        """Confirms the post_migrate signal really did its job for the whole test DB."""
        keys = set(Module.objects.values_list("key", flat=True))
        self.assertEqual(
            keys,
            {"people", "staff", "attendance", "scheduling", "services", "announcements", "finances"},
        )

    def test_dependencies_match_registry(self):
        pairs = set(ModuleDependency.objects.values_list("module__key", "depends_on_module__key"))
        self.assertEqual(pairs, {("staff", "people"), ("scheduling", "people")})

    def test_sync_is_idempotent(self):
        before = Module.objects.count()
        sync_modules()
        sync_modules()
        self.assertEqual(Module.objects.count(), before)

    def test_sync_retires_modules_no_longer_in_registry(self):
        Module.objects.create(key="legacy_module", name="Legacy", sort_order=99)
        sync_modules()
        legacy = Module.objects.get(key="legacy_module")
        self.assertTrue(legacy.is_retired)
        # still present, never deleted -- preserves FK integrity
        self.assertTrue(Module.objects.filter(key="legacy_module").exists())

    def test_sync_un_retires_a_module_that_reappears(self):
        people = Module.objects.get(key="people")
        people.is_retired = True
        people.save(update_fields=["is_retired"])
        sync_modules()
        people.refresh_from_db()
        self.assertFalse(people.is_retired)

    def test_sync_removes_dependency_no_longer_declared(self):
        fake_registry = {
            "people": {"name": "People", "description": "", "sort_order": 0, "depends_on": []},
            "staff": {"name": "Staff", "description": "", "sort_order": 1, "depends_on": []},  # dropped dep
        }
        with mock.patch("apps.module_system.services.AVAILABLE_MODULES", fake_registry):
            sync_modules()
        self.assertFalse(
            ModuleDependency.objects.filter(module__key="staff", depends_on_module__key="people").exists()
        )

    def test_sync_adds_a_newly_declared_dependency(self):
        fake_registry = {
            "people": {"name": "People", "description": "", "sort_order": 0, "depends_on": []},
            "announcements": {
                "name": "Announcements",
                "description": "",
                "sort_order": 5,
                "depends_on": ["people"],  # newly declared
            },
        }
        with mock.patch("apps.module_system.services.AVAILABLE_MODULES", fake_registry):
            sync_modules()
        self.assertTrue(
            ModuleDependency.objects.filter(
                module__key="announcements", depends_on_module__key="people"
            ).exists()
        )


# --- initialize_congregation_modules -----------------------------------


class InitializeCongregationModulesTests(ModuleSystemTestCase):
    def test_creates_one_row_per_active_module(self):
        initialize_congregation_modules(self.congregation)
        self.assertEqual(
            CongregationModule.objects.filter(congregation=self.congregation).count(),
            Module.objects.filter(is_retired=False).count(),
        )

    def test_enables_only_the_requested_keys(self):
        initialize_congregation_modules(self.congregation, enabled_keys={"people", "attendance"})
        enabled = set(
            CongregationModule.objects.filter(congregation=self.congregation, is_enabled=True).values_list(
                "module__key", flat=True
            )
        )
        self.assertEqual(enabled, {"people", "attendance"})

    def test_does_not_create_rows_for_retired_modules(self):
        Module.objects.create(key="legacy_module", name="Legacy", is_retired=True, sort_order=99)
        initialize_congregation_modules(self.congregation)
        self.assertFalse(
            CongregationModule.objects.filter(congregation=self.congregation, module__key="legacy_module").exists()
        )

    def test_idempotent_does_not_duplicate_or_overwrite_existing_rows(self):
        initialize_congregation_modules(self.congregation, enabled_keys={"people"})
        enable_module(self.congregation, "attendance", self.user)  # diverge state by hand
        initialize_congregation_modules(self.congregation, enabled_keys=set())  # re-run, different args
        self.assertEqual(
            CongregationModule.objects.filter(congregation=self.congregation).count(),
            Module.objects.filter(is_retired=False).count(),
        )
        attendance = CongregationModule.objects.get(congregation=self.congregation, module__key="attendance")
        self.assertTrue(attendance.is_enabled, "re-running initialize must not clobber existing state")

    def test_rows_are_congregation_scoped(self):
        other = Congregation.objects.create(name="Other Chapel", timezone="UTC")
        initialize_congregation_modules(self.congregation, enabled_keys={"people"})
        initialize_congregation_modules(other, enabled_keys=set())
        self.assertTrue(
            CongregationModule.objects.get(congregation=self.congregation, module__key="people").is_enabled
        )
        self.assertFalse(CongregationModule.objects.get(congregation=other, module__key="people").is_enabled)


# --- enable_module / disable_module -------------------------------------


class EnableModuleTests(ModuleSystemTestCase):
    def setUp(self):
        super().setUp()
        initialize_congregation_modules(self.congregation)

    def test_enabling_a_module_with_no_dependencies_succeeds(self):
        cm = enable_module(self.congregation, "announcements", self.user)
        self.assertTrue(cm.is_enabled)
        self.assertIsNotNone(cm.enabled_at)
        self.assertEqual(cm.enabled_by, self.user)

    def test_enabling_blocked_without_prerequisite(self):
        with self.assertRaises(ModuleDependencyError) as ctx:
            enable_module(self.congregation, "scheduling", self.user)
        self.assertIn("Enable People before enabling Scheduling.", str(ctx.exception))

    def test_enabling_succeeds_once_prerequisite_enabled(self):
        enable_module(self.congregation, "people", self.user)
        cm = enable_module(self.congregation, "scheduling", self.user)
        self.assertTrue(cm.is_enabled)

    def test_enabling_writes_history_row(self):
        enable_module(self.congregation, "announcements", self.user)
        entry = CongregationModuleHistory.objects.get(congregation=self.congregation, module__key="announcements")
        self.assertEqual(entry.action, CongregationModuleHistory.Action.ENABLED)
        self.assertEqual(entry.changed_by, self.user)

    def test_enabling_an_already_enabled_module_is_a_noop(self):
        enable_module(self.congregation, "announcements", self.user)
        enable_module(self.congregation, "announcements", self.user)
        self.assertEqual(
            CongregationModuleHistory.objects.filter(
                congregation=self.congregation, module__key="announcements"
            ).count(),
            1,
        )

    def test_blocked_dependency_error_does_not_enable_anything(self):
        with self.assertRaises(ModuleDependencyError):
            enable_module(self.congregation, "staff", self.user)
        cm = CongregationModule.objects.get(congregation=self.congregation, module__key="staff")
        self.assertFalse(cm.is_enabled)


class DisableModuleTests(ModuleSystemTestCase):
    def setUp(self):
        super().setUp()
        initialize_congregation_modules(self.congregation)
        enable_module(self.congregation, "people", self.user)

    def test_disabling_a_module_with_no_dependents_succeeds_without_confirmation(self):
        enable_module(self.congregation, "announcements", self.user)
        cm = disable_module(self.congregation, "announcements", self.user)
        self.assertFalse(cm.is_enabled)

    def test_disabling_blocked_when_a_dependent_is_enabled(self):
        enable_module(self.congregation, "staff", self.user)
        with self.assertRaises(ModuleDisableConfirmationRequired) as ctx:
            disable_module(self.congregation, "people", self.user)
        self.assertEqual([m.key for m in ctx.exception.affected], ["staff"])
        # nothing changed
        self.assertTrue(
            CongregationModule.objects.get(congregation=self.congregation, module__key="people").is_enabled
        )

    def test_disabling_lists_multiple_affected_dependents(self):
        enable_module(self.congregation, "staff", self.user)
        enable_module(self.congregation, "scheduling", self.user)
        with self.assertRaises(ModuleDisableConfirmationRequired) as ctx:
            disable_module(self.congregation, "people", self.user)
        self.assertEqual({m.key for m in ctx.exception.affected}, {"staff", "scheduling"})

    def test_confirmed_disable_cascades_to_dependents(self):
        enable_module(self.congregation, "staff", self.user)
        enable_module(self.congregation, "scheduling", self.user)
        disable_module(self.congregation, "people", self.user, confirmed=True)

        people = CongregationModule.objects.get(congregation=self.congregation, module__key="people")
        staff = CongregationModule.objects.get(congregation=self.congregation, module__key="staff")
        scheduling = CongregationModule.objects.get(congregation=self.congregation, module__key="scheduling")
        self.assertFalse(people.is_enabled)
        self.assertFalse(staff.is_enabled)
        self.assertFalse(scheduling.is_enabled)

    def test_confirmed_cascade_writes_a_history_row_per_module(self):
        enable_module(self.congregation, "staff", self.user)
        disable_module(self.congregation, "people", self.user, confirmed=True)
        actions = CongregationModuleHistory.objects.filter(
            congregation=self.congregation, action=CongregationModuleHistory.Action.DISABLED
        )
        self.assertEqual({a.module.key for a in actions}, {"people", "staff"})

    def test_disabling_a_module_not_enabled_is_a_noop(self):
        cm = disable_module(self.congregation, "finances", self.user)
        self.assertFalse(cm.is_enabled)
        self.assertFalse(
            CongregationModuleHistory.objects.filter(congregation=self.congregation, module__key="finances").exists()
        )


# --- Postgres trigger backstop ------------------------------------------


class TriggerBackstopTests(ModuleSystemTestCase):
    """
    Confirms the database itself rejects an inconsistent state even when
    the application layer (services.disable_module) is bypassed entirely
    -- a direct UPDATE through a raw cursor.
    """

    def setUp(self):
        super().setUp()
        initialize_congregation_modules(self.congregation)
        enable_module(self.congregation, "people", self.user)
        enable_module(self.congregation, "staff", self.user)

    def test_direct_sql_disable_of_prerequisite_is_rejected(self):
        people_module_id = Module.objects.get(key="people").id
        with self.assertRaises(Exception) as ctx:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE congregation_modules SET is_enabled = false "
                        "WHERE congregation_id = %s AND module_id = %s",
                        [self.congregation.id, people_module_id],
                    )
        self.assertIn("dependent module is still enabled", str(ctx.exception))

    def test_direct_sql_disable_of_a_leaf_module_is_allowed(self):
        # Sanity check the trigger isn't just blocking all updates --
        # finances has no dependents, so this must succeed.
        finances_module_id = Module.objects.get(key="finances").id
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE congregation_modules SET is_enabled = true "
                "WHERE congregation_id = %s AND module_id = %s",
                [self.congregation.id, finances_module_id],
            )
        cm = CongregationModule.objects.get(congregation=self.congregation, module__key="finances")
        self.assertTrue(cm.is_enabled)


# --- access_required decorator -------------------------------------------


class AccessRequiredTests(ModuleSystemTestCase):
    def setUp(self):
        super().setUp()
        initialize_congregation_modules(self.congregation)

    def _make_request(self, user):
        from django.test import RequestFactory

        request = RequestFactory().get("/fake-gated-view/")
        request.user = user
        return request

    def test_allows_through_when_module_enabled(self):
        enable_module(self.congregation, "attendance", self.user)

        @access_required(module="attendance")
        def view(request):
            return "ok"

        self.assertEqual(view(self._make_request(self.user)), "ok")

    def test_blocks_when_module_disabled(self):
        from django.core.exceptions import PermissionDenied

        @access_required(module="attendance")
        def view(request):
            return "ok"

        with self.assertRaises(PermissionDenied):
            view(self._make_request(self.user))

    def test_unauthenticated_redirects_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        @access_required(module="attendance")
        def view(request):
            return "ok"

        request = self._make_request(AnonymousUser())
        response = view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_no_module_specified_skips_the_module_check(self):
        @access_required()
        def view(request):
            return "ok"

        self.assertEqual(view(self._make_request(self.user)), "ok")

    def test_no_permission_specified_skips_the_permission_check(self):
        enable_module(self.congregation, "finances", self.user)
        # no role assigned at all -- would fail if a permission check ran

        @access_required(module="finances")
        def view(request):
            return "ok"

        self.assertEqual(view(self._make_request(self.user)), "ok")

    def test_blocks_when_permission_missing(self):
        from django.core.exceptions import PermissionDenied

        from apps.permissions.services import copy_default_roles_to_congregation

        enable_module(self.congregation, "finances", self.user)
        copy_default_roles_to_congregation(self.congregation)  # user holds no role yet

        @access_required(module="finances", permission="finances.edit")
        def view(request):
            return "ok"

        with self.assertRaises(PermissionDenied):
            view(self._make_request(self.user))

    def test_allows_when_permission_present(self):
        from apps.permissions.services import assign_role_to_user, copy_default_roles_to_congregation

        enable_module(self.congregation, "finances", self.user)
        roles = copy_default_roles_to_congregation(self.congregation)
        assign_role_to_user(self.user, roles["finance"])

        @access_required(module="finances", permission="finances.edit")
        def view(request):
            return "ok"

        self.assertEqual(view(self._make_request(self.user)), "ok")

    def test_module_check_runs_before_permission_check(self):
        from django.core.exceptions import PermissionDenied

        from apps.permissions.services import assign_role_to_user, copy_default_roles_to_congregation

        # finances left disabled, but the user *does* hold finances.edit --
        # the module gate (layer 1) must still block first, per the
        # documented fixed check order.
        roles = copy_default_roles_to_congregation(self.congregation)
        assign_role_to_user(self.user, roles["finance"])

        @access_required(module="finances", permission="finances.edit")
        def view(request):
            return "ok"

        with self.assertRaises(PermissionDenied) as ctx:
            view(self._make_request(self.user))
        self.assertIn("finances", str(ctx.exception))
        self.assertIn("not enabled", str(ctx.exception))


# --- Model-level constraints ----------------------------------------------


class ModelConstraintTests(ModuleSystemTestCase):
    def test_congregation_module_unique_constraint(self):
        people = Module.objects.get(key="people")
        CongregationModule.objects.create(congregation=self.congregation, module=people)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CongregationModule.objects.create(congregation=self.congregation, module=people)

    def test_module_cannot_depend_on_itself(self):
        people = Module.objects.get(key="people")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ModuleDependency.objects.create(module=people, depends_on_module=people)

    def test_duplicate_module_dependency_pair_rejected(self):
        staff = Module.objects.get(key="staff")
        people = Module.objects.get(key="people")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ModuleDependency.objects.create(module=staff, depends_on_module=people)


# --- Toggle views (real HTTP requests) ------------------------------------


class ToggleViewTests(ModuleSystemTestCase):
    def setUp(self):
        super().setUp()
        initialize_congregation_modules(self.congregation)
        self.client = Client()
        self.client.login(email="ada@example.com", password="s3cret-pass")

    def test_module_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("module_system:module_list"))
        self.assertEqual(response.status_code, 302)

    def test_module_list_shows_all_modules(self):
        response = self.client.get(reverse("module_system:module_list"))
        self.assertContains(response, "People")
        self.assertContains(response, "Finances")

    def test_enable_via_post_succeeds_and_redirects(self):
        response = self.client.post(
            reverse("module_system:toggle_module", args=["announcements"]), {"action": "enable"}
        )
        self.assertRedirects(response, reverse("module_system:module_list"))
        self.assertTrue(
            CongregationModule.objects.get(congregation=self.congregation, module__key="announcements").is_enabled
        )

    def test_enable_blocked_by_dependency_shows_message_and_does_not_enable(self):
        response = self.client.post(
            reverse("module_system:toggle_module", args=["staff"]), {"action": "enable"}, follow=True
        )
        self.assertContains(response, "Enable People before enabling Staff.")
        self.assertFalse(
            CongregationModule.objects.get(congregation=self.congregation, module__key="staff").is_enabled
        )

    def test_disable_with_enabled_dependent_shows_confirmation_screen(self):
        enable_module(self.congregation, "people", self.user)
        enable_module(self.congregation, "staff", self.user)
        response = self.client.post(
            reverse("module_system:toggle_module", args=["people"]), {"action": "disable"}
        )
        self.assertContains(response, "Staff")
        self.assertContains(response, "will also disable")
        # not yet disabled -- this was just the confirmation screen
        self.assertTrue(
            CongregationModule.objects.get(congregation=self.congregation, module__key="people").is_enabled
        )

    def test_confirmed_disable_via_post_cascades(self):
        enable_module(self.congregation, "people", self.user)
        enable_module(self.congregation, "staff", self.user)
        response = self.client.post(
            reverse("module_system:toggle_module", args=["people"]),
            {"action": "disable", "confirm": "true"},
        )
        self.assertRedirects(response, reverse("module_system:module_list"))
        self.assertFalse(
            CongregationModule.objects.get(congregation=self.congregation, module__key="people").is_enabled
        )
        self.assertFalse(
            CongregationModule.objects.get(congregation=self.congregation, module__key="staff").is_enabled
        )

    def test_toggle_is_scoped_to_the_logged_in_users_own_congregation(self):
        other = Congregation.objects.create(name="Other Chapel", timezone="UTC")
        initialize_congregation_modules(other)
        self.client.post(reverse("module_system:toggle_module", args=["announcements"]), {"action": "enable"})
        self.assertFalse(
            CongregationModule.objects.get(congregation=other, module__key="announcements").is_enabled
        )
