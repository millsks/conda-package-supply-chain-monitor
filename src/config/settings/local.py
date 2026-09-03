import sys

from config.authorization.claims import ClaimsContract
from config.local_dev.keys import DEV_KEY_DIR
from config.local_dev.keys import JWKS_FILENAME
from config.startup import run_stage_one

from .base import *  # noqa: F403
from .base import AUTHENTICATION_BACKENDS
from .base import CLAIMS_CONTRACT
from .base import INSTALLED_APPS
from .base import MIDDLEWARE
from .base import OIDC_AUDIENCE
from .base import OIDC_ISSUER
from .base import OIDC_JWKS_URL
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="TpqsnxPtcoMqj8iXZe7QEHO0LZWjP29KXCIowsta3qyXh17qbe90bYcsELUoVeJo",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1"]  # noqa: S104

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
# One of FR-18's five substitutions: with no Redis running, the cache is the
# in-process one. What makes it a substitution rather than a different feature is
# that the cache *API* is preserved -- `django.core.cache.cache` behaves the same
# here as it does against the Redis backend production.py configures, so no call
# site may branch on which backend is active. The moment one does, this stops
# being a stand-in and becomes a second code path that local runs never exercise.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)

# WhiteNoise
# ------------------------------------------------------------------------------
# http://whitenoise.evans.io/en/latest/django.html#using-whitenoise-in-development
INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]


# DEBUG APPS
# ------------------------------------------------------------------------------
# django-debug-toolbar and django-extensions are development tooling and ship
# only in the pixi `dev` feature, so they are absent from the runtime
# environment. Importing them unconditionally makes these settings unusable
# there -- Django aborts with ModuleNotFoundError before it can start.
#
# The dev environment sets DJANGO_DEBUG_APPS=True for you (see
# [feature.dev.activation.env] in pixi.toml); everywhere else it defaults off.
DEBUG_APPS = env.bool("DJANGO_DEBUG_APPS", default=False)

if DEBUG_APPS:
    # django-debug-toolbar
    # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
    INSTALLED_APPS += ["debug_toolbar"]
    # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
    MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
    # https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
    DEBUG_TOOLBAR_CONFIG = {
        "DISABLE_PANELS": [
            "debug_toolbar.panels.redirects.RedirectsPanel",
            # Disable profiling panel due to an issue with Python 3.12+:
            # https://github.com/jazzband/django-debug-toolbar/issues/1875
            "debug_toolbar.panels.profiling.ProfilingPanel",
        ],
        "SHOW_TEMPLATE_CONTEXT": True,
    }
    # https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
    INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]

    # django-extensions
    # https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
    INSTALLED_APPS += ["django_extensions"]
# Celery
# ------------------------------------------------------------------------------
# FR-18's task substitution, and it holds in **all six** valid combinations
# locally -- including the two that selected background task processing. FR-22's
# broker constraint is a statement about *deployment* only: nothing has to be
# running here, because the task body executes in the calling process.
#
# Deployed, the same absence is a conditional refusal (FR-14, Epic 4): a
# component that selected background task processing and came up with no broker
# is misconfigured, not conveniently eager.
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-always-eager
CELERY_TASK_ALWAYS_EAGER = True
# Eager on its own captures a raised exception into the result object, where a
# caller that never inspects `.result` will not see it -- so a task body that
# fails locally would look like one that passed. Propagating is what re-raises it
# in the caller, which is what makes "task bodies are invoked synchronously"
# mean the same thing for failures as it does for successes.
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-eager-propagates
CELERY_TASK_EAGER_PROPAGATES = True
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

# Local development values, not defaults. `base.py` defaults none of the four
# claim names -- `config/authorization/claims.py` reads each from the environment
# and leaves it empty when unset, deliberately, so that a deployed component with
# a half-configured contract is caught by Epic 4's stage-1 refusal rather than
# silently mapping against a conventional name nobody declared.
#
# Local development still needs a *configured* contract: FR-19's personas are
# materialized by driving the real mapper with synthetic claims, and the mapper
# rejects a payload whose identity-key claim it cannot find. With the contract
# left empty here, `pixi run -e dev seed-personas` fails on a fresh clone with
# `ClaimsRejected: identity key claim absent` -- which is the mapper behaving
# correctly against a contract that was never declared, not a seeding bug.
#
# These names mirror `config/settings/test.py`'s fixture values so that what a
# developer exercises by hand is what the suite exercises.
#
# Only *unset* fields are filled. `base.py` has already read all four through
# `load_claims_contract(env)`, so pointing a local run at a real identity realm
# is still done with the four `COMPONENT_*` variables that
# `config/authorization/claims.py` declares -- this block does not re-spell their
# names, and anything the environment supplied survives untouched.
CLAIMS_CONTRACT = ClaimsContract(
    identity_key_claim=CLAIMS_CONTRACT.identity_key_claim or "sub",
    group_claim=CLAIMS_CONTRACT.group_claim or "groups",
    staff_group=CLAIMS_CONTRACT.staff_group or "platform-staff",
    superuser_group=CLAIMS_CONTRACT.superuser_group or "platform-superuser",
)

# Your stuff...
# ------------------------------------------------------------------------------

# THE LOCAL PROGRAMMATIC CREDENTIAL
# ------------------------------------------------------------------------------
# FR-20: the local programmatic flow validates for real. `pixi run -e dev
# mint-token <persona>` signs a JWT with a keypair generated on this machine, and
# the three values below are what let
# `config/authorization/authentication.py` -- the real Bearer class, with nothing
# stubbed and no local branch inside it -- verify that token's signature, `iss`,
# `aud` and `exp`.
#
# The JWKS location is a `file://` URL because there is no IdP running locally to
# serve one. `config/authorization/jwks.py` accepts that scheme only where
# locality is local; deployed, the same location is refused there and, once Epic 4
# lands, refused again at startup by AD-23's trust-anchor condition, which
# `jwks_url_derives_from_issuer` already answers `False` for. Importing
# `DEV_KEY_DIR` names the directory without creating anything: `keys.py` reads no
# settings and generates no key at import (FR-23), and the first key is written
# by the minting task rather than by boot.
#
# **The issuer half of the condition is what keeps a real realm reachable.**
# `base.py` leaves this empty on purpose: `configured_jwks_url()` falls back to
# `conventional_jwks_url(OIDC_ISSUER)`, so an unset location means *derived from
# the issuer*, not *unconfigured*. Filling it unconditionally would destroy that
# fallback -- a developer who exports only `COMPONENT_OIDC_ISSUER` to point a
# local run at a real Keycloak would silently get this machine's own key as the
# trust anchor, and every token that realm issued would be refused with
# `no signing key published for the presented kid`. So the file location is the
# fallback only when *neither* variable was declared, which is the fresh-clone
# case it exists for. `OIDC_ISSUER` still carries the environment's value here:
# the local fill below has not run yet, and the order is load-bearing for exactly
# this reason.
_DEV_JWKS_LOCATION = "" if OIDC_ISSUER.strip() else (DEV_KEY_DIR / JWKS_FILENAME).as_uri()
OIDC_JWKS_URL = OIDC_JWKS_URL.strip() or _DEV_JWKS_LOCATION
# Local development values, not defaults, filled the same way `CLAIMS_CONTRACT`
# above is filled: only where the environment left them unset, so pointing a local
# run at a real identity realm is still done with the `COMPONENT_*` variables and
# this block re-spells none of their names.
#
# **Both are load-bearing rather than decorative.** `base.py` defaults each to the
# empty string, and PyJWT refuses a token whose `aud` is empty with
# `MissingRequiredClaimError` -- `_validate_aud` tests `not payload["aud"]`, not
# merely its presence. With the audience unset, every locally minted token is
# rejected and the flow FR-20 describes cannot work on a fresh clone. The issuer
# is set alongside it so that the wrong-issuer rejection is a real rejection
# rather than two empty strings comparing equal.
#
# **Stripped before the test, in all three.** A variable exported as `"   "` is
# truthy, so an unstripped `or` treats whitespace as a declaration and skips the
# fill -- and `authentication._audience()` strips before comparing, so the
# component would then refuse every token while every setting looked configured.
# The failure has no diagnostic: the value is present, non-empty and wrong.
#
# `.invalid` is reserved by RFC 2606 and resolves nowhere, which is the point:
# these values are verified as strings and are never fetched. Nothing here reaches
# `SOCIALACCOUNT_PROVIDERS`, which `base.py` already built from the issuer it read
# there.
OIDC_ISSUER = OIDC_ISSUER.strip() or "https://local-dev.invalid/realms/component"
OIDC_AUDIENCE = OIDC_AUDIENCE.strip() or "local-dev-component-api"

# Stage 1 of the refusal contract (AD-26, FR-12). The last statement of this
# module, deliberately: it runs after the AD-8 composition step by construction,
# so every value a condition inspects is the composed one. `base.py` makes no
# such call -- it is a fragment consumed through `from .base import *`, and a
# call at its end would fire before this module had finished composing.
run_stage_one(sys.modules[__name__])
