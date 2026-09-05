"""What the audited override declares, and what it refuses before it touches a row.

`CPM-FR-3` makes `override_identity` the only human write in the product that
mutates governed reference data, and `CPM-AD-14` puts three obligations on it: a
permission, a reason, and an audit row written in the same transaction as the
correction. This module holds the two halves of that which need no database --
the declarations, and the refusals that fire before the first query -- and
`tests/integration/django_apps/test_identity_overrides.py` holds everything that
needs a row to have been written, refused or rolled back.

**No `django_db` marker anywhere in this file, and that is an assertion rather
than an omission.** "Every refusal precedes the first write" is the property that
makes a refused override leave nothing behind, and the cheapest possible proof of
it is a case that reaches its refusal in a process where any query at all raises
`RuntimeError: Database access not allowed`. So each refusal below is asserted
*and* is asserted to have needed no database, in one act. The same argument
`tests/unit/django_apps/test_selection.py` makes for its own refusal cases.

The property is load-bearing and it is carried by an *absence*, which is worth
naming: `test_the_module_asks_for_no_database` below is what stops a later edit
adding a marker to make one awkward case pass and silently retiring the
guarantee for every other case in the file. Nothing else would notice -- the
cases would still pass, and they would have stopped proving the thing they exist
to prove.

**The actors here are unsaved `User` instances, which is what keeps that true.**
`PermissionsMixin.has_perm` returns True for an active superuser without
consulting a backend or a row, and every configured backend derives from
`ModelBackend`, whose `has_perm` short-circuits to False on a user that is not
active -- also without a row. Those two are the whole set of answers this module
needs: a permitted actor for the cases about *other* refusals, and a refused one
for the case about the permission. Whether a real group membership grants the
real permission is a claim about the database and about the migration, and it is
asserted in `tests/integration/django_apps/test_role_groups.py` against both.

**The atomicity claim is made twice, and this is the structural half.**
`IDENTITY.05-INT-001` and risk `R-07` are about the correction and the audit row
committing or rolling back together. The integration module proves the behaviour
in both directions by making each side fail; the sweep here proves the *shape*
over the source -- one transaction, both writes inside it, and nothing deferred
to `transaction.on_commit` or to a follow-up task, which `CPM-AD-23` forbids by
name and which no rollback test can see the absence of.

Reads and parses repository files, and inspects the model registry: no database,
no network, no subprocess.
"""

from __future__ import annotations

import ast
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import models

from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.models import AppendOnlyManager
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from conda_package_supply_chain_monitor.core.roles import IDENTITY_APP_LABEL
from conda_package_supply_chain_monitor.core.roles import IDENTITY_OVERRIDE_CODENAME
from conda_package_supply_chain_monitor.core.roles import IDENTITY_OVERRIDE_PERMISSION
from conda_package_supply_chain_monitor.identity.models import OVERRIDE_READ_INDEX
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import IdentityOverride
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_FIELD
from conda_package_supply_chain_monitor.identity.services import CANONICAL_NAME_LENGTH
from conda_package_supply_chain_monitor.identity.services import DISPLAY_NAME_FIELD
from conda_package_supply_chain_monitor.identity.services import DISPLAY_NAME_LENGTH
from conda_package_supply_chain_monitor.identity.services import OVERRIDE_PERMISSION_MISSING
from conda_package_supply_chain_monitor.identity.services import OVERRIDE_REFUSED_EVENT
from conda_package_supply_chain_monitor.identity.services import Correction
from conda_package_supply_chain_monitor.identity.services import OverrideError
from conda_package_supply_chain_monitor.identity.services import ResolutionError
from conda_package_supply_chain_monitor.identity.services import override_identity
from django_service.users.models import User
from tests.clocks import FIXED_INSTANT
from tests.model_registry import OBSERVED_AT_FIELD
from tests.source_scan import REPO_ROOT
from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse

if TYPE_CHECKING:
    from pathlib import Path

#: Exactly what `IdentityOverride` holds, in declaration order, with `observed_at`
#: from the base and the surrogate key first.
#:
#: Written out rather than counted, for the reason `EXPECTED_PACKAGE_FIELDS` is: a
#: length assertion would pass while a field was swapped for another. Every value
#: the row records appears as a *pair* -- what the identity read before this
#: correction and what it reads after -- because `CPM-FR-32` makes the audit
#: independently queryable, and a row carrying only the new value is one an
#: auditor has to reconstruct the answer from.
EXPECTED_OVERRIDE_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "observed_at",
    "package",
    "actor",
    "prior_canonical_name",
    "new_canonical_name",
    "prior_display_name",
    "new_display_name",
    "prior_confidence",
    "new_confidence",
    "reason",
    "trace_id",
)

#: The table PRD Appendix A.2 names.
EXPECTED_TABLE: Final[str] = "identity_overrides"

#: The two relations, and the deletion behaviour `EVIDENCE.02-AUDIT-001` requires
#: of every relation on an evidence model. Named here so the case reads as the
#: rule rather than as two lookups.
RELATION_FIELDS: Final[tuple[str, ...]] = ("package", "actor")

#: The service module every structural sweep below parses, relative to `src/`.
#: Named once because three cases read it.
SERVICES_MODULE: Final[str] = "django_apps/conda_package_supply_chain_monitor/identity/services.py"

#: The transaction opener the atomicity claim is about, and the two forms
#: `CPM-AD-23` forbids in its place -- a callback that runs *after* the commit,
#: and a task queued to do the second write later. Either would satisfy "the audit
#: row is written" and neither would satisfy "together".
ATOMIC_FORM: Final[str] = "transaction.atomic"
#:
#: Matched on the *trailing attribute*, never on the resolved dotted chain --
#: `tests/source_scan.dotted_name` returns the whole chain, so `a_task.delay(...)`
#: is `"a_task.delay"` and a set of bare names would match nothing at all. See
#: `_deferrals`.
DEFERRAL_FORMS: Final[frozenset[str]] = frozenset({"on_commit", "delay", "apply_async"})

#: The function whose body the atomicity sweep is about, and the two writes that
#: have to be inside its transaction: the package's own `save` and the insert of
#: the audit row.
OVERRIDE_FUNCTION: Final[str] = "override_identity"
CORRECTION_WRITER: Final[str] = "_write_correction"
AUDIT_WRITE_FORM: Final[str] = "IdentityOverride.objects.create"

#: The three routes to a database this module must contain none of: the marker by
#: either spelling, and pytest-django's database fixtures, which a case can
#: request by name with no marker at all. Matched on the syntax tree, never as
#: text -- the module docstring above says the word `django_db` in prose, and a
#: substring scan would report its own explanation as the offence.
DATABASE_MARKERS: Final[frozenset[str]] = frozenset({"django_db"})
DATABASE_FIXTURES: Final[frozenset[str]] = frozenset(
    {"db", "transactional_db", "django_db_setup", "django_db_reset_sequences"}
)

#: An arbitrary non-blank reason, for the cases whose subject is something else.
A_REASON: Final[str] = "the resolver matched the wrong PyPI project"

#: A package id that is never queried, because every case here refuses first. Not
#: `1`: a number that could plausibly be a row makes a case that accidentally
#: reached the database look like one that meant to.
AN_UNREACHED_PACKAGE_ID: Final[int] = 987_654_321

#: The event's required shape. `config/authorization/mapper.py` emits every
#: authorization decision under a dotted `authorization.<event>` name, and an
#: operator filters the log by that prefix rather than by which application made
#: the call.
AUTHORIZATION_PREFIX: Final[str] = "authorization."

#: A naive instant, for the clock that answers one. `FixedClock` refuses to be
#: built from one and `SystemClock` cannot produce one, so this is what a writer
#: that went around the clock looks like from the service's side -- which is the
#: only way the refusal is reachable at all. Declared here rather than imported
#: from the sibling module that declares its own: a test module is not a helper
#: library, and `tests/clocks.py` deliberately carries only aware instants.
A_NAIVE_INSTANT: Final[datetime] = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose; see above


class NaiveClock:
    """A clock that answers a naive instant, which no real clock can.

    `Clock` is `runtime_checkable` and that check sees method *names* only, which
    is exactly the hole this stands in: a class whose `now` returns a naive
    datetime satisfies the protocol and would record a correction at a time it did
    not happen. The service is what refuses it, and this is what lets the refusal
    be reached.
    """

    def now(self) -> datetime:
        """Return a naive instant.

        Returns:
            `A_NAIVE_INSTANT`, unchanged on every call.

        """
        return A_NAIVE_INSTANT


@pytest.fixture
def a_permitted_actor() -> User:
    """An actor `has_perm` answers True for without touching the database.

    `PermissionsMixin.has_perm` returns True for an active superuser before it
    consults a single backend, so this instance never needs a row, a group or a
    permission. It stands in for "somebody the permission check lets through" and
    for nothing else: what a *leadership* membership grants is a claim about the
    migration, and it is asserted where the rows are.

    Returns:
        An unsaved user the override's permission check admits.

    """
    return User(username="a-leader", is_active=True, is_superuser=True)


@pytest.fixture
def a_refused_actor() -> User:
    """An actor every configured backend answers False for, without a database.

    `AUTHENTICATION_BACKENDS` holds one entry and it derives from `ModelBackend`,
    whose `has_perm` is `user_obj.is_active and super().has_perm(...)` -- so an
    inactive user is refused before any permission is resolved and before any
    query is issued. That is what makes the refusal case below provably prior to
    the first write rather than merely observed to be.

    Returns:
        An unsaved user holding no permission at all.

    """
    return User(username="not-a-leader", is_active=False, idp_subject="urn:example:principal:not-a-leader")


def _services_source() -> Path:
    """Return the service module's path, for the sweeps that parse it.

    Returns:
        The absolute path under `src/`.

    """
    return SRC_ROOT / SERVICES_MODULE


def _field(name: str) -> models.Field[object, object]:
    """Return one declared field of the audit model.

    Args:
        name: The field's name.

    Returns:
        The field, read off `_meta`.

    """
    return IdentityOverride._meta.get_field(name)  # type: ignore[return-value]  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


def _override_function(tree: ast.Module) -> ast.FunctionDef:
    """Return the `override_identity` definition from the parsed service module.

    Args:
        tree: The parsed module.

    Returns:
        The function node.

    """
    return _named_function(tree, OVERRIDE_FUNCTION)


def _named_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """Return the one function of a given name from a parsed module.

    Args:
        tree: The parsed module.
        name: The function's name.

    Returns:
        The function node, asserted unique so a rename leaves a failing test
        rather than a sweep over nothing.

    """
    found = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(found) == 1, f"expected exactly one {name} in {SERVICES_MODULE}, found {len(found)}"
    return found[0]


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Return every module-level name bound to a string literal.

    The half `ast.Constant` alone cannot see. `identity/services.py` addresses its
    columns through `Final[str]` constants -- `CANONICAL_NAME_FIELD` and the rest
    -- so a sweep for column names that read only literals would be blind to the
    module's own idiom, which is exactly the spelling somebody adding a column
    would use.

    Annotated assignments are included because that is how every one of them is
    written; the walk is over the module body only, so a same-named local inside a
    function cannot shadow one here.

    Args:
        tree: The parsed module.

    Returns:
        Name to string value, for the bindings that are string literals.

    """
    resolved: dict[str, str] = {}
    for node in tree.body:
        target, value = None, None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0], node.value
        if target is not None and isinstance(value, ast.Constant) and isinstance(value.value, str):
            resolved[target.id] = value.value
    return resolved


def _deferrals(node: ast.AST) -> list[str]:
    """Return every deferral-shaped call under a node, by its trailing attribute.

    Matched on the *last* segment rather than on the resolved dotted chain, and
    that is the whole point of the helper: `dotted_name` returns the full chain, so
    `a_task.delay(...)` resolves to `"a_task.delay"` and a membership test against
    `{"delay"}` matches nothing. Only an unqualified `delay()` could ever have been
    caught, and nobody writes that -- so the ban read as enforced while being
    unable to fire.

    Args:
        node: The subtree to walk.

    Returns:
        The trailing attribute of each matching call, one entry per call site.

    """
    return [
        node_.func.attr
        for node_ in ast.walk(node)
        if isinstance(node_, ast.Call) and isinstance(node_.func, ast.Attribute) and node_.func.attr in DEFERRAL_FORMS
    ]


def _atomic_blocks(node: ast.AST) -> list[ast.With]:
    """Return every `with transaction.atomic():` block under a node.

    Args:
        node: The subtree to walk.

    Returns:
        The `With` nodes, in walk order.

    """
    return [
        found
        for found in ast.walk(node)
        if isinstance(found, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call) and dotted_name(item.context_expr.func) == ATOMIC_FORM
            for item in found.items
        )
    ]


# ---------------------------------------------------------------------------
# The audit row: what it holds, and the obligations being evidence brings.
# ---------------------------------------------------------------------------


def test_the_audit_row_holds_exactly_the_decision_and_its_correlation() -> None:
    """AC #1's field set: who, when, from what, to what, and why.

    Order included. It is not load-bearing for the schema, but a set comparison
    would pass while a field moved between the pairs and the provenance, and the
    grouping is how a reader checks the row against `CPM-AD-14` at all.
    """
    names = tuple(
        field.name
        for field in IdentityOverride._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    )

    assert names == EXPECTED_OVERRIDE_FIELDS


def test_the_audit_row_is_the_table_the_prd_names() -> None:
    """`identity_overrides`, not the `identity_identityoverride` Django derives.

    The schema in this product is named by the architecture and PRD Appendix A.2;
    a derived name would make the table depend on which application happened to
    declare the model, so moving a model between applications would rename its
    table.
    """
    assert IdentityOverride._meta.db_table == EXPECTED_TABLE  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


def test_a_half_built_audit_row_renders_rather_than_raising() -> None:
    """`__str__` on an unsaved instance, which is where every other one in this app breaks.

    The related object of an unsaved instance raises `RelatedObjectDoesNotExist`,
    so a `__str__` reaching for `self.package` or `self.actor` raises in exactly
    the two places a half-built object is most likely to be rendered -- a debugger
    and a traceback -- turning the failure somebody is looking at into a different
    one. Asserted on an instance with nothing set at all, which is the worst case
    and the only one that proves the guard rather than the happy path.

    The populated half is asserted beside it so the placeholders cannot be what
    the method always returns.
    """
    empty = str(IdentityOverride())

    assert "no package" in empty
    assert "nobody" in empty
    assert "never" in empty
    assert "(no name)" in empty

    rendered = str(
        IdentityOverride(
            package_id=7,
            actor_id=9,
            observed_at=FIXED_INSTANT,
            prior_canonical_name="numpy-internal",
            new_canonical_name="numpy",
        ),
    )

    assert rendered == f"numpy-internal -> numpy on package 7 by user 9 at {FIXED_INSTANT.isoformat()}"


def test_the_audit_row_inherits_the_append_only_guard_and_its_manager() -> None:
    """`CPM-FR-32`'s "append-only", enforced by machinery rather than by intention.

    The base is what refuses a re-save, and the manager is what refuses
    `update()` and `bulk_update()`; a model that inherited one without the other
    would be half-guarded, and the half that was missing is exactly the half
    somebody reaches for after the first refusal. The base's `base_manager_name`
    is what puts `_base_manager` under the same rule, which is the largest hole
    when it is left unset.

    The refusals themselves are `tests/unit/django_apps/test_append_only_model.py`'s
    and are proven against a real table in
    `tests/integration/django_apps/test_identity_overrides.py`. What is asserted
    here is only that this model is under them.
    """
    assert issubclass(IdentityOverride, AppendOnlyModel)
    assert isinstance(IdentityOverride._default_manager, AppendOnlyManager)  # noqa: SLF001 - Django's own accessor
    assert isinstance(IdentityOverride._base_manager, AppendOnlyManager)  # noqa: SLF001 - Django's own accessor


def test_the_instant_comes_from_the_base_and_carries_no_default() -> None:
    """`CPM-AD-26`: the writer supplies the instant, and no wall clock is near it.

    `auto_now_add` and `default=timezone.now` both read the process wall clock
    where the row is written, which `EVIDENCE.01-AUDIT-002` fails and
    `tests/unit/django_apps/test_clock_audit.py` sweeps the source for. The column
    is the base's, so this is really an assertion that the base's column was not
    shadowed by a redeclaration here -- which is the one way a model under that
    audit could acquire a default without the scan seeing a wall-clock read.
    """
    observed_at = _field(OBSERVED_AT_FIELD)
    inherited = AppendOnlyModel._meta.get_field(OBSERVED_AT_FIELD)  # noqa: SLF001 - Django's own accessor

    # Django copies an abstract base's fields onto every concrete subclass, so
    # `.model` is `IdentityOverride` either way and cannot say which class
    # declared it. Deconstruction can: a redeclaration here would have to differ
    # from the base's in at least the argument that made it worth writing.
    assert observed_at.deconstruct()[1:] == inherited.deconstruct()[1:]
    assert observed_at.has_default() is False
    assert getattr(observed_at, "auto_now_add", False) is False
    assert getattr(observed_at, "auto_now", False) is False


@pytest.mark.parametrize("name", RELATION_FIELDS)
def test_every_relation_on_the_audit_row_protects(name: str) -> None:
    """`EVIDENCE.02-AUDIT-001`, and independently right for the actor.

    Django's deletion collector issues its `DELETE` through `sql.DeleteQuery`,
    never through `Model.delete()`, so a `CASCADE` from either relation would
    destroy audit rows with every append-only refusal bypassed on the way. For the
    actor there is a second reason that does not depend on the mechanism at all:
    deleting a user must not delete the record of what they decided.

    The repository-wide sweep in
    `tests/unit/django_apps/test_evidence_inheritance_audit.py` makes the same
    check across every evidence model. This one fails naming the story's own
    table.
    """
    relation = _field(name)

    assert relation.remote_field.on_delete is models.PROTECT  # type: ignore[union-attr]


def test_the_audit_row_carries_no_uniqueness_of_any_kind() -> None:
    """Two corrections of one package are two facts (`CPM-AD-2`, `EVIDENCE.02-AUDIT-003`).

    A unique constraint spanning the corrected fact would turn the second
    correction into an `IntegrityError` -- the same history loss as an overwrite,
    arriving as a crash. Asserted over the declaration in all three of its
    spellings, because the repository-wide audit's sweep and this one would
    otherwise agree only by accident.
    """
    meta = IdentityOverride._meta  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert [constraint for constraint in meta.constraints if isinstance(constraint, models.UniqueConstraint)] == []
    assert meta.unique_together == ()
    assert [field.name for field in meta.concrete_fields if field.unique and not field.primary_key] == []


def test_the_history_reads_newest_first_and_is_indexed_for_it() -> None:
    """`CPM-FR-32`'s "independently queryable", in the order anybody asks it in.

    The ordering is on the model rather than at each call site because an
    unordered read of an append-only table returns rows in whatever order the
    database chose, and "what happened to this package, most recently first" is
    the only question an audit trail is asked. The descending primary key is the
    tie-break two corrections sharing one instant need -- one clock, two calls in
    one request -- without which the answer depends on the database's own
    arbitrary row order.

    The index is asserted beside it because the two are one decision: the sort is
    over a column that is not the primary key, on a table that grows and is never
    pruned, and Django's automatic foreign-key index covers the filter alone.
    """
    meta = IdentityOverride._meta  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert meta.ordering == ("-observed_at", "-id")
    assert [(index.name, index.fields) for index in meta.indexes] == [
        (OVERRIDE_READ_INDEX, ["package", "-observed_at"]),
    ]


# ---------------------------------------------------------------------------
# The permission: one spelling, declared once and reconciled here.
# ---------------------------------------------------------------------------


def test_the_model_declares_the_permission_the_role_contract_grants() -> None:
    """AC #7's declaration half, in the one place the two halves can disagree.

    `core/roles.py` declares the codename because it is imported from
    `config/settings/base.py`, long before the app registry exists; this model
    attaches it. Those are two files, and the failure mode when they drift is the
    quietest there is -- `_resolve_permissions` logs an unresolved codename at
    warning and attaches nothing, so leadership holds no permission and every
    override is refused as forbidden. This is the reconciliation that turns that
    into a failing test.
    """
    declared = dict(IdentityOverride._meta.permissions)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    assert list(declared) == [IDENTITY_OVERRIDE_CODENAME]
    assert declared[IDENTITY_OVERRIDE_CODENAME]
    assert IdentityOverride._meta.app_label == IDENTITY_APP_LABEL  # noqa: SLF001 - Django's own accessor
    assert f"{IdentityOverride._meta.app_label}.{IDENTITY_OVERRIDE_CODENAME}" == IDENTITY_OVERRIDE_PERMISSION  # noqa: SLF001 - Django's own accessor


# ---------------------------------------------------------------------------
# The columns a caller supplies a value for, measured against the columns.
# ---------------------------------------------------------------------------


def test_the_stored_pairs_are_as_wide_as_the_columns_they_mirror() -> None:
    """A correction the package row accepts must fit the row that records it.

    The audit columns hold what `Package.canonical_name` and
    `Package.display_name` held and what they now hold, so a narrower audit column
    would refuse a correction the package itself accepts -- inside the
    transaction, rolling the correction back, with a message naming the audit
    table rather than the input. Reconciled rather than restated, so widening the
    package widens these with it.
    """
    package_meta = Package._meta  # noqa: SLF001 - `_meta` is Django's own public-by-convention API

    for stored, mirrored in (
        ("prior_canonical_name", "canonical_name"),
        ("new_canonical_name", "canonical_name"),
        ("prior_display_name", DISPLAY_NAME_FIELD),
        ("new_display_name", DISPLAY_NAME_FIELD),
        ("prior_confidence", "confidence"),
        ("new_confidence", "confidence"),
    ):
        assert _field(stored).max_length == package_meta.get_field(mirrored).max_length, stored


def test_the_reason_is_unbounded_and_required() -> None:
    """Prose a person wrote, with no length at which it becomes wrong.

    A bounded `CharField` would be refused by PostgreSQL in the gate and stored
    truncated by the local SQLite (`R-5`) -- a parity gap over a column whose whole
    content is the justification an auditor reads. `blank=False` is the other
    half: the service refuses a blank reason before it writes, so no stored row
    carries one, and declaring the column blankable would say otherwise.
    """
    reason = _field("reason")

    assert isinstance(reason, models.TextField)
    assert reason.max_length is None
    assert reason.blank is False


def test_the_display_name_bound_is_read_off_the_column() -> None:
    """`DISPLAY_NAME_LENGTH` is the column's width, not a number beside it.

    The service refuses an over-long display name against this constant, and a
    constant that had drifted from the column would refuse values the column
    accepts or admit values PostgreSQL refuses. Reconciled here for the reason
    `tests/unit/django_apps/test_identity_services.py` reconciles the other four.
    """
    assert Package._meta.get_field(DISPLAY_NAME_FIELD).max_length == DISPLAY_NAME_LENGTH  # noqa: SLF001 - Django's own accessor
    assert DISPLAY_NAME_LENGTH > 0


# ---------------------------------------------------------------------------
# The refusals, every one of them reached without a database.
# ---------------------------------------------------------------------------


def test_an_actor_without_the_permission_is_refused_and_named_in_the_log(
    a_refused_actor: User,
    captured_identity_service_logs: list[dict[str, Any]],
) -> None:
    """AC #2: refused, nothing written, and the refusal names the acting user.

    The log record is the assertion that matters here. `CPM-AD-13` makes every
    authorization decision an event, and outside a request nothing binds
    `user_id` -- `django_structlog`'s request binding is not available to a
    service reached from a task or a shell -- so the actor has to be passed
    explicitly or the one refusal an operator most needs to explain is the only
    one they cannot attribute.

    There is no `django_db` marker on this case on purpose. The refusal runs
    before the package lookup, so a check that had been moved after it would fail
    here with `Database access not allowed` rather than passing quietly.
    """
    with pytest.raises(OverrideError, match=IDENTITY_OVERRIDE_PERMISSION):
        override_identity(
            package_id=AN_UNREACHED_PACKAGE_ID,
            actor=a_refused_actor,
            correction=Correction(
                reason=A_REASON,
            ),
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert [event["event"] for event in captured_identity_service_logs] == [OVERRIDE_REFUSED_EVENT]
    refusal = captured_identity_service_logs[0]
    assert refusal["reason"] == OVERRIDE_PERMISSION_MISSING
    assert refusal["idp_subject"] == a_refused_actor.idp_subject
    assert refusal["user_id"] == a_refused_actor.pk


def test_the_refusal_event_is_named_as_every_authorization_event_is() -> None:
    """One prefix, so an operator filters the log by decision rather than by application.

    `config/authorization/mapper.py` emits `authorization.claims_rejected` and its
    siblings; a domain service that invented its own namespace for the same class
    of decision would be invisible to whatever query an operator already has.
    """
    assert OVERRIDE_REFUSED_EVENT.startswith(AUTHORIZATION_PREFIX)
    assert OVERRIDE_REFUSED_EVENT != AUTHORIZATION_PREFIX
    assert OVERRIDE_PERMISSION_MISSING


@pytest.mark.parametrize("reason", ["", "   ", "\n\t "])
def test_a_blank_reason_is_refused_before_anything_is_read(reason: str, a_permitted_actor: User) -> None:
    """`CPM-AD-14` requires a reason, and a blank `TextField` is valid SQL.

    Without the refusal the row would be written, would be counted, and would
    record that somebody changed governed reference data for no stated reason --
    an audit trail answering the one question it exists to answer with nothing.
    Whitespace is included because `strip()` is what makes "  " and "" the same
    input, and a check on truthiness alone would admit the first.
    """
    with pytest.raises(OverrideError, match="needs a reason"):
        override_identity(
            package_id=AN_UNREACHED_PACKAGE_ID,
            actor=a_permitted_actor,
            correction=Correction(
                reason=reason,
            ),
            clock=FixedClock(instant=FIXED_INSTANT),
        )


def test_a_whitespace_only_correction_is_refused_rather_than_written(a_permitted_actor: User) -> None:
    """A correction to nothing is not the same as no correction.

    The empty string means "leave the stored name alone" and is the ordinary case.
    Whitespace is a name, and writing it would be refused by
    `canonical_name_is_present` as an `IntegrityError` naming a constraint rather
    than the input that broke it -- from inside the transaction, after the audit
    row had been built.
    """
    with pytest.raises(OverrideError, match="names nothing"):
        override_identity(
            package_id=AN_UNREACHED_PACKAGE_ID,
            actor=a_permitted_actor,
            correction=Correction(
                reason=A_REASON,
                canonical_name="   ",
            ),
            clock=FixedClock(instant=FIXED_INSTANT),
        )


@pytest.mark.parametrize(
    ("field", "keyword", "limit"),
    [
        ("canonical_name", "canonical_name", CANONICAL_NAME_LENGTH),
        (DISPLAY_NAME_FIELD, "display_name", DISPLAY_NAME_LENGTH),
    ],
)
def test_a_value_wider_than_its_column_is_refused(
    field: str,
    keyword: str,
    limit: int,
    a_permitted_actor: User,
) -> None:
    """`R-5`, the parity gap: SQLite truncates and PostgreSQL raises.

    An unrefused over-long value is a correction that works on a developer's
    machine and fails in the gate, and the failure arrives as a `DataError` naming
    a column rather than as a message naming the field the person typed into. The
    same rule the resolution door applies to the values a resolver supplies,
    applied to the two a person supplies.
    """
    with pytest.raises(OverrideError, match=field):
        override_identity(
            package_id=AN_UNREACHED_PACKAGE_ID,
            actor=a_permitted_actor,
            correction=Correction(reason=A_REASON, **{keyword: "x" * (limit + 1)}),
            clock=FixedClock(instant=FIXED_INSTANT),
        )


def test_a_naive_instant_is_refused_before_the_transaction_opens(a_permitted_actor: User) -> None:
    """`AppendOnlyModel.save()` would refuse this too, and too late to be a refusal.

    `USE_TZ` is on, so Django warns and stores a naive value as if it were UTC,
    and an audit row silently shifted by the writer's offset records a correction
    at a time it did not happen. The base refuses it as well -- but inside the
    transaction, after the correction has been written, so what it produces is a
    rollback rather than a refusal that preceded every write. Both guards are
    worth having and only this one is a refusal.

    `FixedClock` refuses a naive instant at construction and `SystemClock` cannot
    produce one, so `NaiveClock` is what a writer that went around the clock looks
    like from the service's side -- which is the only way the refusal is reachable
    at all.
    """
    with pytest.raises(OverrideError, match="naive"):
        override_identity(
            package_id=AN_UNREACHED_PACKAGE_ID,
            actor=a_permitted_actor,
            correction=Correction(
                reason=A_REASON,
            ),
            clock=NaiveClock(),
        )


def test_the_module_asks_for_no_database() -> None:
    """The guarantee this whole module rests on, asserted rather than trusted.

    Every refusal case here proves it reaches its refusal before the first query,
    and it proves it by running where a query raises. That is worth exactly as
    much as the *absence* of a `django_db` marker in this file -- an absence
    nothing else checks, and which a later edit adding one case's marker would
    remove for every case at once, with the whole file still green.

    Read from the parsed syntax tree rather than by substring, for the reason
    every source scan in this repository is: prose about the prohibition -- this
    module's own docstring says the words -- must not itself be an offence.
    Three routes to a database are matched, because all three are the same
    retirement: a `django_db` marker on a case, one applied to the module through
    `pytestmark`, and a parameter named for pytest-django's database fixtures,
    which a case can request without a marker at all.
    """
    tree = parse(REPO_ROOT / "tests" / "unit" / "django_apps" / "test_identity_overrides.py")
    marked = [
        node.lineno for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in DATABASE_MARKERS
    ]
    requested = [
        f"{node.name}({argument.arg})"
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for argument in node.args.args
        if argument.arg in DATABASE_FIXTURES
    ]

    assert [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)] != [], (
        "the guard is pointed at a module with no functions in it"
    )
    assert marked == []
    assert requested == []


def test_an_anonymous_actor_is_refused_and_still_reaches_the_log(
    captured_identity_service_logs: list[dict[str, Any]],
) -> None:
    """AC 2 for the caller the surface will actually hand over.

    `AnonymousUser` answers `has_perm` perfectly well -- False, through every
    backend -- so the *refusal* was never in doubt. What was is the log record
    beside it: `AnonymousUser` declares no `idp_subject`, so reading the attribute
    unconditionally raises `AttributeError` on exactly the branch this AC is
    written about, and the refusal an operator most needs to see is the one that
    never reaches the log. A `PermissionDenied` from a view is at least visible; a
    500 with no authorization event at all is not.

    Latent today only because nothing calls this door from a request. It stops
    being latent the moment `CPM-APP-S05`'s modal passes `request.user`, which is
    an `AnonymousUser` for anybody who is not signed in and a `SimpleLazyObject`
    wrapping one at that.

    The refusal is asserted to carry the two identity fields as *absences* rather
    than to be omitted: an operator reading the event needs to see that the actor
    had no identity, which is a different fact from an event that did not record
    one.
    """
    with pytest.raises(OverrideError):
        override_identity(
            package_id=AN_UNREACHED_PACKAGE_ID,
            actor=AnonymousUser(),  # type: ignore[arg-type]
            correction=Correction(reason=A_REASON),
            clock=FixedClock(instant=FIXED_INSTANT),
        )

    assert [event["event"] for event in captured_identity_service_logs] == [OVERRIDE_REFUSED_EVENT]
    refusal = captured_identity_service_logs[0]
    assert refusal["reason"] == OVERRIDE_PERMISSION_MISSING
    assert refusal["user_id"] is None
    assert refusal["idp_subject"] == ""


def test_an_override_refusal_is_not_a_resolution_error_and_the_reverse() -> None:
    """Two doors, two refusals, and a caller that has to tell them apart.

    "This resolver handed over something unusable" and "this person may not do
    that" are answered differently by the surface that will call them -- one is a
    form error and the other is a refusal to act at all -- so a shared class would
    make the distinction unavailable at the only place it matters. Both stay
    `ValueError` subclasses, which is what every "this input is unusable" in this
    product is, so a caller that wants neither distinction still catches both.
    """
    assert issubclass(OverrideError, ValueError)
    assert not issubclass(OverrideError, ResolutionError)
    assert not issubclass(ResolutionError, OverrideError)


# ---------------------------------------------------------------------------
# `IDENTITY.05-INT-001`, the structural half: one transaction, both writes in it.
# ---------------------------------------------------------------------------


def test_the_override_opens_exactly_one_transaction_and_the_module_opens_no_other() -> None:
    """`CPM-AD-23`: the transaction boundary is the caller's, except for this one.

    Every other door in this module deliberately opens none -- the shell and the
    evidence row that occasioned it commit together, and only the caller knows
    where that boundary is. `override_identity` is the exception the architecture
    describes rather than a departure from it, because there is no caller that
    could place the boundary for a correction and its audit row.

    Asserted in both directions, so the exception stays exactly one: a second
    `transaction.atomic()` appearing anywhere else in this module fails here, and
    so does the first one being deleted.
    """
    tree = parse(_services_source())

    assert len(_atomic_blocks(_override_function(tree))) == 1
    assert len(_atomic_blocks(tree)) == 1


def test_both_writes_sit_inside_the_overrides_one_transaction() -> None:
    """`IDENTITY.05-INT-001` and `R-07`, as a property of the source.

    The integration module proves the behaviour by making each side fail; this is
    the shape that behaviour rests on, and it is worth asserting separately
    because a write moved *out* of the block still passes every ordinary case --
    the rows land, the call returns, and the only symptom is a correction that
    survives an audit row that did not, which nobody sees until an auditor asks.

    Swept by resolved call name: `_write_correction` is the one door the package
    row is written through, and `IdentityOverride.objects.create` is the audit
    insert. Both must appear inside the transaction, and both must appear at all
    -- a function that had stopped writing either would satisfy an enclosure rule
    perfectly.
    """
    block = _atomic_blocks(_override_function(parse(_services_source())))[0]
    enclosed = {
        dotted_name(node.func) for statement in block.body for node in ast.walk(statement) if isinstance(node, ast.Call)
    }

    assert CORRECTION_WRITER in enclosed
    assert AUDIT_WRITE_FORM in enclosed


def test_the_override_defers_neither_write_to_a_callback_or_a_task() -> None:
    """`CPM-AD-23`: "never `transaction.on_commit`, never a follow-up task".

    Both forms would satisfy "the audit row is written" and neither would satisfy
    "together": a callback runs after the commit, so a failure in it leaves the
    correction standing alone, and a queued task can be lost entirely. No rollback
    test can see the absence of either, which is why this is a source claim.
    """
    tree = parse(_services_source())
    deferred = sorted(_deferrals(_override_function(tree)))

    assert deferred == []


def test_the_deferral_detector_sees_a_qualified_call() -> None:
    """The guard the guard above needs, because its first version could not fire.

    `tests/source_scan.dotted_name` returns the *whole* chain, so
    `some_task.delay(...)` resolves to `"some_task.delay"` and a membership test
    against a set of bare method names matches nothing at all -- only an
    unqualified `delay()` could ever have been reported, and nobody writes that.
    A ban that cannot fire is worse than no ban, because it reads as one.

    `_deferrals` matches on the trailing attribute instead, and this measures it
    against the spelling `CPM-AD-23`'s "never a follow-up task" is actually about:
    a Celery task reached through a module, and a callback registered on the
    transaction.
    """
    measured = ast.parse(
        "from django.db import transaction\n"
        "from somewhere import a_task\n"
        "def f():\n"
        "    transaction.on_commit(lambda: None)\n"
        "    a_task.delay(1)\n"
        "    a_task.apply_async(args=[1])\n"
        "    ordinary.compute(1)\n",
    )

    assert sorted(_deferrals(measured)) == ["apply_async", "delay", "on_commit"]


def test_the_override_writes_neither_half_of_the_join_key() -> None:
    """The fourth of the five conditions `CPM-IDENTITY-S06`'s review recorded.

    `identity_source` and `associator_key` are the pair both other doors find a
    package by. Rewriting either while correcting a name orphans the package from
    its inventory source on the next sweep, which then creates a second shell --
    and the symptom arrives days later as duplicated evidence rather than as a
    failure at the correction.

    **Constants are resolved, not just literals read.** The first version of this
    case walked `ast.Constant` only -- and `_write_correction` addresses its
    columns through `CANONICAL_NAME_FIELD` and `DISPLAY_NAME_FIELD`, which is the
    module's *own* idiom. A line spelled `intended[ASSOCIATOR_KEY_FIELD] = ...`
    would therefore have been an `ast.Name` and would have sailed past the ban
    written to stop it. Every module-level `Final[str]` is resolved to its value
    first, so both spellings are seen.

    The behavioural half is in the integration module, which captures the
    `update_fields` the writer actually hands to `save()` -- the thing that
    decides which columns are written. Two independent claims, because this one
    cannot see a value assembled at runtime and that one cannot see a branch no
    case happens to take.
    """
    tree = parse(_services_source())
    writer = _named_function(tree, CORRECTION_WRITER)
    resolved = _module_string_constants(tree)
    named = {node.value for node in ast.walk(writer) if isinstance(node, ast.Constant)} | {
        resolved[node.id] for node in ast.walk(writer) if isinstance(node, ast.Name) and node.id in resolved
    }

    assert resolved, "no module constants resolved, so the Name half of this sweep is vacuous"
    assert CANONICAL_NAME_FIELD in named, "the writer no longer names the column it is supposed to write"
    assert "identity_source" not in named
    assert "associator_key" not in named


def test_the_correction_writer_names_one_confidence_and_it_is_verified() -> None:
    """`CPM-AD-4`: `verified` is the identity a person established, and this is that.

    Asserted over the writer's source rather than only over a written row, because
    what is being claimed is that there is *no branch*: an override writes
    `verified` unconditionally, and the diff against the stored row is what stops
    an already-`verified` package being saved for nothing. A door that chose
    between confidences would be a second confidence gate -- the thing
    `tests/unit/django_apps/test_confidence_gate_audit.py` bans outright -- and a
    door that wrote `inventory-derived` would let a person establish an identity
    `CPM-AD-4` then labels as derived.
    """
    writer = _named_function(parse(_services_source()), CORRECTION_WRITER)
    members = {
        node.attr
        for node in ast.walk(writer)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == IdentityConfidence.__name__
    }

    assert members == {IdentityConfidence.VERIFIED.name}
