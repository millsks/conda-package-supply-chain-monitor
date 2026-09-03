"""What is left of the credential surface after the static-token path is deleted.

FR-6 names three things -- `rest_framework.authtoken`, `TokenAuthentication` and
the `obtain_auth_token` route -- and this module asserts the absence of each.

The route half is asserted against the **resolved** URLconf rather than against
`urls.py` as text. That is AC #2's own wording: `reverse` and `resolve` read the
configuration Django actually loaded, so a route reintroduced from an included
URLconf this file never mentions still fails here, and so does one whose text
lives in a module a string search never opened.

Be precise about what that does *not* buy. `reverse` catches a reintroduction
only if it keeps the old name, and `resolve` catches one only at the old path: a
remount of the same view at another prefix under another name passes both. AD-26
asks for a predicate that walks the resolver and compares view callables by
identity, and that predicate is deliberately not built here -- it is Epic 4
Stories 4.3 and 4.6, and the spine requires the refusal contract to have one
owner. What is here is the story-scale assertion that the surface this story
deleted is gone, not the enforcement that it stays gone.

The settings half resolves objects rather than matching strings, for the same
reason at smaller scale: `apps.is_installed` sees the app however its entry is
spelled, and `issubclass` sees a static-token authenticator however it is named.

`tests/unit/users/test_api_urls.py` is the pattern the route tests follow, from
the other direction: it names routes that must resolve, this one names a route
that must not.

These are unit assertions -- the URLconf and the settings are read in-process,
with no database, socket or filesystem involved.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.urls import NoReverseMatch
from django.urls import Resolver404
from django.urls import resolve
from django.urls import reverse
from django.utils.module_loading import import_string
from rest_framework.authentication import TokenAuthentication
from rest_framework.settings import api_settings

# The route as it was mounted, and the name it was reversible by. Both are
# spelled out because both were part of the surface: the name is what source in
# this repository would have used, the path is what a client would have posted to.
RETIRED_ROUTE_NAME = "obtain_auth_token"
RETIRED_ROUTE_PATH = "/api/auth-token/"

# The dotted module path, which is what `apps.is_installed` compares against
# (`AppConfig.name`) -- and what an `AppConfig`-spelled entry still reports.
RETIRED_APP = "rest_framework.authtoken"

# The credentials that must remain, in the order they are consulted.
IDP_OWNED_AUTHENTICATORS = [
    "config.authorization.authentication.OIDCBearerAuthentication",
    "rest_framework.authentication.SessionAuthentication",
]


def test_the_token_minting_route_is_not_reversible() -> None:
    """No source in this repository can name the route, because the name resolves to nothing."""
    with pytest.raises(NoReverseMatch):
        reverse(RETIRED_ROUTE_NAME)


def test_the_token_minting_path_resolves_to_no_view() -> None:
    """The path a client would post credentials to matches nothing in the loaded URLconf.

    This is the assertion AC #2 asks for by name. Asserted separately from the
    reverse above because they fail for different reasons: an unnamed route still
    resolves, so dropping only the `name=` would leave the path live while
    `reverse` already raised.
    """
    with pytest.raises(Resolver404):
        resolve(RETIRED_ROUTE_PATH)


def test_the_token_app_is_not_installed() -> None:
    """The app is gone from the registry, so its model, migrations and admin registration are.

    Asked of the registry rather than of `INSTALLED_APPS` as a list of strings.
    `is_installed` compares `AppConfig.name`, so it answers for the app itself
    rather than for one spelling of its entry -- an
    `"rest_framework.authtoken.apps.AuthTokenConfig"` entry installs the same app
    and reports the same name, while a membership test against the list would
    not see it.

    What this does not claim is that the code became unimportable.
    `rest_framework.authtoken` ships inside the installed `djangorestframework`
    package and its view still imports fine -- uninstalling an app removes its
    registration, not its reachability. That is precisely why the route assertions
    above are a separate matter from this one.
    """
    assert not apps.is_installed(RETIRED_APP)


def test_no_default_authenticator_is_the_static_token_one() -> None:
    """The DRF defaults hold no static-token authenticator, however it is named.

    Read through `api_settings` rather than off `settings.REST_FRAMEWORK`, because
    that is the configuration DRF actually consults: if the
    `DEFAULT_AUTHENTICATION_CLASSES` key were dropped from the dict altogether,
    reading the dict raises `KeyError` while DRF quietly falls back to its own
    defaults -- which include `BasicAuthentication` against local passwords. The
    fallback is the failure mode worth catching, not the `KeyError`.

    Resolved to classes and tested with `issubclass` rather than matched on the
    name, so a subclass called anything at all is still caught. AD-26's rule
    stated at the scale this file operates on: predicates resolve objects, never
    strings.
    """
    static_token = [cls for cls in api_settings.DEFAULT_AUTHENTICATION_CLASSES if issubclass(cls, TokenAuthentication)]

    assert static_token == [], f"{static_token} is a locally minted credential the IdP does not own"


def test_the_credentials_the_idp_owns_are_still_the_defaults() -> None:
    """The control: this story subtracts, and what it must not have subtracted is here.

    Without this, deleting the whole tuple would pass every assertion above while
    leaving the API with no authentication at all. Order is asserted too, because
    it decides which credential wins when a request carries both.
    """
    resolved = [import_string(entry) for entry in IDP_OWNED_AUTHENTICATORS]

    assert list(api_settings.DEFAULT_AUTHENTICATION_CLASSES) == resolved
