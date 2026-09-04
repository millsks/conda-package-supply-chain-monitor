"""
With these settings, tests run faster.
"""

import sys

from conda_package_supply_chain_monitor.core.roles import RoleContract
from config.authorization.claims import ClaimsContract
from config.observability.logging import build_logging_config
from config.startup import run_stage_one

from .base import *  # noqa: F403
from .base import AUTHENTICATION_BACKENDS
from .base import TEMPLATES
from .base import env

# LOGGING
# ------------------------------------------------------------------------------
# Console rendering at WARNING so the suite's output stays readable; the
# structlog pipeline itself is still exercised.
LOGGING = build_logging_config(debug=False, log_level="WARNING", log_format="console")

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="sYhAdglZfspXonZpMsZIqpgElwZB1hBExBi9le7qOtuacFm2NEYKIjZL7r3eHz45",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# AUTHENTICATION
# ------------------------------------------------------------------------------
# The local username-and-password path, declared here and refused in a deployed
# component by stage 1's condition 2 (states a and b). `base.py` carries neither:
# it is the surface a deployed component inherits, and a base that carried them
# made every deployment refuse to start.
#
# `ModelBackend` is what persona sign-in hands `django.contrib.auth.login` as
# `config.local_dev.views.SESSION_BACKEND`. `login()` does not check that the
# backend it is given is declared -- `get_user` does, on the *next* request, and
# answers `AnonymousUser` when it is not, so an undeclared backend produces a
# sign-in that returns 302 and a session gone by the redirect.
#
# The login method is allauth's own form, which a developer uses to reach `/admin/`
# without an identity provider running. Both are locality-scoped affordances, and
# they are declared where the locality is for the same reason the cache and task
# substitutions are.
#
# Appended rather than respelled: a second full list would agree with `base.py` on
# the day it was written and drift the first time either changed. Allauth's backend
# stays first, so it answers before Django's own.
AUTHENTICATION_BACKENDS = [
    *AUTHENTICATION_BACKENDS,
    "django.contrib.auth.backends.ModelBackend",
]
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_LOGIN_METHODS = {"username"}

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# CACHES
# ------------------------------------------------------------------------------
# Declared rather than inherited. Django's own default is already LocMemCache and
# base.py sets no `CACHES` at all, so leaving this out would give the suite the
# right backend for the wrong reason -- an implicit framework default that no
# assertion can distinguish from a deliberate substitution, and that a future
# `CACHES` key in base.py would silently replace.
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# Celery
# ------------------------------------------------------------------------------
# The same substitution local.py declares, for the same reason and stated in the
# same place: the suite runs with no broker, and a task's body is expected to run
# in the calling process and to raise into it. Neither of these changes the
# suite's behaviour today -- pytest-django loads these settings and the one task
# test already forces eager execution itself -- which is the point: they make the
# substitution visible to a reader and assertable by a test.
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-always-eager
CELERY_TASK_ALWAYS_EAGER = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-eager-propagates
CELERY_TASK_EAGER_PROPAGATES = True

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# AUTHENTICATION
# ------------------------------------------------------------------------------
# Test fixtures, not defaults. The suite runs against a *configured* contract so
# that it exercises the mapping rather than the unconfigured case, and it does so
# independently of whatever COMPONENT_ variables a developer's shell happens to
# hold. base.py defaults none of these -- see config/authorization/claims.py.
CLAIMS_CONTRACT = ClaimsContract(
    identity_key_claim="sub",
    group_claim="groups",
    staff_group="platform-staff",
    superuser_group="platform-superuser",
)
# The product's role contract, on the same terms and for the same reason: a
# fixture, not a default. It is what makes `core/0001_provision_role_groups`
# actually provision during test-database creation, so the suite asserts the
# state a migration left rather than the state a test set up for itself -- and
# what lets `tests/unit/django_apps/test_roles.py` check that none of these three
# names appears in `roles.py`, the module that declares the contract, or in the
# migration that provisions from it. base.py defaults none of them; see
# conda_package_supply_chain_monitor/core/roles.py.
#
# Deliberately disjoint from CLAIMS_CONTRACT's two group names above. The
# collision case -- one directory group named by both contracts -- is a
# configuration an operator may legitimately have, and it is exercised where it
# belongs, in tests/integration/django_apps/test_role_groups.py, rather than made
# the suite-wide default.
ROLE_CONTRACT = RoleContract(
    security_reviewer="cpm-security-reviewer",
    packaging_engineer="cpm-packaging-engineer",
    leadership="cpm-leadership",
)

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver/"
# Your stuff...
# ------------------------------------------------------------------------------

# Stage 1 of the refusal contract (AD-26, FR-12). The last statement of this
# module, deliberately: it runs after the AD-8 composition step by construction,
# so every value a condition inspects is the composed one. `base.py` makes no
# such call -- it is a fragment consumed through `from .base import *`, and a
# call at its end would fire before this module had finished composing.
run_stage_one(sys.modules[__name__])
