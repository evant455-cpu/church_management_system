from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    """
    The signup wizard + the atomic "Finish" transaction (Phase 5).

    Deliberately has no models.py -- wizard state across steps lives in
    the Django session, not a new database table (see chat for the
    comparison against a dedicated SignupSession model and signed hidden
    fields). Nothing in this app writes to the database until
    services.complete_signup() runs at "Finish".
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.onboarding"
