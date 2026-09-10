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

**What it cannot show you, it says rather than leaves you to infer.** A parameter
the shipped file records as empty makes the column it drives inert whatever evidence
is behind it -- `license_rules = []` is one today, and `priority_rules` was until
`2026.09.4` recorded ten. So the sentence `SEEDED_EVENT` carries is *read from the
parameters at the version the run applied*, never written here: a fixed sentence
became false the moment a rule set was recorded, and a demo confidently explaining a
state it is no longer in is worse than a demo that explains nothing. See
`_unconfigured_at`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Final

import structlog
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from config.locality import is_local

if TYPE_CHECKING:
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

#: The SPDX operators that make a licence string an *expression* rather than an
#: identifier. `WITH` counts: `GPL-2.0-only WITH Classpath-exception-2.0` is one
#: expression, not one identifier, and the column's three values distinguish them.
_COMPOUND: Final[re.Pattern[str]] = re.compile(r"\s(?:OR|AND|WITH)\s")

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
_INFERRED_INCOMPATIBLE: Final[str] = "inferred_incompatible"

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

    #: The date CISA's catalogue states it added the advisory, as `YYYY-MM-DD`.
    #:
    #: Read off the catalogue rather than computed from the run, because the whole
    #: reason a KEV listing is worth showing is that it is checkable: a date derived
    #: from "thirty days before you ran the seeder" moves every time somebody reruns
    #: it and matches nothing anybody can look up. Blank on a listing that states no
    #: date -- which `kev_findings` treats as missing, not as absent.
    kev_catalogued: str = ""

    #: The licence the artifact declares, if the licence lookup found one.
    licence: str = ""

    #: Whether a conda-forge feedstock exists, and when it last saw a commit.
    feedstock: bool = True
    feedstock_idle_days: int = 3

    #: How far along the packaging chain the advisory's fix has actually got:
    #: `"release"` (the upstream source and PyPI have it), `"recipe"` (the feedstock
    #: recipe has been updated too) or `"channel"` (conda-forge publishes it).
    #:
    #: **Still an observation, not a verdict.** It sets which snapshot carries the
    #: fixed version and nothing else; `policies/remediation.py` decides what that
    #: means, and the four `..._fix` columns on its row are how it says which surface
    #: it read. Only meaningful on a package carrying an advisory.
    #:
    #: It exists because a roster where the fix had reached exactly one surface made
    #: three of the shipped priority rules unreachable -- every vulnerable package
    #: landed in the same bucket, and a screen whose whole job is to separate "act
    #: today" from "wait for a build" showed one value.
    fix_reached: str = "release"

    #: How the Python 3.14 question was answered: `"build"` for a verification that
    #: ran, `"metadata"` for a static assessment that came out compatible,
    #: `"metadata-incompatible"` for one that came out the other way, `"build-failed"`
    #: for a verification that ran and did not work, `"none"` for neither.
    #:
    #: The two negative kinds are here because a demo without them showed the
    #: readiness column in one tone: `CPM-FR-24`'s whole point is telling a package
    #: that is ready from one that is not, and every seeded package being ready made
    #: two of the shipped priority rules unreachable as well.
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
#: **A hundred packages, and the number is the point.** The roster used to hold ten,
#: which was enough to put every tone the stylesheet draws on one screen and not
#: nearly enough to judge one: ten rows fit above the fold, sort instantly, paginate
#: never, and make a queue that holds two items look like a queue. A reviewer asking
#: "is this screen usable" was being shown a screen that could not be unusable.
#:
#: **A mixture, on the product owner's terms**: web frameworks, data science, and the
#: ordinary utilities every environment carries -- well known and less so, and seven
#: things conda-forge ships that are not Python at all, which is where
#: `not_applicable` comes from rather than from a contrivance.
#:
#: Every state `CPM-FR-5` insists a reader can tell apart is still here, and now more
#: than one row is in each: clean packages, packages behind their upstream, adverse
#: verdicts, lookups that found nothing, a question that does not apply, lookups that
#: broke, and two packages the confidence gate blanks entirely.
#:
#: ### What is real here and what is not
#:
#: **The advisories are real.** Every `advisory=` below carries an identifier, a
#: severity and an affected range taken from **OSV.dev**, and the one KEV listing is a
#: real entry in **CISA's Known Exploited Vulnerabilities catalogue** with the date
#: the catalogue states. They were harvested rather than invented, at the product
#: owner's direction and against this module's first draft, which used names like
#: `GHSA-demo-high`. A reader who does not believe a row can look the identifier up,
#: which is the whole difference: a fictional advisory teaches a reviewer to stop
#: checking.
#:
#: Note what the KEV column then looks like: **one row out of twenty-eight**. That is
#: not a thin demo, it is the truth about that catalogue -- it lists software known to
#: be exploited in the wild, and almost nothing on PyPI is in it. The row that is
#: listed is `git`, which conda-forge ships and CISA catalogued on 2025-08-25.
#:
#: **Everything around them is a fixture.** No collector ran, no build was performed,
#: no feedstock was read, and the installed and upstream versions are plausible rather
#: than observed -- except on a package carrying an advisory, where the affected range
#: and the fixed version are the advisory's own and the installed version is a real
#: release inside that range. `internal-telemetry-sdk` and `internal-feature-flags`
#: are not packages at all.
#:
#: ### Reading the table
#:
#: The first three arguments are positional and they are a table: **name, upstream,
#: installed** -- upstream first because that is the column a currency verdict is
#: measured against. A hundred rows only stay readable as one line each, and one line
#: each is what makes "which of these is behind" a thing a reviewer can see rather
#: than compute.
#:
#: The order is the risk, and it is the risk positional arguments always carry:
#: swapping the pair inverts a package's currency verdict silently.
#: `test_local_dev_demo_data.py` compares every parsable pair and fails on an
#: inversion, which is the guard that makes the shape safe rather than merely
#: shorter.
DEMO_PACKAGES: Final[tuple[DemoPackage, ...]] = (
    # --- Carrying a real advisory ------------------------------------------------
    DemoPackage(
        "django",
        "6.0.7",
        "6.0.0",
        advisory=("CVE-2026-48588", "low", ">=6.0.0,<6.0.7"),
        licence="BSD-3-Clause",
        python_evidence="build",
        fix_reached="channel",
    ),
    DemoPackage(
        "aiohttp",
        "3.10.11",
        "3.10.6",
        advisory=("CVE-2024-52303", "moderate", ">=3.10.6,<3.10.11"),
        licence="Apache-2.0",
        fix_reached="recipe",
    ),
    DemoPackage(
        "jinja2",
        "3.1.5",
        "3.0.0",
        advisory=("CVE-2024-56201", "moderate", ">=3.0.0,<3.1.5"),
        licence="BSD-3-Clause",
        fix_reached="recipe",
    ),
    DemoPackage(
        "werkzeug",
        "3.0.1",
        "3.0.0",
        advisory=("CVE-2023-46136", "moderate", ">=3.0.0,<3.0.1"),
        licence="BSD-3-Clause",
        fix_reached="channel",
    ),
    DemoPackage(
        "urllib3",
        "2.7.0",
        "2.6.0",
        advisory=("CVE-2026-44432", "high", ">=2.6.0,<2.7.0"),
        licence="MIT",
        python_evidence="build",
        fix_reached="recipe",
    ),
    DemoPackage(
        "cryptography",
        "49.0.0",
        "45.0.0",
        advisory=("CVE-2026-69248", "moderate", ">=45.0.0,<49.0.0"),
        licence="Apache-2.0 OR BSD-3-Clause",
        python_evidence="build",
    ),
    DemoPackage(
        "paramiko",
        "3.4.0",
        "2.5.0",
        advisory=("CVE-2023-48795", "moderate", ">=2.5.0,<3.4.0"),
        licence="LGPL-2.1-or-later",
    ),
    DemoPackage(
        "pyjwt",
        "2.13.0",
        "2.8.0",
        advisory=("CVE-2026-48525", "moderate", ">=2.8.0,<2.13.0"),
        licence="MIT",
        fix_reached="recipe",
    ),
    DemoPackage(
        "authlib",
        "1.7.1",
        "1.7.0",
        advisory=("CVE-2026-41479", "moderate", ">=1.7.0,<1.7.1"),
        licence="BSD-3-Clause",
        fix_reached="channel",
    ),
    DemoPackage(
        "waitress", "3.0.1", "2.0.0", advisory=("CVE-2024-49768", "critical", ">=2.0.0,<3.0.1"), licence="ZPL-2.1"
    ),
    DemoPackage(
        "starlette", "1.3.1", "0.41.3", advisory=("CVE-2026-54283", "high", ">=0.4.1,<1.3.1"), licence="BSD-3-Clause"
    ),
    DemoPackage(
        "litestar",
        "2.20.0",
        "2.19.0",
        advisory=("CVE-2026-25480", "moderate", ">=2.19.0,<2.20.0"),
        licence="MIT",
        fix_reached="channel",
    ),
    DemoPackage(
        "tornado",
        "6.5.8",
        "6.5.5",
        advisory=("GHSA-wwv5-g3v4-889x", "low", ">=6.5.5,<6.5.8"),
        licence="Apache-2.0",
        fix_reached="recipe",
    ),
    DemoPackage(
        "scrapy",
        "2.14.2",
        "2.11.2",
        advisory=("GHSA-cwxj-rr6w-m6w7", "high", ">=1.4.0,<2.14.2"),
        licence="BSD-3-Clause",
    ),
    DemoPackage(
        "flask",
        "3.1.1",
        "3.1.0",
        advisory=("CVE-2025-47278", "low", ">=3.1.0,<3.1.1"),
        licence="BSD-3-Clause",
        python_evidence="build",
        fix_reached="channel",
    ),
    DemoPackage("pyyaml", "5.2", "5.1", advisory=("CVE-2019-20477", "critical", ">=5.1,<5.2"), licence="MIT"),
    DemoPackage(
        "wheel",
        "0.46.2",
        "0.40.0",
        advisory=("CVE-2026-24049", "high", ">=0.40.0,<0.46.2"),
        licence="MIT",
        fix_reached="recipe",
    ),
    DemoPackage("black", "26.3.1", "24.3.0", advisory=("CVE-2026-32274", "high", ">=24.3.0,<26.3.1"), licence="MIT"),
    DemoPackage(
        "pyarrow",
        "23.0.1",
        "15.0.0",
        advisory=("CVE-2026-25087", "high", ">=15.0.0,<23.0.1"),
        licence="Apache-2.0",
        python_evidence="build",
        feedstock_idle_days=210,
    ),
    DemoPackage(
        "pillow",
        "12.3.0",
        "11.3.0",
        advisory=("CVE-2026-59204", "high", ">=8.2.0,<12.3.0"),
        licence="MIT-CMU",
        python_evidence="build",
    ),
    DemoPackage(
        "jupyterlab",
        "4.6.2",
        "4.6.0",
        advisory=("CVE-2026-73417", "high", ">=4.6.0,<4.6.2"),
        licence="BSD-3-Clause",
        fix_reached="channel",
    ),
    DemoPackage(
        "notebook", "7.5.6", "7.0.0", advisory=("CVE-2026-42557", "high", ">=7.0.0,<7.5.6"), licence="BSD-3-Clause"
    ),
    DemoPackage(
        "transformers",
        "4.51.0",
        "4.49.0",
        advisory=("CVE-2025-3262", "moderate", ">=4.49.0,<4.51.0"),
        licence="Apache-2.0",
    ),
    DemoPackage(
        "keras", "3.15.0", "3.13.0", advisory=("CVE-2026-9335", "moderate", ">=3.13.0,<3.15.0"), licence="Apache-2.0"
    ),
    DemoPackage("lightgbm", "4.6.0", "4.5.0", advisory=("CVE-2024-43598", "high", ">=1.0.0,<4.6.0"), licence="MIT"),
    DemoPackage(
        "grpcio",
        "1.55.3",
        "1.55.0",
        advisory=("CVE-2023-4785", "high", ">=1.55.0,<1.55.3"),
        licence="Apache-2.0",
        python_evidence="build",
        fix_reached="recipe",
    ),
    DemoPackage(
        "pydantic",
        "2.4.0",
        "2.0.0",
        advisory=("CVE-2024-3772", "moderate", ">=2.0.0,<2.4.0"),
        licence="MIT",
        python_evidence="build",
    ),
    DemoPackage(
        "git",
        "2.50.1",
        "2.49.0",
        advisory=("CVE-2025-48384", "high", ">=0,<2.50.1"),
        kev_listed=True,
        kev_catalogued="2025-08-25",
        licence="GPL-2.0-only",
        python_evidence="none",
    ),
    # --- Web frameworks and the stack around them --------------------------------
    DemoPackage("fastapi", "0.121.4", "0.121.4", licence="MIT", python_evidence="build"),
    DemoPackage("uvicorn", "0.38.0", "0.38.0", licence="BSD-3-Clause"),
    DemoPackage("gunicorn", "23.0.0", "23.0.0", licence="MIT"),
    DemoPackage("httpx", "0.29.0", "0.29.0", licence="BSD-3-Clause"),
    DemoPackage("requests", "2.32.5", "2.32.3", licence="Apache-2.0", python_evidence="build"),
    DemoPackage("bottle", "0.13.4", "0.13.4", licence="MIT"),
    DemoPackage("falcon", "4.1.0", "4.1.0", licence="Apache-2.0"),
    DemoPackage(
        "pyramid", "2.0.2", "2.0.0", licence="ZPL-2.1", feedstock_idle_days=320, python_evidence="metadata-incompatible"
    ),
    DemoPackage("quart", "0.20.0", "0.20.0"),
    DemoPackage("hypercorn", "0.17.3", "0.17.3"),
    DemoPackage("sanic", "25.3.0", "24.12.0", licence="MIT"),
    DemoPackage("twisted", "25.5.0", "24.11.0", licence="MIT"),
    DemoPackage("wtforms", "3.2.1", "3.1.2", feedstock_idle_days=240, python_evidence="metadata-incompatible"),
    DemoPackage("flask-cors", "6.0.1", "6.0.1", licence="MIT", feedstock=False),
    # --- Data science -------------------------------------------------------------
    DemoPackage("numpy", "2.3.4", "2.2.6", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("scipy", "1.16.2", "1.15.2", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("pandas", "2.3.3", "2.2.3", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("scikit-learn", "1.7.2", "1.6.1", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("matplotlib", "3.10.6", "3.10.6", licence="PSF-2.0", python_evidence="build"),
    DemoPackage("statsmodels", "0.14.5", "0.14.5", licence="BSD-3-Clause"),
    DemoPackage("xarray", "2025.9.0", "2025.9.0", licence="Apache-2.0"),
    DemoPackage("dask", "2025.9.1", "2025.9.1", licence="BSD-3-Clause"),
    DemoPackage("polars", "1.34.0", "1.34.0", licence="MIT", python_evidence="build"),
    DemoPackage("h5py", "3.14.0", "3.14.0", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("numba", "0.62.1", "0.62.1", licence="BSD-2-Clause", python_evidence="build"),
    DemoPackage("ipython", "9.6.0", "8.32.0", licence="BSD-3-Clause"),
    DemoPackage("plotly", "6.3.0", "6.3.0", licence="MIT"),
    DemoPackage("bokeh", "3.8.0", "3.8.0", licence="BSD-3-Clause"),
    DemoPackage("pytorch", "2.9.0", "2.6.0", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("nltk", "3.9.2", "3.9.2", licence="Apache-2.0"),
    DemoPackage("spacy", "3.8.7", "3.8.7", licence="MIT", errored=("advisory",)),
    DemoPackage("gensim", "4.3.3", "4.3.2", feedstock_idle_days=400, python_evidence="metadata-incompatible"),
    DemoPackage("scikit-image", "0.25.2", "0.25.2", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("shap", "0.48.0", "0.48.0", licence="MIT", feedstock=False, python_evidence="build-failed"),
    DemoPackage("patsy", "1.0.2", "1.0.1", feedstock_idle_days=280, python_evidence="metadata-incompatible"),
    DemoPackage("datashader", "0.18.1", "0.18.1", python_evidence="metadata-incompatible"),
    DemoPackage("umap-learn", "0.5.9", "0.5.9", python_evidence="build-failed"),
    DemoPackage(
        "hdbscan", "0.8.40", "0.8.40", feedstock=False, feedstock_idle_days=500, python_evidence="metadata-incompatible"
    ),
    DemoPackage("imbalanced-learn", "0.14.0", "0.14.0", licence="MIT", feedstock=False),
    # --- The utilities every environment carries ----------------------------------
    DemoPackage("setuptools", "80.9.0", "75.8.0", licence="MIT"),
    DemoPackage("pip", "25.2", "25.0", licence="MIT"),
    DemoPackage("typer", "0.19.2", "0.19.2", licence="MIT"),
    DemoPackage("tqdm", "4.67.1", "4.67.1", licence="MPL-2.0 AND MIT"),
    DemoPackage("attrs", "25.4.0", "25.4.0", licence="MIT"),
    DemoPackage("cattrs", "25.3.0", "25.3.0", licence="MIT", feedstock=False),
    DemoPackage("packaging", "25.0", "25.0", licence="Apache-2.0 OR BSD-2-Clause"),
    DemoPackage("certifi", "2025.10.5", "2025.1.31", licence="MPL-2.0"),
    DemoPackage("idna", "3.11", "3.11", licence="BSD-3-Clause"),
    DemoPackage("psutil", "7.1.0", "7.1.0", licence="BSD-3-Clause", python_evidence="build"),
    DemoPackage("boto3", "1.40.40", "1.36.20", licence="Apache-2.0", errored=("advisory",)),
    DemoPackage("sqlalchemy", "2.0.44", "2.0.38", licence="MIT", python_evidence="build"),
    DemoPackage("celery", "5.6.3", "5.4.0", licence="BSD-3-Clause"),
    DemoPackage("redis-py", "6.4.0", "5.2.1", licence="MIT"),
    DemoPackage("psycopg2", "2.9.10", "2.9.10", licence="LGPL-3.0-or-later", python_evidence="build"),
    DemoPackage("ruff", "0.14.1", "0.14.1", licence="MIT"),
    DemoPackage("mypy", "1.18.2", "1.18.2", licence="MIT"),
    DemoPackage("pytest", "8.4.2", "8.4.2", licence="MIT"),
    DemoPackage("coverage", "7.10.7", "7.10.7", licence="Apache-2.0", python_evidence="build"),
    DemoPackage("structlog", "25.4.0", "25.4.0", licence="Apache-2.0 OR MIT"),
    DemoPackage("orjson", "3.11.3", "3.11.3", licence="Apache-2.0 OR MIT", python_evidence="build"),
    DemoPackage("protobuf", "6.33.0", "5.29.3", licence="BSD-3-Clause", errored=("advisory",), python_evidence="build"),
    DemoPackage("tenacity", "9.1.2", "9.1.2", licence="Apache-2.0", feedstock=False),
    DemoPackage("filelock", "3.19.1", "3.19.1", licence="Unlicense"),
    DemoPackage("marshmallow", "4.1.0", "4.1.0", licence="MIT", feedstock=False),
    # --- Things conda-forge ships that are not Python at all ----------------------
    #
    # Where `not_applicable` comes from. The Python 3.14 question is not a hard one
    # for these, it is not a question at all, and a reader has to be able to tell
    # that from `unknown` -- which is why they are in the roster rather than being
    # simulated by a flag on a package the question does apply to.
    DemoPackage("nodejs", "24.10.0", "22.13.1", licence="MIT", python_evidence="none"),
    DemoPackage("cmake", "4.1.2", "3.31.5", licence="BSD-3-Clause", python_evidence="none"),
    DemoPackage("ripgrep", "14.1.1", "14.1.1", licence="MIT OR Unlicense", python_evidence="none"),
    DemoPackage("ffmpeg", "8.0", "7.1.0", licence="GPL-3.0-or-later", python_evidence="none"),
    DemoPackage("libarchive", "3.8.1", "3.8.1", licence="BSD-2-Clause", python_evidence="none"),
    DemoPackage("sqlite", "3.50.4", "3.50.4", licence="blessing", python_evidence="none"),
    # --- Never identified, so `CPM-AD-4` gates every verdict on them ---------------
    #
    # The rows a reviewer opens the identity queue for, and deliberately not real
    # packages: a fictional name cannot be resolved by anybody later deciding to
    # improve the demo, and two rather than one so the queue looks like a queue.
    DemoPackage("internal-telemetry-sdk", "2.4.0", "2.4.0", identified=False),
    DemoPackage("internal-feature-flags", "0.9.3", "0.9.1", identified=False),
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
            published_version=_surface_version(demo, reached="channel"),
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
        recipe_version=_surface_version(demo, reached="recipe"),
        recipe_build_number=0,
        recipe_metadata_url=f"https://github.com/conda-forge/{demo.name}-feedstock/blob/main/recipe/meta.yaml",
        last_recipe_activity_at=observed_at - timedelta(days=demo.feedstock_idle_days),
        absence_established=False,
    )


def _surface_version(demo: DemoPackage, *, reached: str) -> str:
    """Return the version one packaging surface publishes.

    The fixed version where the fix has got this far, and the version in hand where
    it has not. `fix_reached` names the furthest surface, and the chain is ordered:
    a fix in the channel has necessarily been through a recipe.

    Args:
        demo: The package, which says how far the fix has reached.
        reached: The surface being written, `"recipe"` or `"channel"`.

    Returns:
        The version that surface publishes.

    """
    chain = ("release", "recipe", "channel")
    if demo.advisory is None or chain.index(demo.fix_reached) < chain.index(reached):
        return demo.installed_version
    return demo.upstream_version


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
        # A **bare version**, which is what OSV states as the range's `fixed` event and
        # the one form `policies/remediation.py` can compare -- anything carrying an
        # ordering marker states a *set* of versions and is `not_comparable`.
        #
        # Every advisory row's `upstream_version` is the advisory's own fixed version,
        # by construction of the roster, so there is no second place to keep it. The
        # consequence of not recording it is what made this worth doing: without a
        # fixed version the remediation pass reads no surface at all, every remediation
        # row comes out `unknown`, and the priority rules that turn on a fix being
        # available or packaged can never fire -- a demo where a quarter of the
        # inventory is vulnerable and the screen cannot say what to do about any of it.
        fixed_range=demo.upstream_version,
        matched_version=demo.installed_version,
        match_confidence=MatchConfidence.EXACT_VERSION,
    )
    KevFinding.objects.create(
        package=package,
        vulnerability_finding=finding,
        observed_at=observed_at,
        state=LISTED if demo.kev_listed else NOT_LISTED,
        source="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        catalog_date_added=_catalogued(demo),
    )


def _catalogued(demo: DemoPackage) -> datetime | None:
    """Return the instant CISA's catalogue states it added this advisory, or none.

    Args:
        demo: The package, which carries the date the catalogue states.

    Returns:
        The stated date as an aware instant, or `None` for an advisory the catalogue
        does not list -- which is what `kev_findings` requires of a `not_listed` row.

    """
    if not demo.kev_listed or not demo.kev_catalogued:
        return None
    return datetime.fromisoformat(demo.kev_catalogued).replace(tzinfo=UTC)


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
        # single well-known identifier is recognised as; a compound expression is
        # what `spdx-expression` is for -- and the roster now carries `AND` as well
        # as `OR`, which a test for `" OR "` alone would have filed as an identifier.
        detection_method="spdx-expression" if _COMPOUND.search(demo.licence) else "spdx-identifier",
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
    from conda_sentinel.collectors.outcomes import VERIFICATION_FAILED  # noqa: PLC0415 - as above
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

    compatible = demo.python_evidence in {"metadata", "build"}
    PythonReadinessAssessment.objects.create(
        package=package,
        observed_at=observed_at,
        state=_INFERRED_COMPATIBLE if compatible else _INFERRED_INCOMPATIBLE,
        python_series=series,
        source=f"https://pypi.org/project/{demo.name}/",
        # An upper bound is what makes a static assessment come out incompatible, and
        # it is the ordinary real cause: a package that pinned `<3.14` and has not
        # been revisited. The classifier is absent on those rows rather than
        # contradicting the bound.
        requires_python=">=3.9" if compatible else ">=3.9,<3.14",
        matching_classifier="Programming Language :: Python :: 3.14" if compatible else "",
        deciding_signal="classifier" if compatible else "requires-python",
    )
    if demo.python_evidence in {"build", "build-failed"}:
        PythonVerificationResult.objects.create(
            package=package,
            observed_at=observed_at,
            state=VERIFIED_COMPATIBLE if demo.python_evidence == "build" else VERIFICATION_FAILED,
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
        "unconfigured": _unconfigured_at(version),
    }


def _unconfigured_at(version: str) -> str:
    """Return what the parameter file leaves undecided at the version just run.

    **Read from the parameters rather than written as a sentence**, and the reason is
    a lesson rather than a preference: this used to be a fixed string saying priority
    and licence come out inert. Recording a rule set at a newer version made that
    string false the moment the seeder picked the newer version up -- a demo
    confidently explaining a state it was no longer in, which is worse than a demo
    that says nothing.

    Args:
        version: The policy version the run applied.

    Returns:
        A sentence naming what is still empty, or -- when nothing is -- pointing at
        the file so a reader can see whether the version they just ran at is a
        proposal.

    """
    from conda_sentinel.policies.parameters import parameters_for  # noqa: PLC0415 - after django.setup()

    recorded = parameters_for(version)
    empty = [
        name
        for name, values in (("priority_rules", recorded.priority_rules), ("license_rules", recorded.license_rules))
        if not values
    ]
    if not empty:
        return (
            f"Every rule set is recorded at {version}. If that version is a PROPOSAL -- the comment above it in "
            f"the parameter file says so -- then the priority buckets on these screens are a proposal too, and "
            f"reviewing them by looking at the screens is exactly what it is for."
        )
    return (
        f"{' and '.join(empty)} are empty at {version}, so the columns they drive come out unknown or "
        f"manual_review whatever evidence is behind them. The parameter file says why; the values are PRD "
        f"Open Questions 8 and 4."
    )


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
