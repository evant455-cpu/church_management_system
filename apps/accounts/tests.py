from django.core import mail
from django.db.models import RestrictedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.people.models import Person
from apps.tenancy.models import Congregation


class UserManagerTests(TestCase):
    def setUp(self):
        self.congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        self.person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )

    def test_create_user_normalizes_email_to_lowercase(self):
        user = User.objects.create_user(
            email="Ada.Lovelace@EXAMPLE.com",
            password="s3cret-pass",
            congregation=self.congregation,
            person=self.person,
        )
        self.assertEqual(user.email, "ada.lovelace@example.com")

    def test_create_user_defaults_not_staff_not_superuser(self):
        user = User.objects.create_user(
            email="ada@example.com", password="s3cret-pass", congregation=self.congregation, person=self.person
        )
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_create_superuser_sets_staff_and_superuser(self):
        user = User.objects.create_superuser(
            email="ops@example.com", password="s3cret-pass", congregation=self.congregation, person=self.person
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_create_user_requires_congregation(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="ada@example.com", password="s3cret-pass", person=self.person)

    def test_create_user_requires_person(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="ada@example.com", password="s3cret-pass", congregation=self.congregation)

    def test_password_is_hashed_not_stored_plaintext(self):
        user = User.objects.create_user(
            email="ada@example.com", password="s3cret-pass", congregation=self.congregation, person=self.person
        )
        self.assertNotEqual(user.password, "s3cret-pass")
        self.assertTrue(user.check_password("s3cret-pass"))

    def test_email_uniqueness_enforced(self):
        User.objects.create_user(
            email="ada@example.com", password="s3cret-pass", congregation=self.congregation, person=self.person
        )
        other_person = Person.objects.create(
            congregation=self.congregation, first_name="Grace", last_name="Hopper"
        )
        with self.assertRaises(Exception):
            User.objects.create_user(
                email="ada@example.com",
                password="another-pass",
                congregation=self.congregation,
                person=other_person,
            )


class UserDeletionPolicyTests(TestCase):
    def test_person_deletion_restricted_while_user_references_them(self):
        congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        person = Person.objects.create(congregation=congregation, first_name="Ada", last_name="Lovelace")
        User.objects.create_user(
            email="ada@example.com", password="s3cret-pass", congregation=congregation, person=person
        )
        with self.assertRaises(RestrictedError):
            person.delete()


@override_settings(ALLOWED_HOSTS=["testserver"])
class AuthFlowTests(TestCase):
    def setUp(self):
        self.congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        self.person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )
        self.user = User.objects.create_user(
            email="ada@example.com", password="s3cret-pass", congregation=self.congregation, person=self.person
        )
        self.client = Client()

    def test_login_with_email_succeeds(self):
        response = self.client.post(
            reverse("login"), {"username": "ada@example.com", "password": "s3cret-pass"}
        )
        self.assertRedirects(response, reverse("home"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(
            reverse("login"), {"username": "ada@example.com", "password": "wrong-pass"}
        )
        self.assertEqual(response.status_code, 200)  # re-renders form, no redirect
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_home_requires_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('home')}")

    def test_logout_redirects_to_login(self):
        self.client.login(email="ada@example.com", password="s3cret-pass")
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))

    def test_password_reset_sends_email_with_working_link(self):
        response = self.client.post(reverse("password_reset"), {"email": "ada@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ada@example.com", mail.outbox[0].body)

        # Extract the reset link Django actually generated and follow it.
        import re

        match = re.search(r"/accounts/reset/[^\s]+", mail.outbox[0].body)
        self.assertIsNotNone(match, "Reset link not found in email body")
        reset_url = match.group(0)

        confirm_response = self.client.get(reset_url, follow=True)
        self.assertEqual(confirm_response.status_code, 200)
        # Django redirects to a sentinel URL with a fresh token embedded in session,
        # then renders the actual set-password form.
        self.assertContains(confirm_response, "Set a new password")

        final_url = confirm_response.redirect_chain[-1][0]
        set_password_response = self.client.post(
            final_url, {"new_password1": "brand-new-pass-99", "new_password2": "brand-new-pass-99"}
        )
        self.assertRedirects(set_password_response, reverse("password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-pass-99"))

    def test_no_password_reset_email_for_unknown_address(self):
        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


@override_settings(ALLOWED_HOSTS=["testserver"])
class AdminAccessTests(TestCase):
    def setUp(self):
        self.congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        self.ops_person = Person.objects.create(
            congregation=self.congregation, first_name="Ops", last_name="Admin"
        )
        self.superuser = User.objects.create_superuser(
            email="ops@example.com",
            password="s3cret-pass",
            congregation=self.congregation,
            person=self.ops_person,
        )
        self.regular_person = Person.objects.create(
            congregation=self.congregation, first_name="Regular", last_name="Member"
        )
        self.regular_user = User.objects.create_user(
            email="member@example.com",
            password="s3cret-pass",
            congregation=self.congregation,
            person=self.regular_person,
        )
        self.client = Client()

    def test_superuser_can_reach_admin_index(self):
        self.client.login(email="ops@example.com", password="s3cret-pass")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_ordinary_user_cannot_reach_admin(self):
        self.client.login(email="member@example.com", password="s3cret-pass")
        response = self.client.get("/admin/")
        # Django Admin redirects non-staff users to its own login page rather than 403ing outright.
        self.assertNotEqual(response.status_code, 200)

    def test_superuser_can_view_user_changelist(self):
        self.client.login(email="ops@example.com", password="s3cret-pass")
        response = self.client.get("/admin/accounts/user/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ops@example.com")

    def test_superuser_can_create_user_through_real_admin_form(self):
        """
        End-to-end through the actual admin add-form codepath (not the ORM
        directly) -- this is the workflow Phase 1 explicitly relies on for
        creating test congregations/users before Phase 5's signup wizard
        exists.
        """
        new_person = Person.objects.create(
            congregation=self.congregation, first_name="New", last_name="Staffer"
        )
        self.client.login(email="ops@example.com", password="s3cret-pass")
        response = self.client.post(
            "/admin/accounts/user/add/",
            {
                "email": "newstaffer@example.com",
                "congregation": self.congregation.id,
                "person": new_person.id,
                "password1": "a-strong-passw0rd-99",
                "password2": "a-strong-passw0rd-99",
            },
        )
        self.assertEqual(response.status_code, 302, response.context["adminform"].form.errors if response.status_code == 200 else None)
        created = User.objects.get(email="newstaffer@example.com")
        self.assertTrue(created.check_password("a-strong-passw0rd-99"))
        self.assertEqual(created.congregation_id, self.congregation.id)

    def test_congregation_can_be_created_through_admin(self):
        self.client.login(email="ops@example.com", password="s3cret-pass")
        response = self.client.post(
            "/admin/tenancy/congregation/add/",
            {"name": "New Congregation", "timezone": "America/New_York"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Congregation.objects.filter(name="New Congregation").exists())
