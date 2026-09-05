"""The audited override against real tables: what it writes, and what it undoes.

`tests/unit/django_apps/test_identity_overrides.py` holds the declarations and
every refusal that fires before the first query -- each of those reaches its
refusal in a process where a query would raise, which is the property being
asserted as much as the message is. Everything here needs a row to have been
written, a constraint to have refused, or a transaction to have rolled back, and
none of the three is decidable from `_meta`.

**`IDENTITY.05-INT-001` is the reason this module exists.** `CPM-AD-14` requires
the correction and its audit row to be one atomic unit, and risk `R-07` is what
happens when they are not: a corrected package with no record of who corrected
it, or an audit row for a correction that never landed. Three cases carry it and
they are deliberately not three spellings of one claim.
`test_a_failure_writing_the_audit_row_rolls_the_correction_back` is the load-
bearing one: both rows are *really* written and the transaction then fails, so
both directions are asserted where both writes actually happened.
`test_a_failure_between_the_two_writes_rolls_the_correction_back` covers the
other place the pair can break, and says in its own docstring which of its
assertions is trivially true given the write order.
`test_the_correction_is_written_before_the_audit_row` pins that order, because
"the audit row cannot survive alone" rests on it as much as on the transaction --
and nothing asserted it.

**On the shape of the injected failures.** Both rollback cases raise a
hand-constructed `DatabaseError` after the real write, which is
`tests/integration/django_apps/test_run_ledger.py`'s idiom and is chosen for its
reason: reproducing a genuine driver error inside the test's own transaction
needs a real constraint violation, which then has to be unwound before anything
can be queried. The one thing an injected error does not reproduce is
`connection.needs_rollback`, which a driver error sets and which changes what
happens to code that *catches* inside the block. `override_identity` catches
nothing, so the two are equivalent here -- and if it ever grows a handler, that
is the day this note stops being true and the cases need a real violation.

**The append-only refusals are asserted here rather than only in the base's own
tests.** `tests/unit/django_apps/test_append_only_model.py` proves the guard
against fixture models; what it cannot prove is that `identity_overrides` is
behind it, and `ProtectedError` on the actor is a database guarantee that only a
database can demonstrate.

**Refusals that raise `IntegrityError` or `ProtectedError` are asserted inside
`transaction.atomic()`,** for the reason
`tests/integration/django_apps/test_identity_models.py` gives at length: such a
statement marks pytest-django's per-test transaction broken, so an unwrapped
`pytest.raises` passes and then fails the teardown of a case that had nothing
wrong with it.

No `connection.vendor` branch and no assertion on a constraint's message. The
suite runs on the sqlite fallback and `pixi run gate-postgres` runs the same cases
against `postgres:17`; the exception types are what both raise, and they are the
whole claim.

Every case rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import DatabaseError
from django.db import transaction
from django.db.models import ProtectedError
from opentelemetry import trace

from conda_package_supply_chain_monitor.collectors.models import InventorySnapshot
from conda_package_supply_chain_monitor.collectors.selection import unresolved_packages
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.ledger import TRACE_ID_FORMAT
from conda_package_supply_chain_monitor.core.models import AppendOnlyError
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.roles import IDENTITY_OVERRIDE_PERMISSION
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import Feedstock
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import IdentityOverride
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import PackageMapping
from conda_package_supply_chain_monitor.identity.services import OVERRIDE_PERMISSION_MISSING
from conda_package_supply_chain_monitor.identity.services import OVERRIDE_RECORDED_EVENT
from conda_package_supply_chain_monitor.identity.services import OVERRIDE_REFUSED_EVENT
from conda_package_supply_chain_monitor.identity.services import Correction
from conda_package_supply_chain_monitor.identity.services import OverrideError
from conda_package_supply_chain_monitor.identity.services import Resolution
from conda_package_supply_chain_monitor.identity.services import override_identity
from conda_package_supply_chain_monitor.identity.services import record_resolution
from conda_package_supply_chain_monitor.identity.services import resolve_package_shell
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.factories import UserFactory

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from django_service.users.models import User

#: What the inventory source is called and what it files the package under. Any
#: two strings would do; what matters is that they are the pair both other doors
#: find the package by, so a case can assert they are byte-identical afterwards.
AN_IDENTITY_SOURCE: Final[str] = "internal-inventory"
A_SOURCE_KEY: Final[str] = "svc/numpy"
ANOTHER_SOURCE_KEY: Final[str] = "svc/numpy-legacy"

#: What the source called the package, and what a reviewer corrects it to.
THE_SOURCE_NAME: Final[str] = "numpy-internal"
THE_CORRECTED_NAME: Final[str] = "numpy"
A_DISPLAY_NAME: Final[str] = "NumPy"

#: Why. Non-blank, because `CPM-AD-14` requires a reason and the service refuses
#: a blank one before it writes anything.
A_REASON: Final[str] = "the resolver matched the wrong PyPI project; this is the upstream numpy"
ANOTHER_REASON: Final[str] = "confirmed against the conda-forge feedstock"

#: The identity-provider subjects the two actors carry. Distinct, so a log record
#: naming one cannot be mistaken for the other.
A_LEADER_SUBJECT: Final[str] = "urn:example:principal:a-leader"
AN_OUTSIDER_SUBJECT: Final[str] = "urn:example:principal:an-outsider"

#: Every mapping kind answered `not_found`, which is the smallest well-formed
#: resolution `record_resolution` accepts. Built per call rather than shared,
#: because `Resolution` takes it as a mapping and a shared dict is one a case
#: could mutate for every case after it.
_NOTHING_ESTABLISHED: Final[dict[str, str]] = dict.fromkeys(MappingKind.values, OutcomeState.NOT_FOUND.value)

#: How many audit rows one correction followed by one confirmation leaves. Named
#: rather than written as a literal because the number *is* the claim: a
#: confirmation that changed nothing is still a decision, and a door that wrote no
#: row for it would leave one.
A_CORRECTION_AND_A_CONFIRMATION: Final[int] = 2


@pytest.fixture
def stopped_clock() -> FixedClock:
    """A clock stopped at `tests.clocks.FIXED_INSTANT`.

    Constructed and passed exactly as production code does, for the reason
    `tests/integration/django_apps/test_run_ledger.py` gives: time is a
    *parameter*, and an integration case supplies its clock rather than inheriting
    a fixture the unit tier declares.

    Returns:
        A clock every reader handed it observes the same instant from.

    """
    return FixedClock(instant=FIXED_INSTANT)


@pytest.fixture
def a_package(db: None, stopped_clock: FixedClock) -> Package:
    """One package, created the only way `CPM-AD-25` permits one to be created.

    Through `resolve_package_shell` rather than `Package.objects.create`, because
    the join key is what several cases below are about: the shell carries the
    `(identity_source, associator_key)` pair a real ingestion sweep would have
    given it, and a case asserting the pair is untouched afterwards would prove
    nothing about a row that never had one.

    Args:
        db: pytest-django's per-test transaction.
        stopped_clock: The clock the shell's `resolved_at` comes from.

    Returns:
        The shell, at `unmapped` confidence and with no mapping of any kind.

    """
    return resolve_package_shell(
        source_package_key=A_SOURCE_KEY,
        package_name=THE_SOURCE_NAME,
        identity_source=AN_IDENTITY_SOURCE,
        clock=stopped_clock,
    )


@pytest.fixture
def a_leader(db: None) -> User:
    """A user who holds the override permission, by membership and by nothing else.

    Put in the group `settings.ROLE_CONTRACT` names for the leadership slot, which
    `core/0004_grant_identity_override` attached the permission to when the test
    database was built. Nothing here grants a permission directly: the whole point
    is that a *membership* is what confers it, which is `CPM-FR-30`'s contract and
    is the path a real person arrives by.

    Re-read from the database after the membership is added, because Django caches
    a user's permissions on the instance the first time it resolves them -- so an
    instance that had been asked before joining would answer from that cache.

    Args:
        db: pytest-django's per-test transaction.

    Returns:
        A user `has_perm(IDENTITY_OVERRIDE_PERMISSION)` answers True for.

    """
    user: User = UserFactory.create(username="a-leader", idp_subject=A_LEADER_SUBJECT)
    user.groups.add(Group.objects.get(name=settings.ROLE_CONTRACT.leadership))
    refreshed: User = get_user_model().objects.get(pk=user.pk)
    assert refreshed.has_perm(IDENTITY_OVERRIDE_PERMISSION), (
        "the leadership group must confer the override permission for these cases to mean anything"
    )
    return refreshed


@pytest.fixture
def an_outsider(db: None) -> User:
    """A real, active, saved user in no role group at all.

    Deliberately not the unit module's inactive stand-in: this one is refused by
    resolving its permissions against real rows and finding none, which is the
    path a person who simply has not been given the role arrives by -- and the
    only path that shows the grant is doing the work rather than `is_active`.

    Args:
        db: pytest-django's per-test transaction.

    Returns:
        A user holding no permission.

    """
    user: User = UserFactory.create(username="an-outsider", idp_subject=AN_OUTSIDER_SUBJECT)
    return user


def _a_resolution(*, confidence: str, canonical_name: str = "") -> Resolution:
    """Return a well-formed resolution that establishes nothing.

    `record_resolution` refuses a confidence above `unmapped` that rests on no
    established mapping, so anything above it here would be refused for a reason
    that is not what the case is about. Every case using this is about what
    happens to an *already overridden* package when a resolver reaches it again.

    Args:
        confidence: What the resolution claims.
        canonical_name: A corrected name, or blank for none.

    Returns:
        The resolution, keyed at the fixture package's pair.

    """
    return Resolution(
        identity_source=AN_IDENTITY_SOURCE,
        associator_key=A_SOURCE_KEY,
        confidence=confidence,
        outcomes=dict(_NOTHING_ESTABLISHED),
        canonical_name=canonical_name,
    )


# ---------------------------------------------------------------------------
# AC 1 and AC 2: the permitted override, and the refused one.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_permitted_override_corrects_the_package_and_records_one_audit_row(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """AC 1: the correction lands at `verified`, and exactly one row says who and why.

    "Exactly one" is asserted rather than "at least one": an override is a single
    human decision, and a door that wrote a row per changed field would split that
    decision across rows an auditor has to read back together to reconstruct it.

    The instant is asserted against the clock rather than against a range, which
    is the whole reason the clock is injected (`CPM-AD-26`): a row stamped from the
    process wall clock would pass any assertion about elapsed time and would make
    every later staleness question a statement about how long this test took.
    """
    override = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
            display_name=A_DISPLAY_NAME,
        ),
        clock=stopped_clock,
    )

    a_package.refresh_from_db()
    assert a_package.canonical_name == THE_CORRECTED_NAME
    assert a_package.display_name == A_DISPLAY_NAME
    assert a_package.confidence == IdentityConfidence.VERIFIED.value
    assert a_package.resolved_at == FIXED_INSTANT

    rows = list(IdentityOverride.objects.filter(package=a_package))
    assert rows == [override]
    assert (rows[0].actor_id, rows[0].observed_at, rows[0].reason) == (a_leader.pk, FIXED_INSTANT, A_REASON)
    assert (rows[0].prior_canonical_name, rows[0].new_canonical_name) == (THE_SOURCE_NAME, THE_CORRECTED_NAME)
    assert (rows[0].prior_display_name, rows[0].new_display_name) == ("", A_DISPLAY_NAME)


@pytest.mark.django_db
def test_the_confidence_rises_and_the_row_records_what_it_rose_from(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """The second matrix row: `verified`, and the prior confidence kept beside it.

    `CPM-AD-4` describes `verified` as an identity a person established, so an
    override raising it is the definition rather than a side effect. What makes
    the pair worth storing is the other half: an auditor asking "was this package
    speaking for itself before a human looked at it" needs the value the
    correction replaced, and the package row no longer holds it.
    """
    assert a_package.confidence == IdentityConfidence.UNMAPPED.value

    override = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )

    a_package.refresh_from_db()
    assert a_package.confidence == IdentityConfidence.VERIFIED.value
    assert override.prior_confidence == IdentityConfidence.UNMAPPED.value
    assert override.new_confidence == IdentityConfidence.VERIFIED.value


@pytest.mark.django_db
def test_an_actor_without_the_permission_is_refused_and_writes_nothing(
    a_package: Package,
    an_outsider: User,
    stopped_clock: FixedClock,
    captured_identity_service_logs: list[dict[str, Any]],
) -> None:
    """AC 2, against real rows: refused, nothing written, and the log names the actor.

    The unit module asserts the same refusal against an actor no backend can
    admit. This one asserts it against a real saved user whose permissions are
    resolved against real `auth_permission` and `auth_group` rows and come back
    empty -- which is the only version of the case that shows the *grant* is doing
    the work rather than something about the instance.

    "Nothing written" is asserted on both sides: the package is byte-identical and
    the audit table is empty. A door that logged and raised after correcting the
    package would satisfy the refusal and none of `CPM-AD-14`.
    """
    before = Package.objects.filter(pk=a_package.pk).values().get()

    with pytest.raises(OverrideError, match=IDENTITY_OVERRIDE_PERMISSION):
        override_identity(
            package_id=a_package.pk,
            actor=an_outsider,
            correction=Correction(
                reason=A_REASON,
                canonical_name=THE_CORRECTED_NAME,
            ),
            clock=stopped_clock,
        )

    assert Package.objects.filter(pk=a_package.pk).values().get() == before
    assert IdentityOverride.objects.count() == 0
    assert [event["event"] for event in captured_identity_service_logs] == [OVERRIDE_REFUSED_EVENT]
    assert captured_identity_service_logs[0]["reason"] == OVERRIDE_PERMISSION_MISSING
    assert captured_identity_service_logs[0]["idp_subject"] == AN_OUTSIDER_SUBJECT
    assert captured_identity_service_logs[0]["user_id"] == an_outsider.pk


@pytest.mark.django_db
def test_a_blank_reason_leaves_the_package_and_the_audit_table_alone(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """The refusal a permitted actor can still meet, with the rows there to be changed.

    The unit module proves the check runs before any query. This proves the thing
    that actually matters to the package: a permitted actor with a blank reason
    changes nothing, so a reviewer who submits the modal without filling the field
    has not silently half-corrected a row.
    """
    before = Package.objects.filter(pk=a_package.pk).values().get()

    with pytest.raises(OverrideError, match="needs a reason"):
        override_identity(
            package_id=a_package.pk,
            actor=a_leader,
            correction=Correction(
                reason="   ",
                canonical_name=THE_CORRECTED_NAME,
            ),
            clock=stopped_clock,
        )

    assert Package.objects.filter(pk=a_package.pk).values().get() == before
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_an_unknown_package_is_refused_rather_than_created(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """`CPM-AD-25`: resolution is the only creator of a package row.

    An override that quietly created what it could not find would give the product
    a second creator -- and the row it made would carry no `identity_source` and no
    `associator_key`, so the next inventory sweep would create a shell beside it
    and every later observation would hang off whichever the sweep found first.

    The fixture package exists so the count assertion is about *this* id being
    refused rather than about a table nothing has ever written to.
    """
    missing = a_package.pk + 1_000

    with pytest.raises(OverrideError, match="nothing to override"):
        override_identity(
            package_id=missing,
            actor=a_leader,
            correction=Correction(
                reason=A_REASON,
                canonical_name=THE_CORRECTED_NAME,
            ),
            clock=stopped_clock,
        )

    assert list(Package.objects.values_list("pk", flat=True)) == [a_package.pk]
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_a_correction_onto_a_taken_name_is_refused_and_names_the_collision(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """Two shells converging on one upstream package is what correction is *for*.

    `canonical_name` is `unique=True`, so without the check the collision escapes
    as an `IntegrityError` from inside the transaction: the audit row rolls back
    correctly and the actor is told a constraint name rather than which package
    already holds the name they typed. Merging the two rows decides which
    associator key survives and which evidence moves, and that is not something a
    name correction can express.
    """
    other = resolve_package_shell(
        source_package_key=ANOTHER_SOURCE_KEY,
        package_name=THE_CORRECTED_NAME,
        identity_source=AN_IDENTITY_SOURCE,
        clock=stopped_clock,
    )

    with pytest.raises(OverrideError, match="already another package's canonical name"):
        override_identity(
            package_id=a_package.pk,
            actor=a_leader,
            correction=Correction(
                reason=A_REASON,
                canonical_name=THE_CORRECTED_NAME,
            ),
            clock=stopped_clock,
        )

    a_package.refresh_from_db()
    other.refresh_from_db()
    assert a_package.canonical_name == THE_SOURCE_NAME
    assert other.canonical_name == THE_CORRECTED_NAME
    assert IdentityOverride.objects.count() == 0


# ---------------------------------------------------------------------------
# AC 5: the join key is what the next sweep finds the package by.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_join_key_is_byte_identical_after_a_successful_override(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """AC 5, and the fourth of the five conditions `CPM-IDENTITY-S06`'s review recorded.

    Both other doors find a package by `(identity_source, associator_key)`.
    Rewriting either while correcting a name orphans the package from its
    inventory source, and the next sweep -- finding nothing under the key it filed
    the package under -- creates a second shell. Nothing fails at the correction;
    the symptom is duplicated evidence days later.

    Asserted as byte equality rather than as truthiness, because the failure this
    guards against is a value being *changed*, and a check that the field is still
    non-empty would pass on a rewritten one.
    """
    before = (a_package.identity_source, a_package.associator_key)

    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
            display_name=A_DISPLAY_NAME,
        ),
        clock=stopped_clock,
    )

    a_package.refresh_from_db()
    assert (a_package.identity_source, a_package.associator_key) == before


@pytest.mark.django_db
def test_the_next_sweep_still_finds_the_package_it_corrected(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """The consequence of the case above, composed end to end.

    The join key surviving is only interesting because of what it buys, and what
    it buys is this: the inventory sweep that named the package under its own key
    yesterday finds the *same row* today, after a reviewer renamed it. A case that
    asserted the columns and stopped would still pass if the lookup had moved back
    onto the correctable name.
    """
    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )

    found = resolve_package_shell(
        source_package_key=A_SOURCE_KEY,
        package_name=THE_SOURCE_NAME,
        identity_source=AN_IDENTITY_SOURCE,
        clock=FixedClock(instant=LATER_INSTANT),
    )

    assert found.pk == a_package.pk
    assert Package.objects.count() == 1
    assert found.canonical_name == THE_CORRECTED_NAME


# ---------------------------------------------------------------------------
# AC 3: `IDENTITY.05-INT-001`, in both directions.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_failure_writing_the_audit_row_rolls_the_correction_back(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`R-07`: both rows are genuinely written, the transaction then fails, and neither survives.

    **This is the case that carries the claim, and it is the one where both writes
    have really happened.** The failure is injected *after* the real insert rather
    than in place of it, so at the moment the error is raised the corrected package
    row and the audit row are both present in the transaction -- and what is
    asserted is that afterwards neither is. Nothing about that is true by
    construction: replace `with transaction.atomic():` with `if True:` and this
    case fails, which is what makes it a test of the transaction rather than of the
    write order.

    Both halves of `CPM-FR-32` are in the two assertions below and they are
    different failures. A correction that outlived its audit row is a governed
    value changed by a person the record cannot name. An audit row that outlived
    its correction tells an auditor a value was changed when it was not, and marks
    the package reviewed forever.

    On the shape of the injected error, see the module docstring: a hand-raised
    `DatabaseError` does not set `connection.needs_rollback` the way a driver error
    does, and it does not need to, because nothing in `override_identity` catches
    anything.
    """
    original = IdentityOverride.save

    def flaky(self: IdentityOverride, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)  # type: ignore[arg-type]
        message = "the audit row could not be written"
        raise DatabaseError(message)

    monkeypatch.setattr(IdentityOverride, "save", flaky)

    with pytest.raises(DatabaseError, match="audit row"):
        override_identity(
            package_id=a_package.pk,
            actor=a_leader,
            correction=Correction(
                reason=A_REASON,
                canonical_name=THE_CORRECTED_NAME,
            ),
            clock=stopped_clock,
        )

    # Undone before the assertions for the reason the sibling case gives: the
    # patched `save` is still in place, and a later read that happened to write
    # would raise from the patch rather than from anything under test.
    monkeypatch.undo()
    a_package.refresh_from_db()
    assert a_package.canonical_name == THE_SOURCE_NAME
    assert a_package.confidence == IdentityConfidence.UNMAPPED.value
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_a_failure_between_the_two_writes_rolls_the_correction_back(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`R-07`, the other place the pair can break: between the first write and the second.

    The correction is written for real and the failure is raised immediately
    after, so the audit insert is never reached. What is under test is the
    *correction's* rollback: the package row genuinely carried the new name inside
    the transaction and does not afterwards.

    **What this case does not prove, stated rather than implied.** Its
    `IdentityOverride.objects.count() == 0` is true of any implementation, because
    the audit insert follows the correction and was never attempted -- the case is
    honest about that rather than claiming a second direction it does not have.
    The direction where an audit row exists and the transaction then fails is the
    case above, where the insert really happens. What makes *this* ordering a fact
    rather than an accident is `test_the_correction_is_written_before_the_audit_row`
    below; without it, "the audit row cannot survive alone" would rest on a
    property nothing asserted.
    """
    original = Package.save

    def flaky(self: Package, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)  # type: ignore[arg-type]
        message = "the correction could not be written"
        raise DatabaseError(message)

    monkeypatch.setattr(Package, "save", flaky)

    with pytest.raises(DatabaseError, match="correction"):
        override_identity(
            package_id=a_package.pk,
            actor=a_leader,
            correction=Correction(
                reason=A_REASON,
                canonical_name=THE_CORRECTED_NAME,
            ),
            clock=stopped_clock,
        )

    # Undone before the assertions because `refresh_from_db` and the count below
    # run against a model whose `save` is still patched, and a fixture teardown
    # that wrote would raise the injected error instead of the real one.
    monkeypatch.undo()
    a_package.refresh_from_db()
    assert a_package.canonical_name == THE_SOURCE_NAME
    assert a_package.confidence == IdentityConfidence.UNMAPPED.value
    assert IdentityOverride.objects.count() == 0


@pytest.mark.django_db
def test_the_correction_is_written_before_the_audit_row(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The write order the pair's failure modes are argued from, pinned as a fact.

    "The audit row cannot survive its correction" is true of this door for two
    independent reasons: the transaction, and the order -- the correction is
    written first, so a failure before the audit insert has nothing to leave
    behind. The transaction is asserted above. The *order* was not asserted
    anywhere, which meant one of the two reasons the pair holds was resting on
    nobody having reversed two statements.

    It is worth pinning in its own right rather than only as scaffolding for those
    cases: the audit row records `new_canonical_name` by reading the package back
    after `_write_correction` has applied it, so reversing the two would make every
    audit row record the *prior* value in both halves of every pair.
    """
    order: list[str] = []
    write_package, write_override = Package.save, IdentityOverride.save

    def note_package(self: Package, *args: object, **kwargs: object) -> None:
        order.append("correction")
        write_package(self, *args, **kwargs)  # type: ignore[arg-type]

    def note_override(self: IdentityOverride, *args: object, **kwargs: object) -> None:
        order.append("audit")
        write_override(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Package, "save", note_package)
    monkeypatch.setattr(IdentityOverride, "save", note_override)

    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=A_REASON, canonical_name=THE_CORRECTED_NAME),
        clock=stopped_clock,
    )

    monkeypatch.undo()
    assert order == ["correction", "audit"]


# ---------------------------------------------------------------------------
# AC 4: the row is append-only, and the actor cannot be deleted.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_written_audit_row_refuses_to_be_re_saved(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """`CPM-FR-32`'s "append-only", enforced by the base rather than by intention.

    Rewriting the reason after the fact is the whole failure: the audit trail would
    then say something other than what the person decided, and nothing would record
    that it had changed. The base refuses on the primary key being set, so the
    refusal reaches every re-save spelling rather than only the one a case thought
    of.
    """
    override = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )
    override.reason = ANOTHER_REASON

    with pytest.raises(AppendOnlyError):
        override.save()

    assert IdentityOverride.objects.get(pk=override.pk).reason == A_REASON


@pytest.mark.django_db
def test_a_written_audit_row_refuses_to_be_deleted_or_updated_through_its_queryset(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """The two spellings somebody reaches for once `save()` has refused.

    `delete()` on the instance, and `update()` on the queryset. The second is the
    one that would otherwise work: `AppendOnlyModel.save` cannot see a queryset,
    so the refusal has to come from the manager -- which is why the base names
    `objects` as its `base_manager_name` and why this case asserts the queryset
    spelling rather than only the instance one.
    """
    override = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )

    with pytest.raises(AppendOnlyError):
        override.delete()
    with pytest.raises(AppendOnlyError):
        IdentityOverride.objects.filter(pk=override.pk).update(reason=ANOTHER_REASON)

    assert IdentityOverride.objects.get(pk=override.pk).reason == A_REASON


@pytest.mark.django_db
def test_the_actor_cannot_be_deleted_while_a_correction_names_them(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """`PROTECT`, and it is the database that refuses rather than the model.

    Django's deletion collector issues its `DELETE` through `sql.DeleteQuery`,
    never through `Model.delete()`, so `CASCADE` here would take audit rows with
    the user and every append-only refusal in `core/models.py` would be bypassed
    on the way. `PROTECT` makes the attempt fail instead -- which is the only
    behaviour compatible with an audit trail that outlives the account of the
    person it names.

    Asserted inside `transaction.atomic()` for the reason the module docstring
    gives: the refusal marks the per-test transaction broken.
    """
    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )

    with transaction.atomic(), pytest.raises(ProtectedError):
        a_leader.delete()

    assert IdentityOverride.objects.count() == 1
    assert get_user_model().objects.filter(pk=a_leader.pk).exists()


# ---------------------------------------------------------------------------
# AC 6: the correction survives automated resolution, and leaves the queue.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_override_stands_against_a_later_lower_confidence_resolution(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """AC 6: surviving resolution needs no new mechanism, and proving it is the point.

    `record_resolution` already refuses to lower a `verified` confidence and
    refuses to overwrite the name that goes with it -- `CPM-IDENTITY-S02` built
    that branch and this story writes the value that reaches it. So the two
    stories agree by construction, and this asserts the agreement end to end
    rather than assuming it.

    The resolution is still *recorded*: its result says the claim was held back,
    which is what a collector logs per package. A door that discarded the whole
    resolution would lock every verified package out of every later collector.
    """
    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )

    recorded = record_resolution(
        resolution=_a_resolution(
            confidence=IdentityConfidence.UNMAPPED.value,
            canonical_name=THE_SOURCE_NAME,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    assert recorded.downgrade_refused is True
    a_package.refresh_from_db()
    assert a_package.canonical_name == THE_CORRECTED_NAME
    assert a_package.confidence == IdentityConfidence.VERIFIED.value


@pytest.mark.django_db
def test_an_overridden_package_leaves_the_review_queue(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """The last matrix row: the queue is the complement of `RESOLVED_CONFIDENCES`.

    `CPM-IDENTITY-S04`'s selection excludes `verified` and nothing else, so an
    override is what takes a package out of it -- and that is the loop the whole
    epic closes: the queue names a package, a reviewer corrects it, and it stops
    being named.

    The package is observed first so it is genuinely in the queue before the
    override, because a case whose subject was absent from the selection both
    before and after would assert nothing at all.
    """
    InventorySnapshot.objects.create(
        observed_at=FIXED_INSTANT,
        package=a_package,
        source_package_key=A_SOURCE_KEY,
        state=OutcomeState.OK.value,
        internal_component_count=3,
        internal_lob_count=1,
    )
    assert [selected.package.pk for selected in unresolved_packages(cutoff=LATER_INSTANT)] == [a_package.pk]

    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )

    assert unresolved_packages(cutoff=LATER_INSTANT) == []


# ---------------------------------------------------------------------------
# `CPM-FR-32`: the overrides are independently queryable.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_override_is_retrievable_as_a_set_newest_first(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """`CPM-FR-32`'s "independently queryable", across packages and across time.

    Three rows: two corrections of one package at two instants, and one of
    another. The second correction of the first package is what makes the
    ordering assertion mean something -- a table with one row per package would
    come back in the right order by accident -- and the second package is what
    makes it a *set* rather than one package's history.

    Nothing sorts the queryset here. The ordering is the model's, which is the
    claim: a caller that has to remember to order an audit trail is a caller that
    will eventually not.
    """
    later = FixedClock(instant=LATER_INSTANT)
    another = resolve_package_shell(
        source_package_key=ANOTHER_SOURCE_KEY,
        package_name="scipy-internal",
        identity_source=AN_IDENTITY_SOURCE,
        clock=stopped_clock,
    )

    first = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )
    second = override_identity(
        package_id=another.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name="scipy",
        ),
        clock=stopped_clock,
    )
    third = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=ANOTHER_REASON,
            display_name=A_DISPLAY_NAME,
        ),
        clock=later,
    )

    assert list(IdentityOverride.objects.all()) == [third, second, first]
    assert list(IdentityOverride.objects.filter(package=a_package)) == [third, first]


@pytest.mark.django_db
def test_an_override_that_changes_nothing_is_still_recorded(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """Confirming an identity is a decision, and the audit trail is about decisions.

    A reviewer who reads the queue, checks a package and concludes that what the
    inventory called it was right all along has made exactly the judgement
    `CPM-AD-4` means by `verified`. The row records it with both halves of every
    pair equal, which is what "nothing changed" looks like in an audit trail --
    and is a different fact from no row at all, which is what "nobody has looked"
    looks like.

    `resolved_at` is asserted *not* to have advanced on the second override, which
    is the other half of the rule `_write_identity` states: that column records
    when the identity last changed, and a confirmation changed nothing about it.
    """
    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
        ),
        clock=stopped_clock,
    )
    a_package.refresh_from_db()
    corrected_at = a_package.resolved_at

    confirmation = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=ANOTHER_REASON,
        ),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    a_package.refresh_from_db()
    assert a_package.resolved_at == corrected_at
    assert confirmation.prior_canonical_name == confirmation.new_canonical_name == THE_CORRECTED_NAME
    assert confirmation.prior_confidence == confirmation.new_confidence == IdentityConfidence.VERIFIED.value
    assert IdentityOverride.objects.count() == A_CORRECTION_AND_A_CONFIRMATION


# ---------------------------------------------------------------------------
# What is stored: normalisation, correlation, and the columns nothing may touch.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_supplied_value_is_stored_stripped(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """The normalisation, asserted on what is stored rather than only on what is refused.

    Every refusal case in this story submits a *wholly* blank value, and every
    accepted constant is already stripped -- so nothing exercised the strip at all,
    and deleting it from all three helpers passed the entire suite. That is not a
    cosmetic gap. `canonical_name` is `unique=True`: `" numpy "` and `"numpy"` are
    two rows to the database and one name to every person who reads them, so an
    unstripped correction slips past `_require_name_is_unclaimed`, past the unique
    index, and into every export as a near-duplicate of a package that already
    exists -- governed reference data acquiring two names for one thing through the
    product's one audited write, with nothing failing at the correction.

    All three fields at once, because they are three separate helpers with three
    separate `strip()` calls and one of them being deleted is the realistic edit.
    The audit row is asserted alongside the package: a row recording the padded
    value would say the reviewer typed something other than what was stored.
    """
    override = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=f"  {A_REASON}\n",
            canonical_name=f"  {THE_CORRECTED_NAME}  ",
            display_name=f"\t{A_DISPLAY_NAME} ",
        ),
        clock=stopped_clock,
    )

    a_package.refresh_from_db()
    assert a_package.canonical_name == THE_CORRECTED_NAME
    assert a_package.display_name == A_DISPLAY_NAME
    assert override.reason == A_REASON
    assert override.new_canonical_name == THE_CORRECTED_NAME
    assert override.new_display_name == A_DISPLAY_NAME


@pytest.mark.django_db
def test_a_whitespace_only_display_name_clears_it_rather_than_storing_spaces(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """`None`, `""` and `"   "` are three inputs and two meanings.

    `None` says the override made no statement about the display name. The empty
    string says there is not one, which PRD Appendix A.1's data rules make the
    honest spelling of missing. Whitespace is neither a name nor a statement of
    absence, and storing it would make the reporting layer's fallback to the
    canonical name stop firing for a value that renders as nothing -- a package
    that displays as a blank cell rather than as its name.

    Asserted against a display name that was set first, so the case is about
    clearing an existing value rather than about writing nothing over nothing.
    """
    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=A_REASON, display_name=A_DISPLAY_NAME),
        clock=stopped_clock,
    )

    cleared = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=ANOTHER_REASON, display_name="   "),
        clock=FixedClock(instant=LATER_INSTANT),
    )

    a_package.refresh_from_db()
    assert a_package.display_name == ""
    assert cleared.prior_display_name == A_DISPLAY_NAME
    assert cleared.new_display_name == ""


@pytest.mark.django_db
def test_the_audit_row_carries_the_trace_id_the_platform_would_log(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
    recorded_spans: InMemorySpanExporter,
) -> None:
    """`CPM-AD-15`, inside a real recording span rather than outside every span.

    Outside a span the column holds `""` -- which is also the column's default, so
    a door that never set `trace_id` at all would pass any assertion made outside
    one. Deleting `trace_id=current_trace_id()` from the insert passed this whole
    suite before this case existed, which is exactly that hole. The span is what
    makes the assertion mean something: the id is non-empty, and it is the one
    `config/observability/logging.py` would put on every log line of the request
    the correction was made in -- which is the join `CPM-AD-15` exists to provide
    between an audit row and the story of how it came to be written.

    The shape is `tests/integration/django_apps/test_inventory_ingestion.py`'s,
    including reading the exported spans at the end: that is what makes "a real
    recording span" a fact rather than an assumption.

    Args:
        a_package: The package to correct.
        a_leader: An actor holding the permission.
        stopped_clock: The clock the instant comes from.
        recorded_spans: The in-memory exporter attached to the live provider.

    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("override") as span:
        expected = format(span.get_span_context().trace_id, TRACE_ID_FORMAT)
        override = override_identity(
            package_id=a_package.pk,
            actor=a_leader,
            correction=Correction(reason=A_REASON, canonical_name=THE_CORRECTED_NAME),
            clock=stopped_clock,
        )

    assert expected != ""
    assert override.trace_id == expected
    assert IdentityOverride.objects.get(pk=override.pk).trace_id == expected
    assert "override" in [recorded.name for recorded in recorded_spans.get_finished_spans()]


@pytest.mark.django_db
def test_an_override_outside_a_span_is_recorded_uncorrelated_rather_than_refused(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """`current_trace_id()` never raises, and nothing here branches on what it answers.

    An uncorrelated audit row is worth incomparably more than a refused
    correction: the person still decided, the reason is still recorded, and the
    only thing missing is the join to a request nobody can reconstruct anyway.
    Asserted so that a later "require a trace id" is a deliberate change rather
    than one somebody makes to tidy the column.
    """
    override = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=A_REASON, canonical_name=THE_CORRECTED_NAME),
        clock=stopped_clock,
    )

    assert override.trace_id == ""
    assert IdentityOverride.objects.count() == 1


@pytest.mark.django_db
def test_the_correction_writes_only_the_columns_it_names(
    a_package: Package,
    a_leader: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The join key stays out of `update_fields` by construction, captured at the call.

    The unit module sweeps the writer's source for the two column names, resolving
    the module constants it addresses them through. This is the other half and the
    one that cannot be fooled by a value assembled at runtime: the `update_fields`
    the writer actually hands to `save()` is what decides which columns the UPDATE
    touches, so capturing it is capturing the answer rather than an argument about
    it.

    A full `save()` -- one with `update_fields=None` -- writes all thirteen
    columns, `identity_source` and `associator_key` included, from whatever the
    in-memory instance holds. That is the failure this pins: it would look correct
    in every ordinary case, because the instance holds the right values, and would
    break the moment two writers touched one row.
    """
    captured: list[object] = []
    original = Package.save

    def note(self: Package, *args: object, **kwargs: object) -> None:
        captured.append(kwargs.get("update_fields"))
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Package, "save", note)

    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(
            reason=A_REASON,
            canonical_name=THE_CORRECTED_NAME,
            display_name=A_DISPLAY_NAME,
        ),
        # A *later* clock than the shell's `resolved_at`, so the timestamp is in
        # the set as well: `_write_correction` only advances that column when the
        # instant is newer, and a case stamped at the shell's own instant would
        # assert a shorter list for a reason that has nothing to do with the join
        # key this is about.
        clock=FixedClock(instant=LATER_INSTANT),
    )

    monkeypatch.undo()
    assert captured == [["canonical_name", "confidence", "display_name", "resolved_at"]]


@pytest.mark.django_db
def test_an_override_leaves_the_mappings_the_feedstocks_and_the_rollup_alone(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
) -> None:
    """`_write_correction` names three columns of one row and reaches no other table.

    The mapping and feedstock rows were written under the identity this override
    has just replaced, and they stay exactly as they were -- which is the honest
    state rather than a defect. They are keyed on the package's integer primary key
    (`CPM-AD-3`), not on its name, so they still describe the same package; that
    they predate the correction is answerable from `PackageMapping.resolved_at`
    against the override's `observed_at`. Re-resolving under the corrected identity
    is a collector's job on the next sweep, and a door that invalidated findings on
    the strength of a name would be discarding evidence.

    Asserted as byte equality over the whole rows rather than as counts: a door
    that rewrote an outcome or blanked a URL would keep the counts and lose the
    finding.
    """
    Feedstock.objects.create(package=a_package, name="numpy-feedstock", url="https://example.invalid/f")
    PackageMapping.objects.create(
        package=a_package,
        kind=MappingKind.FEEDSTOCK.value,
        outcome=ESTABLISHED,
        resolved_at=FIXED_INSTANT,
    )
    before_feedstocks = list(Feedstock.objects.filter(package=a_package).values())
    before_mappings = list(PackageMapping.objects.filter(package=a_package).values())

    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=A_REASON, canonical_name=THE_CORRECTED_NAME),
        clock=stopped_clock,
    )

    assert list(Feedstock.objects.filter(package=a_package).values()) == before_feedstocks
    assert list(PackageMapping.objects.filter(package=a_package).values()) == before_mappings
    assert PackageHealth.objects.count() == 0


@pytest.mark.django_db
def test_a_correction_stamped_from_behind_does_not_move_resolved_at_backwards(
    a_package: Package,
    a_leader: User,
) -> None:
    """`resolved_at` records when the identity last changed, and time does not run back.

    Every other writer of this column takes its instant from a collector's own run
    clock, which advances. This door takes it from whoever is correcting the row,
    and a correction made against an earlier instant -- a replayed request, a
    backfill, two workers with skewed clocks -- would move the column backwards.
    Nothing would fail; every freshness read after it would simply judge the row
    older than it is, and `CPM-IDENTITY-S04`'s queue and every staleness consumer
    read that column.

    The correction itself still lands, which is the other half: the override is not
    refused for being stamped from behind, it just does not rewrite when the
    identity was last settled.
    """
    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=A_REASON, canonical_name=THE_CORRECTED_NAME),
        clock=FixedClock(instant=LATER_INSTANT),
    )
    a_package.refresh_from_db()
    assert a_package.resolved_at == LATER_INSTANT

    override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=ANOTHER_REASON, display_name=A_DISPLAY_NAME),
        clock=FixedClock(instant=FIXED_INSTANT),
    )

    a_package.refresh_from_db()
    assert a_package.display_name == A_DISPLAY_NAME
    assert a_package.resolved_at == LATER_INSTANT


# ---------------------------------------------------------------------------
# The two authorization events, and the one actor the permission check lets past.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_recorded_override_is_logged_naming_the_actor_and_the_row(
    a_package: Package,
    a_leader: User,
    stopped_clock: FixedClock,
    captured_identity_service_logs: list[dict[str, Any]],
) -> None:
    """`CPM-AD-13` makes every authorization change an event, and a success is one.

    Refusals were logged from the start and successes were not, which left an
    operator filtering `authorization.` able to see every *rejected* correction of
    governed reference data and not one accepted one -- the half an auditor asks
    about first, and the half that is a change rather than the absence of one.

    The event carries the audit row's own primary key, which is what makes the log
    line and the row joinable: an operator who sees the event can read the reason
    and the pair it replaced without searching by timestamp.
    """
    override = override_identity(
        package_id=a_package.pk,
        actor=a_leader,
        correction=Correction(reason=A_REASON, canonical_name=THE_CORRECTED_NAME),
        clock=stopped_clock,
    )

    assert [event["event"] for event in captured_identity_service_logs] == [OVERRIDE_RECORDED_EVENT]
    recorded = captured_identity_service_logs[0]
    assert recorded["user_id"] == a_leader.pk
    assert recorded["idp_subject"] == A_LEADER_SUBJECT
    assert recorded["package_id"] == a_package.pk
    assert recorded["override_id"] == override.pk


@pytest.mark.django_db
def test_a_superuser_reaches_the_write_without_the_grant_and_is_still_audited(
    a_package: Package,
    stopped_clock: FixedClock,
) -> None:
    """A recorded decision about the one actor the permission check does not gate.

    `PermissionsMixin.has_perm` returns True for any active superuser before it
    consults a backend, so a superuser corrects governed reference data without
    holding the leadership grant. `CPM-AD-14` says identity is mutated by
    resolution or the override path and nothing else, and this is neither a third
    path nor a hole in the second -- but it *is* a way past the permission, and a
    way past a permission that nobody wrote down is how it stops being one.

    So it is asserted rather than left to Django's default, in both halves. The
    superuser is admitted, for the reason `_require_permitted`'s docstring gives:
    the flag is the platform's break-glass, it already reaches the admin where the
    same rows are editable with no audit row at all, and a check refusing it here
    would make the product's one *audited* correction path the only thing
    unavailable during the incident where group synchronisation is what broke. And
    the write is still governed -- the audit row names them, at the same instant,
    with the same required reason -- which is the mitigation the flag does not
    bypass.

    Reverse this and the case fails, which is the point: whichever way the product
    decides, it decides here rather than by accident.
    """
    superuser: User = UserFactory.create(username="a-superuser", idp_subject="urn:example:principal:root")
    superuser.is_superuser = True
    superuser.save(update_fields=["is_superuser"])
    reread: User = get_user_model().objects.get(pk=superuser.pk)

    assert reread.groups.count() == 0

    override = override_identity(
        package_id=a_package.pk,
        actor=reread,
        correction=Correction(reason=A_REASON, canonical_name=THE_CORRECTED_NAME),
        clock=stopped_clock,
    )

    assert override.actor_id == superuser.pk
    assert override.reason == A_REASON
    assert IdentityOverride.objects.count() == 1
