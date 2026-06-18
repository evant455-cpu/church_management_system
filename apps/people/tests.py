from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.people.models import Household, MembershipStatus, Person, PersonHousehold
from apps.tenancy.models import Congregation


class PeopleTestCase(TestCase):
    def setUp(self):
        self.congregation = Congregation.objects.create(name="Grace Chapel", timezone="UTC")
        self.other_congregation = Congregation.objects.create(name="Other Chapel", timezone="UTC")


class PersonModelTests(PeopleTestCase):
    def test_defaults(self):
        person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )
        self.assertEqual(person.membership_status, MembershipStatus.VISITOR)
        self.assertFalse(person.is_archived)
        self.assertIsNone(person.archived_at)

    def test_str(self):
        person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )
        self.assertEqual(str(person), "Ada Lovelace")

    def test_congregation_protect_blocks_deletion(self):
        Person.objects.create(congregation=self.congregation, first_name="Ada", last_name="Lovelace")
        with self.assertRaises(ProtectedError):
            self.congregation.delete()


class HouseholdModelTests(PeopleTestCase):
    def test_primary_contact_set_null_on_person_delete(self):
        person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )
        household = Household.objects.create(
            congregation=self.congregation, name="The Lovelace Family", primary_contact_person=person
        )
        person.delete()
        household.refresh_from_db()
        self.assertIsNone(household.primary_contact_person_id)

    def test_household_survives_without_timestamps_oversight_resolved(self):
        """Confirms created_at/updated_at exist on Household (doc oversight, resolved as: add them)."""
        household = Household.objects.create(congregation=self.congregation, name="The Lovelace Family")
        self.assertIsNotNone(household.created_at)
        self.assertIsNotNone(household.updated_at)


class PersonHouseholdModelTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.person = Person.objects.create(
            congregation=self.congregation, first_name="Ada", last_name="Lovelace"
        )
        self.household = Household.objects.create(congregation=self.congregation, name="The Lovelace Family")

    def test_person_can_belong_to_multiple_households(self):
        second_household = Household.objects.create(congregation=self.congregation, name="The Other Family")
        PersonHousehold.objects.create(person=self.person, household=self.household, congregation=self.congregation)
        PersonHousehold.objects.create(
            person=self.person, household=second_household, congregation=self.congregation
        )
        self.assertEqual(self.person.household_links.count(), 2)

    def test_duplicate_person_household_pair_rejected(self):
        PersonHousehold.objects.create(person=self.person, household=self.household, congregation=self.congregation)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PersonHousehold.objects.create(
                    person=self.person, household=self.household, congregation=self.congregation
                )

    def test_only_one_primary_household_per_person(self):
        second_household = Household.objects.create(congregation=self.congregation, name="The Other Family")
        PersonHousehold.objects.create(
            person=self.person, household=self.household, congregation=self.congregation, is_primary=True
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PersonHousehold.objects.create(
                    person=self.person,
                    household=second_household,
                    congregation=self.congregation,
                    is_primary=True,
                )

    def test_non_primary_links_for_same_person_are_unrestricted(self):
        second_household = Household.objects.create(congregation=self.congregation, name="The Other Family")
        PersonHousehold.objects.create(
            person=self.person, household=self.household, congregation=self.congregation, is_primary=False
        )
        # Should not raise -- the partial unique index only applies where is_primary=True.
        PersonHousehold.objects.create(
            person=self.person, household=second_household, congregation=self.congregation, is_primary=False
        )

    def test_cascade_delete_on_person_removal(self):
        link = PersonHousehold.objects.create(
            person=self.person, household=self.household, congregation=self.congregation
        )
        self.person.delete()
        self.assertFalse(PersonHousehold.objects.filter(pk=link.pk).exists())

    def test_cascade_delete_on_household_removal(self):
        link = PersonHousehold.objects.create(
            person=self.person, household=self.household, congregation=self.congregation
        )
        self.household.delete()
        self.assertFalse(PersonHousehold.objects.filter(pk=link.pk).exists())
