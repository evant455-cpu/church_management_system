from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Placeholder custom user model.

    This exists now purely so AUTH_USER_MODEL points at our own app from the
    very first migration -- swapping it later (after migrations exist) is a
    well-known Django pain point we're deliberately avoiding.

    Field design (email-as-login instead of username, congregation_id FK,
    person_id FK per the people_households_users_schema doc, dropping
    PermissionsMixin in favor of the app's own roles/permissions system) is
    intentionally deferred to the Auth & Accounts phase. Extending
    AbstractUser for now keeps this fully functional out of the box without
    committing to final fields before that design conversation happens.
    """
    pass

