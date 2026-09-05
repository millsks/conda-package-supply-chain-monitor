"""The watchlist: the column contract, the file selection rule, and the adapter that reads it.

`CPM-AD-29` makes the inventory source a **declared adapter** reading a
**versioned watchlist**, with **locality selecting the file and failing closed
toward production**. `CPM-IDENTITY-S06` built the collector and left the adapter
slot empty; this module fills it.

**Parsing and reading are two things, and they are separated here.**
`records_from` turns *text* into records and owns every refusal about content;
`WatchlistAdapter` opens a file, hands the text over, and owns only the refusals
that are about a file -- one that is missing, unreadable, or not text. That split
is what lets the whole column contract be measured in memory, with the file
reads left to the handful of cases that are genuinely about files.

**The adapter is a `Transport` substitution and nothing else.** It implements
`fetch(source, *, headers=None) -> Payload` and is bound at the collector base's
one seam, so `collectors/tasks.py` carries no branch on which source is active
and the seam needs no second protocol (`CPM-AD-29`, `CPM-AD-27`). The `Payload`
it answers carries `status_code=None`, which is what "this source does not speak
HTTP" means in `core/transport.py`'s own words.

**It ignores the locator it is handed, and that is the contract rather than a
shortcut.** `INVENTORY_SOURCE` is `inventory://declared-adapter` -- deliberately
opaque, naming the *run* in the ledger and in every log line rather than
addressing a resource. The file this adapter reads comes from its own
construction. It ignores `headers` for the same kind of reason: the parameter is
keyword-only and defaulted precisely so a transport that speaks no HTTP can
accept and discard them.

**Locality selects the file, and `watchlist_path` never reads it.** `AD-4`
forbids anything under `src/django_apps/` importing `config`, and `CPM-AD-29`
names `config.locality.is_local()` as the selector. `core/roles.py` already
resolves that tension and this module copies its shape exactly: the application
owns the contract and a pure function taking a boolean, and
`config/settings/base.py` performs the read and assigns
`INVENTORY_WATCHLIST_PATH = watchlist_path(local=is_local())`. Nothing here
imports `config`, reads `os.environ`, or touches `django.conf.settings`.

**Selection fails closed toward production**, which is a property of
`is_local()` rather than of this module: only `COMPONENT_RUNTIME=local` selects
the development subset, and absent, empty and unrecognized all read the
production watchlist. That default is the one that matters. A deployed component
that read the development subset would find the packages outside it missing and
record every one of them as *absent* -- permanently, in an append-only log that
nothing may correct.

**The files are read at a path relative to this module.** `pyproject.toml`'s
`only-include = ["src"]` with the `sources` mapping that strips `src/django_apps`
puts `data/` in the wheel beside this module. A path computed from `BASE_DIR`
would work in a checkout and fail in a container, because the `src/` segment does
not exist in the wheel layout, and the failure would arrive at the first deployed
sweep rather than at the build.

**Every refusal is `ImproperlyConfigured`, names the file, and names the line
where a row is at fault.** The watchlist is governed reference data under
`CPM-AD-14`: a malformed one is a misconfigured deployment, not a misbehaving
remote source. That is a different boundary from `collectors/tasks.py`'s
`InventoryRecordError`, which refuses a bad *document* whoever produced it --
this refuses a bad *file*, and can therefore say which line to go and edit. Every
bound the record contract applies is applied here first, for exactly that
reason: a refusal that arrives one layer later names neither the file nor the
line, and the record contract still refuses the same thing from any future
adapter.

**A header-only file is refused.** The production watchlist ships with its header
and no rows, because which packages are tracked is an organizational decision and
not a thing to invent. So a component deployed before that file has been reviewed
fails its ingestion loudly rather than recording every package the inventory has
ever named as departed. `records_in` refuses the empty document one step later
for the same reason; this refusal is earlier and says which file to go and edit.

**The column contract and the three bounds are spelled here and reconciled by
test.** They cannot be imported from `collectors/tasks.py` or from
`identity/models.py`, both of which reach models: this module is imported from
`config/settings/base.py`, long before the app registry exists, and a model
definition at that point raises `AppRegistryNotReady`.
`tests/unit/django_apps/test_watchlist.py` compares each of them against its
source in both directions, so a widened column or an added field is a failing
test rather than a bound that has quietly stopped matching.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Final

from django.core.exceptions import ImproperlyConfigured

from conda_package_supply_chain_monitor.core.transport import Payload

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

__all__ = [
    "DEVELOPMENT_WATCHLIST",
    "MAX_PACKAGE_NAME",
    "MAX_SIGNAL",
    "MAX_SOURCE_PACKAGE_KEY",
    "OPTIONAL_COLUMNS",
    "PRODUCTION_WATCHLIST",
    "REQUIRED_COLUMNS",
    "WATCHLIST_COLUMNS",
    "WATCHLIST_DIRECTORY",
    "WatchlistAdapter",
    "WatchlistError",
    "records_from",
    "watchlist_path",
]

#: The columns that must carry a value on every row, in the order the shipped
#: files spell them. They are the record contract's own field names -- the key,
#: the package's name, and the two counts that together are the internal usage
#: breadth `CPM-FR-4` ranks by -- and `tests/unit/django_apps/test_watchlist.py`
#: reconciles them against `collectors/tasks.py` rather than this comment.
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "source_package_key",
    "package_name",
    "internal_component_count",
    "internal_lob_count",
)

#: The columns a row may leave blank. Blank means *the source did not say* and is
#: yielded as missing, which stays distinguishable from a stated `0` all the way
#: to the NULL in the column -- PRD Open Question 3b, and the reason these four
#: are nullable at all.
OPTIONAL_COLUMNS: Final[tuple[str, ...]] = ("apps", "platforms", "downloads", "versions")

#: The whole header, and the header must be **exactly** this set in any order.
#:
#: Stricter than "no undefined columns", and one rule rather than two: a
#: `feedstock_url` column and a missing `internal_lob_count` column are the same
#: set comparison, and both are refused. The strictness is `CPM-FR-42` and
#: `CPM-FR-1`: ingestion never asserts a mapping, so a column naming a repository,
#: a feedstock, a purl or a confidence is a reviewer who believes they are
#: supplying one -- and a column silently ignored is worse than a run refused.
WATCHLIST_COLUMNS: Final[frozenset[str]] = frozenset({*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS})

#: The two columns that carry text rather than a count, and the key among them.
#: Named rather than sliced off `REQUIRED_COLUMNS`, because a slice would
#: silently change meaning the day a column is added.
KEY_COLUMN: Final[str] = "source_package_key"
NAME_COLUMN: Final[str] = "package_name"
_TEXT_COLUMNS: Final[frozenset[str]] = frozenset({KEY_COLUMN, NAME_COLUMN})

#: The largest count a usage signal may carry: `PositiveIntegerField`'s ceiling,
#: which is a signed 32-bit maximum on every backend Django supports. Restated
#: here rather than imported from `collectors/tasks.py`, which imports models --
#: see the module docstring -- and reconciled against `MAX_COUNT` by test.
#:
#: Applied *here* as well as there so the refusal can name the file and the line.
#: A count the column will not hold is a row a reviewer has to find and edit, and
#: "some record somewhere declares 4000000000" is not a message anybody can act
#: on.
MAX_SIGNAL: Final[int] = 2_147_483_647

#: How long the two text columns may be, by the columns each one lands in.
#:
#: **They are different numbers, and that is the point of this story.** The key
#: becomes `associator_key` -- the stable thing a later resolution matches on,
#: and a wide column because a source may file a package under a long identifier.
#: The name becomes `canonical_name`, which is narrower and is what the product
#: displays. Fusing the two would refuse a legitimately long key for a column it
#: no longer occupies. Both are reconciled against `identity/models.py`'s own
#: fields by test.
MAX_SOURCE_PACKAGE_KEY: Final[int] = 512
MAX_PACKAGE_NAME: Final[int] = 128

#: The two files, by name. The production one is what a deployment reads and what
#: review populates; the development subset is what a developer runs against.
PRODUCTION_WATCHLIST: Final[str] = "watchlist.csv"
DEVELOPMENT_WATCHLIST: Final[str] = "watchlist-development.csv"

#: The line the header sits on, so a refusal about a row can say which row.
#: `csv.reader.line_num` counts physical lines and a quoted cell may span
#: several, so the number a message carries is read off the reader rather than
#: derived from how many records have been seen. That is only true of a reader
#: fed text whose newlines survived, which is why `records_from` builds its
#: `StringIO` with `newline=""` and the adapter opens its file the same way.
HEADER_LINE: Final[int] = 1

#: The encoding a watchlist is read as.
#:
#: `utf-8-sig` rather than `utf-8`, and not as a convenience: a reviewed CSV
#: opened and saved in Excel gains a byte-order mark, and under plain `utf-8`
#: that mark becomes part of the first header cell. The refusal that follows
#: names one undefined column and one missing column whose printed names are
#: indistinguishable, which is the least actionable message this module could
#: produce. `utf-8-sig` reads a file with the mark and a file without it.
WATCHLIST_ENCODING: Final[str] = "utf-8-sig"


class WatchlistError(ImproperlyConfigured):
    """The selected watchlist file cannot be read as an inventory.

    An `ImproperlyConfigured` subclass, deliberately, and the boundary is the
    point. The watchlist is governed reference data (`CPM-AD-14`), so a malformed
    one is a misconfigured deployment and an operator sent to the file is being
    sent to the right place -- whereas `collectors/tasks.py`'s
    `InventoryRecordError` is a `ValueError` about a *document* and would send
    the same operator looking for a broken source.

    A named subclass rather than raising `ImproperlyConfigured` directly, so a
    case can assert *this* refusal rather than any misconfiguration, and so the
    startup stages' own exception stays theirs. It adds no startup condition:
    `src/config/startup/` is where those live and this is a run-time refusal
    raised from a domain application, which the startup audits do not scan.
    """


def _watchlist_directory(module: str) -> Path:
    """Return the directory the reviewed files live in, or refuse the installation.

    `strict=True` asks the OS to resolve every path component and follow symlinks,
    so an editable install whose `collectors/` is a link into a checkout resolves
    to the checkout -- which is where the files actually are.
    `config/component/loader.py` computes its own path the same way and for the
    same reason.

    Called at import, and this module is imported from `config/settings/base.py`,
    so an unresolvable path would otherwise surface as a raw `OSError` in the
    middle of settings import -- a traceback with no file name in it, during the
    one phase of startup that has nothing else to say. An installation that
    shipped the modules and dropped the tree they sit in is a misconfiguration,
    and it says so.

    Takes the module's path rather than reading `__file__` itself, so the refusal
    is reachable from a case: `__file__` for a module being imported names a file
    that exists, and a branch that could only be provoked by deleting the module
    out from under the interpreter would be an unreachable line and a
    `pragma: no cover` that `tests/unit/test_coverage_policy.py` bans.

    Args:
        module: The location of the module the `data/` tree sits beside --
            `__file__` in production.

    Returns:
        The `data/` directory beside it.

    Raises:
        WatchlistError: When that location cannot be resolved.

    """
    try:
        here = Path(module).resolve(strict=True)
    except OSError as unresolvable:
        message = (
            f"the watchlist directory cannot be resolved from {module!r}: {type(unresolvable).__name__}: "
            f"{unresolvable}. The reviewed files ship beside this module (CPM-AD-29); an installation "
            f"without them cannot ingest an inventory."
        )
        raise WatchlistError(message) from unresolvable
    return here.parent / "data"


#: Where the reviewed files live: beside this module, in the wheel and in a
#: checkout alike. See the module docstring for why it is not computed from
#: `BASE_DIR`.
WATCHLIST_DIRECTORY: Final[Path] = _watchlist_directory(__file__)


def watchlist_path(*, local: bool) -> Path:
    """Return the watchlist file this component reads, by locality.

    Pure, and pure on purpose. It reads no environment variable, imports no
    `config`, and touches no filesystem -- which is what lets it live in a domain
    application under `AD-4` while `CPM-AD-29`'s `config.locality.is_local()`
    still decides. `config/settings/base.py` composes the two.

    Args:
        local: Whether this process is running locally. `config.locality`'s
            `is_local()` is the only intended source, and it fails closed: absent,
            empty and unrecognized `COMPONENT_RUNTIME` values are all False, so
            everything that is not a declared local run reads the production file.

    Returns:
        The path to the development subset when `local`, and to the production
        watchlist otherwise. The file is not read and is not required to exist:
        a component that never ingests never needs one, and the refusal for a
        missing file belongs to the read.

    """
    return WATCHLIST_DIRECTORY / (DEVELOPMENT_WATCHLIST if local else PRODUCTION_WATCHLIST)


def records_from(text: str, *, watchlist: Path | str) -> list[dict[str, str | int]]:
    """Turn a whole watchlist into records, or refuse it.

    Pure: it opens nothing and knows nothing about where the text came from
    beyond the name it puts in its messages. Every refusal about *content* is
    here, which is what lets the column contract be measured against strings
    rather than against files.

    The whole text is turned into records before anything is returned.
    `CPM-FR-42`'s "no run partially ingests a malformed source" starts here rather
    than at `records_in`: a generator yielding rows until it hit a bad one would
    hand the collector a prefix.

    Args:
        text: The file's contents, with its newlines intact -- a quoted cell may
            span physical lines, and text whose newlines have been normalized
            away makes `csv`'s own line counter, and therefore every refusal that
            names a line, wrong.
        watchlist: What to call the file in a refusal. A `Path` in production; a
            case that parses a literal may pass any name.

    Returns:
        One record per row, in the file's own order. Required columns are always
        present; an optional column is present only where the row populated it,
        which is what the record contract reads as the difference between a
        stated `0` and a source that did not say.

    Raises:
        WatchlistError: When the text carries no header, a header that is not
            exactly the declared columns, no rows, a blank line, a ragged row, a
            blank required cell, a cell that is not a count or is one the schema
            will not hold, an over-long key or name, or one package key twice.

    """
    # `newline=""` on the way in, as `csv`'s own documentation requires: the
    # module does its own newline handling, and a reader fed text whose line
    # endings were translated splits a quoted cell that legitimately spans lines.
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        rows = list(reader)
    except csv.Error as unparsable:
        # An unterminated quote, or a field past `csv.field_size_limit()`. Refused
        # as a misconfigured file rather than left to escape: it leaves this
        # module as a bare `csv.Error`, which nothing between here and the Celery
        # task turns into something naming the file.
        message = (
            f"the watchlist at {watchlist} is not readable as CSV: {type(unparsable).__name__}: "
            f"{unparsable}, at or before line {reader.line_num}. A watchlist is a delimited file changed "
            f"by review (CPM-AD-29)."
        )
        raise WatchlistError(message) from unparsable

    if not rows:
        message = (
            f"the watchlist at {watchlist} is empty and carries not even a header row. Every watchlist "
            f"declares the columns {sorted(WATCHLIST_COLUMNS)} on line {HEADER_LINE}."
        )
        raise WatchlistError(message)

    columns = _header(rows[0], watchlist=watchlist)
    records = [
        _record(cells, columns=columns, watchlist=watchlist, line=line)
        for line, cells in enumerate(rows[1:], start=HEADER_LINE + 1)
    ]
    _require_rows(records, watchlist=watchlist)
    _require_distinct_keys(records, watchlist=watchlist)
    return records


def _header(cells: Sequence[str], *, watchlist: Path | str) -> tuple[str, ...]:
    """Refuse a header that is not exactly the declared columns, and return it normalized.

    Surrounding whitespace is stripped and the *stripped* names are what every
    row is keyed by. That is one decision rather than two: a header spelled
    `source_package_key, package_name` -- which is what hand-editing produces --
    would otherwise pass a check made against stripped names and then be indexed
    by unstripped ones, and the `KeyError` that followed would escape this module
    entirely rather than becoming a refusal naming the file.

    Args:
        cells: The header row as read.
        watchlist: What to call the file in a refusal.

    Returns:
        The column names, stripped, in the order the file declares them. The
        order is kept because the rows are positional; the *set* is what is
        checked, so any order is accepted.

    Raises:
        WatchlistError: When a column is named twice, or when the set of columns
            differs from `WATCHLIST_COLUMNS` in either direction.

    """
    columns = tuple(name.strip() for name in cells)
    repeated = sorted({name for name in columns if columns.count(name) > 1})
    if repeated:
        message = (
            f"the watchlist at {watchlist} names the column(s) {repeated} more than once on line "
            f"{HEADER_LINE}. A repeated column makes every cell under it ambiguous, and choosing one of "
            f"them would be an invention."
        )
        raise WatchlistError(message)
    undefined = sorted(set(columns) - WATCHLIST_COLUMNS)
    missing = sorted(WATCHLIST_COLUMNS - set(columns))
    if undefined or missing:
        message = (
            f"the watchlist at {watchlist} declares a header this contract does not define: undefined "
            f"column(s) {undefined}, missing column(s) {missing} on line {HEADER_LINE}. The header is "
            f"exactly {sorted(WATCHLIST_COLUMNS)} in any order -- an extra column is refused rather than "
            f"ignored, because ingestion never asserts a mapping (CPM-FR-42, CPM-FR-1) and a silently "
            f"dropped column is a reviewer who believes they supplied one."
        )
        raise WatchlistError(message)
    return columns


def _record(
    cells: Sequence[str],
    *,
    columns: Sequence[str],
    watchlist: Path | str,
    line: int,
) -> dict[str, str | int]:
    """Turn one row into a record, or refuse the row.

    Args:
        cells: The row as read, positionally.
        columns: The normalized header, so a cell can be named by its column.
        watchlist: What to call the file in a refusal.
        line: Which line the row is on.

    Returns:
        The record, carrying every required column and only those optional ones
        the row populated. An omitted key is what the record contract reads as
        *missing*, and it is why a blank cell and a `0` do not collapse.

    Raises:
        WatchlistError: When the row is blank or ragged, when a required cell is
            blank, when a text cell is longer than the column it lands in, or
            when a count is not a whole number the schema can hold.

    """
    if not cells:
        # `csv` yields an empty list for a blank line, and `DictReader` used to
        # skip them silently -- which made a stray blank line a row nobody
        # reviewed and a short row a refusal, for no reason a reader could state.
        # Both are now the same thing: a line that is not a record.
        message = (
            f"the watchlist at {watchlist} carries a blank line on line {line}. Every line after the "
            f"header names a package; a blank one is an edit nobody finished."
        )
        raise WatchlistError(message)
    if len(cells) != len(columns):
        message = (
            f"the watchlist at {watchlist} carries a ragged row on line {line}: it has {len(cells)} cells "
            f"and its header declares {len(columns)}. A row with the wrong number of cells puts every "
            f"value under the wrong column."
        )
        raise WatchlistError(message)

    row = dict(zip(columns, (cell.strip() for cell in cells), strict=True))
    record: dict[str, str | int] = {}
    for column in REQUIRED_COLUMNS:
        value = row[column]
        if not value:
            message = (
                f"the watchlist at {watchlist} leaves {column} blank on line {line}. All of "
                f"{list(REQUIRED_COLUMNS)} are required on every row: the first two are what the package "
                f"is filed under and called, and the two counts together are the internal usage breadth "
                f"CPM-FR-4 ranks by (PRD Open Question 3b)."
            )
            raise WatchlistError(message)
        if column in _TEXT_COLUMNS:
            record[column] = _text(value, column=column, watchlist=watchlist, line=line)
        else:
            record[column] = _count(value, column=column, watchlist=watchlist, line=line)

    for column in OPTIONAL_COLUMNS:
        value = row[column]
        if not value:
            # Omitted rather than written as null, and the two are the same thing
            # to `records_in` -- it reads a missing key and a null the same way.
            # Omitting is what makes the document say what the blank cell said:
            # nothing.
            continue
        record[column] = _count(value, column=column, watchlist=watchlist, line=line)
    return record


def _text(value: str, *, column: str, watchlist: Path | str, line: int) -> str:
    """Refuse a key or a name longer than the column it lands in.

    The two bounds are different because the two columns are: see
    `MAX_SOURCE_PACKAGE_KEY` and `MAX_PACKAGE_NAME`. Refused here rather than left
    to resolution because SQLite ignores `max_length` and PostgreSQL raises -- an
    unrefused value is a stored row on a developer's machine and a failed run in
    the gate (`R-5`) -- and refused here rather than left to the record contract
    because only this layer can say which line.

    Args:
        value: The cell, already stripped and known to be non-empty.
        column: Which column, for the message and for the bound.
        watchlist: What to call the file in a refusal.
        line: Which line, for the message.

    Returns:
        The value, unchanged.

    Raises:
        WatchlistError: When it is longer than its column holds.

    """
    limit = MAX_SOURCE_PACKAGE_KEY if column == KEY_COLUMN else MAX_PACKAGE_NAME
    if len(value) > limit:
        message = (
            f"the watchlist at {watchlist} declares a {column} of {len(value)} characters on line {line}, "
            f"and the column that holds it takes {limit}. SQLite would store it truncated and PostgreSQL "
            f"would refuse it, so the row would exist on a developer's machine and fail in the gate -- the "
            f"parity gap is refused here instead."
        )
        raise WatchlistError(message)
    return value


def _count(value: str, *, column: str, watchlist: Path | str, line: int) -> int:
    """Refuse a cell that is not a count this schema can hold, and return the count it is.

    Args:
        value: The cell, already stripped and known to be non-empty.
        column: Which column, for the message.
        watchlist: What to call the file in a refusal.
        line: Which line, for the message.

    Returns:
        The count.

    Raises:
        WatchlistError: When the cell is not a non-negative whole number written
            in ASCII digits, or is larger than `MAX_SIGNAL`. A sign, a decimal
            point, a thousands separator and a non-ASCII digit are all refused
            rather than coerced: `int()` accepts a surprising amount of that, and
            a watchlist is reviewed by reading it. The ceiling is refused here
            rather than left to the column for the parity reason `_text` gives,
            and rather than left to the record contract so the message can name
            the line.

    """
    if not (value.isascii() and value.isdigit()):
        message = (
            f"the watchlist at {watchlist} declares {column}={value!r} on line {line}, which is not a "
            f"count. A usage signal is a whole number written in digits and zero or more of them; leave "
            f"the cell empty to record that the source did not say, which is stored as missing and stays "
            f"distinguishable from zero (PRD Appendix A.1 data rules)."
        )
        raise WatchlistError(message)
    count = int(value)
    if count > MAX_SIGNAL:
        message = (
            f"the watchlist at {watchlist} declares {column}={value} on line {line}, which is larger than "
            f"the {MAX_SIGNAL} a usage signal column holds. PostgreSQL refuses it and SQLite stores it, so "
            f"the row would exist on a developer's machine and fail in the gate (R-5)."
        )
        raise WatchlistError(message)
    return count


def _require_rows(records: Sequence[dict[str, str | int]], *, watchlist: Path | str) -> None:
    """Refuse a watchlist that names no packages at all.

    The production file ships with its header and no rows, because its content is
    an organizational decision (`CPM-AD-29`). This is what makes that safe: a
    component deployed before the file has been reviewed fails its ingestion
    loudly, rather than handing the collector an empty document that would record
    every package the inventory has ever named as absent, permanently, in a log
    nothing may correct.

    Args:
        records: Every record the file produced.
        watchlist: What to call the file in a refusal.

    Raises:
        WatchlistError: When there are none.

    """
    if not records:
        message = (
            f"the watchlist at {watchlist} carries a header and no rows, so it names no packages at all. "
            f"That is a watchlist awaiting review rather than an inventory of nothing: an empty inventory "
            f"is indistinguishable from a source that broke, and ingesting one would record every package "
            f"the inventory has ever named as absent (CPM-FR-42, CPM-AD-25)."
        )
        raise WatchlistError(message)


def _require_distinct_keys(records: Sequence[dict[str, str | int]], *, watchlist: Path | str) -> None:
    """Refuse a watchlist naming one package key twice.

    `CPM-FR-42`: a repeated source package key fails the run. Two rows for one key
    are two claims about one package's usage in one observation, and there is no
    rule for choosing between them that is not an invention. The record contract
    refuses the same thing one step later, from any adapter; this refusal is what
    can name the key in the file a reviewer is editing.

    **Names are deliberately not checked here.** Two rows may legitimately be
    proposed for one name and they are not the same package -- and resolution is
    where that collides, on `canonical_name`'s unique constraint, one record at a
    time, so the sweep carries on and the run reports `partial` rather than the
    whole file being refused for a collision the source is entitled to have.

    Args:
        records: Every record the file produced.
        watchlist: What to call the file in a refusal.

    Raises:
        WatchlistError: When any source package key appears more than once.

    """
    seen: set[str] = set()
    repeated: set[str] = set()
    for record in records:
        key = str(record[KEY_COLUMN])
        if key in seen:
            repeated.add(key)
        seen.add(key)
    if repeated:
        message = (
            f"the watchlist at {watchlist} names the package key(s) {sorted(repeated)} more than once. One "
            f"observation records one fact per package (CPM-AD-7); two rows for one key are two claims "
            f"about the same package, and choosing between them would be an invention (CPM-FR-42)."
        )
        raise WatchlistError(message)


class WatchlistAdapter:
    """Reads one reviewed CSV watchlist and answers the record document.

    The `Transport` `CPM-AD-29` substitutes at the collector base's seam. It
    satisfies the protocol structurally -- one `fetch` -- and
    `tests/unit/django_apps/test_watchlist.py` pins what that `fetch` returns as
    well as that it exists, because `runtime_checkable` sees method names only.

    It owns the file and nothing else: opening it, decoding it, and refusing the
    two things only a file can be wrong about. What the text *says* is
    `records_from`'s.

    The file is read on every `fetch` and nothing is cached. A daily sweep reads a
    file of a few thousand lines, and a cached parse would mean an operator who
    corrected the watchlist had to restart the worker to be believed.
    """

    def __init__(self, *, path: Path) -> None:
        """Bind the one file this adapter reads.

        Args:
            path: The watchlist to read, from `watchlist_path`. Held rather than
                recomputed, so the file an adapter reads is fixed at the moment
                it was declared and cannot change under a running process.

        """
        self._path = path

    @property
    def path(self) -> Path:
        """The watchlist file this adapter reads.

        Returns:
            The path it was constructed with. Exposed so a refusal a caller
            raises, and a case asserting which file was selected, can name it
            without reaching into the instance.

        """
        return self._path

    def fetch(self, source: str, *, headers: Mapping[str, str] | None = None) -> Payload:
        """Read the watchlist and record it as the record document.

        Args:
            source: The locator the collector declared, recorded on the `Payload`
                and **otherwise ignored**. `INVENTORY_SOURCE` names the run
                rather than a resource (`CPM-AD-29`); the file comes from this
                adapter's own construction, so a caller cannot redirect it by
                passing a different locator.
            headers: Accepted and ignored. The parameter is keyword-only and
                defaulted in `Transport` for exactly this case -- a substituted
                transport that speaks no HTTP -- and the ingestion collector
                declares no headers and no response cache anyway.

        Returns:
            A `Payload` carrying `found=True`, the record document as its body,
            and `status_code=None`, which is `core/transport.py`'s stated meaning
            of "this source does not speak HTTP".

        Raises:
            WatchlistError: When the file is missing, unreadable or not text, and
                for every refusal `records_from` makes about what it says. Raised
                before any document exists, so a malformed file fails the run
                with nothing ingested.

        """
        return Payload(
            source=source,
            found=True,
            body=json.dumps(records_from(self._read(), watchlist=self._path)),
            status_code=None,
        )

    def _read(self) -> str:
        """Return the file's text, or refuse the file.

        Opened with `newline=""` so the newlines inside a quoted cell survive --
        `csv` does its own newline handling, and `records_from` counts on the
        line numbers staying true -- and decoded as `WATCHLIST_ENCODING`.

        Returns:
            The whole file.

        Raises:
            WatchlistError: When the file cannot be opened or read, or is not
                text this component can decode.

        """
        try:
            with self._path.open(encoding=WATCHLIST_ENCODING, newline="") as watchlist:
                return watchlist.read()
        except OSError as unreadable:
            message = (
                f"the watchlist at {self._path} could not be read: {type(unreadable).__name__}: "
                f"{unreadable}. The inventory source is a reviewed file this component ships "
                f"(CPM-AD-29); a run is refused rather than treated as an empty inventory, which would "
                f"record every package it should have named as absent (CPM-FR-42)."
            )
            raise WatchlistError(message) from unreadable
        except UnicodeDecodeError as undecodable:
            message = (
                f"the watchlist at {self._path} is not {WATCHLIST_ENCODING}: {undecodable}. A watchlist is "
                f"reviewed in a pull-request diff and is text (CPM-AD-29)."
            )
            raise WatchlistError(message) from undecodable
