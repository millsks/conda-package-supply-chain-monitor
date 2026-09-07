"""The versioned policy parameters: one reviewed file, read by the run's policy version.

`CPM-FR-40` requires the feedstock inactivity threshold to be "a versioned policy
parameter" rather than a constant, and `CPM-AD-8` says a rule set is *versioned
data*. This module is the mechanism: a delimited, reviewed file shipped inside
the wheel, mapping a policy version to the parameters a run at that version
applies, read through one contract that refuses rather than repairs.

**Why a file rather than a setting or a database table.** `CPM-AD-14` makes
reviewed reference data in the repository this product's one governed shape for
exactly this, and `collectors/data/` is the precedent, down to shipping inside
the built artifact and being changed by pull request. A *setting* would be
per-deployment rather than per-version, so two components at one policy version
could disagree about what that version means -- which is the whole property
`CPM-AD-8`'s versioning exists to give. A *table* would be a write path nothing
audits: a verdict would change because somebody ran an `UPDATE`, with no diff and
no reviewer.

**The file is a history, not a current value, and that is load-bearing.**
`CPM-FR-22` promises that re-running a recorded policy version at its recorded
cut-off reproduces the original output. A version's parameters must therefore
still be readable long after a newer version has superseded them, so an entry is
*added* when a threshold changes and the old entry stays. Removing one makes
every run recorded at that version unreplayable.

**An unknown version is refused, never defaulted.** There is no fallback entry
and there must not be: a default would make a run at a version nobody reviewed
produce verdicts that look exactly like reviewed ones, which is the "degrades to
a clean result" `CPM-NFR-3` forbids. `CPM-AD-23` contains the refusal to one
package -- that package's derived rows roll back and every other package's
commit -- so the cost of the refusal is bounded and visible in the run's ending.
The operational consequence is stated rather than left to be met: **a policy run
must name a version this file records, or every package fails.**

**Parsing and reading are two things, and they are separated here** on exactly
the terms `collectors/watchlist.py` separates them. `parameters_from` turns
*text* into parameter sets and owns every refusal about content; `parameters_at`
opens a file and owns only the refusals that are about a file. That split is what
lets the whole contract be measured in memory.

**The read is memoized, and that is the one place this module differs from the
watchlist deliberately.** A watchlist is data an operator corrects between
sweeps, so it is re-read on every fetch. These parameters are keyed by the policy
version a run declares, and `CPM-AD-8` makes one version mean one rule set: a
file re-read per package would let an edit mid-run split a single run across two
rule sets, with half the inventory judged under each. So the file is read once
per process and a change to it takes effect at the next start -- which shipping a
new artifact already is, because the file ships inside the wheel.

**Every refusal is `ImproperlyConfigured`, names the file, and names the fault.**
The parameters are governed reference data under `CPM-AD-14`, so a malformed set
is a misconfigured deployment rather than a misbehaving source, and an operator
sent to the file is being sent to the right place. `collectors/watchlist.py`'s
`WatchlistError` is the same boundary drawn for the same reason.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import timedelta
from functools import cache as memoized
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING
from typing import Final

from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "INACTIVITY_DAYS_KEY",
    "MAX_INACTIVITY_DAYS",
    "PARAMETERS_FILENAME",
    "VERSIONS_TABLE",
    "PolicyParameterError",
    "PolicyParameters",
    "forget_recorded_parameters",
    "parameters_at",
    "parameters_directory",
    "parameters_file",
    "parameters_for",
    "parameters_from",
    "parameters_in",
    "recorded_parameters",
]

#: The one top-level table the file declares: policy version to parameter set.
#:
#: Nested rather than flat -- `[versions."2026.09"]` rather than
#: `["2026.09"]` -- so the file has room for a header comment and for a later
#: top-level key without every version becoming ambiguous with it. A key outside
#: this table is refused rather than ignored, on the terms
#: `collectors/watchlist.py` refuses an undefined column: a reviewer who adds one
#: believes they have supplied something.
VERSIONS_TABLE: Final[str] = "versions"

#: The one parameter a version records today, in the unit review reads it in.
#:
#: Days rather than seconds because the file is changed by a person reading a
#: pull-request diff, and "180" is a number a reviewer can hold an opinion about
#: where "15552000" is not. It becomes a `timedelta` at the boundary, so nothing
#: downstream carries a unit in a name.
INACTIVITY_DAYS_KEY: Final[str] = "feedstock_inactivity_days"

#: Every key a version's table may declare. One today; the set is what makes an
#: unrecognised key a refusal rather than a silently dropped edit.
PARAMETER_KEYS: Final[frozenset[str]] = frozenset({INACTIVITY_DAYS_KEY})

#: The reviewed file's name.
PARAMETERS_FILENAME: Final[str] = "policy-parameters.toml"

#: The encoding the file is read as. `tomllib` requires UTF-8 by specification,
#: and the decode happens here so a file that is not text produces a refusal
#: naming the file rather than a `UnicodeDecodeError` from inside the parser.
PARAMETERS_ENCODING: Final[str] = "utf-8"

#: The largest interval a recorded threshold may express, in days.
#:
#: `timedelta`'s own ceiling, and the bound exists to turn an `OverflowError`
#: into a refusal that names the file and the version rather than to express an
#: opinion about how long is too long. A reviewer who writes a nine-digit number
#: has made a typing mistake, and the message they get should say which file to
#: go and edit -- not `days=1000000000; must have magnitude <= 999999999`, raised
#: from inside a constructor, with no mention of a parameter set anywhere in it.
MAX_INACTIVITY_DAYS: Final[int] = timedelta.max.days


class PolicyParameterError(ImproperlyConfigured):
    """The reviewed policy parameters cannot be read, or do not cover a version.

    An `ImproperlyConfigured` subclass, on exactly the terms
    `collectors/watchlist.py`'s `WatchlistError` is one: these parameters are
    governed reference data (`CPM-AD-14`), so a malformed set is a misconfigured
    deployment and the operator is being sent to a file they can edit.

    A named subclass rather than a bare `ImproperlyConfigured`, so a case can
    assert *this* refusal rather than any misconfiguration. It adds no startup
    condition: `src/config/startup/` is where those live, and this is a run-time
    refusal raised from a domain application.
    """


@dataclass(frozen=True, slots=True)
class PolicyParameters:
    """The parameter set one policy version applies.

    Frozen, because a parameter set that could be edited after it was read would
    make "this run applied this version's rules" a claim nothing supports.

    Attributes:
        version: The policy version this set was recorded under. Carried on the
            object rather than only in the mapping's key, so a refusal or a log
            line downstream can name the version without the caller passing it
            twice.
        feedstock_inactivity: How long a feedstock may go without a push before
            `CPM-FR-40`'s policy calls it inactive. A `timedelta`, positive by
            construction -- the read below refuses anything else.

    """

    version: str
    feedstock_inactivity: timedelta


def _parameters_directory(module: str) -> Path:
    """Return the directory the reviewed file lives in, or refuse the installation.

    The reviewed file ships beside this module: `pyproject.toml`'s
    `only-include = ["src"]` with the `sources` mapping that strips
    `src/django_apps` puts `data/` in the wheel here. A path computed from
    `BASE_DIR` would work in a checkout and fail in a container, because the
    `src/` segment does not exist in the wheel layout -- and the failure would
    arrive at the first deployed policy run rather than at the build.
    `collectors/watchlist.py` computes its own the same way and for the same
    reason, and `tests/integration/test_import_resolution.py` asserts both trees
    are actually inside the built wheel.

    `strict=True` resolves every path component and follows symlinks, so an
    editable install whose `policies/` is a link into a checkout resolves to the
    checkout, which is where the file actually is.

    Takes the module's location rather than reading `__file__` itself, so the
    refusal is reachable from a case: `__file__` for a module being imported
    names a file that exists, and a branch only provokable by deleting the module
    out from under the interpreter would be an unreachable line and a
    `pragma: no cover` that `tests/unit/test_coverage_policy.py` bans.

    Args:
        module: The location of the module the `data/` tree sits beside --
            `__file__` in production.

    Returns:
        The `data/` directory beside it.

    Raises:
        PolicyParameterError: When that location cannot be resolved.

    """
    try:
        here = Path(module).resolve(strict=True)
    except OSError as unresolvable:
        message = (
            f"the policy parameter directory cannot be resolved from {module!r}: "
            f"{type(unresolvable).__name__}: {unresolvable}. The reviewed file ships beside this module "
            f"(CPM-AD-14); an installation without it cannot run a policy pass that reads a versioned "
            f"parameter."
        )
        raise PolicyParameterError(message) from unresolvable
    return here.parent / "data"


def parameters_directory() -> Path:
    """Return where the reviewed file lives: beside this module, in the wheel and in a checkout.

    **Resolved on demand rather than at import, and that changed for a reason.**
    A module-scope constant resolves during `django.setup()`, so an installation
    that shipped the modules and dropped the `data/` tree would refuse to *boot*
    -- and `CPM-AD-23` puts the atomic unit at one package, with a pass's refusal
    costing one package's rows and leaving every other package's committed. A
    misconfiguration that fails the whole component is the opposite of that
    containment, and it fails a web process that would never have read this file.
    Resolved here, the same misconfiguration fails the policy run that needed it
    and nothing else.

    Cheap enough to do per call: one `Path.resolve`. The *file* is what is
    expensive to read, and `recorded_parameters` memoizes that.

    Returns:
        The `data/` directory beside this module.

    Raises:
        PolicyParameterError: When this module's own location cannot be resolved.

    """
    return _parameters_directory(__file__)


def parameters_file() -> Path:
    """Return the reviewed parameter file this component ships.

    The one substitution point the suite has: a case that needs a different file
    patches this name, which is what `tests/policy_parameters.py` does. A module
    constant would have been the same seam with none of `parameters_directory`'s
    laziness.

    Returns:
        The path to `policy-parameters.toml` beside this module.

    Raises:
        PolicyParameterError: When the directory cannot be resolved.

    """
    return parameters_directory() / PARAMETERS_FILENAME


def parameters_from(text: str, *, source: Path | str) -> dict[str, PolicyParameters]:
    """Turn a whole parameter file into parameter sets, or refuse it.

    Pure: it opens nothing and knows nothing about where the text came from
    beyond the name it puts in its messages. Every refusal about *content* is
    here, which is what lets the contract be measured against strings rather than
    against files.

    The whole document is turned into parameter sets before anything is returned.
    A generator that yielded entries until it met a bad one would hand a caller a
    prefix of a reviewed file, and the version it happened to want might be in it
    -- so a broken file would fail or not depending on which version was asked
    for.

    Args:
        text: The file's contents.
        source: What to call the file in a refusal. A `Path` in production; a
            case parsing a literal may pass any name.

    Returns:
        One `PolicyParameters` per recorded version, by version.

    Raises:
        PolicyParameterError: When the text is not TOML; when it declares a key
            outside `VERSIONS_TABLE`; when `VERSIONS_TABLE` is absent, is not a
            table, or is empty; when a version's entry is not a table or declares
            an unrecognised key; or when its threshold is missing, is not a whole
            number of days, or is not positive.

    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as unparsable:
        message = (
            f"the policy parameters at {source} are not readable as TOML: {type(unparsable).__name__}: "
            f"{unparsable}. A parameter set is reviewed in a pull-request diff and is text (CPM-AD-14)."
        )
        raise PolicyParameterError(message) from unparsable

    undefined = sorted(key for key in document if key != VERSIONS_TABLE)
    if undefined:
        message = (
            f"the policy parameters at {source} declare the top-level key(s) {undefined}, which this "
            f"contract does not define. The only table is [{VERSIONS_TABLE}]; a key outside it is refused "
            f"rather than ignored, because a silently dropped key is a reviewer who believes they supplied "
            f"a parameter."
        )
        raise PolicyParameterError(message)

    recorded = document.get(VERSIONS_TABLE)
    if not isinstance(recorded, dict):
        found = "nothing" if recorded is None else type(recorded).__name__
        message = (
            f"the policy parameters at {source} do not declare a [{VERSIONS_TABLE}] table -- found {found}. "
            f"Every parameter set is recorded under the policy version that applies it (CPM-AD-8), so a file "
            f"without that table records nothing a run could ask for."
        )
        raise PolicyParameterError(message)
    if not recorded:
        message = (
            f"the policy parameters at {source} record no versions at all. A file awaiting review is not a "
            f"parameter set of nothing: every policy run naming any version would fail against it, and an "
            f"empty table says so far less clearly than this refusal does."
        )
        raise PolicyParameterError(message)

    return {
        _named_version(version, source=source): _parameters(entry, version=version, source=source)
        for version, entry in recorded.items()
    }


def _named_version(version: str, *, source: Path | str) -> str:
    """Refuse a version key that names nothing, and return it unchanged.

    Args:
        version: The key the file recorded a parameter set under.
        source: What to call the file in a refusal.

    Returns:
        The key, **unchanged** -- not stripped. A run declares its version as a
        literal string and `core/ledger.py` records that string verbatim, so a
        key silently trimmed here would match a version the ledger row does not
        carry, and the replay `CPM-FR-22` promises would then read a parameter
        set the original run's own row cannot be traced to.

    Raises:
        PolicyParameterError: When the key is empty or is nothing but
            whitespace. `core/ledger.py` refuses a policy run whose version names
            nothing, so a `[versions.""]` entry can never be reached by a run --
            and a `[versions." 2026.09 "]` entry can never be reached either,
            because the lookup is exact. Both are edits nobody finished, and
            leaving them in the file would mean a reviewer believing they had
            recorded a threshold that nothing will ever apply.

    """
    if not version.strip():
        message = (
            f"the policy parameters at {source} record a parameter set under a version key that names "
            f"nothing ({version!r}). A policy run declares its version as a string and the run ledger "
            f"refuses one that names nothing (CPM-AD-8), so no run can ever reach this entry."
        )
        raise PolicyParameterError(message)
    if version != version.strip():
        message = (
            f"the policy parameters at {source} record a parameter set under {version!r}, which carries "
            f"surrounding whitespace. The lookup is exact, so only a run declaring that exact string -- "
            f"padding included -- would reach it; trimming it here instead would match a version the run's "
            f"own ledger row does not carry."
        )
        raise PolicyParameterError(message)
    return version


def _parameters(entry: object, *, version: str, source: Path | str) -> PolicyParameters:
    """Turn one version's entry into its parameter set, or refuse the entry.

    Args:
        entry: Whatever the file recorded under that version.
        version: The version being read, for the message and for the result.
        source: What to call the file in a refusal.

    Returns:
        The parameter set.

    Raises:
        PolicyParameterError: When the entry is not a table, declares a key this
            contract does not define, or records a threshold that is missing, of
            the wrong type, or not positive.

    """
    if not isinstance(entry, dict):
        message = (
            f"the policy parameters at {source} record {version!r} as {type(entry).__name__} rather than as "
            f"a table. Each version declares its parameters under "
            f"[{VERSIONS_TABLE}.{version!r}], and a scalar there is an edit nobody finished."
        )
        raise PolicyParameterError(message)

    unrecognised = sorted(set(entry) - PARAMETER_KEYS)
    if unrecognised:
        message = (
            f"the policy parameters at {source} declare the key(s) {unrecognised} for version {version!r}, "
            f"which this contract does not define. The parameters are exactly "
            f"{sorted(PARAMETER_KEYS)}; an unrecognised key is refused rather than ignored, because a "
            f"threshold spelled a way nothing reads is a reviewer who believes they changed a verdict."
        )
        raise PolicyParameterError(message)

    return PolicyParameters(
        version=version,
        feedstock_inactivity=_interval(entry.get(INACTIVITY_DAYS_KEY), version=version, source=source),
    )


def _interval(days: object, *, version: str, source: Path | str) -> timedelta:
    """Refuse a threshold that is not a positive whole number of days, and return the interval.

    Args:
        days: Whatever the file recorded, or `None` where it recorded nothing.
        version: The version being read, for the message.
        source: What to call the file in a refusal.

    Returns:
        The threshold as a `timedelta`.

    Raises:
        PolicyParameterError: When the value is absent, is not an integer, is a
            boolean, or is not positive. A boolean is refused explicitly because
            `isinstance(True, int)` is true in Python and TOML spells `true` in a
            way a reviewer could plausibly reach for -- and a threshold of one day
            arrived at by a typo is worse than a refusal. Zero and negatives are
            refused because an interval that is not positive makes every observed
            feedstock inactive the instant it is observed, which is a verdict
            about the whole inventory reached by arithmetic nobody intended.

    """
    if days is None:
        message = (
            f"the policy parameters at {source} record no {INACTIVITY_DAYS_KEY} for version {version!r}. "
            f"CPM-FR-40 makes the inactivity threshold a versioned policy parameter, so a version that "
            f"records none has no rule for this pass to apply -- and defaulting one would make an "
            f"unreviewed value indistinguishable from a reviewed one."
        )
        raise PolicyParameterError(message)
    if isinstance(days, bool) or not isinstance(days, int):
        message = (
            f"the policy parameters at {source} record {INACTIVITY_DAYS_KEY}={days!r} for version "
            f"{version!r}, which is {type(days).__name__} rather than a whole number of days. The threshold "
            f"is an interval a reviewer reads in days; a value of another type is refused rather than "
            f"coerced, because coercion is how a threshold nobody meant becomes a verdict about every "
            f"package."
        )
        raise PolicyParameterError(message)
    if days <= 0:
        message = (
            f"the policy parameters at {source} record {INACTIVITY_DAYS_KEY}={days} for version "
            f"{version!r}, which is not a positive interval. A threshold of zero or less calls every "
            f"feedstock inactive at the instant it was last pushed to, which is a verdict about the whole "
            f"inventory rather than a threshold."
        )
        raise PolicyParameterError(message)
    if days > MAX_INACTIVITY_DAYS:
        message = (
            f"the policy parameters at {source} record {INACTIVITY_DAYS_KEY}={days} for version "
            f"{version!r}, which is longer than the {MAX_INACTIVITY_DAYS} days an interval can express. "
            f"Refused here so the message names the file and the version: built without the check, the "
            f"constructor raises an OverflowError about magnitudes with nothing in it to say which "
            f"parameter set a reviewer has to go and correct."
        )
        raise PolicyParameterError(message)
    return timedelta(days=days)


def parameters_in(
    recorded: Mapping[str, PolicyParameters],
    *,
    version: str,
    source: Path | str,
) -> PolicyParameters:
    """Return one version's parameter set, or refuse a version nothing records.

    Pure, and separated from the read above so the unknown-version refusal -- the
    one AC 3 is actually about -- can be exercised against a mapping rather than
    against a file.

    Args:
        recorded: Every parameter set the file holds, by version.
        version: The policy version the run declared.
        source: What to call the file in the refusal, so an operator is sent to
            the file they have to edit.

    Returns:
        That version's parameter set.

    Raises:
        PolicyParameterError: When the version is not recorded. Refused rather
            than defaulted: see the module docstring. The message lists the
            versions the file does record, because "no parameters for this
            version" without them sends an operator to open the file by hand.

    """
    parameters = recorded.get(version)
    if parameters is None:
        message = (
            f"the policy parameters at {source} record nothing for policy version {version!r}. The recorded "
            f"versions are {sorted(recorded)}. CPM-FR-40 makes the threshold a versioned policy parameter "
            f"and CPM-AD-8 makes a rule set versioned data, so a run at an unrecorded version is refused "
            f"rather than given a default -- a defaulted verdict is indistinguishable from a reviewed one "
            f"in every report that reads it."
        )
        raise PolicyParameterError(message)
    return parameters


def parameters_at(path: Path) -> dict[str, PolicyParameters]:
    """Read one parameter file, or refuse the file.

    Owns only the refusals that are about a *file*: one that is missing,
    unreadable, or not text this component can decode. What the text says is
    `parameters_from`'s.

    Args:
        path: The file to read.

    Returns:
        Every parameter set it records, by version.

    Raises:
        PolicyParameterError: When the file cannot be opened or read, is not
            `PARAMETERS_ENCODING`, or says something `parameters_from` refuses.

    """
    try:
        text = path.read_text(encoding=PARAMETERS_ENCODING)
    except OSError as unreadable:
        message = (
            f"the policy parameters at {path} could not be read: {type(unreadable).__name__}: {unreadable}. "
            f"The parameter sets are a reviewed file this component ships (CPM-AD-14); a policy run is "
            f"refused rather than given a default threshold."
        )
        raise PolicyParameterError(message) from unreadable
    except UnicodeDecodeError as undecodable:
        message = (
            f"the policy parameters at {path} are not {PARAMETERS_ENCODING}: {undecodable}. A parameter set "
            f"is reviewed in a pull-request diff and is text (CPM-AD-14), and TOML is UTF-8 by "
            f"specification."
        )
        raise PolicyParameterError(message) from undecodable
    return parameters_from(text, source=path)


@memoized
def _remembered(path: Path) -> Mapping[str, PolicyParameters] | PolicyParameterError:
    """Read one parameter file once per process, remembering a refusal as readily as a parse.

    Split out of `recorded_parameters` below because `functools.cache` stores
    *returns* and re-runs on every exception, and a refusal that is not
    remembered is the hazard the memoization exists to prevent arrived at from
    the other side: a reviewed file repaired while a failing run was still going
    would begin succeeding mid-inventory, so half the packages would be judged
    under a rule set the other half never saw. So the refusal is returned as a
    value and the caller raises it.

    Args:
        path: The file to read.

    Returns:
        Every recorded parameter set as a **read-only** mapping, or the refusal
        the read raised. The parse is shared by every caller for the life of the
        process, so handing out the mutable dictionary would let one caller's
        assignment change the rule set for every later one -- which is the
        mutability `PolicyParameters` is frozen to prevent, one level up.

    """
    try:
        return MappingProxyType(parameters_at(path))
    except PolicyParameterError as refused:
        return refused


#: Forget every parse this process has made, so the next read opens the files
#: again.
#:
#: The one supported way to make a corrected parameter file take effect without
#: restarting: `recorded_parameters` reads once per process on purpose
#: (`CPM-AD-8` -- one policy version means one rule set, and a file re-read per
#: package would split a run across two of them), and this is the deliberate act
#: that says a reader knows they are changing the rules mid-process. The suite
#: uses it between substituted files; an operator's alternative is a restart,
#: which shipping a new artifact already is.
forget_recorded_parameters: Final = _remembered.cache_clear


def recorded_parameters(path: Path) -> Mapping[str, PolicyParameters]:
    """Return every parameter set one file records, reading it once per process.

    **Memoized on the path**, not on nothing. An argument-free memo over a module
    global answers about whatever file the *first* caller happened to name, so a
    later caller reading a different one would silently get the earlier parse --
    which is a suite whose substituted file stops taking effect, and a component
    whose parameter tree moved and nobody noticed.

    **Memoized deliberately at all** -- see the module docstring and `_remembered`
    above, which is also where a refusal is remembered rather than retried. The
    consequence, stated rather than discovered: a change to the shipped file takes
    effect at the next process start, or at the next `forget_recorded_parameters()`.

    Args:
        path: The file to read. `parameters_file()` in production.

    Returns:
        Every recorded parameter set, by version, as a read-only mapping.

    Raises:
        PolicyParameterError: For everything `parameters_at` refuses, on the
            first call and on every later one -- the same object each time, which
            is what makes the refusal a remembered fact about the file rather
            than a fresh opinion about it.

    """
    remembered = _remembered(path)
    if isinstance(remembered, PolicyParameterError):
        raise remembered
    return remembered


def parameters_for(version: str) -> PolicyParameters:
    """Return the parameter set a run at one policy version applies.

    The one entry point a pass calls. It composes the memoized read with the
    unknown-version refusal, and holds no rule of its own -- both halves are
    argued and exercised where they live.

    Args:
        version: The policy version the run declared, off the run's own row.

    Returns:
        That version's parameter set.

    Raises:
        PolicyParameterError: When the shipped file cannot be read, or records
            nothing for this version.

    """
    path = parameters_file()
    return parameters_in(recorded_parameters(path), version=version, source=path)
