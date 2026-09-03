"""The Bearer class's configuration readers, exercised without a request or a database.

`tests/integration/authorization/test_bearer_authentication.py` drives the class
through a real DRF request cycle and is where every verdict about a token is
pinned. What lives here is the narrow band the integration suite cannot see: the
helpers that turn a `settings` value into the arguments `jwt.decode` is called
with. Each one has a shape of configuration that is accepted today and silently
refuses every token, which is a failure mode no test that only ever supplies
well-formed settings can catch.

None of these touch the network, the database or the key store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import jwt
import pytest
import structlog

from config.authorization.authentication import OIDCBearerAuthentication
from config.authorization.authentication import _algorithms
from config.authorization.authentication import _audience
from config.authorization.authentication import _leeway
from config.authorization.authentication import _refused

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

DEFAULT_ALGORITHMS = ("RS256",)

# The bound a logged `kid` is truncated to, written as a literal rather than
# imported from the module that declares it: a test comparing against the
# constant it is meant to pin moves with the code and detects no drift.
MAX_LOGGED_KID = 64

# Material for a token nothing ever verifies. These cases read the *unverified*
# header, which is the whole point -- the `kid` is attacker-supplied and is read
# before anything about the token has been established.
UNVERIFIED_MATERIAL = "material no deployment would ever hold"

# The shipped clock-skew posture. Zero, and the lever exists so that it can be
# raised deliberately rather than so that it is.
DEFAULT_LEEWAY_SECONDS = 0.0


def test_a_configured_allowlist_is_taken_as_it_stands(settings: SettingsWrapper) -> None:
    settings.OIDC_ALGORITHMS = ["RS256", "ES256"]

    assert _algorithms() == ("RS256", "ES256")


def test_a_bare_string_allowlist_is_one_algorithm_and_not_five_characters(settings: SettingsWrapper) -> None:
    """`tuple("RS256")` is `('R', 'S', '2', '5', '6')`, and every token is then refused.

    `COMPONENT_OIDC_ALGORITHMS` is read by `env.list`, so the environment path
    always produces a list -- but a settings override, a test, or a downstream
    component's own settings module can perfectly reasonably assign the string.
    The failure it produces is an `InvalidAlgorithmError` on every request, which
    names nothing an operator can act on.
    """
    settings.OIDC_ALGORITHMS = "RS256"

    assert _algorithms() == ("RS256",)


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param(["RS256", "", "  "], id="empty-and-blank-entries"),
        pytest.param([" RS256 "], id="padded-entry"),
    ],
)
def test_blank_and_padded_entries_are_cleaned_rather_than_passed_through(
    settings: SettingsWrapper,
    configured: list[str],
) -> None:
    """A trailing comma in the environment variable must not become an unnamed algorithm."""
    settings.OIDC_ALGORITHMS = configured

    assert _algorithms() == ("RS256",)


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param(None, id="unset"),
        pytest.param([], id="empty-list"),
        pytest.param(["", "   "], id="nothing-but-blanks"),
    ],
)
def test_an_allowlist_that_names_nothing_falls_back_to_the_default(
    settings: SettingsWrapper,
    configured: list[str] | None,
) -> None:
    """An empty `algorithms` is an error inside PyJWT rather than a refusal here."""
    settings.OIDC_ALGORITHMS = configured

    assert _algorithms() == DEFAULT_ALGORITHMS


def test_a_whitespace_only_audience_reads_as_unconfigured(settings: SettingsWrapper) -> None:
    """A padded value is truthy, so it looks configured while refusing every token.

    `aud` is a required claim on this path, so an audience of `" "` is compared
    literally against what the IdP minted and never matches -- an outage that
    presents as "every API call is 401" with a settings file that looks correct.
    """
    settings.OIDC_AUDIENCE = "   "

    assert _audience() == ""


def test_a_padded_audience_is_compared_stripped(settings: SettingsWrapper) -> None:
    settings.OIDC_AUDIENCE = "  component-api  "

    assert _audience() == "component-api"


def test_the_shipped_clock_skew_tolerance_is_zero(settings: SettingsWrapper) -> None:
    """The lever is added; the default posture is not moved.

    Anything above zero accepts a token for that many seconds past its own `exp`,
    so the default has to be the strict one -- a lever that ships pre-pulled is a
    policy change wearing a configuration option's clothes.
    """
    del settings.OIDC_LEEWAY_SECONDS

    assert _leeway() == DEFAULT_LEEWAY_SECONDS


def test_a_configured_tolerance_is_read(settings: SettingsWrapper) -> None:
    settings.OIDC_LEEWAY_SECONDS = 5.0

    assert _leeway() == 5.0  # noqa: PLR2004 - the value under test, not a magic number


def _unverified_token(kid: str) -> str:
    """Mint a token whose header carries a given `kid` and whose signature is never checked.

    Args:
        kid: The identifier to advertise.

    Returns:
        The encoded token.

    """
    return jwt.encode({"sub": "urn:example:principal:header-probe"}, UNVERIFIED_MATERIAL, headers={"kid": kid})


def test_a_padded_kid_is_read_stripped() -> None:
    """An unstripped `kid` never matches the cache, so it refetches once per window forever.

    The validation already reads `kid.strip()`, so a padded value passes it and
    is then looked up under its padded form -- which the key store has never held
    and never will, because the IdP publishes the trimmed identifier. Every such
    request misses the cache and provokes a refetch attempt: the amplification
    the rate limit bounds, reached by a route the rate limit's own test does not
    cover.
    """
    kid = OIDCBearerAuthentication()._kid(_unverified_token("  primary-2026  "))  # noqa: SLF001 - the helper under test

    assert kid == "primary-2026"


def test_an_over_long_kid_is_truncated_before_it_reaches_the_log() -> None:
    """The `kid` is attacker-supplied, unbounded, and written on an unauthenticated path.

    The mapper next door refuses an over-long identity key for exactly this
    reason. Here it is truncated rather than refused -- it is a log field and not
    a value anything is decided on -- but a caller must not get to choose how
    many bytes each refusal event writes, because they can cause one at will.
    """
    with structlog.testing.capture_logs() as captured:
        _refused("a reason", kid="k" * (MAX_LOGGED_KID * 8))

    logged = [event for event in captured if event["event"] == "authorization.bearer_rejected"]
    assert len(logged) == 1
    assert logged[0]["kid"] == "k" * MAX_LOGGED_KID


def test_an_absent_kid_is_logged_as_absent_rather_than_as_an_empty_string() -> None:
    """`None` and `""` are different facts: no header at all versus a header declaring nothing."""
    with structlog.testing.capture_logs() as captured:
        _refused("a reason", kid=None)

    assert captured[0]["kid"] is None
