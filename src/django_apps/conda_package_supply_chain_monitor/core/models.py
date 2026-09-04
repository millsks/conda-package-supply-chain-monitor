"""The append-only base every evidence model inherits, and the refusals it carries.

`CPM-AD-2`: "evidence models inherit an abstract base in `core` whose `save()`
refuses when `pk` is set, and whose manager exposes no `update()` or `delete()`.
Re-observation always inserts." `CPM-FR-36` is the requirement and `R-06` is the
risk: once a collector updates an evidence row instead of inserting one, what the
system knew at a point in time is gone, and no later fix reconstructs it. There
is no migration back from an overwritten history, which is why the guard is a
refusal at the write rather than a review convention.

**What this base is not.** It declares no table. `Meta.abstract = True`, so
`makemigrations` produces nothing for it, and it is deliberately not accompanied
by a concrete evidence model: `CPM-AD-7` gives each collector its own evidence
table, and the first of them arrives with `CPM-EP-CURRENCY`. The run ledger --
`collection_runs` and `policy_runs` -- is explicitly *exempt* from this base by
`CPM-AD-2` and belongs to `CPM-EVIDENCE-S03`: a run row is created before the
first outbound call and finalized afterwards, so it is mutable by construction
and is not evidence.

**`observed_at` carries no default, and that is forced rather than chosen.** The
two idiomatic Django spellings -- `default=timezone.now` and `auto_now_add=True`
-- are both failures of `EVIDENCE.01-AUDIT-002`, because both read the process
wall clock where the row is written. `CPM-AD-26` wants the instant injected, so
that freshness targets and observation windows are testable without waiting or
freezing time process-wide. The writer therefore supplies the instant from its
`Clock`, and `save()` refuses a row that has none -- the omission is loud rather
than a silent epoch-zero row that a later staleness query reads as ancient.

**Why "`pk` is set" is the whole rule.** It is what `CPM-AD-2` says, and it is
also the widest form of the accident: an instance loaded from the database and
saved again is the path nobody writes on purpose, and it is indistinguishable
from a constructed one except by its primary key. The consequence, stated rather
than discovered: a model whose primary key the *writer* assigns before the first
save cannot use this base. Nothing in this product does that -- `CPM-AD-3` fixes
every table on a surrogate key, which Django assigns at insert -- and a model
that needed one would be asking for a natural key on evidence, which is a
separate decision.

**What the guard cannot see, and what closes it.** `save()` is one write path of
several, and the others do not construct an instance at all:

* `queryset.update()`, `bulk_update()`, `QuerySet.delete()` and `_raw_delete()`
  are refused by the queryset below, and reach the *manager* spellings through
  it. `Meta.base_manager_name` is what stops `_base_manager` being a plain,
  unguarded manager Django builds on the model's behalf.
* `bulk_create(update_conflicts=True)` is an `UPDATE` compiled into an insert;
  the queryset refuses it, and the plain insert stays untouched.
* **Cascade deletion goes past every refusal here.** Django's deletion collector
  issues its `DELETE` through `sql.DeleteQuery`, never through `QuerySet.delete()`
  or `Model.delete()`, so a `ForeignKey(..., on_delete=CASCADE)` from an evidence
  row destroys observations when the parent goes -- and `SET_NULL` and
  `SET_DEFAULT` rewrite them in place. Nothing in this class can see that; what
  closes it is `EVIDENCE.02-AUDIT-001`, which requires every relation on an
  evidence model to use `PROTECT`, `RESTRICT` or `DO_NOTHING`.
* Raw SQL is closed by `tests/unit/django_apps/test_mutation_path_audit.py`
  (`EVIDENCE.02-AUDIT-002`), which sweeps the product's own source for every
  bypass form plus cursor-level `UPDATE`, `DELETE` and `ON CONFLICT`.

Two audits hold the shape of the models themselves:
`test_evidence_inheritance_audit.py` (`EVIDENCE.02-AUDIT-001`), that every
evidence model inherits this base, keeps its managers and cannot be deleted
through a relation; and `test_evidence_constraint_audit.py`
(`EVIDENCE.02-AUDIT-003`), that none carries a unique constraint -- a constraint
spanning the observed fact would turn a re-observation into an `IntegrityError`,
which is the same history loss arriving as a crash instead of an overwrite.

**Inserts are left alone, deliberately.** `create()`, `acreate()` and plain
`bulk_create()` stay exactly as Django wrote them: an insert is not a mutation,
and a base that made bulk insertion awkward would push collectors toward raw SQL,
which is the one write path nothing here can guard.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited*
platform decision; a decision from this product's own architecture spine always
carries the `CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar
from typing import override

from django.db import models
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from collections.abc import Collection
    from collections.abc import Iterable
    from datetime import datetime

    from django.db.models.base import ModelBase

__all__ = [
    "AppendOnlyError",
    "AppendOnlyManager",
    "AppendOnlyModel",
    "AppendOnlyQuerySet",
]

#: The model an append-only queryset or manager is bound to. Bound to
#: `models.Model` rather than to `AppendOnlyModel` so that the queryset can be
#: constructed against a subclass without the manager's type collapsing to the
#: abstract base.
_EvidenceModel = TypeVar("_EvidenceModel", bound=models.Model)


class AppendOnlyError(Exception):
    """An operation would have changed or removed evidence that is already written.

    One type rather than a hierarchy, on the same terms as
    `config/authorization/exceptions.py`'s `ClaimsRejected`: no caller branches on
    *which* mutating path was attempted -- every one of them is a defect to be
    fixed at the call site, not a condition to be handled -- so the detail lives
    in the message and in the attributes rather than in the class.

    It raises rather than warning or logging-and-continuing, which inherited
    `CG-3` requires: a warning on an overwritten observation is a warning nobody
    reads until the history is already gone.

    Attributes:
        model_label: The `app_label.ModelName` of the table the operation would
            have touched, so a failure names the model without the reader parsing
            the message.
        pk: The primary key of the row, where one operation was aimed at a
            single row. `None` for a queryset-wide operation, which has no one
            row to name.

    """

    def __init__(self, message: str, *, model_label: str, pk: object = None) -> None:
        """Record the message and the row it names.

        Args:
            message: What was attempted and why it was refused.
            model_label: The `app_label.ModelName` of the model.
            pk: The primary key of the row, or `None` for a set-wide operation.

        """
        super().__init__(message)
        self.model_label = model_label
        self.pk = pk


def _label(model: type[models.Model]) -> str:
    """Return a model's `app_label.ModelName`.

    Args:
        model: The model to name.

    Returns:
        The label Django itself uses in system checks and migrations, so a
        refusal message and a `makemigrations` message name the model the same
        way.

    """
    return str(model._meta.label)  # noqa: SLF001 - `_meta` is Django's own public-by-convention API


def _is_aware(instant: datetime) -> bool:
    """Report whether a datetime carries a usable offset.

    The same two-part test `FixedClock.__post_init__` makes, and deliberately the
    same shape: a `tzinfo` that answers `None` to `utcoffset` is as naive as no
    `tzinfo` at all, and only checking `tzinfo is not None` misses it.

    Args:
        instant: The value to check.

    Returns:
        True when the instant can be compared against a stored one without
        guessing an offset.

    """
    return instant.tzinfo is not None and instant.tzinfo.utcoffset(instant) is not None


class AppendOnlyQuerySet(models.QuerySet[_EvidenceModel]):
    """A queryset that offers no way to change or remove a row.

    Five overrides, and each is a path that reaches the table without ever
    constructing an instance -- which is exactly why `AppendOnlyModel.save()`
    cannot see any of them. `update()` and `bulk_update()` issue `UPDATE`;
    `delete()` runs Django's collector rather than the instance's `delete()`;
    `_raw_delete()` is the collector's own statement, reachable directly;
    `bulk_create()` is refused *only* in its conflict-handling forms.

    **`bulk_create` is the subtle one.** The plain call is an insert and stays
    exactly as Django wrote it. `update_conflicts=True` compiles to
    `INSERT ... ON CONFLICT DO UPDATE`, which is an overwrite wearing an insert's
    name, and `ignore_conflicts=True` compiles to `DO NOTHING`, which drops the
    observation instead of recording it -- and `CPM-AD-7` says re-observation is
    never a no-op any more than it is an update. Both are refused; neither can be
    reached without the corresponding keyword, so the permitted path is
    unaffected.

    The async spellings are `sync_to_async` wrappers around these, so `aupdate`,
    `adelete` and `abulk_update` refuse through the same guard rather than
    through a second copy of it that could drift. That is a fact about Django's
    implementation rather than about this class, so
    `tests/unit/django_apps/test_append_only_model.py` calls all three and
    asserts the refusal -- a future native async implementation is then a failing
    test rather than a silently reopened path.

    Every other method is Django's own. Filtering, `values_list`, `create` and
    `acreate` are untouched, because reading evidence and inserting evidence are
    what evidence is for.

    **`raw()` is left in place here and banned by the audit**, and the two are
    not in conflict: Django's `raw()` executes the SQL it is handed, and while it
    is documented for `SELECT` there is nothing in it that refuses an `UPDATE`.
    A runtime refusal would have to parse the SQL, which is the audit's job and
    is done better there;
    `tests/unit/django_apps/test_mutation_path_audit.py` says why it bans the
    form outright rather than trying to tell the two apart.
    """

    @override
    def update(self, **kwargs: Any) -> int:
        """Refuse an `UPDATE` against the whole set.

        Args:
            kwargs: The column assignments Django would have written. Named in
                the message so the refusal says what was being attempted.

        Raises:
            AppendOnlyError: Always. Re-observation inserts a new row carrying
                its own `observed_at`; there is no correct `update()` on
                evidence.

        """
        label = _label(self.model)
        message = (
            f"{label} is append-only, so update({', '.join(sorted(kwargs))}) is refused. "
            f"Observe the fact again and insert a new row with its own observed_at (CPM-AD-2)."
        )
        raise AppendOnlyError(message, model_label=label)

    @override
    def bulk_update(
        self,
        objs: Iterable[_EvidenceModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Refuse a batched `UPDATE`.

        Args:
            objs: The instances Django would have written back.
            fields: The columns it would have written.
            batch_size: How many rows per statement. Unused; the refusal is
                unconditional.

        Raises:
            AppendOnlyError: Always. `bulk_update` is the mutation that most
                looks like a write path a collector may legitimately use, which
                is why it is refused here *and* swept for by
                `EVIDENCE.02-AUDIT-002`.

        """
        label = _label(self.model)
        message = (
            f"{label} is append-only, so bulk_update({', '.join(sorted(fields))}) is refused. "
            f"Insert the re-observed rows with bulk_create instead (CPM-AD-2)."
        )
        raise AppendOnlyError(message, model_label=label)

    @override
    def delete(self) -> tuple[int, dict[str, int]]:
        """Refuse a set-wide `DELETE`.

        Raises:
            AppendOnlyError: Always. Retention is a decision for an
                administrative process against a named window, not something a
                queryset in the product's own source may take.

        """
        label = _label(self.model)
        message = (
            f"{label} is append-only, so delete() on a queryset is refused. "
            f"An observation is removed by a declared retention process, never by product code (CPM-AD-2)."
        )
        raise AppendOnlyError(message, model_label=label)

    @override
    def _raw_delete(self, using: str | None) -> int:
        """Refuse the collector's own `DELETE`.

        `QuerySet.delete()` above is what product code calls; this is what
        Django's deletion collector calls underneath it, and it is reachable
        directly. Overriding only the public spelling would leave the private one
        as a one-underscore bypass -- which is the kind of hole the audit was
        written for, so it is closed here as well.

        Args:
            using: The database alias Django would have deleted from.

        Raises:
            AppendOnlyError: Always.

        """
        label = _label(self.model)
        message = (
            f"{label} is append-only, so _raw_delete() is refused. "
            f"An observation is removed by a declared retention process, never by product code (CPM-AD-2)."
        )
        raise AppendOnlyError(message, model_label=label)

    @override
    def bulk_create(
        self,
        objs: Iterable[_EvidenceModel],
        batch_size: int | None = None,
        # Both keep Django's own name, position and boolean type: a signature
        # that renamed or reordered them would refuse the very calls it is
        # meant to intercept with a TypeError instead of this model's error.
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_EvidenceModel]:
        """Insert rows, refusing the two forms that are not inserts.

        Args:
            objs: The rows to insert.
            batch_size: How many rows per statement, passed through.
            ignore_conflicts: Refused. `INSERT ... ON CONFLICT DO NOTHING`
                silently drops the observation.
            update_conflicts: Refused. `INSERT ... ON CONFLICT DO UPDATE`
                overwrites the earlier observation.
            update_fields: Passed through; meaningful only with
                `update_conflicts`, which is refused.
            unique_fields: Passed through; meaningful only with
                `update_conflicts`, which is refused.

        Returns:
            The inserted rows, from Django's own implementation.

        Raises:
            AppendOnlyError: When either conflict-handling flag is set. The
                message names the flag, because the caller asked for a specific
                behaviour and needs to be told which one is unavailable.

        """
        asked = [
            name
            for name, wanted in (("ignore_conflicts", ignore_conflicts), ("update_conflicts", update_conflicts))
            if wanted
        ]
        if asked:
            label = _label(self.model)
            message = (
                f"{label} is append-only, so bulk_create({'=True, '.join(asked)}=True) is refused. "
                f"Conflict handling turns an insert into an overwrite or into a dropped observation; "
                f"a re-observed fact is inserted as a new row (CPM-AD-2, CPM-AD-7)."
            )
            raise AppendOnlyError(message, model_label=label)
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class AppendOnlyManager(models.Manager[_EvidenceModel]):
    """The default manager for every evidence model.

    It overrides `get_queryset` and nothing else, which is the whole trick:
    Django builds `Manager` from `QuerySet`, so `Model.objects.update(...)` and
    `Model.objects.bulk_update(...)` are thin delegations to the queryset this
    returns and refuse through the overrides above rather than through a second
    set of guards here. `Model.objects.delete()` does not exist at all --
    `QuerySet.delete` is marked `queryset_only`, so it is never copied onto a
    manager -- and raises `AttributeError`.

    `tests/unit/django_apps/test_append_only_model.py` pins both spellings, so a
    future Django that started copying `delete` onto managers is a failing test
    rather than a silent hole.
    """

    #: Declared for the type checker only. Django's `BaseManager.__init__` sets
    #: it and `Manager.get_queryset` reads it; django-stubs does not carry it, and
    #: an annotation is the narrow way to say so without a blanket ignore.
    _hints: dict[str, models.Model]

    @override
    def get_queryset(self) -> AppendOnlyQuerySet[_EvidenceModel]:
        """Return the refusing queryset.

        Returns:
            An `AppendOnlyQuerySet` bound to this manager's model, database alias
            and routing hints. The hints are carried rather than dropped because
            `CPM-AD-16` adds a second database alias for analytics: a queryset
            built without them asks the router a question with less information
            than the manager was given, and the router can then answer with a
            different alias.

        """
        return AppendOnlyQuerySet(self.model, using=self._db, hints=self._hints)


class AppendOnlyModel(models.Model):
    """The abstract base every evidence model inherits.

    See the module docstring for why the guard is "`pk` is set", why
    `observed_at` has no default, and what the three audits close that this class
    cannot.
    """

    #: The instant *this* observation was made, supplied by the writer from an
    #: injected `Clock` (`CPM-AD-26`). No `default` and no `auto_now_add`: both
    #: read the wall clock where the row is written, which
    #: `EVIDENCE.01-AUDIT-002` fails. Non-null, so a row with no instant is a
    #: database error even if it somehow reached an insert path that skipped
    #: `save()`.
    observed_at = models.DateTimeField(_("observed at"))

    objects = AppendOnlyManager()

    class Meta:
        """Abstract, so this declaration creates no table and no migration."""

        abstract = True
        # `_base_manager` is the guard's largest hole if it is left unset. Django
        # builds one itself when no name is given -- a plain `Manager` returning
        # a plain `QuerySet` -- so `Evidence._base_manager.filter(...).update(...)`
        # would compile and run an UPDATE with every refusal above bypassed, and
        # it is exactly what somebody reaches for once `objects.update()` has
        # refused. Naming `objects` here makes the base manager the append-only
        # one. It reaches concrete subclasses that declare a `Meta` of their own
        # -- which is every one of them, because they must declare `app_label`
        # or an application -- through `Options.base_manager`, which walks the
        # MRO for a parent whose base manager is named. Django uses
        # `_base_manager` internally for related-object lookups, and it stays a
        # working queryset for those: only the mutating methods refuse.
        base_manager_name = "objects"

    @override
    def save(
        self,
        *args: Any,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Insert the observation, or refuse if it would change one already written.

        **The rule for both write methods is the same: accept exactly what Django
        accepts, and refuse with this model's own error.** Django 5.2 still takes
        `save()`'s four arguments positionally, under a deprecation, and
        `delete()` takes both of its own positionally; a signature here that
        narrowed either would answer a positional caller with a bare `TypeError`
        naming an argument, which is precisely the unhelpful message the
        `force_update` refusal exists to replace. So `*args` is accepted and
        refused by name.

        Args:
            args: The deprecated positional spelling of the four arguments below.
                Refused rather than mapped: an append-only model has one
                permitted call, `save()`, and a positional caller is asking for
                one of the three that are not.
            force_insert: Passed through to Django unchanged. An insert is
                always permitted.
            force_update: Always refused. It is the one argument whose entire
                purpose is the operation this model forbids.
            using: The database alias, passed through.
            update_fields: Passed through. With no primary key set there is
                nothing to update, so Django's own error covers the misuse.

        Raises:
            AppendOnlyError: When the call is positional, when `force_update` is
                asked for, when the row already exists (`pk` is set), or when
                `observed_at` is absent or naive. Each names the model, and the
                row wherever there is one.

        """
        label = _label(type(self))
        if args:
            message = (
                f"{label} is append-only and takes save()'s arguments by keyword only; "
                f"{len(args)} positional argument(s) were given. The deprecated positional spelling can only "
                f"ask for force_insert, force_update, using or update_fields, and three of those are refused."
            )
            raise AppendOnlyError(message, model_label=label, pk=self.pk)
        if force_update:
            message = (
                f"{label} is append-only, so save(force_update=True) is refused for pk={self.pk!r}. "
                f"Observe the fact again and insert a new row (CPM-AD-2)."
            )
            raise AppendOnlyError(message, model_label=label, pk=self.pk)
        if self.pk is not None:
            message = (
                f"{label} row pk={self.pk!r} is already written and this model is append-only, so save() is "
                f"refused. Re-observation inserts a new row with its own observed_at (CPM-AD-2)."
            )
            raise AppendOnlyError(message, model_label=label, pk=self.pk)
        if self.observed_at is None:
            message = (
                f"{label} was saved with no observed_at. The instant comes from the writer's injected "
                f"Clock (CPM-AD-26); this field has no default, deliberately."
            )
            raise AppendOnlyError(message, model_label=label)
        if not _is_aware(self.observed_at):
            # `FixedClock` refuses a naive instant and `SystemClock` cannot
            # produce one, so a naive `observed_at` means the writer went around
            # the clock -- and the consequence lands far from here: `USE_TZ` is
            # on, so Django warns and stores the value as if it were UTC, and
            # every freshness comparison, observation window and "what did we
            # know at" query is then silently wrong by the writer's offset. This
            # is the one place every evidence write passes through, so it is the
            # one place the check is worth making.
            message = (
                f"{label} was saved with a naive observed_at ({self.observed_at!r}). "
                f"The instant comes from a Clock, which always answers in UTC (CPM-AD-26); a naive value has "
                f"no offset to interpret and would make every freshness comparison wrong rather than failing."
            )
            raise AppendOnlyError(message, model_label=label)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    @override
    def delete(self, using: Any | None = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        """Refuse to remove the observation.

        Args:
            using: The database alias Django would have deleted from.
            keep_parents: Whether Django would have kept parent rows.

        Raises:
            AppendOnlyError: Always. An observation that was made cannot be
                un-made; a retention process removes rows by a declared window,
                and it is not this model's to offer.

        """
        label = _label(type(self))
        message = (
            f"{label} is append-only, so delete() is refused for pk={self.pk!r}. "
            f"An observation is removed by a declared retention process, never by product code (CPM-AD-2)."
        )
        raise AppendOnlyError(message, model_label=label, pk=self.pk)
