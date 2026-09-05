"""`EVIDENCE.02-AUDIT-001`: every evidence model still carries the append-only guard.

`CPM-AD-2` says evidence models inherit an abstract base in `core` whose `save()`
refuses when `pk` is set and whose manager exposes no `update()` or `delete()`.
`AppendOnlyModel` is that base and
`tests/unit/django_apps/test_append_only_model.py` proves it refuses -- but a
guard is only worth what it is attached to, and there are three ways for it to
end up attached to nothing while the model looks exactly like one that is
guarded. This is the audit that notices all three.

**One: the base is missing.** An evidence table declared as a plain
`models.Model` inherits no refusal at all, and every `save()` on a loaded row
silently updates.

**Two: the managers were re-declared.** A model that inherits the base and then
writes `objects = models.Manager()` -- or sets `Meta.default_manager_name` or
`Meta.base_manager_name` at a plain one -- has `update()`, `bulk_update()` and
`delete()` all working again, while passing any audit that checks only the base
class. `_base_manager` is the sharp one: Django builds a plain manager itself
when no name is given, so it is unguarded *by default* and `AppendOnlyModel`
sets `Meta.base_manager_name` for exactly this reason. `Evidence._base_manager.filter(...).update(...)`
is what somebody writes after `objects.update()` has refused.

**Three: a relation deletes the row from the other end.** Django's deletion
collector issues its `DELETE` through `sql.DeleteQuery`, never through
`QuerySet.delete()` or `Model.delete()`, so `on_delete=CASCADE` on a
`ForeignKey` destroys observations when the parent goes and no refusal in
`core/models.py` is consulted. `SET_NULL` and `SET_DEFAULT` are the same hole
spelled as a rewrite. Only `PROTECT`, `RESTRICT` and `DO_NOTHING` leave the
observation where it is.

**Enumerated from the model registry, never from a hand-written list**, on the
same terms as `EVIDENCE.01-AUDIT-001`: a list is edited by whoever remembers it
exists, so the first evidence table added by someone who did not is the one that
escapes. What counts as an evidence model -- three independent marks and one
declared way out -- is `tests/model_registry.py`'s, with the argument for each.

**The anti-vacuity guard is the load-bearing half today.** Every mark is empty:
`CPM-EVIDENCE-S02` is forbidden to create a concrete evidence model, and the
first arrives with `CPM-EP-CURRENCY`. So the sweep below passes over nothing,
which is exactly how an audit becomes permanently green and permanently useless.
What stops that is the fixture half: the detector is measured against real Django
models built in an isolated registry, one per way of losing the guard and one per
way of keeping it. A detector that had stopped detecting fails here on the day it
stops rather than on the day the first evidence model lands.

`django.test.utils.isolate_apps` is what keeps those fixtures out of the real
registry: it patches `Options.default_apps` rather than the global
`django.apps.apps`, so the sweep cannot see them and `makemigrations --check`
cannot either.

No database and no network: defining a model and reading `_meta` touches neither.
"""

from __future__ import annotations

from typing import Final

import pytest
from django.db import models
from django.test.utils import isolate_apps

from conda_package_supply_chain_monitor.core.models import AppendOnlyManager
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from tests.model_registry import EVIDENCE_APP_LABEL
from tests.model_registry import FIXTURE_APP
from tests.model_registry import FIXTURE_LABEL
from tests.model_registry import NOT_EVIDENCE_ATTRIBUTE
from tests.model_registry import RUN_LEDGER_MODEL_LABELS
from tests.model_registry import evidence_marks
from tests.model_registry import evidence_models
from tests.model_registry import exempt_models
from tests.model_registry import first_party_models
from tests.model_registry import is_evidence_model

#: The `on_delete` behaviours that leave an observation where it is. Everything
#: else either removes the row (`CASCADE`) or rewrites it (`SET_NULL`,
#: `SET_DEFAULT`, `SET(...)`), and both happen through Django's collector, where
#: no refusal in `core/models.py` is consulted.
PERMITTED_ON_DELETE: Final[frozenset[str]] = frozenset({"DO_NOTHING", "PROTECT", "RESTRICT"})

# Every first-party model declaring `not_evidence = True`, by label.
#
# The declared way out of the evidence rules, recorded so that taking it is a
# visible act rather than a quiet one -- the same shape `RECORDED_EXEMPTIONS` has
# in the source scans, and for the same reason. `CPM-AD-2` exempts the run ledger
# in so many words, and `CPM-EVIDENCE-S03` added it: `core.CollectionRun` is
# `collection_runs` and `core.PolicyRun` is `policy_runs`, both mutable by
# construction because a run row is created before the first outbound call and
# finalized afterwards. Both declare the exemption on `RunLedgerModel`, the
# abstract base they share, and the reason is in that class's docstring.
#
# The labels come from `tests/model_registry.py` rather than being written out
# again here: three modules need this pair, and three hand-written copies that
# can disagree look exactly like three passing tests.
#
# The case below fails from both sides: a model that takes the escape without
# being recorded, and a record naming a model that no longer takes it.
RECORDED_NOT_EVIDENCE: Final[frozenset[str]] = RUN_LEDGER_MODEL_LABELS


def guard_failures(model: type[models.Model]) -> list[str]:
    """Return every way one model has lost the append-only guard.

    Args:
        model: The model to audit.

    Returns:
        One message per failure, each naming the model. Empty for a conforming
        evidence model and for anything that is not evidence at all.

    """
    marks = evidence_marks(model)
    if not marks:
        return []
    label = model._meta.label  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    reason = f"{label} is an evidence model ({', '.join(marks)})"

    if not issubclass(model, AppendOnlyModel):
        missing = (
            f"{reason} but does not inherit AppendOnlyModel, so nothing stops an observation in it being "
            f"overwritten (CPM-AD-2)"
        )
        return [missing]

    failures = [
        f"{reason} but its {name} is a {type(manager).__name__} rather than an AppendOnlyManager, so "
        f"update(), bulk_update() and delete() all work through it (CPM-AD-2)"
        for name, manager in (("_default_manager", model._default_manager), ("_base_manager", model._base_manager))  # noqa: SLF001 - Django's own accessors for the two managers it uses
        if not isinstance(manager, AppendOnlyManager)
    ]
    failures.extend(
        f"{reason} but its {field.name} relation uses on_delete={_on_delete_name(field)}, which removes or "
        f"rewrites the observation through Django's collector, where no refusal is consulted. Use PROTECT, "
        f"RESTRICT or DO_NOTHING (CPM-AD-2)"
        for field in model._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if field.is_relation and _on_delete_name(field) not in PERMITTED_ON_DELETE
    )
    return failures


def _on_delete_name(field: models.Field[object, object]) -> str:
    """Return the name of a relation's `on_delete` behaviour.

    Args:
        field: The relation field.

    Returns:
        The function's `__name__` -- `CASCADE`, `PROTECT`, `set_on_delete` for
        `models.SET(...)` -- or `"<none>"` for a relation that declares none,
        which no forward `ForeignKey` can, but which keeps the audit reporting
        rather than raising if one ever does.

    """
    behaviour = getattr(field.remote_field, "on_delete", None)
    return getattr(behaviour, "__name__", "<none>")


def audit_failures(candidates: list[type[models.Model]]) -> dict[str, list[str]]:
    """Return every guard failure among a set of models, keyed by model label.

    Args:
        candidates: The models to audit.

    Returns:
        Model label to its failures, for the models that have any.

    """
    return {
        model._meta.label: failures  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for model in candidates
        if (failures := guard_failures(model))
    }


# ---------------------------------------------------------------------------
# The sweep, and the guards that it is looking at the right things.
# ---------------------------------------------------------------------------


def test_the_sweep_has_applications_to_look_at() -> None:
    """The vacuity guard for this audit specifically.

    The scope predicate itself is `tests/model_registry.py`'s and is guarded by
    `tests/unit/test_model_registry.py`; what this asserts is that *this* sweep
    is pointed at a non-empty registry, so a run in which the scope had collapsed
    reports a failure here rather than an empty, passing audit.
    """
    assert first_party_models(), "expected this repository's applications to declare models"


def test_every_evidence_model_still_carries_the_append_only_guard() -> None:
    """`EVIDENCE.02-AUDIT-001`, enumerated from the registry rather than from a list.

    `CPM-IDENTITY-S06` landed the first evidence table -- `inventory_snapshots`,
    whose relation to `identity.Package` is the first `PROTECT` this rule is
    actually about -- so this is no longer a sweep over an empty set, and it
    needed no edit to start mattering. The fixture half below is kept rather than
    retired: one real subject can be conforming for reasons the detector never
    had to exercise, and only a deliberately broken model shows that it still
    detects.
    """
    assert evidence_models() != [], "the sweep has nothing to be about"
    assert audit_failures(evidence_models()) == {}


def test_every_model_taking_the_declared_escape_is_recorded() -> None:
    """`not_evidence = True` is a decision, and a decision belongs in a table.

    Checked in both directions, exactly as the source scans check their
    exemptions: a model that declares itself not evidence without being recorded
    fails here, and a record naming a model that no longer declares it fails too.
    Without this the escape would be a door anybody could open by writing one
    line on a model, which is precisely what an audit is for.
    """
    declared = {
        model._meta.label  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for model in exempt_models()
    }

    assert declared == RECORDED_NOT_EVIDENCE


# ---------------------------------------------------------------------------
# The anti-vacuity half: the detector, measured against real models.
# ---------------------------------------------------------------------------


def test_the_detector_accepts_the_intended_declaration() -> None:
    """A subclass of the base, with the managers and relations it inherits.

    The conforming case has to exist, or every assertion below could be
    satisfied by a detector that failed everything.
    """
    with isolate_apps(FIXTURE_APP):

        class Guarded(AppendOnlyModel):
            fact = models.CharField(max_length=32)

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        assert evidence_marks(Guarded) == ["base", "app_label", "observed_at"]
        assert guard_failures(Guarded) == []


def test_the_detector_rejects_an_evidence_model_without_the_base() -> None:
    """The first way to lose the guard, and the one the story names.

    A table carrying `observed_at` and declared as a plain `models.Model`
    inherits no refusal at all: every `save()` on a loaded row silently updates,
    which is `R-06` happening quietly for as long as it takes somebody to look.
    """
    with isolate_apps(FIXTURE_APP):

        class Unguarded(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            observed_at = models.DateTimeField()

            class Meta:
                app_label = FIXTURE_LABEL

        failures = guard_failures(Unguarded)

        assert len(failures) == 1
        assert "does not inherit AppendOnlyModel" in failures[0]
        assert "Unguarded" in failures[0]


def test_the_detector_rejects_a_re_declared_default_manager() -> None:
    """The second way, and the one that passes an inheritance-only audit.

    `objects = models.Manager()` on a model that does inherit the base restores
    `update()`, `bulk_update()` and `delete()` in full, and every refusal in
    `core/models.py` becomes unreachable from the spelling every collector uses.
    """
    with isolate_apps(FIXTURE_APP):

        class ReDeclared(AppendOnlyModel):
            fact = models.CharField(max_length=32)
            objects = models.Manager()

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        failures = guard_failures(ReDeclared)

        assert any("_default_manager" in failure for failure in failures)
        assert any("_base_manager" in failure for failure in failures)


def test_the_detector_rejects_a_base_manager_pointed_elsewhere() -> None:
    """The sharpest spelling of the second way: `_base_manager` alone is redirected.

    `objects` still refuses, so every test written against `objects` passes,
    while `Evidence._base_manager.filter(...).update(...)` compiles and runs an
    `UPDATE`. Django uses `_base_manager` internally for related-object lookups,
    so it is a real manager on every model whether or not anybody named it --
    which is why `AppendOnlyModel.Meta` names it.

    `default_manager_name` is pinned back at `objects` here on purpose, so the
    case isolates the base manager: without it the failure below would be
    reported for both, and this case would not be able to tell a detector that
    checks `_base_manager` from one that only checks the default.
    """
    with isolate_apps(FIXTURE_APP):

        class RedirectedBase(AppendOnlyModel):
            fact = models.CharField(max_length=32)
            unguarded = models.Manager()

            class Meta:
                app_label = EVIDENCE_APP_LABEL
                default_manager_name = "objects"
                base_manager_name = "unguarded"

        failures = guard_failures(RedirectedBase)

        assert [failure for failure in failures if "_base_manager" in failure] != []
        assert [failure for failure in failures if "_default_manager" in failure] == []


def test_any_locally_declared_manager_displaces_the_default() -> None:
    """A finding worth a case of its own: the displacement needs no bad intent.

    `Options.managers` sorts by `(inheritance depth, creation counter)`, so a
    manager declared on the concrete model comes before one inherited from the
    abstract base *whatever it is called*. A collector adding an ordinary
    `PackageManager()` for convenience -- not touching `objects`, not meaning to
    change anything -- silently makes `_default_manager` the plain one, and every
    Django internal that reaches for the default gets an unguarded queryset.

    That is not obvious, it is not documented anywhere a writer would look, and
    it is why this audit checks the *resolved* managers rather than the presence
    of the inherited declaration.
    """
    with isolate_apps(FIXTURE_APP):

        class WithAHelper(AppendOnlyModel):
            fact = models.CharField(max_length=32)
            helpers = models.Manager()

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        assert isinstance(WithAHelper._default_manager, models.Manager)  # noqa: SLF001 - Django's own accessor
        assert not isinstance(WithAHelper._default_manager, AppendOnlyManager)  # noqa: SLF001 - Django's own accessor
        assert [failure for failure in guard_failures(WithAHelper) if "_default_manager" in failure] != []


def test_the_base_manager_is_the_append_only_one_by_default() -> None:
    """The positive half of the same rule, and the reason `Meta.base_manager_name` exists.

    A subclass declaring its own `Meta` -- which every concrete model does,
    because it must declare `app_label` or live in an application -- does not
    inherit the parent's `Meta` attributes directly. What carries the name across
    is `Options.base_manager` walking the MRO for a parent whose base manager is
    named, and that is a fact about Django rather than about this repository, so
    it is pinned here.
    """
    with isolate_apps(FIXTURE_APP):

        class Inheriting(AppendOnlyModel):
            fact = models.CharField(max_length=32)

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        assert isinstance(Inheriting._base_manager, AppendOnlyManager)  # noqa: SLF001 - Django's own accessor
        assert isinstance(Inheriting._default_manager, AppendOnlyManager)  # noqa: SLF001 - Django's own accessor


@pytest.mark.parametrize(
    "behaviour",
    [models.CASCADE, models.SET_NULL, models.SET_DEFAULT],
    ids=["cascade", "set-null", "set-default"],
)
def test_the_detector_rejects_a_relation_that_removes_or_rewrites_the_row(behaviour: object) -> None:
    """The third way, which no refusal in `core/models.py` can see.

    Django's collector never calls `Model.delete()` or `QuerySet.delete()`, so a
    parent row going away takes the observations with it -- or, for the two `SET`
    behaviours, rewrites them in place. All three are the loss `CPM-FR-36`
    forbids, arriving from the other end of a relation.
    """
    with isolate_apps(FIXTURE_APP):

        class Subject(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            name = models.CharField(max_length=32)

            class Meta:
                app_label = FIXTURE_LABEL

        class Cascading(AppendOnlyModel):
            # Nullable because SET_NULL requires it; the relation is the subject
            # of the case either way.
            subject = models.ForeignKey(
                Subject,
                on_delete=behaviour,
                null=True,
                default=None,
            )

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        failures = guard_failures(Cascading)

        assert [failure for failure in failures if "on_delete" in failure] != []
        assert "subject" in failures[0]


def test_the_detector_accepts_a_protected_relation() -> None:
    """The other side of the same rule, so it cannot be satisfied by rejecting relations.

    Evidence references a package by its integer primary key (`CPM-AD-3`), so
    relations are the normal case rather than an exception. `PROTECT` is the
    right answer: deleting a package that has observations should fail loudly,
    not silently discard the observations.
    """
    with isolate_apps(FIXTURE_APP):

        class Package(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            canonical_name = models.CharField(max_length=32)

            class Meta:
                app_label = FIXTURE_LABEL

        class Protected(AppendOnlyModel):
            package = models.ForeignKey(Package, on_delete=models.PROTECT)

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        assert guard_failures(Protected) == []


def test_the_detector_looks_at_no_model_that_is_not_evidence() -> None:
    """The negative control, and the reason the marks are not simply "every model".

    A run-ledger row is mutable by construction -- `CPM-AD-2` exempts
    `collection_runs` and `policy_runs` in so many words, and `CPM-EVIDENCE-S03`
    declares them -- so an audit that held every model to the append-only base
    would be describing a rule the architecture explicitly does not have, and
    would be switched off rather than satisfied.
    """
    with isolate_apps(FIXTURE_APP):

        class Ordinary(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            started_at = models.DateTimeField()
            status = models.CharField(max_length=16)

            class Meta:
                app_label = FIXTURE_LABEL

        assert is_evidence_model(Ordinary) is False
        assert guard_failures(Ordinary) == []


def test_a_model_declaring_the_escape_is_audited_no_further() -> None:
    """The declared way out, exercised rather than only described.

    `CPM-EVIDENCE-S03`'s ledger will carry `observed_at`-shaped columns and be
    legitimately mutable; without an escape its only options would be to fail
    this audit or to rename its columns to dodge a mark, and the second is worse.
    The escape is recorded by the case above, which is what keeps it from being
    silent.
    """
    with isolate_apps(FIXTURE_APP):

        class RunLedger(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            observed_at = models.DateTimeField()

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        setattr(RunLedger, NOT_EVIDENCE_ATTRIBUTE, True)

        assert evidence_marks(RunLedger) == []
        assert guard_failures(RunLedger) == []


def test_the_detector_separates_the_conforming_from_the_offending_in_one_sweep() -> None:
    """The whole definition exercised at once, which is how the sweep will meet it.

    Four models, checked in a single pass: the one that forgot the base is
    reported and the three that are guarded are not. A detector that reported
    everything, or nothing, passes each of the cases above in isolation only if
    they are read one at a time -- this is the one that fails.
    """
    with isolate_apps(FIXTURE_APP):

        class BothMarks(AppendOnlyModel):
            class Meta:
                app_label = EVIDENCE_APP_LABEL

        class BaseOnly(AppendOnlyModel):
            class Meta:
                app_label = FIXTURE_LABEL

        class ObservedAtOnly(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            observed_at = models.DateTimeField()

            class Meta:
                app_label = FIXTURE_LABEL

        class NeitherMark(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            recorded_at = models.DateTimeField()

            class Meta:
                app_label = FIXTURE_LABEL

        candidates = [BothMarks, BaseOnly, ObservedAtOnly, NeitherMark]

        assert [model.__name__ for model in candidates if is_evidence_model(model)] == [
            "BothMarks",
            "BaseOnly",
            "ObservedAtOnly",
        ]
        assert list(audit_failures(candidates)) == [f"{FIXTURE_LABEL}.ObservedAtOnly"]
