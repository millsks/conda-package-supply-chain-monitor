"""Tests for the parts of the mapper's resolve path that need no database.

Everything here is pure: a mapping of claims in, a name or a refusal out. The
database-backed half -- that resolution is by the identity key alone, that the
same identity resolves to one user through either flow, and that the hit path is
a single read -- lives in `tests/integration/authorization/test_mapper_resolve.py`,
because none of it can be shown without rows.

`resolve_user` is reachable from here for the two refusals that happen *before*
the query -- an unreadable identity key and one too long to store -- so both are
observable without a connection. Any other call would open one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator

from config.authorization.claims import ClaimsContract
from config.authorization.exceptions import ClaimsRejected
from config.authorization.mapper import EMAIL_CLAIM
from config.authorization.mapper import NAME_CLAIM
from config.authorization.mapper import USERNAME_CLAIM
from config.authorization.mapper import _attributes_from_claims
from config.authorization.mapper import _derived_username
from config.authorization.mapper import _reject_a_deactivated_user
from config.authorization.mapper import _reject_an_unstorable_identity_key
from config.authorization.mapper import _username_from_identity_key
from config.authorization.mapper import resolve_user

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

# A claim name that looks nothing like `sub`, so a test passing on it cannot be
# passing on a conventional name hardcoded in the mapper.
IDENTITY_CLAIM = "urn:example:principal-id"

# How many distinct identity keys the determinism check derives names for.
DERIVATION_SAMPLE = 500

# How far past a field's length the over-long cases reach. Any positive number
# works; a round one keeps the failure readable when an assertion prints it.
OVERSHOOT = 50


def field_length(field_name: str) -> int:
    """Read a bound from the user model's own field.

    Every length assertion below goes through this rather than through a literal
    or through the mapper's own constant. A test that restates 150 stops being
    true the moment `AUTH_USER_MODEL` is swapped, and a test that imports the
    constant the production code truncated with cannot detect drift at all --
    both sides would move together and the assertion would still pass.

    Args:
        field_name: The field's name on the user model.

    Returns:
        The field's `max_length`.

    """
    max_length = get_user_model()._meta.get_field(field_name).max_length  # noqa: SLF001 - `Model._meta` is Django's documented field API
    assert max_length is not None
    return int(max_length)


@pytest.fixture
def contract(settings: SettingsWrapper) -> ClaimsContract:
    """Point the claims contract at a deliberately unconventional identity claim."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim="realm_access.roles",
        staff_group="shipping-desk-operators",
        superuser_group="shipping-desk-owners",
    )
    return settings.CLAIMS_CONTRACT


# ---------------------------------------------------------------------------
# AC #1 -- an absent identity key is a refusal, not a lookup by something else.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({}, id="no-claims-at-all"),
        pytest.param({"email": "ada@example.com"}, id="email-present-identity-absent"),
        pytest.param({"preferred_username": "ada"}, id="username-present-identity-absent"),
        pytest.param({IDENTITY_CLAIM: ""}, id="identity-blank"),
        pytest.param({IDENTITY_CLAIM: "   "}, id="identity-whitespace-only"),
        pytest.param({IDENTITY_CLAIM: None}, id="identity-null"),
        pytest.param({IDENTITY_CLAIM: True}, id="identity-boolean"),
    ],
)
def test_claims_without_an_identity_key_are_refused(
    contract: ClaimsContract,
    claims: dict[str, Any],
) -> None:
    """AD-11: no email fallback, no username fallback -- a refusal instead.

    The email and username cases are the load-bearing ones. Both carry a claim
    that a mapper resolving by attribute could have used, and both must still be
    refused: "never resolved by" is absolute, so the presence of a usable-looking
    attribute changes nothing.

    No database is touched. The refusal happens before the query, which is why
    this case belongs in the unit suite at all.
    """
    with pytest.raises(ClaimsRejected) as refusal:
        resolve_user(claims)

    assert refusal.value.reason == "identity key claim absent"


def test_the_refusal_reason_carries_no_claim_value(contract: ClaimsContract) -> None:
    """A refusal message naming the token's contents is the token leaking into the log."""
    claim_value = "urn:example:principal:0e7b-please-do-not-log-me"

    with pytest.raises(ClaimsRejected) as refusal:
        resolve_user({"some-other-claim": claim_value})

    assert claim_value not in refusal.value.reason
    assert claim_value not in str(refusal.value)


def test_an_identity_key_longer_than_the_identity_field_is_refused(contract: ClaimsContract) -> None:
    """A key that cannot be stored is a refusal, not a `DataError` mid-authentication.

    SQLite ignores a varchar bound and PostgreSQL does not, so without this the
    gate is green and the deployment answers 500. Refused rather than truncated:
    a truncated identity key is a *different* identity, and two keys sharing a
    prefix would resolve to one user.

    No database is touched -- the refusal happens before the query, which is why
    this case belongs in the unit suite.
    """
    over_long = "u" * (field_length("idp_subject") + 1)

    with pytest.raises(ClaimsRejected) as refusal:
        resolve_user({IDENTITY_CLAIM: over_long})

    assert refusal.value.reason == "identity key longer than the identity field"
    assert over_long not in refusal.value.reason


def test_an_identity_key_exactly_the_field_length_is_storable() -> None:
    """The bound is inclusive: an off-by-one here would refuse a storable identity.

    The check is called directly rather than through `resolve_user`, which would
    go on to the query and therefore to a database this suite does not have.
    """
    _reject_an_unstorable_identity_key("u" * field_length("idp_subject"))


# ---------------------------------------------------------------------------
# AC #4 -- the derived username is deterministic, bounded and valid.
# ---------------------------------------------------------------------------


def test_the_derived_username_is_the_same_on_every_call() -> None:
    """AD-12: a random suffix or a counter would make AC #2's assertion flaky."""
    subject = "urn:example:principal:8f14e45fceea167a5a36dedd4bea2543"

    first = _derived_username(subject)

    assert all(_derived_username(subject) == first for _ in range(5))


def test_distinct_identity_keys_derive_distinct_usernames() -> None:
    """Collision-free, or the rule that produced it has merely moved the collision."""
    derived = {_derived_username(f"urn:example:principal:{index}") for index in range(DERIVATION_SAMPLE)}

    assert len(derived) == DERIVATION_SAMPLE


def test_the_derived_username_fits_the_field_and_the_validator() -> None:
    """A derived name that the database or the validator rejects is not a fallback."""
    derived = _derived_username("urn:example:principal:" + "x" * 500)

    assert len(derived) <= field_length("username")
    UnicodeUsernameValidator()(derived)


def test_the_derived_username_does_not_reproduce_the_identity_key() -> None:
    """A digest, not a rendering: the subject does not end up displayed in the admin."""
    subject = "urn:example:principal:0e7b"

    assert subject not in _derived_username(subject)


# ---------------------------------------------------------------------------
# AC #1 / AC #4 -- attribute reading and the identity-key fallback name.
# ---------------------------------------------------------------------------


def test_the_three_attribute_claims_are_read_from_their_standard_names() -> None:
    attributes = _attributes_from_claims(
        {
            USERNAME_CLAIM: "  ada  ",
            EMAIL_CLAIM: " ada@example.com ",
            NAME_CLAIM: " Ada Lovelace ",
        },
        "urn:example:principal:A",
    )

    assert attributes == {
        "username": "ada",
        "email": "ada@example.com",
        "name": "Ada Lovelace",
    }


def test_an_absent_preferred_username_falls_back_to_the_identity_key() -> None:
    attributes = _attributes_from_claims({}, "principal-A")

    assert attributes["username"] == "principal-A"
    assert attributes["email"] == ""
    assert attributes["name"] == ""


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param(["ada"], id="list"),
        pytest.param({"name": "ada"}, id="object"),
        pytest.param(7, id="integer"),
    ],
)
def test_an_unusable_attribute_claim_is_not_coerced(value: Any) -> None:
    """A `str()` of a dict would land in the admin and in URLs as a display name."""
    attributes = _attributes_from_claims(
        {USERNAME_CLAIM: value, EMAIL_CLAIM: value, NAME_CLAIM: value},
        "principal-A",
    )

    assert attributes["email"] == ""
    assert attributes["name"] == ""
    # The username has a fallback, so it is the identity key rather than blank.
    assert attributes["username"] == "principal-A"


@pytest.mark.parametrize(
    ("claimed", "expected"),
    [
        pytest.param("ada/lovelace", "ada-lovelace", id="path-separator"),
        pytest.param("ada lovelace", "ada-lovelace", id="space"),
        pytest.param("ada?next=/admin", "ada-next--admin", id="query-string"),
        pytest.param("../../etc/passwd", "..-..-etc-passwd", id="traversal"),
        pytest.param("・・・", "", id="nothing-usable-at-all"),
    ],
)
def test_a_preferred_username_claim_is_sanitized_like_the_fallback(claimed: str, expected: str) -> None:
    """The claim gets the same rendering the identity-key fallback always got.

    A `preferred_username` is attacker-influenced input and was reaching
    `user.username` verbatim, which is two defects at once: the stored name fails
    `UnicodeUsernameValidator`, and `users:detail` is `<str:username>`, whose
    converter matches no `/` -- so `get_absolute_url()` raised `NoReverseMatch`
    for a user the mapper had just created.
    """
    attributes = _attributes_from_claims({USERNAME_CLAIM: claimed}, "principal-A")

    if expected:
        assert attributes["username"] == expected
        UnicodeUsernameValidator()(attributes["username"])
    else:
        # Nothing usable survived, so the claim is treated exactly as an absent
        # one and the identity key supplies the name.
        assert attributes["username"] == "principal-A"


@pytest.mark.parametrize(
    ("claim", "field"),
    [
        pytest.param(USERNAME_CLAIM, "username", id="username"),
        pytest.param(EMAIL_CLAIM, "email", id="email"),
        pytest.param(NAME_CLAIM, "name", id="name"),
    ],
)
def test_an_over_long_attribute_claim_is_bounded_by_its_field(claim: str, field: str) -> None:
    """Everything claim-derived is bounded, not only the identity-key fallback.

    The asymmetry this closes: the fallback name was truncated and the three
    claims were not, so an IdP asserting a 300-character `email` reached
    PostgreSQL as a `DataError` in the middle of an authentication. SQLite --
    what the gate runs on -- stores it and says nothing.
    """
    limit = field_length(field)

    attributes = _attributes_from_claims({claim: "v" * (limit + OVERSHOOT)}, "principal-A")

    assert len(attributes[field]) == limit


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        pytest.param("ada", "ada", id="already-valid"),
        pytest.param("ada.lovelace@example.com", "ada.lovelace@example.com", id="email-shaped-subject"),
        pytest.param("auth0|5f3e", "auth0-5f3e", id="pipe-separated-subject"),
        pytest.param("urn:example:principal", "urn-example-principal", id="urn-subject"),
        pytest.param("Ada Lovelace", "Ada-Lovelace", id="spaces"),
    ],
)
def test_the_identity_key_renders_to_a_valid_username(subject: str, expected: str) -> None:
    """`auth0|...` and URN subjects are both common and both invalid as usernames."""
    rendered = _username_from_identity_key(subject)

    assert rendered == expected
    UnicodeUsernameValidator()(rendered)


def test_a_long_identity_key_is_truncated_to_the_field() -> None:
    """`idp_subject` is longer than `username` in this model; the difference is real."""
    rendered = _username_from_identity_key("a" * field_length("idp_subject"))

    assert len(rendered) == field_length("username")


def test_an_identity_key_with_nothing_usable_falls_through_to_the_digest() -> None:
    """`or` on the rendered name, not an unguarded slice: an empty username is not a name."""
    subject = "・・・"

    rendered = _username_from_identity_key(subject)

    assert rendered == _derived_username(subject)


# ---------------------------------------------------------------------------
# AC #7 (Story 2.7) -- the deactivation refusal, without a database.
# ---------------------------------------------------------------------------


def test_a_deactivated_row_is_refused_with_its_own_reason() -> None:
    """A resolved row must also be active to be returned.

    The check is called directly rather than through `resolve_user`, which would
    go on to the query and therefore to a database this suite does not have --
    the same shape `test_an_identity_key_exactly_the_field_length_is_storable`
    already uses. The database-backed half, that the refusal fires for a row the
    identity key actually resolved to, lives in
    `tests/integration/authorization/test_mapper_resolve.py`.
    """
    with pytest.raises(ClaimsRejected) as refusal:
        _reject_a_deactivated_user(get_user_model()(username="retired", is_active=False))

    assert refusal.value.reason == "resolved user is deactivated"
    assert "deactivated" in refusal.value.reason


def test_an_active_row_passes_the_check_untouched() -> None:
    """The control: the check is one line and it must not refuse anybody else."""
    _reject_a_deactivated_user(get_user_model()(username="still-here", is_active=True))


def test_the_deactivation_reason_is_not_shared_with_any_claim_refusal() -> None:
    """A deactivated user's claims are valid; naming a claim refusal would misreport it."""
    with pytest.raises(ClaimsRejected) as refusal:
        _reject_a_deactivated_user(get_user_model()(username="retired", is_active=False))

    assert refusal.value.reason not in {
        "identity key claim absent",
        "identity key longer than the identity field",
        "no username available for the identity key",
        "group claim absent",
        "token carries no jti",
    }
