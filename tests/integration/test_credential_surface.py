"""The retired credential surface, and its replacement, through real requests.

Two halves of one claim. The first is that `/api/auth-token/` is *gone* -- not
deprecated, not answering 410, not redirecting: a request to it matches nothing
and gets Django's 404, which is the only answer that means the route does not
exist. `tests/unit/test_credential_surface.py` asserts the same thing against the
resolved URLconf; this asserts it through the stack a client actually reaches, so
a 410, a redirect or a shim answering at that path fails here even though
`resolve` would already have raised. What neither file catches is the same view
remounted elsewhere -- that needs a resolver walk comparing view callables, which
is Epic 4's refusal predicate and deliberately not built here.

The second is FR-6's "no functionality is lost": the API call a client used to
make with a locally minted token succeeds today with a token the IdP minted.
`tests/integration/authorization/test_bearer_authentication.py` is the full
account of that flow; what is repeated here is only the one end-to-end pass, so
that the removal and its replacement are asserted together rather than in two
suites that could each be true while the transition was not.

The IdP is stubbed at exactly one seam -- the key store's fetch -- for the reason
that suite states: nothing in this repository opens a socket, and NFR-7 keeps
signing material out of the source. `tests/jwt_keys.py` holds the shared stubs.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from config.authorization.jwks import KEY_STORE
from tests.jwt_keys import SigningKey
from tests.jwt_keys import StubFetch
from tests.jwt_keys import generate
from tests.jwt_keys import jwks_document

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.test import Client
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

# The path the retired route was mounted at, as a client would have written it.
RETIRED_PATH = "/api/auth-token/"

# The stubbed IdP, in the shape the Bearer suite established.
ISSUER = "https://idp.example.com/realms/main"
AUDIENCE = "component-api"
PUBLISHED_KID = "primary-2026"
SUBJECT = "urn:example:principal:api-client"
CLAIMED_USERNAME = "api-client"
GROUP = "engineering"

# The route the replacement flow drives: it exists, it requires authentication,
# and it answers with something an assertion can read.
ROUTE = "api:user-me"


@pytest.fixture(scope="module")
def published_key() -> SigningKey:
    """The keypair the stubbed IdP publishes."""
    return generate(PUBLISHED_KID)


@pytest.fixture
def _idp(settings: SettingsWrapper, published_key: SigningKey) -> Iterator[None]:
    """Point the component at the stubbed IdP and leave the key store as it was found.

    `KEY_STORE` is module-level state, so restoring the fetch seam and resetting
    the cache on both sides is what keeps this file from deciding whether another
    one passes.

    The two JWKS windows are pinned along with the provider values, matching
    `_bearer` in `tests/integration/authorization/test_bearer_authentication.py`.
    Left unset they fall back to `base.py`'s `env.float` reads, which would make
    this test's configuration a function of whoever's shell ran it.
    """
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_AUDIENCE = AUDIENCE
    settings.OIDC_ALGORITHMS = ["RS256"]
    settings.JWKS_TTL_SECONDS = 3600.0
    settings.JWKS_MIN_REFETCH_SECONDS = 60.0

    KEY_STORE.reset()
    original = KEY_STORE._fetch  # noqa: SLF001 - the constructor seam, reached on the module-level instance
    KEY_STORE._fetch = StubFetch(jwks_document(published_key))  # noqa: SLF001 - see above
    try:
        yield
    finally:
        KEY_STORE._fetch = original  # noqa: SLF001 - see above
        KEY_STORE.reset()


def claims() -> dict[str, Any]:
    """Build the claims a well-formed access token would carry.

    Returns:
        The claims, with a fresh `jti` on every call so a second token is a
        second credential epoch rather than a replay.

    """
    now = datetime.now(tz=UTC)
    return {
        "sub": SUBJECT,
        "groups": [GROUP],
        "jti": str(uuid.uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "preferred_username": CLAIMED_USERNAME,
    }


def test_getting_the_retired_token_route_is_a_404(client: Client) -> None:
    """A credential-minting route that still answers anything is still a route."""
    response = client.get(RETIRED_PATH)

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_posting_credentials_to_the_retired_token_route_is_a_404(client: Client) -> None:
    """The verb the route actually took. A GET-only 404 would leave the minting call live."""
    response = client.post(RETIRED_PATH, {"username": "someone", "password": "something"})

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.usefixtures("_idp")
def test_the_api_call_that_needed_a_static_token_succeeds_with_an_idp_token(
    client: Client,
    published_key: SigningKey,
) -> None:
    """FR-6's "no functionality is lost", stated as the call that used to need the removed route.

    A client posted credentials to `/api/auth-token/`, got a token back and sent
    it as `Authorization: Token ...`. Both halves are gone. The same call now
    carries a token the IdP minted, and answers with the same 200 and the same
    body -- which is what makes this a removal rather than a regression.
    """
    Group.objects.get_or_create(name=GROUP)

    response = client.get(reverse(ROUTE), headers={"authorization": f"Bearer {published_key.sign(claims())}"})

    assert response.status_code == HTTPStatus.OK
    assert response.json()["username"] == CLAIMED_USERNAME
