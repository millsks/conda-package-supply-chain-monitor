"""Tests for the parts of the mapper's sync path that need no database.

Everything here is a claim-shape refusal or a pure reading. Both refusals happen
*before* any query -- an absent group claim is rejected before the `Group` lookup
and an unusable `jti` before the epoch insert -- which is exactly why they are
observable without a connection.

The behavioural half -- that memberships are added and removed, that `is_staff`
and `is_superuser` track their designated groups, that a `jti` syncs once and
never again -- lives in `tests/integration/authorization/test_mapper_sync.py`,
because none of it can be shown without rows.

`User()` is constructed rather than created throughout. Instantiating a model
opens no connection, and the refusals under test raise before the instance is
read from at all.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog

from config.authorization.claims import ClaimsContract
from config.authorization.exceptions import ClaimsRejected
from config.authorization.mapper import EXPIRY_CLAIM
from config.authorization.mapper import JTI_CLAIM
from config.authorization.mapper import SyncOutcome
from config.authorization.mapper import _expires_at
from config.authorization.mapper import _reject_an_unstorable_jti
from config.authorization.mapper import sync_authorization
from config.authorization.mapper import sync_once_per_epoch
from django_service.users.models import CredentialEpoch
from django_service.users.models import User

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

# Names that look nothing like `sub`, `groups`, `staff` or `superuser`, so a test
# passing on them cannot be passing on a conventional name hardcoded in the
# mapper.
IDENTITY_CLAIM = "urn:example:principal-id"
GROUP_CLAIM = "realm_access.roles"
STAFF_GROUP = "shipping-desk-operators"
SUPERUSER_GROUP = "shipping-desk-owners"

# A `jti` one character past what the epoch column can hold.
JTI_MAX_LENGTH = CredentialEpoch._meta.get_field("jti").max_length  # noqa: SLF001 - `Model._meta` is Django's documented field API
assert JTI_MAX_LENGTH is not None, "CredentialEpoch.jti must declare a max_length for this module to assert anything"

# 2026-08-17T00:00:00Z, as a token would carry it: seconds since the epoch.
AN_EXPIRY = 1786924800


@pytest.fixture
def contract(settings: SettingsWrapper) -> ClaimsContract:
    """Point the claims contract at deliberately unconventional names."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )
    return settings.CLAIMS_CONTRACT


# ---------------------------------------------------------------------------
# AC #7 -- a token lacking the configured group claim is refused, never
# authenticated with zero groups.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({}, id="no-claims-at-all"),
        pytest.param({"groups": ["a"]}, id="groups-under-a-different-name"),
        pytest.param({"realm_access": {}}, id="path-half-present"),
        pytest.param({"realm_access": {"roles": None}}, id="claim-null"),
        pytest.param({"realm_access": {"roles": {"name": "a"}}}, id="claim-an-object"),
        pytest.param({"realm_access": {"roles": [{"name": "a"}]}}, id="an-element-is-an-object"),
        pytest.param({"realm_access": {"roles": ["a", None]}}, id="an-element-is-null"),
    ],
)
def test_claims_without_a_readable_group_claim_are_refused(
    contract: ClaimsContract,
    claims: dict[str, Any],
) -> None:
    """AD-12: a 401, never an authentication with zero groups.

    The two are indistinguishable on the row afterwards, which is how a
    misconfigured claim name presents as a permissions bug instead of as a
    configuration error. `groups-under-a-different-name` is the load-bearing
    case: a claim set that carries groups a mapper reading a hardcoded name
    would have found must still be refused, because the contract does not name
    it.

    No database is touched -- the refusal happens before the `Group` lookup,
    which is why this case belongs in the unit suite.
    """
    with pytest.raises(ClaimsRejected) as refusal:
        sync_authorization(User(), claims)

    assert refusal.value.reason == "group claim absent"


def test_the_group_refusal_names_the_claim_it_looked_for(contract: ClaimsContract) -> None:
    """The refusal is an event, not only an exception.

    AD-12's reason for refusing here is that a misconfigured claim *name* is
    indistinguishable from an identity with no groups once the request is over.
    A silent raise leaves the operator exactly where that argument says they
    must not be left: the configured name is the one thing they cannot infer
    from the 401.
    """
    with structlog.testing.capture_logs() as captured, pytest.raises(ClaimsRejected):
        sync_authorization(User(), {})

    events = [event for event in captured if event["event"] == "authorization.claims_rejected"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["reason"] == "group claim absent"
    assert events[0]["group_claim"] == GROUP_CLAIM


def test_the_group_refusal_reason_carries_no_claim_value(contract: ClaimsContract) -> None:
    """A refusal message naming the token's contents is the token leaking into the log."""
    claim_value = "urn:example:group:please-do-not-log-me"

    with pytest.raises(ClaimsRejected) as refusal:
        sync_authorization(User(), {"some-other-claim": claim_value})

    assert claim_value not in refusal.value.reason
    assert claim_value not in str(refusal.value)


# ---------------------------------------------------------------------------
# AC #4 -- a Bearer token with no `jti` is rejected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({}, id="absent"),
        pytest.param({JTI_CLAIM: ""}, id="empty"),
        pytest.param({JTI_CLAIM: "   "}, id="whitespace-only"),
        pytest.param({JTI_CLAIM: None}, id="null"),
        pytest.param({JTI_CLAIM: True}, id="boolean"),
        pytest.param({JTI_CLAIM: ["j1"]}, id="list"),
        pytest.param({JTI_CLAIM: {"id": "j1"}}, id="object"),
    ],
)
def test_a_credential_with_no_usable_jti_is_refused(claims: dict[str, Any]) -> None:
    """AD-10: without this rule the epoch gate has no key.

    One builder would then sync on every request and another never again --
    exactly the two outcomes AD-10 exists to prevent. The rule lives in the
    mapper; Story 2.7's DRF class is what turns the refusal into the 401.

    No database is touched: the refusal precedes the epoch insert.
    """
    with pytest.raises(ClaimsRejected) as refusal:
        sync_once_per_epoch(User(), claims)

    assert refusal.value.reason == "token carries no jti"


def test_the_missing_jti_refusal_is_reported() -> None:
    """Nothing is swallowed silently, refusals included.

    Reported under the same event name the over-long `jti` uses, so an operator
    reading the log finds every credential the epoch gate turned away in one
    place, told apart by `reason` rather than by which line raised.
    """
    with structlog.testing.capture_logs() as captured, pytest.raises(ClaimsRejected):
        sync_once_per_epoch(User(), {})

    events = [event for event in captured if event["event"] == "authorization.jti_rejected"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["reason"] == "token carries no jti"


def test_a_jti_longer_than_the_epoch_column_is_refused_before_the_insert() -> None:
    """A credential that cannot be recorded is a refusal, not a `DataError`.

    Truncating instead would make two distinct credentials sharing a prefix
    share one epoch, so the second would never sync -- the stale-authorization
    half of what AD-10 prevents, reintroduced by a silent string slice. SQLite
    stores the over-long value and says nothing; PostgreSQL answers with a
    `DataError` in the middle of an authentication.
    """
    over_long = "j" * (JTI_MAX_LENGTH + 1)

    with pytest.raises(ClaimsRejected) as refusal:
        sync_once_per_epoch(User(), {JTI_CLAIM: over_long})

    assert refusal.value.reason == "jti longer than the epoch field"
    assert over_long not in refusal.value.reason


def test_a_jti_exactly_the_column_length_is_storable() -> None:
    """The bound is inclusive: an off-by-one here would refuse a storable credential.

    The check is called directly rather than through `sync_once_per_epoch`, which
    would go on to the epoch insert and therefore to a database this suite does
    not have.
    """
    _reject_an_unstorable_jti("j" * JTI_MAX_LENGTH)


# ---------------------------------------------------------------------------
# `exp` -- the column AD-31's pruner will scan, read from the token.
# ---------------------------------------------------------------------------


def test_a_numeric_expiry_claim_is_read_as_an_aware_utc_moment() -> None:
    """Aware, not naive: `USE_TZ` is on, and a naive datetime would be stored guessed."""
    read = _expires_at({EXPIRY_CLAIM: AN_EXPIRY})

    assert read == datetime.fromtimestamp(AN_EXPIRY, tz=UTC)
    assert read is not None
    assert read.tzinfo is not None


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({}, id="absent"),
        pytest.param({EXPIRY_CLAIM: None}, id="null"),
        pytest.param({EXPIRY_CLAIM: True}, id="boolean"),
        pytest.param({EXPIRY_CLAIM: "1786924800"}, id="string"),
        pytest.param({EXPIRY_CLAIM: 10**30}, id="unrepresentable"),
    ],
)
def test_an_unreadable_expiry_claim_yields_no_expiry(claims: dict[str, Any]) -> None:
    """No invented expiry: a row with none is simply not prunable by expiry.

    That is the safe reading. An epoch row pruned too early re-syncs a
    credential; one pruned too late costs a row. `True` is excluded explicitly
    because `bool` is an `int` subclass and `1970-01-01T00:00:01Z` is not an
    expiry anybody asserted.
    """
    assert _expires_at(claims) is None


def test_an_expiry_the_platform_cannot_represent_is_reported() -> None:
    """Handled and reported, never swallowed -- this is the reporting half.

    The authentication proceeds -- an unreadable `exp` is not grounds to refuse
    a token whose signature and other claims are good -- so the only trace the
    row leaves is that it is unprunable by expiry. Without the event, an
    operator watching the table's size has nothing to find. The absent, null,
    boolean and string cases above never reach the conversion at all, so this is
    the one value that drives it.
    """
    with structlog.testing.capture_logs() as captured:
        assert _expires_at({EXPIRY_CLAIM: 10**30}) is None

    events = [event for event in captured if event["event"] == "authorization.unreadable_expiry_claim"]
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"


# ---------------------------------------------------------------------------
# The outcome type the callers read.
# ---------------------------------------------------------------------------


def test_the_sync_outcome_defaults_to_a_sync_that_changed_nothing() -> None:
    """Frozen and defaulted, so a caller constructing one cannot leave a flag unset."""
    outcome = SyncOutcome()

    assert outcome == SyncOutcome(added=(), removed=(), ignored=(), is_staff=False, is_superuser=False)
    with pytest.raises(AttributeError):
        outcome.is_staff = True  # type: ignore[misc]
