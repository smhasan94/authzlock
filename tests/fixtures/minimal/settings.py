"""Settings for the minimal fixture project, used to prove process isolation."""

SECRET_KEY = "fixture-not-secret"
USE_TZ = True
ROOT_URLCONF = "urls"
INSTALLED_APPS = ["home"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
