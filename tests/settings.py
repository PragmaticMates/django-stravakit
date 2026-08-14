import os

# Stub Strava env vars so strava.api can import without real credentials
os.environ.setdefault("STRAVA_CLIENT_ID", "0")
os.environ.setdefault("STRAVA_CLIENT_SECRET", "fake-secret")
os.environ.setdefault("STRAVA_ACCESS_TOKEN", "fake-token")
os.environ.setdefault("STRAVA_REFRESH_TOKEN", "fake-refresh")

SECRET_KEY = "test-secret-key"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    # unfold (and its filter contrib) must precede django.contrib.admin — stravakit.admin is
    # built entirely on unfold's decorators, so the admin tests need both installed.
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.humanize",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django_htmx",
    "stravakit",
]

MIDDLEWARE = [
    "django_htmx.middleware.HtmxMiddleware",
]

# django.contrib.admin's system checks require these to be configured.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ROOT_URLCONF = "tests.urls"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
