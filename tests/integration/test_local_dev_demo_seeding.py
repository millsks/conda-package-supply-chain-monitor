"""What the demo seeder actually produces, against a real database and a real run.

The claim `config/local_dev/demo_data.py` makes about itself is that **nothing it
shows is fabricated**: it writes evidence and lets the policy engine conclude. That
claim is only worth as much as a test of it, because the shortcut it refuses -- insert
rows into `package_health` directly -- produces prettier screens faster and would pass
any test that only checked the screens were populated.

So the cases below check the *provenance* of what appears: every rollup row belongs to
the run this seeder executed, every derived status has a pass's row behind it, and the
identity of the unmapped package was never promoted rather than written unmapped.

**The variety cases are the second half.** A demo whose ten rows all read the same
demonstrates nothing about a design built to distinguish five states, so the seeded
inventory is asserted to produce genuinely different verdicts -- and, specifically, to
produce the three that a happy-path fixture never does.

Every test rolls back: `@pytest.mark.django_db` wraps each in a transaction.
"""

from __future__ import annotations

from typing import Final

import pytest

from conda_sentinel.core.models import CollectionRun
from conda_sentinel.core.models import PackageHealth
from conda_sentinel.core.models import PolicyRun
from conda_sentinel.core.outcomes import OutcomeState
from conda_sentinel.identity.models import IdentityConfidence
from conda_sentinel.identity.models import Package
from conda_sentinel.policies.models import PackageVulnerability
from config.local_dev.demo_data import DEMO_COLLECTOR
from config.local_dev.demo_data import DEMO_PACKAGES
from config.local_dev.demo_data import seed_demo_inventory
from config.locality import RUNTIME_ENV_VAR

pytestmark = pytest.mark.integration

#: The package the roster leaves unresolved, so `CPM-AD-4`'s gate has something to do.
THE_UNMAPPED_PACKAGE: Final[str] = "internal-telemetry-sdk"

#: Every package the roster leaves unresolved.
#:
#: Read off the declarations rather than listed here: the roster is a hundred rows and
#: a hand-written list of the unmapped ones would be a second place to remember. What
#: is asserted below is that there *are* some and that everything else was resolved,
#: which is the pairing that matters -- a seeder that resolved nothing would satisfy
#: the gate case above on its own.
THE_UNMAPPED_PACKAGES: Final[frozenset[str]] = frozenset(demo.name for demo in DEMO_PACKAGES if not demo.identified)

#: How many distinct vulnerability verdicts the seeded inventory should produce.
#:
#: Three: an advisory matched, a lookup that matched nothing, and one that could not
#: establish anything. A demo producing fewer would render a column that looks like it
#: has one value.
DISTINCT_VULNERABILITY_VERDICTS: Final[int] = 3


@pytest.fixture
def seeded() -> dict[str, object]:
    """Seed the demo inventory once for a case to read.

    Returns:
        What the seeder reported.

    """
    return seed_demo_inventory()


@pytest.mark.django_db
def test_every_declared_package_reaches_the_rollup(seeded: dict[str, object]) -> None:
    """`CPM-AD-11`: one row per package, and the seeder gets all of them there.

    Args:
        seeded: What the seeder reported.

    """
    assert Package.objects.count() == len(DEMO_PACKAGES)
    assert PackageHealth.objects.count() == len(DEMO_PACKAGES)
    assert seeded["rollup_rows"] == len(DEMO_PACKAGES)


@pytest.mark.django_db
def test_every_rollup_row_belongs_to_the_run_the_seeder_executed(seeded: dict[str, object]) -> None:
    """The provenance claim, and the case the shortcut would fail.

    A seeder that wrote `package_health` directly would produce rows with no run, or
    with a run nothing executed. Every row here names the one policy run this seeding
    performed -- which is what makes the screens a picture of the engine's output
    rather than of the fixture's intent.

    Args:
        seeded: What the seeder reported.

    """
    run = PolicyRun.objects.get(policy_version=seeded["policy_version"])

    assert run.finished_at is not None
    assert set(PackageHealth.objects.values_list("policy_run_id", flat=True)) == {run.pk}


@pytest.mark.django_db
def test_every_status_has_a_pass_row_behind_it(seeded: dict[str, object]) -> None:
    """A rollup status with no derived row behind it would be a fabricated verdict.

    `CPM-AD-21` writes one derived row per package per run, so a package with a
    vulnerability status and no `package_vulnerability` row would mean the value came
    from somewhere other than the pass.

    Args:
        seeded: What the seeder reported.

    """
    run = PolicyRun.objects.get(policy_version=seeded["policy_version"])

    assert PackageVulnerability.objects.filter(policy_run=run).count() == len(DEMO_PACKAGES)


@pytest.mark.django_db
def test_the_unmapped_package_was_never_promoted(seeded: dict[str, object]) -> None:
    """It is unmapped because resolution never established it, not because a field says so.

    `CPM-AD-14` gives identity one write path and `CPM-AD-25` gives creation to
    `resolve_package_shell`, which creates at `unmapped`. The demo's unresolved
    package is simply never carried further -- so it is a *real* instance of the state
    the identity queue exists for, and the gate below is the gate doing its job rather
    than a fixture imitating it.

    Args:
        seeded: What the seeder reported.

    """
    package = Package.objects.get(canonical_name=THE_UNMAPPED_PACKAGE)
    row = PackageHealth.objects.get(package=package)

    assert package.confidence == IdentityConfidence.UNMAPPED
    assert row.confidence == IdentityConfidence.UNMAPPED
    assert row.currency_status == OutcomeState.UNKNOWN.value
    assert row.feedstock_presence_status == OutcomeState.UNKNOWN.value


@pytest.mark.django_db
def test_the_identified_packages_really_were_identified(seeded: dict[str, object]) -> None:
    """The other side: resolution ran and established them, so the gate lets them through.

    Without this the case above would pass on a seeder that resolved nothing at all.

    Args:
        seeded: What the seeder reported.

    """
    identified = Package.objects.exclude(canonical_name__in=THE_UNMAPPED_PACKAGES)

    assert THE_UNMAPPED_PACKAGES, "the roster resolves everything, so the gate case above proves nothing"
    assert identified.count() == len(DEMO_PACKAGES) - len(THE_UNMAPPED_PACKAGES)
    assert set(identified.values_list("confidence", flat=True)) == {IdentityConfidence.VERIFIED}


@pytest.mark.django_db
def test_the_seeded_run_is_filed_under_a_collector_that_is_not_registered(seeded: dict[str, object]) -> None:
    """So the coverage screen is not told a real collector is healthy.

    Args:
        seeded: What the seeder reported.

    """
    assert set(CollectionRun.objects.values_list("collector", flat=True)) == {DEMO_COLLECTOR}


# ---------------------------------------------------------------------------
# The variety, which is what the demo is for.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_inventory_produces_more_than_one_currency_verdict(seeded: dict[str, object]) -> None:
    """Ten rows reading the same thing demonstrate nothing about a design built to differ.

    Args:
        seeded: What the seeder reported.

    """
    verdicts = set(PackageHealth.objects.values_list("currency_status", flat=True))

    assert {"behind", "current"} <= verdicts


@pytest.mark.django_db
def test_the_inventory_produces_three_distinct_vulnerability_verdicts(seeded: dict[str, object]) -> None:
    """An advisory matched, a lookup that matched nothing, and one that established nothing.

    The third is the one a happy-path fixture never produces, and it is the state
    `CPM-FR-5` insists a reader can tell from the second.

    Args:
        seeded: What the seeder reported.

    """
    run = PolicyRun.objects.get(policy_version=seeded["policy_version"])
    verdicts = set(
        PackageVulnerability.objects.filter(policy_run=run).values_list("vulnerability_status", flat=True),
    )

    assert len(verdicts) >= DISTINCT_VULNERABILITY_VERDICTS, sorted(verdicts)
    assert "advisories_matched" in verdicts
    assert "no_advisory_matched" in verdicts


@pytest.mark.django_db
def test_the_kev_column_carries_a_listing_and_a_non_listing(seeded: dict[str, object]) -> None:
    """The KEV column qualifies the one beside it, so both values have to appear.

    Args:
        seeded: What the seeder reported.

    """
    run = PolicyRun.objects.get(policy_version=seeded["policy_version"])
    memberships = set(PackageVulnerability.objects.filter(policy_run=run).values_list("kev_membership", flat=True))

    assert {"listed", "not_listed"} <= memberships


@pytest.mark.django_db
def test_the_inventory_produces_more_than_one_work_type(seeded: dict[str, object]) -> None:
    """The column a queue is built from, so a demo where it is constant is a poor demo.

    Args:
        seeded: What the seeder reported.

    """
    assert len(set(PackageHealth.objects.values_list("work_type_status", flat=True))) > 1


@pytest.mark.django_db
def test_the_seeder_reports_what_the_version_it_ran_at_leaves_empty(seeded: dict[str, object]) -> None:
    """A column that comes out inert is explained, and the explanation is derived.

    It used to be a fixed sentence saying priority *and* licence were empty.
    Recording a priority rule set at a newer version made that sentence false the
    moment the seeder picked the newer version up -- a demo confidently explaining a
    state it was no longer in, which is worse than one that says nothing. So the
    report is read from the parameters the run actually applied, and this case checks
    it against the same source rather than against a remembered string.

    Args:
        seeded: What the seeder reported.

    """
    from conda_sentinel.policies.parameters import parameters_for  # noqa: PLC0415 - read beside the claim

    recorded = parameters_for(str(seeded["policy_version"]))
    reported = str(seeded["unconfigured"])

    assert ("license_rules" in reported) == (not recorded.license_rules)
    assert ("priority_rules" in reported) == (not recorded.priority_rules)


@pytest.mark.django_db
def test_the_demo_runs_at_a_version_that_records_priority_rules(seeded: dict[str, object]) -> None:
    """The precondition of the case below, asserted rather than skipped around.

    `tests/unit/test_suite_policy.py` bans `pytest.skip` in a test body, and is right
    to: a skipped case reads in a report as a gate that ran. So the precondition is
    its own assertion.

    **If the proposed rule set is withdrawn, this is the case to delete** -- together
    with the one below it. Both exist because the seeded demo currently runs at a
    version that records rules, which is what makes the ranking checkable at all.

    Args:
        seeded: What the seeder reported.

    """
    assert parameters_for_run(seeded), (
        f"the demo ran at {seeded['policy_version']}, which records no priority rules -- so the priority "
        f"column is inert and the ranking case below has nothing to check"
    )


@pytest.mark.django_db
def test_a_vulnerable_package_never_falls_through_to_the_backlog(seeded: dict[str, object]) -> None:
    """The hole the demo found in the proposed rule set, kept closed.

    Every priority rule that conditions on a *second* domain is implicitly a
    condition on that domain having reached a verdict, and every domain can be
    `unknown`. The first draft's vulnerability rules all named
    `remediation_readiness`, so a package with a critical advisory and no remediation
    verdict matched none of them and landed in "behind upstream".

    Whatever the rule set says, a package the product knows is vulnerable must not
    rank below one that is merely out of date.

    Args:
        seeded: What the seeder reported.

    """
    from conda_sentinel.policies.models import PackageVulnerability  # noqa: PLC0415 - read beside the claim
    from conda_sentinel.policies.outcomes import PRIORITY_BUCKETS  # noqa: PLC0415 - as above

    run_id = PackageHealth.objects.values_list("policy_run_id", flat=True).first()
    vulnerable = set(
        PackageVulnerability.objects.filter(
            policy_run_id=run_id,
            vulnerability_status="advisories_matched",
        ).values_list("package_id", flat=True),
    )
    assert vulnerable, "the demo seeded no vulnerable package, so this proves nothing"

    order = {bucket: rank for rank, bucket in enumerate(PRIORITY_BUCKETS)}
    worst_allowed = order["p3"]
    for row in PackageHealth.objects.filter(package_id__in=vulnerable):
        assert row.priority_status in order, row.priority_status
        assert order[row.priority_status] <= worst_allowed, (
            f"{row.package.canonical_name} is vulnerable and ranked {row.priority_status}"
        )


def parameters_for_run(seeded: dict[str, object]) -> tuple[object, ...]:
    """Return the priority rules the seeded run applied.

    Args:
        seeded: What the seeder reported.

    Returns:
        The recorded rules, empty when the version records none.

    """
    from conda_sentinel.policies.parameters import parameters_for  # noqa: PLC0415 - after django.setup()

    return tuple(parameters_for(str(seeded["policy_version"])).priority_rules)


@pytest.mark.django_db
def test_seeding_twice_appends_evidence_rather_than_replacing_it() -> None:
    """`CPM-AD-2`: a re-observation inserts, and the demo is honest about that.

    Which is useful rather than merely correct -- it is what gives the detail view's
    superseded-evidence list something to show.
    """
    seed_demo_inventory()
    first = PackageVulnerability.objects.count()
    from conda_sentinel.collectors.models import VulnerabilityFinding  # noqa: PLC0415 - read after the first run

    findings = VulnerabilityFinding.objects.count()

    seed_demo_inventory()

    assert Package.objects.count() == len(DEMO_PACKAGES), "a second run created packages rather than reusing them"
    assert VulnerabilityFinding.objects.count() > findings, "a second run replaced evidence rather than appending"
    assert PackageVulnerability.objects.count() > first, "the second policy run wrote no derived rows"


# ---------------------------------------------------------------------------
# The runnable form.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_entry_point_seeds_and_reports() -> None:
    """`python -m config.local_dev.seed_demo` is what the pixi task runs, and it runs.

    Called as a function rather than as a subprocess, on the terms
    `tests/integration/test_local_dev_seeding.py` sets for the persona seeder: a
    subprocess would resolve a different pixi environment and a different database,
    and what is worth pinning is that the module's `main` sets Django up and drives
    the same seeding the task promises.
    """
    from config.local_dev import seed_demo  # noqa: PLC0415 - imported here for the same reason `main` defers its own

    reported = seed_demo.main()

    assert reported["rollup_rows"] == len(DEMO_PACKAGES)
    assert PackageHealth.objects.count() == len(DEMO_PACKAGES)


@pytest.mark.django_db
def test_the_entry_point_adds_no_escape_hatch_around_the_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal is the seeding function's, and the entry point does not soften it.

    Args:
        monkeypatch: pytest's patcher, which restores the runtime variable.

    """
    from django.core.exceptions import ImproperlyConfigured  # noqa: PLC0415 - local to this case

    from config.local_dev import seed_demo  # noqa: PLC0415 - as above

    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")

    with pytest.raises(ImproperlyConfigured, match=r"append-only"):
        seed_demo.main()
