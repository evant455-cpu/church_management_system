import datetime
from unittest import mock

import stripe
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.billing import services, stripe_client
from apps.billing.access import owner_required
from apps.billing.models import Subscription, SubscriptionEvent
from apps.module_system.access import access_required
from apps.people.models import Person
from apps.tenancy.models import Congregation


class BillingTestCase(TestCase):
    """Shared fixture -- a congregation with an owner, mirroring ModuleSystemTestCase's pattern."""

    def setUp(self):
        self.congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        self.owner_person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )
        self.owner = User.objects.create_user(
            email="ada@example.com",
            password="s3cret-pass",
            congregation=self.congregation,
            person=self.owner_person,
        )
        self.congregation.owner_user = self.owner
        self.congregation.save(update_fields=["owner_user"])

        self.staff_person = Person.objects.create(
            congregation=self.congregation, first_name="Bea", last_name="Staffer"
        )
        self.staff_user = User.objects.create_user(
            email="bea@example.com",
            password="s3cret-pass",
            congregation=self.congregation,
            person=self.staff_person,
        )

    def _subscription(self, status):
        return Subscription.objects.create(
            congregation=self.congregation,
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
            status=status,
        )


# --- Model constraints -------------------------------------------------


class SubscriptionModelTests(BillingTestCase):
    def test_one_subscription_per_congregation(self):
        self._subscription(Subscription.Status.ACTIVE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._subscription(Subscription.Status.ACTIVE)


class SubscriptionEventModelTests(BillingTestCase):
    def test_duplicate_stripe_event_id_rejected(self):
        SubscriptionEvent.objects.create(
            congregation=self.congregation,
            event_type="payment_succeeded",
            source=SubscriptionEvent.Source.STRIPE_WEBHOOK,
            stripe_event_id="evt_123",
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SubscriptionEvent.objects.create(
                    congregation=self.congregation,
                    event_type="payment_failed",
                    source=SubscriptionEvent.Source.STRIPE_WEBHOOK,
                    stripe_event_id="evt_123",
                    occurred_at=datetime.datetime.now(datetime.timezone.utc),
                )

    def test_multiple_null_stripe_event_ids_allowed(self):
        """admin_action rows have no stripe_event_id -- the constraint is partial, not global-null-unique."""
        SubscriptionEvent.objects.create(
            congregation=self.congregation,
            event_type="trial_started",
            source=SubscriptionEvent.Source.ADMIN_ACTION,
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
        )
        SubscriptionEvent.objects.create(
            congregation=self.congregation,
            event_type="trial_started",
            source=SubscriptionEvent.Source.ADMIN_ACTION,
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
        )
        self.assertEqual(SubscriptionEvent.objects.count(), 2)


# --- Access gate layer 3 (the billing check inside access_required) ---


class BillingAccessGateTests(BillingTestCase):
    def _request(self, method="get", user=None):
        factory = RequestFactory()
        request = getattr(factory, method)("/fake-billed-view/")
        request.user = user if user is not None else self.owner
        return request

    def test_active_status_allows_get_and_post(self):
        self._subscription(Subscription.Status.ACTIVE)

        @access_required()
        def view(request):
            return "ok"

        self.assertEqual(view(self._request("get")), "ok")
        self.assertEqual(view(self._request("post")), "ok")

    def test_trialing_status_allows_full_access(self):
        self._subscription(Subscription.Status.TRIALING)

        @access_required()
        def view(request):
            return "ok"

        self.assertEqual(view(self._request("post")), "ok")

    def test_past_due_status_allows_full_access(self):
        """past_due is full access + a warning banner (a UI concern) -- not blocked at the gate."""
        self._subscription(Subscription.Status.PAST_DUE)

        @access_required()
        def view(request):
            return "ok"

        self.assertEqual(view(self._request("post")), "ok")

    def test_read_only_blocks_writes_but_allows_reads(self):
        self._subscription(Subscription.Status.READ_ONLY)

        @access_required()
        def view(request):
            return "ok"

        self.assertEqual(view(self._request("get")), "ok")
        with self.assertRaises(PermissionDenied):
            view(self._request("post"))

    def test_canceled_blocks_writes_but_allows_reads(self):
        self._subscription(Subscription.Status.CANCELED)

        @access_required()
        def view(request):
            return "ok"

        self.assertEqual(view(self._request("get")), "ok")
        with self.assertRaises(PermissionDenied):
            view(self._request("post"))

    def test_missing_subscription_blocks_even_reads(self):
        """Fails closed -- no Subscription row at all is not the same as 'fully active'."""

        @access_required()
        def view(request):
            return "ok"

        with self.assertRaises(PermissionDenied):
            view(self._request("get"))

    def test_billing_exempt_bypasses_the_check_entirely(self):
        self._subscription(Subscription.Status.CANCELED)

        @access_required(billing_exempt=True)
        def view(request):
            return "ok"

        self.assertEqual(view(self._request("post")), "ok")

    def test_billing_exempt_bypasses_even_a_missing_subscription(self):
        @access_required(billing_exempt=True)
        def view(request):
            return "ok"

        self.assertEqual(view(self._request("get")), "ok")

    def test_unauthenticated_still_redirects_to_login_first(self):
        @access_required()
        def view(request):
            return "ok"

        response = view(self._request("get", user=AnonymousUser()))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


# --- owner_required -----------------------------------------------------


class OwnerRequiredTests(BillingTestCase):
    def _request(self, user):
        request = RequestFactory().get("/fake-billing-view/")
        request.user = user
        return request

    def test_owner_passes(self):
        @owner_required
        def view(request):
            return "ok"

        self.assertEqual(view(self._request(self.owner)), "ok")

    def test_non_owner_blocked(self):
        @owner_required
        def view(request):
            return "ok"

        with self.assertRaises(PermissionDenied):
            view(self._request(self.staff_user))

    def test_unauthenticated_redirects_to_login(self):
        @owner_required
        def view(request):
            return "ok"

        response = view(self._request(AnonymousUser()))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


# --- billing_status view (real HTTP) ------------------------------------


class BillingStatusViewTests(BillingTestCase):
    def test_owner_can_view_even_when_canceled(self):
        self._subscription(Subscription.Status.CANCELED)
        client = Client()
        client.force_login(self.owner)
        response = client.get(reverse("billing:billing_status"))
        self.assertEqual(response.status_code, 200)

    def test_non_owner_forbidden(self):
        self._subscription(Subscription.Status.ACTIVE)
        client = Client()
        client.force_login(self.staff_user)
        response = client.get(reverse("billing:billing_status"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirects_to_login(self):
        client = Client()
        response = client.get(reverse("billing:billing_status"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


# --- stripe_client.py -- the only module allowed to touch `stripe` -----


class StripeClientTests(TestCase):
    """
    These are the only tests in the suite that patch the `stripe` SDK
    itself, rather than apps.billing.stripe_client -- by design, since
    this module *is* the boundary. No network call is made: mock.patch
    replaces the SDK method before it would ever be invoked.
    """

    def test_create_setup_intent_calls_stripe(self):
        with mock.patch("stripe.SetupIntent.create") as mock_create:
            mock_create.return_value = "fake-intent"
            result = stripe_client.create_setup_intent()
        mock_create.assert_called_once_with(usage="off_session")
        self.assertEqual(result, "fake-intent")

    def test_create_customer_sets_default_payment_method(self):
        with mock.patch("stripe.Customer.create") as mock_create:
            mock_create.return_value = "fake-customer"
            result = stripe_client.create_customer(
                email="ada@example.com", name="Ada Lovelace", payment_method_id="pm_123"
            )
        mock_create.assert_called_once_with(
            email="ada@example.com",
            name="Ada Lovelace",
            payment_method="pm_123",
            invoice_settings={"default_payment_method": "pm_123"},
        )
        self.assertEqual(result, "fake-customer")

    def test_create_subscription_passes_trial_period(self):
        with mock.patch("stripe.Subscription.create") as mock_create:
            mock_create.return_value = "fake-subscription"
            result = stripe_client.create_subscription(
                customer_id="cus_123", price_id="price_123", trial_period_days=14
            )
        mock_create.assert_called_once_with(
            customer="cus_123", items=[{"price": "price_123"}], trial_period_days=14
        )
        self.assertEqual(result, "fake-subscription")

    def test_cancel_subscription(self):
        with mock.patch("stripe.Subscription.cancel") as mock_cancel:
            mock_cancel.return_value = "fake-canceled"
            result = stripe_client.cancel_subscription("sub_123")
        mock_cancel.assert_called_once_with("sub_123")
        self.assertEqual(result, "fake-canceled")

    def test_construct_webhook_event_delegates_to_stripe_webhook(self):
        with mock.patch("stripe.Webhook.construct_event") as mock_construct:
            mock_construct.return_value = "fake-event"
            result = stripe_client.construct_webhook_event(b"payload", "sig", "whsec_test")
        mock_construct.assert_called_once_with(b"payload", "sig", "whsec_test")
        self.assertEqual(result, "fake-event")


# --- services.py -- signup-flow scaffolding (mocks stripe_client) ------


class FakeStripeObject(dict):
    """Stands in for stripe.StripeObject -- supports both attribute access
    (obj.id) and dict-style .get() (obj.get('x')), exactly like the real
    SDK's objects, without depending on stripe internals or the network."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class SignupFlowServiceTests(BillingTestCase):
    def test_create_setup_intent_delegates_to_stripe_client(self):
        with mock.patch.object(stripe_client, "create_setup_intent", return_value="fake-intent") as mocked:
            result = services.create_setup_intent()
        mocked.assert_called_once_with()
        self.assertEqual(result, "fake-intent")

    def test_create_stripe_customer_and_subscription(self):
        fake_customer = FakeStripeObject(id="cus_abc")
        fake_subscription = FakeStripeObject(id="sub_abc", status="trialing")
        with mock.patch.object(stripe_client, "create_customer", return_value=fake_customer) as mock_cust, \
             mock.patch.object(stripe_client, "create_subscription", return_value=fake_subscription) as mock_sub:
            customer, subscription = services.create_stripe_customer_and_subscription(
                email="ada@example.com",
                name="Ada Lovelace",
                payment_method_id="pm_123",
                price_id="price_123",
                trial_period_days=14,
            )
        mock_cust.assert_called_once_with(email="ada@example.com", name="Ada Lovelace", payment_method_id="pm_123")
        mock_sub.assert_called_once_with(customer_id="cus_abc", price_id="price_123", trial_period_days=14)
        self.assertEqual(customer.id, "cus_abc")
        self.assertEqual(subscription.id, "sub_abc")

    def test_create_subscription_record_writes_local_rows(self):
        trial_end = int(datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc).timestamp())
        period_start = int(datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc).timestamp())
        period_end = int(datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc).timestamp())
        fake_customer = FakeStripeObject(id="cus_abc")
        fake_subscription = FakeStripeObject(
            id="sub_abc",
            status="trialing",
            trial_end=trial_end,
            current_period_start=period_start,
            current_period_end=period_end,
        )

        subscription = services.create_subscription_record(
            congregation=self.congregation, stripe_customer=fake_customer, stripe_subscription=fake_subscription
        )

        subscription.refresh_from_db()
        self.assertEqual(subscription.stripe_customer_id, "cus_abc")
        self.assertEqual(subscription.stripe_subscription_id, "sub_abc")
        self.assertEqual(subscription.status, Subscription.Status.TRIALING)
        self.assertEqual(subscription.trial_ends_at, datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc))

        events = SubscriptionEvent.objects.filter(congregation=self.congregation)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().event_type, "trial_started")
        self.assertEqual(events.first().source, SubscriptionEvent.Source.ADMIN_ACTION)

    def test_cancel_stripe_subscription_for_compensation_delegates(self):
        with mock.patch.object(stripe_client, "cancel_subscription", return_value="canceled") as mocked:
            result = services.cancel_stripe_subscription_for_compensation("sub_abc")
        mocked.assert_called_once_with("sub_abc")
        self.assertEqual(result, "canceled")


# --- services.py -- webhook processing ----------------------------------


def _fake_event(event_id, event_type, object_data, created=1750000000):
    return FakeStripeObject(
        id=event_id,
        type=event_type,
        created=created,
        data=FakeStripeObject(object=FakeStripeObject(object_data)),
    )


class ProcessWebhookEventTests(BillingTestCase):
    def setUp(self):
        super().setUp()
        self.subscription = self._subscription(Subscription.Status.ACTIVE)

    def test_duplicate_event_id_is_a_noop(self):
        SubscriptionEvent.objects.create(
            congregation=self.congregation,
            event_type="status_changed",
            source=SubscriptionEvent.Source.STRIPE_WEBHOOK,
            stripe_event_id="evt_dup",
            occurred_at=datetime.datetime.now(datetime.timezone.utc),
        )
        event = _fake_event(
            "evt_dup", "customer.subscription.updated", {"id": "sub_test", "status": "past_due"}
        )
        result = services.process_webhook_event(event)
        self.assertFalse(result)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)

    def test_unrecognized_event_type_is_a_noop(self):
        event = _fake_event("evt_unknown", "charge.refunded", {"id": "ch_123"})
        result = services.process_webhook_event(event)
        self.assertFalse(result)
        self.assertEqual(SubscriptionEvent.objects.count(), 0)

    def test_subscription_for_unknown_local_row_is_a_noop(self):
        event = _fake_event(
            "evt_1", "customer.subscription.updated", {"id": "sub_does_not_exist", "status": "active"}
        )
        result = services.process_webhook_event(event)
        self.assertFalse(result)
        self.assertEqual(SubscriptionEvent.objects.count(), 0)

    def test_status_mapping_unpaid_to_read_only(self):
        event = _fake_event(
            "evt_2", "customer.subscription.updated", {"id": "sub_test", "status": "unpaid"}
        )
        result = services.process_webhook_event(event)
        self.assertTrue(result)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.READ_ONLY)
        event_row = SubscriptionEvent.objects.get(stripe_event_id="evt_2")
        self.assertEqual(event_row.event_type, "status_changed")
        self.assertEqual(event_row.source, SubscriptionEvent.Source.STRIPE_WEBHOOK)

    def test_status_mapping_incomplete_expired_to_canceled(self):
        event = _fake_event(
            "evt_3", "customer.subscription.updated", {"id": "sub_test", "status": "incomplete_expired"}
        )
        services.process_webhook_event(event)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.CANCELED)

    def test_recovery_from_read_only_logs_reactivated(self):
        self.subscription.status = Subscription.Status.READ_ONLY
        self.subscription.save(update_fields=["status"])
        event = _fake_event(
            "evt_4", "customer.subscription.updated", {"id": "sub_test", "status": "active"}
        )
        services.process_webhook_event(event)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)
        event_row = SubscriptionEvent.objects.get(stripe_event_id="evt_4")
        self.assertEqual(event_row.event_type, "reactivated")

    def test_subscription_deleted_sets_canceled_status_and_timestamp(self):
        event = _fake_event(
            "evt_5", "customer.subscription.deleted", {"id": "sub_test", "status": "canceled"}
        )
        services.process_webhook_event(event)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.CANCELED)
        self.assertIsNotNone(self.subscription.canceled_at)
        event_row = SubscriptionEvent.objects.get(stripe_event_id="evt_5")
        self.assertEqual(event_row.event_type, "canceled")

    def test_invoice_payment_failed_logs_without_changing_status(self):
        event = _fake_event(
            "evt_6", "invoice.payment_failed", {"id": "in_123", "subscription": "sub_test"}
        )
        result = services.process_webhook_event(event)
        self.assertTrue(result)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)
        event_row = SubscriptionEvent.objects.get(stripe_event_id="evt_6")
        self.assertEqual(event_row.event_type, "payment_failed")

    def test_invoice_payment_succeeded_logs_without_changing_status(self):
        event = _fake_event(
            "evt_7", "invoice.payment_succeeded", {"id": "in_124", "subscription": "sub_test"}
        )
        services.process_webhook_event(event)
        event_row = SubscriptionEvent.objects.get(stripe_event_id="evt_7")
        self.assertEqual(event_row.event_type, "payment_succeeded")

    def test_invoice_event_with_no_local_subscription_is_a_noop(self):
        event = _fake_event(
            "evt_8", "invoice.payment_succeeded", {"id": "in_125", "subscription": "sub_does_not_exist"}
        )
        result = services.process_webhook_event(event)
        self.assertFalse(result)
        self.assertEqual(SubscriptionEvent.objects.count(), 0)


# --- webhook view (real HTTP, mocking stripe_client) ---------------------


class StripeWebhookViewTests(BillingTestCase):
    def setUp(self):
        super().setUp()
        self.subscription = self._subscription(Subscription.Status.ACTIVE)

    def test_valid_signature_processes_event(self):
        event = _fake_event(
            "evt_view_1", "customer.subscription.updated", {"id": "sub_test", "status": "past_due"}
        )
        with mock.patch.object(stripe_client, "construct_webhook_event", return_value=event):
            client = Client()
            response = client.post(
                reverse("billing:stripe_webhook"), data=b"{}", content_type="application/json"
            )
        self.assertEqual(response.status_code, 200)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.PAST_DUE)

    def test_invalid_signature_returns_400(self):
        with mock.patch.object(
            stripe_client,
            "construct_webhook_event",
            side_effect=stripe.error.SignatureVerificationError("bad sig", "sig_header"),
        ):
            client = Client()
            response = client.post(
                reverse("billing:stripe_webhook"), data=b"{}", content_type="application/json"
            )
        self.assertEqual(response.status_code, 400)

    def test_malformed_payload_returns_400(self):
        with mock.patch.object(stripe_client, "construct_webhook_event", side_effect=ValueError("bad json")):
            client = Client()
            response = client.post(
                reverse("billing:stripe_webhook"), data=b"{}", content_type="application/json"
            )
        self.assertEqual(response.status_code, 400)

    def test_get_not_allowed(self):
        client = Client()
        response = client.get(reverse("billing:stripe_webhook"))
        self.assertEqual(response.status_code, 405)

    def test_endpoint_is_csrf_exempt(self):
        event = _fake_event(
            "evt_view_2", "customer.subscription.updated", {"id": "sub_test", "status": "active"}
        )
        with mock.patch.object(stripe_client, "construct_webhook_event", return_value=event):
            client = Client(enforce_csrf_checks=True)
            response = client.post(
                reverse("billing:stripe_webhook"), data=b"{}", content_type="application/json"
            )
        self.assertEqual(response.status_code, 200)
