"""The fifteen forbidden states, named -- FR-16's index, not a second contract.

**This module names states. It does not decide them.** Every predicate lives
once, in `src/config/startup/` (AD-26, AD-1), and nothing here reads a setting,
resolves a route or evaluates a condition. What it holds is a stable identifier
per forbidden state, so that `tests/unit/startup/test_refusal_coverage_audit.py`
can reconcile "every state has a test that configures it and asserts the raise"
in both directions. The moment a record here starts carrying a predicate, the
contract has two copies and this file is the wrong one.

**Why the inherited count is fourteen and why that number is not re-derived.**
The planning sources are arithmetically inconsistent -- PRD §4.3 and FR-16 say
nine conditions, FR-13 says seven and lists eight bullets, and AD-27 adds a
stage-2 refusal that appears in no bullet at all. The settled reading, recorded
in the epic context and in the inherited platform's Story 1.5, is **nine conditions -- seven
unconditional and two feature-scoped -- across fourteen distinct forbidden
states**, applying FR-16's own rule that one condition may cover several states
each tested separately. Conditions 2, 5 and 6 are the three that do. Do not
re-open that arithmetic here; the audit asserts against this table.

**And why this product adds a tenth condition rather than folding into one.**
`CPM-EVIDENCE-S06` brings `CPM-AD-28`: a registered collector that declares no
freshness target refuses to start, because an unset target behaves as "fresh
forever" and six-month-old evidence then reads as current. It belongs to none of
the inherited nine -- those are about credential surfaces, telemetry, the trust
anchor, the claims contract, routed views and schema state -- so filing it under
one of them would make FR-16's "each of the conditions has at least one test that
configures the forbidden state" a sentence about a condition that now covers two
unrelated rules. It is condition 10, unconditional and stage 2, and the settled
count for *this repository* is therefore **ten conditions across fifteen
states**: the inherited fourteen plus one.

**Two of the fifteen are feature-scoped and leave with their features.** States
8 and 9 are Redis's and Celery's, so their records sit inside AD-24 marker pairs
exactly as the conditions themselves do in `src/config/startup/stage_one.py`: a
combination materialized without Redis has no `_refuse_in_process_cache` and must
not carry a declaration demanding a test for it. The `feature` field on each
record says the same thing to a reader; the markers are what say it to the
materializer, and only the markers are a removal mechanism.

**FR-12's escape route is declared separately, on purpose.** A deployed component
that loaded `config.settings.local` is the failure the whole contract is built
around, but it is not one of the nine numbered conditions -- so it gets its own
record outside `FORBIDDEN_STATES`, asserted by its own case in the audit. Folded
into the tuple it would be tradeable against the rest: drop it, add one more, and
a count-based check would still pass.

Not a test module. `tests/coverage_policy.py` and `tests/factories.py` are the
existing precedent for a helper that lives under `tests/` and is imported rather
than collected -- `[tool.pytest.ini_options] python_files` matches `test_*.py`
and `tests.py`, so pytest collects nothing from this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "DELEGATED_TO_THE_INTEGRATION_SUITE",
    "ESCAPE_ROUTE_STATE",
    "FORBIDDEN_STATES",
    "ForbiddenState",
]


@dataclass(frozen=True, slots=True)
class ForbiddenState:
    """One forbidden state of the refusal contract, named rather than defined.

    Attributes:
        state_id: The stable identifier a test claims with
            `@pytest.mark.forbidden_state(...)`. Renaming one is a two-sided
            change: the audit fails on the unclaimed state *and* on the claim
            naming a state nothing declares.
        condition: Which of the nine numbered conditions this state belongs to.
            Zero for FR-12's escape route, which is outside the nine.
        stage: 1 for the checks that evaluate at settings import, 2 for the ones
            that evaluate at serving-process startup.
        description: What the state is, in one line, in the words the refusal
            table uses.
        feature: The AD-24 feature that owns this state, or None for the twelve
            that every combination carries.

    """

    state_id: str
    condition: int
    stage: int
    description: str
    feature: str | None = None


#: The fifteen. Ordered by condition and, within a condition, by the order the
#: states are listed in the refusal table -- which is also the order
#: `src/config/startup/stage_one.py` and `stage_two.py` evaluate them in, so a
#: reader following a refusal back from a log line meets them here in the same
#: sequence.
FORBIDDEN_STATES: Final[tuple[ForbiddenState, ...]] = (
    ForbiddenState(
        state_id="sqlite-backend",
        condition=1,
        stage=1,
        description="a configured database alias resolves to the sqlite backend",
    ),
    ForbiddenState(
        state_id="model-backend-installed",
        condition=2,
        stage=1,
        description="django.contrib.auth.backends.ModelBackend is in AUTHENTICATION_BACKENDS",
    ),
    ForbiddenState(
        state_id="account-login-methods-declared",
        condition=2,
        stage=1,
        description="ACCOUNT_LOGIN_METHODS is non-empty, so allauth serves a local login",
    ),
    ForbiddenState(
        state_id="admin-not-forced-through-allauth",
        condition=2,
        stage=1,
        description="DJANGO_ADMIN_FORCE_ALLAUTH is not True, so the admin keeps its own login form",
    ),
    ForbiddenState(
        state_id="static-token-surface",
        condition=2,
        stage=1,
        description="rest_framework.authtoken is installed or TokenAuthentication is a DRF default",
    ),
    ForbiddenState(
        state_id="otel-sdk-disabled",
        condition=3,
        stage=1,
        description="OTEL_SDK_DISABLED is set, so a deployed component has opted out of tracing",
    ),
    ForbiddenState(
        state_id="untrusted-jwks-anchor",
        condition=4,
        stage=1,
        description="the JWKS location is not derived from the configured IdP issuer",
    ),
    ForbiddenState(
        state_id="unconfigured-claims-contract",
        condition=5,
        stage=1,
        description="the claims contract is missing an identity key, group claim or designated group",
    ),
    ForbiddenState(
        state_id="designated-group-absent",
        condition=5,
        stage=2,
        description="a designated group named by the claims contract is absent from the database (AD-27)",
    ),
    ForbiddenState(
        state_id="credential-minting-route",
        condition=6,
        stage=2,
        description="a route in the resolved URLconf reaches DRF's token-minting view",
    ),
    ForbiddenState(
        state_id="local-sign-in-route",
        condition=6,
        stage=2,
        description="a route in the resolved URLconf reaches the local persona sign-in module",
    ),
    ForbiddenState(
        state_id="unapplied-migrations",
        condition=7,
        stage=2,
        description="a serving process would start against a schema with migrations pending",
    ),
    ForbiddenState(
        state_id="collector-without-freshness-target",
        condition=10,
        stage=2,
        description="a registered collector declares no freshness target, so its evidence never goes stale",
    ),
    # feature:redis
    ForbiddenState(
        state_id="in-process-cache-backend",
        condition=8,
        stage=1,
        description="a configured cache alias resolves to an in-process backend where Redis was selected",
        feature="redis",
    ),
    # /feature:redis
    # feature:celery
    ForbiddenState(
        state_id="eager-task-execution",
        condition=9,
        stage=1,
        description="CELERY_TASK_ALWAYS_EAGER is enabled where background task processing was selected",
        feature="celery",
    ),
    # /feature:celery
)

#: FR-12's escape route, outside the fourteen and asserted on its own.
#:
#: Condition zero because it is not one of the nine: it says *the wrong settings
#: module loaded*, which is the reason `src/config/startup/` sits outside the
#: settings package at all. A guard placed behind the door it guards cannot fire,
#: so this one is evaluated first in the stage-1 roster and claimed first here.
ESCAPE_ROUTE_STATE: Final = ForbiddenState(
    state_id="local-settings-module-loaded",
    condition=0,
    stage=1,
    description="a deployed component imported config.settings.local (FR-12)",
)

#: The states whose CG-3 measurements cannot be made without a live connection,
#: and are therefore made in `tests/integration/startup/test_stage_two_served_path.py`
#: rather than in `tests/unit/startup/test_no_softening.py`.
#:
#: **Declared here rather than in either of those two modules, because both read
#: it.** The unit module reconciles it against its own builder table -- every
#: declared state is either built there or delegated, never both and never
#: neither -- and the integration module *parametrizes its own cases from it*, so
#: a state named here with no case there fails. That second direction is the
#: whole reason this is not a comment: while the set lived in the unit module it
#: was a one-way bookkeeping check, and a delegated state with no delegate test
#: passed both halves of a reconciliation that only ever compared two lists.
#:
#: A test module importing another test module is the cross-import
#: `tests/integration/startup/conftest.py` exists to prevent, so the shared
#: constant lives in this uncollected declaration module with the states it
#: names.
DELEGATED_TO_THE_INTEGRATION_SUITE: Final[frozenset[str]] = frozenset(
    {"unapplied-migrations", "designated-group-absent"},
)
