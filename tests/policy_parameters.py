"""Substituting the reviewed policy parameter file, for the cases that need another version.

`policies/parameters.py` reads one file shipped inside the wheel and memoizes it,
because `CPM-AD-8` makes one policy version mean one rule set and a file re-read
per package would let an edit split a run across two of them. That is the right
production behaviour and it leaves the suite with two problems this module
solves.

**A case needing two versions cannot have them from the shipped file.** The
`Block If` on `CPM-CURRENCY-S07` limits this component to shipping *one* reviewed
parameter set, so the file records one version. AC 3's claim -- that two runs at
two versions whose recorded thresholds differ reach different verdicts over the
same evidence -- therefore needs a file the case writes, and `tmp_path` is where
an integration case writes one.

**A case needing a version the file does not record cannot use the shipped file
either.** `tests/integration/django_apps/test_rollup.py` is the one module that
genuinely needs two: its recompose cases are about a *newer* run's stamps
replacing an older run's, and one version cannot express that. Its two fixture
versions are recorded into a substituted file rather than added to the shipped
one, because a version in the reviewed file is a reviewed decision and a test
fixture is not. The modules that need only one --
`tests/integration/django_apps/test_policy_run.py` and
`tests/integration/django_apps/test_currency_policy.py` -- name the shipped
version instead, which is also what keeps the shipped file read end to end.

**The memoization is cleared on both sides of the substitution.** Clearing only
on the way in would leave the *substituted* parse cached for every later case in
the session, which is the worse of the two failures: the shipped file would stop
being read at all and nothing would say so.

A helper module, not a collected one. `[tool.pytest.ini_options] python_files`
matches `test_*.py` and `tests.py`, so nothing here is collected, and it sits at
`tests/` for the reason `tests/passes.py`, `tests/clocks.py` and
`tests/model_registry.py` do: a collected test module is not a helper library.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING
from typing import Final

from conda_package_supply_chain_monitor.policies import parameters as parameters_module
from conda_package_supply_chain_monitor.policies.parameters import INACTIVITY_DAYS_KEY
from conda_package_supply_chain_monitor.policies.parameters import PARAMETERS_FILENAME
from conda_package_supply_chain_monitor.policies.parameters import RISK_ORDER_KEY
from conda_package_supply_chain_monitor.policies.parameters import VERSIONS_TABLE
from conda_package_supply_chain_monitor.policies.parameters import forget_recorded_parameters

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Mapping
    from collections.abc import Sequence
    from pathlib import Path

    import pytest

__all__ = ["A_FIXTURE_RISK_ORDER", "parameter_document", "recorded_policy_parameters"]

#: The severity order a substituted file records unless a case says otherwise.
#:
#: **Deliberately not the shipped labels.** `policies/data/policy-parameters.toml`
#: ranks `critical`/`high`/`moderate`/`low`; a fixture using those would pass just
#: as well against a pass that had gone back to reading a constant, which is the
#: same argument `tests/unit/django_apps/test_feedstock_policy.py` makes for
#: choosing a threshold the shipped file does not carry.
#:
#: It exists because `CPM-SECURITY-S04` adopted a pass that refuses a version
#: recording no risk order: every substituted file that a *real policy run* reads
#: has to record one, or every run in the suite would finalize `partial` with
#: every package's vulnerability row missing, and the cases about the rollup and
#: the orchestration would be measuring that instead.
A_FIXTURE_RISK_ORDER: Final[tuple[str, ...]] = ("severe", "moderate", "mild")


def parameter_document(inactivity_days: Mapping[str, int], *, risk_order: Sequence[str] | None = None) -> str:
    """Render a parameter file recording one parameter set per named policy version.

    Written by rendering TOML rather than by calling `tomllib` in reverse,
    because what the cases need is a *document* -- the thing
    `policies/parameters.py` refuses or accepts -- and the refusal cases are all
    about documents that a serializer would never produce.

    Args:
        inactivity_days: The inactivity threshold to record for each version, in
            whole days.
        risk_order: The severity order to record for every version, or `None` to
            record none at all. `None` is the default and not an oversight: the
            key is optional in the file by design -- a version recorded before
            `CPM-SECURITY-S04` cannot carry it and must stay replayable -- so the
            document a case gets by asking for nothing is the document a version
            that predates the parameter really has.

    Returns:
        The file's text.

    """
    ranked = "" if risk_order is None else f"{RISK_ORDER_KEY} = {json.dumps(list(risk_order))}\n"
    return "".join(
        # `json.dumps` for the key rather than surrounding quotes. A TOML basic
        # string escapes the way a JSON string does, and a version containing a
        # quote or a backslash -- which nothing forbids, and which a refusal case
        # may well want to write -- would otherwise produce a document the parser
        # rejects. The failure would then surface from this helper as "not
        # readable as TOML" rather than from the fixture as whatever it was
        # about, which is the least useful place for it to appear.
        #
        # `json.dumps` again for the severity list, and for the same reason plus
        # one: a TOML array of basic strings is spelled exactly as a JSON array
        # of strings, so the one call renders both correctly.
        f"[{VERSIONS_TABLE}.{json.dumps(version)}]\n{INACTIVITY_DAYS_KEY} = {days}\n{ranked}\n"
        for version, days in inactivity_days.items()
    )


@contextmanager
def recorded_policy_parameters(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    inactivity_days: Mapping[str, int],
    *,
    risk_order: Sequence[str] | None = A_FIXTURE_RISK_ORDER,
) -> Iterator[Path]:
    """Point the parameter reader at a file recording exactly these versions.

    `monkeypatch.setattr` is the substitution rather than a bare assignment, on
    the terms `tests/unit/django_apps/test_policy_contribution.py` substitutes the
    rollup model: it restores the original at teardown whatever the case does,
    where an assignment restored in a `finally` still leaks if the case is
    interrupted between the two.

    **`parameters_file` rather than a module constant**, because that is what
    the module offers: the directory is resolved on demand so a missing `data/`
    tree fails a policy run rather than a boot, and a function is what that
    laziness costs and buys.

    Args:
        monkeypatch: pytest's patcher, which is also the teardown for the path.
        directory: Where to write the file. `tmp_path` in an integration case.
        inactivity_days: The threshold to record for each policy version, in
            whole days.
        risk_order: The severity order to record for every version. Defaults to
            `A_FIXTURE_RISK_ORDER` rather than to `None`, which is the opposite
            of `parameter_document`'s default and is deliberate: this helper
            substitutes the file a *real policy run* will read, and
            `VulnerabilityPass` fails every package at a version recording no
            order. A case that wants that refusal passes `None` and says so.

    Yields:
        The substituted file's path, so a case can assert against it or corrupt
        it further.

    """
    path = directory / PARAMETERS_FILENAME
    path.write_text(parameter_document(inactivity_days, risk_order=risk_order), encoding="utf-8")
    monkeypatch.setattr(parameters_module, "parameters_file", lambda: path)
    forget_recorded_parameters()
    try:
        yield path
    finally:
        # Cleared on the way out as well as on the way in: the substituted parse
        # would otherwise stay cached for the rest of the session, keyed by a
        # `tmp_path` no later case can name, and a case that rewrote the same
        # path would silently read the earlier text.
        forget_recorded_parameters()
