"""The trace roster: which status the detail view traces, and to which evidence.

`CPM-AD-24` requires that every read surface projects the same values, and names the
failure it prevents: "a new derived status reaching the API but not the governed
view". A detail screen missing a status the health table shows is that failure in its
quietest form -- the remaining rows all look complete, and a reviewer goes looking for
reasoning that is not there.

So the roster is reconciled against the health view's columns rather than checked for
internal consistency, and against the models rather than against itself: a `Trace`
naming a status field no model has, or an evidence relation that is not a foreign key
to an evidence table, would be a row that renders empty on a screen whose whole
purpose is not being empty.

Reads declarations and model metadata: no database, no queries executed.
"""

from __future__ import annotations

from typing import Final

import pytest
from django.db import models

from conda_sentinel.surface.detail import DERIVED_FROM_VERDICTS
from conda_sentinel.surface.detail import HISTORY_LIMIT
from conda_sentinel.surface.detail import TRACES
from conda_sentinel.surface.detail import Trace
from conda_sentinel.surface.health import COLUMNS

#: The module every evidence table lives in. An evidence relation must point into it:
#: a foreign key to another *derived* table would be a status traced to a conclusion
#: rather than to an observation, which is the one thing this screen must not do.
EVIDENCE_MODULE: Final[str] = "conda_sentinel.collectors.models"

#: The traces that deliberately cite nothing, and why each does.
#:
#: Both are downstream of other passes rather than of a collector, which
#: `CPM-PRIORITY-S01` and `CPM-PRIORITY-S02` each state. Enumerated so a *third*
#: status quietly losing its evidence relation is a failing case rather than a row
#: that renders `DERIVED_FROM_VERDICTS` and looks deliberate.
WITHOUT_EVIDENCE: Final[frozenset[str]] = frozenset({"Priority", "Work type"})

#: The two traces that choose their evidence relation per row rather than declaring
#: one. `PackageCurrency` names a snapshot per version surface and records which it
#: treated as authoritative; `PackagePythonReadiness` cites an assessment or a
#: verification depending on which kind of evidence the verdict rests on.
CHOSEN_PER_ROW: Final[frozenset[str]] = frozenset({"Currency", "Py 3.14"})


@pytest.mark.parametrize("trace", TRACES, ids=lambda trace: trace.label)
def test_every_trace_names_a_status_its_model_holds(trace: Trace) -> None:
    """A status field no model has is a row that renders nothing, on an evidence screen.

    Args:
        trace: The trace under test.

    """
    fields = {field.name for field in trace.model._meta.get_fields()}  # noqa: SLF001 - a model's own metadata

    assert trace.status_field in fields, f"{trace.label} reads {trace.status_field}, which {trace.model} has not"


@pytest.mark.parametrize("trace", TRACES, ids=lambda trace: trace.label)
def test_every_trace_reads_a_table_keyed_on_the_package_and_the_run(trace: Trace) -> None:
    """`CPM-AD-21`, which is what makes "read at this row's run" possible at all.

    A derived table keyed on the package alone would have one row whatever the run,
    and the detail screen would show last quarter's verdict beside this morning's
    stamps with nothing to distinguish them.

    Args:
        trace: The trace under test.

    """
    fields = {field.name for field in trace.model._meta.get_fields()}  # noqa: SLF001 - a model's own metadata

    assert {"package", "policy_run"} <= fields, trace.label


@pytest.mark.parametrize(
    "trace",
    [trace for trace in TRACES if trace.evidence_field],
    ids=lambda trace: trace.label,
)
def test_a_declared_evidence_relation_points_at_an_evidence_table(trace: Trace) -> None:
    """A status traced to another *derived* table would be traced to a conclusion.

    Which is the one thing this screen must not do: the reviewer is here to check the
    reasoning, and a chain of verdicts is not evidence however long it is.

    Args:
        trace: The trace under test.

    """
    field = trace.model._meta.get_field(trace.evidence_field)  # noqa: SLF001 - a model's own metadata

    assert field.many_to_one, f"{trace.label}.{trace.evidence_field} is not a foreign key"
    assert field.related_model.__module__ == EVIDENCE_MODULE, field.related_model


@pytest.mark.parametrize(
    "trace",
    [trace for trace in TRACES if trace.evidence_field],
    ids=lambda trace: trace.label,
)
def test_every_evidence_table_records_when_it_observed(trace: Trace) -> None:
    """`observed_at` is what "the timestamp behind each status" is read from.

    Every evidence table inherits it from `AppendOnlyModel`, where it carries no
    default -- so a table that had somehow lost it would make the criterion
    unanswerable rather than merely blank.

    Args:
        trace: The trace under test.

    """
    evidence = trace.model._meta.get_field(trace.evidence_field).related_model  # noqa: SLF001 - a model's own metadata
    fields = {field.name for field in evidence._meta.get_fields()}  # noqa: SLF001 - as above

    assert "observed_at" in fields, evidence


def test_the_traces_cover_every_status_the_health_view_shows() -> None:
    """`CPM-AD-24`: a status shown on one read surface is shown on the other.

    Matched by label, which is the pairing a reader actually makes -- they arrive
    from a column headed "Vulnerability" and look for a row headed the same.
    """
    traced = {trace.label for trace in TRACES}
    shown = {column.label for column in COLUMNS}

    assert shown <= traced, f"the health view shows statuses the detail view does not trace: {sorted(shown - traced)}"


def test_the_traces_add_the_two_the_health_table_shows_outside_its_columns() -> None:
    """Priority and work type are columns of the table but not of its status roster.

    They are shown there and traced here, so this is what stops the reconciliation
    above being satisfied by a detail screen that had quietly dropped them.
    """
    assert {trace.label for trace in TRACES} >= WITHOUT_EVIDENCE


@pytest.mark.parametrize("trace", TRACES, ids=lambda trace: trace.label)
def test_only_the_declared_traces_rest_on_no_observation(trace: Trace) -> None:
    """A status that lost its evidence relation must not render as deliberately unevidenced.

    `DERIVED_FROM_VERDICTS` is an honest answer for two statuses and a *false
    statement about the product* for any other -- currency is observed from a version
    surface whether or not this row chose one. The two render identically, so which
    may say it is declared rather than inferred from an empty field.

    Args:
        trace: The trace under test.

    """
    assert trace.observed == (trace.label not in WITHOUT_EVIDENCE), trace.label


@pytest.mark.parametrize("trace", TRACES, ids=lambda trace: trace.label)
def test_an_observed_status_without_a_declared_relation_chooses_one_per_row(trace: Trace) -> None:
    """The third state, and the one the empty string used to hide.

    A trace that is `observed` and declares no relation must be one that picks its
    relation from the row -- currency by the authority the pass chose, readiness by
    the kind of evidence the verdict rests on. Any other would silently trace to
    nothing.

    Args:
        trace: The trace under test.

    """
    if trace.observed and not trace.evidence_field:
        assert trace.label in CHOSEN_PER_ROW, trace.label


def test_the_roster_has_no_duplicate_labels() -> None:
    """Two rows headed the same would make the screen unreadable and the tests ambiguous.

    `KEV` and `Vulnerability` share a *model* deliberately -- both statuses live on
    `package_vulnerability` -- which is exactly why the labels rather than the models
    have to be unique.
    """
    labels = [trace.label for trace in TRACES]

    assert len(set(labels)) == len(labels)


def test_two_traces_share_one_model_and_that_is_the_point() -> None:
    """One derived row can hold two statuses resting on two different observations.

    `PackageVulnerability` carries the advisory verdict and the KEV membership, and
    each cites its own finding. A roster keyed on the model rather than on the status
    could not express that, and would date the catalogue by the advisory.
    """
    by_model = [trace for trace in TRACES if trace.model.__name__ == "PackageVulnerability"]

    assert len(by_model) > 1
    assert len({trace.evidence_field for trace in by_model}) == len(by_model)


def test_the_history_bound_is_a_display_bound_and_leaves_room_to_see_a_change() -> None:
    """The cap is about scrolling, not retention, and has to be big enough to be useful.

    A cap of one would satisfy every structural assertion here and would make the
    screen useless for the question it exists for: what did this say before, and when
    did it change.
    """
    assert HISTORY_LIMIT > 1
    assert DERIVED_FROM_VERDICTS != ""


@pytest.mark.parametrize("trace", TRACES, ids=lambda trace: trace.label)
def test_every_trace_is_over_a_real_model(trace: Trace) -> None:
    """The roster holds models, not names or strings that happen to look like them.

    Args:
        trace: The trace under test.

    """
    assert issubclass(trace.model, models.Model), trace.label
    assert trace.label.strip() == trace.label
    assert trace.label != ""
