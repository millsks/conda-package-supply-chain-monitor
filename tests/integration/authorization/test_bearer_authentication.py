"""The Bearer credential through a real DRF request cycle.

Real tokens, a real signature, the real mapper and a real database. What is
stubbed is exactly one thing -- the key store's fetch -- because AD-23's whole
point is that the JWKS document comes from the IdP, and nothing in this
repository may open a socket. The keypair is generated in-test at 2048 bits
(NFR-7: secrets never live in source) and the JWK Set the store is handed is the
document that keypair would be published as.

`api:user-me` is the route every case drives, because it exists today, requires
authentication, and returns something an assertion can look at.

`KEY_STORE` is module-level state, which makes it the most likely source of an
order-dependent failure in this package. `_bearer` below resets it on both sides
of every test.

**SC-6 is not closed here and cannot be.** It requires a real IdP identity
authenticating through both flows, and it is an external exit criterion owned by
the platform group after Epic 2. Every case below passes against a locally
generated keypair and a stubbed JWKS document; that is deliberate and is not
proof of SC-6.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog
from django.contrib.auth.models import Group

from config.authorization import authentication as authentication_module
from config.authorization.jwks import KEY_STORE
from django_service.users.models import User
from tests.jwt_keys import SigningKey
from tests.jwt_keys import StubFetch
from tests.jwt_keys import generate
from tests.jwt_keys import jwks_document
from tests.jwt_keys import sign_with_a_symmetric_key
from tests.jwt_keys import sign_with_an_elliptic_curve_key

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.test import Client
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

ISSUER = "https://idp.example.com/realms/main"
AUDIENCE = "component-api"
PUBLISHED_KID = "primary-2026"
UNPUBLISHED_KID = "never-published"

SUBJECT = "urn:example:principal:api-client"
GROUP = "engineering"
CLAIMED_USERNAME = "api-client"

# AC #2's "contains no mapping logic of its own", read off the module's own
# source, in the shape Story 2.6 established for the adapter. Every authorization
# decision this component takes is spelled with one of these three names, so
# their absence is what the claim means concretely.
MAPPING_VOCABULARY = ("Group", "is_" + "staff", "is_" + "superuser")

# The route the whole suite drives. Named rather than reversed at module scope so
# the URLconf is not loaded at collection time.
ROUTE = "api:user-me"


@pytest.fixture(scope="module")
def published_key() -> SigningKey:
    """The keypair the stubbed IdP publishes."""
    return generate(PUBLISHED_KID)


@pytest.fixture(scope="module")
def impostor_key() -> SigningKey:
    """A keypair nobody published, wearing the published `kid`.

    This is what makes the bad-signature case a *signature* case rather than an
    unknown-key case: the store answers with the real published key and the
    signature simply does not check out against it.
    """
    return generate(PUBLISHED_KID)


@pytest.fixture(autouse=True)
def _bearer(settings: SettingsWrapper, published_key: SigningKey) -> Iterator[StubFetch]:
    """Point the component at the stubbed IdP and leave the key store as it was found."""
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_AUDIENCE = AUDIENCE
    settings.OIDC_ALGORITHMS = ["RS256"]
    settings.JWKS_TTL_SECONDS = 3600.0
    settings.JWKS_MIN_REFETCH_SECONDS = 60.0

    KEY_STORE.reset()
    fetch = StubFetch(jwks_document(published_key))
    original = KEY_STORE._fetch  # noqa: SLF001 - the constructor seam, reached on the module-level instance
    KEY_STORE._fetch = fetch  # noqa: SLF001 - see above
    try:
        yield fetch
    finally:
        KEY_STORE._fetch = original  # noqa: SLF001 - see above
        KEY_STORE.reset()


@pytest.fixture
def jwks_fetch(_bearer: StubFetch) -> StubFetch:
    """The fetch seam, for the cases that count outbound requests."""
    return _bearer


@pytest.fixture
def route() -> str:
    """The URL every case drives."""
    from django.urls import reverse  # noqa: PLC0415 - resolved per test, not at collection

    return reverse(ROUTE)


def claims(**overrides: Any) -> dict[str, Any]:
    """Build the claims a well-formed access token would carry.

    Args:
        **overrides: Claims to replace. A `None` value removes the claim
            outright, which is how the missing-`jti` case is expressed.

    Returns:
        The claims, with a fresh `jti` on every call so a second token for the
        same identity is a second credential epoch rather than a replay.

    """
    now = datetime.now(tz=UTC)
    built: dict[str, Any] = {
        "sub": SUBJECT,
        "groups": [GROUP],
        "jti": str(uuid.uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "preferred_username": CLAIMED_USERNAME,
    }
    built.update(overrides)
    return {name: value for name, value in built.items() if value is not None}


def bearer(token: str) -> dict[str, str]:
    """Render a token as the header a client would send.

    Args:
        token: The encoded token.

    Returns:
        The header mapping Django's test client takes.

    """
    return {"authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# AC #1, #2 -- a valid credential authenticates, and the mapper is what decides.
# ---------------------------------------------------------------------------


def test_a_valid_bearer_token_authenticates_and_resolves_the_mapped_user(
    client: Client,
    route: str,
    published_key: SigningKey,
) -> None:
    """FR-5 end to end: signature, `iss`, `aud` and `exp` verified, then the mapper asked."""
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(published_key.sign(claims())))

    assert response.status_code == HTTPStatus.OK
    user = User.objects.get(idp_subject=SUBJECT)
    assert response.json()["username"] == user.username
    assert user.username == CLAIMED_USERNAME
    # The groups moved, which is only true if `sync_once_per_epoch` ran -- the
    # authentication class does no group work of its own (AC #2).
    assert list(user.groups.values_list("name", flat=True)) == [GROUP]


def test_the_authentication_class_holds_no_mapping_logic_of_its_own() -> None:
    """AC #2: it invokes the mapper and contains no mapping logic at all.

    Asserted against the module's own source rather than only against behaviour,
    because an inlined group lookup would still leave the mapper nominally
    called and every behavioural assertion green.
    """
    source = Path(str(authentication_module.__file__)).read_text(encoding="utf-8")

    found = [name for name in MAPPING_VOCABULARY if name in source]

    assert found == [], f"{found} in config/authorization/authentication.py -- that belongs to the mapper"


# ---------------------------------------------------------------------------
# AC #1 -- one case per clause, each answered with 401.
# ---------------------------------------------------------------------------


def test_a_token_whose_signature_does_not_check_out_is_refused(
    client: Client,
    route: str,
    impostor_key: SigningKey,
) -> None:
    """The signature clause. The `kid` is real, so the store answers and the check fails."""
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(impostor_key.sign(claims())))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert User.objects.filter(idp_subject=SUBJECT).count() == 0


def test_a_token_asserting_another_issuer_is_refused(
    client: Client,
    route: str,
    published_key: SigningKey,
) -> None:
    """The `iss` clause."""
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(published_key.sign(claims(iss="https://evil.example.com/realms/main"))))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_a_token_minted_for_another_audience_is_refused(
    client: Client,
    route: str,
    published_key: SigningKey,
) -> None:
    """The `aud` clause."""
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(published_key.sign(claims(aud="another-component"))))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_an_expired_token_is_refused(client: Client, route: str, published_key: SigningKey) -> None:
    """The `exp` clause."""
    Group.objects.get_or_create(name=GROUP)
    expired = int((datetime.now(tz=UTC) - timedelta(hours=1)).timestamp())

    response = client.get(route, headers=bearer(published_key.sign(claims(exp=expired))))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize("absent", ["exp", "iss", "aud"])
def test_a_token_omitting_a_required_claim_is_refused(
    client: Client,
    route: str,
    published_key: SigningKey,
    absent: str,
) -> None:
    """Omission is not a way past a check.

    PyJWT verifies an *absent* `aud` against nothing unless it is required, so
    without the `require` option a token minted for another audience could pass
    the audience clause by simply leaving the claim out.
    """
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(published_key.sign(claims(**{absent: None}))))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_a_token_signed_with_an_algorithm_outside_the_allowlist_is_refused(client: Client, route: str) -> None:
    """`alg` comes from configuration, never from the token -- the algorithm-confusion family."""
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(sign_with_a_symmetric_key(claims(), kid=PUBLISHED_KID)))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_a_token_signed_with_the_other_permitted_family_is_refused_not_crashed(
    client: Client,
    route: str,
    settings: SettingsWrapper,
) -> None:
    """A key/algorithm mismatch is a verdict about the credential, so it is a 401.

    `RS256,ES256` is a supported value of `COMPONENT_OIDC_ALGORITHMS` -- the
    settings suite blesses it -- and an IdP that publishes only RSA keys under a
    two-family allowlist is therefore a shipped configuration. A token signed
    with the family the published key is *not* makes PyJWT's key preparation
    raise a bare `TypeError`, which is not under `InvalidTokenError` and is not a
    `PyJWTError` at all.

    Uncaught, that escapes as a **500 with a traceback**, on an unauthenticated
    path, with no `bearer_rejected` event -- so the one signal an operator has
    that someone is probing the credential is absent for the probe most likely to
    be deliberate. The status code is half the assertion; the event is the other
    half.
    """
    Group.objects.get_or_create(name=GROUP)
    settings.OIDC_ALGORITHMS = ["RS256", "ES256"]
    token = sign_with_an_elliptic_curve_key(claims(), kid=PUBLISHED_KID)

    with structlog.testing.capture_logs() as captured:
        response = client.get(route, headers=bearer(token))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    refusals = [event for event in captured if event["event"] == "authorization.bearer_rejected"]
    assert len(refusals) == 1, "a refusal that emits no event is a refusal nobody can see"
    assert refusals[0]["kid"] == PUBLISHED_KID


def test_a_token_naming_a_kid_nobody_published_is_refused(
    client: Client,
    route: str,
    published_key: SigningKey,
) -> None:
    """The key store refuses, and the refusal is a 401 like any other."""
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(published_key.sign(claims(), kid=UNPUBLISHED_KID)))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_a_token_carrying_no_kid_is_refused(client: Client, route: str, published_key: SigningKey) -> None:
    """Without a `kid` there is no published key to check against, and no set to try in turn."""
    Group.objects.get_or_create(name=GROUP)
    import jwt  # noqa: PLC0415 - only this case mints a token outside the helper

    token = jwt.encode(claims(), published_key.private_key, algorithm="RS256")

    response = client.get(route, headers=bearer(token))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("Bearer", id="scheme-with-no-token"),
        pytest.param("Bearer a b", id="scheme-with-two-tokens"),
        pytest.param("Bearer not-a-jwt", id="scheme-with-something-that-is-not-a-jwt"),
    ],
)
def test_a_malformed_bearer_header_is_refused(client: Client, route: str, header: str) -> None:
    """The credential was offered to this class, so a broken one is refused rather than passed on."""
    response = client.get(route, headers={"authorization": header})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_a_refused_request_is_challenged_rather_than_forbidden(
    client: Client,
    route: str,
    impostor_key: SigningKey,
) -> None:
    """`authenticate_header` is what makes every refusal above a 401 instead of a 403."""
    response = client.get(route, headers=bearer(impostor_key.sign(claims())))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_refusal_tells_the_caller_nothing_about_which_check_failed(
    client: Client,
    route: str,
    published_key: SigningKey,
) -> None:
    """Naming the failing clause to an unauthenticated caller is a verification oracle."""
    wrong_audience = client.get(route, headers=bearer(published_key.sign(claims(aud="another-component"))))
    expired = int((datetime.now(tz=UTC) - timedelta(hours=1)).timestamp())
    stale = client.get(route, headers=bearer(published_key.sign(claims(exp=expired))))

    assert wrong_audience.json() == stale.json()
    assert SUBJECT not in wrong_audience.content.decode()


# ---------------------------------------------------------------------------
# Clock skew -- a lever, deliberately shipped at zero.
# ---------------------------------------------------------------------------


def test_a_token_expired_within_the_configured_tolerance_is_admitted(
    client: Client,
    route: str,
    published_key: SigningKey,
    settings: SettingsWrapper,
) -> None:
    """A few seconds of IdP clock drift otherwise produces intermittent, undiagnosable 401s.

    With no tolerance, `exp` is compared against the local clock with zero
    slack, so a component whose host runs a few seconds ahead of the IdP refuses
    tokens that are, by the issuer's own clock, still valid -- and does it
    sporadically, which is the hardest shape of failure to attribute.
    """
    Group.objects.get_or_create(name=GROUP)
    settings.OIDC_LEEWAY_SECONDS = 30.0
    just_expired = int((datetime.now(tz=UTC) - timedelta(seconds=5)).timestamp())

    response = client.get(route, headers=bearer(published_key.sign(claims(exp=just_expired))))

    assert response.status_code == HTTPStatus.OK


def test_the_same_token_is_refused_with_the_shipped_tolerance(
    client: Client,
    route: str,
    published_key: SigningKey,
    settings: SettingsWrapper,
) -> None:
    """The control for the case above, and the assertion that the default is still strict.

    Only `OIDC_LEEWAY_SECONDS` differs between the two. This is what makes the
    lever a lever rather than a policy change: at its default the expiry check is
    exactly as tight as it was before the setting existed.
    """
    Group.objects.get_or_create(name=GROUP)
    settings.OIDC_LEEWAY_SECONDS = 0.0
    just_expired = int((datetime.now(tz=UTC) - timedelta(seconds=5)).timestamp())

    response = client.get(route, headers=bearer(published_key.sign(claims(exp=just_expired))))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------------------
# AD-10 / Story 2.5 -- the `jti` rule, observed through this surface.
# ---------------------------------------------------------------------------


def test_a_token_carrying_no_jti_is_refused(client: Client, route: str, published_key: SigningKey) -> None:
    """Story 2.5's rule has one home, in the mapper, and arrives here as any other refusal."""
    Group.objects.get_or_create(name=GROUP)

    response = client.get(route, headers=bearer(published_key.sign(claims(jti=None))))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    # The refusal happens after the user is resolved, so the row exists; what
    # must not have happened is the sync.
    assert User.objects.filter(idp_subject=SUBJECT, groups__name=GROUP).count() == 0


# ---------------------------------------------------------------------------
# AC #7 -- a deactivated user's token verifies cleanly and is still refused.
# ---------------------------------------------------------------------------


def test_a_token_verifying_against_a_deactivated_user_is_refused(
    client: Client,
    route: str,
    published_key: SigningKey,
) -> None:
    """Without the mapper's check this is the case that authenticates a deactivated principal.

    Nothing is wrong with the token: it is signed by the published key, asserts
    the right issuer and audience, and has not expired. The Bearer path has no
    Django authentication backend in front of it, so if `resolve_user` ever stops
    refusing an inactive row, this request answers 200 and every API call a
    deactivated person's token makes succeeds until the token expires.
    """
    Group.objects.get_or_create(name=GROUP)
    User.objects.create(username="retired", idp_subject=SUBJECT, is_active=False)

    response = client.get(route, headers=bearer(published_key.sign(claims())))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_an_active_user_with_the_same_shape_of_token_is_admitted(
    client: Client,
    route: str,
    published_key: SigningKey,
) -> None:
    """The control for the case above: only `is_active` differs between the two."""
    Group.objects.get_or_create(name=GROUP)
    User.objects.create(username="still-here", idp_subject=SUBJECT, is_active=True)

    response = client.get(route, headers=bearer(published_key.sign(claims())))

    assert response.status_code == HTTPStatus.OK


# ---------------------------------------------------------------------------
# AC #3 -- the first Bearer request is what fetches, and only the first.
# ---------------------------------------------------------------------------


def test_the_first_bearer_request_is_what_fetches_the_jwks(
    client: Client,
    route: str,
    published_key: SigningKey,
    jwks_fetch: StubFetch,
) -> None:
    """Lazily on the first request that needs it (AD-23), and cached by `kid` after that."""
    Group.objects.get_or_create(name=GROUP)
    assert jwks_fetch.calls == 0, "something fetched before any Bearer request was made"

    first = client.get(route, headers=bearer(published_key.sign(claims())))
    assert first.status_code == HTTPStatus.OK
    assert jwks_fetch.calls == 1

    second = client.get(route, headers=bearer(published_key.sign(claims())))

    assert second.status_code == HTTPStatus.OK
    assert jwks_fetch.calls == 1, "a cached kid triggered a second outbound fetch"


def test_a_request_with_no_bearer_header_never_reaches_the_key_store(
    client: Client,
    route: str,
    jwks_fetch: StubFetch,
) -> None:
    """A session-authenticated request must not pay for JWKS material it does not use."""
    person = User.objects.create(username="signed-in", idp_subject="urn:example:principal:session")
    client.force_login(person)

    response = client.get(route)

    assert response.status_code == HTTPStatus.OK
    assert jwks_fetch.calls == 0


# ---------------------------------------------------------------------------
# Falling through -- returning None rather than raising is what keeps sessions working.
# ---------------------------------------------------------------------------


def test_no_authorization_header_falls_through_to_session_authentication(client: Client, route: str) -> None:
    """Raising on an absent header would refuse every session-authenticated request."""
    person = User.objects.create(username="signed-in", idp_subject="urn:example:principal:session")
    client.force_login(person)

    response = client.get(route)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["username"] == "signed-in"


def test_a_header_naming_another_scheme_falls_through_too(client: Client, route: str) -> None:
    """A scheme this class does not own is passed on rather than refused.

    `Token ...` is the one Story 2.8 retired, and it is still the right probe:
    nothing accepts that scheme any more, so the request must fall through to
    `SessionAuthentication` and be decided by the session it carries. Refusing an
    unrecognised scheme here would mean a signed-in caller sending any other
    `Authorization` header -- one this component never issued -- got a 401.
    """
    person = User.objects.create(username="signed-in", idp_subject="urn:example:principal:session")
    client.force_login(person)

    response = client.get(route, headers={"authorization": "Token 0123456789abcdef"})

    assert response.status_code == HTTPStatus.OK


def test_an_anonymous_request_with_no_credential_at_all_is_refused(client: Client, route: str) -> None:
    """Falling through is not admitting: the default permission class is `IsAuthenticated`.

    401 rather than the 403 this component answered before Story 2.7, and the
    change reaches every DRF route rather than only the Bearer ones: DRF renders
    a permission failure for an unauthenticated request as 401 as soon as *some*
    authenticator offers a challenge, and this class is the first that does. The
    spine's rule -- "authentication failure is 401" -- is what it moves onto.
    `tests/integration/users/test_api_openapi.py` records the same change on the
    schema route.
    """
    response = client.get(route)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
