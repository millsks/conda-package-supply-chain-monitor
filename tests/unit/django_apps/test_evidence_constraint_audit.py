"""`EVIDENCE.02-AUDIT-003`: no evidence table carries a unique constraint.

`CPM-AD-7`: "Evidence is always inserted. No evidence table carries a unique
constraint that suppresses an insert. `observed_at` always means the moment of
*this* observation." The append-only base refuses the *update* path; this audit
closes the other way the same history is lost. A unique constraint spanning the
observed fact turns the second observation of an unchanged fact into an
`IntegrityError`, and the collector that meets one has two bad options -- swallow
it, which silently drops the observation, or fall back to `update_or_create`,
which is `R-06` arriving by the front door.

**Idempotency is a property of the run ledger, not of the evidence table.**
`CPM-AD-7` says so in those words, and it is why "just add a unique constraint"
is not the cheap alternative it looks like: a second run inside a collector's
observation window writes a ledger row with status `skipped` and no evidence, and
a manually triggered recollection always writes. Both live in
`CPM-EVIDENCE-S03`'s ledger. A constraint here would be a *second*, incompatible
idempotency rule enforced by the database, which is exactly the disagreement
`CPM-AD-7` was written to prevent.

**What is banned, and what is not.** Any `unique=True` on a field that is not the
primary key, any `unique_together`, and any `UniqueConstraint` -- including one
over expressions, since Django gives it the same class. `unique_for_date`,
`unique_for_month` and `unique_for_year` are banned too: they are enforced by
model validation rather than by the database, but a re-observation rejected by
`full_clean` is a re-observation rejected. A plain `Index` is *not* banned and
must not be: an index on `observed_at` is what makes a freshness query answerable
at all, and an audit that could not tell an index from a unique constraint would
be pushing writers away from the one and toward neither.

**The primary key is exempt because it is not a constraint on the fact.** Every
evidence row gets its own surrogate key at insert (`CPM-AD-3`), which is the
mechanism that lets two identical observations coexist rather than the thing that
stops them.

**Anti-vacuity, and where it comes from.** The registry holds no evidence model
today, so the sweep passes over nothing. Two halves keep that honest. The
detector is measured against fixture models built in an isolated registry, one
per banned spelling -- and it is also measured against `django_service.users`'
own `User`, a real model in this repository that genuinely carries `unique=True`.
That second half is the one that fails if the detector ever stops detecting: a
fixture can be wrong in the same direction as the code it measures, an inherited
platform model cannot.

No database and no network: defining a model and reading `_meta` touches neither.
"""

from __future__ import annotations

from typing import Final

import pytest
from django.contrib.auth import get_user_model
from django.db import models
from django.test.utils import isolate_apps

from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from tests.model_registry import EVIDENCE_APP_LABEL
from tests.model_registry import FIXTURE_APP
from tests.model_registry import FIXTURE_LABEL
from tests.model_registry import evidence_models
from tests.model_registry import first_party_models
from tests.model_registry import is_evidence_model

#: The field-level uniqueness declarations that are enforced by model validation
#: rather than by the database. Banned on the same footing: a re-observation
#: rejected by `full_clean` is a re-observation rejected.
VALIDATION_UNIQUENESS: Final[tuple[str, ...]] = ("unique_for_date", "unique_for_month", "unique_for_year")

#: A first-party model that is not evidence and does carry a unique constraint.
#: It is the anti-vacuity guard's subject: `User.idp_subject` and
#: `User.username` are `unique=True` today, so a detector that had stopped
#: detecting fails here rather than reporting a clean repository.
A_UNIQUE_FIELD_ON_A_NON_EVIDENCE_MODEL: Final[str] = "idp_subject"


def unique_constraints(model: type[models.Model]) -> list[str]:
    """Return every uniqueness declaration on one model, named.

    Reports rather than judges: whether a declaration is an offence depends on
    whether the model is evidence, and separating the two is what lets the same
    detector be pointed at an inherited platform model to prove it still detects.

    Args:
        model: The model to inspect.

    Returns:
        One string per declaration, sorted, each naming the constraint the way
        its author spelled it. The primary key is excluded: it is the surrogate
        key that lets two identical observations coexist, not a constraint on the
        observed fact.

    """
    meta = model._meta  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    found: list[str] = [
        f"{field.name}: unique=True" for field in meta.concrete_fields if field.unique and not field.primary_key
    ]
    found.extend(
        f"{field.name}: {keyword}={getattr(field, keyword)!r}"
        for field in meta.concrete_fields
        for keyword in VALIDATION_UNIQUENESS
        if getattr(field, keyword, None)
    )
    found.extend(f"unique_together {tuple(together)}" for together in meta.unique_together)
    found.extend(
        f"UniqueConstraint {constraint.name!r}"
        for constraint in meta.constraints
        if isinstance(constraint, models.UniqueConstraint)
    )
    return sorted(found)


def constraint_failures(model: type[models.Model]) -> list[str]:
    """Return every uniqueness declaration that `CPM-AD-7` forbids on this model.

    Args:
        model: The model to audit.

    Returns:
        The declarations from `unique_constraints`, for an evidence model.
        Empty for anything that is not evidence, however many unique constraints
        it carries.

    """
    return unique_constraints(model) if is_evidence_model(model) else []


# ---------------------------------------------------------------------------
# The sweep, and the guards that it is looking at the right things.
# ---------------------------------------------------------------------------


def test_no_evidence_model_carries_a_unique_constraint() -> None:
    """`EVIDENCE.02-AUDIT-003`, enumerated from the registry rather than from a list.

    No evidence model exists yet, so this passes over an empty set today. The day
    `CPM-EP-CURRENCY` lands the first evidence table, it becomes the assertion
    that matters and needs no edit to start mattering; until then the two guards
    below are what keep it from being permanently green for the wrong reason.
    """
    offenders = {
        model._meta.label: failures  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for model in evidence_models()
        if (failures := constraint_failures(model))
    }

    assert offenders == {}


def test_the_detector_finds_the_unique_constraint_an_inherited_model_really_has() -> None:
    """The anti-vacuity guard, measured against real in-tree code rather than a fixture.

    `django_service.users.User` carries `unique=True` on `idp_subject` -- `AD-11`
    makes the identity key the sole store and unique is what enforces it -- so a
    detector that had stopped recognising `unique=True` fails here. A fixture
    alone could not do this job: it can be wrong in the same direction as the
    detector that reads it.
    """
    user_model = get_user_model()

    found = unique_constraints(user_model)

    assert user_model in first_party_models()
    assert any(A_UNIQUE_FIELD_ON_A_NON_EVIDENCE_MODEL in declaration for declaration in found), found


def test_a_first_party_model_that_is_not_evidence_is_not_an_offender() -> None:
    """The other side of the same case: the rule is `CPM-AD-7`'s, not a ban on uniqueness.

    An identity key, a `jti`, a canonical package name -- `CPM-AD-3` requires
    `canonical_name` to be `unique=True` -- are all unique on purpose, and an
    audit that failed them would be describing a rule nobody agreed to and would
    be switched off rather than satisfied.
    """
    user_model = get_user_model()

    assert is_evidence_model(user_model) is False
    assert constraint_failures(user_model) == []


# ---------------------------------------------------------------------------
# The anti-vacuity half: the detector, measured against real models.
# ---------------------------------------------------------------------------


def test_the_detector_accepts_an_evidence_model_with_no_uniqueness() -> None:
    """The intended declaration, including the index that must stay permitted.

    An index on `observed_at` is what makes a freshness or window query
    answerable, and it is the declaration nearest to the banned one. If this case
    were missing, a detector that read `Meta.indexes` as constraints would pass
    every other case here.
    """
    with isolate_apps(FIXTURE_APP):

        class Observation(AppendOnlyModel):
            fact = models.CharField(max_length=64)

            class Meta:
                app_label = EVIDENCE_APP_LABEL
                indexes = [models.Index(fields=["observed_at"], name="observation_observed_at")]

        assert unique_constraints(Observation) == []
        assert constraint_failures(Observation) == []


def test_the_detector_rejects_a_unique_field() -> None:
    """The cheapest way to make re-observation impossible, and so the likeliest.

    A collector whose evidence carries `unique=True` on the source's own
    identifier observes the fact once and then raises forever, which reads as a
    broken collector rather than as a modelling mistake.
    """
    with isolate_apps(FIXTURE_APP):

        class UniqueFact(AppendOnlyModel):
            fact = models.CharField(max_length=64, unique=True)

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        failures = constraint_failures(UniqueFact)

        assert failures == ["fact: unique=True"]


def test_the_detector_rejects_unique_together() -> None:
    """The spelling that most looks like idempotency, and is the one `CPM-AD-7` names.

    `(package, observed_at)` or `(package, source)` is what somebody writes to
    stop "duplicate" rows. The duplicates are the point: two observations of an
    unchanged fact are two facts about two moments.
    """
    with isolate_apps(FIXTURE_APP):

        class OncePerPackage(AppendOnlyModel):
            package = models.CharField(max_length=64)
            source = models.CharField(max_length=64)

            class Meta:
                app_label = EVIDENCE_APP_LABEL
                unique_together = (("package", "source"),)

        failures = constraint_failures(OncePerPackage)

        assert failures == ["unique_together ('package', 'source')"]


def test_the_detector_rejects_a_unique_constraint_in_meta() -> None:
    """The modern spelling of the same thing, which a scan for `unique_together` misses.

    Django's own documentation steers writers here rather than to
    `unique_together`, so this is the form the constraint will actually arrive
    in, and the failure names the constraint so a reader knows which line to
    delete.
    """
    with isolate_apps(FIXTURE_APP):

        class ConstrainedObservation(AppendOnlyModel):
            package = models.CharField(max_length=64)

            class Meta:
                app_label = EVIDENCE_APP_LABEL
                constraints = [models.UniqueConstraint(fields=["package"], name="one_row_per_package")]

        failures = constraint_failures(ConstrainedObservation)

        assert failures == ["UniqueConstraint 'one_row_per_package'"]


def test_the_detector_permits_a_check_constraint() -> None:
    """`Meta.constraints` is not itself the offence; a `UniqueConstraint` inside it is.

    A check constraint expresses a rule about what a single row may say, which is
    orthogonal to how many rows there may be, and an audit that rejected the
    whole `constraints` list would take it away for no reason.
    """
    with isolate_apps(FIXTURE_APP):

        class CheckedObservation(AppendOnlyModel):
            count = models.IntegerField()

            class Meta:
                app_label = EVIDENCE_APP_LABEL
                constraints = [
                    models.CheckConstraint(condition=models.Q(count__gte=0), name="observation_count_not_negative"),
                ]

        assert constraint_failures(CheckedObservation) == []


def test_the_detector_rejects_a_one_to_one_relation() -> None:
    """`OneToOneField` is `unique=True` wearing a different name.

    "One evidence row per package" expressed as a relation is the same
    suppression as expressing it as a constraint, and it is easier to write by
    accident: the field type reads as a modelling choice rather than as a rule
    about how many observations may exist.
    """
    with isolate_apps(FIXTURE_APP):

        class Subject(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            name = models.CharField(max_length=64)

            class Meta:
                app_label = FIXTURE_LABEL

        class SoleObservation(AppendOnlyModel):
            # PROTECT rather than CASCADE, and not incidentally: CASCADE on an
            # evidence relation destroys observations through Django's collector,
            # which `EVIDENCE.02-AUDIT-001` rejects. A fixture demonstrating one
            # offence must not quietly carry another.
            subject = models.OneToOneField(Subject, on_delete=models.PROTECT)

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        assert constraint_failures(SoleObservation) == ["subject: unique=True"]


@pytest.mark.parametrize("keyword", VALIDATION_UNIQUENESS, ids=str)
def test_the_detector_rejects_validation_level_uniqueness(keyword: str) -> None:
    """`unique_for_date` never reaches the database, and rejects the row all the same.

    It is enforced by `full_clean`, so a collector writing through a serializer or
    a form meets it and a collector writing through `save()` does not -- which is
    worse than either, because the rule then depends on which write path was
    used.

    Parametrized over the whole table rather than over its first entry: an entry
    no case exercises is an entry that can be deleted with the suite still green,
    which is a ban that has quietly stopped being one. The `_month` and `_year`
    spellings are the wider windows of the same rule, and a collector observing
    daily meets them sooner.
    """
    with isolate_apps(FIXTURE_APP):

        class OncePerWindow(AppendOnlyModel):
            fact = models.CharField(max_length=64, **{keyword: "observed_at"})

            class Meta:
                app_label = EVIDENCE_APP_LABEL

        assert constraint_failures(OncePerWindow) == [f"fact: {keyword}='observed_at'"]


def test_the_detector_reports_every_offence_on_one_model() -> None:
    """A model that breaks the rule three ways is reported three ways.

    Reporting only the first would make removing them an exercise in re-running
    the suite once per constraint, and the second and third would each look like
    a new failure introduced by the fix for the previous one.
    """
    with isolate_apps(FIXTURE_APP):

        class ThoroughlyConstrained(AppendOnlyModel):
            package = models.CharField(max_length=64, unique=True)
            source = models.CharField(max_length=64)

            class Meta:
                app_label = EVIDENCE_APP_LABEL
                unique_together = (("package", "source"),)
                constraints = [models.UniqueConstraint(fields=["source"], name="one_row_per_source")]

        assert constraint_failures(ThoroughlyConstrained) == [
            "UniqueConstraint 'one_row_per_source'",
            "package: unique=True",
            "unique_together ('package', 'source')",
        ]
