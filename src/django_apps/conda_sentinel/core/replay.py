"""`CPM-FR-22`: whether re-running a version at a cut-off really did reproduce the answer.

`core/policy_run.py` makes a replay *possible* -- `execute_policy_run` takes the
cut-off rather than choosing one -- and every pass is written to be deterministic at
one. This module is what turns that from a property somebody asserts into one
anybody can check: given two runs, it compares what each pass concluded, per package,
and names every column that differs.

**Why a comparison is part of the requirement rather than a convenience.**
`CPM-FR-22`'s testable consequence is "re-running a stated version against a stated
cut-off reproduces identical results", and a guarantee nobody can evaluate after the
fact is a guarantee about the code rather than about the data. A compliance reviewer
replaying a quarter-old cut-off is asking a question about *these two runs*, and the
honest answer is a diff.

**It compares the derived tables and not the rollup, and that is not an omission.**
`CPM-AD-11` gives `package_health` exactly one row per package, and `core/rollup.py`
replaces it. So a replay overwrites the rollup rather than adding to it, and there is
no earlier row left to compare against -- the derived tables, keyed
`(package, policy_run)` by `CPM-AD-21`, are the only record that survives both runs.
That is also why a replay has an operational consequence worth stating loudly, which
`core/management/commands/replay_policy_run.py` and `docs/deployment.md` both do:
until the next scheduled run, the current-health table reflects the cut-off that was
replayed.

**Every pass is compared, including ones added later.** The set comes from
`registered_passes()` rather than a list here, so a ninth pass is covered the day it
is adopted and a reader is never asked to keep two rosters in step.

**Two columns are excluded from every comparison, and only two.** The primary key,
because two runs' rows are different rows; and the run reference itself, because the
whole point is that they name different runs. Everything else is compared --
including `policy_version` and `evidence_cutoff`, which a caller might think are
inputs rather than outputs: they are copied onto every derived row, and a replay
whose rows carried a different version than it was asked for is exactly the failure a
reviewer needs to see.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Final
from typing import cast

from conda_sentinel.core.policy import registered_passes

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Mapping
    from collections.abc import Sequence

    from django.db import models

    from conda_sentinel.core.models import PolicyRun

__all__ = [
    "EXCLUDED_COLUMNS",
    "Difference",
    "ReplayReport",
    "compare_runs",
]

#: The columns no comparison reads, and there are exactly two.
#:
#: `id` because two runs' rows are different rows, and `policy_run` because the
#: whole point of the comparison is that they name different runs. Everything else
#: is compared, including the stamps a caller might take for inputs -- see the
#: module docstring.
EXCLUDED_COLUMNS: Final[frozenset[str]] = frozenset({"id", "policy_run"})


@dataclass(frozen=True, slots=True)
class Difference:
    """One column of one package's row that the two runs disagree about.

    Frozen and slotted, holding only data, so a report can be built, passed around
    and rendered without anything being able to edit a finding after the fact.

    Attributes:
        table: The derived table's own name, as the schema spells it -- the name a
            reviewer would query.
        package_id: The package the two rows are about.
        column: The field the two rows disagree about.
        original: What the run being replayed concluded.
        replayed: What the replay concluded.

    """

    table: str
    package_id: int
    column: str
    original: object
    replayed: object

    def describe(self) -> str:
        """Return this difference as one line a reviewer can read.

        Returns:
            The table, the package, the column and both values.

        """
        return (
            f"{self.table}: package {self.package_id}: {self.column} was {self.original!r}, "
            f"replayed as {self.replayed!r}"
        )


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """What comparing two runs found.

    Attributes:
        original: The run that was replayed.
        replayed: The run that replayed it.
        differences: Every column of every package's row the two disagree about, in
            a stable order -- by table, then package, then column -- so two
            invocations render the same report and a reviewer diffing two reports
            sees only real change.
        compared_rows: How many rows were compared. Carried because "no differences"
            over nothing is not a reproduction, and a report that could not say so
            would let an empty inventory read as a pass.

    """

    original: PolicyRun
    replayed: PolicyRun
    differences: tuple[Difference, ...]
    compared_rows: int

    @property
    def reproduced(self) -> bool:
        """Report whether the replay reproduced the original exactly.

        Returns:
            `True` when nothing differs. **Says nothing about whether anything was
            compared** -- a caller that needs to know a replay covered the inventory
            reads `compared_rows`, and `core/management/commands/replay_policy_run.py`
            reports both rather than folding them together: "identical" over zero
            rows is a different fact from "identical" over ten thousand.

        """
        return not self.differences


def compare_runs(original: PolicyRun, replayed: PolicyRun) -> ReplayReport:
    """Compare what two policy runs concluded, pass by pass and package by package.

    Args:
        original: The run being replayed.
        replayed: The run that replayed it.

    Returns:
        The report. A package present in one run and absent from the other is
        reported as a difference on every compared column, because that is what it
        is: a run that evaluated a package the other did not concluded something
        about it that the other did not.

    """
    differences: list[Difference] = []
    compared = 0
    for policy_pass in registered_passes():
        # `derived_model` is declared `... | None` on the base and is never `None`
        # on a registered pass: `core/policy.py`'s `_require_derived_model` refuses
        # a registration without one. The cast names what the registry guarantees
        # rather than adding a branch nothing can reach -- which would be an
        # uncovered line, and `tests/unit/test_coverage_policy.py` bans the pragma
        # that would hide it.
        model = cast("type[models.Model]", policy_pass.derived_model)
        columns = _compared_columns(model)
        before = _rows_by_package(model, run=original, columns=columns)
        after = _rows_by_package(model, run=replayed, columns=columns)
        compared += len(before.keys() | after.keys())
        differences.extend(_differences_in(model, before=before, after=after, columns=columns))
    return ReplayReport(
        original=original,
        replayed=replayed,
        differences=tuple(differences),
        compared_rows=compared,
    )


def _compared_columns(model: type[models.Model]) -> tuple[str, ...]:
    """Return the columns of one derived table a comparison reads.

    Args:
        model: The derived table.

    Returns:
        Its concrete field names, in declaration order, less `EXCLUDED_COLUMNS`.
        Declaration order rather than sorted, so a report reads in the order the
        model presents its columns -- which is the order the class docstring
        explains them in.

    """
    return tuple(
        field.attname if field.is_relation else field.name
        for field in model._meta.concrete_fields  # noqa: SLF001 - Django's own public-by-convention API
        if field.name not in EXCLUDED_COLUMNS
    )


def _rows_by_package(
    model: type[models.Model],
    *,
    run: PolicyRun,
    columns: Sequence[str],
) -> dict[int, tuple[object, ...]]:
    """Return one run's rows from one derived table, by package.

    Args:
        model: The derived table.
        run: The run whose rows to read.
        columns: The columns to read, in comparison order.

    Returns:
        The compared columns' values, keyed by package. `CPM-AD-21` keys the table
        `(package, policy_run)`, so one run has at most one row per package and the
        mapping cannot lose one.

    """
    manager = model._default_manager  # noqa: SLF001 - Django's own public-by-convention API
    return {row[0]: tuple(row[1:]) for row in manager.filter(policy_run=run).values_list("package_id", *columns)}


def _differences_in(
    model: type[models.Model],
    *,
    before: Mapping[int, tuple[object, ...]],
    after: Mapping[int, tuple[object, ...]],
    columns: Sequence[str],
) -> Iterator[Difference]:
    """Yield every column of every package the two runs disagree about.

    Args:
        model: The derived table, for the report's table name.
        before: The original run's rows, by package.
        after: The replay's rows, by package.
        columns: The columns, in the order the values are held.

    Yields:
        One difference per disagreeing column, packages in ascending order so the
        report is stable.

    """
    table = model._meta.db_table  # noqa: SLF001 - Django's own public-by-convention API
    for package_id in sorted(before.keys() | after.keys()):
        original = before.get(package_id)
        replayed = after.get(package_id)
        for position, column in enumerate(columns):
            was = None if original is None else original[position]
            now = None if replayed is None else replayed[position]
            if was != now:
                yield Difference(
                    table=table,
                    package_id=package_id,
                    column=column,
                    original=was,
                    replayed=now,
                )
