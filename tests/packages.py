"""The packages a case's literal ledger keys name, created at those exact keys.

`CPM-EVIDENCE-S09` made `core.CollectionRun.package` a real `ForeignKey`, and a
real foreign key is enforced from the moment it is migrated. Before it, a
`core` integration case could record a run against `package_id=7` for a package
nothing had created -- and several did, each with an arbitrary integer chosen for
readability. Those keys are now claims the database checks, on both backends: the
recorder refuses an unknown one before the insert (`core/ledger.py`), and a row
written directly past the recorder is caught at teardown, because Django's SQLite
backend runs `PRAGMA foreign_key_check` there and PostgreSQL checks the deferred
constraint at commit.

**The keys stay literal and the packages are created to match, rather than the
other way round.** Reversing it -- creating packages and reading their assigned
`pk` back -- would be the smaller diff and the worse test: `A_PACKAGE_ID` reads
as a *chosen* value in the assertions that carry it (`row.package_id ==
A_PACKAGE_ID` says the recorder wrote the key it was handed), and a key taken
from whatever the sequence happened to issue asserts only that two reads of the
same row agree. `0` is the case that makes the point: it is a falsy value and a
perfectly good primary key, and no sequence will ever hand it out.

**One fixture rather than a copy per module.** Three `core` modules need the same
arrangement -- `test_run_ledger.py`, `test_collection.py` and
`test_collector_health.py` -- and three autouse fixtures that can drift apart is
exactly the duplication `tests/collectors.py` and `tests/model_registry.py` were
extracted to prevent: two fixtures that can disagree look like two passing tests.
`packages_fixture` is therefore a factory, and each module binds one.

**It depends on `db`, which is the load-bearing part.** An autouse fixture that
merely *wrote* rows would be relying on pytest-django having already opened the
case's transaction -- undeclared ordering between two autouse fixtures, and
silently wrong for a case that requests `db` or `transactional_db` directly
instead of carrying the marker. Depending on `db` states the requirement, so the
rows land inside the transaction that rolls them back and every case in the
module is a database case whether it says so with a marker or not.

The name each package gets is derived from its key rather than chosen, because
nothing here asserts about names -- these cases are about the *reference*. It is
still a real, unique, non-blank name, which `canonical_name_is_present` requires.

Requires a database. Every caller is an integration case whose transaction rolls
the rows back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

import pytest

from conda_package_supply_chain_monitor.identity.models import Package
from tests.clocks import FIXED_INSTANT

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "PACKAGE_NAME_PREFIX",
    "packages_fixture",
    "packages_keyed",
]

#: What a helper-created package is called, before its key is appended. Distinct
#: enough that a case asserting on a name it did not create cannot match one of
#: these by accident, and stable so a failure message names the helper that made
#: the row.
PACKAGE_NAME_PREFIX: Final[str] = "cpm-fixture-package-"


def packages_keyed(*package_ids: int) -> list[Package]:
    """Create one package per key, each at the primary key it was given.

    `get_or_create` rather than `create`, keyed on the primary key. Nothing here
    is trying to be clever about reuse: it is that a duplicate must not surface
    as an `IntegrityError` raised inside a fixture, which reports as an error
    with the case's own subject nowhere in it. A module that creates a package of
    its own at one of these keys, or a second call in the same transaction, then
    gets the row rather than a failure -- and the `defaults` are only ever
    applied to a key nothing has taken.

    Args:
        package_ids: The primary keys the calling module's constants carry.
            Given explicitly rather than allocated, so the constants stay the
            authority and the assertions that read them keep saying something.

    Returns:
        The packages, in the order their keys were given, so a caller that wants
        the rows can have them.

    Raises:
        ValueError: When no key is given. An empty call would return `[]` and
            create nothing, which is a fixture that quietly does not run --
            indistinguishable from one that did until a foreign key refuses much
            later.

    """
    if not package_ids:
        message = (
            "packages_keyed() was given no keys, so it would create nothing and return an empty list. "
            "Name the keys the module's constants carry; a module that needs no package should not bind "
            "this fixture at all."
        )
        raise ValueError(message)
    return [
        Package.objects.get_or_create(
            pk=package_id,
            defaults={"canonical_name": f"{PACKAGE_NAME_PREFIX}{package_id}", "resolved_at": FIXED_INSTANT},
        )[0]
        for package_id in package_ids
    ]


def packages_fixture(*package_ids: int) -> Callable[..., list[Package]]:
    """Build the autouse fixture that creates these packages for a whole module.

    Bound at module scope by each caller -- `monitored_packages =
    packages_fixture(A_PACKAGE_ID, ...)` -- so the arrangement is stated once
    instead of in the signature of every case that happens to record a run. The
    fixture returns its packages, so a case that wants the rows requests it by
    name like any other.

    Args:
        package_ids: The primary keys the calling module's constants carry.
            Refused if empty, by `packages_keyed`, at the first case rather than
            at import: a fixture that created nothing would be indistinguishable
            from one that had not been bound.

    Returns:
        A function-scoped, autouse fixture depending on `db`.

    """

    @pytest.fixture(autouse=True)
    def _packages(db: None) -> list[Package]:
        """Create the module's packages inside the case's own transaction.

        Args:
            db: pytest-django's database fixture. Requested rather than assumed:
                it is what opens the transaction these rows are written in and
                rolled back with, and naming it means the module does not depend
                on the order two autouse fixtures happen to run in.

        Returns:
            The packages, in the order their keys were given.

        """
        return packages_keyed(*package_ids)

    return _packages
