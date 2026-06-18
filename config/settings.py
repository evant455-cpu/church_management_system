"""
Django settings for church_management_system.

Single settings.py + django-environ, reading config from environment
variables / a .env file. See docs/.env.example for everything this expects.
This is the deliberate choice over a split settings/{base,dev,prod}.py
package: it matches how this project will actually deploy (env vars
injected by the host), and gives one source of truth for what config exists
instead of three files to keep in sync.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
# .env is for local development only -- never committed (see .gitignore).
# In real deployments, these are real environment variables set by the host.
environ.Env.read_env(BASE_DIR / ".env")


# --- Core ---------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])


# --- Applications ---------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

# Domain-driven local apps. Order matters only in that accounts/people/
# tenancy have no forward dependencies on the others below them.
LOCAL_APPS = [
    "apps.tenancy",
    "apps.billing",
    "apps.module_system",
    "apps.permissions",
    "apps.accounts",
    "apps.people",
    "apps.staff",
    "apps.attendance",
    "apps.scheduling",
    "apps.services",
    "apps.announcements",
    "apps.finances",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database ---------------------------------------------------------

# DATABASE_URL drives this entirely -- see .env.example. Local dev points
# at the docker-compose Postgres; nothing here is environment-specific.
DATABASES = {
    "default": env.db("DATABASE_URL"),
}


# --- Password validation ---------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization ---------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # congregations have their own timezone field; this is the system default
USE_I18N = True
USE_TZ = True


# --- Static files ---------------------------------------------------------

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
