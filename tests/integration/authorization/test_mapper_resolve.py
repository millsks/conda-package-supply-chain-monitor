"""Resolution against a real database.

What the unit tests cannot show: that resolution is by the identity key and by
nothing else, that one identity seen through two flows is one user, that two
identities sharing an email are two users, that a username collision is refused
rather than reaching the database as an `IntegrityError`, and that the hit path
is a single read.

Every test here rolls back. `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the state as found; `transaction=True` would truncate the
tables the group-provisioning migration seeded and is not needed by anything
below.

The claims contract is pointed at a deliberately unconventional identity claim
in every test, through the `settings` fixture rather than the environment: the
contract is already materialised into settings by the time a test runs, and a
test that passed on `sub` would not distinguish "reads the contract" from "reads
a conventional name the mapper hardcoded".
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog
from django.contrib.auth import get_user_model
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db.models import Q

from config.authorization import mapper
from config.authorization.claims import ClaimsContract
from config.authorization.exceptions import ClaimsRejected
from config.authorization.mapper import _available_username
from config.authorization.mapper import _derived_username
from config.authorization.mapper import _username_from_identity_key
from config.authorization.mapper import resolve_user
from tests.factories import UserFactory

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

    from django_service.users.models import User

# Nothing here is `sub`, `groups`, `staff` or `superuser`.
IDENTITY_CLAIM = "urn:example:principal-id"
GROUP_CLAIM = "realm_access.roles"
STAFF_GROUP = "shipping-desk-operators"
SUPERUSER_GROUP = "shipping-desk-owners"

SUBJECT_A = "urn:example:principal:A"
SUBJECT_B = "urn:example:principal:B"
# A key that renders to a username on its own, which is what makes it the right
# subject for the "every other candidate is held" cases below.
SUBJECT_S3 = "S3"

SHARED_EMAIL = "ada@example.com"

# Two identity keys means two rows, in every assertion below that counts them.
TWO_USERS = 2

# How far past a field's length the over-long cases reach.
OVERSHOOT = 50


def field_length(field_name: str) -> int:
    """Read a bound from the user model's own field, never from the mapper's constant.

    Args:
        field_name: The field's name on the user model.

    Returns:
        The field's `max_length`.

    """
    max_length = get_user_model()._meta.get_field(field_name).max_length  # noqa: SLF001 - `Model._meta` is Django's documented field API
    assert max_length is not None
    return int(max_length)


@pytest.fixture(autouse=True)
def _contract(settings: SettingsWrapper) -> None:
    """Point the claims contract at names that appear nowhere in the source."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )


def _claims(subject: str, **attributes: Any) -> dict[str, Any]:
    """Build a claim set carrying the identity key at the configured name."""
    return {IDENTITY_CLAIM: subject, **attributes}


def _events(captured: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """Select one event by name from a `capture_logs` recording."""
    return [event for event in captured if event["event"] == name]


def _collision_events(captured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the username-collision events from a `capture_logs` recording."""
    return _events(captured, "authorization.username_collision")


# ---------------------------------------------------------------------------
# AC #1 -- resolved by the identity key alone, never by email or username.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_new_identity_key_is_a_new_user_even_when_every_attribute_matches() -> None:
    """AD-11: an attribute that matches an existing row is not an identity.

    The arriving claims are indistinguishable from the seeded user on both of the
    attributes a resolver could be tempted to key on -- same `email`, same
    `preferred_username` -- and differ only in the identity key. A mapper with an
    email or username fallback returns the seeded user here; this one does not.
    """
    existing = UserFactory.create(username="ada", email=SHARED_EMAIL, idp_subject=SUBJECT_A)

    resolved = resolve_user(_claims(SUBJECT_B, preferred_username="ada", email=SHARED_EMAIL))

    assert resolved.pk != existing.pk
    assert resolved.idp_subject == SUBJECT_B
    assert get_user_model().objects.filter(Q(idp_subject=SUBJECT_A) | Q(idp_subject=SUBJECT_B)).count() == TWO_USERS


@pytest.mark.django_db
def test_a_row_with_no_identity_key_is_never_resolved_to() -> None:
    """Story 2.1 AC #3's nullable `idp_subject`: pre-existing rows are simply not resolvable.

    That is the intended behaviour rather than a gap to patch -- the row becomes
    resolvable when its own identity authenticates and claims it, not because
    somebody else's email matched.
    """
    legacy = UserFactory.create(username="ada", email=SHARED_EMAIL)
    assert legacy.idp_subject is None

    resolved = resolve_user(_claims(SUBJECT_A, preferred_username="ada", email=SHARED_EMAIL))

    assert resolved.pk != legacy.pk
    legacy.refresh_from_db()
    assert legacy.idp_subject is None


@pytest.mark.django_db
def test_a_created_user_carries_an_unusable_password() -> None:
    """A deployed component authenticates nobody locally, so there is no password to guess."""
    created = resolve_user(_claims(SUBJECT_A, preferred_username="ada", email=SHARED_EMAIL))

    assert created.has_usable_password() is False
    assert created.check_password("") is False


# ---------------------------------------------------------------------------
# AC #2 -- one identity, either flow, either order, one user.
# ---------------------------------------------------------------------------


# Two claim sets for the same identity, shaped the way each flow presents it: the
# interactive login carries the profile scope's attributes, the Bearer token
# typically carries fewer. Only the identity key is common to both, which is the
# point.
INTERACTIVE_CLAIMS: dict[str, Any] = {
    "preferred_username": "ada",
    "email": SHARED_EMAIL,
    "name": "Ada Lovelace",
}
BEARER_CLAIMS: dict[str, Any] = {"name": "A. Lovelace"}


@pytest.mark.django_db
def test_interactive_first_then_bearer_resolves_to_one_user() -> None:
    """AC #2, first order."""
    first = resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))
    second = resolve_user(_claims(SUBJECT_A, **BEARER_CLAIMS))

    assert second.pk == first.pk
    assert get_user_model().objects.filter(idp_subject=SUBJECT_A).count() == 1


@pytest.mark.django_db
def test_bearer_first_then_interactive_resolves_to_one_user() -> None:
    """AC #2, the reverse order.

    Written out rather than parameterised. The AC asks for both directions and a
    single parameterised case covering one of them would read as if it covered
    both -- and the orders are not symmetric: the first call creates the row and
    the second reads it, so which claim set does the creating differs.
    """
    first = resolve_user(_claims(SUBJECT_A, **BEARER_CLAIMS))
    second = resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    assert second.pk == first.pk
    assert get_user_model().objects.filter(idp_subject=SUBJECT_A).count() == 1


@pytest.mark.django_db
def test_the_same_identity_key_keeps_the_username_its_first_sighting_derived() -> None:
    """Deterministic, so the second flow's claims cannot rename the person mid-session."""
    first = resolve_user(_claims(SUBJECT_A, **BEARER_CLAIMS))
    username = first.username

    second = resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    assert second.username == username


# ---------------------------------------------------------------------------
# AC #3 -- colliding emails are two people.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_two_identities_sharing_an_email_resolve_to_two_users() -> None:
    """No branch does this: `email` carries no uniqueness constraint and is in no lookup.

    Both identities are given the same email *and* distinct `preferred_username`
    values, so the only thing that could have merged them is a lookup on `email`.
    """
    first = resolve_user(_claims(SUBJECT_A, preferred_username="ada", email=SHARED_EMAIL))
    second = resolve_user(_claims(SUBJECT_B, preferred_username="grace", email=SHARED_EMAIL))

    assert first.pk != second.pk
    assert first.email == second.email == SHARED_EMAIL
    assert get_user_model().objects.filter(email=SHARED_EMAIL).count() == TWO_USERS


# ---------------------------------------------------------------------------
# AC #4 -- a username collision is refused and logged.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_username_collision_is_refused_and_logged() -> None:
    """AD-12: the holder keeps the name, the arrival authenticates, nothing raises.

    `UserFactory` sets `username` and no `idp_subject`, so user A is seeded with
    the name and then given the identity key explicitly -- the "pre-existing user
    with a colliding username" fixture the AC describes.
    """
    ada = UserFactory.create(username="ada", idp_subject=SUBJECT_A)

    with structlog.testing.capture_logs() as captured:
        arriving = resolve_user(_claims(SUBJECT_B, preferred_username="ada", email=SHARED_EMAIL))

    # The arrival exists, under a name that is not the one it asked for.
    assert arriving.pk != ada.pk
    assert arriving.idp_subject == SUBJECT_B
    assert arriving.username != "ada"
    assert arriving.username == _derived_username(SUBJECT_B)

    # The holder is untouched -- in memory and on the row.
    ada.refresh_from_db()
    assert ada.username == "ada"
    assert ada.idp_subject == SUBJECT_A

    # Both authenticate normally: each identity key still resolves to its own user.
    assert resolve_user(_claims(SUBJECT_A)).pk == ada.pk
    assert resolve_user(_claims(SUBJECT_B)).pk == arriving.pk

    # Refused *and logged*, at warning, naming both sides.
    events = _collision_events(captured)
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["idp_subject"] == SUBJECT_B
    assert events[0]["desired_username"] == "ada"
    assert events[0]["held_by_idp_subject"] == SUBJECT_A


@pytest.mark.django_db
def test_a_username_free_of_collision_is_written_and_nothing_is_logged() -> None:
    """The other half of the rule: no collision, no event, and the asked-for name is kept."""
    UserFactory.create(username="grace", idp_subject=SUBJECT_A)

    with structlog.testing.capture_logs() as captured:
        arriving = resolve_user(_claims(SUBJECT_B, preferred_username="ada"))

    assert arriving.username == "ada"
    assert _collision_events(captured) == []


@pytest.mark.django_db
def test_a_collision_with_a_row_carrying_no_identity_key_is_still_refused() -> None:
    """The holder need not be an IdP identity for the name to be taken.

    The event records `held_by_idp_subject` as None rather than omitting it: "no
    collision" and "collided with a legacy row" have to be distinguishable in the
    log, or the operator cannot tell which of the two happened.
    """
    UserFactory.create(username="ada")

    with structlog.testing.capture_logs() as captured:
        arriving = resolve_user(_claims(SUBJECT_B, preferred_username="ada"))

    assert arriving.username == _derived_username(SUBJECT_B)
    events = _collision_events(captured)
    assert len(events) == 1
    assert events[0]["held_by_idp_subject"] is None


@pytest.mark.django_db
def test_a_first_sighting_whose_derived_name_is_also_held_still_resolves() -> None:
    """AD-12's "never an `IntegrityError` mid-authentication", at the second candidate.

    The derived name used to be returned without ever being checked, so a row
    already holding it turned the create into
    `IntegrityError: UNIQUE constraint failed: users_user.username` -- a 500 in
    the middle of an authentication, for a caller who did nothing wrong. Every
    candidate is checked now, and the identity key's own rendering is the third.
    """
    UserFactory.create(username=_derived_username(SUBJECT_S3))
    UserFactory.create(username="taken")

    resolved = resolve_user(_claims(SUBJECT_S3, preferred_username="taken"))

    assert resolved.idp_subject == SUBJECT_S3
    assert resolved.username == _username_from_identity_key(SUBJECT_S3)
    assert resolved.username not in {"taken", _derived_username(SUBJECT_S3)}


@pytest.mark.django_db
def test_a_forged_derived_username_cannot_deny_the_identity_it_impersonates() -> None:
    """The derived namespace is a pure function of the subject, so it is forgeable.

    One identity asserting `idp-<digest of another subject>` as its
    `preferred_username` used to reserve the exact name its victim's first
    sighting would derive -- and that first sighting then died on the unique
    constraint. The squatter keeps the name it asked for (a display name is not
    an identity), and the victim resolves under the next candidate.
    """
    squatter = resolve_user(_claims(SUBJECT_B, preferred_username=_derived_username(SUBJECT_A)))
    assert squatter.username == _derived_username(SUBJECT_A)
    UserFactory.create(username="ada")

    victim = resolve_user(_claims(SUBJECT_A, preferred_username="ada"))

    assert victim.idp_subject == SUBJECT_A
    assert victim.username == _username_from_identity_key(SUBJECT_A)
    assert victim.pk != squatter.pk
    squatter.refresh_from_db()
    assert squatter.username == _derived_username(SUBJECT_A)


@pytest.mark.django_db
def test_a_first_sighting_with_no_candidate_left_is_refused_not_an_integrity_error() -> None:
    """The end of the deterministic candidates is a refusal, and a logged one.

    Overwriting the holder is forbidden by AD-12, a random suffix or a counter by
    AC #2's determinism, and an `IntegrityError` by AD-12 again -- which leaves
    `ClaimsRejected`, the same refusal every caller already turns into a 401.
    """
    for held in ("taken", _derived_username(SUBJECT_S3), _username_from_identity_key(SUBJECT_S3)):
        UserFactory.create(username=held)

    with structlog.testing.capture_logs() as captured, pytest.raises(ClaimsRejected) as refusal:
        resolve_user(_claims(SUBJECT_S3, preferred_username="taken"))

    assert refusal.value.reason == "no username available for the identity key"
    events = _events(captured, "authorization.username_unavailable")
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["idp_subject"] == SUBJECT_S3
    assert not get_user_model().objects.filter(idp_subject=SUBJECT_S3).exists()


@pytest.mark.django_db
def test_a_concurrent_first_sighting_of_one_identity_resolves_to_the_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check-then-insert is not atomic, and `idp_subject` is unique.

    Two callers can both miss the read and both insert; the loser's insert
    violates the constraint. Forced deterministically rather than with threads:
    the conflicting row is created inside `_available_username`, which runs
    between this call's read and its insert -- exactly the window a second
    process occupies. The recovered outcome is the *same* user, which is AC #2's
    "the same identity resolves to the same user" holding under a race.
    """
    winners: list[User] = []

    def _let_the_other_caller_win(user: User, desired: str, subject: str) -> str:
        username = _available_username(user, desired, subject)
        winners.append(UserFactory.create(username="won-the-race", idp_subject=subject))
        return username

    monkeypatch.setattr(mapper, "_available_username", _let_the_other_caller_win)

    with structlog.testing.capture_logs() as captured:
        resolved = resolve_user(_claims(SUBJECT_A, preferred_username="ada"))

    assert resolved.pk == winners[0].pk
    assert resolved.username == "won-the-race"
    assert get_user_model().objects.filter(idp_subject=SUBJECT_A).count() == 1
    assert len(_events(captured, "authorization.user_created_concurrently")) == 1
    # The loser's own row was rolled back to the savepoint, so nothing it built
    # survived -- and the transaction is still usable, which is what let the
    # recovery read run at all.
    assert not get_user_model().objects.filter(username="ada").exists()


@pytest.mark.django_db
def test_a_username_taken_between_the_check_and_the_insert_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other constraint the insert can violate, and the other outcome.

    Here the concurrent caller took the *name* rather than the identity key, so
    re-reading by `idp_subject` finds nothing and there is no winner to resolve
    to. Which constraint fired is decided by that re-read rather than by parsing
    the driver's message, which differs between PostgreSQL and SQLite. The
    caller gets the same `ClaimsRejected` every other refusal produces -- what it
    must never get is the `IntegrityError`.
    """

    def _let_the_other_caller_take_the_name(user: User, desired: str, subject: str) -> str:
        username = _available_username(user, desired, subject)
        UserFactory.create(username=username)
        return username

    monkeypatch.setattr(mapper, "_available_username", _let_the_other_caller_take_the_name)

    with structlog.testing.capture_logs() as captured, pytest.raises(ClaimsRejected) as refusal:
        resolve_user(_claims(SUBJECT_A, preferred_username="ada"))

    assert refusal.value.reason == "no username available for the identity key"
    events = _events(captured, "authorization.username_unavailable")
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["idp_subject"] == SUBJECT_A
    assert not get_user_model().objects.filter(idp_subject=SUBJECT_A).exists()


# ---------------------------------------------------------------------------
# Every claim-derived value is bounded and valid on the row (AD-11's attributes).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_claim_derived_attribute_is_bounded_by_its_field() -> None:
    """PostgreSQL answers an over-long value with `DataError`; SQLite stores it.

    So this asserts lengths rather than trusting the insert: on the gate's SQLite
    the assertions are the only thing that fails, and on PostgreSQL the insert
    itself would have raised before them.
    """
    limits = {field: field_length(field) for field in ("username", "email", "name")}

    created = resolve_user(
        _claims(
            SUBJECT_A,
            preferred_username="a" * (limits["username"] + OVERSHOOT),
            email="b" * (limits["email"] + OVERSHOOT),
            name="c" * (limits["name"] + OVERSHOOT),
        ),
    )

    created.refresh_from_db()
    assert len(created.username) == limits["username"]
    assert len(created.email) == limits["email"]
    assert len(created.name) == limits["name"]


@pytest.mark.django_db
def test_a_claimed_username_lands_on_the_row_valid_and_reversible() -> None:
    """`users:detail` is `<str:username>`, and that converter matches no `/`.

    An unsanitized `preferred_username` was written verbatim, so the user the
    mapper had just created raised `NoReverseMatch` from `get_absolute_url()` and
    failed `UnicodeUsernameValidator` on its way through any form.
    """
    created = resolve_user(_claims(SUBJECT_A, preferred_username="ada/lovelace"))

    created.refresh_from_db()
    assert created.username == "ada-lovelace"
    UnicodeUsernameValidator()(created.username)
    assert created.get_absolute_url() == "/users/ada-lovelace/"


@pytest.mark.django_db
def test_an_identity_key_too_long_to_store_is_refused_before_the_insert() -> None:
    """A refusal the caller turns into a 401, not a `DataError` from the driver."""
    over_long = "u" * (field_length("idp_subject") + 1)

    with pytest.raises(ClaimsRejected) as refusal:
        resolve_user(_claims(over_long))

    assert refusal.value.reason == "identity key longer than the identity field"
    assert not get_user_model().objects.filter(idp_subject__startswith="u").exists()


# ---------------------------------------------------------------------------
# The spine: every authorization change emits an event, and a new principal
# existing is one.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_first_sighting_emits_the_user_created_event() -> None:
    """Asserted, not merely emitted: the call could be deleted and nothing else would notice.

    Every other event assertion in this file filters for the collision event, so
    `authorization.user_created` was the one authorization change with no
    observer at all.
    """
    with structlog.testing.capture_logs() as captured:
        created = resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    events = _events(captured, "authorization.user_created")
    assert len(events) == 1
    assert events[0]["log_level"] == "info"
    assert events[0]["idp_subject"] == SUBJECT_A
    assert events[0]["username"] == created.username


@pytest.mark.django_db
def test_resolving_an_existing_identity_emits_no_creation_event() -> None:
    """The other half: a hit is not a change, so it is not an event."""
    resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    with structlog.testing.capture_logs() as captured:
        resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    assert _events(captured, "authorization.user_created") == []


# ---------------------------------------------------------------------------
# The one non-string identity key the claims reader supports.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_integer_identity_key_resolves_and_is_stored_as_text() -> None:
    """`read_identity_key` stringifies a non-boolean integer -- numeric subjects occur.

    Exercised through the mapper rather than only through the reader: everything
    downstream of it, `_username_from_identity_key`'s `subject.encode()`
    included, is typed for `str` and had never seen the one supported non-string
    subject arrive.
    """
    numeric = 1234567890

    created = resolve_user({IDENTITY_CLAIM: numeric})

    assert created.idp_subject == str(numeric)
    assert created.username == str(numeric)
    UnicodeUsernameValidator()(created.username)
    # Same identity, second sighting: the stringification is stable, so it is the
    # same user rather than a second row.
    assert resolve_user({IDENTITY_CLAIM: numeric}).pk == created.pk


# ---------------------------------------------------------------------------
# AC #5 -- one indexed read, and no write.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_resolving_an_existing_identity_is_a_single_query(django_assert_num_queries: Any) -> None:
    """AD-10's whole point, asserted mechanically rather than described in a comment.

    One `SELECT` and nothing else: no `get_or_create` write attempt, no
    `user.groups` read -- which is what `auth_user_groups` write amplification on
    every API call would look like at its source -- and no attribute save.
    """
    resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    with django_assert_num_queries(1):
        resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))


@pytest.mark.django_db
def test_the_single_read_holds_when_the_attribute_claims_have_changed(
    django_assert_num_queries: Any,
) -> None:
    """A Bearer request whose token carries different attributes still must not write.

    Reconciling attributes on the read path is the amplification AD-10 forbids
    wearing a different name: it would turn every API call into a write.
    """
    created = resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    with django_assert_num_queries(1):
        resolve_user(_claims(SUBJECT_A, preferred_username="different", email="other@example.com"))

    created.refresh_from_db()
    assert created.username == "ada"
    assert created.email == SHARED_EMAIL


@pytest.mark.django_db
def test_the_resolve_path_never_loads_groups(django_assert_num_queries: Any) -> None:
    """No `select_related`/`prefetch_related` of groups: sync loads groups, resolve does not."""
    user = resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))
    user.groups.set([])

    with django_assert_num_queries(1):
        resolved = resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    # Untouched by resolve, so the descriptor is still unevaluated and reading it
    # here costs its own query -- outside the assertion above, deliberately.
    assert resolved.groups.count() == 0


# ---------------------------------------------------------------------------
# AC #7 (Story 2.7) -- a resolved row must also be active to be returned.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_deactivated_user_is_refused_rather_than_returned() -> None:
    """The refusal lives here, once, so all three entry points inherit it.

    Placing it in each caller instead has already failed by omission once: Story
    2.6 shipped with no explicit check and was safe only because allauth's
    `perform_login` happens to gate inactive users after `pre_social_login`
    returns. The Bearer path has no such backend in front of it at all.
    """
    UserFactory.create(idp_subject=SUBJECT_A, is_active=False)

    with pytest.raises(ClaimsRejected) as refusal:
        resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    assert refusal.value.reason == "resolved user is deactivated"


@pytest.mark.django_db
def test_the_deactivation_refusal_does_not_reuse_another_refusals_reason() -> None:
    """A shared reason would send whoever reads the log to the IdP for an admin action.

    A deactivated user's claims are perfectly valid. Reporting one of the claim
    refusals here would describe an operator decision taken in this component as
    a verdict about the token.
    """
    UserFactory.create(idp_subject=SUBJECT_A, is_active=False)

    with pytest.raises(ClaimsRejected) as refusal:
        resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    reason = refusal.value.reason
    assert "deactivated" in reason
    assert reason not in {
        "identity key claim absent",
        "identity key longer than the identity field",
        "no username available for the identity key",
        "group claim absent",
        "token carries no jti",
    }


@pytest.mark.django_db
def test_the_deactivation_refusal_is_reported() -> None:
    """Handled and reported, never swallowed -- and `idp_subject` is what an operator has."""
    UserFactory.create(idp_subject=SUBJECT_A, is_active=False)

    with structlog.testing.capture_logs() as captured, pytest.raises(ClaimsRejected):
        resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS))

    events = _events(captured, "authorization.claims_rejected")
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["reason"] == "resolved user is deactivated"
    assert events[0]["idp_subject"] == SUBJECT_A


@pytest.mark.django_db
def test_an_active_user_is_returned_unchanged() -> None:
    """The control: only `is_active` separates this from the refusal above."""
    existing = UserFactory.create(idp_subject=SUBJECT_A, is_active=True)

    assert resolve_user(_claims(SUBJECT_A, **INTERACTIVE_CLAIMS)) == existing


@pytest.mark.django_db
def test_a_user_created_on_a_miss_is_active_by_construction() -> None:
    """A first sighting is never refused by the check: nothing has deactivated it yet."""
    created = resolve_user(_claims(SUBJECT_B, **INTERACTIVE_CLAIMS))

    assert created.is_active is True
