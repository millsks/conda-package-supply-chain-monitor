# ruff: noqa: ERA001
"""Base settings to build other settings files upon."""

import os
import ssl
from pathlib import Path
from typing import Any

import environ
from django.urls import reverse_lazy

from conda_package_supply_chain_monitor.collectors.watchlist import watchlist_path
from conda_package_supply_chain_monitor.core import queues
from conda_package_supply_chain_monitor.core.roles import load_role_contract
from config.authorization.claims import load_claims_contract
from config.locality import is_local
from config.observability.logging import build_logging_config
from config.observability.logging import configure_structlog

# Repository root (holds manage.py, pyproject.toml, .env).
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent.parent
# The django_service package: holds the apps, templates, static and media.
# src/ itself is the import root and is deliberately not a package.
APPS_DIR = BASE_DIR / "src" / "django_service"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "UTC"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#languages
# from django.utils.translation import gettext_lazy as _
# LANGUAGES = [
#     ('en', _('English')),
#     ('fr-fr', _('French')),
#     ('pt-br', _('Portuguese')),
# ]
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
# Kept, and the `sites` app with it. allauth resolves a provider app through
# `SocialApp.objects.on_site(request)` on every lookup, so the table has to
# exist even though AD-31 forbids a row ever being the provider's source.
SITE_ID = 1
# The `Site` domain, environment-driven (AD-31). The data migration that used to
# write it into the database is retired -- see
# django_service/contrib/sites/migrations/0003_set_site_domain_and_name.py --
# because a baked-in domain travels into every deployed component and decides
# what callback URL it advertises. Nothing writes these values to the `Site`
# row: NFR-1 keeps startup free of queries beyond migration state and AD-22
# forbids a boot-time write, so these settings are the source of truth and the
# table exists only for allauth's `on_site` lookup.
SITE_DOMAIN = env.str("COMPONENT_SITE_DOMAIN", default="localhost")
SITE_NAME = env.str("COMPONENT_SITE_NAME", default="localhost")
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases


def _sqlite_alias(base_dir: Path, alias: str = "default") -> dict[str, Any]:
    """Build the sqlite configuration that stands in for one database alias.

    The `default` alias keeps the historical `db.sqlite3` filename so an existing
    checkout's database is still the one that gets opened; every other alias gets
    its own file, because two aliases sharing one file is not a second database.

    Args:
        base_dir: The repository root, which is where the file is written.
        alias: The database alias the configuration is being built for.

    Returns:
        A Django database configuration dict for the sqlite backend.

    """
    name = base_dir / "db.sqlite3" if alias == "default" else base_dir / f"db.{alias}.sqlite3"
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(name)}


def apply_local_database_substitution(databases: dict[str, Any], base_dir: Path) -> None:
    """Fill every unconfigured database alias with the local sqlite substitution.

    This is FR-18's database substitution, and AD-9 requires the *base* to apply
    it automatically rather than each settings module doing so for itself: a
    contributed database (Epic 9) adds an alias to `DATABASES`, and that alias
    must be substituted by this same code path instead of inventing a second
    mechanism. An alias whose configuration is already populated is left exactly
    as it is -- the substitution must never shadow a real database.

    It is called unconditionally from this module, not gated on locality and not
    moved into `local.py`, because FR-12 makes the refusal contract evaluate
    independently of which settings module loaded. What keeps that safe is the
    refusal, not a condition here: `config/settings/production.py` raises rather
    than serving a deployment off sqlite. Do not "fix" this into a local-only
    call -- doing so is what would let a production module with an unconfigured
    alias reach a caller with no database at all.

    Args:
        databases: The `DATABASES` mapping, mutated in place.
        base_dir: The repository root, passed to `_sqlite_alias`.

    """
    for alias in list(databases):
        if not databases[alias]:
            databases[alias] = _sqlite_alias(base_dir, alias)


if os.getenv("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
elif os.getenv("POSTGRES_DB", default=None):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env.str("POSTGRES_DB"),
            "USER": env.str("POSTGRES_USER"),
            "PASSWORD": env.str("POSTGRES_PASSWORD"),
            "HOST": env.str("POSTGRES_HOST", default="postgres"),
            "PORT": env.str("POSTGRES_PORT", default="5432"),
        },
    }
else:
    # Local-development fallback until Postgres is provisioned. Production
    # refuses to boot on sqlite -- see config/settings/production.py.
    DATABASES = {"default": _sqlite_alias(BASE_DIR)}

# After the selection, never instead of it: the three branches above own which
# backend `default` gets, and this only fills in aliases that ended up with no
# configuration at all. Today that is a no-op; it is the declared hook AD-9's
# contributed database extends, so that FR-18 stays true by construction rather
# than by a second epic remembering to add its own fallback.
apply_local_database_substitution(DATABASES, BASE_DIR)

DATABASES["default"]["ATOMIC_REQUESTS"] = True
# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "django.contrib.humanize", # Handy template tags
    "django.contrib.admin",
    "django.forms",
]
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    # The OIDC provider that ships with the installed django-allauth
    # distribution (AD-31, FR-4). No second OIDC framework is added, and this
    # entry is never guarded behind an availability check -- AD-24 permits no
    # conditional import, no settings-module inheritance and no
    # `try`/`except ImportError` as a removal mechanism.
    "allauth.socialaccount.providers.openid_connect",
    "django_celery_beat",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "django_structlog",
]

LOCAL_APPS = [
    "django_service.users",
    # Domain applications live under the second import root, src/django_apps/,
    # as subpackages of one distribution package. Appended, never prepended:
    # `django_service.users` is the stage-2 owner (AD-26) and must stay first --
    # tests/unit/startup/test_installed_apps_ordering.py asserts it.
    #
    # `component.toml`'s `adopted_apps` is the AD-8 declaration of the same
    # adoption, but nothing consumes it into INSTALLED_APPS yet (that
    # composition step is Epic 9), so the entry here is what actually installs
    # the application today.
    "conda_package_supply_chain_monitor.core",
    "conda_package_supply_chain_monitor.identity",
    # The collectors application, and the first adopted application declaring a
    # `ready()` (CPM-IDENTITY-S06). It adopts its collectors into `core`'s
    # registry, which is what CPM-AD-28's stage-2 sweep walks -- so it has to
    # stay after the stage-2 owner exactly as the two above do, which appending
    # is what guarantees.
    "conda_package_supply_chain_monitor.collectors",
    # Your stuff: custom apps go here
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {"sites": "django_service.contrib.sites.migrations"}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
# Allauth's backend alone, because the base is the surface a *deployed* component
# inherits: authentication is the identity provider's (FR-4), and stage 1 refuses
# `django.contrib.auth.backends.ModelBackend` here in a deployed component
# (condition 2, state a). It carried `ModelBackend` until this story, which meant
# no deployed component could import this module at all -- `production.py` adds no
# override, so the refusal fired on every real deployment.
#
# `local.py` and `test.py` add it back, which is where the affordance it exists
# for belongs: persona sign-in hands `django.contrib.auth.login` the backend path
# in `config.local_dev.views.SESSION_BACKEND`, and `get_user` answers
# `AnonymousUser` on the next request for a backend this list does not name. A
# locality-scoped credential path is declared where the locality is, exactly as
# the cache and task substitutions are.
#
# Allauth's `AuthenticationBackend` **is** a `ModelBackend` subclass, which is why
# condition 2a compares dotted paths rather than resolving and testing
# `issubclass` -- see `config/startup/stage_one.py`.
AUTHENTICATION_BACKENDS = [
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "users:redirect"
# The id the OIDC app is registered under, read here rather than beside
# `SOCIALACCOUNT_PROVIDERS` below because `LOGIN_URL` is built from it. One
# variable, one meaning: the provider block reads this same name.
OIDC_PROVIDER_ID = env.str("COMPONENT_OIDC_PROVIDER_ID", default="oidc")
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
# FR-4 / AC #1: an unauthenticated request to an authenticated page redirects to
# the IdP, never to allauth's local credential form. `reverse_lazy` rather than
# `reverse` because a module-level reverse in a settings file runs before the
# URLconf is loaded. The local account routes are deliberately still installed
# -- deleting them is Story 2.8's, and refusing them at startup is Epic 4's.
LOGIN_URL = reverse_lazy("openid_connect_login", kwargs={"provider_id": OIDC_PROVIDER_ID})
# The claims contract (FR-10, AD-11, AD-12): the identity-key claim, the group
# claim, and the staff- and superuser-conferring groups, each read from a
# COMPONENT_-prefixed variable with no default. Unset stays unset -- an empty
# field means unconfigured, which is what Epic 4's startup check refuses on.
# See config/authorization/claims.py and docs/authentication.md.
CLAIMS_CONTRACT = load_claims_contract(env)
# The product's role contract (CPM-FR-30): the names of the three groups that
# confer the security-and-compliance-reviewer, packaging-engineer and leadership
# roles, each read from a CPM_-prefixed variable with no default. Unset stays
# unset, exactly as above.
#
# Read *here* rather than inside the application it belongs to, for the reason
# FR-38 gives: `.env` is read once, by this module, and `env` is the only handle
# on it. An app reading its own configuration would be a second read of a file
# this module has already consumed and a second place a deployment's
# configuration lives. The application owns the contract's *shape* --
# `conda_package_supply_chain_monitor.core.roles` declares the slots, the
# variable names and the loader -- and the settings module owns the read, which
# is the same division `config/authorization/claims.py` is on the other side of.
#
# The import is legal in the direction it runs: `config` may import a domain
# application, and `roles.py` imports nothing from `django.apps` or
# `django.contrib.auth`, so it loads before the app registry exists.
# See src/django_apps/conda_package_supply_chain_monitor/core/roles.py and
# docs/authentication.md.
ROLE_CONTRACT = load_role_contract(env)
# The inventory source's file (CPM-AD-29, CPM-FR-42): the versioned watchlist the
# declared adapter reads, selected by locality.
#
# The read is *here* for the same reason ROLE_CONTRACT's is, and the split is the
# same one. CPM-AD-29 names config.locality.is_local() as the selector and AD-4
# forbids a domain application importing config, so the application owns the
# contract and a pure function -- watchlist_path(local=...) reads no environment
# variable and touches no filesystem -- and this module performs the read.
#
# Selection fails closed toward production, which is is_local()'s own default:
# only COMPONENT_RUNTIME=local selects the development subset, and absent, empty
# and unrecognized all read the production watchlist. That direction is
# load-bearing. A deployed component reading the development subset would find
# every package outside it missing and record each one as absent -- permanently,
# in an append-only log nothing may correct.
#
# Read at settings-import time, so it freezes for the process. That is what a
# declared adapter is: CollectorsConfig.ready() binds one file at boot, and a
# component that has to read a different one restarts.
# See src/django_apps/conda_package_supply_chain_monitor/collectors/watchlist.py.
INVENTORY_WATCHLIST_PATH = watchlist_path(local=is_local())

# PASSWORDS
# ------------------------------------------------------------------------------
# PASSWORD_HASHERS is deliberately unset. Authentication is delegated to an
# OpenID Connect provider, so a component never issues or verifies a local
# password and has no reason to prefer one hasher over another -- Django's
# defaults stand. Dropping the Argon2 entry is what lets argon2-cffi leave the
# dependency set.
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # After AuthenticationMiddleware so request.user is resolved and can be
    # bound onto the log context as user_id.
    "django_structlog.middlewares.RequestMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(BASE_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "django_service.users.context_processors.allauth_settings",
            ],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-engine
#
# FR-44 / AD-31: sessions are database-backed, and the engine is stated here
# rather than inherited. Django's own global default happens to be this same
# string, so the line changes no behaviour today -- which is precisely why it is
# worth writing. What it removes is the *dependence on a default*: a value the
# component never states is a value a Django release note can move, and one that
# a feature's settings fragment can quietly redefine.
#
# The Redis feature may not change it. Two of the six combinations ship no Redis
# at all, so a cache-backed engine would make session behaviour a property of an
# unrelated toggle -- per-replica sessions in those two LocMem combinations, where
# a user's session then depends on which replica answered. That is the NFR-3
# statelessness failure this setting exists to prevent, and it is why this
# assignment sits **outside every `feature:<name>` region**: an assignment inside
# a region is an assignment the materializer removes from every component that
# did not select that region's feature, whichever feature that turns out to be.
#
# No `cached_db` variant "for performance", and no `SESSION_CACHE_ALIAS`: both
# reintroduce the toggle dependency the explicit engine removes.
# `tests/unit/test_session_settings.py` holds all of it, including the
# outside-every-region half.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
#
# A list of `(name, address)` pairs, and the shape is load-bearing rather than
# stylistic: `django.core.mail.mail_admins` refuses anything else outright --
# `raise ValueError("The ADMINS setting must be a list of 2-tuples.")` -- and it
# is called from `AdminEmailHandler.emit`, which `production.py` wires onto the
# `django.request` logger. The single-string form this carried until Story 5.3
# therefore turned the *first* 5xx the component ever emitted into an unhandled
# exception raised from inside `logging`, replacing the response with a
# traceback. Nothing caught it before because nothing returned a 5xx
# deliberately; readiness returns 503 by design (AD-22), so it does now, and
# `tests/integration/test_health.py` exercises that path through the real stack.
ADMINS = [("Kevin Samuel Mills", "millsks@gmail.com")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS
# https://cookiecutter-django.readthedocs.io/en/latest/settings.html#other-environment-settings
# Force the `admin` sign in process to go through the `django-allauth` workflow.
# FR-7: this defaults *true*. It arrived from cookiecutter-django defaulting
# false, which left `/admin/` serving Django's own credential form through
# `ModelBackend` with the IdP never involved. The mechanism is unchanged --
# `django_service/users/admin.py` already wraps `admin.site.login` in allauth's
# `secure_admin_login`, which redirects at `LOGIN_URL`; only the default was
# wrong.
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=True)

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# Everything -- ours, Django's, allauth's, Celery's -- renders through structlog.
# See config/observability/logging.py.
DJANGO_LOG_LEVEL = env.str("DJANGO_LOG_LEVEL", default="INFO")
DJANGO_LOG_FORMAT = env.str("DJANGO_LOG_FORMAT", default="")

LOGGING = build_logging_config(
    debug=DEBUG,
    log_level=DJANGO_LOG_LEVEL,
    log_format=DJANGO_LOG_FORMAT,
)

configure_structlog()

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
REDIS_SSL = REDIS_URL.startswith("rediss://")

# Celery
# ------------------------------------------------------------------------------
# django-structlog binds request_id and user_id for the life of a request and
# carries request_id into the Celery tasks a request enqueues.
DJANGO_STRUCTLOG_CELERY_ENABLED = True
if USE_TZ:
    # https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-timezone
    CELERY_TIMEZONE = TIME_ZONE
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE} if REDIS_SSL else None
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_backend
CELERY_RESULT_BACKEND = REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_REDIS_BACKEND_USE_SSL = CELERY_BROKER_USE_SSL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-extended
CELERY_RESULT_EXTENDED = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-always-retry
# https://github.com/celery/celery/pull/6122
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-max-retries
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ["json"]
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_TIME_LIMIT = 5 * 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-soft-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_SOFT_TIME_LIMIT = 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-routes
# CPM-AD-20's three workload queues, routed by task-name namespace. The table is
# `conda_package_supply_chain_monitor.core.queues`' -- the three queue names are
# declared there once and every reader resolves them from it, because a second
# literal spelling of "collect" is exactly what this repository's audits exist to
# catch.
#
# `CELERY_TASK_ROUTES` is one of the keys `config/startup/allowlist.py`'s
# `CONTRIBUTABLE_KEYS` permits a domain application to contribute to. The
# composition step that would apply such a contribution is the platform's Epic 9
# and is not built -- `config/component/loader.py` parses `component.toml` and
# stops there -- so the contribution is written here by hand, on exactly the
# terms the `LOCAL_APPS` entry above records for the same app's adoption. When
# Epic 9 lands, this line is what it replaces.
#
# No catch-all pattern and no `CELERY_TASK_DEFAULT_QUEUE`: a task declaring no
# `cpm.` name keeps landing on the inherited default queue, which is where the
# platform's own `get_users_count` and the correlation probe in
# `tests/integration/test_celery_log_correlation.py` both belong.
CELERY_TASK_ROUTES = queues.CELERY_TASK_ROUTES
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-scheduler
# Cadence is data in this scheduler's tables and never a decorator on a task
# (CPM-AD-20, CPM-NFR-2): a hard-coded schedule cannot be changed without a
# deploy. `tests/unit/django_apps/test_task_declaration_audit.py` is the gate.
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-send-task-events
CELERY_WORKER_SEND_TASK_EVENTS = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-task_send_sent_event
CELERY_TASK_SEND_SENT_EVENT = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-hijack-root-logger
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://docs.allauth.org/en/latest/account/configuration.html
# Empty in the base for the reason `AUTHENTICATION_BACKENDS` above is empty of
# `ModelBackend`: any declared login method keeps allauth's local sign-in form
# reachable, which is stage 1's condition 2, state b. Declared -- rather than left
# out -- because absence is not neutral here: allauth defaults this to a method,
# so a deleted line reinstates the forbidden state, and `stage_one.py` refuses an
# undeclared `ACCOUNT_LOGIN_METHODS` for exactly that reason. `local.py` and
# `test.py` declare the developer-facing form where the locality that justifies it
# is.
ACCOUNT_LOGIN_METHODS: set[str] = set()
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_ADAPTER = "django_service.users.adapters.AccountAdapter"
# https://docs.allauth.org/en/latest/account/forms.html
ACCOUNT_FORMS = {"signup": "django_service.users.forms.UserSignupForm"}
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
# The adapter lives in `config.authorization` beside the mapper it calls. AD-4
# permits `config` to import `django_service` and forbids the reverse, so an
# adapter that has to reach the mapper cannot stay in `django_service`.
SOCIALACCOUNT_ADAPTER = "config.authorization.adapters.OIDCSocialAccountAdapter"
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_FORMS = {"signup": "django_service.users.forms.UserSocialSignupForm"}
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
# Already allauth's default, and stated anyway: with it on, a provider asserting
# a verified address that matches a local row signs that row's owner in. AD-11
# makes `idp_subject` the sole identity key and forbids email standing in for
# it, so this being explicit is what stops a later edit turning email into a
# resolution key without anyone noticing the rule it broke.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
# The OIDC provider, configured from the environment (AD-31, AC #4). Never from
# database-resident `SocialApp` rows: a component forbidden to migrate itself
# could not create one, and configuring the same provider in both places makes
# allauth's `get_app` raise `MultipleObjectsReturned` at login. So nothing in
# this repository creates such a row, and no fixture or instruction asks anyone
# to.
#
# `server_url` is required -- allauth reads `app.settings["server_url"]` with a
# bare subscript, so a missing one is a `KeyError` rather than a graceful
# degradation. Every value is read with `default=""` all the same: an
# unconfigured IdP is refused at startup by Epic 4's stage 1, not by a settings
# module that cannot be imported to be inspected.
#
# `COMPONENT_OIDC_ISSUER` is the single trust anchor (AD-23). Story 2.7 derives
# the JWKS location from this same variable -- there is no second issuer
# setting, and adding one would give the component two answers to "who signs
# these tokens".
#
# Discovery is a *request*-time fetch inside allauth (`openid_config`), which is
# what keeps NFR-1's "startup makes no network call" true with this block
# present. Nothing here, in an `AppConfig.ready()` or in a system check may
# fetch the discovery document.
#
# `OIDC_ISSUER` and `OIDC_CLIENT_ID` are read into names of their own rather than
# inline in the block below, because the Bearer path (Story 2.7) needs both and
# reading `COMPONENT_OIDC_ISSUER` a second time is how a component acquires two
# answers to "who signs these tokens". One read, one name, two consumers.
OIDC_ISSUER = env.str("COMPONENT_OIDC_ISSUER", default="")
OIDC_CLIENT_ID = env.str("COMPONENT_OIDC_CLIENT_ID", default="")
SOCIALACCOUNT_PROVIDERS = {
    "openid_connect": {
        "APPS": [
            {
                "provider_id": OIDC_PROVIDER_ID,
                "name": env.str("COMPONENT_OIDC_PROVIDER_NAME", default=""),
                "client_id": OIDC_CLIENT_ID,
                "secret": env.str("COMPONENT_OIDC_CLIENT_SECRET", default=""),
                "settings": {
                    "server_url": OIDC_ISSUER,
                    # FR-4 specifies Authorization Code with PKCE. allauth reads
                    # exactly this key (`oauth2.provider.get_pkce_params`) and
                    # falls back to the provider default, which is False --
                    # without the key there is no PKCE.
                    "oauth_pkce_enabled": True,
                },
            },
        ],
    },
}

# The Bearer credential (FR-5, AD-23). Every value below is read here so that
# config/authorization/jwks.py and config/authorization/authentication.py take
# their configuration from Django settings rather than from the environment
# directly -- one `.env` read (FR-38), and a `settings` fixture can move any of
# them inside a test.
#
# `COMPONENT_OIDC_JWKS_URL` is an override, not a second trust anchor: unset, the
# location is derived from `OIDC_ISSUER` above. AD-23's startup refusal for a
# location not derived from the issuer is Epic 4's, and it consumes
# `config.authorization.jwks.jwks_url_derives_from_issuer`. That check is
# syntactic and can be nothing else -- confirming a location against the issuer's
# discovery document would mean fetching it at boot, which FR-23 forbids.
OIDC_JWKS_URL = env.str("COMPONENT_OIDC_JWKS_URL", default="")
# The audience every Bearer token must be minted for. Defaults to the OIDC client
# id, which is what an IdP issuing tokens for this component's own client puts in
# `aud`; a deployment whose IdP names a separate resource server sets the
# variable. Never defaulted to "any": `aud` is a required claim on this path, so
# an unconfigured audience refuses every token rather than accepting all of them.
OIDC_AUDIENCE = env.str("COMPONENT_OIDC_AUDIENCE", default="") or OIDC_CLIENT_ID
# The signature-algorithm allowlist. Never taken from the token's own `alg`
# header -- that is the `alg=none` and algorithm-confusion family of attacks.
OIDC_ALGORITHMS = env.list("COMPONENT_OIDC_ALGORITHMS", default=["RS256"])
# Clock-skew tolerance for `exp`, `iat` and `nbf`, in seconds. **Zero by default,
# which is the verification posture this component shipped with and is not
# changed here** -- this adds the lever, not a new policy. It exists because a
# few seconds of drift between the IdP's clock and this host's produces
# intermittent 401s with no diagnosable cause, and the only alternative is
# telling an operator to fix NTP on a machine they may not own. Raising it is a
# deliberate widening of the credential window: a token is accepted for this many
# seconds *past its own `exp`*, so the value is the amount of extra life every
# token in the deployment gains. Keep it in single-digit seconds.
OIDC_LEEWAY_SECONDS = max(0.0, env.float("COMPONENT_OIDC_LEEWAY_SECONDS", default=0.0))
# The JWKS cache lifetime. Its only job is to notice a key *removed* at the IdP
# (AD-23). Rotation is handled by the uncached-`kid` refetch below, so shortening
# this does not catch a rotation faster, and it has no effect at all on R-2's
# revocation window, which governs authorization rather than key material.
#
# Clamped to a floor rather than taken as given: at zero or below, every lookup
# sees the cache as expired and each one attempts a fetch, so the JWKS document
# is re-fetched as fast as the refetch window permits for the life of the
# process. A minute is the shortest lifetime that still makes the cache a cache.
JWKS_TTL_SECONDS = max(60.0, env.float("COMPONENT_JWKS_TTL_SECONDS", default=3600.0))
# The shortest interval between two outbound JWKS fetches. The Bearer path is
# unauthenticated at the moment a key is needed, so without this a caller sending
# random `kid` values produces one fetch per request against the IdP's JWKS
# endpoint. Lowering it towards zero is what re-arms that amplification.
#
# Clamped for that reason, and this floor is the load-bearing one: at zero or
# below the comparison `now - last_attempt < window` is false for every caller,
# which disables the rate limit outright and re-arms exactly the amplification
# this module was written to prevent. A configuration mistake must not be able to
# turn that off, so the floor is enforced here rather than documented as advice.
JWKS_MIN_REFETCH_SECONDS = max(1.0, env.float("COMPONENT_JWKS_MIN_REFETCH_SECONDS", default=60.0))

# django-rest-framework
# -------------------------------------------------------------------------------
# django-rest-framework - https://www.django-rest-framework.org/api-guide/settings/
REST_FRAMEWORK = {
    # The Bearer class is first deliberately: a request carrying both a session
    # cookie and an `Authorization: Bearer` header is decided by the Bearer
    # credential, because that is the one the caller chose to present. It returns
    # None rather than raising when no Bearer header is there, so a
    # session-authenticated request still falls through to the class below it.
    #
    # These two are the whole credential surface (FR-6, Story 2.8): the
    # locally minted static-token path is deleted, app and class alike, so every
    # credential a component accepts is one the IdP owns, plus the session those
    # flows establish. See docs/authentication.md, "Retired surfaces".
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "config.authorization.authentication.OIDCBearerAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# django-cors-headers - https://github.com/adamchainz/django-cors-headers#setup
CORS_URLS_REGEX = r"^/api/.*$"

# By Default swagger ui is available only to admin user(s). You can change permission classes to change that
# See more configuration options at https://drf-spectacular.readthedocs.io/en/latest/settings.html#settings
# Annotated because production.py adds a "SERVERS" list of dicts, which a
# value-inferred dict type would reject.
SPECTACULAR_SETTINGS: dict[str, Any] = {
    "TITLE": "Django 15-Factor Application Accelerator API",
    "DESCRIPTION": "Documentation of API endpoints of Django 15-Factor Application Accelerator",
    "VERSION": "1.0.0",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
    "SCHEMA_PATH_PREFIX": "/api/",
}
# Your stuff...
# ------------------------------------------------------------------------------
