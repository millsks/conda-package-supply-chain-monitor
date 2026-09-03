"""Sync and the epoch gate against a real database.

What the unit tests cannot show: that memberships move in both directions, that
the whole diff is one transaction, that `is_staff` and `is_superuser` are cleared
when the claims stop asserting their designated groups, that a Bearer `jti` syncs
once and never again, and that the epoch record lands in a table rather than in a
cache.

Every test here rolls back. `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the state as found; `transaction=True` would truncate the
tables the group-provisioning migration seeded and is not needed by anything
below -- the `IntegrityError` race is simulated by making the insert raise rather
than by spawning concurrency.

The claims contract is pointed at deliberately unconventional names in every
test, through the `settings` fixture. The *designated* groups those names call
for are then seeded by calling `provision_designated_groups()` (Story 2.3) rather
than by creating them here: a test that made its own would hide a real defect in
the one mechanism AD-27 says creates groups. The ordinary groups below are not
designated and are created directly, exactly as an operator's would be.
"""

from __future__ import annotations

import ast
from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.db import transaction
from django.urls import reverse

from config.authorization.claims import ClaimsContract
from config.authorization.exceptions import ClaimsRejected
from config.authorization.mapper import EXPIRY_CLAIM
from config.authorization.mapper import JTI_CLAIM
from config.authorization.mapper import sync_authorization
from config.authorization.mapper import sync_for_interactive
from config.authorization.mapper import sync_once_per_epoch
from django_service.users.models import CredentialEpoch
from django_service.users.provisioning import provision_designated_groups
from tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django.fixtures import SettingsWrapper

    from django_service.users.models import User

# Nothing here is `sub`, `groups`, `staff` or `superuser`.
IDENTITY_CLAIM = "urn:example:principal-id"
GROUP_CLAIM = "realm_access.roles"
STAFF_GROUP = "shipping-desk-operators"
SUPERUSER_GROUP = "shipping-desk-owners"

SUBJECT_A = "urn:example:principal:A"

# Ordinary groups: not designated, so the operator creates them, not AD-27's
# provisioning.
GROUP_A = "manifest-readers"
GROUP_B = "manifest-writers"
GROUP_C = "manifest-approvers"
ORDINARY_GROUPS = (GROUP_A, GROUP_B, GROUP_C)

UNKNOWN_GROUP = "no-such-group"

# The package the source-text scan below covers, and the import it forbids.
AUTHORIZATION_PACKAGE = Path(__file__).resolve().parents[3] / "src" / "config" / "authorization"
FORBIDDEN_CACHE_IMPORT = "django.core.cache"

# 2026-08-17T00:00:00Z, as a token carries it: seconds since the epoch.
AN_EXPIRY = 1786924800

# How many authentications AC #5 drives through the mapper.
AUTHENTICATIONS = 3


class SyncSaveError(Exception):
    """Raised in place of the user save, to prove the whole diff is one transaction."""


@pytest.fixture(autouse=True)
def _contract(settings: SettingsWrapper) -> None:
    """Point the claims contract at names that appear nowhere in the source."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )


@pytest.fixture
def groups(db: None) -> None:
    """Seed the designated groups through the one mechanism, and the ordinary ones directly.

    The designated pair goes through `provision_designated_groups` because that
    is the only thing in this repository permitted to create a `Group` (AD-27),
    and because AC #8's "ignored, never created" is defensible only while that
    guarantee holds. The three ordinary groups are not designated: they stand for
    whatever an operator has already created, and creating them here is what
    creating them in the admin would be.
    """
    provision_designated_groups()
    for name in ORDINARY_GROUPS:
        Group.objects.get_or_create(name=name)


@pytest.fixture
def user(groups: None) -> User:
    """A user carrying the identity key, as `resolve_user` would have left it."""
    created: User = UserFactory.create(username="ada", idp_subject=SUBJECT_A)
    return created


def _claims(*names: str, jti: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a claim set asserting `names` at the configured dotted group claim."""
    claims: dict[str, Any] = {
        IDENTITY_CLAIM: SUBJECT_A,
        "realm_access": {"roles": list(names)},
        **extra,
    }
    if jti is not None:
        claims[JTI_CLAIM] = jti
    return claims


def _events(captured: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """Select one event by name from a `capture_logs` recording."""
    return [event for event in captured if event["event"] == name]


def _imports(path: Path) -> set[str]:
    """Return every module one source file imports, as dotted names.

    Parsed rather than grepped. Both this module's docstrings and the mapper's
    quote AD-10's rule, which names `django.core.cache` in prose -- a text search
    would report the prohibition itself as a violation of the prohibition.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _reaches_for_the_cache(module: str) -> bool:
    """Say whether one imported dotted name is the cache package or something inside it.

    A prefix rather than an equality: `django.core.cache.backends.locmem` is the
    in-process backend itself, and every other submodule is reached through the
    same package, so an exact comparison would pass the very import the ban is
    aimed at. The dot is part of the prefix -- a package merely *starting* with
    the same letters is a different package.
    """
    return module == FORBIDDEN_CACHE_IMPORT or module.startswith(f"{FORBIDDEN_CACHE_IMPORT}.")


def _held(user: User) -> set[str]:
    """Read a user's group names back from the database."""
    return set(user.groups.values_list("name", flat=True))


# ---------------------------------------------------------------------------
# AC #1 -- adds, removes, sets both flags, emits one event, one transaction.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sync_adds_the_asserted_groups_and_removes_the_unasserted_ones(user: User) -> None:
    """FR-9's whole point: the removal half is what makes a revocation arrive.

    A user holding `{A, B}` given claims asserting `{B, C}` ends holding
    `{B, C}` -- `C` added, `A` removed, `B` left alone -- and the emitted event
    records exactly which rows moved. `user.groups.set(...)` would produce the
    same membership and no way to say what changed, which is why it is not used.
    """
    user.groups.set(Group.objects.filter(name__in=(GROUP_A, GROUP_B)))

    with structlog.testing.capture_logs() as captured:
        outcome = sync_authorization(user, _claims(GROUP_B, GROUP_C))

    assert _held(user) == {GROUP_B, GROUP_C}
    assert outcome.added == (GROUP_C,)
    assert outcome.removed == (GROUP_A,)
    assert outcome.ignored == ()

    events = _events(captured, "authorization.synced")
    assert len(events) == 1
    assert events[0]["log_level"] == "info"
    assert events[0]["idp_subject"] == SUBJECT_A
    assert events[0]["groups_added"] == (GROUP_C,)
    assert events[0]["groups_removed"] == (GROUP_A,)
    assert events[0]["groups_ignored"] == ()
    assert events[0]["is_staff"] is False
    assert events[0]["is_superuser"] is False


@pytest.mark.django_db
def test_a_sync_that_fails_part_way_moves_no_group(
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #1's "all of it runs inside one transaction", asserted rather than described.

    The flag save is made to raise, which is the last write in the body and
    therefore the one that leaves the widest window: without the transaction the
    memberships have already moved by the time it fires, and the user is left
    holding a set no claim asserted. With it, the whole diff rolls back to the
    savepoint and the membership is the one the sync started from.

    Both flags are asserted alongside the memberships, and the user starts
    holding them while the claims assert neither designated group -- so a sync
    that completed would have cleared both. Reading only the memberships back
    would leave the very statement this test forces to raise unchecked.
    """
    user.groups.set(Group.objects.filter(name__in=(GROUP_A, GROUP_B)))
    user.is_staff = True
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser"])

    def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise SyncSaveError

    monkeypatch.setattr(type(user), "save", _fail)

    with pytest.raises(SyncSaveError):
        sync_authorization(user, _claims(GROUP_B, GROUP_C))

    assert _held(user) == {GROUP_A, GROUP_B}
    user.refresh_from_db()
    assert user.is_staff is True
    assert user.is_superuser is True


@pytest.mark.django_db
def test_each_flag_comes_from_its_own_designated_group(user: User) -> None:
    """AD-12: two groups, two flags, and neither implies the other."""
    staff_only = sync_authorization(user, _claims(STAFF_GROUP))
    assert (staff_only.is_staff, staff_only.is_superuser) == (True, False)

    superuser_only = sync_authorization(user, _claims(SUPERUSER_GROUP))
    assert (superuser_only.is_staff, superuser_only.is_superuser) == (False, True)

    both = sync_authorization(user, _claims(STAFF_GROUP, SUPERUSER_GROUP))
    assert (both.is_staff, both.is_superuser) == (True, True)

    user.refresh_from_db()
    assert user.is_staff is True
    assert user.is_superuser is True


@pytest.mark.django_db
def test_sync_is_bounded_in_queries(user: User, django_assert_max_num_queries: Any) -> None:
    """The asserted set resolves in one query and the diff applies in a bounded few.

    A per-name `Group.objects.get(...)` would make sync's cost a function of how
    many groups the IdP asserts, which is the shape that turns a large token into
    a slow login. The bound is asserted rather than the exact count so that a
    savepoint or a backend difference does not make the test a tripwire for
    nothing.
    """
    user.groups.set(Group.objects.filter(name__in=(GROUP_A, GROUP_B)))

    with django_assert_max_num_queries(7):
        sync_authorization(user, _claims(GROUP_B, GROUP_C, STAFF_GROUP))


# ---------------------------------------------------------------------------
# AC #2 -- every interactive login, once per Bearer `jti`.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_bearer_credential_syncs_at_the_first_sighting_of_its_jti_and_not_after(user: User) -> None:
    """AD-10's gate: the second request carrying the same token writes nothing.

    The second call is given *different* claims on purpose. If the gate were
    absent the membership would follow them, so the assertion that it did not is
    what distinguishes "skipped the sync" from "synced to the same answer".
    """
    first = sync_once_per_epoch(user, _claims(GROUP_A, jti="j1"))
    assert first is not None
    assert first.added == (GROUP_A,)
    assert _held(user) == {GROUP_A}

    second = sync_once_per_epoch(user, _claims(GROUP_C, jti="j1"))

    assert second is None
    assert _held(user) == {GROUP_A}


@pytest.mark.django_db
def test_a_second_credential_is_a_second_epoch_and_syncs_again(user: User) -> None:
    """Once per `jti`, not once per user: a fresh token is a fresh epoch."""
    sync_once_per_epoch(user, _claims(GROUP_A, jti="j1"))

    outcome = sync_once_per_epoch(user, _claims(GROUP_C, jti="j2"))

    assert outcome is not None
    assert outcome.added == (GROUP_C,)
    assert outcome.removed == (GROUP_A,)
    assert _held(user) == {GROUP_C}


@pytest.mark.django_db
def test_an_interactive_login_syncs_every_time(user: User) -> None:
    """An interactive login is itself the epoch and never goes through the gate.

    It carries no `jti`, so routing it through `sync_once_per_epoch` would refuse
    every interactive login outright -- which is why the two entry points are
    separate rather than one function with a branch.
    """
    first = sync_for_interactive(user, _claims(GROUP_A))
    second = sync_for_interactive(user, _claims(GROUP_C))

    assert first.added == (GROUP_A,)
    assert second.added == (GROUP_C,)
    assert second.removed == (GROUP_A,)
    assert _held(user) == {GROUP_C}
    assert not CredentialEpoch.objects.exists()


@pytest.mark.django_db
def test_a_lost_race_for_the_first_sighting_is_treated_as_already_seen(
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two workers can race one first sighting; the unique constraint decides it.

    Simulated by making the insert raise rather than by spawning concurrency --
    real threads would need `transaction=True`, which truncates the tables the
    provisioning migration seeded. The loser's answer is a second sighting's:
    already recorded, nothing to sync, and the caller is not handed an
    `IntegrityError` mid-authentication.

    The winner's row is created first, because that is what the losing worker
    would find: `get_or_create` re-reads after a violation and only a failure
    whose re-read *also* comes back empty is something other than the race.
    """
    CredentialEpoch.objects.create(jti="j1", user=user)

    def _lose_the_race(**_kwargs: Any) -> tuple[CredentialEpoch, bool]:
        raise IntegrityError

    monkeypatch.setattr(CredentialEpoch.objects, "get_or_create", _lose_the_race)

    with structlog.testing.capture_logs() as captured:
        outcome = sync_once_per_epoch(user, _claims(GROUP_A, jti="j1"))

    assert outcome is None
    assert _held(user) == set()
    events = _events(captured, "authorization.epoch_race")
    assert len(events) == 1
    assert events[0]["log_level"] == "debug"
    assert events[0]["idp_subject"] == SUBJECT_A


@pytest.mark.django_db
def test_an_insert_failure_that_is_not_the_race_is_reported_and_raised(
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A violation with no row behind it is a fault, not a second sighting.

    Reporting it as "already seen" would skip the authorization sync outright
    and leave a debug line as the only trace -- a swallowed failure, and one
    that presents afterwards as an identity whose groups never moved. The
    re-read is what tells the two apart: the race leaves the winner's row, a
    foreign-key or NOT NULL violation leaves nothing.
    """

    def _fail_for_another_reason(**_kwargs: Any) -> tuple[CredentialEpoch, bool]:
        raise IntegrityError

    monkeypatch.setattr(CredentialEpoch.objects, "get_or_create", _fail_for_another_reason)

    with structlog.testing.capture_logs() as captured, pytest.raises(IntegrityError):
        sync_once_per_epoch(user, _claims(GROUP_A, jti="j1"))

    assert _events(captured, "authorization.epoch_race") == []
    events = _events(captured, "authorization.epoch_insert_failed")
    assert len(events) == 1
    assert events[0]["log_level"] == "error"
    assert events[0]["idp_subject"] == SUBJECT_A


@pytest.mark.django_db
def test_a_jti_already_recorded_for_another_identity_is_refused(user: User) -> None:
    """One credential's epoch may not decide another identity's authorization.

    An issuer minting colliding identifiers, or a token presented for the wrong
    subject, would otherwise take the quiet second-sighting path: no sync, no
    event, and an identity authorized from a sync nobody performed for it --
    which is the staleness AD-10 exists to prevent. The `jti` reaches the event
    as a length only, for the reason the over-long refusal gives.
    """
    other: User = UserFactory.create(username="grace", idp_subject="urn:example:principal:B")
    CredentialEpoch.objects.create(jti="j1", user=other)

    with structlog.testing.capture_logs() as captured, pytest.raises(ClaimsRejected) as refusal:
        sync_once_per_epoch(user, _claims(GROUP_A, jti="j1"))

    assert refusal.value.reason == "jti recorded for another identity"
    assert _held(user) == set()
    events = _events(captured, "authorization.epoch_jti_reuse")
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["idp_subject"] == SUBJECT_A
    assert events[0]["jti_length"] == len("j1")
    assert "j1" not in str(events[0])


# ---------------------------------------------------------------------------
# AC #3 -- the epoch record lives in a table, never in `django.core.cache`.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_first_sighting_is_recorded_as_a_row(user: User) -> None:
    """A `django_service`-owned table, carrying the owner and the expiry the pruner needs."""
    sync_once_per_epoch(user, _claims(GROUP_A, jti="j1", **{EXPIRY_CLAIM: AN_EXPIRY}))

    epoch = CredentialEpoch.objects.get(jti="j1")
    assert epoch.user_id == user.pk
    assert epoch.expires_at == datetime.fromtimestamp(AN_EXPIRY, tz=UTC)
    assert epoch.first_seen_at is not None
    assert str(epoch) == "j1"
    assert user.credential_epochs.count() == 1


@pytest.mark.django_db
def test_a_credential_with_no_expiry_is_recorded_without_one(user: User) -> None:
    """`expires_at` is nullable: a token carrying no `exp` is still an epoch."""
    sync_once_per_epoch(user, _claims(GROUP_A, jti="j1"))

    assert CredentialEpoch.objects.get(jti="j1").expires_at is None


@pytest.mark.django_db
def test_the_epoch_table_refuses_a_second_row_for_one_jti(user: User) -> None:
    """The first sighting is a database guarantee, not a check-then-act.

    Everything the gate does rests on it: two workers both miss the read, both
    insert, and the constraint is the only thing that decides which of them
    syncs. Without it the losing insert succeeds and both sync, which is the
    write amplification AD-10 exists to prevent, and no other test in this file
    would notice. The failing insert is wrapped in a savepoint because
    PostgreSQL poisons the enclosing transaction until one is rolled back to,
    which would take the rest of this test with it.
    """
    CredentialEpoch.objects.create(jti="j1", user=user)

    with pytest.raises(IntegrityError), transaction.atomic():
        CredentialEpoch.objects.create(jti="j1", user=user)

    assert CredentialEpoch.objects.filter(jti="j1").count() == 1


def test_the_authorization_package_never_reaches_for_the_cache() -> None:
    """AD-10, stated as a source fact because no runtime assertion can catch it.

    Two of the six combinations ship no Redis, so their `django.core.cache` is
    Django's in-process backend: "first sighting" would become
    first-sighting-per-worker-per-restart there, and every test in this file
    would still pass on a single-worker test runner. A cache read "as an
    optimization in front of the table" reintroduces exactly that, which is why
    the ban is on the import rather than on the behaviour.
    """
    modules = sorted(AUTHORIZATION_PACKAGE.rglob("*.py"))
    assert modules != [], f"expected the authorization package to be scannable at {AUTHORIZATION_PACKAGE}"

    offenders = {path.name for path in modules if any(_reaches_for_the_cache(module) for module in _imports(path))}

    assert offenders == set()


# ---------------------------------------------------------------------------
# AC #4 -- a Bearer token with no `jti` is rejected (401 at the caller).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "jti",
    [
        pytest.param(None, id="no-jti-key-at-all"),
        pytest.param("", id="empty-jti"),
    ],
)
def test_a_credential_with_no_jti_is_refused_and_records_no_epoch(user: User, jti: str | None) -> None:
    """Refused before anything is written: no epoch row, no membership change."""
    claims = _claims(GROUP_A) if jti is None else _claims(GROUP_A, jti=jti)

    with pytest.raises(ClaimsRejected) as refusal:
        sync_once_per_epoch(user, claims)

    assert refusal.value.reason == "token carries no jti"
    assert not CredentialEpoch.objects.exists()
    assert _held(user) == set()


@pytest.mark.django_db
def test_a_refused_sync_leaves_the_epoch_unrecorded(user: User) -> None:
    """A credential refused at the sync must not have burnt its one epoch.

    The row is inserted before the sync is attempted, so a refusal that let it
    stand would mean the token can never sync again -- the gate would report
    every later request as a second sighting, for the whole lifetime of the
    credential, and the identity would authenticate with whatever groups it
    happened to hold. The claim set here carries a usable `jti` and no group
    claim at all, so the insert succeeds and `sync_authorization` refuses after
    it; the transaction is what takes the row back out.
    """
    with pytest.raises(ClaimsRejected) as refusal:
        sync_once_per_epoch(user, {IDENTITY_CLAIM: SUBJECT_A, JTI_CLAIM: "j1"})

    assert refusal.value.reason == "group claim absent"
    assert not CredentialEpoch.objects.filter(jti="j1").exists()
    assert _held(user) == set()


# ---------------------------------------------------------------------------
# AC #5 -- mapping is not in `populate_user()`, so it happens every time.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_same_identity_maps_on_every_authentication(user: User) -> None:
    """`populate_user` runs only when allauth instantiates a *new* user.

    Mapping placed there would run once and never again, and the membership
    would freeze at whatever the first login asserted. Asserted against the
    mapper's own entry point so it holds however Story 2.6 hooks the adapter.
    """
    asserted = (GROUP_A, GROUP_B, GROUP_C)
    outcomes = [sync_for_interactive(user, _claims(name)) for name in asserted]

    assert len(outcomes) == AUTHENTICATIONS
    assert [outcome.added for outcome in outcomes] == [(GROUP_A,), (GROUP_B,), (GROUP_C,)]
    assert [outcome.removed for outcome in outcomes] == [(), (GROUP_A,), (GROUP_B,)]
    assert _held(user) == {GROUP_C}


# ---------------------------------------------------------------------------
# AC #6 -- dropping the designated staff group costs staff status and the admin.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dropping_the_staff_group_clears_staff_and_closes_the_admin(user: User, client: Client) -> None:
    """The clearing half of AD-12, checked where it is felt rather than on the flag alone.

    A rendered request is the assertion that matters: `is_staff = False` on the
    row and an admin page that still renders would be the revocation not
    arriving. `DJANGO_ADMIN_FORCE_ALLAUTH` changes where the refusal redirects
    to, so this asserts "not 200" rather than a target.
    """
    sync_for_interactive(user, _claims(STAFF_GROUP))
    user.refresh_from_db()
    assert user.is_staff is True

    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    assert client.get(reverse("admin:index")).status_code == HTTPStatus.OK

    outcome = sync_for_interactive(user, _claims(GROUP_A))

    assert outcome.is_staff is False
    user.refresh_from_db()
    assert user.is_staff is False
    assert client.get(reverse("admin:index")).status_code != HTTPStatus.OK


# ---------------------------------------------------------------------------
# AC #7 -- an absent group claim is a refusal; a present, empty one is not.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_absent_group_claim_is_refused_and_changes_nothing(user: User) -> None:
    """AD-12: a 401, never an authentication with zero groups.

    Placed next to its twin below on purpose -- the two claim sets differ by one
    key, the outcomes differ completely, and collapsing them is the defect this
    pair exists to catch.
    """
    user.groups.set(Group.objects.filter(name=GROUP_A))

    with pytest.raises(ClaimsRejected) as refusal:
        sync_authorization(user, {IDENTITY_CLAIM: SUBJECT_A})

    assert refusal.value.reason == "group claim absent"
    assert _held(user) == {GROUP_A}


@pytest.mark.django_db
def test_a_present_but_empty_group_claim_is_a_legitimate_assertion_of_no_groups(user: User) -> None:
    """The twin: the claim is there and asserts nothing, which is a real answer."""
    user.groups.set(Group.objects.filter(name__in=(GROUP_A, STAFF_GROUP)))

    outcome = sync_authorization(user, _claims())

    assert outcome.removed == tuple(sorted((GROUP_A, STAFF_GROUP)))
    assert _held(user) == set()
    assert outcome.is_staff is False
    user.refresh_from_db()
    assert user.is_staff is False


# ---------------------------------------------------------------------------
# AC #8 -- a claim naming no Django group is ignored and logged, never created.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_claim_naming_no_django_group_is_ignored_and_logged(user: User) -> None:
    """AD-12: ignored, never created, and the groups that do exist still sync.

    Creating the missing row would make the IdP's group taxonomy silently become
    Django's, so an unknown name is a warning rather than a `get_or_create`. It
    is safe to ignore only because Story 2.3 guarantees the *designated* rows
    exist -- otherwise ignoring would deny the very administrator meant to be
    established by claim.
    """
    before = Group.objects.count()

    with structlog.testing.capture_logs() as captured:
        outcome = sync_authorization(user, _claims(GROUP_A, UNKNOWN_GROUP))

    assert Group.objects.count() == before
    assert not Group.objects.filter(name=UNKNOWN_GROUP).exists()
    assert outcome.ignored == (UNKNOWN_GROUP,)
    assert outcome.added == (GROUP_A,)
    assert _held(user) == {GROUP_A}

    events = _events(captured, "authorization.unknown_group_claim")
    assert len(events) == 1
    assert events[0]["log_level"] == "warning"
    assert events[0]["group"] == UNKNOWN_GROUP
    assert events[0]["idp_subject"] == SUBJECT_A
    assert _events(captured, "authorization.synced")[0]["groups_ignored"] == (UNKNOWN_GROUP,)


@pytest.mark.django_db
def test_a_designated_group_that_does_not_exist_confers_nothing(user: User, settings: SettingsWrapper) -> None:
    """The flags read the *resolved* names, so an unprovisioned group grants nothing.

    AD-27 makes this state a stage-2 startup refusal (Epic 4's), not something
    sync papers over: no defensive `get_or_create` runs here, because a group
    invented mid-authentication is a grant nobody wrote down.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group="never-provisioned-staff",
        superuser_group="never-provisioned-superuser",
    )

    outcome = sync_authorization(user, _claims("never-provisioned-staff"))

    assert outcome.is_staff is False
    assert outcome.ignored == ("never-provisioned-staff",)
    assert not Group.objects.filter(name="never-provisioned-staff").exists()
