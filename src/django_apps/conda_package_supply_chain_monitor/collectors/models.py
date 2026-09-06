"""What this application's collectors observed, as evidence, and how it is read.

`CPM-AD-25`: "the internal inventory is observed by a collector like any other
source ... and writes `inventory_snapshots` -- append-only rows carrying the
source's package key, the internal usage signals as observed, `observed_at`, and
the run's correlation identifiers." This module is that table, the one read
against it, and -- since `CPM-CURRENCY-S01` -- the upstream release table beside
it.

**One module, two tables, and no shared columns beyond the ones every evidence
row carries.** `CPM-AD-7` gives each collector its own evidence table, which is a
rule about tables rather than about files: `inventory_snapshots` and
`source_release_snapshots` are written by two collectors that share nothing but
the log, and neither reads the other's. They live together because Django
auto-imports `<app>.models` and no other module, so a model declared elsewhere in
this application is registered only by whatever happens to import it -- which is
a table that exists on a developer's machine and not in a migration.

**The first evidence model in this repository.** `core/models.py` has carried
`AppendOnlyModel` since `CPM-EVIDENCE-S02` with nothing inheriting it, and three
audits have swept an empty set ever since. They now have something to sweep, and
none of them needed an edit to start mattering: `tests/model_registry.py`
classifies this as evidence by all three of its marks, so the inheritance,
constraint and outcome-field sweeps reach it by construction.

**Presence is `state`, not a boolean.** `CPM-AD-5` bans boolean status fields
outright, and the base's `sentinel_evidence` hook already requires an
`OutcomeState` value carried verbatim in a concrete field. So absence is
expressible through machinery `core` owns: a package the source listed is `ok`,
and one it stopped listing is `not_found`. A `present = BooleanField()` beside it
would be a second vocabulary for one fact, and it would put this model outside
the sentinel path the base checks.

**The counts are required of a present observation and of nothing else.** PRD
Open Question 3b makes `internal_component_count` and `internal_lob_count`
required on every inventory *record* -- together they are the internal usage
breadth `CPM-FR-4` ranks by -- while `apps`, `platforms`, `downloads` and
`versions` are nullable score inputs. But an *absence* row observes no counts at
all, and a `not_found` sentinel observes nothing whatever, so a NOT NULL column
would make the two unwritable. The requirement is therefore a
`CheckConstraint` reading "both counts are present exactly when `state` is `ok`",
which is where the rule is actually true. A `CheckConstraint` is permitted on an
evidence model; a `UniqueConstraint` is not, and
`tests/unit/django_apps/test_evidence_constraint_audit.py` is what keeps it that
way -- a constraint spanning the observed fact would turn a re-observation into
an `IntegrityError` (`CPM-AD-2`, `CPM-AD-7`).

**NULL means missing and `0` means zero.** PRD Appendix A.1's data rules say
blank means missing and values are never invented, and Open Question 3b says the
four optional signals stay distinguishable from zero. That is the whole reason
they are nullable integers rather than integers defaulting to `0`: a package with
no recorded download count and a package nobody downloaded are different facts,
and a score built on them must be able to tell.

**`PROTECT`, and it is required rather than preferred** (`EVIDENCE.02-AUDIT-001`).
Django's deletion collector issues its `DELETE` through `sql.DeleteQuery`, never
through `QuerySet.delete()` or `Model.delete()`, so a `CASCADE` from here would
destroy observations when a package went and every append-only refusal in
`core/models.py` would be bypassed on the way. `PROTECT` makes the database
refuse instead -- which is also `CPM-AD-25`'s "no package row is ever deleted",
enforced rather than intended.

**Reading is cut-off bound, and `snapshot_as_of` is the only supported way.**
`CPM-AD-25`: "a policy reading a usage signal reads the latest snapshot at or
before its run's cut-off, never the current value", which is what makes
`CPM-FR-22`'s replay reproduce identical results. A caller that reached for
`.latest()` or `.first()` would read whatever the most recent sweep happened to
write, and a replay of the same policy version at the same stated cut-off would
then conclude something different every time the inventory changed.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Final

from django.db import models
from django.utils.translation import gettext_lazy as _

from conda_package_supply_chain_monitor.core.clock import is_aware
from conda_package_supply_chain_monitor.core.models import AppendOnlyModel
from conda_package_supply_chain_monitor.core.outcomes import OutcomeState
from conda_package_supply_chain_monitor.identity.models import Package

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "COUNTS_PRESENT_CONSTRAINT",
    "RELEASE_FACTS_CONSTRAINT",
    "RELEASE_READ_INDEX",
    "SNAPSHOT_KEY_INDEX",
    "SNAPSHOT_READ_INDEX",
    "InventoryReadError",
    "InventorySnapshot",
    "SourceReleaseSnapshot",
    "snapshot_as_of",
]

#: How wide the source's own package key column is. Sized as an identifier
#: rather than as a name, on the same terms `identity/models.py` sizes
#: `associator_key`: it is a key some other system chose, not a word a person
#: picked, and neither its shape nor its bound is this product's to guess at.
_KEY_LENGTH: Final[int] = 512

#: How wide the `state` column is. `OutcomeState`'s longest value is
#: `not_applicable`, fourteen characters, and the rest is headroom. Not sized
#: against `core/models.py`'s `_STATUS_LENGTH`, which is 16 and holds `RunState`
#: -- two vocabularies, two widths, each argued from its own longest value.
_STATE_LENGTH: Final[int] = 32

#: How wide the correlation identifier is. `CPM-AD-15` takes it from the active
#: span formatted `032x`, so it is exactly 32 hexadecimal digits, which is the
#: same number `core/models.py` declares for `CollectionRun.trace_id`. Restated
#: here rather than imported: that constant is private to its module, and one
#: spelling shared by import would still be two column declarations. What keeps
#: them in step is that both are 32 because the format says 32, and
#: `tests/integration/django_apps/test_run_ledger.py` pins the format itself.
_TRACE_ID_LENGTH: Final[int] = 32

#: The name of the constraint that makes the counts required where they are
#: required. Named here because the model declares it and the case that asserts
#: the database refuses a violation names it too, and a string spelled twice is
#: a constraint that can be renamed on one side only.
COUNTS_PRESENT_CONSTRAINT: Final[str] = "inventory_counts_present_exactly_when_observed"

#: The two indexes this table's two access paths need, by name.
#:
#: Indexes are permitted on an evidence model and unique *constraints* are not,
#: and the difference is exactly the one `CPM-AD-2` draws: an index makes a read
#: cheaper and changes no write, while a unique constraint turns a re-observation
#: into an `IntegrityError`. `tests/unit/django_apps/test_evidence_constraint_audit.py`
#: reads `Meta.constraints` and the field flags, never `Meta.indexes`.
#:
#: `SNAPSHOT_READ_INDEX` serves `snapshot_as_of`, which is every policy pass's
#: read: filter by package, order by `observed_at` descending, take one. Without
#: it that is a scan of one package's whole observation history on every read, and
#: the history grows daily and is never pruned. `SNAPSHOT_KEY_INDEX` serves the
#: ingestion collector's absence derivation, which excludes on
#: `source_package_key` across the whole table once per sweep.
#:
#: Django caps an index name at 30 characters, which is why neither spells out
#: `inventory_snapshot`.
SNAPSHOT_READ_INDEX: Final[str] = "inv_snapshot_pkg_observed"
SNAPSHOT_KEY_INDEX: Final[str] = "inv_snapshot_source_key"

#: How wide the upstream version column is. A release tag is a string a project
#: chose rather than a name a person picked -- `v1.2.3`, `2024.11.0rc1`,
#: `release/2025-06-11`, and occasionally a whole sentence -- so it is sized like
#: an identifier rather than like the 128 `identity/models.py` gives a name. It is
#: its own constant rather than `_KEY_LENGTH` reused: the two answer to different
#: sources, an inventory's key format and an upstream project's tagging habits,
#: and one of them changing is not a reason to move the other.
_VERSION_LENGTH: Final[int] = 512

#: How wide the locator column is. A locator is a URL this collector built from
#: an owner and a repository, so it is bounded by the same reasoning `_KEY_LENGTH`
#: carries -- a machine-generated string, not a name a person picked -- and by the
#: same number, because both are sized as identifiers rather than ordered against
#: each other.
_LOCATOR_LENGTH: Final[int] = 512

#: The name of the constraint that makes the release facts present exactly where
#: they are true, and the read index the freshness query needs. Named here for the
#: reason the two above are: the model declares them and the cases that assert the
#: database refuses a violation name them too, and a string spelled twice is a
#: constraint that can be renamed on one side only.
#:
#: Django caps an index name at 30 characters, which is why the index does not
#: spell out `source_release_snapshot`.
RELEASE_FACTS_CONSTRAINT: Final[str] = "release_facts_present_exactly_when_observed"
RELEASE_READ_INDEX: Final[str] = "src_release_pkg_observed"


class InventoryReadError(ValueError):
    """An inventory read was asked for in terms it cannot be answered in.

    A `ValueError` subclass, matching `core/freshness.py`'s `FreshnessError` and
    `core/collection.py`'s `CollectorConfigurationError`: every "this input
    cannot describe what it claims to" in this product is a `ValueError`, so a
    caller catching one catches them all.
    """


class InventorySnapshot(AppendOnlyModel):
    """One observation of one package by the inventory source. Table `inventory_snapshots`.

    See the module docstring for why presence is `state`, why the counts are a
    constraint rather than NOT NULL columns, and why the relation is `PROTECT`.

    `observed_at` and `objects` come from `AppendOnlyModel`: the instant is
    supplied by the writer from an injected `Clock` (`CPM-AD-26`) and the manager
    is the one that offers no `update()` and no `delete()` (`CPM-AD-2`).
    """

    #: The package this observation is about, by the integer primary key
    #: `CPM-AD-3` fixes -- a real `ForeignKey`, as every reference to a package
    #: in this product now is (`core.CollectionRun`'s became one in
    #: `CPM-EVIDENCE-S09`).
    #:
    #: Non-nullable, which is the difference that matters here: an observation is
    #: always *about* a package, and this table's writer creates the package
    #: before it writes the row -- the shell and the snapshot commit together
    #: (`CPM-AD-25`, `CPM-AD-23`). A run ledger's reference is nullable because a
    #: sweep is scoped to no package; an observation of no package is not a thing
    #: that happens.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="inventory_snapshots",
        verbose_name=_("package"),
    )

    #: The key the inventory source used for this package, kept so a row can be
    #: traced back to the record that produced it (`CPM-FR-42`). Stored on every
    #: row including an absence one, whose key is the one the source last used:
    #: "this key stopped appearing" is the observation, and a row that could not
    #: say which key would not be one.
    source_package_key = models.CharField(_("source package key"), max_length=_KEY_LENGTH)

    #: What the source said about this package, over `OutcomeState` and emitted
    #: verbatim (`CPM-AD-24`). `ok` when the source listed it, `not_found` when a
    #: source that listed it before no longer does, and `error` for the base's
    #: sentinel path. Never a boolean (`CPM-AD-5`).
    state = models.CharField(_("state"), max_length=_STATE_LENGTH, choices=OutcomeState.choices)

    #: How many internal components use this package. Required of a present
    #: observation and absent from every other kind -- see `Meta.constraints`.
    internal_component_count = models.PositiveIntegerField(
        _("internal component count"),
        null=True,
        blank=True,
        default=None,
    )

    #: How many internal lines of business use it. The other half of the
    #: "internal usage breadth" `CPM-FR-4` ranks by, and required on the same
    #: terms.
    internal_lob_count = models.PositiveIntegerField(_("internal LOB count"), null=True, blank=True, default=None)

    #: How many applications name it. A nullable score input (Open Question 3b):
    #: NULL means the source did not say, which stays distinguishable from a
    #: stored `0`.
    apps = models.PositiveIntegerField(_("apps"), null=True, blank=True, default=None)

    #: How many platforms it is used on. Nullable on the same terms as `apps`.
    platforms = models.PositiveIntegerField(_("platforms"), null=True, blank=True, default=None)

    #: How many times it was downloaded internally. Nullable on the same terms as
    #: `apps`, and the signal the missing-versus-zero distinction was argued
    #: about: a package nobody downloaded is not a package nobody counted.
    downloads = models.PositiveIntegerField(_("downloads"), null=True, blank=True, default=None)

    #: How many versions of it are in use. Nullable on the same terms as `apps`.
    versions = models.PositiveIntegerField(_("versions"), null=True, blank=True, default=None)

    #: What the collector or the base had to say about this observation -- the
    #: sentinel path's reason, or the words that go with an absence. Empty on an
    #: ordinary present observation, which needs no explanation.
    detail = models.TextField(_("detail"), blank=True, default="")

    #: The `trace_id` of the task that made this observation, formatted `032x`
    #: exactly as `config/observability/logging.py` formats it for every log line
    #: (`CPM-AD-15`). Empty when no span was active, which never blocks a write:
    #: an uncorrelated observation is worth more than no observation.
    trace_id = models.CharField(_("trace id"), max_length=_TRACE_ID_LENGTH, blank=True, default="")

    class Meta:
        """The table PRD Appendix A.2 names, not the `collectors_inventorysnapshot` Django derives.

        Rejected for the reason `core/models.py` and `identity/models.py` reject
        theirs: the tables in this product are named by the architecture and the
        PRD, and a derived name would make the schema depend on which
        application happened to declare the model.

        **No unique constraint of any kind** (`CPM-AD-2`, `CPM-AD-7`). Two
        observations of one package by one source are two rows, and idempotency
        is the run ledger's property rather than this table's -- a constraint
        spanning the observed fact would turn a re-observation into an
        `IntegrityError`, which is the same history loss arriving as a crash
        instead of an overwrite.
        """

        db_table = "inventory_snapshots"
        verbose_name = _("inventory snapshot")
        verbose_name_plural = _("inventory snapshots")
        indexes = [
            # The cut-off-bound read's shape, in the order it asks for it: one
            # package, newest observation first. Django's automatic foreign-key
            # index covers the filter alone and leaves the sort to a scan of that
            # package's whole history.
            models.Index(fields=["package", "-observed_at"], name=SNAPSHOT_READ_INDEX),
            # The absence derivation's, which asks about a key rather than about
            # a package -- it is the source's own identifier that stops appearing,
            # and the package is what that resolves to.
            models.Index(fields=["source_package_key"], name=SNAPSHOT_KEY_INDEX),
        ]
        constraints = [
            # The biconditional, and both halves are load bearing. A present
            # observation missing a count is a record the source should have
            # been refused for (`CPM-FR-42`); an absence row *carrying* counts
            # is a row claiming to have observed usage for a package the source
            # did not list, which is exactly the invented value Appendix A.1's
            # data rules forbid. `state` is NOT NULL and an `IS NULL` test is
            # never itself NULL, so this expression is always true or false and
            # never the third thing a SQL CHECK can be.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state=OutcomeState.OK,
                        internal_component_count__isnull=False,
                        internal_lob_count__isnull=False,
                    )
                    | (
                        ~models.Q(state=OutcomeState.OK)
                        & models.Q(internal_component_count__isnull=True, internal_lob_count__isnull=True)
                    )
                ),
                name=COUNTS_PRESENT_CONSTRAINT,
            ),
        ]

    def __str__(self) -> str:
        """Return the source's key, the state and when it was observed.

        Returns:
            A one-line summary. Read off `source_package_key` and `package_id`
            rather than off `package`, because the related object of an unsaved
            instance raises `RelatedObjectDoesNotExist` -- and a `__str__` that
            raises breaks the two places a half-built object is most likely to be
            rendered, a debugger and a traceback.

        """
        key = self.source_package_key or "(no source package key)"
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        when = "never" if self.observed_at is None else self.observed_at.isoformat()
        return f"{key} for {scope}: {self.state} at {when}"


def snapshot_as_of(*, package_id: int, cutoff: datetime) -> InventorySnapshot | None:
    """Return the latest observation of one package at or before a stated cut-off.

    `CPM-AD-25`'s cut-off-bound read, and the only supported one. A policy pass
    reads a usage signal *as of* its run's stated cut-off rather than as of now,
    which is what makes `CPM-FR-22`'s replay reproduce identical results: the row
    this returns for a given `(package, cutoff)` pair does not change when a
    later sweep writes another one.

    Args:
        package_id: The package being asked about, by the integer primary key
            `CPM-AD-3` fixes.
        cutoff: The instant to read as of, aware. `CPM-AD-21` makes it the
            `finished_at` of a completed collection run, so a pass never reads
            evidence written by a run that is still `running`.

    Returns:
        The newest snapshot whose `observed_at` is at or before the cut-off, or
        `None` when the package had none by then. `None` is not an error: a
        cut-off earlier than a package's first observation is an ordinary
        question with an ordinary answer, and inventing a row would be the
        clean-looking result `CPM-NFR-3` forbids.

        Ties are broken by descending primary key. Two rows can share an
        `observed_at` -- one sweep writes every row it produces with the run's
        one instant (`CPM-AD-7`) -- so an unordered tie would make the answer
        depend on the database's own arbitrary row order, and a replay would
        stop being a replay.

    Raises:
        InventoryReadError: When `cutoff` is naive. Refused rather than
            converted, on the same terms `core/freshness.py` refuses one: there
            is no offset to convert from, `USE_TZ` is on so Django would read it
            as if it were UTC, and a cut-off silently shifted by the reader's
            offset selects a different evidence set on every replay -- which is
            the opposite of what `CPM-FR-22` promises.

    """
    if not is_aware(cutoff):
        message = (
            f"an inventory snapshot cannot be read as of the naive cutoff {cutoff!r}. Every instant comes "
            f"from a Clock, which always answers in UTC (CPM-AD-26); a naive value has no offset to "
            f"interpret, so the read would be silently shifted by whichever offset the reader happened to "
            f"be in and the replay CPM-FR-22 promises would return a different set each time."
        )
        raise InventoryReadError(message)
    return (
        InventorySnapshot.objects.filter(package_id=package_id, observed_at__lte=cutoff)
        .order_by("-observed_at", "-pk")
        .first()
    )


class SourceReleaseSnapshot(AppendOnlyModel):
    """One observation of a package's upstream releases. Table `source_release_snapshots`.

    PRD Appendix A.2 gives this table four facts -- "upstream latest version,
    release date, repository activity, lookup status" -- and `CPM-FR-7` is where
    they come from: "latest release or tag, its date, and a repository activity
    signal from the package's source repository", with the lookup status recorded
    explicitly.

    **The lookup status is `state`, over `OutcomeState`, and never a boolean**
    (`CPM-AD-5`). `ok` is a version this run read; `not_found` is the source
    answering that there is none -- because the repository could not be read, or
    because it publishes no releases *and* lists no tags; `error` is a look that
    failed. Which of the two `not_found` means is in `detail`, and the reason it
    is there rather than in a second status column is that `OutcomeState` says
    what may be claimed about the package rather than why the run went the way it
    did. The
    column is called `state` rather than `*_status` for the reason
    `InventorySnapshot.state` is: `tests/unit/django_apps/test_outcome_field_audit.py`
    sweeps the derived-status *names*, and a collector's observation of what a
    source said is not a status a policy derived (`CPM-AD-8`).

    **A `not_found` row is the point of the table rather than an edge of it.**
    `CPM-FR-7` says a repository that publishes no releases "records that fact
    rather than reporting stale", and this is where that fact lives: a row, with
    this run's `observed_at`, carrying `not_found` and no version. Recording it as
    a missing observation instead would make the package read as unobserved --
    which `core/freshness.py` reports as `unknown` and which ages into stale --
    and the difference between "we have not looked" and "we looked and there is
    nothing to find" is exactly what `CPM-FR-6` exists to keep.

    **`releases_seen` is nullable because zero is an answer.** A row written from
    a document the collector actually read carries the number of releases that
    document listed, and `0` is a real observation. A sentinel row -- the base's
    `error` or `not_found` for a call that produced no document -- carries NULL,
    because nothing was counted. That is PRD Appendix A.1's "blank means missing;
    values are never invented" applied to the one column where missing and zero
    are both reachable.

    **`released_at` and `last_activity_at` are two facts, not one written twice.**
    The first is when the latest *release* -- the newest entry that is neither a
    draft nor a prerelease -- was published, which is what a currency comparison
    (`CPM-FR-16`) is made against. The second is the most recent instant the
    source showed any release activity at all, prereleases included, which is the
    repository activity signal `CPM-FR-7` asks for and is what distinguishes a
    project that stopped from one that is mid-cycle. They differ exactly when a
    project is actively cutting prereleases, which is the case the distinction was
    made for.

    **A determinate row may carry no date, and `source` is what says why.**
    `CPM-FR-7` asks for the latest release **or tag**, and a tag carries no
    publication date -- the endpoint that lists them supplies none. So a row whose
    version came from a tag is `ok`, names the version, and leaves `released_at`
    NULL; the constraint below permits exactly that and nothing looser. What tells
    a reader which happened is the `source` column, which names the locator the
    observation came from -- a releases endpoint or a tags one -- and which is
    also what keeps two observations of *different* repositories apart in an
    append-only history: `Package.source_repository_url` is mutable, so a package
    can be resolved to one repository and later corrected to another, and without
    this column nothing on the rows would say which was read.

    **A `not_found` row is weaker than it looks while no credential is
    configured.** `core/transport.py` reads `404` and `410` as "the source says
    this does not exist", and GitHub answers `404` identically for an absent
    repository, a private one, one that has moved and one that is blocked -- by
    design, so an unauthenticated reader cannot enumerate private repositories.
    The collector sends no credential, so it records the caveat in `detail` rather
    than claiming a fact it cannot support, and a reader comparing these rows must
    treat `not_found` as "absent **or** unreadable" until authentication lands.

    **`PROTECT`, and it is required rather than preferred**
    (`EVIDENCE.02-AUDIT-001`), on the terms `InventorySnapshot.package` states:
    Django's deletion collector issues its `DELETE` through `sql.DeleteQuery` and
    would go past every append-only refusal in `core/models.py` on the way.

    `observed_at` and `objects` come from `AppendOnlyModel`: the instant is
    supplied by the writer from an injected `Clock` (`CPM-AD-26`) and the manager
    is the one that offers no `update()` and no `delete()` (`CPM-AD-2`).
    """

    #: The package this observation is about, by the integer primary key
    #: `CPM-AD-3` fixes. Non-nullable: an observation is always about a package,
    #: and this collector is only ever asked about one that already has a row.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        related_name="source_release_snapshots",
        verbose_name=_("package"),
    )

    #: The locator this observation was read from -- a releases endpoint or a tags
    #: one, naming the owner and repository that answered.
    #:
    #: Recorded on the row rather than left to the run ledger, because the ledger
    #: is not what a read surface queries: a policy comparing a package's
    #: observation history reads this table, and `Package.source_repository_url`
    #: is mutable, so the history can legitimately hold rows read from two
    #: different repositories with nothing else on them to tell which. Blank only
    #: on a row written by a caller that reached `sentinel_evidence` without
    #: asking for a locator first, which the base never does -- blank means
    #: missing, as it does everywhere else here.
    source = models.CharField(_("source"), max_length=_LOCATOR_LENGTH, blank=True, default="")

    #: What the lookup concluded, over `OutcomeState` and emitted verbatim
    #: (`CPM-AD-24`). See the class docstring for what each value means here.
    state = models.CharField(_("state"), max_length=_STATE_LENGTH, choices=OutcomeState.choices)

    #: The tag the latest upstream release carries, exactly as the source spelled
    #: it. Stored raw rather than normalised: `CPM-FR-16`'s comparison is a policy
    #: pass's (`CPM-AD-8`), and a collector that normalised a version would be
    #: deriving a value into an append-only row nothing may correct. Blank on every
    #: row that is not a determinate observation -- see `Meta.constraints`.
    latest_version = models.CharField(_("latest version"), max_length=_VERSION_LENGTH, blank=True, default="")

    #: When that release was published. NULL on every row that is not a
    #: determinate observation -- and NULL on a determinate one whose version came
    #: from a *tag*, because a tag carries no publication date. The constraint
    #: below says exactly that: a determinate row names a version, and a date is
    #: something only a release can supply.
    released_at = models.DateTimeField(_("released at"), null=True, blank=True, default=None)

    #: The repository activity signal: the most recent release activity the source
    #: showed, prereleases included. NULL when the source showed none, and
    #: permitted on a `not_found` row -- a repository that has cut only prereleases
    #: has no latest release and is plainly active, and a column that could not say
    #: both would lose the more interesting half.
    last_activity_at = models.DateTimeField(_("last activity at"), null=True, blank=True, default=None)

    #: How many releases the document this run read listed. `0` is an observation
    #: and NULL is the absence of one; see the class docstring. It stays `0` on a
    #: row whose version came from a tag, because the fallback is reached only
    #: when the release list was empty and that is the fact this column records.
    releases_seen = models.PositiveIntegerField(_("releases seen"), null=True, blank=True, default=None)

    #: What the collector or the base had to say about this observation -- the
    #: sentinel path's reason, or the words that go with a repository publishing
    #: nothing. Empty on an ordinary determinate observation, which needs no
    #: explanation.
    detail = models.TextField(_("detail"), blank=True, default="")

    #: The `trace_id` of the task that made this observation, formatted `032x`
    #: exactly as `config/observability/logging.py` formats it for every log line
    #: (`CPM-AD-15`). Empty when no span was active, which never blocks a write.
    trace_id = models.CharField(_("trace id"), max_length=_TRACE_ID_LENGTH, blank=True, default="")

    class Meta:
        """The table PRD Appendix A.2 names, not the `collectors_sourcereleasesnapshot` Django derives.

        Rejected for the reason `InventorySnapshot.Meta` rejects its own: the
        tables in this product are named by the architecture and the PRD, and a
        derived name would make the schema depend on which application happened to
        declare the model.

        **No unique constraint of any kind** (`CPM-AD-2`, `CPM-AD-7`). Two
        observations of one package's releases are two rows, and idempotency is
        the run ledger's property rather than this table's.
        """

        db_table = "source_release_snapshots"
        verbose_name = _("source release snapshot")
        verbose_name_plural = _("source release snapshots")
        indexes = [
            # `core/freshness.py`'s `latest_observation` reads exactly this: one
            # package, newest observation first. Django's automatic foreign-key
            # index covers the filter alone and leaves the sort to a scan of that
            # package's whole observation history, which grows daily and is never
            # pruned.
            models.Index(fields=["package", "-observed_at"], name=RELEASE_READ_INDEX),
        ]
        constraints = [
            # The biconditional, and all three conjuncts are load bearing.
            #
            # A determinate observation with no version is a row saying "there is
            # a latest version" while declining to say which -- the guess
            # `CPM-FR-1`'s sibling rule forbids in identity, and worse here
            # because nothing may correct it. A row that is *not* determinate and
            # carries a version is claiming to have observed something the run
            # never saw; one that carries a *date* without a version is claiming
            # a release date for a release it cannot name.
            #
            # A date is deliberately not required of a determinate row.
            # `CPM-FR-7` asks for the latest release **or tag**, and the endpoint
            # that lists tags supplies no date, so a tagged observation is `ok`,
            # names its version, and dates nothing. Requiring the date here would
            # make the honest answer unwritable and would push the collector into
            # inventing one.
            #
            # `state` is NOT NULL and an `IS NULL` test is never itself NULL, so
            # this expression is always true or false and never the third thing a
            # SQL CHECK can be.
            models.CheckConstraint(
                condition=(
                    (models.Q(state=OutcomeState.OK) & ~models.Q(latest_version=""))
                    | (~models.Q(state=OutcomeState.OK) & models.Q(latest_version="", released_at__isnull=True))
                ),
                name=RELEASE_FACTS_CONSTRAINT,
            ),
        ]

    def __str__(self) -> str:
        """Return the version, the state and when it was observed.

        Returns:
            A one-line summary. Read off `package_id` rather than off `package`,
            because the related object of an unsaved instance raises
            `RelatedObjectDoesNotExist` -- and a `__str__` that raises breaks the
            two places a half-built object is most likely to be rendered, a
            debugger and a traceback.

        """
        version = self.latest_version or "(no release)"
        scope = "no package" if self.package_id is None else f"package {self.package_id}"
        when = "never" if self.observed_at is None else self.observed_at.isoformat()
        return f"{version} for {scope}: {self.state} at {when}"
