from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.tenancy.models import Congregation


class CongregationModelTests(TestCase):
    def test_owner_user_starts_null_breaking_the_circular_dependency(self):
        """
        A Congregation can be created before any User exists -- this is
        the whole point of owner_user being nullable (see
        onboarding_sequence_schema.md's circular-dependency resolution).
        """
        congregation = Congregation.objects.create(name="Grace Chapel", timezone="America/Chicago")
        self.assertIsNone(congregation.owner_user_id)

    def test_invalid_timezone_rejected(self):
        congregation = Congregation(name="Bad TZ Chapel", timezone="Not/AZone")
        with self.assertRaises(ValidationError):
            congregation.full_clean()

    def test_valid_timezone_accepted(self):
        congregation = Congregation(name="Good TZ Chapel", timezone="America/Chicago")
        congregation.full_clean()  # should not raise

    def test_str_is_name(self):
        congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        self.assertEqual(str(congregation), "Grace Chapel")
