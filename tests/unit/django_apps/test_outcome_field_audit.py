"""`EVIDENCE.01-AUDIT-001`: every derived-status field carries the four sentinels.

`CPM-AD-5`: "Every derived-status column is `CharField(choices=...)`. No boolean
or nullable-boolean status fields anywhere." This is `R-01` at the storage layer,
and it is the half that cannot be fixed later: once a `BooleanField` has a
million rows in it, nothing can tell a row that was genuinely clean from one that
collapsed to clean because the check errored, the package was out of scope, or
nobody had looked yet. The handoff document says as much -- `R-01` needs a
passing `AUDIT` test *before* `CPM-EP-APP` starts.

**Enumerated from the model registry, never from a hand-written list.** The
criterion the test design added to this story says so in those words, and the
reason is the failure mode: a list is edited by whoever remembers it exists, so
the first status field added by someone who did not is the one that escapes. The
registry is edited by adding the field.

The sweep's *scope* -- which applications count as this repository's own -- comes
from `tests/model_registry.py`, which is shared with the two evidence audits
`CPM-EVIDENCE-S02` added. It began here; it moved there for the reason
`tests/source_scan.py` gives about its own primitives, that two sweeps
disagreeing about what they cover look exactly like two passing tests.

**The anti-vacuity guard is the load-bearing half today.** No derived-status
model exists yet -- `CPM-EVIDENCE-S02` and `S03` bring the first ones -- so the
sweep over the registry currently passes by finding nothing, which is exactly how
an audit comes to be permanently green and permanently useless. What stops that
is the fixture half below: the detector is measured against real Django models
built in an isolated registry, one conforming and four broken in the four ways
`CPM-AD-5` names, so a detector that had stopped detecting fails here on the day
it stops rather than on the day the first evidence model lands.

`django.test.utils.isolate_apps` is what keeps those fixtures out of the real
registry. They are genuine model classes with genuine fields -- a stand-in object
would prove the detector works on stand-in objects -- and they are gone when the
block exits, so the sweep above cannot see them and `makemigrations --check`
cannot either.

**What the registry can and cannot see, stated rather than implied.** Django
normalises `choices=SomeTextChoices` into a list of `(value, label)` pairs and
keeps no reference to the class, so no audit reading `Field.choices` can assert
"these choices came from a type `core` composed". What it *can* assert is every
observable consequence of that, and those are what the checks below are:

* the four sentinel values are offered, and each carries the label `core` gives
  it -- Django derives a `TextChoices` label from the member *name*, so a
  hand-rolled table spelling `("not_applicable", "N/A")` fails here even though
  its values are right;
* every value obeys `CPM-AD-5`'s fixed-lowercase rule;
* nothing outside the declared vocabulary can reach the column -- not `NULL`,
  not the empty string through `blank`, and not a `default` that is not itself
  one of the choices.

What survives that and should not be mistaken for approval: a field offering the
four sentinels, correctly labelled, *plus* `"clean"` and `"pending"`. Extra
values are indistinguishable at this level from the determinate verdicts a
per-status type legitimately refines `ok` into -- `outcome_type` exists to add
exactly such members -- so a rule rejecting them would reject the intended
declaration. Closing that gap needs the *type* to be reachable from the field,
which is a change to how a status field is declared and belongs to
`CPM-EVIDENCE-S02`, the story that declares the first one.

**One field name is a derived status and one column is not, and the difference is
recorded rather than assumed.** `CPM-EVIDENCE-S03`'s run ledger stores what
happened to a *run* in a column called `status`, over `RunState` -- a separate
vocabulary that carries none of the four sentinels and must never be composed
from `outcome_type` (`core/runs.py` says why at length). The convention below
recognises the name, so an unamended sweep would demand the sentinels on a column
that must not hold one. `RECORDED_RUN_LEDGER_STATUS` is the amendment: the named
fields leave the sentinel sweep and are checked against `RunState.choices`
instead, and the table is reconciled in both directions. Excluded from one
vocabulary, held to the other -- never simply unchecked.

The failure list is not exhaustive by design. `max_length` shorter than the
longest choice is a real defect and is not checked here, because Django's own
system check `fields.E009` already rejects it; duplicating a framework check
would only give it a second place to drift.

No database and no network: defining a model and reading `_meta` touches neither.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import Final

import pytest
from django.db import models
from django.db.models.fields import NOT_PROVIDED
from django.test.utils import isolate_apps

from conda_package_supply_chain_monitor.core.outcomes import SENTINEL_MEMBERS
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.core.outcomes import outcome_type
from conda_package_supply_chain_monitor.core.runs import RunState
from tests.model_registry import A_THIRD_PARTY_APP_NAME
from tests.model_registry import FIRST_PARTY_APP_NAMES
from tests.model_registry import FIXTURE_APP
from tests.model_registry import FIXTURE_LABEL
from tests.model_registry import RUN_LEDGER_MODEL_LABELS
from tests.model_registry import first_party_app_names
from tests.model_registry import first_party_models
from tests.model_registry import installed_app_names

if TYPE_CHECKING:
    from collections.abc import Iterable

#: What makes a field a derived status: it is named for one.
#:
#: A convention rather than a marker attribute, because the audit has to be able
#: to recognise the *wrong* declaration -- a `BooleanField` named
#: `license_status` carries no marker anybody would have remembered to add, and
#: it is the exact field this rule exists to reject. The name is what the author
#: of that field would have written either way.
DERIVED_STATUS_NAMES: Final[frozenset[str]] = frozenset({"outcome", "status"})
DERIVED_STATUS_SUFFIXES: Final[tuple[str, ...]] = ("_outcome", "_status")

#: `CPM-AD-5`'s "fixed lowercase string values", as a pattern. A value that fails
#: it -- `""`, `"N/A"`, `"not applicable "` -- is one that will be emitted
#: verbatim on an export and an API surface (`CPM-AD-24`) and read back by
#: nobody.
FIXED_VALUE: Final = re.compile(r"[a-z][a-z0-9_]*")

#: How many elements a choices entry has. Named because the check that uses it
#: is what stops a malformed entry raising a bare `ValueError` from inside the
#: audit instead of being reported as the finding it is.
CHOICE_ENTRY_LENGTH: Final[int] = 2

#: A per-status type of the kind `CPM-EVIDENCE-S02` will declare, used to build
#: the conforming fixture so that the fixture demonstrates the intended
#: declaration rather than a hand-assembled approximation of it.
FIXTURE_OUTCOME = outcome_type("WharfOutcome", [("MOORED", "moored"), ("ADRIFT", "adrift")])

# The derived-status *names* that are not derived statuses, by model label and
# field name.
#
# `CPM-EVIDENCE-S03`'s run ledger has a `status` column, and `status` is in
# `DERIVED_STATUS_NAMES` above, so an unamended sweep demands the four outcome
# sentinels on a column that must never hold one. That is a collision between a
# convention and a rule the ledger is not bound by, and there were two ways out.
# Renaming the column to `state` would dodge a marker, which
# `tests/model_registry.py` names as the worse option in the same passage that
# explains why the `not_evidence` escape exists at all. So the name stays and the
# audit is amended here.
#
# **An exemption in this repository is a counted decision, never a hole.** The
# entries below are excluded from the sentinel sweep and then checked against
# `RunState.choices` instead -- excluded from one vocabulary and held to the
# other. Two cases reconcile the table in both directions: every entry must name
# a real field whose choices are exactly `RunState`'s, and no unrecorded field
# anywhere may carry that vocabulary. `core/runs.py` says why the two
# vocabularies are separate.
RECORDED_RUN_LEDGER_STATUS: Final[dict[str, str]] = {
    "core.CollectionRun": "status",
    "core.PolicyRun": "status",
}

#: `RunState`'s values, for recognising a run-ledger status column that nobody
#: recorded. Derived from the type rather than written out, so a sixth run state
#: is covered the moment it is declared.
RUN_LEDGER_VALUES: Final[frozenset[str]] = frozenset(RunState.values)


def is_derived_status_name(name: str) -> bool:
    """Report whether a field name declares a derived status.

    Args:
        name: The field's attribute name.

    Returns:
        True for `status`, `outcome`, and anything ending in `_status` or
        `_outcome`. False for `status_note` and `observed_at`, which are not
        statuses however near one they sit.

    """
    return name in DERIVED_STATUS_NAMES or name.endswith(DERIVED_STATUS_SUFFIXES)


def derived_status_fields(model: type[models.Model]) -> list[models.Field[object, object]]:
    """Return one model's derived-status fields.

    Args:
        model: The model to inspect.

    Returns:
        Every concrete field whose name declares a derived status. Reverse
        relations are excluded: they are not columns and carry no choices.

    """
    return [
        field
        for field in model._meta.get_fields()  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if isinstance(field, models.Field) and is_derived_status_name(field.name)
    ]


def choice_pairs(choices: Iterable[object]) -> list[tuple[str, str]]:
    """Flatten a choices declaration into `(value, label)` pairs.

    Grouped choices -- `(group, [(value, label), ...])` -- are descended into,
    because a status split into optgroups still offers its sentinels. Entries
    that are not two-element sequences are skipped rather than unpacked;
    `malformed_entries` below is what reports them. An unconditional
    `value, label = entry` would raise a bare `ValueError` from inside the audit
    on a one- or three-element entry, which turns a finding into a crash.

    Args:
        choices: A Django choices sequence, normalised or not.

    Returns:
        The pairs, values and labels both as strings, in declaration order.

    """
    pairs: list[tuple[str, str]] = []
    for entry in choices or ():
        if not isinstance(entry, list | tuple) or len(entry) != CHOICE_ENTRY_LENGTH:
            continue
        value, label = entry
        if isinstance(label, list | tuple):
            pairs.extend(choice_pairs(label))
        else:
            pairs.append((str(value), str(label)))
    return pairs


def malformed_entries(choices: Iterable[object]) -> list[str]:
    """Return every choices entry that is not a `(value, label)` pair.

    Args:
        choices: A Django choices sequence.

    Returns:
        One repr per entry that `choice_pairs` had to skip.

    """
    return [
        repr(entry)
        for entry in choices or ()
        if not isinstance(entry, list | tuple) or len(entry) != CHOICE_ENTRY_LENGTH
    ]


def field_failures(field: models.Field[object, object]) -> list[str]:
    """Return every way one derived-status field breaks `CPM-AD-5`.

    See the module docstring for what this can and cannot prove, and for why the
    list is deliberately not exhaustive.

    Args:
        field: The field to check.

    Returns:
        One string per failure, empty for a conforming field.

    """
    if not isinstance(field, models.CharField):
        return [f"is a {type(field).__name__}; a derived status is a CharField with choices (CPM-AD-5)"]

    failures: list[str] = []
    if field.null:
        failures.append("is nullable; NULL would stand in for a sentinel that has its own value (CPM-FR-6)")
    if field.blank:
        failures.append("allows blank; the empty string is a non-answer with no name and no value (CPM-FR-6)")

    malformed = malformed_entries(field.choices or ())
    if malformed:
        failures.append(f"declares choices entries that are not (value, label) pairs: {malformed}")

    offered = dict(choice_pairs(field.choices or ()))
    missing = [value for _, value in SENTINEL_MEMBERS if value not in offered]
    if missing:
        failures.append(f"offers no {', '.join(missing)} among its choices {sorted(offered)}")

    unfixed = sorted(value for value in offered if not FIXED_VALUE.fullmatch(value))
    if unfixed:
        failures.append(f"offers values that are not fixed lowercase tokens: {unfixed} (CPM-AD-5)")

    drifted = {
        value: offered[value]
        for _, value in SENTINEL_MEMBERS
        if value in offered and offered[value] != OutcomeState(value).label
    }
    if drifted:
        failures.append(
            f"labels its sentinels differently from core: {drifted}. Django derives a TextChoices label from "
            f"the member name, so these choices were not composed by core.outcomes.outcome_type",
        )

    if field.default is not NOT_PROVIDED and str(field.default) not in offered:
        failures.append(f"defaults to {field.default!r}, which is not one of its own choices")
    return failures


def is_recorded_run_ledger_status(model: type[models.Model], field: models.Field[object, object]) -> bool:
    """Report whether a field is the recorded run-ledger status of its model.

    Args:
        model: The model the field belongs to.
        field: The field to classify.

    Returns:
        True only for an exact `(label, field name)` match in
        `RECORDED_RUN_LEDGER_STATUS`. Keyed on both so that recording
        `core.CollectionRun` does not exempt a second status field somebody adds
        to the same model later.

    """
    label = str(model._meta.label)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
    return RECORDED_RUN_LEDGER_STATUS.get(label) == field.name


def carries_the_run_vocabulary(field: models.Field[object, object]) -> bool:
    """Report whether a field's choices offer every run state.

    Args:
        field: The field to classify.

    Returns:
        True when all five of `RunState`'s values are among the field's choices.
        A *superset* test rather than equality: a ledger status refined with an
        extra verdict still belongs to the run vocabulary, and it is exactly the
        field that would otherwise fall between the two reconciliations.

    """
    return {value for value, _ in choice_pairs(field.choices or ())} >= RUN_LEDGER_VALUES


def audited_status_fields(model: type[models.Model]) -> list[models.Field[object, object]]:
    """Return the derived-status fields the sentinel sweep still applies to.

    Args:
        model: The model to inspect.

    Returns:
        Every derived-status field except the recorded run-ledger ones, which are
        checked against `RunState.choices` by the cases below instead. See
        `RECORDED_RUN_LEDGER_STATUS` for why the exclusion exists and what
        replaces it.

    """
    return [field for field in derived_status_fields(model) if not is_recorded_run_ledger_status(model, field)]


def model_failures(model: type[models.Model]) -> dict[str, list[str]]:
    """Return every derived-status failure on one model, keyed by field name.

    Args:
        model: The model to audit.

    Returns:
        Field name to its failures. Empty when the model declares no derived
        status, or declares them all correctly. Recorded run-ledger status fields
        are not reported here; they are checked against the run vocabulary
        instead.

    """
    return {field.name: failures for field in audited_status_fields(model) if (failures := field_failures(field))}


# ---------------------------------------------------------------------------
# The sweep, and the guard that the sweep is looking at the right things.
# ---------------------------------------------------------------------------


def test_the_registry_scope_reaches_this_repositorys_applications() -> None:
    """The scope resolves to real applications, and excludes third-party ones.

    Without this the sweep below could pass because `first_party_models` had
    narrowed to nothing -- an app moved, a path comparison that stopped
    matching -- and the failure would look exactly like a clean repository.

    The predicate is `tests/model_registry.py`'s, called rather than re-derived:
    a guard that computed the scope a second way would keep passing while the
    scope the sweep above actually uses had drifted, which is the failure mode
    `tests/source_scan.py` was extracted to prevent.
    """
    in_scope = first_party_app_names()
    installed = installed_app_names()

    for name in FIRST_PARTY_APP_NAMES:
        assert name in in_scope, name
    # Asserted installed *before* asserted out of scope. A third-party package
    # that had been removed would satisfy "not in scope" for the wrong reason,
    # and the exclusion this case exists to prove would go untested -- the same
    # vacuity `NAMED_INHERITED_CALL_SITES` is guarded against in the clock audit.
    assert A_THIRD_PARTY_APP_NAME in installed, A_THIRD_PARTY_APP_NAME
    assert A_THIRD_PARTY_APP_NAME not in in_scope
    assert first_party_models(), "expected this repository's applications to declare models"


def test_every_derived_status_field_carries_the_four_sentinels() -> None:
    """`CPM-AD-5`, enumerated from the registry rather than from a list.

    No model declares a derived status yet, so this passes over an empty set
    today. That is stated rather than hidden: what keeps the case honest in the
    meantime is the fixture half below, which proves the detector still detects.
    The day `CPM-EVIDENCE-S02` lands the first evidence model, this becomes the
    assertion that matters and needs no edit to start mattering.
    """
    offenders = {
        model._meta.label: failures  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for model in first_party_models()
        if (failures := model_failures(model))
    }

    assert offenders == {}


def test_no_first_party_model_declares_a_boolean_named_like_a_status() -> None:
    """The same rule stated as the shape it is most often broken by.

    Separate from the sweep because a `BooleanField` is caught by
    `field_failures` on the way to the choices check, and a reader of a failure
    naming "offers no not_applicable" would go looking for a choices table on a
    field that has none.
    """
    booleans = [
        f"{model._meta.label}.{field.name}"  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for model in first_party_models()
        for field in derived_status_fields(model)
        if isinstance(field, models.BooleanField)
    ]

    assert booleans == []


# ---------------------------------------------------------------------------
# The run-ledger amendment, reconciled in both directions.
# ---------------------------------------------------------------------------


def test_the_run_ledger_status_table_has_entries_to_check() -> None:
    """The two cases below mean nothing if the table they read is empty.

    The same guard `RECORDED_EXEMPTIONS` gets in the source scans: a table that
    had been emptied would make both reconciliations pass by iterating over
    nothing, and the exclusion they exist to police would be unpoliced.

    Its keys are also tied to `RUN_LEDGER_MODEL_LABELS`, which is where the
    `CPM-AD-2` exemption is recorded once for the three modules that need it.
    The table stays a literal because the *field name* is per-model information
    that a shared set of labels cannot carry -- but a third ledger model recorded
    as not-evidence and forgotten here fails on this line rather than three cases
    later with a message about outcome sentinels.
    """
    assert RECORDED_RUN_LEDGER_STATUS != {}
    assert set(RECORDED_RUN_LEDGER_STATUS) == RUN_LEDGER_MODEL_LABELS


def test_every_recorded_run_ledger_status_is_checked_against_the_run_vocabulary() -> None:
    """The first direction: an excluded field is checked, not skipped.

    Each entry has to name a model this repository declares, a derived-status
    field on it, and choices that are *exactly* `RunState.choices` -- values and
    labels both, so a hand-rolled table carrying the five run values under
    different labels fails here the same way a hand-rolled outcome table fails
    the sentinel sweep.

    Without this the exclusion would be a hole: a field removed from one
    vocabulary's audit and held to nothing at all, which is worse than the
    collision the exclusion was written to resolve.
    """
    by_label = {
        str(model._meta.label): model  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for model in first_party_models()
    }
    expected = {f"{label}.{name}": list(RunState.choices) for label, name in RECORDED_RUN_LEDGER_STATUS.items()}
    found: dict[str, list[tuple[str, str]]] = {}

    for label, field_name in sorted(RECORDED_RUN_LEDGER_STATUS.items()):
        assert label in by_label, f"{label} is recorded as a run-ledger status but declares no such model"
        fields = {field.name: field for field in derived_status_fields(by_label[label])}
        assert field_name in fields, f"{label} declares no derived-status field named {field_name}"
        found[f"{label}.{field_name}"] = choice_pairs(fields[field_name].choices or ())

    assert found == expected


def test_no_unrecorded_status_field_carries_the_run_ledger_vocabulary() -> None:
    """The second direction: a new ledger status cannot arrive unrecorded.

    A third run-ledger model added without an entry above would be swept for the
    four outcome sentinels and fail with a message about a vocabulary it is not
    bound by. This case fails first, and says what is actually wrong: the field
    carries `RunState`'s values and nobody recorded the decision.

    **A superset, not an exact match.** A field offering the five run states
    *plus* one more is the likeliest next ledger column -- `RunState` refined the
    way `outcome_type` refines `ok` -- and exact equality would let it through
    both directions: not recorded, so not excluded; not an exact match, so not
    reported here. It would then fail the sentinel sweep with precisely the
    confusing message this case exists to pre-empt.
    """
    unrecorded = [
        f"{model._meta.label}.{field.name}"  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        for model in first_party_models()
        for field in derived_status_fields(model)
        if not is_recorded_run_ledger_status(model, field) and carries_the_run_vocabulary(field)
    ]

    assert unrecorded == []


def test_the_run_vocabulary_detector_sees_a_refined_run_status_too() -> None:
    """The superset rule, exercised rather than only argued.

    The sweep above passes over an empty set today -- every run-ledger status
    there is is recorded -- so without this the widening from equality to a
    superset would be a change no case can tell from the version before it.
    """
    with isolate_apps(FIXTURE_APP):

        class Refined(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            status = models.CharField(max_length=16, choices=[*RunState.choices, ("retrying", "Retrying")])
            unrelated_status = models.CharField(max_length=32, choices=OutcomeState.choices)

            class Meta:
                app_label = FIXTURE_LABEL

        fields = {field.name: field for field in derived_status_fields(Refined)}

        assert carries_the_run_vocabulary(fields["status"]) is True
        assert carries_the_run_vocabulary(fields["unrelated_status"]) is False


def test_a_run_ledger_status_that_is_not_recorded_is_still_swept() -> None:
    """The exclusion is keyed on the model, not on the vocabulary it happens to use.

    A field carrying `RunState.choices` on a model nobody recorded is still
    reported by the sentinel sweep, which is what stops the amendment from being
    a general licence for the run vocabulary anywhere it turns up.
    """
    with isolate_apps(FIXTURE_APP):

        class Unrecorded(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            status = models.CharField(max_length=16, choices=RunState.choices)

            class Meta:
                app_label = FIXTURE_LABEL

        assert "status" in model_failures(Unrecorded)


# ---------------------------------------------------------------------------
# The anti-vacuity half: the detector, measured against real models.
# ---------------------------------------------------------------------------


def test_the_detector_accepts_a_conforming_model() -> None:
    """A `CharField` over a composed outcome type, which is the intended declaration.

    Both spellings a story will reach for: a per-status type from `outcome_type`,
    and `OutcomeState` itself where no refinement is needed.
    """
    with isolate_apps(FIXTURE_APP):

        class Conforming(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(max_length=32, choices=FIXTURE_OUTCOME.choices)
            currency_outcome = models.CharField(max_length=32, choices=OutcomeState.choices)

            class Meta:
                app_label = FIXTURE_LABEL

        assert [field.name for field in derived_status_fields(Conforming)] == [
            "license_status",
            "currency_outcome",
        ]
        assert model_failures(Conforming) == {}


def test_the_detector_rejects_a_boolean_status_field() -> None:
    """The declaration `CPM-AD-5` bans outright, and the one this audit exists for."""
    with isolate_apps(FIXTURE_APP):

        class BooleanStatus(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.BooleanField(default=False)

            class Meta:
                app_label = FIXTURE_LABEL

        failures = model_failures(BooleanStatus)

        assert "license_status" in failures
        assert "BooleanField" in failures["license_status"][0]


def test_the_detector_rejects_a_nullable_status_field() -> None:
    """NULL is a fifth non-answer with no name and no value.

    A nullable status column reintroduces exactly the ambiguity the four
    sentinels exist to remove: the row that is NULL because nobody looked and the
    row that is NULL because the check errored are indistinguishable again, and
    every reader has to guess which.
    """
    with isolate_apps(FIXTURE_APP):

        class NullableStatus(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(  # noqa: DJ001 - the nullable status is what this case rejects
                max_length=32,
                choices=OutcomeState.choices,
                null=True,
            )

            class Meta:
                app_label = FIXTURE_LABEL

        failures = model_failures(NullableStatus)

        assert "license_status" in failures
        assert any("nullable" in failure for failure in failures["license_status"])


def test_the_detector_rejects_a_status_field_that_allows_blank() -> None:
    """`blank=True` is `null=True` wearing a different name.

    It puts the empty string back in reach of the column, and the empty string is
    a fifth non-answer with no name, no value and no place in the precedence
    order -- so a reader meets it and has to guess whether it means unknown,
    not applicable, or a row written before the field existed.
    """
    with isolate_apps(FIXTURE_APP):

        class BlankStatus(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(max_length=32, choices=OutcomeState.choices, blank=True)

            class Meta:
                app_label = FIXTURE_LABEL

        failures = model_failures(BlankStatus)

        assert any("blank" in failure for failure in failures["license_status"])


def test_the_detector_rejects_a_default_outside_the_vocabulary() -> None:
    """`default=""` is how the empty string arrives even on a non-blank column.

    Every row inserted without an explicit status then carries a value the
    precedence order cannot rank, which `aggregate` refuses -- at read time, in a
    rollup, long after the migration that created it.
    """
    with isolate_apps(FIXTURE_APP):

        class EmptyDefault(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(max_length=32, choices=OutcomeState.choices, default="")

            class Meta:
                app_label = FIXTURE_LABEL

        assert any("defaults to" in failure for failure in model_failures(EmptyDefault)["license_status"])


def test_the_detector_accepts_a_default_that_is_one_of_the_choices() -> None:
    """The other side of the same rule, so it cannot be satisfied by rejecting all defaults.

    `default=OutcomeState.UNKNOWN` is the *right* default for a status nobody has
    computed yet -- it is the honest one -- and an audit that failed it would be
    pushing writers back toward a nullable column.
    """
    with isolate_apps(FIXTURE_APP):

        class UnknownByDefault(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(
                max_length=32,
                choices=OutcomeState.choices,
                default=OutcomeState.UNKNOWN,
            )

            class Meta:
                app_label = FIXTURE_LABEL

        assert model_failures(UnknownByDefault) == {}


def test_the_detector_rejects_a_hand_rolled_choices_table() -> None:
    """The four right values with the wrong labels never came from `core`.

    This is as close as a registry-level audit gets to "these choices were
    composed by `outcome_type`": Django derives a `TextChoices` label from the
    member *name*, so every type the factory builds labels `not_applicable` as
    "Not Applicable". A table typed out by hand almost never does, and this is
    the case that catches it. The module docstring records what still gets
    through and why.
    """
    with isolate_apps(FIXTURE_APP):

        class HandRolled(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(
                max_length=32,
                choices=[
                    ("error", "Error"),
                    ("unknown", "Unknown"),
                    ("not_found", "Not found"),
                    ("not_applicable", "N/A"),
                    ("ok", "OK"),
                ],
            )

            class Meta:
                app_label = FIXTURE_LABEL

        failures = model_failures(HandRolled)["license_status"]

        assert any("not composed by core" in failure for failure in failures)


def test_the_detector_rejects_a_value_that_is_not_a_fixed_lowercase_token() -> None:
    """`CPM-AD-5`'s "fixed lowercase string values", enforced rather than assumed.

    The values are emitted verbatim on every export and API surface
    (`CPM-AD-24`), so `"N/A"` or `"not applicable"` is a wire-format defect
    rather than a style one.
    """
    with isolate_apps(FIXTURE_APP):

        class ShoutingStatus(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(
                max_length=32,
                choices=[*OutcomeState.choices, ("Not Sure", "Not Sure")],
            )

            class Meta:
                app_label = FIXTURE_LABEL

        failures = model_failures(ShoutingStatus)["license_status"]

        assert any("fixed lowercase" in failure for failure in failures)


def test_the_detector_reads_grouped_choices() -> None:
    """A status split into optgroups still offers its sentinels.

    The recursion exists because Django permits the shape; without a case it
    would never run, and the first grouped status field would be reported as
    missing all four sentinels for a reason nobody could act on.
    """
    grouped = [
        ("Sentinels", [(value, OutcomeState(value).label) for _, value in SENTINEL_MEMBERS]),
        ("Verdicts", [("ok", OutcomeState.OK.label)]),
    ]

    with isolate_apps(FIXTURE_APP):

        class GroupedStatus(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(max_length=32, choices=grouped)

            class Meta:
                app_label = FIXTURE_LABEL

        assert model_failures(GroupedStatus) == {}


@pytest.mark.parametrize(
    "entry",
    [("lonely",), ("a", "b", "c"), "not-a-pair"],
    ids=["one-element", "three-elements", "bare-string"],
)
def test_a_malformed_choices_entry_is_reported_rather_than_raised(entry: object) -> None:
    """A finding, not a crash.

    An unconditional `value, label = entry` inside the audit turns a malformed
    declaration into a `ValueError` raised from the audit's own frame -- which
    reports no field, no model and no rule, and reads as the audit being broken
    rather than the field.
    """
    choices = [*OutcomeState.choices, entry]

    assert malformed_entries(choices) == [repr(entry)]
    assert choice_pairs(choices) == list(OutcomeState.choices)


def test_the_detector_rejects_a_char_field_missing_a_sentinel() -> None:
    """Choices that carry three of the four, which is how the vocabulary drifts.

    Named in the failure, because "this field is wrong" sends a reader to read
    the whole choices table and "offers no not_applicable" does not.
    """
    dropped = "not_applicable"
    partial = [choice for choice in OutcomeState.choices if choice[0] != dropped]

    with isolate_apps(FIXTURE_APP):

        class PartialStatus(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(max_length=32, choices=partial)

            class Meta:
                app_label = FIXTURE_LABEL

        failures = model_failures(PartialStatus)

        assert dropped in failures["license_status"][0]


def test_the_detector_rejects_a_status_field_with_no_choices_at_all() -> None:
    """A bare `CharField` is a free-text status, which is every vocabulary at once."""
    with isolate_apps(FIXTURE_APP):

        class FreeTextStatus(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            license_status = models.CharField(max_length=32)

            class Meta:
                app_label = FIXTURE_LABEL

        assert model_failures(FreeTextStatus) != {}


def test_the_detector_looks_at_no_field_that_is_not_a_status() -> None:
    """The negative control, and the reason the convention is narrow.

    An audit that flagged `observed_at` or `status_note` would be describing a
    rule nobody agreed to, and it would be switched off rather than satisfied.
    """
    with isolate_apps(FIXTURE_APP):

        class Neighbours(models.Model):  # noqa: DJ008 - a fixture in an isolated registry; nothing renders it
            observed_at = models.DateTimeField()
            status_note = models.TextField()
            is_active = models.BooleanField(default=False)

            class Meta:
                app_label = FIXTURE_LABEL

        assert derived_status_fields(Neighbours) == []
        assert model_failures(Neighbours) == {}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("status", True),
        ("outcome", True),
        ("license_status", True),
        ("vulnerability_outcome", True),
        ("status_note", False),
        ("observed_at", False),
        ("statuses", False),
        ("id", False),
    ],
    ids=str,
)
def test_the_field_name_convention_recognises_what_it_claims_to(name: str, *, expected: bool) -> None:
    """The convention itself, pinned so a widening or a narrowing is deliberate.

    It is the audit's whole definition of its own subject: narrow it and fields
    stop being checked, widen it and unrelated columns start failing. Either
    change should be an edit somebody makes here on purpose.
    """
    assert is_derived_status_name(name) is expected
