"""Resolution: the only thing in this product that writes a package row.

`CPM-AD-25`: "the collector never writes the package table. For a source record
naming a package that does not exist yet, it calls `identity`'s resolution
service, which creates the shell at `unmapped` confidence." `CPM-AD-14` is the
other half and is unchanged: identity is mutated by resolution or by the override
path, and by nothing else. This module is the door that sentence names.

**Three doors, and they are deliberately not one.** `resolve_package_shell` is
create-only: a package named by the inventory for the first time gets an identity
row *before* anything has resolved it, and `unmapped` is the honest value for that
row rather than a placeholder waiting to be corrected. `record_resolution` is the
second, added by `CPM-IDENTITY-S02`: it finds a package that already exists and
writes what a resolver concluded about it. Neither is the other's special case --
one may only insert and the other may only update, so a caller cannot reach the
wrong behaviour by passing a different argument, and ingestion's contract stayed
settled while resolution's was written.

`override_identity` is the third, added by `CPM-IDENTITY-S05`, and it is the
other half of `CPM-AD-14` -- the human path. It is not a variant of the second:
`record_resolution` takes what a *resolver* concluded and may not lower a
`verified` identity, while this takes what a *person* decided, requires a
permission and a reason, raises the confidence to `verified`, and writes an
append-only audit row recording who, when, from what and why. `CPM-FR-3` makes it
the only human write in the product that mutates governed reference data, which
is why it carries obligations no other door here has.

**A corrected name leaves the mapping rows exactly as they were, and that is
worth saying out loud.** `PackageMapping` records what resolution concluded about
each mapping of a package, and those conclusions were reached under the identity
the override has just replaced -- so after a correction the outcome rows describe
a package by a name it no longer has. That is the honest state rather than a
defect: the rows are keyed on the package's integer primary key, not on its name
(`CPM-AD-3`), so they still describe the same *package*, and what an auditor
needs to know -- that they predate the correction -- is answerable from
`PackageMapping.resolved_at` against the `IdentityOverride`'s `observed_at`.
Re-resolving under the corrected identity is a collector's job and happens on the
next sweep; a door that invalidated the mappings here would be discarding
findings on the strength of a name.

**This module opens exactly one transaction, and it is that one.** Everywhere
else the boundary is the caller's (see below); `override_identity` is the
exception `CPM-AD-23` describes rather than a departure from it -- the correction
and its audit row are one atomic unit, "never `transaction.on_commit`, never a
follow-up task", and there is no caller that could place the boundary for them,
because a correction committed without its audit row is precisely the state
`CPM-FR-32` exists to make impossible. Nesting it inside a caller's own
`atomic()` is safe and is the ordinary case: Django opens a savepoint, and the
pair still commits or rolls back together.

`CPM-FR-1` is explicit that a resolution which cannot establish a mapping records
nothing rather than a guess. `resolve_package_shell` therefore asserts no mapping
at all, and `record_resolution` writes a mapping's value only when the resolution
says it was `established`.

**Resolution takes its mappings; it does not find them.** There is no PyPI
client, no conda-forge client and no purl builder anywhere in `src/`, and the
collectors that will supply them belong to `CPM-EP-CURRENCY`, which depends on
this epic. So `record_resolution` is a *recorder*: it is handed what a resolver
concluded and is responsible for writing it correctly, refusing what it must, and
preserving what it may not lower.

**The name and the key are two values, and were one until `CPM-IDENTITY-S07`.**
The inventory source supplies both: `package_name` is what the package is
called, and `source_package_key` is what the source files it under. The name
becomes `canonical_name` -- "the one *correctable* name", correctable precisely
because nothing in this product references a package by it, and corrected by
`CPM-IDENTITY-S02` when it establishes a real identity -- and the key becomes
`associator_key`, which `CPM-FR-2` requires so the resolution "can be re-derived
and disputed rather than merely trusted".

**The pair is never written after creation, and it is now unique.** Both doors
find a package by `(identity_source, associator_key)`, and neither writes either
field on a row that already exists: `resolve_package_shell` puts them in the
`get_or_create` lookup rather than in `defaults`, and `record_resolution` leaves
both out of its `update_fields`. Rewriting the pair while correcting a name is
what creates a duplicate shell on the next sweep -- the trap `CPM-IDENTITY-S06`
and `-S07` both recorded -- and `Package.Meta`'s partial
`one_package_per_source_key` is the database's half of the same rule.

**The lookup is on `(identity_source, associator_key)` and never on the name.**
While the two were one value, keying on the name was harmless because the name
*was* the key. Once they are separate it is not: `package_name` carries no
uniqueness guarantee from any layer -- the adapter and the record contract both
refuse a repeated *key* and neither says anything about names -- so a name-keyed
lookup would collapse two packages that happen to agree on a name onto one row,
discard the second key silently, hang both keys' evidence off the first shell,
and report the run `SUCCEEDED`. It would also stop matching the day
`CPM-IDENTITY-S02` corrects a name, which is the duplicate-shell trap that story
has to close.

Keyed on the pair, two rows with different keys and one name are two calls that
both reach the `create`, and `canonical_name`'s unique constraint refuses the
second. The record fails, the sweep carries on, the run finalizes `partial`, and
the collision is in the ledger where somebody can see it.

**Get-or-create, not create, and `canonical_name` is create-only.** A sweep runs
daily over a source that names the same packages every time, so the second run
must find the rows the first one made rather than refusing. It is also not an
`update_or_create`, and that is what puts `canonical_name` in `defaults`: an
existing package row is left exactly as it is, including its `confidence` and
including its name. Ingestion must never lower a `verified` identity back to
`unmapped` -- PRD Appendix A.1's data rules state that in so many words -- and it
must never overwrite a name a reviewer or `CPM-IDENTITY-S02` corrected with
whatever the source is calling the package this morning. "Get or create" delivers
both by construction rather than by a branch somebody has to remember.

**Refusals are `ValueError`s and they are raised before the row.** This is a
domain service, so `ImproperlyConfigured` is wrong: that exception belongs to the
two startup stages, and raising it here would make a bad inventory record look
like a misconfigured process. The shape of each check is `core/ledger.py`'s
`_require_*(value, *, field)`, which is the house form for "this input cannot
describe what it claims to".

**The provenance is written even though the mapping is not.** `CPM-FR-2` wants
the resolver that established an identity and the key it matched on recorded so
the resolution "can be re-derived and disputed rather than merely trusted", and a
shell is a resolution -- a very small one. It matters more here than for a real
resolution, not less: the shell's name is corrected out from under it by
`CPM-IDENTITY-S02`, and a shell with no `associator_key` is a package the next
sweep cannot match back to the record that created it. Neither field asserts a
mapping, and `confidence` stays `unmapped`.

**The transaction boundary is the caller's** (`CPM-AD-23`). The shell and the
evidence row that occasioned it commit together, one package at a time, and the
caller is what knows where that boundary is -- so nothing here opens a
transaction the caller could be *outside* of. A service that wrapped its own
would put the shell outside the block the snapshot is in, and a snapshot write
that then failed would leave a package row nothing ever observed.

The one qualification, stated rather than left to be discovered: `get_or_create`
opens a savepoint around its `create`, so that losing the unique-constraint race
rolls back to a known point and re-reads instead of poisoning the caller's
transaction. That is a savepoint *within* the caller's block rather than a
boundary of its own -- the shell still commits or rolls back with the snapshot
beside it.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Final

import structlog
from django.db import transaction

from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.core.ledger import current_trace_id
from conda_package_supply_chain_monitor.core.roles import IDENTITY_OVERRIDE_PERMISSION
from conda_package_supply_chain_monitor.identity.models import ESTABLISHED
from conda_package_supply_chain_monitor.identity.models import MAPPED_FIELDS
from conda_package_supply_chain_monitor.identity.models import Feedstock
from conda_package_supply_chain_monitor.identity.models import IdentityConfidence
from conda_package_supply_chain_monitor.identity.models import IdentityOverride
from conda_package_supply_chain_monitor.identity.models import MappingKind
from conda_package_supply_chain_monitor.identity.models import MappingOutcome
from conda_package_supply_chain_monitor.identity.models import Package
from conda_package_supply_chain_monitor.identity.models import PackageMapping

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence
    from datetime import datetime

    from django.db import models

    from conda_package_supply_chain_monitor.core.clock import Clock
    from django_service.users.models import User

__all__ = [
    "ASSOCIATOR_KEY_FIELD",
    "ASSOCIATOR_KEY_LENGTH",
    "CANONICAL_NAME_FIELD",
    "CANONICAL_NAME_LENGTH",
    "DISPLAY_NAME_FIELD",
    "DISPLAY_NAME_LENGTH",
    "FEEDSTOCK_NAME_FIELD",
    "FEEDSTOCK_NAME_LENGTH",
    "FEEDSTOCK_URL_LENGTHS",
    "IDENTITY_FIELD",
    "OVERRIDE_PERMISSION_MISSING",
    "OVERRIDE_RECORDED_EVENT",
    "OVERRIDE_REFUSED_EVENT",
    "PACKAGE_FIELD_LENGTHS",
    "Correction",
    "FeedstockMapping",
    "OverrideError",
    "RecordedResolution",
    "Resolution",
    "ResolutionError",
    "override_identity",
    "record_resolution",
    "resolve_package_shell",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _column_length(model: type[models.Model], field: str) -> int:
    """Return how wide one column is, read off the model rather than restated.

    `getattr` with a default rather than an attribute access: `get_field` is
    annotated as returning any of three field kinds, two of which have no
    `max_length`, and a `cast` would be asserting something about the schema that
    this function is trying to read. `0` is the honest answer for a column with
    no bound -- and also a value that would refuse everything silently, which is
    why `tests/unit/django_apps/test_identity_services.py` reconciles every
    constant below against its field.

    One function rather than the idiom written out seven times, so a column
    losing its bound fails the same way wherever it happens.

    Args:
        model: The model declaring the column.
        field: The column's name.

    Returns:
        Its `max_length`, or `0` when it declares none.

    """
    return int(
        getattr(
            model._meta.get_field(field),  # noqa: SLF001 - `_meta` is Django's own public-by-convention API
            "max_length",
            0,
        )
        or 0,
    )


#: The column a shell's name is written to, named once because the length bound
#: below is read off it. A literal 128 here would be a second declaration of a
#: width `identity/models.py` already owns, and the two would drift the day the
#: column is widened.
CANONICAL_NAME_FIELD: Final[str] = "canonical_name"

#: How long a shell's name may be, read off the column rather than restated.
#:
#: Public because it is also the bound a *caller* has to apply. The inventory
#: record contract refuses an over-long package name so that the whole document
#: is refused rather than one record failing mid-sweep (`CPM-FR-42`: "no run
#: partially ingests a malformed source"), and it cannot do that against a number
#: only this module knows. `_require_name` below applies the same bound for a
#: caller that did not.
#:
#: Read through `_column_length` above, which is the one place that idiom lives.
#: `tests/unit/django_apps/test_identity_services.py` reconciles the value
#: against the field, so a column that stopped declaring one fails there rather
#: than silently admitting every key.
CANONICAL_NAME_LENGTH: Final[int] = _column_length(Package, CANONICAL_NAME_FIELD)

#: The column a shell's source key is written to, and how long it may be.
#:
#: A *different* column from `canonical_name` and a different bound, which is the
#: whole of what `CPM-IDENTITY-S07` separated. The key is what a source files a
#: package under -- an identifier, potentially long -- and the name is what the
#: product displays. Measuring the key against the name's narrower bound would
#: refuse a legitimately long key for a column it does not occupy.
#:
#: Read off the field the same way, and public for the same reason: the record
#: contract applies this bound to a whole document before any row is written.
ASSOCIATOR_KEY_FIELD: Final[str] = "associator_key"
ASSOCIATOR_KEY_LENGTH: Final[int] = _column_length(Package, ASSOCIATOR_KEY_FIELD)

#: The column a display name is written to, and how long it may be.
#:
#: `CPM-IDENTITY-S05`'s override is the only thing in this product that writes
#: it: `identity/models.py` says a blank display name means *missing* and the
#: reporting layer falls back to the canonical name, and `Resolution` deliberately
#: carries no field for it -- what a human is shown is not a mapping `CPM-FR-1`
#: asks a resolver to establish. Read off the field on the same terms as the two
#: above, so widening the column widens the refusal with it.
DISPLAY_NAME_FIELD: Final[str] = "display_name"
DISPLAY_NAME_LENGTH: Final[int] = _column_length(Package, DISPLAY_NAME_FIELD)

#: The column a feedstock's name is written to, and how long it may be.
#:
#: Read off `Feedstock` the same way and for the same reason: the name is a value
#: a caller hands in, `feedstock_name_is_present` refuses a blank one and the
#: column refuses an over-long one, and a refusal arriving as an `IntegrityError`
#: from inside a loop names neither the feedstock nor which of the two rules it
#: broke. Public on the same terms as the two above.
FEEDSTOCK_NAME_FIELD: Final[str] = "name"
FEEDSTOCK_NAME_LENGTH: Final[int] = _column_length(Feedstock, FEEDSTOCK_NAME_FIELD)

#: Every other bounded column a caller can supply a value for, and how wide each
#: is. Read off the model, so widening a column widens the refusal with it.
#:
#: The rule these serve is the one the two names already carry: SQLite ignores
#: `max_length` and PostgreSQL raises, so an unrefused over-long purl is a
#: working row locally and a failed run in the gate (`R-5`). Applying it to the
#: names and not to the mappings was an inconsistency rather than a decision, and
#: a table is what keeps a seventh column from being added without it.
#:
#: `canonical_name` is deliberately not here: it has its own refusal, with its
#: own message about what a nameless package costs. `alternative_purls` and
#: `cpes` are not here either -- a `JSONField` carries no width, and what is
#: checked on those is the shape of their elements.
PACKAGE_FIELD_LENGTHS: Final[dict[str, int]] = {
    name: _column_length(Package, name)
    for name in ("source_repository_url", "primary_purl", "primary_type", "conda_purl")
}

#: The feedstock URLs, on the same terms. Kept apart from the package table above
#: because they are read off a different model, and a single flat table would
#: have to encode which.
FEEDSTOCK_URL_LENGTHS: Final[dict[str, int]] = {
    name: _column_length(Feedstock, name) for name in ("url", "metadata_url")
}


#: The two events an override emits -- the refused one and the recorded one --
#: and the reason a refusal on the permission carries.
#:
#: Named constants rather than literals at the call site, on the shape
#: `config/authorization/mapper.py` established for every authorization refusal in
#: this repository: a dotted `authorization.<event>` name, a `reason=` drawn from
#: a constant, and the acting identity as a kwarg. Declared here so the case that
#: asserts what was logged and the code that logs it cannot drift.
#:
#: `authorization.`-prefixed although this is a domain service, because the events
#: are authorization decisions and an operator reading the log filters on the
#: prefix rather than on which application happened to make the call.
#:
#: **Both directions, not only the refusal.** A log carrying only refusals would
#: show an operator every rejected correction of governed reference data and not
#: one accepted one -- and the accepted ones are what an auditor asks about.
#: `CPM-AD-13` makes every authorization change an event; a correction that
#: succeeded is one.
OVERRIDE_REFUSED_EVENT: Final[str] = "authorization.override_refused"
OVERRIDE_RECORDED_EVENT: Final[str] = "authorization.identity_overridden"
OVERRIDE_PERMISSION_MISSING: Final[str] = "override_permission_missing"

#: The attribute the acting identity is read from, matching
#: `config/authorization/mapper.py`'s `_IDENTITY_FIELD`. Read through `getattr`
#: with a default rather than accessed directly: `AnonymousUser` does not declare
#: it, and neither would a user model from a component that has not adopted the
#: platform's identity column -- and an `AttributeError` raised while *logging a
#: refusal* would lose the record of the refusal as well as raising the wrong
#: exception.
IDENTITY_FIELD: Final[str] = "idp_subject"


class OverrideError(ValueError):
    """A human correction of a package identity was refused.

    A separate type from `ResolutionError`, and the separation is the point:
    "this resolver handed over something unusable" and "this person may not do
    that, or did not say why" are refusals a caller has to be able to tell apart
    -- the surface that will call this door (`CPM-APP-S05`) answers one of them
    with a form error and the other with a refusal to act at all.

    One type rather than a hierarchy, on the same terms `ResolutionError` states:
    the detail is in the message, and no caller branches on which check failed.
    What distinguishes the permission refusal from the rest is not the class, it
    is the log record -- `OVERRIDE_REFUSED_EVENT` above, naming the actor.

    A `ValueError` subclass, matching every other "this declaration or input is
    unusable" in this product, so a caller catching one catches them all.
    Deliberately **not** `django.core.exceptions.PermissionDenied`: that
    exception is a request-layer instruction to render a 403, and this service is
    reached by no request today -- see the story's design notes for why the
    permission is enforced at the service boundary rather than at a surface that
    does not exist.
    """


class ResolutionError(ValueError):
    """A package identity could not be established from what was supplied.

    One type rather than a hierarchy, on the same terms as `core/models.py`'s
    `AppendOnlyError`: every occurrence is a defect in the record that was handed
    over or in the caller that handed it, and no caller branches on which check
    failed. The detail is in the message.

    A `ValueError` subclass, matching `core/collection.py`'s
    `CollectorConfigurationError`, `core/registry.py`'s `CollectorRegistryError`
    and `core/freshness.py`'s `FreshnessError`: every "this declaration or input
    is unusable" in this product is a `ValueError`, so a caller catching one
    catches them all. Deliberately **not** `ImproperlyConfigured`, which is
    reserved for the two startup stages -- a malformed inventory record is not a
    misconfigured process, and a sweep that reported it as one would send an
    operator to the settings.
    """


@dataclass(frozen=True, slots=True)
class FeedstockMapping:
    """One conda-forge feedstock a resolution established, as the resolver found it.

    A value rather than a `Feedstock` instance, because an unsaved model instance
    carries a manager, a primary key and a relation the caller would have to
    populate, and none of the three is part of what a resolver concluded. The
    service turns these into rows.

    Attributes:
        name: The feedstock's name on conda-forge. Required, because a nameless
            feedstock is *counted* -- `package.feedstocks` returns it, so "this
            package has a feedstock" reads true for a row naming nothing.
        url: Where the feedstock repository lives, or blank when the mapping is
            known by name and the URL is not established. Blank means missing
            (PRD Appendix A.1's data rules), never "none".
        metadata_url: Where the recipe metadata lives, on the same terms.

    """

    name: str
    url: str = ""
    metadata_url: str = ""


@dataclass(frozen=True, slots=True)
class Resolution:
    """What a resolver concluded about one package, handed over to be recorded.

    One object rather than fifteen keyword parameters, and that is not only about
    the signature: a resolution is a single conclusion, and passing it as one
    value is what lets a caller build it, log it and hand the same thing to the
    recorder rather than assembling it at the call site where a field is easy to
    forget.

    **The outcomes are supplied, never inferred.** A blank
    `source_repository_url` cannot say whether the repository was looked for and
    not found, was never looked for, or does not apply -- and an empty
    `feedstocks` cannot say whether the package genuinely has none. That is the
    whole of `CPM-FR-6`, and it is why `outcomes` is required rather than derived
    from which fields are populated.

    Attributes:
        identity_source: What established this identity, and half of the pair the
            package is found by (`CPM-FR-2`). Never written: see the module
            docstring.
        associator_key: The key that source filed the package under, and the
            other half of the pair. Never written either.
        confidence: What the resolution claims, as an `IdentityConfidence` value.
        outcomes: One `MappingOutcome` value per `MappingKind`, every kind named
            exactly once.
        canonical_name: The corrected name, or blank to leave the stored one
            alone. Correcting it is the ordinary outcome of a real resolution --
            the shell was named by whatever the inventory called the package --
            and it is safe precisely because nothing references a package by its
            name (`CPM-AD-3`). `display_name` is deliberately not here: it is
            what a human is shown rather than a mapping `CPM-FR-1` asks a
            resolver to establish, and the one path that sets it is
            `CPM-IDENTITY-S05`'s audited override.
        source_repository_url: The upstream VCS identity, written only when
            `MappingKind.SOURCE_REPOSITORY` is `established`.
        primary_purl: The primary release ecosystem's package URL, written only
            when `MappingKind.RELEASE_ECOSYSTEM` is `established`.
        primary_type: That ecosystem's purl type, written with it.
        conda_purl: The package URL naming this package as a conda artifact,
            written only when `MappingKind.CONDA_ARTIFACT` is `established`.
        alternative_purls: Every other derivable package URL, written only when
            `MappingKind.CROSS_ECOSYSTEM` is `established`.
        cpes: The CPE names, written with them.
        feedstocks: The conda-forge feedstocks, written only when
            `MappingKind.FEEDSTOCK` is `established` -- and legitimately empty
            then, which is the successful empty result `CPM-FR-6` keeps apart
            from `not_found`.

    """

    identity_source: str
    associator_key: str
    confidence: str
    outcomes: Mapping[str, str]
    canonical_name: str = ""
    source_repository_url: str = ""
    primary_purl: str = ""
    primary_type: str = ""
    conda_purl: str = ""
    alternative_purls: tuple[str, ...] = ()
    cpes: tuple[str, ...] = ()
    feedstocks: tuple[FeedstockMapping, ...] = ()


@dataclass(frozen=True, slots=True)
class Correction:
    """What a person decided a package's identity should be, and why.

    One object rather than three keyword parameters, for the reason `Resolution`
    is one rather than fifteen: a correction is a single human decision, and
    passing it as one value is what lets the surface that collects it build it,
    log it and hand the same thing to the service -- rather than assembling it at
    the call site, where the field somebody forgets is the reason.

    It carries the *reason* as well as the values, because `CPM-AD-14` makes the
    justification part of the decision rather than metadata about it: a correction
    with no reason is not a correction this product accepts, and separating the
    two would make it possible to build a well-formed one.

    Every field is a *statement about a field*, so "leave this alone" has to be
    expressible for each. It is the empty string for the name -- the ordinary case
    for an override that only raises the confidence -- and `None` for the display
    name, whose empty string means something else.

    **Every value is stripped before it is stored, and that is a rule rather than
    tidiness.** `canonical_name` is `unique=True`, so `" numpy "` and `"numpy"` are
    two rows to the database and one name to every person who reads them: an
    unstripped correction would slip past the collision check, past the unique
    index, and into every export and read surface as a near-duplicate of a package
    that already exists -- governed reference data acquiring two names for one
    thing through the product's one audited write, with nothing failing at the
    correction. The three `_require_*` helpers below normalise, and
    `tests/unit/django_apps/test_identity_overrides.py` asserts what is stored for
    a padded value on each field rather than only that a wholly blank one is
    refused.

    **There is no confidence field, and a correction therefore cannot lower one.**
    An override always writes `verified`, because `CPM-AD-4` says that value *is*
    an identity a person established. The cost is stated rather than hidden: a
    reviewer who looks at a package and concludes it genuinely has no upstream
    identity has no way to record that here. That is deliberate on two grounds.
    "There is no identity to find" is a finding about the world, which is a
    *resolution* -- `unmapped` with the outcome rows that say which mappings were
    looked for and not found (`CPM-FR-6`), none of which a correction carries. And
    a human write that lowered a confidence to `unmapped` would put the package
    straight back into `CPM-IDENTITY-S04`'s review queue it had just been taken
    out of, carrying an audit row saying a person verified it was unverifiable --
    a loop nothing in the product breaks. If the product later wants a reviewer to
    be able to say "looked, and there is nothing", it is a field here plus a
    validation plus a queue rule, and it is a decision for the story that adds it.

    Attributes:
        reason: Why the correction was made. Required and non-blank
            (`CPM-AD-14`); stored verbatim after stripping.
        canonical_name: The corrected name, or blank to leave the stored one
            alone. Correcting it is safe precisely because nothing in this product
            references a package by its name (`CPM-AD-3`).
        display_name: What a human should be shown, or `None` to leave the stored
            value alone. The empty string is *not* `None` here: it means "there is
            no display name", which PRD Appendix A.1's data rules make the honest
            spelling of missing, and clearing one a previous override set is a
            correction like any other. This is the only path in the product that
            writes the column -- `Resolution` deliberately carries no field for
            it, because what a human is shown is not a mapping `CPM-FR-1` asks a
            resolver to establish.

    """

    reason: str
    canonical_name: str = ""
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedResolution:
    """What `record_resolution` did, and not only what it was done to.

    A result type rather than a bare `Package`, because this door has two
    non-error outcomes and they are indistinguishable from the row alone. Every
    other refusal in the module raises; a `verified` identity holding a lower
    confidence claim *cannot*, because the findings are still recorded and the
    call still succeeded. Without this a caller would have to diff the row it
    passed in against the row it got back to learn that its claim was refused --
    and the collectors that will call this door log per package, which is exactly
    where "recorded" and "recorded except the part I asked for" have to be told
    apart.

    Attributes:
        package: The package as it now stands, with whatever this resolution
            wrote already applied.
        downgrade_refused: True when the stored confidence was `verified` and the
            claim was not, so the confidence and any corrected name were held
            back while the mappings, the feedstocks and the outcome rows were
            recorded. False in every other case, including a resolution that
            established nothing -- that is a finding, not a refusal.

    """

    package: Package
    downgrade_refused: bool


def resolve_package_shell(
    *,
    source_package_key: str,
    package_name: str,
    identity_source: str,
    clock: Clock,
) -> Package:
    """Return the package row for one source key, creating the shell if there is none.

    The whole of this story's resolution: `CPM-AD-25`'s "creates the shell at
    `unmapped` confidence", and nothing more. See the module docstring for why it
    asserts no mapping, why the source key becomes the canonical name, why the
    provenance is recorded anyway, and why the transaction belongs to the caller.

    Args:
        source_package_key: The key the inventory source used for this package.
            It becomes the shell's `associator_key` and nothing else: the stable
            record of what this resolution matched on, which nothing corrects.
        package_name: What the source calls the package. It becomes the shell's
            `canonical_name`, which is the correctable one -- see the module
            docstring for why the two are separate values and were not always.
        identity_source: What established this identity, recorded on the row
            (`CPM-FR-2`). A collector's declared name rather than a relation:
            resolvers are code, declared and never discovered (inherited `AD-8`),
            so there is no table for it to point at.
        clock: The clock `resolved_at` is read from (`CPM-AD-26`). Injected
            rather than reached for, because `CPM-FR-2` records the resolution's
            timestamp and a service that read a wall clock would make every
            assertion about that instant a statement about how long the test
            took.

    Returns:
        The existing package row, untouched, or the shell this call created --
        `unmapped` confidence, no mapping of any kind, the provenance above, and
        `resolved_at` from the clock.

    Raises:
        ResolutionError: When the key or the name names nothing, when either is
            longer than the column that has to hold it, when nothing is named as
            the identity source, or when the clock answered a naive instant. Each
            is refused before the row is written, so a record that cannot produce
            a usable identity leaves no half-made one behind.

    """
    key = _require_key(source_package_key)
    name = _require_name(package_name)
    source = _require_source(identity_source)
    resolved_at = _require_aware(clock.now(), field="resolved_at")
    # Looked up on `(identity_source, associator_key)` and never on the name --
    # see the module docstring. The key is the stable half of the pair, so a
    # lookup on the *name* would collapse two packages that happen to share one
    # onto a single row, discarding the second key silently, and would find
    # nothing at all the day `CPM-IDENTITY-S02` corrects a name.
    #
    # `canonical_name` sits in `defaults`, which makes it create-only, and that
    # is `CPM-AD-25` rather than an oversight: an existing shell keeps the name
    # it has, so a later sweep whose source has renamed a package does not
    # overwrite a name a reviewer or a real resolution corrected. It is the same
    # reason this is `get_or_create` and not `update_or_create`.
    #
    # Two rows with different keys and one name therefore reach the `create`, and
    # `canonical_name`'s unique constraint refuses the second. That surfaces as a
    # `DatabaseError` the collector records as one package's failure: the sweep
    # carries on and the run finalizes `partial`, which is the correct outcome for
    # a source that named one package twice under two keys.
    package, _created = Package.objects.get_or_create(
        identity_source=source,
        associator_key=key,
        defaults={
            "canonical_name": name,
            "resolved_at": resolved_at,
            # Written out rather than left to the column's default. The default
            # is `unmapped` and this passes `unmapped`, which is not redundancy:
            # the value this service asserts is the thing `CPM-AD-25` names, and
            # a reader must not have to open the model to find out that ingestion
            # claims nothing about the package it just created.
            "confidence": IdentityConfidence.UNMAPPED,
        },
    )
    return package


def record_resolution(*, resolution: Resolution, clock: Clock) -> RecordedResolution:
    """Record what a resolver concluded about a package that already exists.

    The second door into `identity`, and the update half of `CPM-AD-14`'s "package
    identity is mutated by resolution, or by the override path -- nothing else".
    See the module docstring for why creation stays with
    `resolve_package_shell`, why the join key is never written, and why the
    caller owns the transaction.

    What it does, in order: validates everything it was handed; finds the package
    by `(identity_source, associator_key)`; refuses if the pair names no row;
    writes the mappings whose outcome is `established`, the corrected name and
    the claimed confidence -- holding the last two when a `verified` identity
    meets a lower claim; writes the feedstock rows; and records one outcome row
    per `MappingKind`.

    **A mapping's value is written when, and only when, its outcome is
    `established`.** Both halves are enforced. A resolution that did not
    establish the source repository leaves whatever is stored exactly as it found
    it rather than blanking a value some earlier resolution did establish
    (`CPM-FR-1`, "records nothing rather than a guess"); and a resolution that
    says it *did* establish a mapping owning columns must supply one, or the
    columns would be indistinguishable from `not_found` and the distinction
    `PackageMapping` exists for would be lost at the moment it was recorded. The
    outcome row is written either way, which is where "we looked and it is not
    there" is actually recorded.

    **A lower-confidence resolution against a `verified` package is recorded, not
    discarded.** `CPM-FR-2` protects the *confidence* -- "a resolution never
    overwrites a `verified` confidence with a lower one" -- and nothing more. The
    findings still land: a `CPM-EP-CURRENCY` collector that discovers a feedstock
    for a package a human verified must be able to record it, and a door that
    dropped the whole resolution would lock every verified package out of every
    later collector. What is held back is the confidence claim and the corrected
    name, because those two *are* what `verified` asserts about the identity, and
    rewriting either from a lower-confidence resolver is the downgrade the rule
    forbids. Correcting them anyway is `CPM-IDENTITY-S05`'s audited override.

    The result says which of the two happened. Every other refusal in this module
    raises, so a holding that returned an ordinary `Package` would be the one
    outcome a caller could not tell from success without diffing the row it
    passed in.

    Args:
        resolution: What the resolver concluded. See `Resolution` for each field
            and for why the outcomes are supplied rather than inferred.
        clock: The clock `resolved_at` is read from, on the package row and on
            every mapping row (`CPM-AD-26`).

    Returns:
        A `RecordedResolution` carrying the package as it now stands and whether
        the claimed confidence was refused.

    Raises:
        ResolutionError: When the resolution names no resolver or no associator
            key; when the pair matches no package, or matches more than one; when
            the confidence or an outcome is not one of its vocabulary's values;
            when the outcomes do not name every mapping kind exactly once; when a
            mapping that was not `established` carries a value, or one that was
            `established` carries none; when a confidence above `unmapped` rests
            on no established mapping; when a value is wider than the column that
            has to hold it, or a purl list holds something that is not a name;
            when two feedstocks share a name; when a corrected name is blank or
            is already another package's; or when the clock answered a naive
            instant. Every one is refused before the first write, so a resolution
            that cannot be recorded correctly leaves no half-recorded one behind.

    """
    source = _require_source(resolution.identity_source)
    key = _require_associator_key(resolution.associator_key)
    confidence = _require_confidence(resolution.confidence)
    correction = _require_correction(resolution.canonical_name)
    outcomes = _require_outcomes(resolution)
    feedstocks = _require_feedstocks(resolution)
    _require_values_fit_their_columns(resolution)
    established = _require_established_mappings_carry_a_value(resolution, feedstocks=feedstocks)
    _require_confidence_is_earned(confidence, established=established)
    resolved_at = _require_aware(clock.now(), field="resolved_at")

    package = _package_at(source=source, key=key)
    # An equality test rather than a comparison, deliberately.
    # `identity/models.py` records that `IdentityConfidence` declares no ranking
    # and that nothing may read its member order as one; the only ordering
    # `CPM-AD-5` sanctions is `core`'s over `OutcomeState`, which this vocabulary
    # is not. "Stored verified, and the claim is not verified" is the whole rule
    # and it needs no order to state -- which is also why `inventory-derived`
    # falling to `unmapped` is *permitted*: `CPM-FR-2` protects one value by
    # name, and a re-resolution that lost its mapping has to be able to say so,
    # after which `CPM-AD-4`'s gate correctly stops claiming anything.
    held = package.confidence == IdentityConfidence.VERIFIED and confidence != IdentityConfidence.VERIFIED
    if not held and correction:
        _require_name_is_free(correction, package=package)

    _write_identity(
        package,
        resolution=resolution,
        correction="" if held else correction,
        confidence=package.confidence if held else confidence,
        resolved_at=resolved_at,
    )
    _write_feedstocks(package, feedstocks=feedstocks, established=outcomes[MappingKind.FEEDSTOCK.value] == ESTABLISHED)
    _write_outcomes(package, outcomes=outcomes, resolved_at=resolved_at)
    return RecordedResolution(package=package, downgrade_refused=held)


def _package_at(*, source: str, key: str) -> Package:
    """Return the package one source key names, refusing when there is not exactly one.

    Args:
        source: The identity source, already required non-blank.
        key: The associator key, already required non-blank.

    Returns:
        The package row.

    Raises:
        ResolutionError: When the pair matches no row, or matches several. The
            first is refused rather than created: creation is
            `resolve_package_shell`'s, and a recorder that quietly created what
            it could not find would give the product a second creator of package
            rows, which is exactly what `CPM-AD-14` and `CPM-AD-25` forbid.

            The second is unreachable on a schema carrying
            `one_package_per_source_key` and entirely reachable on one written
            before it -- a database migrated from an earlier release is exactly
            where the duplicate shells this story exists to prevent already are.
            `MultipleObjectsReturned` escaping would be the one failure from this
            door that no caller is told to catch.

    """
    try:
        return Package.objects.get(identity_source=source, associator_key=key)
    except Package.DoesNotExist as unknown:
        message = (
            f"no package is filed under {key!r} by {source!r}, so there is nothing to record a resolution "
            f"against. A package row is created by resolve_package_shell during ingestion (CPM-AD-25); this "
            f"door updates one and never creates one."
        )
        raise ResolutionError(message) from unknown
    except Package.MultipleObjectsReturned as duplicated:
        message = (
            f"more than one package is filed under {key!r} by {source!r}, so no resolution can be recorded "
            f"against that pair. one_package_per_source_key makes this impossible on a schema that carries it; "
            f"a database written before it can already hold the duplicate shells that constraint exists to "
            f"prevent, and they have to be merged before either row can be resolved."
        )
        raise ResolutionError(message) from duplicated


def _require_name_is_free(correction: str, *, package: Package) -> None:
    """Refuse a correction onto a name another package already holds.

    Not exotic: two shells converging on one upstream package is precisely what
    correction is *for*, and two inventory sources filing one package under two
    keys is a state this product deliberately permits. `canonical_name` is
    `unique=True`, so without this the collision escapes as an `IntegrityError`
    from the `save()` -- an exception this door's contract does not mention, out
    of a module whose every other refusal is a `ResolutionError` raised before
    the first write.

    **Merging the two rows is nobody's yet, and this message used to say
    otherwise.** It named `CPM-IDENTITY-S05`'s audited override as where the merge
    belonged. That story shipped, and its `override_identity` refuses the same
    collision rather than resolving it -- correctly, because merging decides which
    associator key survives, which evidence moves and what becomes of the mappings
    each side holds, and none of those is a name correction. So the message no
    longer hands the operator a door that would refuse them. It is owed by a later
    story; the two refusals are what keep the collision visible until then.

    Args:
        correction: The validated corrected name.
        package: The package the resolution was recorded against.

    Raises:
        ResolutionError: When another package already carries that name.

    """
    if not _another_package_holds(correction, package=package):
        return
    message = (
        f"{correction!r} is already another package's canonical name, so this correction would collide with "
        f"it. canonical_name is unique (CPM-AD-3) and two shells converging on one upstream package is what "
        f"correction is for -- but *merging* them decides which associator key survives, which evidence moves "
        f"and what becomes of each side's mappings, and no door in this product does that yet. The collision "
        f"is reported so a person can decide."
    )
    raise ResolutionError(message)


def _write_identity(
    package: Package,
    *,
    resolution: Resolution,
    correction: str,
    confidence: str,
    resolved_at: datetime,
) -> None:
    """Write the identity fields this resolution settled, and no others.

    `update_fields` is built from what was actually written rather than listing
    every column, which is what keeps `identity_source` and `associator_key` out
    of it by construction instead of by somebody remembering to omit them. A
    `save()` with no `update_fields` would write all thirteen columns, including
    the two the whole duplicate-shell trap turns on.

    **`resolved_at` advances only when something else did.** A resolver that runs
    daily and establishes nothing would otherwise stamp the row every day, and a
    package nothing has ever resolved would read as freshly resolved to
    `CPM-IDENTITY-S04`'s review queue and to every staleness consumer after it.
    When a resolver last *looked* is `PackageMapping.resolved_at`, which is
    written on every call; this column is when the identity last *changed*. So
    the intended writes are diffed against what is stored, and a call that would
    change nothing but the timestamp does not save at all.

    Args:
        package: The row to write, already found by its pair.
        resolution: What the resolver concluded.
        correction: The validated corrected name, or blank for no correction --
            blank both when none was supplied and when a `verified` identity held
            one back.
        confidence: The confidence to store, already validated. The stored value
            itself when a `verified` identity held a lower claim, which is what
            makes it drop out of the diff below rather than needing a branch.
        resolved_at: The instant from the clock.

    """
    intended: dict[str, object] = {"confidence": confidence}
    if correction:
        intended[CANONICAL_NAME_FIELD] = correction
    for kind in MappingKind.values:
        if resolution.outcomes[kind] != ESTABLISHED:
            continue
        for name in MAPPED_FIELDS.get(kind, ()):
            intended[name] = _stored_form(getattr(resolution, name))
    written = {name: value for name, value in intended.items() if getattr(package, name) != value}
    if not written:
        return
    written["resolved_at"] = resolved_at
    for name, value in written.items():
        setattr(package, name, value)
    package.save(update_fields=sorted(written))


def _stored_form(value: object) -> object:
    """Return a supplied value in the shape the column stores it in.

    `alternative_purls` and `cpes` are `JSONField`s holding lists, and
    `Resolution` carries tuples because it is frozen. Assigning the tuple would
    leave the returned instance holding one where a re-read holds a list, so the
    object a caller was handed and the row it describes would differ by type on
    two of thirteen columns -- a difference that shows up as a failing equality
    in whichever consumer compares them first.

    Args:
        value: The value the resolution supplied.

    Returns:
        A list for a tuple, and the value unchanged for anything else.

    """
    return list(value) if isinstance(value, tuple) else value


def _write_feedstocks(package: Package, *, feedstocks: Sequence[FeedstockMapping], established: bool) -> None:
    """Write the conda-forge feedstocks this resolution established.

    Additive: a feedstock the resolution no longer names is left where it is.
    Removing one is a correction rather than a resolution -- it says an earlier
    conclusion was *wrong* rather than that a newer one is available -- and
    `CPM-AD-14` puts corrections on `CPM-IDENTITY-S05`'s audited override path,
    which records who removed it and why. A recorder that deleted rows silently
    would be that path without the audit.

    Args:
        package: The package the feedstocks map.
        feedstocks: The mappings, already required well-formed.
        established: Whether the feedstock kind's outcome is `established`.
            `_require_feedstocks` has already refused a non-established outcome
            carrying any, so this only decides whether to write nothing at all --
            and an `established` outcome with none is the successful empty result
            (`CPM-FR-6`), which writes nothing and means something.

    """
    if not established:
        return
    for feedstock in feedstocks:
        # `feedstock.name` is already stripped: `_require_feedstocks` normalises
        # every mapping it validates and hands back the normalised tuple, so the
        # name matched on here and the name the bound and the duplicate check
        # were applied to are the same string. Stripping again at the write would
        # be a second place the rule lives, and the two would drift the day one
        # of them started folding case as well.
        row, created = Feedstock.objects.get_or_create(
            package=package,
            name=feedstock.name,
            defaults={"url": feedstock.url, "metadata_url": feedstock.metadata_url},
        )
        if not created and (row.url, row.metadata_url) != (feedstock.url, feedstock.metadata_url):
            row.url = feedstock.url
            row.metadata_url = feedstock.metadata_url
            row.save(update_fields=["url", "metadata_url"])


def _write_outcomes(package: Package, *, outcomes: Mapping[str, str], resolved_at: datetime) -> None:
    """Write one outcome row per mapping kind, replacing whatever stood before.

    The row is rewritten rather than appended because `PackageMapping` is
    identity and not evidence: it records what is currently concluded, exactly as
    `Package.confidence` does, and `one_outcome_per_package_mapping` is what makes
    "what do we conclude about this package's feedstocks" have one answer.

    Args:
        package: The package the outcomes are about.
        outcomes: One outcome value per mapping kind, already validated.
        resolved_at: The instant from the clock.

    """
    for kind in sorted(outcomes):
        mapping, created = PackageMapping.objects.get_or_create(
            package=package,
            kind=kind,
            defaults={"outcome": outcomes[kind], "resolved_at": resolved_at},
        )
        if created:
            continue
        mapping.outcome = outcomes[kind]
        mapping.resolved_at = resolved_at
        mapping.save(update_fields=["outcome", "resolved_at"])


def _require_associator_key(associator_key: str) -> str:
    """Refuse a lookup that does not say which package it is about.

    Separate from `_require_key` because it is a different question asked of the
    same value: that one asks whether a key can *become* a shell's
    `associator_key`, and this asks whether it can *find* one. The length bound is
    deliberately absent here -- an over-long key simply matches no row, and
    `_package_at` says so more usefully than a bound would.

    Args:
        associator_key: The key the resolution says it matched on.

    Returns:
        The key with surrounding whitespace removed, which is the form the row
        carries -- so a key differing only by a trailing space still finds it.

    Raises:
        ResolutionError: When it is empty or only whitespace. Refused rather than
            queried: `associator_key` is blank on every package no source claims,
            `one_package_per_source_key` deliberately does not constrain those,
            and a lookup for the blank key would therefore match an unbounded
            number of rows and raise something no caller is told to catch.

    """
    key = associator_key.strip()
    if not key:
        message = (
            f"a recorded resolution needs an associator_key; {associator_key!r} names nothing. It is half of "
            f"the pair a package is found by (CPM-FR-2), and the blank key is deliberately not unique -- so a "
            f"lookup on it would match every package no source claims rather than one."
        )
        raise ResolutionError(message)
    return key


def _require_correction(canonical_name: str) -> str:
    """Return the corrected name a resolution supplied, or blank for no correction.

    The empty string means "leave the stored name alone" and is the ordinary case
    for a resolution that settled a mapping without touching the name. Whitespace
    is *not* that: it is a correction to nothing, and writing it would be refused
    by `canonical_name_is_present` as an `IntegrityError` naming a constraint
    rather than the input that broke it.

    Called before the lookup rather than at the write, so a resolution carrying
    an unusable name never reaches a row -- which is what makes every refusal in
    this door provably prior to any write.

    Args:
        canonical_name: What the resolution says the package is called.

    Returns:
        The validated name, stripped, or the empty string when none was supplied.

    Raises:
        ResolutionError: When a correction was supplied and is only whitespace,
            or is wider than `canonical_name` can hold.

    """
    if not canonical_name:
        return ""
    return _require_name(canonical_name)


def _require_confidence(confidence: str) -> str:
    """Refuse a confidence that is not one of the three the PRD fixes.

    Args:
        confidence: What the resolution claims.

    Returns:
        The value, unchanged.

    Raises:
        ResolutionError: When it is not an `IdentityConfidence` value. Refused
            here rather than left to the column, because `choices` is enforced by
            model validation and nothing in this product runs `full_clean` --
            an unrecognised value would be stored, and `CPM-AD-4`'s gate would
            then meet a confidence it has no rule for.

    """
    if confidence not in set(IdentityConfidence.values):
        message = (
            f"{confidence!r} is not a package-identity confidence; the values are "
            f"{sorted(IdentityConfidence.values)}. CPM-AD-4 gates every outward claim on this value, so a "
            f"spelling it does not recognise is a package nothing can decide what to say about."
        )
        raise ResolutionError(message)
    return confidence


def _require_outcomes(resolution: Resolution) -> Mapping[str, str]:
    """Refuse an outcome table that does not answer for every mapping, once each.

    Exhaustive on purpose. A missing kind would have to default to something, and
    every candidate is wrong: `unknown` would silently claim nobody looked, and
    leaving the stored row alone would silently claim the last resolution's
    finding still holds. `CPM-FR-6` is about not folding states together, and a
    default is a fold nobody wrote down.

    Args:
        resolution: The resolution whose outcomes are being checked.

    Returns:
        The outcomes, unchanged.

    Raises:
        ResolutionError: When a kind is missing, when a name is not a mapping
            kind, when a value is not a `MappingOutcome` value, or when a mapping
            that was not `established` nonetheless carries a value.

    """
    permitted = {value for value, _label in MappingOutcome.choices}
    # Read off `MappingKind` rather than off `MAPPED_FIELDS`, because the kinds
    # are what the `kind` column offers and the field table is a statement
    # *about* them. A member declared on the model but absent from that table
    # would otherwise be reported back to a caller as "unrecognised" -- for a
    # kind the model does declare -- and could never be given a row at all.
    # `MAPPED_FIELDS.get(kind, ())` is the matching read at every use below;
    # `tests/unit/django_apps/test_identity_models.py` reconciles the two so the
    # gap is a failing test rather than a silently unmappable kind.
    declared = set(MappingKind.values)
    missing = sorted(declared - set(resolution.outcomes))
    unknown = sorted(set(resolution.outcomes) - declared)
    if missing or unknown:
        message = (
            f"a recorded resolution answers for every mapping kind exactly once; missing {missing}, "
            f"unrecognised {unknown}. CPM-FR-6 keeps not_applicable, not_found and a successful empty result "
            f"apart, and a kind left out would have to be folded into one of them by default."
        )
        raise ResolutionError(message)
    unrecognised = sorted(kind for kind, outcome in resolution.outcomes.items() if outcome not in permitted)
    if unrecognised:
        message = (
            f"these mapping outcomes are not values of the composed vocabulary: {unrecognised}. The values are "
            f"{sorted(permitted)}, composed by core.outcomes.outcome_type so every status in this product is "
            f"drawn from one table (CPM-AD-5)."
        )
        raise ResolutionError(message)
    return _require_absent_where_not_established(resolution)


def _require_absent_where_not_established(resolution: Resolution) -> Mapping[str, str]:
    """Refuse a value recorded beside an outcome that says there is none.

    `CPM-FR-1` says a resolution that cannot establish a mapping records nothing
    rather than a guess. A purl handed over with `not_found` beside it is that
    guess: the value would be dropped by `_write_identity` and the caller would
    never learn that half of what it supplied was discarded, which is the quiet
    failure this refusal exists to make loud.

    Args:
        resolution: The resolution whose values are being checked.

    Returns:
        The outcomes, unchanged.

    Raises:
        ResolutionError: When a kind whose outcome is not `established` carries a
            value, or when the feedstock kind does while carrying feedstocks.

    """
    contradicted = sorted(
        f"{kind}={outcome}"
        for kind, outcome in resolution.outcomes.items()
        if outcome != ESTABLISHED
        and (
            any(getattr(resolution, name) for name in MAPPED_FIELDS.get(kind, ()))
            or _carries_feedstocks(resolution, kind)
        )
    )
    if contradicted:
        message = (
            f"these mappings carry a value beside an outcome that says there is none: {contradicted}. "
            f"CPM-FR-1 records nothing rather than a guess, so a value is written only when its outcome is "
            f"{ESTABLISHED!r} -- and one supplied here would have been dropped silently."
        )
        raise ResolutionError(message)
    return resolution.outcomes


def _carries_feedstocks(resolution: Resolution, kind: str) -> bool:
    """Report whether a kind is the feedstock one and the resolution supplied rows.

    The feedstock mapping is the one whose value is child rows rather than
    columns, so `MAPPED_FIELDS` is empty for it and the column check above cannot
    see it. Written out rather than folded in, because a reader meeting an empty
    tuple in that table needs to find the other half somewhere.

    Args:
        resolution: The resolution being checked.
        kind: The mapping kind.

    Returns:
        True only for the feedstock kind carrying at least one mapping.

    """
    return kind == MappingKind.FEEDSTOCK.value and bool(resolution.feedstocks)


def _require_established_mappings_carry_a_value(
    resolution: Resolution,
    *,
    feedstocks: Sequence[FeedstockMapping],
) -> frozenset[str]:
    """Refuse an `established` mapping that established nothing, and report the rest.

    The converse of `_require_absent_where_not_established`, and the half that
    was missing. `established` with every field blank stores exactly what
    `not_found` stores -- nothing -- so the two become indistinguishable in the
    columns at the moment the row is written, which is the fold `PackageMapping`
    exists to prevent. A caller that has not established a mapping has four
    sentinels to say so with.

    **The feedstock kind is the one exception, and it is the reason the exception
    is worth having.** `CPM-FR-1` says "zero or more", so `established` with no
    rows is a *successful empty result* -- this package genuinely has no
    conda-forge recipe -- which `CPM-FR-6` insists stays distinct from
    `not_found` and `not_applicable`. No other kind says "zero or more" of
    anything, so for the four that own columns an empty establishment is a
    contradiction rather than a finding.

    Args:
        resolution: The resolution being checked.
        feedstocks: The validated feedstock mappings.

    Returns:
        The kinds this resolution established *and* supplied a value for. The
        confidence check below reads it, so the walk happens once rather than
        twice with two chances to disagree.

    Raises:
        ResolutionError: When a column-owning kind is `established` and every one
            of its fields is blank.

    """
    established = frozenset(
        kind
        for kind, outcome in resolution.outcomes.items()
        if outcome == ESTABLISHED
        and (
            any(getattr(resolution, name) for name in MAPPED_FIELDS.get(kind, ()))
            or (kind == MappingKind.FEEDSTOCK.value and bool(feedstocks))
        )
    )
    empty = sorted(
        kind
        for kind, outcome in resolution.outcomes.items()
        if outcome == ESTABLISHED and kind != MappingKind.FEEDSTOCK.value and kind not in established
    )
    if empty:
        message = (
            f"these mappings are {ESTABLISHED!r} and carry no value: {empty}. A mapping established with every "
            f"field blank stores what not_found stores, so the two stop being distinguishable in the columns "
            f"(CPM-FR-6) -- a resolution that established nothing has four sentinels to say so with. Only the "
            f"feedstock mapping may be established and empty, because CPM-FR-1 says zero or more of those."
        )
        raise ResolutionError(message)
    return established


def _require_confidence_is_earned(confidence: str, *, established: frozenset[str]) -> None:
    """Refuse a confidence above `unmapped` that rests on no established mapping.

    `CPM-AD-4` gates every outward claim on this value: `verified` shows
    comparisons and recommendations normally, and `inventory-derived` shows them
    with a label. A row carrying either while every mapping reads `not_found` is
    a package the product will speak about on the strength of nothing, which is
    the `CPM-SM-C1` failure the whole system is built to avoid.

    `CPM-FR-1` states the rule from the other side -- "a resolution that cannot
    establish a mapping records `unmapped`, never a guess" -- and `unmapped` is
    therefore always available and never refused: a resolver that found nothing
    says so and `CPM-AD-4` correctly stops claiming anything.

    Args:
        confidence: The claimed confidence, already validated.
        established: The kinds established with a value.

    Raises:
        ResolutionError: When the confidence is above `unmapped` and nothing was
            established.

    """
    if confidence == IdentityConfidence.UNMAPPED or established:
        return
    message = (
        f"a resolution claiming {confidence!r} established no mapping. CPM-AD-4 gates every outward claim on "
        f"this value, so a confidence above {IdentityConfidence.UNMAPPED.value!r} resting on nothing is a "
        f"package the product will speak about on the strength of nothing -- and CPM-FR-1 says a resolution "
        f"that cannot establish a mapping records {IdentityConfidence.UNMAPPED.value!r}, never a guess."
    )
    raise ResolutionError(message)


def _require_values_fit_their_columns(resolution: Resolution) -> None:
    """Refuse a supplied value wider than the column that has to hold it.

    The parity rule this module already applies to the two names, applied to
    every other value a caller supplies: SQLite ignores `max_length` and
    PostgreSQL raises, so an unrefused over-long purl is a working row on a
    developer's machine and a failed run in the gate (`R-5`). Applying it to
    three columns and not to the other four was the inconsistency, not the rule.

    The two `JSONField`s carry no width -- JSON text is unbounded on both
    backends -- so what is checked there is shape instead: every element must be
    a non-blank string, because a `None`, a nested list or an integer would be
    stored happily and would then be read back by an advisory matcher that
    expects identifiers.

    Args:
        resolution: The resolution whose values are being checked.

    Raises:
        ResolutionError: When a bounded value is too long, or when a purl or CPE
            list holds something that is not a name.

    """
    for name, limit in PACKAGE_FIELD_LENGTHS.items():
        value = str(getattr(resolution, name))
        if len(value) > limit:
            raise ResolutionError(_too_wide(value, field=name, limit=limit))
    for name in ("alternative_purls", "cpes"):
        malformed = [
            element for element in getattr(resolution, name) if not isinstance(element, str) or not element.strip()
        ]
        if malformed:
            message = (
                f"{name} holds entries that are not identifiers: {malformed!r}. The column is a JSONField, so a "
                f"None, a number or a nested list is stored without complaint and is read back by an advisory "
                f"matcher expecting a purl or a CPE name (CPM-FR-1)."
            )
            raise ResolutionError(message)


def _too_wide(value: str, *, field: str, limit: int) -> str:
    """Return the refusal message for a value wider than its column.

    One message for the seven columns that share the rule, because seven copies
    of a parity argument is seven places it can be weakened one at a time. The
    two names keep their own messages: each says *why* that particular value
    matters, which a shared sentence could not.

    Args:
        value: The over-long value.
        field: The column it was destined for.
        limit: How wide that column is.

    Returns:
        The message.

    """
    return (
        f"the value for {field} is {len(value)} characters and the column holds {limit}. SQLite would store it "
        f"truncated and PostgreSQL would refuse it, so the row would exist on a developer's machine and fail "
        f"in the gate -- the parity gap is refused here instead."
    )


def _require_feedstocks(resolution: Resolution) -> tuple[FeedstockMapping, ...]:
    """Refuse a feedstock the child table could not hold, and normalise the rest.

    The same checks the package's own name gets, against `Feedstock`'s own
    columns, and here for the same reason plus one more: these rows are written
    in a loop, so an `IntegrityError` from `feedstock_name_is_present`, a
    PostgreSQL length refusal or a `one_feedstock_name_per_package` violation
    would arrive with some rows already written and would name neither the
    feedstock nor the rule.

    **Two mappings with the same name are refused rather than merged.** The write
    loop is a `get_or_create` per name, so a duplicate would be silently
    last-wins: the second entry's URLs would overwrite the first's and the
    resolver would never learn that half of what it supplied was discarded. A
    resolver that has two things to say about one feedstock has a defect, not a
    preference.

    Args:
        resolution: The resolution whose feedstocks are being checked.

    Returns:
        The mappings with their names stripped, which is the form the rows carry
        and the form `_write_feedstocks` matches on -- normalised once here so
        the bound, the duplicate check and the lookup all see the same string.

    Raises:
        ResolutionError: When a feedstock's name is blank or only whitespace,
            when a name or either URL is wider than its column, or when two
            mappings share a name.

    """
    normalised: list[FeedstockMapping] = []
    for feedstock in resolution.feedstocks:
        name = feedstock.name.strip()
        if not name:
            message = (
                f"a feedstock mapping needs a name; {feedstock.name!r} names nothing. A nameless feedstock is "
                f"worse than a missing one because it is counted -- package.feedstocks returns it, so 'this "
                f"package has a feedstock' reads true for a row naming nothing (CPM-FR-5)."
            )
            raise ResolutionError(message)
        if len(name) > FEEDSTOCK_NAME_LENGTH:
            message = (
                f"the feedstock name {name!r} is {len(name)} characters and {FEEDSTOCK_NAME_FIELD} holds "
                f"{FEEDSTOCK_NAME_LENGTH}. SQLite would store it truncated and PostgreSQL would refuse it, so "
                f"the row would exist on a developer's machine and fail in the gate -- the parity gap is "
                f"refused here instead."
            )
            raise ResolutionError(message)
        for field_name, limit in FEEDSTOCK_URL_LENGTHS.items():
            value = str(getattr(feedstock, field_name))
            if len(value) > limit:
                raise ResolutionError(_too_wide(value, field=f"feedstock {field_name}", limit=limit))
        normalised.append(FeedstockMapping(name=name, url=feedstock.url, metadata_url=feedstock.metadata_url))
    repeated = sorted(
        {mapping.name for mapping in normalised if [row.name for row in normalised].count(mapping.name) > 1}
    )
    if repeated:
        message = (
            f"these feedstocks are named twice in one resolution: {repeated}. The write is a get_or_create per "
            f"name, so the second entry would silently overwrite the first's URLs and one_feedstock_name_per_package "
            f"would keep exactly one row -- a resolver with two things to say about one feedstock has a defect."
        )
        raise ResolutionError(message)
    return tuple(normalised)


def _require_source(identity_source: str) -> str:
    """Refuse a resolution that does not say what established it.

    `CPM-FR-2` needs a resolution traceable to the resolver that made it, on the
    same terms `core/ledger.py` needs a run traceable to the code that performed
    it. The refusal is here rather than at the column because a blank `CharField`
    is perfectly valid SQL: the row would be written, would be counted, and would
    name nothing.

    Args:
        identity_source: What the caller says established the identity.

    Returns:
        The name with surrounding whitespace removed.

    Raises:
        ResolutionError: When it is empty or only whitespace.

    """
    source = identity_source.strip()
    if not source:
        message = (
            f"a package shell needs an identity_source; {identity_source!r} names nothing. A resolution is "
            f"traceable to the resolver that made it (CPM-FR-2), and a blank name is a row nothing can be "
            f"re-derived from."
        )
        raise ResolutionError(message)
    return source


def _require_key(source_package_key: str) -> str:
    """Refuse a source key that cannot name a package.

    Args:
        source_package_key: The key the caller supplied.

    Returns:
        The key with surrounding whitespace removed, which is what the row
        carries: a key that differs from another only by a trailing space is the
        same key to the source and a different one to every later match on it.

    Raises:
        ResolutionError: When the key is blank or only whitespace, or when it is
            longer than `associator_key` can hold. The length check is here
            rather than left to the database because the two disagree: SQLite
            ignores `max_length` entirely and PostgreSQL raises, so an
            over-long key is a working row on a developer's machine and a failed
            run in the gate.

            The bound is `associator_key`'s -- the column the key lands in -- and
            not `canonical_name`'s narrower one. Fusing the two would refuse a
            legitimately long source key for a column it does not occupy, which
            is exactly the confusion `CPM-IDENTITY-S07` split the two values to
            remove.

    """
    name = source_package_key.strip()
    if not name:
        message = (
            f"a package shell needs a source package key; {source_package_key!r} names nothing. A package "
            f"with no name cannot be corrected, cannot be exported and cannot be found again (CPM-FR-2)."
        )
        raise ResolutionError(message)
    if len(name) > ASSOCIATOR_KEY_LENGTH:
        message = (
            f"the source package key {name!r} is {len(name)} characters and {ASSOCIATOR_KEY_FIELD} holds "
            f"{ASSOCIATOR_KEY_LENGTH}. SQLite would store it truncated and PostgreSQL would refuse it, so "
            f"the row would exist on a developer's machine and fail in the gate -- the parity gap is "
            f"refused here instead."
        )
        raise ResolutionError(message)
    return name


def _require_name(package_name: str) -> str:
    """Refuse a package name the shell's canonical name cannot be.

    The same two checks `_require_key` applies, against the same bound and for
    the same parity reason, applied to the other of the two values the source
    supplies. Written out rather than folded into one helper taking a field name:
    the two refusals say different things -- a missing key is a record nothing
    can re-derive, a missing name is a package nothing can display -- and a
    shared message would say neither.

    Args:
        package_name: The name the caller supplied.

    Returns:
        The name with surrounding whitespace removed, which is what the row
        carries: a name differing from another only by a trailing space is the
        same name to a reader and two rows to `unique=True`.

    Raises:
        ResolutionError: When the name is blank or only whitespace, or when it is
            longer than `canonical_name` can hold.

    """
    name = package_name.strip()
    if not name:
        message = (
            f"a package shell needs a package name; {package_name!r} names nothing. A package with no name "
            f"cannot be corrected, cannot be exported and cannot be found again (CPM-FR-2)."
        )
        raise ResolutionError(message)
    if len(name) > CANONICAL_NAME_LENGTH:
        message = (
            f"the package name {name!r} is {len(name)} characters and {CANONICAL_NAME_FIELD} holds "
            f"{CANONICAL_NAME_LENGTH}. SQLite would store it truncated and PostgreSQL would refuse it, so "
            f"the row would exist on a developer's machine and fail in the gate -- the parity gap is "
            f"refused here instead."
        )
        raise ResolutionError(message)
    return name


def _require_aware(instant: datetime, *, field: str) -> datetime:
    """Refuse a naive instant, on the same terms `core/ledger.py` does.

    `identity/models.py` says the model performs no awareness check of its own
    and that the check is this service's. This is it: `USE_TZ` is on, so Django
    warns and stores a naive value as if it were UTC, and a `resolved_at`
    silently shifted by the writer's offset is a provenance record that says the
    identity was established at a time it was not.

    Args:
        instant: The value the clock answered.
        field: Which field it is for, for the message.

    Returns:
        The instant, unchanged.

    Raises:
        ResolutionError: When the instant carries no usable offset.

    """
    if not is_aware(instant):
        message = (
            f"a package shell was resolved with a naive {field} ({instant!r}). The instant comes from a "
            f"Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to interpret and "
            f"would record a resolution at a time it did not happen rather than failing."
        )
        raise ResolutionError(message)
    return instant


def override_identity(
    *,
    package_id: int,
    actor: User,
    correction: Correction,
    clock: Clock,
) -> IdentityOverride:
    """Correct a package identity as a person, and record who did it and why.

    The third door into `identity`, and the human half of `CPM-AD-14`'s "package
    identity is mutated by resolution, or by the override path -- nothing else".
    `CPM-FR-3` makes it the only human write in the product that mutates governed
    reference data, so it carries the three obligations `CPM-AD-14` puts on that
    write: it requires a permission, it requires a reason, and it writes an audit
    row **in the same transaction** as the correction.

    What it does, in order: refuses an actor without the permission and logs the
    refusal naming them; refuses a blank reason; refuses a name or display name
    the columns could not hold; finds the package by its primary key and refuses
    one that names nothing; refuses a correction onto a name another package
    already holds; and then, inside one `transaction.atomic()`, writes the
    correction and the `IdentityOverride` row that records it.

    **Every refusal precedes the first write**, which is what makes a refused
    override leave nothing behind. The two writes inside the block are the only
    two, and they commit or roll back together (`IDENTITY.05-INT-001`, risk
    `R-07`).

    **`identity_source` and `associator_key` are never written.** They are the
    pair both other doors find a package by, and rewriting either while
    correcting a name is what orphans the package from its inventory source on
    the next sweep -- the trap `CPM-IDENTITY-S06` recorded and `CPM-IDENTITY-S07`
    closed. `_write_correction` builds its `update_fields` from what it actually
    intends, so neither column can reach a `save()` by construction.

    **The correction survives automated resolution, and needs no new mechanism to
    do it.** The override writes `verified`, and `record_resolution` already
    refuses to lower a `verified` confidence or to overwrite the name that goes
    with it. So a later, lower-confidence resolver records its findings and
    leaves the human's decision standing.

    **Creation is not this door's.** A package id naming nothing is refused rather
    than created: `CPM-AD-25` makes `resolve_package_shell` the only creator of a
    package row, and an override that quietly created what it could not find would
    give the product a second one.

    Args:
        package_id: The package to correct, by the surrogate integer primary key
            `CPM-AD-3` fixes. An id rather than an instance, because the caller is
            a surface holding a selection from `CPM-IDENTITY-S04`'s review queue,
            and re-reading the row inside this door is what makes the correction a
            statement about the row as it stands rather than about a copy that may
            be minutes old.
        actor: The person making the correction. Must hold
            `IDENTITY_OVERRIDE_PERMISSION`, which `core/roles.py` grants to the
            leadership role group alone.
        correction: What they decided and why. See `Correction` for each field
            and for why it is one value rather than three parameters.
        clock: The clock the audit row's `observed_at` and the package's
            `resolved_at` are read from (`CPM-AD-26`). Injected rather than
            reached for, because an audit row's instant is the thing an auditor
            reads, and a service that read a wall clock would make every assertion
            about it a statement about how long the test took.

    Returns:
        The audit row this override wrote, with `package` already carrying the
        correction. The row rather than the package, because the row is the thing
        `CPM-FR-32` makes independently queryable and the package is reachable
        through it -- and because a caller handed only the package could not tell
        an override that changed nothing from one that was never recorded.

    Raises:
        OverrideError: When the actor does not hold the permission; when the
            reason is blank or only whitespace; when a corrected name is blank
            after stripping or is wider than its column; when the display name is
            wider than its column; when the package id names no row; when the
            corrected name is already another package's; or when the clock
            answered a naive instant. Every one is raised before the first write.

    """
    _require_permitted(actor)
    justification = _require_reason(correction.reason)
    name = _require_overridden_name(correction.canonical_name)
    replacement = _require_overridden_display_name(correction.display_name)
    decided_at = _require_decided_at(clock.now())

    # The one `transaction.atomic()` in this module (`CPM-AD-23`), and the read is
    # *inside* it under `select_for_update()`. That is not tidiness: the audit row
    # records the values this correction replaced, so the row it reads them from
    # has to be the row it then writes. Read outside the block, two concurrent
    # overrides of one package both observe the same prior values and both record
    # them, and the second row claims to have replaced a value the first had
    # already replaced -- an audit trail that is wrong about the thing it exists to
    # be right about. The collision check is inside for the same reason: a name
    # taken between the check and the write would escape as the raw
    # `IntegrityError` this door refuses in order to prevent.
    with transaction.atomic():
        package = _package_with_id(package_id)
        if name and name != package.canonical_name:
            _require_name_is_unclaimed(name, package=package)
        prior_canonical_name = package.canonical_name
        prior_display_name = package.display_name
        prior_confidence = package.confidence
        _write_correction(package, canonical_name=name, display_name=replacement, decided_at=decided_at)
        override = IdentityOverride.objects.create(
            observed_at=decided_at,
            package=package,
            actor=actor,
            prior_canonical_name=prior_canonical_name,
            new_canonical_name=package.canonical_name,
            prior_display_name=prior_display_name,
            new_display_name=package.display_name,
            prior_confidence=prior_confidence,
            new_confidence=package.confidence,
            reason=justification,
            # `current_trace_id()` never raises and answers the empty string
            # outside an instrumented request or task (`CPM-AD-15`). An
            # uncorrelated audit row is worth incomparably more than a refused
            # correction, so nothing here branches on it.
            trace_id=current_trace_id(),
        )
    # Logged after the block rather than inside it, so the event describes a
    # correction that reached the end of its transaction rather than one that was
    # merely attempted. `CPM-AD-13` makes every authorization change an event, and
    # a log carrying only the *refusals* would let an operator filtering
    # `authorization.` see every rejected correction of governed reference data and
    # not one accepted one -- which is the half an auditor asks about first.
    logger.info(
        OVERRIDE_RECORDED_EVENT,
        user_id=actor.pk,
        idp_subject=getattr(actor, IDENTITY_FIELD, ""),
        package_id=package.pk,
        override_id=override.pk,
    )
    return override


def _require_permitted(actor: User) -> None:
    """Refuse an actor who does not hold the override permission, and say so in the log.

    **The service is the boundary, because it is where the only caller is.**
    `CPM-AD-13` says authorization is declared per surface and enforced centrally;
    there is no surface yet -- see the story's design notes -- so `user.has_perm`
    here is the whole enforcement. When `CPM-APP-S05` builds the modal it declares
    its own permission and this becomes the second line rather than the only one,
    which is the right number for the product's single governed write.

    **An unauthenticated actor is refused first, and that ordering is the whole
    of it.** `AnonymousUser` answers `has_perm` perfectly well -- False, through
    every backend -- so the check itself would work. What does not work is the
    *log record beside it*: `AnonymousUser` has no `idp_subject`, so reading the
    attribute unconditionally would raise `AttributeError` on exactly the branch
    AC 2 is written about, and the refusal an operator most needs to see would be
    the one that never reaches the log. `is_authenticated` is tested first and
    both identity fields are read defensively, so a caller handing over an
    anonymous request user, a `SimpleLazyObject` wrapping one, or a user model
    without the platform's identity column is refused *and* recorded.

    **A superuser is admitted, and that is a decision rather than an oversight.**
    `PermissionsMixin.has_perm` returns True for any active superuser before it
    consults a backend, so a superuser reaches this write without the leadership
    grant. It is left that way for the reason `django_service/users/provisioning.py`
    leaves `SUPERUSER_ROLE`'s tuple empty: the superuser flag is the platform's
    break-glass, it already reaches the Django admin -- from which the same rows
    are editable with no audit row at all -- and a check written to refuse it here
    would make the product's one *audited* correction path the only thing a
    superuser could not use during the incident where group synchronisation is
    what broke. The mitigation is not the check, it is the row: an override by a
    superuser writes the same `IdentityOverride` naming them, at the same instant,
    with the same reason, so the write stays governed even when the grant is
    bypassed. `tests/integration/django_apps/test_identity_overrides.py` asserts
    both halves, so this is a recorded decision rather than an accident of
    Django's default.

    **The refusal is logged with the acting identity, explicitly.** Outside a
    request nothing binds `user_id`, so `django_structlog`'s request binding
    cannot be relied on and the actor is passed as a kwarg. Both the primary key
    and the identity-provider subject are carried: `idp_subject` is the
    correlation key an operator has and is what every other authorization event in
    this repository names, and it is blank on a locally created account -- which
    is exactly the case where the primary key is the only handle there is.

    Args:
        actor: The person attempting the correction.

    Raises:
        OverrideError: When the actor is not authenticated, or does not hold the
            permission. Raised after the log record rather than before it, so the
            refusal is recorded even where the caller swallows the exception.

    """
    if actor.is_authenticated and actor.has_perm(IDENTITY_OVERRIDE_PERMISSION):
        return
    logger.warning(
        OVERRIDE_REFUSED_EVENT,
        reason=OVERRIDE_PERMISSION_MISSING,
        user_id=getattr(actor, "pk", None),
        idp_subject=getattr(actor, IDENTITY_FIELD, ""),
    )
    message = (
        f"user {getattr(actor, 'pk', None)!r} does not hold {IDENTITY_OVERRIDE_PERMISSION!r}, so this identity "
        f"override is refused. CPM-FR-3 makes the override the only human write that mutates governed reference "
        f"data and CPM-AD-14 gates it on a permission, which core/roles.py grants to the leadership role group "
        f"alone."
    )
    raise OverrideError(message)


def _require_reason(reason: str) -> str:
    """Refuse an override that does not say why it was made.

    `CPM-AD-14` requires a reason, and the refusal is here rather than at the
    column because a blank `TextField` is perfectly valid SQL: the row would be
    written, would be counted, and would record that somebody changed governed
    reference data for no stated reason -- an audit trail that answers the one
    question it exists to answer with nothing.

    Args:
        reason: What the actor gave as the justification.

    Returns:
        The reason with surrounding whitespace removed, which is the form the row
        carries.

    Raises:
        OverrideError: When it is empty or only whitespace.

    """
    justification = reason.strip()
    if not justification:
        message = (
            f"an identity override needs a reason; {reason!r} says nothing. CPM-AD-14 requires the correction "
            f"to record why it was made, and an audit row with a blank reason answers the one question it "
            f"exists to answer with nothing."
        )
        raise OverrideError(message)
    return justification


def _require_overridden_name(canonical_name: str) -> str:
    """Return the corrected name an override supplied, or blank for no correction.

    The empty string means "leave the stored name alone", which is the ordinary
    case for an override that raises a correct identity to `verified` or that only
    supplies a display name. Whitespace is *not* that: it is a correction to
    nothing, and writing it would be refused by `canonical_name_is_present` as an
    `IntegrityError` naming a constraint rather than the input that broke it.

    Written out rather than delegating to `_require_correction`, on the terms this
    module already states for `_require_key` and `_require_name`: the two refusals
    say different things -- a resolver that handed over an unusable name has a
    defect, a person who typed one has a typo -- and a shared message would say
    neither.

    Args:
        canonical_name: What the actor says the package should be called.

    Returns:
        The validated name, stripped, or the empty string when none was supplied.

    Raises:
        OverrideError: When a correction was supplied and is only whitespace, or
            is wider than `canonical_name` can hold.

    """
    if not canonical_name:
        return ""
    correction = canonical_name.strip()
    if not correction:
        message = (
            f"an identity override was given {canonical_name!r} as a canonical name, which names nothing. "
            f"Leave the name out entirely to correct something else about the identity; a package with no "
            f"name cannot be corrected, exported or found again (CPM-FR-2)."
        )
        raise OverrideError(message)
    if len(correction) > CANONICAL_NAME_LENGTH:
        raise OverrideError(_too_wide(correction, field=CANONICAL_NAME_FIELD, limit=CANONICAL_NAME_LENGTH))
    return correction


def _require_overridden_display_name(display_name: str | None) -> str | None:
    """Return the display name an override supplied, or `None` to leave it alone.

    `None` and `""` are two different instructions, and that distinction is the
    reason this parameter is nullable at all: `None` means the override said
    nothing about the display name, and `""` means it said there is not one.
    Blank means missing rather than empty (PRD Appendix A.1's data rules), so a
    whitespace-only value is normalised to `""` rather than refused -- "a display
    name of three spaces" is not a state worth being able to store.

    Args:
        display_name: What the actor supplied, or `None`.

    Returns:
        The value stripped, or `None` when nothing was supplied.

    Raises:
        OverrideError: When it is wider than `display_name` can hold. SQLite
            ignores `max_length` and PostgreSQL raises, so an unrefused over-long
            value is a working row on a developer's machine and a failed
            correction in the gate (`R-5`).

    """
    if display_name is None:
        return None
    replacement = display_name.strip()
    if len(replacement) > DISPLAY_NAME_LENGTH:
        raise OverrideError(_too_wide(replacement, field=DISPLAY_NAME_FIELD, limit=DISPLAY_NAME_LENGTH))
    return replacement


def _require_decided_at(instant: datetime) -> datetime:
    """Refuse a naive instant, on the same terms every other writer here does.

    `AppendOnlyModel.save()` refuses a naive `observed_at` as well, so this is the
    second guard on the same value -- and it is worth having, because it is the
    one that fires *before* the transaction opens. The base's refusal would fire
    inside it, after the correction had already been written, and a rollback that
    happens to be correct is not the same thing as a refusal that precedes every
    write.

    Args:
        instant: The value the clock answered.

    Returns:
        The instant, unchanged.

    Raises:
        OverrideError: When the instant carries no usable offset.

    """
    if not is_aware(instant):
        message = (
            f"an identity override was made with a naive instant ({instant!r}). The instant comes from a "
            f"Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to interpret and "
            f"would record a correction at a time it did not happen rather than failing."
        )
        raise OverrideError(message)
    return instant


def _package_with_id(package_id: int) -> Package:
    """Return the package one primary key names, locked, refusing when there is none.

    **Called from inside the override's transaction, and `select_for_update()` is
    why.** The audit row records the values this correction replaced, so between
    reading them and writing the new ones no other writer may change the row --
    otherwise two concurrent overrides both read the same prior values, both
    record them, and the second row is wrong about the thing it exists to be right
    about. The lock is also what makes `_require_name_is_unclaimed` a check rather
    than a guess: without it a name is free when it is tested and taken when it is
    written.

    PostgreSQL takes the row lock; SQLite has no row locks and Django's compiler
    emits nothing for it there, which is a real difference and a stated one. The
    gate is where this is proven (`pixi run gate-postgres`), on the terms every
    other database guarantee in this product is.

    Args:
        package_id: The surrogate integer primary key.

    Returns:
        The package row, re-read so the correction is applied to the row as it now
        stands rather than to a copy the caller may have been holding.

    Raises:
        OverrideError: When the id matches no row. Refused rather than created:
            `CPM-AD-25` makes `resolve_package_shell` the only creator of a
            package row, and an override that quietly created what it could not
            find would give the product a second creator -- exactly what
            `CPM-AD-14` and `CPM-AD-25` forbid.

    """
    try:
        return Package.objects.select_for_update().get(pk=package_id)
    except Package.DoesNotExist as unknown:
        message = (
            f"no package has the id {package_id!r}, so there is nothing to override. A package row is created "
            f"by resolve_package_shell during ingestion (CPM-AD-25); this door corrects one that exists and "
            f"never creates one."
        )
        raise OverrideError(message) from unknown


def _require_name_is_unclaimed(name: str, *, package: Package) -> None:
    """Refuse a correction onto a name another package already holds.

    `_require_name_is_free` refuses the same collision for `record_resolution` and
    the two share `_another_package_holds` -- one query, so the *rule* cannot
    drift. What is deliberately not shared is the message: that one names this
    door as where the merge belongs, and this one has to say that merging belongs
    to nobody yet. See `_require_name_is_free` for the whole of that.

    Without this the collision escapes as an `IntegrityError` from inside the
    transaction -- `canonical_name` is `unique=True` -- which would roll the audit
    row back correctly and tell the actor nothing about what they collided with.

    Args:
        name: The validated corrected name.
        package: The package being corrected.

    Raises:
        OverrideError: When another package already carries that name.

    """
    if not _another_package_holds(name, package=package):
        return
    message = (
        f"{name!r} is already another package's canonical name, so this override would collide with it. "
        f"canonical_name is unique (CPM-AD-3). Two rows for one upstream package are *merged* rather than "
        f"renamed onto each other -- which decides which associator key survives, which evidence moves and what "
        f"becomes of the mappings each side holds. No door in this product does that yet; it is owed by a later "
        f"story, and until then the collision is reported so a person can decide."
    )
    raise OverrideError(message)


def _another_package_holds(name: str, *, package: Package) -> bool:
    """Report whether some other package already carries a canonical name.

    One query for the two doors that ask the question. They ask it for different
    reasons and answer it with different messages, but "is this name taken by
    somebody else" is one rule -- and two copies of it are two things that can be
    changed one at a time, which is what `unique=True` would then catch as an
    `IntegrityError` naming a constraint instead.

    Args:
        name: The validated corrected name.
        package: The package the correction is against, excluded so a row keeping
            the name it already has is not a collision with itself.

    Returns:
        True when at least one other package carries that name.

    """
    return Package.objects.filter(canonical_name=name).exclude(pk=package.pk).exists()


def _write_correction(
    package: Package,
    *,
    canonical_name: str,
    display_name: str | None,
    decided_at: datetime,
) -> None:
    """Write what this override settled, and no other column.

    `update_fields` is built from what was actually written rather than listing
    every column, which is what keeps `identity_source` and `associator_key` out
    of it by construction instead of by somebody remembering to omit them -- the
    same discipline `_write_identity` applies, for the same reason. Nothing on
    `Feedstock`, `PackageMapping` or `core.PackageHealth` is touched either: this
    function names three columns of one row and reaches no other table.

    **The confidence is always `verified`, and a correction cannot lower it.**
    `CPM-AD-4` describes that value as an identity a person established, and a
    person establishing one is precisely what this door is. `Correction` therefore
    carries no confidence field at all -- see its docstring for the trade, which is
    that a reviewer concluding a package genuinely has no upstream identity has no
    way to say so here, and why that is a *resolution's* finding rather than a
    correction. It is written unconditionally rather than only when it changes; the
    diff below is what stops an already-`verified` package from being saved again
    for nothing.

    **`resolved_at` advances only when something else did, and never backwards.**
    Two rules over one column, and they are not the same one. The first is
    `_write_identity`'s: the column records when the identity last *changed*, and
    an override that confirmed an already-correct, already-`verified` identity
    changed nothing about it -- so a confirmation writes an audit row and leaves
    the package row alone. The second is this door's own, because this is the only
    writer whose instant a *person* chooses: a correction made with an earlier
    clock than the stored value would move the column backwards, and every
    freshness read after it would judge the row older than it is. So the column is
    advanced only when the new instant is later, and a correction stamped from
    behind still lands -- it simply does not rewrite when the identity was last
    settled.

    Args:
        package: The row to correct, already found and locked by its primary key.
        canonical_name: The validated corrected name, or blank for no correction.
        display_name: The validated display name, or `None` to leave it alone.
        decided_at: The instant from the clock.

    """
    intended: dict[str, object] = {"confidence": IdentityConfidence.VERIFIED.value}
    if canonical_name:
        intended[CANONICAL_NAME_FIELD] = canonical_name
    if display_name is not None:
        intended[DISPLAY_NAME_FIELD] = display_name
    written = {name: value for name, value in intended.items() if getattr(package, name) != value}
    if not written:
        return
    if package.resolved_at is None or decided_at > package.resolved_at:
        written["resolved_at"] = decided_at
    for name, value in written.items():
        setattr(package, name, value)
    package.save(update_fields=sorted(written))
