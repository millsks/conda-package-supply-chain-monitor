"""The licence pass through a real policy run, against real evidence.

`tests/unit/django_apps/test_licence_policy.py` holds the rules: the five
outcomes, the rule lookup, the detail lines and every declaration. None of those
needs a database. What does need one is everything the rules are *wrapped in* --
the cut-off-bound read of a whole sweep, the row the pass writes, the constraints
the database keeps, the replay that must reproduce it, and the three claims this
story cannot make anywhere else: that the rule set is genuinely versioned, that a
version recording none costs no other domain a row, and that **an `allowed` row
naming no rule is refused by PostgreSQL** rather than merely avoided by the pass.

**The pass is never called directly, except by the query-count case and the two
about `prepare`.** Every other case runs `execute_policy_run`, because what
`CPM-AD-21` promises is a property of the orchestration: the cut-off comes from
the run ledger and the pass runs inside the package's transaction.

**The pass is already registered, and nothing here registers it.**
`policies/apps.py` adopts it during `django.setup()`, which is the arrangement a
deployed process is in. `tests/unit/django_apps/test_policies_app.py` is where
the adoption itself is asserted.

**The reviewed parameter file is substituted for every case here, and the shipped
one is still exercised.** These cases need rule sets they chose -- the shipped
file records none, deliberately and permanently until PRD Open Question 2 is
answered, so a case about what a rule *does* has nowhere else to get one. What
still reads the shipped file end to end is every policy run in
`tests/integration/django_apps/test_currency_policy.py` and
`tests/integration/django_apps/test_policy_run.py`, and the four cases at the
bottom of this module, which are about the shipped file's own entries -- including
the one that holds this story's `Block If`: **no shipped version records any
licence rule.**

**Time comes from stopped clocks, never from the wall.** `tests/clocks.py` owns
the instants and derives the later ones from the earlier, so the ordering the
cut-off cases assert cannot drift.

Every case rolls back: `@pytest.mark.django_db` wraps each in a transaction,
which is what leaves the database as found.
"""

from __future__ import annotations

import json
import tomllib
from contextlib import contextmanager
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
from django.db import IntegrityError
from django.db import transaction
from django.test import override_settings

from conda_package_supply_chain_monitor.collectors.license import CHANNELS_SETTING
from conda_package_supply_chain_monitor.collectors.license import LICENSE_FIELD
from conda_package_supply_chain_monitor.collectors.license import LicenseCollector
from conda_package_supply_chain_monitor.collectors.license import package_locator
from conda_package_supply_chain_monitor.collectors.models import LicenseFinding
from conda_package_supply_chain_monitor.collectors.outcomes import LICENSE_ERROR
from conda_package_supply_chain_monitor.collectors.outcomes import LICENSE_NOT_FOUND
from conda_package_supply_chain_monitor.collectors.outcomes import LICENSE_UNKNOWN
from conda_package_supply_chain_monitor.collectors.outcomes import NORMALIZED
from conda_package_supply_chain_monitor.collectors.spdx import DetectionMethod
from conda_package_supply_chain_monitor.core.clock import FixedClock
from conda_package_supply_chain_monitor.core.models import CollectionRun
from conda_package_supply_chain_monitor.core.models import PackageHealth
from conda_package_supply_chain_monitor.core.models import PolicyRun
from conda_package_supply_chain_monitor.core.policy_run import choose_evidence_cutoff
from conda_package_supply_chain_monitor.core.policy_run import execute_policy_run
from conda_package_supply_chain_monitor.core.runs import RunState
from conda_package_supply_chain_monitor.identity.confidence import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.policies import parameters as parameters_module
from conda_package_supply_chain_monitor.policies.licence import POLICY_NAME
from conda_package_supply_chain_monitor.policies.licence import LicensePass
from conda_package_supply_chain_monitor.policies.licence import current_findings
from conda_package_supply_chain_monitor.policies.models import PackageCurrency
from conda_package_supply_chain_monitor.policies.models import PackageFeedstockPresence
from conda_package_supply_chain_monitor.policies.models import PackageLicense
from conda_package_supply_chain_monitor.policies.models import PackageVulnerability
from conda_package_supply_chain_monitor.policies.outcomes import ALLOWED
from conda_package_supply_chain_monitor.policies.outcomes import FORBIDDEN
from conda_package_supply_chain_monitor.policies.outcomes import LICENSE_STATUS_UNKNOWN
from conda_package_supply_chain_monitor.policies.outcomes import MANUAL_REVIEW
from conda_package_supply_chain_monitor.policies.outcomes import RESTRICTED
from conda_package_supply_chain_monitor.policies.parameters import RULES_KEY
from conda_package_supply_chain_monitor.policies.parameters import VERSIONS_TABLE
from conda_package_supply_chain_monitor.policies.parameters import PolicyParameterError
from conda_package_supply_chain_monitor.policies.parameters import forget_recorded_parameters
from conda_package_supply_chain_monitor.policies.parameters import parameters_at
from conda_package_supply_chain_monitor.policies.parameters import parameters_file
from tests.clocks import FIXED_INSTANT
from tests.clocks import LATER_INSTANT
from tests.clocks import OBSERVATION_GAP
from tests.collectors import FixedLimiter
from tests.collectors import RecordedTransport
from tests.collectors import RecordingResponseCache
from tests.collectors import recorded_payload
from tests.policy_parameters import license_rule_array

if TYPE_CHECKING:
    from collections.abc import Iterator
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

#: The reviewed file this component ships, resolved before any substitution.
THE_SHIPPED_FILE: Final = parameters_file()

#: The fixture policy versions these cases run at.
#:
#: **The first two rule the same expression in opposite directions**, which is
#: the smallest arrangement that can show AC 2: the same evidence at two policy
#: versions reaches two different outcomes with no collection run in between.
#: Two versions ruling *different* expressions would show only that the pass reads
#: the file.
A_POLICY_VERSION: Final[str] = "cpm-fixture-policy-1"
AN_INVERTED_POLICY_VERSION: Final[str] = "cpm-fixture-policy-inverted"

#: A version whose entry records the key as an explicitly empty list -- the
#: shipped state, spelled by a reviewer who meant it.
AN_EMPTY_RULE_SET_VERSION: Final[str] = "cpm-fixture-policy-empty"

#: A version whose entry records no `license_rules` key at all -- the state every
#: version recorded before this pass existed is in.
A_VERSION_WITHOUT_RULES: Final[str] = "cpm-fixture-policy-unruled"

#: A version nothing records at all, for the run-wide refusal.
AN_UNRECORDED_VERSION: Final[str] = "cpm-fixture-policy-nobody-reviewed"

#: The expressions these cases are about, spelled as SPDX spells them.
AN_ALLOWED_LICENCE: Final[str] = "MIT"
A_FORBIDDEN_LICENCE: Final[str] = "GPL-3.0-only"
A_RESTRICTED_LICENCE: Final[str] = "MPL-2.0"
AN_UNRULED_LICENCE: Final[str] = "Zlib"

#: The rule set `A_POLICY_VERSION` records: one rule per disposition, so each
#: matrix row has one to reach.
THE_FIXTURE_RULES: Final[tuple[tuple[str, str], ...]] = (
    (AN_ALLOWED_LICENCE, ALLOWED),
    (A_FORBIDDEN_LICENCE, FORBIDDEN),
    (A_RESTRICTED_LICENCE, RESTRICTED),
)

#: What `AN_INVERTED_POLICY_VERSION` records instead: the same expression, the
#: other way round.
THE_INVERTED_RULES: Final[tuple[tuple[str, str], ...]] = ((AN_ALLOWED_LICENCE, FORBIDDEN),)

#: The inactivity threshold and severity order every fixture version records.
#: This module is about neither; they are here because the other two adopted
#: passes read them and a run has to complete.
A_THRESHOLD_IN_DAYS: Final[int] = 90
A_FIXTURE_RISK_ORDER: Final[tuple[str, ...]] = ("severe", "moderate", "mild")

#: The collector name the fixture collection runs carry. Prefixed so it cannot be
#: confused with a real collector's.
A_COLLECTOR: Final[str] = "cpm-fixture-collector"

#: An instant after the run's cut-off, for the cases about evidence the cut-off
#: excludes. Derived from `OBSERVATION_GAP` rather than written out, so the two
#: instants cannot drift into an ordering nobody intended.
AFTER_THE_CUTOFF: Final = FIXED_INSTANT + OBSERVATION_GAP

#: An instant *before* the cut-off, for the case about two sweeps that are both
#: eligible and only one of which is current.
BEFORE_THE_CUTOFF: Final = FIXED_INSTANT - OBSERVATION_GAP

#: The version the shipped file records before this pass existed, named rather
#: than searched for, on exactly the terms
#: `tests/integration/django_apps/test_vulnerability_policy.py` names it: what
#: `CPM-FR-22` promises is about the version runs were actually recorded at.
THE_EARLIEST_SHIPPED_VERSION: Final[str] = "2026.09"

#: The newest version the shipped file records, and the one this story added. It
#: is the entry that carries the rule schema, recorded as an explicitly empty
#: list.
THE_NEWEST_SHIPPED_VERSION: Final[str] = "2026.09.2"

#: What one `evaluate` costs: two evidence reads -- the newest sweep's instant,
#: then that sweep's rows -- plus the one insert of the derived row. The rule
#: lookup costs no query at all, and that is part of what this pins.
QUERIES_PER_PACKAGE: Final[int] = 3

#: How many rows two runs over one package leave behind, and how many packages
#: the multi-package case is over. Named separately because the two cases mean
#: different things by it.
REPLAYED_RUNS: Final[int] = 2
PACKAGES_IN_THE_INVENTORY: Final[int] = 2

#: How many channels the disagreement case reads, and how many the sweep case
#: writes.
CHANNELS_IN_A_SWEEP: Final[int] = 3

#: A state nothing recognises, for the one evidence fault this pass refuses.
#: `choices` is a form rule Django does not enforce on `save()`, so the row is
#: reachable.
A_STATE_FROM_NOWHERE: Final[str] = "probably_fine"

#: What the collector-driven case needs: a channel to monitor, the name it asks
#: about, and the licence that channel states.
A_NAME: Final[str] = "numpy"
A_CHANNEL: Final[str] = "conda-forge"


@pytest.fixture(autouse=True)
def _recorded_rule_sets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Record this module's fixture policy versions, so a run at one can complete.

    Autouse because every case here needs a rule set it chose -- the shipped file
    records none by design, so there is nothing else to draw one from. The
    substitution and its teardown are `tests/policy_parameters.py`'s, which argues
    why the file is substituted rather than the reviewed one extended; this module
    renders its own document because it needs four versions with four different
    answers, which that helper's one-value-for-every-version shape cannot express.

    Args:
        monkeypatch: pytest's patcher, which restores the shipped path.
        tmp_path: Where the substituted file is written.

    Yields:
        The substituted file's path.

    """
    path = tmp_path / THE_SHIPPED_FILE.name
    path.write_text(
        _document(
            {
                A_POLICY_VERSION: THE_FIXTURE_RULES,
                AN_INVERTED_POLICY_VERSION: THE_INVERTED_RULES,
                AN_EMPTY_RULE_SET_VERSION: (),
                A_VERSION_WITHOUT_RULES: None,
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(parameters_module, "parameters_file", lambda: path)
    forget_recorded_parameters()
    try:
        yield path
    finally:
        forget_recorded_parameters()


def _document(rule_sets: dict[str, Sequence[tuple[str, str]] | None]) -> str:
    """Render a parameter file recording a different rule set per version.

    Args:
        rule_sets: The rules to record for each version, or `None` for a version
            that records no `license_rules` key at all. `()` records the key with
            an empty list, which is the shipped state spelled by a reviewer who
            meant it.

    Returns:
        The file's text.

    """
    entries = []
    for version, rules in rule_sets.items():
        ruled = "" if rules is None else f"{RULES_KEY} = {license_rule_array(rules)}\n"
        entries.append(
            f"[{VERSIONS_TABLE}.{json.dumps(version)}]\n"
            f"feedstock_inactivity_days = {A_THRESHOLD_IN_DAYS}\n"
            f"vulnerability_risk_order = {json.dumps(list(A_FIXTURE_RISK_ORDER))}\n"
            f"{ruled}\n",
        )
    return "".join(entries)


@contextmanager
def the_shipped_parameters(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the reader back at the file this component ships, for the length of a block.

    This module substitutes the parameter file for every case, because its cases
    need rule sets they chose. The cases at the bottom are about the *shipped*
    file's own entries instead -- what it records and, more to the point, what it
    deliberately does not -- and they need the substitution lifted rather than
    reproduced, because a fixture reproducing an entry would only ever agree with
    itself.

    Args:
        monkeypatch: pytest's patcher.

    Yields:
        Nothing; the restored path is the effect. The memoized parse is cleared on
        both sides, so neither file's parse leaks into the other's cases.

    """
    with monkeypatch.context() as shipped:
        shipped.setattr(parameters_module, "parameters_file", lambda: THE_SHIPPED_FILE)
        forget_recorded_parameters()
        try:
            yield
        finally:
            forget_recorded_parameters()


def an_ended_collection_run(finished_at: datetime = FIXED_INSTANT) -> CollectionRun:
    """Record a collection run that has ended, which is what supplies the cut-off.

    Written directly rather than through `core/ledger.py`'s recorder, because what
    these cases need is a row with a *chosen* `finished_at`: the recorder reads
    its own clock.

    Args:
        finished_at: When the run ended, and therefore the cut-off every pass in
            the policy run reads evidence as of.

    Returns:
        The saved row.

    """
    return CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=FIXED_INSTANT,
        finished_at=finished_at,
        status=RunState.SUCCEEDED,
    )


def a_package(name: str = A_NAME, *, confidence: str = IdentityConfidence.VERIFIED) -> Package:
    """Create one package with a resolved identity.

    Args:
        name: Its canonical name, which is unique.
        confidence: How certain its identity is.

    Returns:
        The saved `Package`. `resolved_at` comes from `tests.clocks.FIXED_INSTANT`
        rather than from the wall clock, exactly as `CPM-AD-26` requires of every
        writer.

    """
    return Package.objects.create(canonical_name=name, resolved_at=FIXED_INSTANT, confidence=confidence)


def a_finding(
    package: Package,
    *,
    state: str = NORMALIZED,
    expression: str = AN_ALLOWED_LICENCE,
    channel: str = A_CHANNEL,
    observed_at: datetime = FIXED_INSTANT,
) -> LicenseFinding:
    """Record one licence finding.

    Written directly rather than through the collector: what most cases here are
    about is the pass reading evidence, and driving a collection would make each
    of them depend on a transport none of them is about. One case *does* drive the
    collector, and it is the one that says these rows are the rows a real
    collector writes.

    Args:
        package: The package observed.
        state: What the observation concluded.
        expression: The normalized SPDX expression, on a determinate row.
        channel: The channel this row is about. Required of every row by that
            table's own constraint.
        observed_at: The instant of this observation.

    Returns:
        The saved row.

    """
    determinate = state == NORMALIZED
    return LicenseFinding.objects.create(
        package=package,
        observed_at=observed_at,
        state=state,
        source=package_locator(channel, package.canonical_name),
        channel=channel,
        raw_license=expression,
        normalized_license=expression if determinate else "",
        detection_method=DetectionMethod.SPDX_IDENTIFIER.value if determinate else "",
        detail="" if determinate else "this run established no licence",
    )


def a_policy_run(*, version: str = A_POLICY_VERSION, at: datetime = LATER_INSTANT) -> None:
    """Execute one policy run over the whole inventory.

    Args:
        version: The policy version the run declares, and therefore the rule set
            it applies.
        at: The instant the run's clock answers, which becomes every rollup row's
            `computed_at`.

    """
    execute_policy_run(policy_version=version, clock=FixedClock(instant=at))


def a_policy_run_row(*, version: str = A_POLICY_VERSION) -> PolicyRun:
    """Record a policy run directly, for the cases that do not execute one.

    Args:
        version: The policy version the row declares.

    Returns:
        The saved row.

    """
    return PolicyRun.objects.create(
        policy_version=version,
        evidence_cutoff=FIXED_INSTANT,
        started_at=FIXED_INSTANT,
        finished_at=LATER_INSTANT,
        status=RunState.SUCCEEDED,
    )


def the_finding(package: Package) -> PackageLicense:
    """Return the one licence row the latest run wrote for a package.

    Args:
        package: The package whose finding is wanted.

    Returns:
        Its `PackageLicense` row, newest run first. `get()` on the package alone
        would raise once a case has run twice, and the replay case needs both
        rows.

    """
    return PackageLicense.objects.filter(package=package).order_by("-policy_run_id")[0]


def a_hand_built_row(**overrides: Any) -> PackageLicense:
    """Write one licence row directly, for the cases about what the database refuses.

    Built by `create()` rather than through the pass, for the reason each
    constraint exists: the pass cannot produce a violating row, and a case that
    only drove the pass would pass against a constraint weakened to `1 = 1`. The
    `allowed`-with-no-rule case is the one this whole helper is here for.

    Args:
        **overrides: The columns to differ from a well-formed row in.

    Returns:
        The saved row.

    """
    package = a_package()
    row: dict[str, Any] = {
        "package": package,
        "policy_run": a_policy_run_row(),
        "license_outcome": LICENSE_STATUS_UNKNOWN,
        "matched_rule": "",
        "policy_version": A_POLICY_VERSION,
        "evidence_cutoff": FIXED_INSTANT,
        "license_finding": None,
        "detail": "",
    }
    row.update(overrides)
    return PackageLicense.objects.create(**row)


# ---------------------------------------------------------------------------
# The shipped state: nothing is allowed, and nothing fails.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_version_recording_no_rule_set_routes_every_licensed_package_to_manual_review() -> None:
    """The matrix's first row, end to end, and this story's whole shipped behaviour.

    Three packages, three different licences, a version that records no rule set:
    every one of them reads `manual_review`, names the finding that established
    its licence, names no rule, and says on the row that the version records
    none. Nothing reads `allowed`, which is asserted rather than implied because
    it is the one value this story exists to keep out of reach.
    """
    an_ended_collection_run()
    packages = [a_package(f"package-{index}") for index in range(CHANNELS_IN_A_SWEEP)]
    for package, expression in zip(
        packages,
        (AN_ALLOWED_LICENCE, A_FORBIDDEN_LICENCE, AN_UNRULED_LICENCE),
        strict=True,
    ):
        a_finding(package, expression=expression)

    a_policy_run(version=A_VERSION_WITHOUT_RULES)

    rows = [the_finding(package) for package in packages]
    assert [row.license_outcome for row in rows] == [MANUAL_REVIEW] * CHANNELS_IN_A_SWEEP
    assert [row.matched_rule for row in rows] == [""] * CHANNELS_IN_A_SWEEP
    assert all(row.license_finding_id is not None for row in rows)
    assert all(RULES_KEY in row.detail for row in rows)
    assert not PackageLicense.objects.filter(license_outcome=ALLOWED).exists()


@pytest.mark.django_db
def test_a_version_recording_an_empty_rule_set_says_the_same_thing() -> None:
    """The other spelling of "no policy has been decided", and it is not a second state.

    A reviewer who writes `license_rules = []` has said what a version predating
    the key could only imply, and the pass must not treat the two differently:
    the outcome, the rule and the line are the same, so nothing downstream has to
    know which spelling produced a row.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package)

    a_policy_run(version=AN_EMPTY_RULE_SET_VERSION)

    row = the_finding(package)
    assert row.license_outcome == MANUAL_REVIEW
    assert row.matched_rule == ""
    assert RULES_KEY in row.detail


@pytest.mark.django_db
def test_a_version_recording_no_rule_set_still_writes_all_four_domains_rows() -> None:
    """The Never list's central rule, and the regression it exists to prevent.

    `CPM-SECURITY-S04`'s pass refused per package for a version recording no
    severity order, on the argument that only its own domain's rows would be
    lost. `CPM-AD-23`'s atomic unit is one *package*, not one pass:
    `core/policy_run.py` wraps every pass for one package in a single
    `transaction.atomic()`, so a refusal here takes the currency, feedstock and
    vulnerability rows with it, `compose_rollup` skips the package, and -- the
    condition holding for every package -- the run finalizes `failed` having
    written nothing.

    What that would break is `CPM-FR-22` for every run recorded before this pass
    existed, to protect a licence replay that does not exist. So every domain
    writes its row, the licence row says why it carries no rule, and the run
    succeeds. This case fails the moment `_rules` starts raising.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package)

    a_policy_run(version=A_VERSION_WITHOUT_RULES)

    assert PackageLicense.objects.filter(package=package).count() == 1
    assert PackageCurrency.objects.filter(package=package).count() == 1
    assert PackageFeedstockPresence.objects.filter(package=package).count() == 1
    assert PackageVulnerability.objects.filter(package=package).count() == 1
    assert PackageHealth.objects.filter(package=package).count() == 1
    assert PolicyRun.objects.get(policy_version=A_VERSION_WITHOUT_RULES).status == RunState.SUCCEEDED


# ---------------------------------------------------------------------------
# What a rule does, and what only a rule can do.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (AN_ALLOWED_LICENCE, ALLOWED),
        (A_FORBIDDEN_LICENCE, FORBIDDEN),
        (A_RESTRICTED_LICENCE, RESTRICTED),
    ],
    ids=[ALLOWED, FORBIDDEN, RESTRICTED],
)
def test_a_rule_naming_the_licence_produces_its_disposition_and_names_itself(
    expression: str,
    expected: str,
) -> None:
    """The matrix's three rule rows, end to end, each naming the rule that produced it.

    The stored rule is the *reviewer's* spelling, which is what makes the row an
    audit trail a person can follow back to a line in a pull request rather than
    a restatement of what the evidence already said.
    """
    an_ended_collection_run()
    package = a_package()
    finding = a_finding(package, expression=expression)

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == expected
    assert row.matched_rule == expression
    assert row.license_finding_id == finding.pk
    assert row.detail == ""


@pytest.mark.django_db
def test_the_stored_rule_is_the_files_spelling_and_not_the_evidence_rows() -> None:
    """The audit trail is a line in a pull request, proved end to end rather than at the matcher.

    Every other case in this module records a rule whose expression is
    byte-identical to the evidence's, so a `create()` storing
    `normalized_license` instead of `rule.expression` satisfies all of them. Here
    the channel states `mit` and the file records `MIT`: the match still folds
    both sides, and what the row stores is the string a reviewer can search the
    file for.

    A stored evidence spelling would be a report telling an operator to look for a
    rule the file does not contain.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=AN_ALLOWED_LICENCE.lower())

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == ALLOWED
    assert row.matched_rule == AN_ALLOWED_LICENCE
    assert row.matched_rule != AN_ALLOWED_LICENCE.lower()


@pytest.mark.django_db
def test_the_same_evidence_reads_allowed_or_manual_review_by_whether_a_rule_names_it() -> None:
    """The story's central property, where an implementation that defaulted could fail it.

    Two packages, **identical** licence evidence, one policy run each: one at a
    version whose rule set names that licence and permits it, one at a version
    that records no rule at all. The two rows must differ, and they must differ in
    exactly one direction -- the ruled one is `allowed` and names the rule, the
    unruled one is `manual_review` and names none.

    Both halves are load-bearing and neither is enough alone. A pass that had
    started defaulting to `allowed` passes the second assertion of the shipped-
    state case above only by accident of which value it defaults to; a pass that
    could never produce `allowed` at all passes every "this row is not allowed"
    assertion in this module. This is the pair that no single broken
    implementation survives, and the evidence is byte-identical on both sides so
    the *only* thing that can explain the difference is the rule set.
    """
    an_ended_collection_run()
    ruled = a_package("ruled")
    unruled = a_package("unruled")
    a_finding(ruled, expression=AN_ALLOWED_LICENCE)
    a_finding(unruled, expression=AN_ALLOWED_LICENCE)
    cutoff = choose_evidence_cutoff()
    with_rules = a_policy_run_row(version=A_POLICY_VERSION)
    without_rules = a_policy_run_row(version=A_VERSION_WITHOUT_RULES)

    for run, package in ((with_rules, ruled), (without_rules, unruled)):
        policy_pass = LicensePass()
        policy_pass.prepare(policy_run=run, evidence_cutoff=cutoff)
        policy_pass.evaluate(package, policy_run=run, evidence_cutoff=cutoff)

    assert the_finding(ruled).license_outcome == ALLOWED
    assert the_finding(ruled).matched_rule == AN_ALLOWED_LICENCE
    assert the_finding(unruled).license_outcome == MANUAL_REVIEW
    assert the_finding(unruled).matched_rule == ""


@pytest.mark.django_db
def test_a_rule_set_that_does_not_name_this_licence_is_manual_review_and_says_which_case() -> None:
    """The matrix's fifth row, distinct from the no-rules-recorded case.

    A recorded policy exists and does not cover this licence. The row says the
    version records rules and how many, which is what tells a reader that the work
    is to extend a policy rather than to write one -- and the two lines are
    required to differ, because a reader who sees only one has to know which case
    it is.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=AN_UNRULED_LICENCE)

    a_policy_run()
    a_policy_run(version=A_VERSION_WITHOUT_RULES, at=LATER_INSTANT + OBSERVATION_GAP)

    rows = list(PackageLicense.objects.filter(package=package).order_by("policy_run_id"))
    assert [row.license_outcome for row in rows] == [MANUAL_REVIEW, MANUAL_REVIEW]
    assert str(len(THE_FIXTURE_RULES)) in rows[0].detail
    assert RULES_KEY in rows[1].detail
    assert rows[0].detail != rows[1].detail


@pytest.mark.django_db
def test_a_rule_naming_a_licence_no_evidence_uses_has_no_effect_and_no_failure() -> None:
    """The matrix's "the rule set is broader than the inventory".

    The fixture rule set names three licences; this package carries a fourth. The
    verdict is `manual_review`, nothing failed, and the run succeeded -- a
    reviewer adding a rule for a licence they expect to see one day has changed no
    verdict at all.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=AN_UNRULED_LICENCE)

    a_policy_run()

    assert the_finding(package).license_outcome == MANUAL_REVIEW
    assert PolicyRun.objects.get(policy_version=A_POLICY_VERSION).status == RunState.SUCCEEDED


# ---------------------------------------------------------------------------
# Where `unknown` comes from, and why it is not `manual_review`.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_package_with_no_licence_evidence_at_all_is_unknown_and_still_gets_a_row() -> None:
    """The matrix's "no licence evidence at all": `unknown`, never clean, never absent.

    Every column says the same thing in its own way: the outcome is `unknown` and
    not `manual_review`, which would claim the licence is known; no rule is named;
    and the evidence reference points at nothing. A package with **no row at all**
    would read as never evaluated, which is the outcome `CPM-SM-2` is written
    about.
    """
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == LICENSE_STATUS_UNKNOWN
    assert row.license_outcome not in {MANUAL_REVIEW, ALLOWED}
    assert row.matched_rule == ""
    assert row.license_finding_id is None
    assert row.detail == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("state", "says"),
    [
        (LICENSE_ERROR, "could not be read"),
        (LICENSE_NOT_FOUND, "do not serve this package"),
        (LICENSE_UNKNOWN, "whether the channel stated none"),
    ],
    ids=["unread-channel", "unserved-package", "unrecognised"],
)
def test_a_package_whose_evidence_established_no_licence_is_unknown_and_the_row_says_which(
    state: str,
    says: str,
) -> None:
    """The matrix's "unknown licence row" and "only an error or not_found row".

    At the package level all three mean this run established no licence, which is
    what `unknown` means -- so the outcome is the same for all of them and for a
    package nobody looked at. What must not be lost is *which*, and the row
    carries it twice: the reference points at the finding that says so, and the
    line says it in words for a reader who never opens the reference.

    None of them is `manual_review`, which is the distinction the whole vocabulary
    turns on: nothing here established a licence for a rule to be missing about.
    """
    an_ended_collection_run()
    package = a_package()
    finding = a_finding(package, state=state)

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == LICENSE_STATUS_UNKNOWN
    assert row.license_outcome != MANUAL_REVIEW
    assert row.license_finding_id == finding.pk
    assert says in row.detail


@pytest.mark.django_db
def test_an_unmapped_package_with_no_evidence_still_gets_a_row() -> None:
    """Every package gets a row, whatever its identity confidence.

    `CPM-AD-4`'s gate is `core/rollup.py`'s and this pass never applies one, so
    what an `unmapped` package changes here is nothing at all -- the row records
    what the evidence supported, which is `unknown`. A pass that had skipped such
    a package would leave it looking never-evaluated in its own domain's table.
    """
    an_ended_collection_run()
    package = a_package(confidence=IdentityConfidence.UNMAPPED)

    a_policy_run()

    assert the_finding(package).license_outcome == LICENSE_STATUS_UNKNOWN


@pytest.mark.django_db
def test_an_unreadable_evidence_state_fails_only_that_package() -> None:
    """The one evidence fault this pass refuses, and what the refusal costs.

    An outcome derived from a value nothing recognises is the one thing that must
    not reach the column a compliance reviewer reads first, so this raises -- and
    `CPM-AD-23` puts one *package* in a transaction, so the cost is that package's
    four derived rows and its rollup row, while every other package's commit and
    the run finalizes `partial` rather than `failed`.

    That is the trade this pass makes deliberately in one place and refuses to
    make in the other: a version-wide condition is recorded on the row, a single
    corrupt evidence row fails a single package.
    """
    an_ended_collection_run()
    broken = a_package("broken")
    healthy = a_package("healthy")
    LicenseFinding.objects.create(
        package=broken,
        observed_at=FIXED_INSTANT,
        state=A_STATE_FROM_NOWHERE,
        source=package_locator(A_CHANNEL, broken.canonical_name),
        channel=A_CHANNEL,
        detail="a state this product does not recognise",
    )
    a_finding(healthy)

    a_policy_run()

    assert PackageLicense.objects.filter(package=broken).count() == 0
    assert PackageHealth.objects.filter(package=broken).count() == 0
    assert the_finding(healthy).license_outcome == ALLOWED
    assert PolicyRun.objects.get(policy_version=A_POLICY_VERSION).status == RunState.PARTIAL


# ---------------------------------------------------------------------------
# Several channels.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_two_channels_stating_different_licences_reach_the_least_permissive_outcome() -> None:
    """The matrix's "several channels disagree": disagreement never resolves upward.

    One channel states a licence the rules allow and the other states one they
    forbid, and the allowing channel is written **first** so an implementation
    taking the first row, or short-circuiting on a permission, reads `allowed`
    and fails here. One row per package, the outcome is the worst rank, the
    reference names the forbidding channel, and the row says the channels
    disagreed -- because a single verdict otherwise shows no sign that there were
    several.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=AN_ALLOWED_LICENCE, channel=A_CHANNEL)
    refused = a_finding(package, expression=A_FORBIDDEN_LICENCE, channel="bioconda")

    a_policy_run()

    row = the_finding(package)
    assert PackageLicense.objects.filter(package=package).count() == 1
    assert row.license_outcome == FORBIDDEN
    assert row.license_outcome != ALLOWED
    assert row.license_finding_id == refused.pk
    assert row.matched_rule == A_FORBIDDEN_LICENCE
    assert A_FORBIDDEN_LICENCE in row.detail
    assert AN_ALLOWED_LICENCE in row.detail


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (A_POLICY_VERSION, ALLOWED),
        (A_VERSION_WITHOUT_RULES, MANUAL_REVIEW),
    ],
    ids=["allowed", "manual-review"],
)
def test_a_channel_that_does_not_serve_the_package_does_not_erase_the_verdict(version: str, expected: str) -> None:
    """**The ordinary shape of a two-channel deployment, end to end.**

    `collectors/license.py` writes one row per monitored channel and never fewer,
    so a package conda-forge serves and bioconda does not gets a determinate row
    *and* a `not_found` row in one sweep. Counting the absence as a verdict puts
    `unknown` into the reduction, and `unknown` outranks both of these: every
    determinate answer this pass can give would collapse the moment a second
    channel was monitored, with `manual_review` masked and `allowed` unreachable
    outside a single-channel deployment.

    Both versions are here because the two failures look different and are the
    same defect: at a version with rules the row loses a `allowed` it earned, and
    at a version with none it loses the `manual_review` that is this component's
    entire shipped output.
    """
    an_ended_collection_run()
    package = a_package()
    served = a_finding(package, expression=AN_ALLOWED_LICENCE, channel=A_CHANNEL)
    a_finding(package, state=LICENSE_NOT_FOUND, channel="bioconda")

    a_policy_run(version=version)

    row = the_finding(package)
    assert row.license_outcome == expected
    assert row.license_finding_id == served.pk


@pytest.mark.django_db
def test_an_absent_channel_beside_a_forbidden_licence_still_reads_forbidden() -> None:
    """The safety half of the same rule, which is why dropping the absence is safe.

    Excluding a `not_found` channel only ever removes an `unknown` vote, so it
    cannot make an outcome milder than `unknown` -- a channel stating a licence
    the rules forbid still decides the row, and this is the case that says the
    exclusion was not bought at the cost of the property the story turns on.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, state=LICENSE_NOT_FOUND, channel="bioconda")
    refused = a_finding(package, expression=A_FORBIDDEN_LICENCE, channel=A_CHANNEL)

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == FORBIDDEN
    assert row.license_finding_id == refused.pk


@pytest.mark.django_db
def test_a_conjunction_a_rule_forbids_one_operand_of_is_forbidden_and_says_so() -> None:
    """`AND` binds every operand at once, and the database holds the row to it.

    `collectors/spdx.py` normalizes `MIT AND GPL-3.0-only` to exactly this string,
    so the expression is reachable evidence rather than a hypothetical. No rule
    names it whole; a rule forbids one of its operands; and left undecomposed the
    row would read `manual_review`, which ranks *below* `forbidden` -- a deny rule
    a reviewer wrote, weakened by a conjunction.

    Driven through `evaluate` rather than through the matcher, because the rule
    the row names has to be the operand's: `A_RULED_OUTCOME_NAMES_THE_RULE_THAT_
    PRODUCED_IT` refuses a `forbidden` row naming no rule, so a verdict reached by
    decomposition whose rule lookup did not decompose is an `IntegrityError` here
    rather than a wrong value.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=f"{AN_ALLOWED_LICENCE} AND {A_FORBIDDEN_LICENCE}")

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == FORBIDDEN
    assert row.matched_rule == A_FORBIDDEN_LICENCE
    assert A_FORBIDDEN_LICENCE in row.detail
    assert "can ever permit a compound" in row.detail


@pytest.mark.django_db
def test_a_conjunction_a_rule_allows_one_operand_of_is_not_allowed() -> None:
    """The direction decomposition must never run, held where it would be written.

    A rule permitting `MIT` says nothing about the obligations `GPL-3.0-only`
    adds, so the conjunction is not permitted by it -- and the fixture rule set
    permits `MIT` outright, so a symmetric decomposition writes `allowed` here.
    That is the one value this story exists to keep out of reach.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=f"{AN_ALLOWED_LICENCE} AND {AN_UNRULED_LICENCE}")

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == MANUAL_REVIEW
    assert row.license_outcome != ALLOWED
    assert row.matched_rule == ""


@pytest.mark.django_db
def test_the_whole_newest_sweep_is_read_and_not_only_its_first_row() -> None:
    """The read that makes a reduction a reduction.

    `license_findings` holds one row per monitored channel and every row of one
    sweep carries that run's single instant. A read returning "the newest row"
    would reduce three channels to whichever the database happened to return,
    which on this table is the difference between seeing a disagreement and not
    knowing there was one -- and it would do it silently, because the answer would
    still look like a verdict.
    """
    an_ended_collection_run()
    package = a_package()
    for channel in ("conda-forge", "bioconda", "nvidia"):
        a_finding(package, channel=channel)
    a_finding(package, channel="later", observed_at=AFTER_THE_CUTOFF)

    read = current_findings(package_id=package.pk, cutoff=choose_evidence_cutoff())

    assert len(read) == CHANNELS_IN_A_SWEEP
    assert {finding.observed_at for finding in read} == {FIXED_INSTANT}
    assert [finding.pk for finding in read] == sorted(finding.pk for finding in read)


# ---------------------------------------------------------------------------
# The cut-off, the versioning, the replay and the cost.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evidence_written_after_the_cutoff_is_not_read() -> None:
    """`CPM-AD-21`: a pass reads evidence as of the run's stated instant and no later.

    The later sweep would make this package `forbidden`; the cut-off's evidence
    says the channel stated a licence the rules allow. Without this the answer
    would change every time the collector ran, which is the difference between a
    replay that reproduces and one that does not.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=AN_ALLOWED_LICENCE)
    a_finding(package, expression=A_FORBIDDEN_LICENCE, observed_at=AFTER_THE_CUTOFF)

    a_policy_run()

    assert the_finding(package).license_outcome == ALLOWED


@pytest.mark.django_db
def test_evidence_from_a_collection_run_that_is_still_running_is_not_read() -> None:
    """`CPM-AD-21`'s second demand, which the first does not satisfy on its own.

    A run still in flight is free to write evidence stamped inside the newest
    ending, so `choose_evidence_cutoff` bounds the cut-off to before the earliest
    unfinished run began. What that means here is that the licence this in-flight
    sweep has already written is not read -- and it must not be, because the sweep
    may write more channels' rows, and every replay would then read a different
    set.
    """
    an_ended_collection_run()
    CollectionRun.objects.create(
        collector=A_COLLECTOR,
        started_at=AFTER_THE_CUTOFF,
        finished_at=None,
        status=RunState.RUNNING,
    )
    package = a_package()
    a_finding(package, observed_at=AFTER_THE_CUTOFF)

    a_policy_run()

    row = the_finding(package)
    assert row.evidence_cutoff == FIXED_INSTANT
    assert row.license_outcome == LICENSE_STATUS_UNKNOWN


@pytest.mark.django_db
def test_the_newest_sweep_at_the_cutoff_is_the_one_read() -> None:
    """Two sweeps, both eligible, and the *newer* one answers.

    The cut-off cases above pin the boundary from one side only: evidence after it
    is not read. Nothing distinguished "the newest sweep at or before the cut-off"
    from "the oldest" or "whichever row sorted first", because no case had two
    sweeps both inside it -- so inverting `READ_ORDERING`, or taking the last row
    rather than the first, would have kept superseded evidence for ever while
    every case passed.
    """
    an_ended_collection_run(finished_at=AFTER_THE_CUTOFF)
    package = a_package()
    stale = a_finding(package, expression=A_FORBIDDEN_LICENCE, observed_at=BEFORE_THE_CUTOFF)
    current = a_finding(package, expression=AN_ALLOWED_LICENCE, observed_at=FIXED_INSTANT)

    a_policy_run()

    row = the_finding(package)
    assert row.license_outcome == ALLOWED
    assert row.license_finding_id == current.pk
    assert row.license_finding_id != stale.pk


@pytest.mark.django_db
def test_two_runs_at_two_versions_over_one_cutoff_reach_two_outcomes_without_recollection() -> None:
    """AC 2: the policy content changes, the evidence does not, and the results change.

    One package, one licence, one cut-off, two policy versions whose recorded rule
    sets name the same expression in opposite directions. No constant could
    produce two answers here, and no amount of reading the file at import could
    either -- which is what makes this the case that says the rules are versioned
    rather than merely external.

    **No collection run happens in between, and that is asserted rather than
    assumed**, because "without recollection" is half of what AC 2 promises: the
    ledger holds exactly the run it started with. Both rows survive, each
    recording its own version, which is what a replay is compared against.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=AN_ALLOWED_LICENCE)
    collections_before = CollectionRun.objects.count()

    a_policy_run(version=A_POLICY_VERSION)
    a_policy_run(version=AN_INVERTED_POLICY_VERSION, at=LATER_INSTANT + OBSERVATION_GAP)

    rows = list(PackageLicense.objects.filter(package=package).order_by("policy_run_id"))
    assert [row.license_outcome for row in rows] == [ALLOWED, FORBIDDEN]
    assert [row.policy_version for row in rows] == [A_POLICY_VERSION, AN_INVERTED_POLICY_VERSION]
    assert [row.matched_rule for row in rows] == [AN_ALLOWED_LICENCE, AN_ALLOWED_LICENCE]
    assert CollectionRun.objects.count() == collections_before


@pytest.mark.django_db
def test_replaying_a_version_at_a_cutoff_reproduces_the_row_and_leaves_the_first_alone() -> None:
    """`CPM-FR-22`: the same version over the same cut-off produces the same values.

    **The second run is a real replay, not a repetition.** A collection run
    finishes between the two, which moves the boundary the second run would
    otherwise choose, and the second run is handed the first's cut-off explicitly
    -- the assertion in the middle is what says the two are actually different
    instants. New evidence lands after the original cut-off too, and it must not
    be read.

    Every column that is not the key is compared, by iterating the table's own
    fields rather than by naming seven of them: a column added later would
    otherwise drift out of the comparison silently, which is the one thing a
    replay case must not let happen.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package)

    first = execute_policy_run(policy_version=A_POLICY_VERSION, clock=FixedClock(instant=LATER_INSTANT))

    an_ended_collection_run(finished_at=AFTER_THE_CUTOFF)
    a_finding(package, expression=A_FORBIDDEN_LICENCE, observed_at=AFTER_THE_CUTOFF)

    assert choose_evidence_cutoff() != first.evidence_cutoff, (
        "the cut-off must have moved between the two runs, or this case is a repetition rather than a replay"
    )

    execute_policy_run(
        policy_version=A_POLICY_VERSION,
        clock=FixedClock(instant=LATER_INSTANT + OBSERVATION_GAP),
        evidence_cutoff=first.evidence_cutoff,
    )

    rows = list(PackageLicense.objects.filter(package=package).order_by("policy_run_id"))
    compared = [
        field.name
        for field in PackageLicense._meta.concrete_fields  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
        if field.name not in {"id", "policy_run"}
    ]

    assert len(rows) == REPLAYED_RUNS
    assert rows[0].policy_run_id != rows[1].policy_run_id
    for column in compared:
        assert getattr(rows[0], column) == getattr(rows[1], column), column


@pytest.mark.django_db
def test_a_run_at_a_version_nothing_records_is_refused_before_any_package() -> None:
    """The `CPM-CURRENCY-S07` rule, re-asserted for this pass's own `prepare`.

    A version the reviewed file does not record is a run-wide fault -- there is no
    parameter set for any package -- so it is established once, before the loop,
    and the refusal names the file rather than arriving ten thousand times. It is
    the one run-wide condition this pass does refuse, and the contrast with a
    version recording no *rule set* is the whole of the Never list: one is a
    version nobody reviewed, the other is a version review deliberately left
    empty.
    """
    run = a_policy_run_row(version=AN_UNRECORDED_VERSION)

    with pytest.raises(PolicyParameterError, match=AN_UNRECORDED_VERSION):
        LicensePass().prepare(policy_run=run, evidence_cutoff=FIXED_INSTANT)


@pytest.mark.django_db
@pytest.mark.parametrize("packages", [1, 2, 4], ids=str)
def test_the_query_count_per_package_does_not_grow_with_the_inventory(
    django_assert_num_queries: Any,
    packages: int,
) -> None:
    """Three queries per package, and the rule lookup costs none of them.

    The count is *linear* in the inventory and the per-package constant is three
    -- two reads, because the newest sweep's instant and that sweep's rows are two
    questions, plus one insert. A read that started issuing a query per channel,
    or a rule lookup that had become a database table rather than a reviewed file,
    would change the constant and show up here at three cardinalities rather than
    at none.

    Only the pass phase is measured. `execute_policy_run` also opens a ledger row,
    reads the package set and composes the rollup, and those are the
    orchestration's queries rather than this pass's.
    """
    an_ended_collection_run()
    inventory = [a_package(f"package-{index}") for index in range(packages)]
    for package in inventory:
        # Evidence on every package, because the count is what a package with
        # something to read costs. A package with no rows at all costs two rather
        # than three -- the read stops at the instant query when there is no sweep
        # to fetch -- and pinning the cheaper number would let a read that had
        # started issuing a query per channel hide behind an empty table.
        a_finding(package)
    cutoff = choose_evidence_cutoff()
    run = a_policy_run_row()
    # Prepared outside the measurement, exactly as the orchestration prepares it
    # outside the package loop: the parameter set is established once per run and
    # the point of this case is what each *package* costs after that.
    policy_pass = LicensePass()
    policy_pass.prepare(policy_run=run, evidence_cutoff=cutoff)

    with django_assert_num_queries(QUERIES_PER_PACKAGE * packages):
        for package in inventory:
            policy_pass.evaluate(package, policy_run=run, evidence_cutoff=cutoff)


@pytest.mark.django_db
def test_one_row_per_package_per_run_over_more_than_one_package() -> None:
    """`CPM-AD-21`'s key and `CPM-AD-23`'s atomic unit, over an inventory.

    Two packages with different evidence, one run: two rows, each about its own
    package, neither carrying the other's verdict. A pass that had computed once
    and written the same row twice would satisfy every single-package case here.
    """
    an_ended_collection_run()
    permitted = a_package("permitted")
    refused = a_package("refused")
    a_finding(permitted, expression=AN_ALLOWED_LICENCE)
    a_finding(refused, expression=A_FORBIDDEN_LICENCE)

    a_policy_run()

    assert PackageLicense.objects.count() == PACKAGES_IN_THE_INVENTORY
    assert the_finding(permitted).license_outcome == ALLOWED
    assert the_finding(refused).license_outcome == FORBIDDEN


@pytest.mark.django_db
def test_the_row_records_the_version_and_the_cutoff_it_was_computed_under() -> None:
    """The two facts about the run this table copies where the two older ones copy none.

    An outcome is meaningless without the rule set that produced it, and the rules
    are keyed by version -- so a report reading this table alone can say what a
    value was drawn from. The cut-off is what a replay is compared over.
    """
    an_ended_collection_run()
    package = a_package()

    a_policy_run()

    row = the_finding(package)
    assert row.policy_version == A_POLICY_VERSION
    assert row.evidence_cutoff == FIXED_INSTANT
    assert row.policy_run.policy_version == row.policy_version


@pytest.mark.django_db
def test_the_version_the_row_says_produced_it_is_the_version_that_did() -> None:
    """The line sends a reader to an entry, so it has to name the entry that ran.

    `license_detail` takes the version as an argument and the pass passes the
    run's; handing it `""`, or the newest recorded version, or the string `"the
    policy version"` satisfies every case that only checks the key name appears.
    A `manual_review` on every package is the shipped output of this component,
    and the version in its `detail` is the whole of what makes the row
    actionable.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package, expression=AN_UNRULED_LICENCE)

    a_policy_run(version=A_VERSION_WITHOUT_RULES)

    row = the_finding(package)
    assert row.license_outcome == MANUAL_REVIEW
    assert A_VERSION_WITHOUT_RULES in row.detail
    assert A_POLICY_VERSION not in row.detail


@pytest.mark.django_db
def test_the_pass_writes_only_its_own_table_and_no_rollup_column() -> None:
    """`CPM-AD-21`: no pass writes the health rollup, and this one contributes nothing to it.

    Four passes run and each writes its own per-domain table. What this adds to
    that is the negative: the rollup row exists, it carries this pass's name in
    the version map because the pass ran, and it holds **no** column this pass
    produced -- because there is none, and adding one is what `CPM-AD-21` forbids.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package)

    a_policy_run()

    health = PackageHealth.objects.get(package=package)
    assert health.policy_versions[POLICY_NAME] == A_POLICY_VERSION
    assert PackageLicense.objects.filter(package=package).count() == 1
    assert not [field.name for field in PackageHealth._meta.concrete_fields if "licen" in field.name]  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


# ---------------------------------------------------------------------------
# What the database refuses -- and the one refusal this story exists for.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_allowed_row_that_names_no_rule_is_refused_by_the_database() -> None:
    """**The constraint this story exists to put in the schema.**

    `allowed` is the one verdict in this product that claims nothing is wrong, and
    the one whose appearance in error would be least likely to be questioned,
    because it looks like good news. Every other outcome is reachable by an
    absence; this one must be reachable only by a positive statement. So the rule
    is held at the database and not only in the pass: a hand-written `INSERT` that
    went round `policies/licence.py` entirely is refused by PostgreSQL.

    Built by `create()` rather than through the pass for exactly that reason --
    the pass cannot produce this row, so a case that only drove the pass would
    pass against a constraint weakened to `1 = 1`.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        a_hand_built_row(
            license_outcome=ALLOWED,
            matched_rule="",
            license_finding=a_finding(a_package("evidence")),
        )


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", [RESTRICTED, FORBIDDEN], ids=[RESTRICTED, FORBIDDEN])
def test_the_other_ruled_outcomes_also_have_to_name_their_rule(outcome: str) -> None:
    """The sibling rule, held on every half rather than on the one it was written for.

    All three are reachable only from a rule's recorded disposition, so holding
    the rule on `allowed` alone would be the "one half only" defect
    `ESTABLISHED_VULNERABILITY_STATUSES` records one domain over. `allowed` is
    the value the constraint exists *for*; it is not the only value it is true of.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        a_hand_built_row(
            license_outcome=outcome,
            matched_rule="",
            license_finding=a_finding(a_package("evidence")),
        )


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", [MANUAL_REVIEW, LICENSE_STATUS_UNKNOWN], ids=["manual-review", "unknown"])
def test_an_outcome_no_rule_decided_may_not_name_a_rule(outcome: str) -> None:
    """The other half of the biconditional, and it is a contradiction rather than an oddity.

    A `manual_review` naming a matched rule says both that a rule decided this
    licence and that none did. Asserting the converse is what makes `matched_rule`
    readable as "the rule behind this outcome, or nothing" rather than as a column
    whose meaning depends on which value sits beside it.
    """
    finding = a_finding(a_package("evidence")) if outcome == MANUAL_REVIEW else None

    with pytest.raises(IntegrityError), transaction.atomic():
        a_hand_built_row(license_outcome=outcome, matched_rule=AN_ALLOWED_LICENCE, license_finding=finding)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "outcome",
    [ALLOWED, RESTRICTED, FORBIDDEN, MANUAL_REVIEW],
    ids=[ALLOWED, RESTRICTED, FORBIDDEN, MANUAL_REVIEW],
)
def test_a_judged_outcome_with_no_finding_behind_it_is_refused(outcome: str) -> None:
    """A compliance verdict about a package whose licence was never established.

    All four are statements about a licence this run established -- three because a
    rule named it and `manual_review` because none did -- and each requires the run
    to have read a channel that said what the licence is. `manual_review` is in
    the set for the reason it is easiest to leave out: "somebody has to look at
    this" reads as a to-do rather than as the assertion that a licence exists.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        a_hand_built_row(
            license_outcome=outcome,
            matched_rule="" if outcome == MANUAL_REVIEW else AN_ALLOWED_LICENCE,
            license_finding=None,
        )


@pytest.mark.django_db
def test_an_unknown_outcome_needs_no_finding_and_no_rule() -> None:
    """The row this vocabulary exists to be honest about, and the reason `unknown` is exempt.

    Requiring evidence behind it would forbid a package nobody has observed.
    Asserted, because a constraint tightened to "every outcome names a row" would
    pass every case above.
    """
    row = a_hand_built_row()

    assert row.pk is not None


@pytest.mark.django_db
def test_the_derived_table_refuses_a_second_row_for_one_package_and_run() -> None:
    """`CPM-AD-21`'s key as a database rule rather than as the writer's promise.

    A second row for one pair means the pass ran twice or two passes wrote one
    table, and a reader joining this to anything else would silently get whichever
    the database returned first.
    """
    first = a_hand_built_row()

    with pytest.raises(IntegrityError), transaction.atomic():
        PackageLicense.objects.create(
            package=first.package,
            policy_run=first.policy_run,
            license_outcome=LICENSE_STATUS_UNKNOWN,
            policy_version=A_POLICY_VERSION,
            evidence_cutoff=FIXED_INSTANT,
        )


@pytest.mark.django_db
def test_a_row_whose_policy_version_names_nothing_is_refused() -> None:
    """`CPM-AD-8` in the column that carries it.

    A row whose version names nothing cannot be replayed and cannot say which rule
    set its outcome was drawn from -- which matters most for the row that says
    `manual_review`, since the answer at a later version may be anything at all.
    """
    with pytest.raises(IntegrityError), transaction.atomic():
        a_hand_built_row(policy_version="")


# ---------------------------------------------------------------------------
# The evidence a real collector writes, and the file this component ships.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_licence_the_collector_actually_wrote_is_matched_by_a_rule() -> None:
    """The one contract case between the two modules that share this table.

    Every other case here writes `license_findings` rows directly, with a state
    and a normalized expression a case chose, so all of them would keep passing if
    the collector and the pass disagreed about what a determinate licence row
    looks like. So this drives `LicenseCollector` over a channel document stating
    `MIT`, then runs the policy at a version whose rule set names `MIT` and
    permits it, and requires the derived row to be `allowed` and to name that
    rule.

    Nothing here chooses the evidence text; the collector and
    `collectors/spdx.py` do, which is the whole point -- a normalization that
    started producing a different spelling would surface here rather than as a
    silent inventory-wide `manual_review`.
    """
    package = a_package()
    locator = package_locator(A_CHANNEL, package.canonical_name)
    collector = LicenseCollector(
        clock=FixedClock(instant=FIXED_INSTANT),
        transport=RecordedTransport(
            payload=recorded_payload(
                source=locator,
                body=json.dumps({"name": package.canonical_name, LICENSE_FIELD: AN_ALLOWED_LICENCE}),
            ),
        ),
        limiter=FixedLimiter(permitted=True),
        response_cache=RecordingResponseCache(),
    )
    try:
        with override_settings(**{CHANNELS_SETTING: (A_CHANNEL,)}):
            collector.collect(package_id=package.pk)
    finally:
        collector.close()

    written = LicenseFinding.objects.get(package=package)
    a_policy_run()

    assert written.state == NORMALIZED
    assert written.normalized_license == AN_ALLOWED_LICENCE
    row = the_finding(package)
    assert row.license_outcome == ALLOWED
    assert row.matched_rule == AN_ALLOWED_LICENCE
    assert row.license_finding_id == written.pk


def test_no_shipped_version_records_any_licence_rule() -> None:
    """**This story's `Block If`, as a check rather than as prose.**

    `CPM-FR-18`'s content is PRD Open Question 2, which the PRD names as
    unanswered and as blocking `CPM-EP-SECURITY`, so `CPM-SECURITY-S05` shipped
    the mechanism and the schema with **no allow entries and no deny entries**.
    Nothing else in this repository would notice a "provisional" allow list being
    added to that file: every pass would keep working, every case here would keep
    passing, and packages would start reading `allowed` because a component
    decided a compliance question it was told not to decide.

    So the file is read directly and every version in it is required to record no
    rule. The day Open Question 2 is answered, this case is the deliberate edit
    that says so -- which is exactly what it is for.

    Read from the shipped path rather than through `parameters_for`, because this
    module has the reader pointed at its own file, and read directly rather than
    through the memoized entry point, so it cannot be satisfied by a parse some
    earlier case happened to cache.
    """
    offenders = {
        version: entry.license_rules
        for version, entry in parameters_at(THE_SHIPPED_FILE).items()
        if entry.license_rules
    }

    assert offenders == {}, (
        "a shipped policy version records a licence rule. CPM-SECURITY-S05 ships the mechanism and the schema "
        "with no allow entries and no deny entries, because PRD Open Question 2 is unanswered; answering it is "
        "a deliberate edit to this case as well as to the file."
    )


def test_the_newest_shipped_version_declares_the_rule_key_as_an_explicitly_empty_list() -> None:
    """The other half of the `Block If`: the schema *is* shipped, visibly empty.

    An absent key and an empty list parse to the same rule set, so
    `parameters_at` cannot tell them apart -- which is the right behaviour and is
    why this case reads the document instead. What it pins is that the newest
    entry says out loud what an older entry could only imply: review looked at the
    licence policy and recorded nothing, and here is the key an operator fills in.

    A reviewer answering Open Question 2 copies this entry, so the entry has to
    exist and has to carry the key.
    """
    document = tomllib.loads(THE_SHIPPED_FILE.read_text(encoding="utf-8"))

    entry = document[VERSIONS_TABLE][THE_NEWEST_SHIPPED_VERSION]
    assert RULES_KEY in entry, sorted(entry)
    assert entry[RULES_KEY] == []


@pytest.mark.django_db
def test_a_run_at_the_earliest_shipped_version_writes_every_domains_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CPM-FR-22` at the version this pass could most easily have broken.

    `2026.09` is the earliest version this repository ships and it predates the
    licence rule key entirely, so it is the one a refusal for "this version
    records no rule set" would have destroyed -- and it would have destroyed the
    currency, feedstock and vulnerability rows of every run recorded at it, not
    only this pass's. That is the regression `CPM-SECURITY-S04`'s review found
    after the fact, and this is the case that would have caught it.

    It reads the **shipped** file rather than this module's substituted one,
    because the version it is about is a fact of the shipped file.
    """
    an_ended_collection_run()
    package = a_package()
    a_finding(package)

    with the_shipped_parameters(monkeypatch):
        a_policy_run(version=THE_EARLIEST_SHIPPED_VERSION)

    row = the_finding(package)
    assert row.policy_version == THE_EARLIEST_SHIPPED_VERSION
    assert row.license_outcome == MANUAL_REVIEW
    assert row.matched_rule == ""
    assert PackageCurrency.objects.filter(package=package).count() == 1
    assert PackageFeedstockPresence.objects.filter(package=package).count() == 1
    assert PackageVulnerability.objects.filter(package=package).count() == 1
    assert PackageHealth.objects.filter(package=package).count() == 1
    assert PolicyRun.objects.get(policy_version=THE_EARLIEST_SHIPPED_VERSION).status == RunState.SUCCEEDED
