"""A local inventory with evidence behind it, so the screens have something to render.

`seed_personas` gives a developer a way in. This gives them something to look at:
without it, a fresh checkout renders every status as `unknown` -- correct, and
useless for judging a screen, because the one thing every cell has in common is the
value it would have if the projection were broken.

**Nothing here fabricates a verdict.** That is the constraint the whole module is
shaped around. It writes *evidence* -- append-only rows, exactly as a collector would
(`CPM-AD-2`) -- and then runs the real policy engine over it. Every status on the
resulting screens was concluded by the pass that owns it, from the parameter file
that ships. A seeder that inserted rows into `package_health` directly would be
faster, would produce prettier screens, and would make the demo a picture of a
product rather than the product; `CPM-AD-10` forbids the application layer a write
path to a derived status, and a fixture that took one would be testing the templates
against data the engine cannot produce.

**Identity goes through resolution, never through `Package.objects.create`.**
`CPM-AD-14` gives governed reference data exactly one write path and `CPM-AD-25`
says a collector "never writes the package table" -- it calls the resolution service,
which creates the shell at `unmapped`. So does this: every demo package is resolved
into existence, and the ones that should be identified are then resolved properly.
The unmapped one is simply never promoted, which is why it is a *real* unmapped
package rather than a row with a string in a column.

**It refuses outside a local run**, on the terms `seeding.py` sets: this writes
inventory and evidence, and a deployed component that ran it would have permanent,
replayable, fictional observations in a log nothing may update or delete.

**What it cannot show you, and says so.** The shipped parameter file records
`priority_rules = []` and `license_rules = []` -- deliberately, and both files
explain why at length. So a run at the shipped version concludes `unknown` for every
priority bucket and `manual_review` for every licence, whatever evidence is behind
them. That is the product working as configured, not the seeder failing, and
`SEEDED_EVENT` reports it rather than letting a reader conclude the columns are
broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Final

import structlog
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from config.locality import is_local

if TYPE_CHECKING:
    from datetime import datetime

    from conda_sentinel.identity.models import Package
    from conda_sentinel.identity.services import FeedstockMapping

__all__ = [
    "DEMO_COLLECTOR",
    "DEMO_PACKAGES",
    "SEEDED_EVENT",
    "DemoPackage",
    "seed_demo_inventory",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: What a deployed component is told when it tries to run this.
#:
#: Stronger wording than the persona seeder's, because the consequence is worse and
#: is not undoable: personas are user rows somebody can delete, while this writes
#: append-only evidence. `CPM-AD-2` means a fictional observation, once written, is
#: permanent and will be read by every replayed policy run for ever.
_DEPLOYED_REFUSAL: Final[str] = (
    "seed_demo_inventory writes inventory and evidence and must never run outside a local run. "
    "Evidence is append-only (CPM-AD-2): a fictional observation cannot be deleted, and every replayed "
    "policy run would read it. Set COMPONENT_RUNTIME=local, which the dev pixi environment declares."
)

#: The collector name the seeded runs are filed under.
#:
#: Deliberately not one of the ten registered collector names. The coverage screen
#: reads the run ledger by collector, and seeding runs under `vulnerability` would
#: report that collector as healthy on a machine where it has never made a request --
#: which is precisely the lie that screen exists to prevent.
DEMO_COLLECTOR: Final[str] = "local-dev-demo-seed"

#: The evidence vocabularies' own values, spelled as strings.
#:
#: `core/outcomes.py`'s `outcome_type` composes each of these per domain, which means
#: a member reference is invisible to the type checker -- the composed class is a
#: `TextChoices` with no statically known members. The values are asserted against the
#: models' declared choices in `tests/unit/test_local_dev_demo_data.py`, so a renamed
#: value fails there rather than at the first `IntegrityError` on somebody's laptop.
_ESTABLISHED: Final[str] = "established"
_NOT_FOUND: Final[str] = "not_found"
_NORMALIZED: Final[str] = "normalized"
_INFERRED_COMPATIBLE: Final[str] = "inferred_compatible"

#: The policy version the seeded run is executed at.
#:
#: The newest version the shipped parameter file records. An unrecorded version fails
#: every package (`CPM-CURRENCY-S07`), so this is read from the file rather than
#: written here -- see `_shipped_policy_version`.
SEEDED_EVENT: Final[str] = "local_dev.demo_inventory_seeded"


@dataclass(frozen=True, slots=True)
class DemoPackage:
    """One package to seed, and what the sources should be made to have said about it.

    Every field is an *observation*, never a verdict. There is no way to express
    "this package should come out P1" here, and that is the point: what the screens
    show has to be something the policy engine concluded.
    """

    name: str

    #: What the upstream source and the installed artifact are at. A package behind
    #: its upstream is the ordinary interesting case.
    upstream_version: str
    installed_version: str

    #: Whether the identity is resolved. `False` leaves the shell at `unmapped`,
    #: which `CPM-AD-4` then gates every verdict on -- the demo's one fully gated row.
    identified: bool = True

    #: The advisory to record, if any: `(advisory_id, severity, affected_range)`.
    advisory: tuple[str, str, str] | None = None

    #: Whether the advisory is in the KEV catalogue. Only meaningful with one.
    kev_listed: bool = False

    #: The licence the artifact declares, if the licence lookup found one.
    licence: str = ""

    #: Whether a conda-forge feedstock exists, and when it last saw a commit.
    feedstock: bool = True
    feedstock_idle_days: int = 3

    #: How the Python 3.14 question was answered: `"build"` for a verification that
    #: ran, `"metadata"` for a static assessment, `"none"` for neither.
    #:
    #: **Named for the evidence rather than for the verdict**, and deliberately not
    #: `"verified"`/`"inferred"`. Those are `PackagePythonReadiness`'s words for what
    #: it *concluded*, and this field says what the sources were made to have
    #: recorded -- the seeder does not get to choose a verdict. `"verified"` is also
    #: an `IdentityConfidence` value, so a comparison against it reads, to
    #: `tests/unit/django_apps/test_confidence_gate_audit.py` and to a person, like a
    #: second confidence gate. The audit said so, and it was right to.
    python_evidence: str = "metadata"

    #: Whether a lookup failed instead of answering, and which one. The demo needs at
    #: least one, because `error` is a state `CPM-FR-5` insists a reader can see and
    #: is the one a happy-path fixture never produces.
    errored: tuple[str, ...] = field(default_factory=tuple)


#: The inventory the demo seeds.
#:
#: Ten packages chosen so that **every tone the stylesheet draws appears on the health
#: table at once**, and so that each of `CPM-FR-5`'s five states is on screen: a clean
#: package, an adverse verdict, a lookup that found nothing, a question that does not
#: apply, a lookup that broke, and a package the confidence gate blanks entirely.
#: A demo where every row looks the same tells a reviewer nothing about the design.
#:
#: The names are real conda-forge packages and the version numbers are plausible, but
#: **none of the observations is real** -- no advisory below was published and no
#: build was run. They are fixtures wearing familiar names so the screens read
#: naturally, and `internal-telemetry-sdk` is deliberately not a real package at all.
DEMO_PACKAGES: Final[tuple[DemoPackage, ...]] = (
    DemoPackage(
        name="aiohttp",
        upstream_version="3.9.2",
        installed_version="3.9.1",
        advisory=("CVE-2024-23334", "critical", "<3.9.2"),
        kev_listed=True,
        licence="Apache-2.0",
        python_evidence="metadata",
    ),
    DemoPackage(
        name="cryptography",
        upstream_version="42.0.0",
        installed_version="41.0.4",
        advisory=("GHSA-demo-high", "high", "<42.0.0"),
        licence="Apache-2.0 OR BSD-3-Clause",
        python_evidence="build",
    ),
    DemoPackage(
        name="pyarrow",
        upstream_version="14.0.1",
        installed_version="14.0.1",
        advisory=("GHSA-demo-moderate", "moderate", "<14.0.2"),
        licence="Apache-2.0",
        feedstock_idle_days=420,
    ),
    # No feedstock: the lookup ran and found nothing, which is `not_found` and is a
    # finding rather than a gap.
    DemoPackage(
        name="orjson",
        upstream_version="3.9.12",
        installed_version="3.9.10",
        licence="Apache-2.0",
        feedstock=False,
    ),
    # A native library: the Python 3.14 question does not apply to it.
    DemoPackage(
        name="libarchive",
        upstream_version="3.7.2",
        installed_version="3.7.2",
        licence="BSD-2-Clause",
        python_evidence="none",
    ),
    # Never identified, so `CPM-AD-4` gates every verdict on it. The row a reviewer
    # opens the identity queue for.
    DemoPackage(
        name="internal-telemetry-sdk",
        upstream_version="2.4.0",
        installed_version="2.4.0",
        identified=False,
    ),
    # A lookup that broke rather than answering.
    DemoPackage(
        name="jinja2",
        upstream_version="3.1.2",
        installed_version="3.1.2",
        licence="BSD-3-Clause",
        errored=("advisory",),
    ),
    DemoPackage(name="numpy", upstream_version="2.1.0", installed_version="2.1.0", licence="BSD-3-Clause"),
    DemoPackage(name="scipy", upstream_version="1.14.1", installed_version="1.14.0", licence="BSD-3-Clause"),
    DemoPackage(
        name="pandas",
        upstream_version="2.2.3",
        installed_version="2.2.3",
        licence="BSD-3-Clause",
        python_evidence="build",
    ),
)


def seed_demo_inventory() -> dict[str, object]:
    """Seed a demo inventory, its evidence, and one real policy run over both.

    Returns:
        What was seeded and what the shipped parameter file leaves unconfigured, so
        the caller can say both.

    Raises:
        ImproperlyConfigured: The run is not local. Raised before any row is written,
            for the reason `_DEPLOYED_REFUSAL` states: append-only evidence cannot be
            taken back.

    """
    if not is_local():
        raise ImproperlyConfigured(_DEPLOYED_REFUSAL)

    # Imported here rather than at module scope: this module is reachable from
    # `config/`, which is imported at settings time, and the domain applications'
    # models need a populated app registry.
    from conda_sentinel.core.clock import SystemClock  # noqa: PLC0415 - see above

    clock = SystemClock()
    observed_at = clock.now()

    packages = [_seeded_package(demo, clock=clock) for demo in DEMO_PACKAGES]
    for demo, package in zip(DEMO_PACKAGES, packages, strict=True):
        _seed_evidence(demo, package, observed_at=observed_at)

    summary = _run_policy(observed_at=observed_at, clock=clock)
    logger.info(
        SEEDED_EVENT,
        packages=[demo.name for demo in DEMO_PACKAGES],
        policy_version=summary["policy_version"],
        rollup_rows=summary["rollup_rows"],
        # Said rather than left to be discovered: the shipped parameter file records
        # no priority rules and no licence rules, so those two columns come out
        # `unknown` and `manual_review` whatever evidence is behind them.
        unconfigured=summary["unconfigured"],
    )
    return summary


def _seeded_package(demo: DemoPackage, *, clock: object) -> Package:
    """Return one demo package, resolved into existence the way a collector would.

    Args:
        demo: The package to seed.
        clock: The injected clock (`CPM-AD-26`).

    Returns:
        The saved package: a shell at `unmapped` confidence, promoted to `verified`
        unless the demo says to leave it unresolved.

    """
    from conda_sentinel.identity.models import MappingKind  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.identity.services import Resolution  # noqa: PLC0415 - as above
    from conda_sentinel.identity.services import record_resolution  # noqa: PLC0415 - as above
    from conda_sentinel.identity.services import resolve_package_shell  # noqa: PLC0415 - as above

    with transaction.atomic():
        # The shell is filed under the pair the resolution will name, because
        # `record_resolution` *updates* the row filed under `(identity_source,
        # associator_key)` and never creates one -- `CPM-AD-25` gives creation to
        # `resolve_package_shell` alone. Filing the shell under one pair and
        # resolving against another is a `ResolutionError`, correctly.
        package = resolve_package_shell(
            source_package_key=f"pypi:{demo.name}",
            package_name=demo.name,
            identity_source="pypi",
            clock=clock,  # type: ignore[arg-type]
        )
        if not demo.identified:
            return package

        record_resolution(
            resolution=Resolution(
                identity_source="pypi",
                associator_key=f"pypi:{demo.name}",
                confidence="verified",
                outcomes={
                    MappingKind.SOURCE_REPOSITORY.value: _ESTABLISHED,
                    MappingKind.RELEASE_ECOSYSTEM.value: _ESTABLISHED,
                    MappingKind.CONDA_ARTIFACT.value: _ESTABLISHED,
                    # `not_found` and not an "absent" value: the mapping vocabulary
                    # has no such member, and "we looked for a feedstock and there is
                    # none" is exactly what `not_found` means.
                    MappingKind.FEEDSTOCK.value: _ESTABLISHED if demo.feedstock else _NOT_FOUND,
                    MappingKind.CROSS_ECOSYSTEM.value: _NOT_FOUND,
                },
                canonical_name=demo.name,
                source_repository_url=f"https://github.com/demo/{demo.name}",
                primary_purl=f"pkg:pypi/{demo.name}",
                primary_type="pypi",
                conda_purl=f"pkg:conda/{demo.name}",
                feedstocks=_feedstocks(demo),
            ),
            clock=clock,  # type: ignore[arg-type]
        )
    return package


def _feedstocks(demo: DemoPackage) -> tuple[FeedstockMapping, ...]:
    """Return the feedstock mapping a demo package claims, if it claims one.

    Args:
        demo: The package to seed.

    Returns:
        One mapping, or none for a package with no feedstock.

    """
    from conda_sentinel.identity.services import FeedstockMapping  # noqa: PLC0415 - after django.setup()

    if not demo.feedstock:
        return ()
    return (
        FeedstockMapping(
            name=f"{demo.name}-feedstock",
            url=f"https://github.com/conda-forge/{demo.name}-feedstock",
            metadata_url=f"https://github.com/conda-forge/{demo.name}-feedstock/blob/main/recipe/meta.yaml",
        ),
    )


def _seed_evidence(demo: DemoPackage, package: Package, *, observed_at: datetime) -> None:
    """Insert the observations the demo package's sources are made to have recorded.

    Every row is an insert. `CPM-AD-2` makes evidence append-only, so this is exactly
    the write a collector performs -- and re-running the seeder adds a second
    observation of each fact rather than replacing the first, which is realistic and
    is what makes the detail view's superseded-evidence list worth looking at.

    Args:
        demo: What the sources should have said.
        package: The package they said it about.
        observed_at: When they said it.

    """
    from conda_sentinel.collectors import models as evidence  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.core.outcomes import OutcomeState  # noqa: PLC0415 - as above

    ok = OutcomeState.OK.value
    with transaction.atomic():
        evidence.SourceReleaseSnapshot.objects.create(
            package=package,
            observed_at=observed_at,
            state=ok,
            source=f"https://github.com/demo/{demo.name}",
            latest_version=demo.upstream_version,
        )
        evidence.PyPIReleaseSnapshot.objects.create(
            package=package,
            observed_at=observed_at,
            state=ok,
            source=f"https://pypi.org/project/{demo.name}/",
            latest_version=demo.upstream_version,
        )
        evidence.CondaPackageSnapshot.objects.create(
            package=package,
            observed_at=observed_at,
            state=ok,
            source=f"https://conda.anaconda.org/conda-forge/{demo.name}",
            channel="conda-forge",
            platform="linux-64",
            published_version=demo.installed_version,
            build_string="py312h0",
            build_number=0,
        )
        _seed_feedstock(demo, package, observed_at=observed_at)
        _seed_advisory(demo, package, observed_at=observed_at)
        _seed_licence(demo, package, observed_at=observed_at)
        _seed_python(demo, package, observed_at=observed_at)


def _seed_feedstock(demo: DemoPackage, package: Package, *, observed_at: datetime) -> None:
    """Record whether conda-forge has a feedstock for this package.

    Args:
        demo: What the source should have said.
        package: The package.
        observed_at: When it said it.

    """
    from conda_sentinel.collectors.models import FeedstockSnapshot  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.core.outcomes import OutcomeState  # noqa: PLC0415 - as above

    if not demo.feedstock:
        # `absence_established` is the column that separates "we looked and there is
        # no feedstock" from "we did not look", which is the distinction `CPM-FR-5`
        # exists for and the one an absence claimed without it would erase.
        FeedstockSnapshot.objects.create(
            package=package,
            observed_at=observed_at,
            state=OutcomeState.NOT_FOUND.value,
            source="https://github.com/conda-forge",
            absence_established=True,
        )
        return

    FeedstockSnapshot.objects.create(
        package=package,
        observed_at=observed_at,
        state=OutcomeState.OK.value,
        source=f"https://github.com/conda-forge/{demo.name}-feedstock",
        feedstock_name=f"{demo.name}-feedstock",
        feedstock_url=f"https://github.com/conda-forge/{demo.name}-feedstock",
        recipe_version=demo.installed_version,
        recipe_build_number=0,
        recipe_metadata_url=f"https://github.com/conda-forge/{demo.name}-feedstock/blob/main/recipe/meta.yaml",
        last_recipe_activity_at=observed_at - timedelta(days=demo.feedstock_idle_days),
        absence_established=False,
    )


def _seed_advisory(demo: DemoPackage, package: Package, *, observed_at: datetime) -> None:
    """Record what the advisory sources said, including a lookup that broke.

    Args:
        demo: What the sources should have said.
        package: The package.
        observed_at: When they said it.

    """
    from conda_sentinel.collectors.match_confidence import MatchConfidence  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.collectors.models import KevFinding  # noqa: PLC0415 - as above
    from conda_sentinel.collectors.models import VulnerabilityFinding  # noqa: PLC0415 - as above
    from conda_sentinel.collectors.outcomes import LISTED  # noqa: PLC0415 - as above
    from conda_sentinel.collectors.outcomes import MATCHED  # noqa: PLC0415 - as above
    from conda_sentinel.collectors.outcomes import NOT_LISTED  # noqa: PLC0415 - as above
    from conda_sentinel.collectors.vulnerability import NOTHING_MATCHED_DETAIL  # noqa: PLC0415 - as above
    from conda_sentinel.core.outcomes import OutcomeState  # noqa: PLC0415 - as above

    if "advisory" in demo.errored:
        # The state a happy-path fixture never produces, and the one `CPM-FR-5`
        # insists a reader can tell from "nothing was found".
        VulnerabilityFinding.objects.create(
            package=package,
            observed_at=observed_at,
            state=OutcomeState.ERROR.value,
            source="https://api.osv.dev/v1/query",
            detail="429 rate limited",
        )
        return

    if demo.advisory is None:
        # "The source was read and matched nothing" is `unknown` plus the collector's
        # own detail, **not** `not_found` -- and the seeder got that wrong first.
        # `VulnerabilityPass` reads the detail to tell "we looked and this package has
        # no advisory" from "we could not establish anything", because the two look
        # identical in the state column and only one of them is reassuring. The
        # constant is imported from the collector rather than retyped: the pass
        # matches on its exact prefix, so a copy that drifted would silently turn
        # every clean package `unknown`.
        VulnerabilityFinding.objects.create(
            package=package,
            observed_at=observed_at,
            state=OutcomeState.UNKNOWN.value,
            source="https://api.osv.dev/v1/query",
            detail=NOTHING_MATCHED_DETAIL,
        )
        return

    advisory_id, severity, affected_range = demo.advisory
    finding = VulnerabilityFinding.objects.create(
        package=package,
        observed_at=observed_at,
        state=MATCHED,
        source=f"https://osv.dev/vulnerability/{advisory_id}",
        advisory_id=advisory_id,
        severity=severity,
        affected_range=affected_range,
        matched_version=demo.installed_version,
        match_confidence=MatchConfidence.EXACT_VERSION,
    )
    KevFinding.objects.create(
        package=package,
        vulnerability_finding=finding,
        observed_at=observed_at,
        state=LISTED if demo.kev_listed else NOT_LISTED,
        source="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        catalog_date_added=observed_at - timedelta(days=30) if demo.kev_listed else None,
    )


def _seed_licence(demo: DemoPackage, package: Package, *, observed_at: datetime) -> None:
    """Record what the artifact's metadata declared as its licence.

    Args:
        demo: What the source should have said.
        package: The package.
        observed_at: When it said it.

    """
    from conda_sentinel.collectors.models import LicenseFinding  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.core.outcomes import OutcomeState  # noqa: PLC0415 - as above

    if not demo.licence:
        LicenseFinding.objects.create(
            package=package,
            observed_at=observed_at,
            state=OutcomeState.NOT_FOUND.value,
            source=f"https://conda.anaconda.org/conda-forge/{demo.name}",
            channel="conda-forge",
        )
        return

    LicenseFinding.objects.create(
        package=package,
        observed_at=observed_at,
        # `normalized`, not `ok`: every evidence vocabulary composes `core`'s four
        # sentinels with its *own* determinate members, and this table's is named for
        # what it did -- it read a licence and normalised it.
        state=_NORMALIZED,
        source=f"https://conda.anaconda.org/conda-forge/{demo.name}",
        channel="conda-forge",
        raw_license=demo.licence,
        normalized_license=demo.licence,
        # One of the three the column declares. `spdx-identifier` is what a
        # single well-known identifier is recognised as; the compound expression
        # below is what `spdx-expression` is for.
        detection_method="spdx-expression" if " OR " in demo.licence else "spdx-identifier",
    )


def _seed_python(demo: DemoPackage, package: Package, *, observed_at: datetime) -> None:
    """Record how the Python 3.14 question was answered for this package.

    Args:
        demo: What the sources should have said.
        package: The package.
        observed_at: When they said it.

    """
    from conda_sentinel.collectors.models import PythonReadinessAssessment  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.collectors.models import PythonVerificationResult  # noqa: PLC0415 - as above
    from conda_sentinel.collectors.outcomes import VERIFIED_COMPATIBLE  # noqa: PLC0415 - as above
    from conda_sentinel.core.outcomes import OutcomeState  # noqa: PLC0415 - as above

    series = "3.14"
    if demo.python_evidence == "none":
        # A native library: the question does not apply, and the row has to say why.
        PythonReadinessAssessment.objects.create(
            package=package,
            observed_at=observed_at,
            state=OutcomeState.NOT_APPLICABLE.value,
            python_series=series,
            source=f"https://pypi.org/project/{demo.name}/",
            detail="native library; no Python metadata to assess",
        )
        return

    PythonReadinessAssessment.objects.create(
        package=package,
        observed_at=observed_at,
        state=_INFERRED_COMPATIBLE,
        python_series=series,
        source=f"https://pypi.org/project/{demo.name}/",
        requires_python=">=3.9",
        matching_classifier="Programming Language :: Python :: 3.14",
        deciding_signal="classifier",
    )
    if demo.python_evidence == "build":
        PythonVerificationResult.objects.create(
            package=package,
            observed_at=observed_at,
            state=VERIFIED_COMPATIBLE,
            python_series=series,
            source=DEMO_COLLECTOR,
            platform="linux-64",
            architecture="x86_64",
            log_reference=f"demo://builds/{demo.name}/{series}/linux-64",
        )


def _run_policy(*, observed_at: datetime, clock: object) -> dict[str, object]:
    """Record a finished collection run and execute one real policy run over it.

    The step that makes the seeded screens honest: every status they show is
    concluded here, by the passes that own it, from the parameter file that ships.

    Args:
        observed_at: The instant the seeded evidence was observed at, which becomes
            the collection run's `finished_at` and therefore the policy run's
            evidence cut-off.
        clock: The injected clock (`CPM-AD-26`).

    Returns:
        What the run concluded and what the shipped parameters left unconfigured.

    """
    from conda_sentinel.core.ledger import collection_run  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.core.policy_run import execute_policy_run  # noqa: PLC0415 - as above
    from conda_sentinel.policies.parameters import parameters_file  # noqa: PLC0415 - as above

    # Through the ledger's own writer rather than an insert. Two reasons: it opens
    # the run before the work and finalises it after, which is the shape a real
    # collector's run has and therefore the shape the coverage screen reads; and it
    # keeps the `status=` write inside `core/ledger.py`, which is the module
    # `tests/unit/django_apps/test_derived_status_writability_audit.py` records as
    # owning one. A seeder that inserted the row itself would need an exemption in
    # that table, which is a heavy thing to spend on a fixture.
    with collection_run(collector=DEMO_COLLECTOR, clock=clock) as handle:  # type: ignore[arg-type]
        handle.succeeded()
    version = _shipped_policy_version()
    summary = execute_policy_run(policy_version=version, clock=clock)  # type: ignore[arg-type]
    return {
        "policy_version": version,
        "rollup_rows": summary.rollup_rows,
        "parameters_file": str(parameters_file()),
        "unconfigured": (
            "priority_rules and license_rules are empty in the shipped parameter file, so every priority "
            "bucket comes out unknown and every licence manual_review. Both files say why; the values are "
            "PRD Open Questions 8 and 4. Record a rule set at a new version to see those columns work."
        ),
    }


def _shipped_policy_version() -> str:
    """Return the newest policy version the shipped parameter file records.

    Read rather than written down: an unrecorded version fails every package
    (`CPM-CURRENCY-S07`), so a constant here would break the seeder on the day
    somebody added a version and not before.

    Returns:
        The newest recorded version.

    Raises:
        ImproperlyConfigured: The shipped file records none, which would make every
            seeded package fail for a reason that has nothing to do with the demo.

    """
    from conda_sentinel.policies.parameters import parameters_file  # noqa: PLC0415 - after django.setup()
    from conda_sentinel.policies.parameters import parameters_from  # noqa: PLC0415 - as above

    source = parameters_file()
    versions = sorted(parameters_from(source.read_text(encoding="utf-8"), source=source))
    if not versions:
        message = "the shipped policy parameter file records no version, so no policy run can complete."
        raise ImproperlyConfigured(message)
    return versions[-1]
