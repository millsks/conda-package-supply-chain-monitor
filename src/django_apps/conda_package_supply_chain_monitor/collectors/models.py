"""What the inventory observed, as evidence, and the cut-off-bound way to read it.

`CPM-AD-25`: "the internal inventory is observed by a collector like any other
source ... and writes `inventory_snapshots` -- append-only rows carrying the
source's package key, the internal usage signals as observed, `observed_at`, and
the run's correlation identifiers." This module is that table and the one read
against it.

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
    "SNAPSHOT_KEY_INDEX",
    "SNAPSHOT_READ_INDEX",
    "InventoryReadError",
    "InventorySnapshot",
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
