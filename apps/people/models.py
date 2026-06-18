from django.db import models

from apps.tenancy.models import TenantScopedModel


class MembershipStatus(models.TextChoices):
    MEMBER = "member", "Member"
    VISITOR = "visitor", "Visitor"
    REGULAR_ATTENDER = "regular_attender", "Regular Attender"
    INACTIVE = "inactive", "Inactive"


class Person(TenantScopedModel):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(
        blank=True,
        null=True,
        help_text="A person's contact email -- distinct from users.email, which only exists if they also log in.",
    )
    phone = models.CharField(max_length=30, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    membership_status = models.CharField(
        max_length=30,
        choices=MembershipStatus.choices,
        default=MembershipStatus.VISITOR,
    )
    join_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_archived = models.BooleanField(
        default=False,
        help_text="Soft lifecycle flag. See deletion policy: a person is only hard-deletable once nothing references them.",
    )
    archived_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "people"
        verbose_name_plural = "people"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Household(TenantScopedModel):
    name = models.CharField(max_length=150, help_text='e.g. "The Smith Family"')
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    primary_contact_person = models.ForeignKey(
        Person,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_contact_for_households",
        help_text="Who mail/communications address by default.",
    )
    # Not in people_households_users_schema.md's households table -- every
    # other table in every schema doc has these, so treating the omission
    # as a doc oversight per discussion rather than intentional.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "households"

    def __str__(self):
        return self.name


class PersonHousehold(TenantScopedModel):
    """
    Join table -- a person can belong to more than one household (blended
    families, custody arrangements), so this is deliberately many-to-many
    rather than a single FK on Person.
    """

    class HouseholdRole(models.TextChoices):
        HEAD = "head", "Head"
        SPOUSE = "spouse", "Spouse"
        CHILD = "child", "Child"
        OTHER = "other", "Other"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="household_links")
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="person_links")
    household_role = models.CharField(
        max_length=30,
        choices=HouseholdRole.choices,
        blank=True,
        null=True,
        help_text="Per-relationship, since the same person can hold a different role in each household.",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Which household is the 'main' one for this person.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "person_households"
        constraints = [
            models.UniqueConstraint(
                fields=["person", "household"],
                name="uniq_person_household",
            ),
            models.UniqueConstraint(
                fields=["person"],
                condition=models.Q(is_primary=True),
                name="uniq_primary_household_per_person",
            ),
        ]

    def __str__(self):
        return f"{self.person} @ {self.household}"
