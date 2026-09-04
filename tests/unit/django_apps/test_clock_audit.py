"""`EVIDENCE.01-AUDIT-002`: nothing under `src/` reads a wall clock directly.

`CPM-AD-26` puts one clock in `core` and requires every collector, policy pass
and freshness computation to take it as a parameter. The rule is worth a gate
because breaking it is invisible: `timezone.now()` written inside a staleness
check works perfectly, ships, and is then untestable except by waiting -- so the
window assertions that `R-03` depends on either do not get written or get
written flaky, and nobody notices which.

Shaped after `tests/unit/test_import_roots.py`, which `CPM-AD-26` names as the
model, and after `tests/unit/test_suite_policy.py`, which is where the counted
exemption comes from. Matched on the parsed syntax tree rather than by text
search, for the reason both give: prose about the prohibition -- this docstring,
`core/clock.py`'s -- must not itself be an offence, and `clock.now()`, the
correct call, must be distinguishable from `timezone.now()`, which a grep for
`.now(` cannot do.

**A read is not always a call, and this is the spelling that matters most.**
`observed_at = models.DateTimeField(default=timezone.now)` never calls anything
in the module that writes it -- Django holds the callable and calls it per row --
and it is the *idiomatic* way to give an evidence column a timestamp. It is
therefore exactly what `CPM-EVIDENCE-S02` and `S03` would write, and a detector
keyed on `ast.Call` would let it through while this file's docstring claimed the
repository was clean. `auto_now_add=True` and `auto_now=True` are the same read
with Django supplying the clock as well as the call. All three are matched.

**Receivers are resolved from the imports, not from the last dotted segment.**
`from django.utils import timezone as tz` then `tz.now()` is a two-character
rename, and it is what somebody writes after being told not to call
`timezone.now()`. A table of literal receiver names cannot see it. Every local
binding is resolved back to what it was imported from, the way
`tests/unit/django_apps/test_single_ordering_audit.py::outcome_class_prefixes`
resolves the outcome class -- neither audit should be the weaker of the pair.

**What is deliberately not banned: the monotonic clock.** `time.monotonic()`
reads ambient time but is not a *wall* clock: it has no epoch, cannot stamp an
`observed_at`, and cannot answer a freshness question -- which is the whole
subject of `CPM-AD-26`. It is also the correct source for the timeouts, backoff
and rate limits `CPM-NFR-3` requires of the collector base (`CPM-EVIDENCE-S05`),
and `config/authorization/jwks.py` already takes it as an injected parameter,
which is the pattern this rule asks for anyway. `time.time()` *is* a wall clock
and is banned.

**Four call sites are licensed, by count, and nothing else is.**
`core/clock.py` holds the one intended read. The other three are inherited
platform: `django_service/users/management/commands/prune_expired_state.py`,
`config/local_dev/tokens.py`, and `django_service/users/models.py`, whose
`CredentialEpoch.first_seen_at` carries `auto_now_add=True`. All three predate
this rule, sit outside `CPM-EP-EVIDENCE`'s binding, and cannot be routed through
`core` without making `django_service` import a domain application -- which
inverts the dependency direction `AD-4` fixes. They are recorded below as one
occurrence each, so a *second* direct read in any of them fails the gate exactly
as a first one anywhere else would. A path prefix skipped wholesale would not do
that, which is the whole argument for counting.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a product decision from this project's own architecture spine
always carries the `CPM-` prefix. So `AD-4` above is the platform's dependency
direction and `CPM-AD-26` is this product's clock rule, and they are different
registers rather than a typo.

**Migrations are outside the scan.**
`django_service/users/migrations/0001_initial.py` carries
`django.utils.timezone.now` as a field default, written by Django's own
autogenerator. Failing a gate on generated code would mean hand-editing it
forever.

Reads and parses repository files and nothing else: no database, no network, no
subprocess.
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING
from typing import Final

import pytest

from tests.source_scan import SRC_ROOT
from tests.source_scan import dotted_name
from tests.source_scan import parse
from tests.source_scan import project_files

if TYPE_CHECKING:
    from pathlib import Path

#: The wall-clock reads each canonical receiver offers.
#:
#: `timezone` is Django's helper: `now` is the aware instant, and `localtime` and
#: `localdate` are the same instant rendered in the active zone -- still a wall
#: clock, and one whose answer additionally depends on process state. `datetime`
#: is the stdlib class, whose `today` is one character from `now`. `date.today`
#: is the same read with the time thrown away. `time.time` is the epoch seconds.
BANNED_READS: Final[dict[str, frozenset[str]]] = {
    "date": frozenset({"today"}),
    "datetime": frozenset({"now", "today", "utcnow"}),
    "time": frozenset({"time", "time_ns"}),
    "timezone": frozenset({"localdate", "localtime", "now"}),
}

#: Where each canonical receiver is imported from. `None` as the attribute means
#: the module *is* the receiver -- `import time`, or `from django.utils import
#: timezone` -- while a named attribute means the receiver is reached through the
#: module, as `datetime.datetime` is after `import datetime`.
MODULE_RECEIVERS: Final[dict[str, dict[str | None, str]]] = {
    "datetime": {"date": "date", "datetime": "datetime"},
    "django.utils.timezone": {None: "timezone"},
    "time": {None: "time"},
}

#: The functions that can be imported bare, so that the receiver never appears at
#: the call site at all. `from django.utils.timezone import now` is the form this
#: audit's own docstring calls the one that matters most.
BANNED_FUNCTIONS: Final[dict[str, frozenset[str]]] = {
    "django.utils.timezone": frozenset({"localdate", "localtime", "now"}),
    "time": frozenset({"time", "time_ns"}),
}

#: Field keywords that hand the clock to Django rather than reading it here. They
#: take a boolean, and only `True` is a read.
BANNED_FIELD_KEYWORDS: Final[frozenset[str]] = frozenset({"auto_now", "auto_now_add"})

# Recorded exemptions, keyed by module, by the exact form *and* by how many times
# that form may appear -- the shape `tests/unit/test_suite_policy.py` established,
# and for the same reason: keying by form alone would licence the form for the
# whole file, so the next direct read added to `tokens.py` would be permitted
# silently. The count is one in each case. Two tests below enforce it -- one
# fails on a second occurrence, the other on the recorded one's removal.
#
# django_apps/.../core/clock.py -- CPM-AD-26's own implementation. This is the
# read every other module is required to route through, and `SystemClock.now`
# carries a comment saying so. It is exempted rather than special-cased in the
# detector because "the clock module may read the clock" is a decision, and a
# decision belongs in a table somebody can read.
# config/local_dev/tokens.py -- inherited platform, `issued_at = datetime.now(tz=UTC)`
# in the local-development token minter. It runs only in a local run, it stamps a
# JWT rather than an observation, and nothing about staleness or replay depends
# on it.
# django_service/users/management/commands/prune_expired_state.py -- inherited
# platform, `now = timezone.now()` in the prune command. Its cut-off is compared
# against `Session.expire_date`, not against an evidence row, and routing it
# through `core` would make the platform package import a domain application.
# django_service/users/models.py -- inherited platform,
# `CredentialEpoch.first_seen_at = DateTimeField(..., auto_now_add=True)`. Django
# reads the clock on the model's behalf at insert time. Changing it means a
# migration on an inherited table for a column no product policy reads, which is
# a larger and riskier edit than the rule is worth here; the entry is what keeps
# the *next* `auto_now_add` -- on an evidence table, where replay does depend on
# it -- a failing gate.
RECORDED_EXEMPTIONS: dict[str, dict[str, int]] = {
    "config/local_dev/tokens.py": {"datetime.now(...)": 1},
    "django_apps/conda_package_supply_chain_monitor/core/clock.py": {"timezone.now(...)": 1},
    "django_service/users/management/commands/prune_expired_state.py": {"timezone.now(...)": 1},
    "django_service/users/models.py": {"auto_now_add=True": 1},
}

#: The inherited call sites the story and this review name. Asserted to be
#: reachable by the scan, so an exclusion added later cannot quietly take them
#: out of view.
NAMED_INHERITED_CALL_SITES: Final[tuple[str, ...]] = (
    "config/local_dev/tokens.py",
    "django_service/users/management/commands/prune_expired_state.py",
    "django_service/users/models.py",
)

#: The generated file the scan must *not* reach, named rather than left implicit:
#: it carries `django.utils.timezone.now` and is the reason migrations are
#: excluded at all.
A_MIGRATION_WITH_A_CLOCK_DEFAULT: Final[str] = "django_service/users/migrations/0001_initial.py"

# Synthetic modules the detector is measured against. Source text parsed here
# rather than files on disk: a fixture module under `src/` would be found by the
# scan itself and would need an exemption of its own.
DJANGO_TIMEZONE_CALL = """
from django.utils import timezone

stamped = timezone.now()
"""

ALIASED_TIMEZONE_CALL = """
from django.utils import timezone as tz

stamped = tz.now()
"""

FULLY_QUALIFIED_TIMEZONE_CALL = """
import django.utils.timezone

stamped = django.utils.timezone.now()
"""

ALIASED_MODULE_TIMEZONE_CALL = """
import django.utils.timezone as clockish

stamped = clockish.now()
"""

STDLIB_DATETIME_CALL = """
from datetime import UTC
from datetime import datetime

stamped = datetime.now(tz=UTC)
"""

ALIASED_DATETIME_CALL = """
from datetime import UTC
from datetime import datetime as dt

stamped = dt.now(tz=UTC)
"""

STDLIB_UTCNOW_CALL = """
import datetime

stamped = datetime.datetime.utcnow()
"""

STDLIB_TODAY_CALL = """
from datetime import date

stamped = date.today()
"""

LOCALTIME_CALL = """
from django.utils import timezone

stamped = timezone.localtime()
"""

EPOCH_SECONDS_CALL = """
import time

stamped = time.time()
"""

BARE_IMPORTED_NOW_CALL = """
from django.utils.timezone import now

stamped = now()
"""

CLOCK_AS_A_FIELD_DEFAULT = """
from django.db import models
from django.utils import timezone


class Snapshot(models.Model):
    observed_at = models.DateTimeField(default=timezone.now)
"""

BARE_CLOCK_AS_A_FIELD_DEFAULT = """
from django.db import models
from django.utils.timezone import now


class Snapshot(models.Model):
    observed_at = models.DateTimeField(default=now)
"""

AUTO_NOW_ADD_FIELD = """
from django.db import models


class Snapshot(models.Model):
    observed_at = models.DateTimeField(auto_now_add=True)
"""

AUTO_NOW_FIELD = """
from django.db import models


class Snapshot(models.Model):
    refreshed_at = models.DateTimeField(auto_now=True)
"""

AN_INJECTED_READ = """
def observe(clock):
    return clock.now()
"""

AN_INJECTED_READ_THROUGH_AN_ATTRIBUTE = """
class Collector:
    def observe(self):
        return self.clock.now()
"""

AN_INJECTED_READ_AS_A_DEFAULT = """
from conda_package_supply_chain_monitor.core.clock import SystemClock


def observe(clock=SystemClock()):
    return clock.now()
"""

A_METHOD_NAMED_NOW = """
class FixedClock:
    def now(self):
        return self.instant
"""

A_MONOTONIC_READ = """
from time import monotonic

elapsed = monotonic()
"""

AN_EXPLICIT_AUTO_NOW_OFF = """
from django.db import models


class Snapshot(models.Model):
    observed_at = models.DateTimeField(auto_now_add=False)
"""

A_TIMESTAMP_CONVERSION = """
from datetime import UTC
from datetime import datetime

expires = datetime.fromtimestamp(1700000000, tz=UTC)
"""

PROSE_ONLY = '''
"""Nothing here calls timezone.now() or datetime.utcnow(); it only says so."""
'''


def receiver_bindings(tree: ast.Module) -> dict[str, str]:
    """Return every local dotted spelling that resolves to a clock receiver.

    Resolved from the import statements rather than assumed from the last dotted
    segment, which is what makes `from django.utils import timezone as tz`
    visible. It is also what removes the false positives a literal-name table
    would carry: a local variable called `time` or a model field called `date`
    binds nothing here, because nothing imported it from a clock module.

    Args:
        tree: The parsed module.

    Returns:
        Local dotted spelling to the canonical receiver name -- `"tz"` to
        `"timezone"`, `"dt"` to `"datetime"`, `"datetime.date"` to `"date"`.

    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                offered = MODULE_RECEIVERS.get(alias.name)
                if offered is None:
                    continue
                # `import a.b.c` with no alias binds `a` and is used as `a.b.c`;
                # `import a.b.c as x` binds `x` outright.
                bound = alias.asname or alias.name
                for attribute, canonical in offered.items():
                    bindings[bound if attribute is None else f"{bound}.{attribute}"] = canonical
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            for alias in node.names:
                whole = MODULE_RECEIVERS.get(f"{node.module}.{alias.name}", {})
                through = MODULE_RECEIVERS.get(node.module, {})
                if None in whole:
                    bindings[alias.asname or alias.name] = whole[None]
                elif alias.name in through:
                    bindings[alias.asname or alias.name] = through[alias.name]
    return bindings


def bare_clock_bindings(tree: ast.Module) -> dict[str, str]:
    """Return every local name bound directly to a `now`-style function.

    Args:
        tree: The parsed module.

    Returns:
        Local name to the canonical spelling of what it is -- `"now"` to
        `"timezone.now"` -- so the reported form names the read rather than
        whatever the importing module chose to call it.

    """
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None or node.level != 0:
            continue
        offered = BANNED_FUNCTIONS.get(node.module, frozenset())
        receiver = node.module.rpartition(".")[2]
        for alias in node.names:
            if alias.name in offered:
                bound[alias.asname or alias.name] = f"{receiver}.{alias.name}"
    return bound


def wall_clock_reads(tree: ast.Module) -> list[str]:
    """Return every direct wall-clock read in one module, as `line: form` strings.

    Three shapes, because a wall clock is reached in three ways: called
    (`timezone.now()`), handed over as a callable for something else to call
    (`default=timezone.now`), and delegated to Django outright
    (`auto_now_add=True`). The first two are distinguished in the reported form,
    with and without the trailing `(...)`, so an exemption licenses the exact
    shape that was reviewed rather than any read in that file.

    Args:
        tree: The parsed module.

    Returns:
        One entry per read, the form spelled canonically -- `timezone.now(...)`,
        `timezone.now`, `auto_now_add=True` -- so the exemption table can licence
        a *form* rather than a line number that moves whenever the file is
        edited.

    """
    receivers = receiver_bindings(tree)
    bare = bare_clock_bindings(tree)
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found.extend(
                f"{node.lineno}: {keyword.arg}=True"
                for keyword in node.keywords
                if keyword.arg in BANNED_FIELD_KEYWORDS
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            )
        elif isinstance(node, ast.Attribute):
            dotted = dotted_name(node)
            receiver, _, attribute = dotted.rpartition(".")
            canonical = receivers.get(receiver)
            if canonical is not None and attribute in BANNED_READS[canonical]:
                found.append(f"{node.lineno}: {canonical}.{attribute}{'(...)' if id(node) in called else ''}")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in bare:
            found.append(f"{node.lineno}: {bare[node.id]}{'(...)' if id(node) in called else ''}")
    return sorted(found, key=lambda entry: int(entry.split(":", 1)[0]))


def reads_in(path: Path) -> list[str]:
    """Return every direct wall-clock read in one file.

    Args:
        path: The module to scan.

    Returns:
        One `line: form` string per read.

    """
    return wall_clock_reads(parse(path))


#: Every module under `src/` the rule applies to, migrations excluded.
SUBJECT_MODULES: Final[tuple[Path, ...]] = project_files(SRC_ROOT, skip_migrations=True)


def test_the_scan_reaches_the_named_inherited_call_sites() -> None:
    """The anti-vacuity guard: the files the story names are in view.

    A scan that had stopped reaching them -- an exclusion widened, a walk that
    lost a directory -- would report an empty repository and pass every
    assertion below while proving nothing.
    """
    relative = {path.relative_to(SRC_ROOT).as_posix() for path in SUBJECT_MODULES}

    assert len(SUBJECT_MODULES) > len(RECORDED_EXEMPTIONS), f"expected modules under {SRC_ROOT}"
    for named in NAMED_INHERITED_CALL_SITES:
        assert named in relative, named


def test_the_detector_finds_the_reads_the_named_call_sites_actually_contain() -> None:
    """The other half of the guard: the detector matches real, in-tree code.

    `test_the_scan_reaches_the_named_inherited_call_sites` proves the files are
    looked at; this proves the looking finds something. Together they are what
    stops a detector that had stopped recognising `timezone.now` from reporting a
    clean repository. `users/models.py` is in the list on purpose: it is matched
    only by the `auto_now_add` branch, which the first version of this audit did
    not have, so it is the case that would go red if that branch were removed.
    """
    for named in NAMED_INHERITED_CALL_SITES:
        assert reads_in(SRC_ROOT / named) != [], named


def test_migrations_are_outside_the_scan() -> None:
    """Generated code is not a decision anybody took.

    Named directly rather than asserted as a property of the glob, because the
    file exists and carries exactly the form the ban is about: if the exclusion
    regressed, this is the case that would go red rather than the whole
    parametrized sweep going red for a reason nobody could read.
    """
    migration = SRC_ROOT / A_MIGRATION_WITH_A_CLOCK_DEFAULT

    assert migration.is_file(), migration
    assert migration not in SUBJECT_MODULES


@pytest.mark.parametrize(
    "path",
    SUBJECT_MODULES,
    ids=lambda path: str(path.relative_to(SRC_ROOT)),
)
def test_no_module_reads_the_wall_clock_directly(path: Path) -> None:
    """`CPM-AD-26`: time comes from the injected clock in `core`.

    Parameterized per module so a violation names the file that introduced it.
    The exemption above is spent per occurrence rather than per form: a module
    that has used its one recorded read gets no second one for free.
    """
    relative = path.relative_to(SRC_ROOT).as_posix()
    exempted = RECORDED_EXEMPTIONS.get(relative, {})
    reads = reads_in(path)
    counted = Counter(read.split(": ", 1)[1] for read in reads)
    over_quota = {form for form, count in counted.items() if count > exempted.get(form, 0)}
    offences = [read for read in reads if read.split(": ", 1)[1] in over_quota]

    assert offences == [], f"{relative} reads a wall clock directly rather than taking a clock: {offences}"


def test_the_exemption_table_has_entries_to_check() -> None:
    """The parametrize below means nothing if the table it reads is empty."""
    assert RECORDED_EXEMPTIONS != {}


@pytest.mark.parametrize("relative", sorted(RECORDED_EXEMPTIONS), ids=str)
def test_every_recorded_exemption_still_describes_the_file(relative: str) -> None:
    """An exemption that no longer applies is a licence nobody meant to leave open.

    Checked in the same direction the exemption is granted, exactly as
    `tests/unit/test_suite_policy.py` does: the module has to be one the scan
    reaches -- a rename would otherwise leave the entry green while the file it
    licenses went unscanned -- and it has to still contain the recorded read
    exactly as many times as the table records. Refactor `prune_expired_state.py`
    onto the clock and this fails until its entry goes with it; add a second read
    and it fails from the other side.
    """
    module = SRC_ROOT / relative

    assert module in SUBJECT_MODULES, f"{relative} is exempted but is not a module the scan reaches"

    counted = Counter(read.split(": ", 1)[1] for read in reads_in(module))
    recorded = RECORDED_EXEMPTIONS[relative]
    mismatched = {
        form: (counted.get(form, 0), expected)
        for form, expected in recorded.items()
        if counted.get(form, 0) != expected
    }

    assert mismatched == {}, f"{relative}: recorded exemptions no longer match, found vs recorded {mismatched}"


@pytest.mark.parametrize(
    "source",
    [
        DJANGO_TIMEZONE_CALL,
        ALIASED_TIMEZONE_CALL,
        FULLY_QUALIFIED_TIMEZONE_CALL,
        ALIASED_MODULE_TIMEZONE_CALL,
        STDLIB_DATETIME_CALL,
        ALIASED_DATETIME_CALL,
        STDLIB_UTCNOW_CALL,
        STDLIB_TODAY_CALL,
        LOCALTIME_CALL,
        EPOCH_SECONDS_CALL,
        BARE_IMPORTED_NOW_CALL,
        CLOCK_AS_A_FIELD_DEFAULT,
        BARE_CLOCK_AS_A_FIELD_DEFAULT,
        AUTO_NOW_ADD_FIELD,
        AUTO_NOW_FIELD,
    ],
    ids=[
        "timezone",
        "timezone-aliased",
        "fully-qualified",
        "module-aliased",
        "datetime",
        "datetime-aliased",
        "utcnow",
        "date-today",
        "localtime",
        "epoch-seconds",
        "bare-import",
        "field-default",
        "field-default-bare",
        "auto-now-add",
        "auto-now",
    ],
)
def test_the_detector_matches_every_banned_form(source: str) -> None:
    """Fifteen spellings of the same read, because a scan that knew one has a door in it.

    Three of them are the ones a review found this audit blind to: the two
    aliased receivers, which a table of literal names cannot see, and the field
    default, which is a read that never appears as a call. Each is what somebody
    writes *after* being told not to call `timezone.now()`.
    """
    assert wall_clock_reads(ast.parse(source)) != []


@pytest.mark.parametrize(
    "source",
    [
        AN_INJECTED_READ,
        AN_INJECTED_READ_THROUGH_AN_ATTRIBUTE,
        AN_INJECTED_READ_AS_A_DEFAULT,
        A_METHOD_NAMED_NOW,
        A_MONOTONIC_READ,
        AN_EXPLICIT_AUTO_NOW_OFF,
        A_TIMESTAMP_CONVERSION,
        PROSE_ONLY,
    ],
    ids=[
        "injected",
        "injected-attribute",
        "injected-default",
        "definition",
        "monotonic",
        "auto-now-off",
        "conversion",
        "prose",
    ],
)
def test_the_detector_ignores_what_is_not_a_wall_clock_read(source: str) -> None:
    """The negative control, and the whole point of parsing rather than grepping.

    `clock.now()` is the call this rule exists to *require*. `monotonic()` is a
    different kind of clock and is out of scope for the reason the module
    docstring gives. `auto_now_add=False` is the keyword with the read switched
    off. `datetime.fromtimestamp(...)` converts a value somebody else produced --
    `config/authorization/mapper.py` does exactly this with a token's `exp` claim
    -- and is not a clock read at all. A text search for `.now(`, `datetime` or
    `auto_now` flags several of these.
    """
    assert wall_clock_reads(ast.parse(source)) == []


def test_the_reported_form_distinguishes_a_call_from_a_handed_over_callable() -> None:
    """An exemption licenses the shape that was reviewed, not any read in the file.

    `timezone.now()` and `default=timezone.now` are different decisions with
    different consequences -- one stamps a value here, the other gives Django a
    clock for every row it ever inserts -- so a file licensed for one must not be
    silently licensed for the other.
    """
    called = wall_clock_reads(ast.parse(DJANGO_TIMEZONE_CALL))
    handed_over = wall_clock_reads(ast.parse(CLOCK_AS_A_FIELD_DEFAULT))

    assert [entry.split(": ", 1)[1] for entry in called] == ["timezone.now(...)"]
    assert [entry.split(": ", 1)[1] for entry in handed_over] == ["timezone.now"]
