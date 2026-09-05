"""The run ledger's shape and its handle, proved without a database.

`tests/integration/django_apps/test_run_ledger.py` proves what a real table does
with a recorded run -- the row that exists before finalization,
`EVIDENCE.03-INT-002`'s raising body, the null-package run in `unfinished()`.
Everything here is what does not need one: the handle's state machine, its
refusal of a second ending, `current_trace_id()` on both sides of "is a span
active", and the declared shape of the two models.

**The model assertions are not duplicating the audits.**
`tests/unit/django_apps/test_evidence_inheritance_audit.py` reconciles the
`not_evidence` escape against a recorded table, and
`tests/unit/django_apps/test_outcome_field_audit.py` checks the `status` column
against `RunState`. Both are sweeps: they say "every model that takes the escape
is recorded" and "every recorded field carries the right vocabulary". Neither
says the run ledger takes the escape *for the right reasons* -- that it declares
no `observed_at`, inherits no append-only refusal, and keeps the exemption on the
shared abstract base rather than on one of the two tables. Those are this
story's own claims and they are asserted here.

**A span is fabricated rather than started through the SDK.** `NonRecordingSpan`
over a hand-built `SpanContext` is API-only: no tracer provider is touched, no
processor runs, and nothing can attempt an export -- which is what keeps this a
unit test. The integration suite reads a *real* recorded span and checks the id
against the one the exporter saw, which is the half this cannot do.

No database and no network: nothing here saves a row, and the one queryset built
is never evaluated.
"""

from __future__ import annotations

from typing import Final

import pytest
from django.db import models
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan
from opentelemetry.trace import SpanContext
from opentelemetry.trace import TraceFlags

from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.ledger import NO_TRACE_ID
from conda_package_supply_chain_monitor.core.ledger import TRACE_ID_FORMAT
from conda_package_supply_chain_monitor.core.ledger import RunHandle
from conda_package_supply_chain_monitor.core.ledger import collection_run
from conda_package_supply_chain_monitor.core.ledger import current_trace_id
from conda_package_supply_chain_monitor.core.ledger import policy_run
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.core.models import RunLedgerModel
from conda_package_supply_chain_monitor.core.models import RunLedgerQuerySet
from conda_package_supply_chain_monitor.core.runs import TERMINAL_STATES
from conda_package_supply_chain_monitor.core.runs import RunLedgerError
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT
from tests.model_registry import OBSERVED_AT_FIELD

#: The evidence cut-off a constructed policy run carries. The suite's stopped
#: instant rather than a second literal, so nothing here can drift away from the
#: instant every other case in the project stops at.
A_CUT_OFF: Final = FIXED_INSTANT

#: A clock for the refusal cases, which never reach it.
#:
#: Every case below that constructs one is asserting that the recorder refuses
#: *before* it reads a clock or writes a row, so what the clock answers is beside
#: the point -- but a recorder takes one by parameter (`CPM-AD-26`) and there is
#: no default to fall back on, which is the whole design.
A_STOPPED_CLOCK: Final = FixedClock(instant=FIXED_INSTANT)

#: A trace id and a span id with no leading zero byte, so that a formatting bug
#: which dropped padding would still produce the right length and go unnoticed.
#: The values are arbitrary; what matters is that they are not round numbers.
A_TRACE_ID: Final[int] = 0x4BF92F3577B34DA6A3CE929D0E0E4736
A_SPAN_ID: Final[int] = 0x00F067AA0BA902B7

#: How wide `CPM-AD-15`'s trace id is once formatted. Asserted rather than
#: assumed: the row joins to a log line on this exact string, and a value of a
#: different width joins to nothing.
TRACE_ID_WIDTH: Final[int] = 32

#: The two concrete ledger tables, and the table name each must carry.
#: `CPM-AD-2` names both in so many words, so the names are a contract with the
#: architecture rather than a Django default.
LEDGER_TABLES: Final[dict[type[RunLedgerModel], str]] = {
    CollectionRun: "collection_runs",
    PolicyRun: "policy_runs",
}


def a_span_context() -> SpanContext:
    """Build a valid span context without touching a tracer provider.

    Returns:
        A sampled, non-remote context carrying `A_TRACE_ID` and `A_SPAN_ID`.
        Valid, which is what `current_trace_id` branches on.

    """
    return SpanContext(
        trace_id=A_TRACE_ID,
        span_id=A_SPAN_ID,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )


def field_of(model: type[models.Model], name: str) -> models.Field[object, object]:
    """Return one concrete field of a model by name.

    Args:
        model: The model to look in.
        name: The field's attribute name.

    Returns:
        The field, so a case can assert against its declaration.

    """
    return model._meta.get_field(name)  # type: ignore[return-value]  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


# ---------------------------------------------------------------------------
# The handle: what the body of a run says about how it went.
# ---------------------------------------------------------------------------


def test_a_fresh_handle_has_declared_nothing() -> None:
    """The ordinary path costs nothing to write, which is why `None` is the start.

    A body that returns without saying anything succeeded, and the recorder reads
    `None` as `RunState.SUCCEEDED`. A handle that started at `SUCCEEDED` would
    make "declared" and "not declared" indistinguishable, and the double-ending
    refusal below would then fire on the first honest call.
    """
    handle = RunHandle()

    assert handle.state is None
    assert handle.detail == ""


def test_a_handle_built_without_a_row_refuses_to_name_one() -> None:
    """`CPM-EVIDENCE-S07`'s passes reference the run, and a bare handle has none.

    The recorder builds the row and hands it to the handle, which is the only way
    a body can key its own writes to the run it is inside -- a caller that went
    looking for "the newest running row" would find a different row the moment
    two runs overlap. A bare `RunHandle()` exists only to exercise the
    declaration rules below, so it refuses rather than answering `None`: every
    product caller reaches this through a recorder, and a `None` would push all
    of them into a check none of them needs.
    """
    with pytest.raises(RunLedgerError, match="constructed without a ledger row"):
        _ = RunHandle().run


@pytest.mark.parametrize(
    ("declare", "expected"),
    [
        ("succeeded", RunState.SUCCEEDED),
        ("partial", RunState.PARTIAL),
        ("skipped", RunState.SKIPPED),
        ("failed", RunState.FAILED),
    ],
    ids=["succeeded", "partial", "skipped", "failed"],
)
def test_each_declaration_records_its_state_and_its_detail(declare: str, expected: RunState) -> None:
    """One case per ending the handle offers, and each is a state the row can hold.

    Parametrized rather than written four times because the four are the same
    operation: the point of the case is that the *set* is complete and that each
    name maps to the state it says it does, not that any one of them works.
    """
    handle = RunHandle()

    getattr(handle, declare)(detail="3 of 5 sources answered")

    assert handle.state is expected
    assert handle.state in TERMINAL_STATES
    assert handle.detail == "3 of 5 sources answered"


def test_a_declaration_needs_no_detail() -> None:
    """Detail is optional, because a plain success has nothing to explain.

    Requiring one would push callers toward a placeholder string, and a column
    full of "ok" is worse than an empty one.
    """
    handle = RunHandle()

    handle.succeeded()

    assert handle.state is RunState.SUCCEEDED
    assert handle.detail == ""


def test_a_second_ending_is_refused_and_names_both_states() -> None:
    """The I/O matrix's last row: `succeeded()` then `failed()` refuses.

    Both states are in the message on purpose. "This run was already finalized"
    sends a reader hunting for the first call; naming `succeeded` and `failed`
    tells them what to look for, and the exception is raised at the call site
    where the contradiction was written.
    """
    handle = RunHandle()
    handle.succeeded()

    with pytest.raises(RunLedgerError, match="already declared succeeded") as refusal:
        handle.failed(detail="on second thoughts")

    assert "failed" in str(refusal.value)
    assert handle.state is RunState.SUCCEEDED
    assert handle.detail == ""


def test_a_second_ending_is_refused_even_when_it_repeats_the_first() -> None:
    """Declaring the same state twice is still a caller contradicting itself.

    Permitting the repeat would mean the guard was about the *value* rather than
    about the run having ended, and the first thing that would slip through is a
    loop calling `partial()` once per package.
    """
    handle = RunHandle()
    handle.partial(detail="first")

    with pytest.raises(RunLedgerError, match="already declared partial"):
        handle.partial(detail="second")

    assert handle.detail == "first"


def test_the_body_cannot_reach_the_override_the_recorder_uses() -> None:
    """The exception override is the recorder's half of the handle, not the body's.

    It is the one method that *replaces* a declaration instead of refusing to, so
    a body able to call it could quietly rewrite its own ending -- and could do it
    twice, which the public methods forbid. The name is checked here rather than
    left to review: renaming it back to a public spelling should be a failing
    test, not a diff nobody reads twice.

    What it does when the recorder calls it is proved where it happens, in
    `tests/integration/django_apps/test_run_ledger.py`: the row of a body that
    declared `partial` and then raised says `failed`.
    """
    handle = RunHandle()

    assert not hasattr(handle, "raised")
    assert callable(handle._raised)  # noqa: SLF001 - the name under test is precisely that it is private


# ---------------------------------------------------------------------------
# The correlation identifier, on both sides of "is a span active".
# ---------------------------------------------------------------------------


def test_the_trace_id_is_the_active_spans_id_formatted_as_the_platform_formats_it() -> None:
    """`CPM-AD-15`: the row and the log line join on the same string.

    `config/observability/logging.py` writes `format(trace_id, "032x")` on every
    log line. A ledger row carrying anything else -- an int, a different width, a
    scheme of the product's own -- is a row nobody can pivot from.
    """
    with trace.use_span(NonRecordingSpan(a_span_context()), end_on_exit=False):
        found = current_trace_id()

    assert found == format(A_TRACE_ID, TRACE_ID_FORMAT)
    assert len(found) == TRACE_ID_WIDTH
    assert found == found.lower()


def test_the_trace_id_is_empty_when_no_span_is_active() -> None:
    """The I/O matrix's "No active span" row: recorded, never blocked.

    A collector run from a management command, or a process with the SDK
    disabled, has no span. The run still happened and the row is still worth
    having, so the absence is recorded as the empty string rather than raised or
    faked.
    """
    assert current_trace_id() == NO_TRACE_ID


# ---------------------------------------------------------------------------
# The models: mutable, not evidence, and shaped as the architecture says.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", list(LEDGER_TABLES), ids=lambda model: model.__name__)
def test_a_ledger_model_declares_the_exemption_rather_than_inheriting_a_refusal(
    model: type[RunLedgerModel],
) -> None:
    """`CPM-AD-2`'s exemption, at the definition and in the form the audits read.

    Three claims, and each fails a different way if it is dropped. Without
    `not_evidence` the model is audited as evidence and the sweep demands a base
    that would refuse its own finalization. Inheriting `AppendOnlyModel` would
    make the second `save()` raise, which is the whole recorder. Declaring
    `observed_at` would make it evidence by the third mark -- a run row is not an
    observation, and `CPM-AD-7` fixes that column's meaning as the moment of
    *this* observation.
    """
    assert model.not_evidence is True
    assert not issubclass(model, AppendOnlyModel)
    assert OBSERVED_AT_FIELD not in {
        field.name
        for field in model._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    }


def test_the_exemption_is_declared_once_on_the_shared_base() -> None:
    """One declaration, inherited, rather than two that can drift apart.

    A per-table copy is how one of the two ledgers eventually loses it: the
    second table is added by somebody reading the first, and `not_evidence` is
    one line among many. It is on `RunLedgerModel`, which both inherit, and that
    is asserted rather than left to look accidental.
    """
    assert RunLedgerModel.not_evidence is True
    assert "not_evidence" in vars(RunLedgerModel)
    assert "not_evidence" not in vars(CollectionRun)
    assert "not_evidence" not in vars(PolicyRun)


@pytest.mark.parametrize("model", list(LEDGER_TABLES), ids=lambda model: model.__name__)
def test_a_ledger_model_uses_the_table_name_the_architecture_names(model: type[RunLedgerModel]) -> None:
    """`collection_runs` and `policy_runs`, not Django's derived defaults.

    `CPM-AD-2` names both tables, and so does the PRD appendix it supersedes. A
    derived `core_collectionrun` would leave every document in the project
    naming a table that does not exist.
    """
    assert model._meta.db_table == LEDGER_TABLES[model]  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


@pytest.mark.parametrize("model", list(LEDGER_TABLES), ids=lambda model: model.__name__)
def test_a_ledger_row_starts_running_and_finishes_nowhere(model: type[RunLedgerModel]) -> None:
    """The two columns the killed-worker guarantee is made of.

    `status` defaults to `running` so a row inserted before the first outbound
    call is already truthful, and `finished_at` is nullable so that "not
    finalized" is representable at all. A non-null `finished_at` would force the
    recorder to write a placeholder instant at insert, and every unfinished run
    would then look finished.
    """
    status = field_of(model, "status")
    finished_at = field_of(model, "finished_at")

    assert status.default == RunState.RUNNING
    assert list(status.choices or ()) == list(RunState.choices)
    assert status.null is False
    assert finished_at.null is True
    # `CharField` and `blank is False` are checked *here* because they are
    # checked nowhere else: `RECORDED_RUN_LEDGER_STATUS` lifts this column out of
    # the sentinel sweep, and `field_failures` -- which is what rejects a
    # `TextField`, a nullable status and a blank one -- never runs on it. The
    # exclusion is from the outcome *vocabulary*, not from the shape rule, and
    # without these two lines a `TextField(blank=True)` status would pass every
    # test in the project.
    assert isinstance(status, models.CharField)
    assert status.blank is False


def test_the_package_reference_is_a_protected_nullable_relation() -> None:
    """AC 1: a real `ForeignKey` to `identity.Package`, `PROTECT`, still nullable.

    `CPM-AD-3` says every evidence, rollup and workflow row references the
    package by its integer primary key, and this was the last table meeting that
    with a bare integer. `CPM-EVIDENCE-S09` converted it, which was a change to
    `core/ledger.py`'s recorder contract rather than a field swap -- and is why
    two earlier stories declined it.

    `PROTECT` is asserted for `CPM-AD-25`'s reason rather than
    `EVIDENCE.02-AUDIT-001`'s: that audit's cascade rule binds evidence models
    and this is a run ledger, so nothing else in the project would notice a
    `CASCADE` here. Deleting a package would then delete the record that anything
    was ever collected for it, which is exactly the history `CPM-AD-25` says is
    never removed.

    Nullable, because an inventory-wide sweep genuinely has no package -- see
    `test_a_run_with_no_package_writes_null_and_stays_answerable` in the
    integration module for the run that proves it stays an ordinary state.
    """
    package = field_of(CollectionRun, "package")

    assert isinstance(package, models.ForeignKey)
    assert package.related_model is Package
    assert package.remote_field.on_delete is models.PROTECT
    assert package.null is True
    assert package.db_index is True
    # `blank` and the default are the other half of "still nullable", and they
    # are not decoration: `blank=False` would make an unscoped run fail form and
    # `full_clean()` validation, and no default would make `CollectionRun()`
    # carry `None` by Django's accident rather than by this column's declaration.
    # A sweep writes no package reference, so both have to say so.
    assert package.blank is True
    assert package.has_default() is True
    assert package.get_default() is None


def test_a_package_names_the_runs_recorded_against_it() -> None:
    """`related_name` is public API the moment it is declared, so it is pinned.

    `package.collection_runs` is now the supported way to ask what has been
    collected for a package, and it is the name a coverage view will reach for.
    Left undeclared, Django would call it `collectionrun_set`; renamed later, every
    caller breaks at runtime rather than here.

    Asserted through the descriptor on `Package` rather than through the field's
    own `related_name` attribute, because the accessor is the thing callers use:
    a `related_name` that was declared but shadowed -- by a property, or by a
    second relation claiming the same name -- would satisfy the attribute check
    and still not be reachable.

    The manager it hands back is exercised against a real table in
    `tests/integration/django_apps/test_run_ledger.py`; this is the declaration.
    """
    package = field_of(CollectionRun, "package")

    assert package.remote_field.get_accessor_name() == "collection_runs"
    assert hasattr(Package, "collection_runs")


def test_the_relation_keeps_the_column_the_integer_had() -> None:
    """AC 1's second half, and the reason nothing else in the product changed.

    Django names a `ForeignKey`'s column by its `attname`, so `package` is stored
    in `package_id` -- the same column the `PositiveBigIntegerField` declared.
    That is what let `core/collection.py`'s `window_query`, `core/freshness.py`'s
    `PACKAGE_FIELD` and every `row.package_id` reader carry on untouched, and it
    is what the migration preserves rather than drops and re-adds.

    Asserted through `get_field`, which resolves a relation by either spelling,
    so this stays true of the *column* rather than of one way of naming it.
    """
    package = field_of(CollectionRun, "package")

    assert package.attname == "package_id"
    assert package.column == "package_id"
    assert field_of(CollectionRun, "package_id") is package


def test_a_policy_run_states_the_cut_off_it_read_evidence_at() -> None:
    """`CPM-FR-22`'s replay guarantee, at the column.

    A policy run with no cut-off cannot be replayed, because there is nothing to
    replay it *against*. The column refuses one rather than recording a run that
    is unreproducible by construction.
    """
    evidence_cutoff = field_of(PolicyRun, "evidence_cutoff")

    assert isinstance(evidence_cutoff, models.DateTimeField)
    assert evidence_cutoff.null is False
    assert evidence_cutoff.has_default() is False


def test_a_collection_run_says_what_ran_over_what_and_how_it_ended() -> None:
    """The row's own summary, which is what an admin list and a log line show.

    The unscoped spelling is the one worth pinning: `package_id` is NULL for a
    run that was not scoped to one package, and rendering that as "package None"
    would read as a package whose identity was lost rather than as a run that
    never had one.

    Constructed, never saved, so this stays a unit test.
    """
    scoped = CollectionRun(collector="pypi", package_id=7, status=RunState.RUNNING)
    unscoped = CollectionRun(collector="pypi", status=RunState.SKIPPED)

    assert str(scoped) == "pypi over package 7: running"
    assert str(unscoped) == "pypi over all packages: skipped"


def test_a_policy_run_says_which_version_read_evidence_as_of_when() -> None:
    """The two facts a policy run is identified by, plus the state it reached.

    The cut-off is rendered in ISO 8601 because that is the one spelling that
    survives being read in a different locale from the one it was written in.
    """
    run = PolicyRun(policy_version="licence-2026.09", evidence_cutoff=A_CUT_OFF, status=RunState.PARTIAL)

    assert str(run) == f"licence-2026.09 at {A_CUT_OFF.isoformat()}: partial"


def test_the_ledger_manager_offers_the_unfinished_query() -> None:
    """The queryset method reaches the manager, which is what installs it.

    `RunLedgerQuerySet.as_manager()` is the line that makes "started and never
    finished" askable through `objects`; a manager declared some other way would
    leave `unfinished()` reachable only from a queryset somebody had already
    built, and every caller would go back to writing the filter by hand.

    *What* it selects is a claim about rows and is asserted against a real table
    in `tests/integration/django_apps/test_run_ledger.py` -- including the case
    that distinguishes it from filtering on `status`. The queryset here is built
    and never evaluated, so this stays a unit test.
    """
    assert isinstance(CollectionRun.objects.unfinished(), RunLedgerQuerySet)
    assert isinstance(PolicyRun.objects.unfinished(), RunLedgerQuerySet)


# ---------------------------------------------------------------------------
# The refusals, which happen before any row is written.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("collector", ["", "   ", "\t\n"], ids=["empty", "spaces", "whitespace"])
def test_a_collection_run_refuses_a_collector_that_names_nothing(collector: str) -> None:
    """`CPM-FR-39`: every run is traceable to the code that performed it.

    A blank `CharField` is perfectly valid SQL, so nothing below this refusal
    would notice: the row would be written, counted by every coverage query, and
    traceable to nothing. Whitespace is refused alongside the empty string
    because `" "` is the spelling that arrives from a stripped configuration
    value rather than from a typo.

    No database, and that is the assertion as much as the refusal is: the guard
    runs before the row is constructed, so a refused run leaves nothing behind.
    """
    with (
        pytest.raises(RunLedgerError, match="a run needs a collector"),
        collection_run(collector=collector, clock=A_STOPPED_CLOCK),
    ):
        pytest.fail("the recorder should have refused before the body ran")


def test_a_policy_run_refuses_a_version_that_names_nothing() -> None:
    """The same rule on the other recorder, because both rows answer the same question.

    A derived row records the policy version that produced it (`CPM-AD-8`); a run
    whose version is blank makes every row it produced unattributable.
    """
    with (
        pytest.raises(RunLedgerError, match="a run needs a policy_version"),
        policy_run(policy_version="", evidence_cutoff=A_CUT_OFF, clock=A_STOPPED_CLOCK),
    ):
        pytest.fail("the recorder should have refused before the body ran")


def test_a_policy_run_refuses_a_naive_evidence_cutoff() -> None:
    """The same refusal `AppendOnlyModel.save()` makes for a naive `observed_at`.

    `USE_TZ` is on, so Django warns and stores a naive value as if it were UTC.
    A cut-off shifted by the writer's offset does not fail -- it silently selects
    a different set of evidence, and `CPM-FR-22`'s promise is that re-running a
    version against a cut-off reproduces identical output. This is the one
    parameter a caller supplies that does not come from a `Clock`, so it is the
    one that can be naive.
    """
    naive = A_CUT_OFF.replace(tzinfo=None)

    with (
        pytest.raises(RunLedgerError, match="naive evidence_cutoff"),
        policy_run(policy_version="licence-2026.09", evidence_cutoff=naive, clock=A_STOPPED_CLOCK),
    ):
        pytest.fail("the recorder should have refused before the body ran")


def test_a_collection_run_refuses_a_package_key_that_cannot_be_one() -> None:
    """A negative key cannot be a primary key at all, and is refused without a lookup.

    The refusal predates the relation and outlived it. The column *was* a
    `PositiveBigIntegerField`: PostgreSQL enforced that with a check constraint
    and SQLite did not enforce it at all, so a negative value wrote a row locally
    and raised an `IntegrityError` in CI, and refusing here made the two agree.
    Since `CPM-EVIDENCE-S09` the column is a relation and a negative key would be
    refused by the foreign key too -- but only after a round trip, and with the
    constraint's message rather than one naming the key.

    It stays a *unit* test because it stays pure: a negative integer is not a
    primary key by inspection, so this refusal is reached before the lookup that
    the unknown-key refusal needs. That the two are different refusals with
    different messages is asserted in
    `tests/integration/django_apps/test_run_ledger.py`, along with the absent key
    and `0`, which is a falsy value and a perfectly good primary key.
    """
    with (
        pytest.raises(RunLedgerError, match="not a package primary key"),
        collection_run(collector="pypi", clock=A_STOPPED_CLOCK, package_id=-1),
    ):
        pytest.fail("the recorder should have refused before the body ran")
