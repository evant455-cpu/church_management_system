from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from apps.tenancy.models import TenantScopedModel


class UserManager(BaseUserManager):
    """
    Email-as-username manager.

    create_superuser intentionally does NOT support the interactive
    `manage.py createsuperuser` flow out of the box: `congregation` and
    `person` are required FKs (per people_households_users_schema.md --
    "every login belongs to a real person", "one congregation per user"),
    and there's no sensible interactive prompt for "which congregation."
    Until Phase 5's signup wizard exists, the documented dev workflow is
    the shell: create a Congregation, then a Person, then a User
    referencing both -- mirroring the same order onboarding's signup
    service will eventually automate. Call
    `User.objects.create_superuser(email=..., password=..., congregation=c, person=p)`
    directly rather than via the management command.
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        if "congregation" not in extra_fields or extra_fields["congregation"] is None:
            raise ValueError("Users must belong to a congregation.")
        if "person" not in extra_fields or extra_fields["person"] is None:
            raise ValueError("Every login must correspond to a real person.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TenantScopedModel):
    """
    Real user model, replacing the Phase 0 AbstractUser placeholder.

    Design decisions made explicitly (see chat for the full discussion):

    - email-as-login, no username field at all.
    - `congregation` (from TenantScopedModel) and `person` are both
      required per the schema doc -- "every user belongs to exactly one
      congregation and must correspond to a real person."
    - PermissionsMixin is kept in full (is_superuser + groups +
      user_permissions), even though Phase 3 brings a completely separate,
      tenant-scoped RBAC system that doesn't touch Django's contenttypes
      Permission model at all. The two systems operate at different
      layers: PermissionsMixin/is_superuser is the platform-operator
      escape hatch for Django Admin (creating test data now, support/ops
      later); Phase 3's roles/permissions/overrides tables govern what a
      logged-in congregation user can do *inside the app*. Ordinary
      congregation users should never have is_staff/is_superuser set --
      this is reserved for the platform operator, not exposed via any
      congregation-facing flow.
    - `is_staff` is added even though it isn't in the schema doc, purely
      because Django Admin's access check requires it. Also
      operator-only.
    """

    person = models.ForeignKey(
        "people.Person",
        on_delete=models.RESTRICT,
        related_name="user_account",
        help_text="Every login belongs to a real person -- no identity fields are duplicated on User.",
    )
    email = models.EmailField(unique=True, help_text="Used for login.")
    is_active = models.BooleanField(
        default=True,
        help_text="Deactivate a login without touching the person record or any historical data.",
    )
    is_staff = models.BooleanField(
        default=False,
        help_text=(
            "Grants access to the Django Admin site. Not part of the app's own "
            "per-congregation RBAC (Phase 3) -- reserved for platform-operator "
            "use, never set for ordinary congregation users."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email
