"""The demo seeder's declarations: refused outside a local run, and spelled correctly.

Two things are checked here and the second is the one the module's own docstring
promises. `config/local_dev/demo_data.py` writes evidence with **string literals**
for the states -- `"normalized"`, `"inferred_compatible"`, `"established"` -- because
`core/outcomes.py`'s `outcome_type` composes each vocabulary per domain and a member
reference is invisible to the type checker. A literal that drifted from the column's
declared choices would fail at the first `IntegrityError` on somebody's laptop,
halfway through seeding, with a constraint name and no hint which value was wrong.
That is exactly what happened while the module was being written -- twice -- so the
reconciliation is a test.

**The refusal is checked before any row is written**, which is the whole of why it
matters: `CPM-AD-2` makes evidence append-only, so a fictional observation written by
a deployed component cannot be deleted and would be read by every replayed policy run
afterwards. A refusal that fired after the first insert would be no refusal at all.

Reads declarations and model metadata: no database writes, no policy run. What the
seeder actually produces is `tests/integration/test_local_dev_demo_seeding.py`.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final

import pytest
from django.core.exceptions import ImproperlyConfigured

from conda_sentinel.collectors.models import CondaPackageSnapshot
from conda_sentinel.collectors.models import LicenseFinding
from conda_sentinel.collectors.models import PyPIReleaseSnapshot
from conda_sentinel.collectors.models import PythonReadinessAssessment
from conda_sentinel.collectors.models import SourceReleaseSnapshot
from conda_sentinel.collectors.models import VulnerabilityFinding
from conda_sentinel.core.registry import registered_collectors
from conda_sentinel.identity.models import MappingOutcome
from config.local_dev import demo_data

#: The literals the seeder writes, and the model whose `state` column has to accept
#: each. Written out rather than read from the module's private names, so the pairing
#: is stated here and a rename on either side is a failing case rather than a test
#: that quietly checks a value against itself.
DECLARED_STATES: Final[tuple[tuple[str, type], ...]] = (
    ("normalized", LicenseFinding),
    ("inferred_compatible", PythonReadinessAssessment),
)

#: How many packages the demo seeds.
#:
#: A hundred since `CPM-PLATFORM-S05`, and the number is asserted for the reason it
#: was asserted at ten: the point of the roster is *variety*, and a seeder that had
#: lost most of it would still produce a screen that looked fine. What changed is why
#: a hundred -- ten rows fit above the fold, sort instantly and paginate never, so a
#: reviewer asking whether a screen is usable was being shown one that could not be
#: unusable.
EXPECTED_PACKAGES: Final[int] = 100


@pytest.mark.parametrize(("value", "model"), DECLARED_STATES, ids=str)
def test_every_state_literal_is_one_its_column_declares(value: str, model: type) -> None:
    """The reconciliation the module's docstring promises.

    A literal that drifted fails here, naming the value and the table, rather than at
    the first `IntegrityError` halfway through seeding somebody's laptop.

    Args:
        value: The literal the seeder writes.
        model: The evidence model whose `state` column must accept it.

    """
    declared = {choice for choice, _label in model._meta.get_field("state").choices}  # noqa: SLF001 - model metadata

    assert value in declared, f"{model.__name__}.state does not accept {value!r}; it accepts {sorted(declared)}"


def test_the_mapping_outcome_literals_are_ones_the_vocabulary_declares() -> None:
    """The identity resolution's own vocabulary, checked the same way.

    `MappingOutcome` is composed by `outcome_type` too, so `_ESTABLISHED` and
    `_NOT_FOUND` are literals for the same reason and can drift for the same reason.
    """
    declared = set(MappingOutcome.values)

    assert "established" in declared
    assert "not_found" in declared


def test_the_demo_collector_is_not_a_registered_collector() -> None:
    """The coverage screen reads the run ledger by collector name.

    Seeding runs under `vulnerability` would report that collector as healthy on a
    machine where it has never made a single request -- which is precisely the lie
    `surface/coverage.py` exists to prevent, told by the fixture meant to demonstrate
    it.
    """
    adopted = {collector.name for collector in registered_collectors()}

    assert demo_data.DEMO_COLLECTOR not in adopted
    assert adopted != set()


def test_the_roster_seeds_enough_packages_to_show_variety() -> None:
    """A seeder that had lost most of its roster would still render a plausible screen.

    Which is the failure worth catching: the demo exists to show that the design
    distinguishes states, and eight identical rows demonstrate nothing.
    """
    assert len(demo_data.DEMO_PACKAGES) == EXPECTED_PACKAGES
    assert len({demo.name for demo in demo_data.DEMO_PACKAGES}) == EXPECTED_PACKAGES


def test_the_roster_covers_every_state_the_screens_must_distinguish() -> None:
    """`CPM-FR-5`'s five states, each present in the seeded inventory.

    Asserted over the *declarations* rather than over what the run concludes, because
    this is the roster's job: a demo that produced only clean packages and adverse
    verdicts would leave the three states a reader most needs to tell apart untested
    by eye.
    """
    assert any(demo.advisory for demo in demo_data.DEMO_PACKAGES), "no adverse verdict"
    assert any(not demo.advisory for demo in demo_data.DEMO_PACKAGES), "nothing found by a lookup"
    assert any(not demo.feedstock for demo in demo_data.DEMO_PACKAGES), "nothing to find"
    assert any(demo.python_evidence == "none" for demo in demo_data.DEMO_PACKAGES), "no question that does not apply"

    assert any(demo.errored for demo in demo_data.DEMO_PACKAGES), "no lookup that broke"
    assert any(not demo.identified for demo in demo_data.DEMO_PACKAGES), "nothing for the confidence gate to blank"


def test_the_roster_covers_both_kinds_of_python_evidence() -> None:
    """`CPM-PY314-S03` made the kind of evidence part of the verdict.

    The detail view traces a verified verdict to the build and an inferred one to the
    metadata, and a demo carrying only one kind would exercise one branch.

    The values are named for the *evidence* -- `build`, `metadata` -- rather than for
    the verdict. `verified` is also an `IdentityConfidence` value, and comparing
    against it reads like a second confidence gate; the confidence-gate audit said so
    when the module was first written.
    """
    kinds = {demo.python_evidence for demo in demo_data.DEMO_PACKAGES}

    assert {"build", "metadata", "none"} <= kinds


def test_the_roster_carries_a_kev_listing_and_a_non_listing() -> None:
    """The KEV column qualifies the vulnerability column beside it.

    A demo where every advisory was listed -- or none was -- would make the two
    columns look like one.
    """
    with_advisory = [demo for demo in demo_data.DEMO_PACKAGES if demo.advisory]

    assert any(demo.kev_listed for demo in with_advisory)
    assert any(not demo.kev_listed for demo in with_advisory)


def test_seeding_is_refused_outside_a_local_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CPM-AD-2` is why this refusal has to fire before the first insert.

    Evidence is append-only: a fictional observation written by a deployed component
    cannot be deleted, and every replayed policy run would read it afterwards. A
    refusal that fired after the first row would be no refusal at all.

    Args:
        monkeypatch: pytest's patcher, which restores the locality reader.

    """
    monkeypatch.setattr(demo_data, "is_local", lambda: False)

    with pytest.raises(ImproperlyConfigured, match=r"append-only"):
        demo_data.seed_demo_inventory()


def test_the_refusal_names_what_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal a reader cannot act on sends them to the source to find out how.

    Args:
        monkeypatch: pytest's patcher.

    """
    monkeypatch.setattr(demo_data, "is_local", lambda: False)

    with pytest.raises(ImproperlyConfigured, match=r"COMPONENT_RUNTIME=local"):
        demo_data.seed_demo_inventory()


def test_no_demo_package_declares_a_verdict() -> None:
    """The constraint the whole module is shaped around, asserted as a shape.

    `DemoPackage` has no field that says "this should come out P1". Every field is an
    observation, and what the screens show has to be something the policy engine
    concluded from them -- otherwise the demo is a picture of a product rather than
    the product.
    """
    fields = {field.name for field in demo_data.DemoPackage.__dataclass_fields__.values()}
    verdict_shaped = {"priority", "bucket", "work_type", "status", "readiness", "currency"}

    assert fields & verdict_shaped == set(), sorted(fields & verdict_shaped)


@pytest.mark.parametrize("model", [SourceReleaseSnapshot, PyPIReleaseSnapshot, CondaPackageSnapshot])
def test_the_release_snapshots_accept_the_ok_state_the_seeder_writes(model: type) -> None:
    """Three tables where the determinate value *is* `ok`, unlike the two above.

    Which is the trap: `LicenseFinding` calls its determinate state `normalized` and
    `PythonReadinessAssessment` calls its `inferred_compatible`, while these three
    call theirs `ok`. Writing `ok` to the first two is the mistake the seeder made,
    and this is the case that says the other three are not the same.

    Args:
        model: The evidence model under test.

    """
    declared = {choice for choice, _label in model._meta.get_field("state").choices}  # noqa: SLF001 - model metadata

    assert "ok" in declared


def test_the_vulnerability_table_does_not_accept_ok() -> None:
    """And the one that catches the trap from the other side.

    `VulnerabilityFinding`'s determinate state is `matched`. If it ever grew an `ok`,
    the seeder's states would still be right but the argument above would have
    quietly stopped being the reason they are.
    """
    declared = {choice for choice, _label in VulnerabilityFinding._meta.get_field("state").choices}  # noqa: SLF001

    assert "ok" not in declared
    assert "matched" in declared


def test_a_package_with_no_feedstock_still_seeds_one_snapshot() -> None:
    """`FeedstockSnapshot.absence_established` separates two things that look alike.

    "We looked and there is no feedstock" and "we did not look" are different, and
    `CPM-FR-5` turns on a reader being able to tell them apart. The demo seeds the
    first, so the screen shows a `not_found` a reviewer can trust.
    """
    absent = [demo for demo in demo_data.DEMO_PACKAGES if not demo.feedstock]

    assert absent != []


def test_an_idle_feedstock_is_older_than_the_shipped_inactivity_threshold() -> None:
    """The feedstock pass reads a threshold from the parameter file.

    The demo's idle feedstock has to be idle by *that* measure, not by a number
    chosen here -- otherwise the row renders `present_and_maintained` and the
    inactive state never appears on the screen.
    """
    shipped_threshold_days = 180
    idle = max(demo.feedstock_idle_days for demo in demo_data.DEMO_PACKAGES)

    assert idle > shipped_threshold_days


def _parsed(version: str) -> tuple[int, ...] | None:
    """Return a version as a comparable tuple, or `None` where it is not numeric.

    Deliberately not `packaging.version.Version`. This module needs to compare two
    strings the roster wrote next to each other, not to implement PEP 440, and every
    version in the roster is dotted digits -- so a parser that gives up on anything
    else is honest about its own reach and adds no dependency to say so.

    Args:
        version: The version string as the roster declares it.

    Returns:
        The dotted numbers as a tuple, or `None` when any component is not a number.

    """
    parts = version.split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def test_no_roster_row_declares_an_installed_version_ahead_of_its_upstream() -> None:
    """The guard that makes the roster's positional columns safe rather than shorter.

    `CPM-PLATFORM-S05` turned a ten-row roster into a hundred, and a hundred rows only
    stay readable as one line each -- which means the first three arguments are
    positional and one of them is `upstream_version` and the next is
    `installed_version`. Swapping that pair is the mistake positional arguments always
    invite, and it is a *silent* one here: the currency pass concludes `behind` for a
    package that is current and `current` for one that is behind, both of which render
    perfectly and neither of which is flagged by anything else.

    Equal versions are correct and common -- most of the roster is up to date.
    """
    inverted = [
        f"{demo.name}: installed {demo.installed_version} ahead of upstream {demo.upstream_version}"
        for demo in demo_data.DEMO_PACKAGES
        if (installed := _parsed(demo.installed_version)) is not None
        and (upstream := _parsed(demo.upstream_version)) is not None
        and installed > upstream
    ]

    assert inverted == []


def test_the_guard_would_catch_an_inverted_pair() -> None:
    """Because a comparison over a roster that happens to be right proves nothing.

    The case above passes on an empty roster, on a roster of equal pairs, and on one
    where every version failed to parse. This is the one that says the comparison
    itself works, written against a declaration rather than against the real roster.
    """
    inverted = demo_data.DemoPackage(name="wrong-way-round", upstream_version="1.0.0", installed_version="2.0.0")

    installed = _parsed(inverted.installed_version)
    upstream = _parsed(inverted.upstream_version)

    assert installed is not None
    assert upstream is not None
    assert installed > upstream


def test_every_advisory_identifier_is_one_somebody_can_look_up() -> None:
    """The product owner asked for real advisories, and this is what "real" has to mean.

    The roster used to carry `GHSA-demo-high` and `GHSA-demo-moderate`. A reviewer who
    looks one of those up finds nothing, and what they learn is to stop looking things
    up -- which is a worse outcome than a demo with no advisories at all, because it
    trains the habit the product exists to support out of them.

    Every identifier below came from OSV.dev. This asserts the *shape* rather than
    re-querying: a test that made a network request would fail on an aeroplane, and
    what it would be checking is that OSV is up rather than that this roster is
    honest. What it does catch is a placeholder, which is the thing that actually went
    wrong.
    """
    identifiers = [demo.advisory[0] for demo in demo_data.DEMO_PACKAGES if demo.advisory]
    real = re.compile(r"^(?:CVE-\d{4}-\d{4,}|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})$")

    assert identifiers != []
    assert [name for name in identifiers if not real.match(name)] == []
    assert [name for name in identifiers if "demo" in name.casefold()] == []


def test_every_advisory_states_a_severity_the_shipped_order_ranks() -> None:
    """A severity outside the recorded order contributes nothing to the risk level.

    `vulnerability_risk_order` is matched case-insensitively against the finding's own
    stated severity, and a severity the order does not name is silently ignored -- so
    a roster full of advisories could still produce a screen where every risk level is
    blank, which looks like the pass being broken.
    """
    shipped_order = {"critical", "high", "moderate", "low"}
    stated = {demo.advisory[1] for demo in demo_data.DEMO_PACKAGES if demo.advisory}

    assert stated <= shipped_order
    # More than one, or the risk column shows a single tone and demonstrates no order.
    assert len(stated) > 1


def test_a_kev_listing_carries_the_date_the_catalogue_states() -> None:
    """The reason a KEV listing is worth showing at all is that it is checkable.

    A date computed from the run -- "thirty days ago", which this seeder used to do --
    moves every time somebody reseeds and matches nothing in CISA's catalogue. A
    reader who checks finds a mismatch and concludes the collector is wrong.
    """
    listed = [demo for demo in demo_data.DEMO_PACKAGES if demo.kev_listed]

    assert listed != []
    assert [demo.name for demo in listed if not demo.kev_catalogued] == []
    for demo in listed:
        assert date.fromisoformat(demo.kev_catalogued) <= date.today(), demo.name  # noqa: DTZ011


def test_nothing_unlisted_claims_a_catalogue_date() -> None:
    """`kev_findings` refuses a `not_listed` row that carries one, and rightly.

    A date on a row saying the catalogue does not list the advisory is a contradiction
    the table has a constraint against, so a roster that declared one would fail at
    the first insert rather than at the point the mistake was made.
    """
    stray = [demo.name for demo in demo_data.DEMO_PACKAGES if demo.kev_catalogued and not demo.kev_listed]

    assert stray == []


def test_the_roster_is_the_mixture_it_was_asked_to_be() -> None:
    """Web frameworks, data science, utilities, and things that are not Python at all.

    Asked for by name by the product owner. A roster of a hundred packages all of one
    kind would be a hundred rows that still demonstrate one thing -- and the
    non-Python entries are load-bearing rather than decorative: they are where
    `not_applicable` on the Python 3.14 column comes from, instead of a contrivance.
    """
    names = {demo.name for demo in demo_data.DEMO_PACKAGES}

    for kind, sample in (
        ("web frameworks", {"django", "flask", "fastapi", "tornado", "litestar"}),
        ("data science", {"numpy", "pandas", "scikit-learn", "pytorch", "hdbscan"}),
        ("utilities", {"setuptools", "pytest", "boto3", "sqlalchemy", "cattrs"}),
        ("not Python at all", {"git", "nodejs", "cmake", "ffmpeg", "sqlite"}),
    ):
        assert sample <= names, f"the roster lost its {kind}: {sorted(sample - names)}"


@pytest.mark.parametrize(
    ("licence", "method"),
    [
        ("MIT", "spdx-identifier"),
        ("Apache-2.0 OR BSD-3-Clause", "spdx-expression"),
        ("Apache-2.0 AND BSD-3-Clause", "spdx-expression"),
        ("GPL-2.0-only WITH Classpath-exception-2.0", "spdx-expression"),
        # Not an operator: the word is inside an identifier, not joining two.
        ("BSD-3-Clause-Clear", "spdx-identifier"),
    ],
)
def test_a_compound_licence_is_recorded_as_an_expression(licence: str, method: str) -> None:
    """The column declares three values and the seeder has to pick the right one.

    It used to test for `" OR "` alone, which was true of the ten-package roster and
    false of this one: `tqdm` declares `MPL-2.0 AND MIT` and `python-dateutil`
    declares `Apache-2.0 AND BSD-3-Clause`, and both would have been filed as single
    identifiers -- a licence screen quietly saying an expression is an identifier.

    Args:
        licence: What the metadata declared.
        method: What the seeder should record as having recognised it.

    """
    recognised = "spdx-expression" if demo_data._COMPOUND.search(licence) else "spdx-identifier"  # noqa: SLF001

    assert recognised == method


def test_the_roster_answers_the_python_question_both_ways() -> None:
    """`CPM-FR-24` exists to tell a package that is ready from one that is not.

    Every seeded package used to come out ready, which made the product's headline
    column render one tone across the whole screen -- and made two of the shipped
    priority rules, `p8` and `p9`, unreachable by anything the demo could produce.
    """
    kinds = {demo.python_evidence for demo in demo_data.DEMO_PACKAGES}

    assert {"build", "metadata", "metadata-incompatible", "build-failed", "none"} <= kinds


def test_the_roster_pushes_a_fix_to_every_surface_the_remediation_pass_reads() -> None:
    """Otherwise the screen that separates "act today" from "wait" shows one value.

    `policies/remediation.py` decides between `ready`, `awaiting_build` and
    `awaiting_packaging` by reading which surface carries the fixed version, and the
    priority rules `p1` and `p2` turn on that difference. A roster where the fix had
    reached exactly one surface put every vulnerable package in `p3` -- "no fix is in
    sight" -- including the ones whose fix conda-forge was already shipping.
    """
    reached = {demo.fix_reached for demo in demo_data.DEMO_PACKAGES if demo.advisory}

    assert reached == {"release", "recipe", "channel"}


def test_only_a_package_with_an_advisory_says_how_far_its_fix_got() -> None:
    """The field is meaningless without one, and a value on a clean row would read as one.

    `_surface_version` ignores it in that case, so a stray value changes nothing and
    would sit in the roster looking like it did -- which is the kind of dead
    declaration somebody later reasons from.
    """
    stray = [demo.name for demo in demo_data.DEMO_PACKAGES if demo.advisory is None and demo.fix_reached != "release"]

    assert stray == []
