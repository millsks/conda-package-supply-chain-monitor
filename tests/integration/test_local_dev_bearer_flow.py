"""The local programmatic flow, end to end, with nothing stubbed (FR-20).

This suite differs from `tests/integration/authorization/test_bearer_authentication.py`
in exactly one way, and the difference is the point of the story: **the fetch seam
is not replaced.** That suite stubs it because AD-23's subject is retrieval from
an IdP and no test here may open a socket. Here retrieval is a local file read, so
the real `fetch_jwks_document` runs against the real `file://` location the real
`ensure_keypair` wrote. A test that stubbed it would prove the token was
well-formed and nothing at all about AC #1.

Everything else is production code: the real `OIDCBearerAuthentication`, the real
`JWKSKeyStore`, the real mapper, a real database, and a real DRF request cycle
against `api:user-me`. Nothing is patched, no verification option is relaxed, and
there is no local branch anywhere in the class under test.

**The six rejection cases are not garnish.** A single happy-path test passes
against an implementation that verifies nothing. Tampered signature, tampered
payload, expired, wrong issuer, wrong audience and unknown `kid` are how AC #2's
"no verification step is stubbed or skipped" is actually proven -- a class
decoding with `options={"verify_aud": False}` passes every other case in this
file.

`KEY_STORE` is module-level state, which makes it the likeliest source of an
order-dependent failure here: its sixty-second refetch window and its TTL both
outlive a test. `_local_flow` resets it on both sides of every one.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
import structlog

from config.authorization import jwks as jwks_module
from config.authorization.jwks import KEY_STORE
from config.local_dev import keys as keys_module
from config.local_dev import mint
from config.local_dev.keys import ensure_keypair
from config.local_dev.personas import build_claims
from config.local_dev.personas import get_persona
from config.local_dev.tokens import mint_token
from django_service.users.models import CredentialEpoch
from django_service.users.models import User
from django_service.users.provisioning import provision_designated_groups
from tests.jwt_keys import generate

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from django.test import Client
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

#: The persona every case mints for. The staff one, so the 200 case also shows the
#: mapper granting authorization off the same synthetic claims local sign-in uses.
PERSONA_KEY = "staff"

#: The route driven throughout: it exists today, requires authentication, and
#: answers with something an assertion can look at. Named rather than reversed at
#: module scope so the URLconf is not loaded at collection time.
ROUTE = "api:user-me"

#: A `kid` the local document does not publish, for the unknown-key case.
UNPUBLISHED_KID = "never-published"

#: The issuer and audience in force. Stated rather than inherited -- see
#: `_local_flow` -- and `.invalid` is RFC 2606 reserved, because these are
#: verified as strings and never fetched.
#:
#: **Deliberately not the values `config/settings/local.py` fills in.**
#: `tokens.mint_token` reads `settings.OIDC_ISSUER`/`OIDC_AUDIENCE` rather than
#: writing literals, and that is the module's stated contract -- but if these
#: constants matched local.py's defaults, substituting those literals into the
#: mint would change nothing any assertion here observes, and the contract would
#: be unverified. Different strings are what make the difference visible.
ISSUER = "https://suite-only-idp.invalid/realms/verification"
AUDIENCE = "suite-only-component-api"


@pytest.fixture
def _local_flow(settings: SettingsWrapper, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the whole flow at a keypair this test owns, and leave the key store as found.

    The issuer and audience are declared here rather than inherited. The suite
    runs under `config.settings.test`, which sets neither -- `config/settings/local.py`
    is where the local values live, and `tests/unit/test_settings.py` is what
    asserts they are there. Stating them here keeps what this file proves about
    *verification* independent of what that file proves about *configuration*.
    """
    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_AUDIENCE = AUDIENCE
    settings.OIDC_ALGORITHMS = ["RS256"]
    settings.JWKS_TTL_SECONDS = 3600.0
    settings.JWKS_MIN_REFETCH_SECONDS = 60.0

    monkeypatch.setattr(keys_module, "DEV_KEY_DIR", tmp_path / ".local-dev-keys")
    keypair = ensure_keypair()
    settings.OIDC_JWKS_URL = keypair.jwks_path.as_uri()

    KEY_STORE.reset()
    try:
        yield
    finally:
        KEY_STORE.reset()


@pytest.fixture
def route() -> str:
    """The URL every case drives."""
    from django.urls import reverse  # noqa: PLC0415 - resolved per test, not at collection

    return reverse(ROUTE)


def bearer(token: str) -> dict[str, str]:
    """Present a token the way a client does.

    Args:
        token: The encoded token.

    Returns:
        The request headers carrying it.

    """
    return {"authorization": f"Bearer {token}"}


def resign(token: str, claims: dict[str, object]) -> str:
    """Re-sign a payload with the local key, keeping the local `kid`.

    The wrong-`iss` and wrong-`aud` cases need a token that is *valid in every
    other respect* -- correctly signed, naming a published key -- so that the one
    thing the class refuses it for is the claim under test.

    Args:
        token: A token minted by `mint_token`, read only for its header.
        claims: The payload to sign instead.

    Returns:
        The re-signed token.

    """
    import jwt  # noqa: PLC0415 - the encoder, not the class under test

    keypair = ensure_keypair()
    return jwt.encode(
        claims,
        keys_module.load_private_key(keypair),
        algorithm=keys_module.SIGNING_ALGORITHM,
        headers={"kid": jwt.get_unverified_header(token)["kid"]},
    )


def registered_claims(settings: SettingsWrapper, **overrides: object) -> dict[str, object]:
    """Build the claims `mint_token` builds, so a case can vary exactly one of them.

    Args:
        settings: The settings wrapper, read for the issuer and audience in force.
        **overrides: Claims to replace. A `None` value removes the claim outright,
            which is how the missing-`jti` case is expressed.

    Returns:
        The payload.

    """
    issued_at = datetime.now(tz=UTC)
    claims: dict[str, object] = {
        **build_claims(get_persona(PERSONA_KEY)),
        "iss": settings.OIDC_ISSUER,
        "aud": settings.OIDC_AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=900),
        "jti": uuid.uuid4().hex,
    }
    return {name: value for name, value in {**claims, **overrides}.items() if value is not None}


@pytest.mark.usefixtures("_local_flow")
def test_minted_token_authenticates_through_the_real_class(client: Client, route: str) -> None:
    """AC #1 and #2: the whole flow, with the real class doing the whole verification."""
    provision_designated_groups()
    persona = get_persona(PERSONA_KEY)

    response = client.get(route, headers=bearer(mint_token(PERSONA_KEY)))

    assert response.status_code == HTTPStatus.OK
    # The identity the mapper resolved, not merely "some 200": a class that
    # authenticated the wrong principal would pass a status-only assertion.
    assert User.objects.get(idp_subject=persona.subject).username == response.json()["username"]


@pytest.mark.usefixtures("_local_flow")
def test_the_minted_token_carries_the_issuer_and_audience_in_force(settings: SettingsWrapper) -> None:
    """`mint_token` reads the settings the class verifies against, never a literal.

    The two constants above are deliberately not the values
    `config/settings/local.py` fills in, so this assertion fails if the mint ever
    writes its own issuer or audience -- which would work perfectly on a fresh
    clone and refuse every token the moment a developer pointed a local run at a
    real realm.
    """
    import jwt  # noqa: PLC0415 - the decoder, used here only to read what was minted

    minted = jwt.decode(mint_token(PERSONA_KEY), options={"verify_signature": False})

    assert minted["iss"] == settings.OIDC_ISSUER == ISSUER
    assert minted["aud"] == settings.OIDC_AUDIENCE == AUDIENCE


@pytest.mark.usefixtures("_local_flow")
def test_a_padded_audience_still_mints_a_token_that_verifies(
    client: Client,
    route: str,
    settings: SettingsWrapper,
) -> None:
    """The mint matches each reader's shape, not merely its value.

    `authentication._audience()` strips before comparing, so an audience carrying
    a trailing space -- exported that way, or left by an editor in an `.env` --
    minted into `aud` as written would be compared against its own stripped self
    and refused. The two strings look identical in a log line, which is what
    makes the 401 undiagnosable rather than merely wrong.
    """
    provision_designated_groups()
    settings.OIDC_AUDIENCE = f"  {AUDIENCE}  "

    response = client.get(route, headers=bearer(mint_token(PERSONA_KEY)))

    assert response.status_code == HTTPStatus.OK


@pytest.mark.usefixtures("_local_flow")
def test_a_blank_jti_is_treated_as_absent_rather_than_minted(client: Client, route: str) -> None:
    """An explicitly blank `jti` is a caller's mistake, not a credential identifier.

    The mapper's epoch gate refuses anything empty with `token carries no jti`, so
    carrying a blank one through would produce a token that cannot authenticate
    and a 401 whose cause is an argument the caller believed they had supplied.
    """
    provision_designated_groups()

    response = client.get(route, headers=bearer(mint_token(PERSONA_KEY, jti="   ")))

    assert response.status_code == HTTPStatus.OK


@pytest.mark.usefixtures("_local_flow")
def test_the_key_is_read_from_the_file_location_rather_than_the_network(
    client: Client,
    route: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retrieval under test is the local file read, and nothing here stubbed it.

    Two assertions, because the docstring makes two claims. Nothing reaches the
    network: `requests.get` is replaced with something that fails this test if it
    is ever called, which is what would happen if the `file` branch fell through
    to `_fetched_document`. And the second request is served from the `kid`-keyed
    cache the first populated: the document is deleted between them, so a second
    read of the file could not succeed, and a 200 can only come from the cache.
    """
    provision_designated_groups()

    def refuse_to_reach_the_network(*arguments: object, **keywords: object) -> object:
        message = f"the file branch reached the network: requests.get{arguments!r}"
        raise AssertionError(message)

    monkeypatch.setattr(jwks_module.requests, "get", refuse_to_reach_the_network)

    first = client.get(route, headers=bearer(mint_token(PERSONA_KEY)))
    token = mint_token(PERSONA_KEY)
    ensure_keypair().jwks_path.unlink()
    second = client.get(route, headers=bearer(token))

    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK


@pytest.mark.usefixtures("_local_flow")
def test_tampered_signature_is_rejected(client: Client, route: str) -> None:
    """AC #3: the signature is genuinely checked against the published key."""
    provision_designated_groups()
    header, payload, signature = mint_token(PERSONA_KEY).split(".")
    # Flip a *bit of the decoded signature* rather than a character of its
    # encoding. Truncating would be refused by the decoder's shape check, proving
    # nothing about the signature -- and editing the last base64 character proves
    # nothing either: it carries only the padding bits of the final byte, so
    # several distinct characters decode to the same 256 bytes and the token
    # stays valid. Asserted here as a bit flip so the case cannot pass by
    # accident of what the encoding happened to end in.
    raw = bytearray(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
    raw[0] ^= 0xFF
    corrupted = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode("ascii")

    response = client.get(route, headers=bearer(f"{header}.{payload}.{corrupted}"))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.usefixtures("_local_flow")
def test_tampered_payload_is_rejected(client: Client, route: str) -> None:
    """The escalation case: an added group claim under the original signature."""
    provision_designated_groups()
    header, payload, signature = mint_token(PERSONA_KEY).split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    decoded["groups"] = [*decoded.get("groups", []), "platform-superuser"]
    forged = base64.urlsafe_b64encode(json.dumps(decoded).encode("utf-8")).rstrip(b"=").decode("ascii")

    response = client.get(route, headers=bearer(f"{header}.{forged}.{signature}"))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.usefixtures("_local_flow")
def test_expired_token_is_rejected(client: Client, route: str) -> None:
    """AC #3: `exp` is verified, and a negative lifetime is how that is shown without waiting."""
    provision_designated_groups()

    response = client.get(route, headers=bearer(mint_token(PERSONA_KEY, lifetime_seconds=-60)))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.usefixtures("_local_flow")
def test_wrong_issuer_is_rejected(client: Client, route: str, settings: SettingsWrapper) -> None:
    """AC #2: `iss` is verified. Correctly signed, published `kid`, wrong issuer."""
    provision_designated_groups()
    claims = registered_claims(settings, iss="https://another-idp.invalid/realms/main")

    response = client.get(route, headers=bearer(resign(mint_token(PERSONA_KEY), claims)))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.usefixtures("_local_flow")
def test_wrong_audience_is_rejected(client: Client, route: str, settings: SettingsWrapper) -> None:
    """AC #2: `aud` is verified. Without this, `options={"verify_aud": False}` passes everything else here."""
    provision_designated_groups()
    claims = registered_claims(settings, aud="somebody-elses-api")

    response = client.get(route, headers=bearer(resign(mint_token(PERSONA_KEY), claims)))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.usefixtures("_local_flow")
def test_unknown_kid_is_rejected(client: Client, route: str, settings: SettingsWrapper) -> None:
    """A second keypair the local document never published buys nothing."""
    provision_designated_groups()
    impostor = generate(UNPUBLISHED_KID)

    response = client.get(route, headers=bearer(impostor.sign(registered_claims(settings))))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.usefixtures("_local_flow")
def test_token_without_jti_is_rejected(client: Client, route: str, settings: SettingsWrapper) -> None:
    """AD-10, raised by the mapper's epoch gate rather than by the authentication class."""
    provision_designated_groups()
    claims = registered_claims(settings, jti=None)

    response = client.get(route, headers=bearer(resign(mint_token(PERSONA_KEY), claims)))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.usefixtures("_local_flow")
def test_the_entry_point_mints_a_token_that_authenticates(client: Client, route: str) -> None:
    """`python -m config.local_dev.mint <persona>` is the runnable form, and it runs.

    Called as a function rather than as a subprocess, for the reason
    `tests/integration/test_local_dev_seeding.py` gives about its own entry
    point: a subprocess would resolve a different pixi environment and a
    different database, and what is worth pinning is that `main` sets Django up
    and drives the same minting the task promises.
    """
    provision_designated_groups()

    token = mint.main([PERSONA_KEY])

    assert client.get(route, headers=bearer(token)).status_code == HTTPStatus.OK


def test_the_entry_point_refuses_a_run_with_no_persona() -> None:
    """An omitted argument is a typing mistake and answers with a usage line, not a traceback."""
    with pytest.raises(SystemExit, match="mint-token"):
        mint.main([])


@pytest.mark.usefixtures("_local_flow")
def test_the_entry_point_refuses_a_deployed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The entry point adds no escape hatch of its own around the refusal."""
    from django.core.exceptions import ImproperlyConfigured  # noqa: PLC0415 - one case needs it

    from config.locality import RUNTIME_ENV_VAR  # noqa: PLC0415 - see above

    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")

    with pytest.raises(ImproperlyConfigured, match=RUNTIME_ENV_VAR):
        mint.main([PERSONA_KEY])


def test_a_deployed_run_mints_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-13 fails closed, and *nothing is written* -- not merely nothing returned.

    Deliberately outside `_local_flow`, which generates a keypair before a case
    body runs. Under that fixture a key already exists on disk, so the "mints
    nothing" half of the claim is unobservable: moving the `is_local()` gate below
    `ensure_keypair()` would generate a keypair in a deployed run, still raise,
    and leave the case green. Starting from a directory that does not exist is
    what makes the absence afterwards mean something.
    """
    from django.core.exceptions import ImproperlyConfigured  # noqa: PLC0415 - one case needs it

    from config.locality import RUNTIME_ENV_VAR  # noqa: PLC0415 - see above

    key_dir = tmp_path / ".local-dev-keys"
    monkeypatch.setattr(keys_module, "DEV_KEY_DIR", key_dir)
    monkeypatch.delenv(RUNTIME_ENV_VAR, raising=False)

    with pytest.raises(ImproperlyConfigured, match=RUNTIME_ENV_VAR):
        mint_token(PERSONA_KEY)

    assert not key_dir.exists()


@pytest.mark.usefixtures("_local_flow")
def test_two_tokens_sharing_a_jti_are_one_credential_epoch(client: Client, route: str) -> None:
    """AD-10 through the `jti` parameter: the same credential syncs once, not twice.

    The parameter exists to make this observable, and nothing else passes it. A
    second token bearing a `jti` already recorded is the *same* credential
    re-presented, so the mapper's epoch gate authorizes it without a second sync
    and no second row appears.
    """
    provision_designated_groups()
    persona = get_persona(PERSONA_KEY)
    shared = uuid.uuid4().hex

    first = client.get(route, headers=bearer(mint_token(PERSONA_KEY, jti=shared)))
    second = client.get(route, headers=bearer(mint_token(PERSONA_KEY, jti=shared)))

    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    user = User.objects.get(idp_subject=persona.subject)
    # One row, not two: `unique=True` on `jti` makes first-sighting a database
    # guarantee, and the second presentation is the same credential rather than a
    # new one.
    assert list(CredentialEpoch.objects.filter(user=user).values_list("jti", flat=True)) == [shared]


@pytest.mark.usefixtures("_local_flow")
def test_the_entry_point_emits_the_token_it_minted(client: Client, route: str) -> None:
    """The log event is the *only* channel the token reaches a developer through.

    `print` is banned project-wide, so `pixi run -e dev mint-token` delivers its
    result as `local_dev.minting_complete` and nothing else. Deleting that line
    would break the task for every developer while leaving every other case in
    this file green, because they all read `main`'s return value instead.
    """
    provision_designated_groups()

    with structlog.testing.capture_logs() as captured:
        token = mint.main([PERSONA_KEY])

    emitted = [entry for entry in captured if entry["event"] == "local_dev.minting_complete"]
    assert [entry["token"] for entry in emitted] == [token]


def test_the_entry_point_refuses_an_unknown_persona() -> None:
    """A mistyped key answers with the declared keys, not a `LookupError` traceback."""
    with pytest.raises(SystemExit, match=PERSONA_KEY):
        mint.main(["stff"])
