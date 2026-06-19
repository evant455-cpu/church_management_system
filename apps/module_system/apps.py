from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _sync_modules_on_migrate(sender, **kwargs):
    from .services import sync_modules

    sync_modules()


class ModuleSystemConfig(AppConfig):
    name = "apps.module_system"

    def ready(self):
        # sender=self scopes this to module_system's own post_migrate
        # dispatch (the same pattern django.contrib.auth uses to create
        # default Permission rows after every migrate) -- runs on every
        # `manage.py migrate`, even a no-op one, so editing registry.py
        # and re-running migrate is enough to push a registry change in.
        post_migrate.connect(_sync_modules_on_migrate, sender=self)
