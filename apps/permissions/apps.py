from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _sync_permissions_on_migrate(sender, **kwargs):
    from .services import sync_permissions

    sync_permissions()


class PermissionsConfig(AppConfig):
    name = "apps.permissions"

    def ready(self):
        # sender=self scopes this to permissions' own post_migrate dispatch,
        # same pattern module_system uses for sync_modules() -- runs on
        # every `manage.py migrate`, even a no-op one, so editing
        # registry.py and re-running migrate is enough to push a catalog
        # change in.
        post_migrate.connect(_sync_permissions_on_migrate, sender=self)
