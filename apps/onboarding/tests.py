from unittest import mock

import stripe
from django.contrib.auth.hashers import check_password
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.billing import stripe_client
from apps.billing.models import Subscription, SubscriptionEvent
from apps.module_system.models import CongregationModule, CongregationModuleHistory
from apps.onboarding import services
from apps.onboarding.forms import AccountForm, CongregationForm, ModuleSelectionForm
from apps.permissions.models import UserRole
from apps.tenancy.models import Congregation


class FakeStripeObject(dict):
    """Same stand-in apps.billing.tests uses -- attribute AND dict-style access, no SDK/network dependency."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _fake_intent(secret="seti_secret_test"):
    return FakeStripeObject(id="seti_test", client_secret=secret)


def _fake_customer_and_subscription():
    customer = FakeStripeObject(id="cus_test")
    subscription = FakeStripeObject(
        id="sub_test",
        status="trialing",
        trial_end=None,
        # current_period_start/end live on the subscription item, not the
        # top-level object, as of Stripe's Basil API version -- see
        # apps.billing.services._subscription_period()'s docstring.
        items=FakeStripeObject(data=[FakeStripeObject(current_period_start=None, current_period_end=None)]),
    )
    return customer, subscription


# --- Forms -------------------------------------------------------------


class AccountFormTests(TestCase):
    def _data(self, **overrides):
        data = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "password1": "correct-horse-battery-staple",
            "password2": "correct-horse-battery-staple",
        }
        data.update(overrides)
        return data

    def test_valid_form_hashes_password_and_never_stores_plaintext(self):
        form = AccountForm(self._data())
        self.assertTrue(form.is_valid(), form.errors)
        session_data = form.session_data()
        self.assertNotIn("password1", session_data)
        self.assertNotIn("password2", session_data)
        self.assertNotEqual(session_data["password_hash"], "correct-horse-battery-staple")
        self.assertTrue(check_password("correct-horse-battery-staple", session_data["password_hash"]))

    def test_mismatched_passwords_rejected(self):
        form = AccountForm(self._data(password2="something-else"))
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_duplicate_email_rejected(self):
        congregation = Congregation.objects.create(name="Existing Church", timezone="UTC")
        from apps.people.models import Person

        person = Person.objects.create(congregation=congregation, first_name="Bea", last_name="Existing")
        User.objects.create_user(
            email="ada@example.com", password="whatever-1", congregation=congregation, person=person
        )
        form = AccountForm(self._data())
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_weak_password_rejected(self):
        form = AccountForm(self._data(password1="password", password2="password"))
        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)


class CongregationFormTests(TestCase):
    def test_valid_timezone_accepted(self):
        form = CongregationForm({"name": "Grace Chapel", "timezone": "America/Chicago"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_timezone_rejected(self):
        form = CongregationForm({"name": "Grace Chapel", "timezone": "Mars/Olympus_Mons"})
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)

    def test_timezone_is_a_fixed_dropdown_not_freeform_text(self):
        # A real but differently-cased/spaced string should be rejected --
        # ChoiceField only accepts an exact match from zoneinfo, not a
        # freeform guess at the right spelling.
        form = CongregationForm({"name": "Grace Chapel", "timezone": "america/chicago"})
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)

    def test_size_category_must_be_one_of_the_defined_buckets(self):
        form = CongregationForm({"name": "Grace Chapel", "timezone": "UTC", "size_category": "tiny"})
        self.assertFalse(form.is_valid())
        self.assertIn("size_category", form.errors)

    def test_size_category_accepts_a_defined_bucket(self):
        form = CongregationForm({"name": "Grace Chapel", "timezone": "UTC", "size_category": "501+"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.session_data()["size_category"], "501+")

    def test_blank_optional_fields_become_none_in_session_data(self):
        form = CongregationForm({"name": "Grace Chapel", "timezone": "UTC"})
        self.assertTrue(form.is_valid(), form.errors)
        data = form.session_data()
        self.assertIsNone(data["city"])
        self.assertIsNone(data["size_category"])


class ModuleSelectionFormTests(TestCase):
    def test_no_modules_selected_is_valid(self):
        form = ModuleSelectionForm({})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.session_data()["modules"], [])

    def test_selecting_dependent_without_prerequisite_rejected(self):
        form = ModuleSelectionForm({"modules": ["staff"]})
        self.assertFalse(form.is_valid())
        self.assertIn("modules", form.errors)

    def test_selecting_dependent_with_prerequisite_accepted(self):
        form = ModuleSelectionForm({"modules": ["people", "staff", "scheduling"]})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.session_data()["modules"], ["people", "scheduling", "staff"])


# --- Full wizard, end to end via the test Client ------------------------


class WizardFlowTests(TestCase):
    """Drives the real views in order, the way a browser would, modulo Stripe.js."""

    def setUp(self):
        self.client = Client()

    def _complete_account_step(self):
        return self.client.post(
            reverse("onboarding:step_account"),
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "password1": "correct-horse-battery-staple",
                "password2": "correct-horse-battery-staple",
            },
        )

    def _complete_congregation_step(self):
        return self.client.post(
            reverse("onboarding:step_congregation"),
            {"name": "Grace Chapel", "timezone": "America/Chicago"},
        )

    def _complete_payment_step(self):
        return self.client.post(reverse("onboarding:step_payment"), {"payment_method_id": "pm_test_123"})

    def _complete_modules_step(self, modules=("people", "attendance")):
        return self.client.post(reverse("onboarding:step_modules"), {"modules": list(modules)})

    def test_steps_must_be_completed_in_order(self):
        response = self.client.get(reverse("onboarding:step_congregation"))
        self.assertRedirects(response, reverse("onboarding:step_account"))

        # step_modules only checks its own immediate prerequisite (payment) --
        # it doesn't walk the whole chain back to step 1 itself.
        response = self.client.get(reverse("onboarding:step_modules"))
        self.assertRedirects(response, reverse("onboarding:step_payment"), target_status_code=302)

    def test_finish_redirects_back_if_wizard_incomplete(self):
        self._complete_account_step()
        response = self.client.get(reverse("onboarding:finish"))
        self.assertRedirects(response, reverse("onboarding:step_congregation"))

    def test_payment_step_caches_setup_intent_across_get_requests(self):
        self._complete_account_step()
        self._complete_congregation_step()
        with mock.patch.object(stripe_client, "create_setup_intent", return_value=_fake_intent()) as mocked:
            self.client.get(reverse("onboarding:step_payment"))
            self.client.get(reverse("onboarding:step_payment"))
        mocked.assert_called_once()

    def test_full_happy_path_creates_everything_and_logs_in(self):
        self._complete_account_step()
        self._complete_congregation_step()
        with mock.patch.object(stripe_client, "create_setup_intent", return_value=_fake_intent()):
            self._complete_payment_step()
        self._complete_modules_step(modules=("people", "staff"))

        customer, subscription = _fake_customer_and_subscription()
        with mock.patch.object(stripe_client, "create_customer", return_value=customer), mock.patch.object(
            stripe_client, "create_subscription", return_value=subscription
        ):
            response = self.client.post(reverse("onboarding:finish"))

        self.assertRedirects(response, reverse("home"))

        congregation = Congregation.objects.get(name="Grace Chapel")
        self.assertIsNotNone(congregation.owner_user)

        user = User.objects.get(email="ada@example.com")
        self.assertEqual(congregation.owner_user_id, user.id)
        self.assertEqual(user.person.first_name, "Ada")

        # Owner role assigned.
        self.assertTrue(UserRole.objects.filter(user=user, role__slug="owner", role__congregation=congregation).exists())

        # Selected modules enabled, unselected ones present but disabled.
        people_cm = CongregationModule.objects.get(congregation=congregation, module__key="people")
        finances_cm = CongregationModule.objects.get(congregation=congregation, module__key="finances")
        self.assertTrue(people_cm.is_enabled)
        self.assertFalse(finances_cm.is_enabled)

        # History rows written only for the enabled ones.
        history_keys = set(
            CongregationModuleHistory.objects.filter(congregation=congregation).values_list(
                "module__key", flat=True
            )
        )
        self.assertEqual(history_keys, {"people", "staff"})

        # Subscription + its trial_started event.
        subscription_row = Subscription.objects.get(congregation=congregation)
        self.assertEqual(subscription_row.status, Subscription.Status.TRIALING)
        self.assertTrue(
            SubscriptionEvent.objects.filter(congregation=congregation, event_type="trial_started").exists()
        )

        # Session cleared, user actually logged in.
        self.assertNotIn(services.SESSION_KEY, self.client.session)
        response = self.client.get(reverse("home"))
        self.assertEqual(response.wsgi_request.user, user)

    def test_finish_review_screen_renders_on_get(self):
        self._complete_account_step()
        self._complete_congregation_step()
        with mock.patch.object(stripe_client, "create_setup_intent", return_value=_fake_intent()):
            self._complete_payment_step()
        self._complete_modules_step()

        response = self.client.get(reverse("onboarding:finish"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ada Lovelace")
        self.assertContains(response, "Grace Chapel")

    def test_card_declined_shows_retryable_error_and_keeps_session(self):
        self._complete_account_step()
        self._complete_congregation_step()
        with mock.patch.object(stripe_client, "create_setup_intent", return_value=_fake_intent()):
            self._complete_payment_step()
        self._complete_modules_step()

        with mock.patch.object(
            stripe_client, "create_customer", side_effect=stripe.error.CardError("declined", None, None)
        ):
            response = self.client.post(reverse("onboarding:finish"))

        self.assertEqual(response.status_code, 400)
        self.assertIn(services.SESSION_KEY, self.client.session)
        self.assertFalse(Congregation.objects.filter(name="Grace Chapel").exists())


# --- complete_signup() unit tests (retry + compensation) ----------------


class CompleteSignupTests(TestCase):
    def _account(self):
        return {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "password_hash": "pbkdf2_sha256$irrelevant$for$these$tests",
        }

    def _congregation_data(self):
        return {
            "name": "Grace Chapel",
            "timezone": "UTC",
            "address_line1": None,
            "address_line2": None,
            "city": None,
            "state": None,
            "postal_code": None,
            "country": None,
            "size_category": None,
        }

    def _call(self, modules=("people",), payment_method_id="pm_test"):
        return services.complete_signup(
            account=self._account(),
            congregation_data=self._congregation_data(),
            modules_selected=modules,
            payment_method_id=payment_method_id,
        )

    def test_stripe_failure_raises_before_touching_local_data_no_compensation_needed(self):
        with mock.patch.object(
            stripe_client, "create_customer", side_effect=stripe.error.CardError("declined", None, None)
        ), mock.patch.object(stripe_client, "cancel_subscription") as mock_cancel:
            with self.assertRaises(services.StripeSetupFailed):
                self._call()
        mock_cancel.assert_not_called()
        self.assertEqual(Congregation.objects.count(), 0)

    def test_happy_path_returns_user_and_congregation(self):
        customer, subscription = _fake_customer_and_subscription()
        with mock.patch.object(stripe_client, "create_customer", return_value=customer), mock.patch.object(
            stripe_client, "create_subscription", return_value=subscription
        ):
            user, congregation = self._call()
        self.assertEqual(congregation.name, "Grace Chapel")
        self.assertEqual(congregation.owner_user_id, user.id)

    def test_transient_local_failure_is_retried_then_succeeds(self):
        customer, subscription = _fake_customer_and_subscription()
        real_write = services._write_signup_rows
        call_count = {"n": 0}

        def flaky_write(**kwargs):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise RuntimeError("simulated transient DB blip")
            return real_write(**kwargs)

        with mock.patch.object(stripe_client, "create_customer", return_value=customer), mock.patch.object(
            stripe_client, "create_subscription", return_value=subscription
        ), mock.patch.object(services, "_write_signup_rows", side_effect=flaky_write), mock.patch.object(
            stripe_client, "cancel_subscription"
        ) as mock_cancel:
            user, congregation = self._call()

        self.assertEqual(call_count["n"], 2)
        mock_cancel.assert_not_called()
        self.assertEqual(congregation.owner_user_id, user.id)

    def test_local_failure_exhausting_retries_compensates_and_raises(self):
        customer, subscription = _fake_customer_and_subscription()
        with mock.patch.object(stripe_client, "create_customer", return_value=customer), mock.patch.object(
            stripe_client, "create_subscription", return_value=subscription
        ), mock.patch.object(
            services, "_write_signup_rows", side_effect=RuntimeError("permanently broken")
        ), mock.patch.object(stripe_client, "cancel_subscription", return_value="canceled") as mock_cancel:
            with self.assertRaises(services.SignupTransactionFailed):
                self._call()

        mock_cancel.assert_called_once_with("sub_test")
        self.assertEqual(Congregation.objects.count(), 0)

    def test_compensation_failure_is_swallowed_but_still_raises_signup_failed(self):
        customer, subscription = _fake_customer_and_subscription()
        with mock.patch.object(stripe_client, "create_customer", return_value=customer), mock.patch.object(
            stripe_client, "create_subscription", return_value=subscription
        ), mock.patch.object(
            services, "_write_signup_rows", side_effect=RuntimeError("permanently broken")
        ), mock.patch.object(
            stripe_client, "cancel_subscription", side_effect=stripe.error.StripeError("cancel also failed")
        ):
            with self.assertRaises(services.SignupTransactionFailed):
                self._call()
        self.assertEqual(Congregation.objects.count(), 0)

    def test_retry_attempt_count_matches_documented_budget(self):
        customer, subscription = _fake_customer_and_subscription()
        with mock.patch.object(stripe_client, "create_customer", return_value=customer), mock.patch.object(
            stripe_client, "create_subscription", return_value=subscription
        ), mock.patch.object(
            services, "_write_signup_rows", side_effect=RuntimeError("permanently broken")
        ) as mock_write, mock.patch.object(stripe_client, "cancel_subscription", return_value="canceled"):
            with self.assertRaises(services.SignupTransactionFailed):
                self._call()
        self.assertEqual(mock_write.call_count, services.LOCAL_TRANSACTION_MAX_ATTEMPTS)
