"""The one declared admin process that prunes expired state (FR-44, AD-31, AD-10).

Two tables accumulate rows that stop mattering at a moment written into the row
itself. `django_session` holds one row per session and `expire_date` says when it
died; `users_credentialepoch` holds AD-10's record of the first sighting of a
credential and `expires_at` says when the token behind it did. Neither table has
anything that removes a dead row, so both grow without bound until something
does.

**One process, not two, and not a background task.** AD-31 makes this a declared
*admin* process because background task processing exists in only two of the six
combinations. A Celery beat entry would prune nothing at all in the other four --
and those four are precisely the deployments whose session table nobody is
watching. The component therefore declares a process the deployment repository
can schedule (`component.toml`'s `[[admin_processes]]`, invoked as `pixi run
prune`) and declares no schedule for it: the cadence is the deployment
repository's, which is the half of FR-44 marked *Next*.

**Why the two kinds are pruned by one invocation.** They expire for the same
reason -- a credential's lifetime ran out -- and a deployment repository that has
to schedule two jobs will eventually be running only one of them.

The two legs are independent statements and nothing wraps them in a transaction:
a management command runs in autocommit, and none is added here. So the failure
mode is worth stating exactly rather than as "no silent half-prune". If the epoch
leg raises after the session leg has committed, the run *fails* -- non-zero exit,
with the traceback -- and the session deletion that already happened stands and
has already been reported on the event stream as `prune.sessions_pruned` with its
count. Nothing has to be reconciled: the command is idempotent, so the re-run
after the fix takes the sessions that expired in the meantime, finds the epoch
rows still there, and removes them. A transaction spanning both legs would buy
nothing for that and would hold the session table's row locks across the epoch
delete as well as its own.

**Why the session model is imported rather than `clearsessions` called.**
`SessionStore.clear_expired()` returns nothing, and `--dry-run` needs a count, so
this scans the model directly on the same predicate Django's own command uses
(`expire_date__lt=now`). That import is only coherent because
`config.settings.base` sets `SESSION_ENGINE` to the database backend explicitly:
under a cache or cookie engine there is no table to scan and this command would
be quietly pruning a store nothing writes to.

**Why `expires_at__lt` and never `first_seen_at`.** `__lt` excludes NULL in SQL,
and that exclusion is the required behaviour rather than an accident of the
operator. `config.authorization.mapper._expires_at` writes `None` whenever a
token carries no readable `exp`, and a null expiry means *not prunable by
expiry* -- an epoch row removed early re-syncs a credential that is still live,
which is work the component was told once it did not need to do again. Pruning on
age instead would delete rows for credentials that have not expired at all.

**Why the epoch cutoff is not simply *now*.** `config.settings.base` declares
`OIDC_LEEWAY_SECONDS`, and `config.authorization.authentication._leeway` hands it
to `jwt.decode`, so under a non-zero leeway a Bearer token is still *accepted* for
that many seconds past its own `exp`. An epoch row deleted at `expires_at < now`
is therefore deleted inside the window where the credential behind it is still
live -- which is the same "removed early re-syncs a credential that is still live"
outcome the paragraph above argues against, arriving through the clock instead of
through the predicate, and it drops AD-10's jti-held-by-another-identity guard for
that window at the same time. The epoch cutoff is `now - leeway` for that reason.

The leeway applies to the *epoch* leg and to nothing else. A session's lifetime is
its own `expire_date`, written by Django when the session was saved and derived
from no token claim, so there is no verification window to widen there and
subtracting the leeway from the session cutoff would only leave dead rows behind.

The value is read off `django.conf.settings` rather than by importing
`config.authorization.authentication._leeway`: AD-4 permits `config` to import
`django_service` and forbids the reverse, so this module cannot reach for that
accessor. It is read the same defensive way that accessor reads it -- `getattr`
with a zero default -- so a settings module that never declared the name is a zero
leeway rather than an `AttributeError` in a job nobody is watching.

`tests/integration/test_prune_command.py` exercises both legs, both modes, the
null-expiry row, the leeway window and the steady state against a real database.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import structlog
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db.models import Model
from django.utils import timezone

from django_service.users.models import CredentialEpoch

if TYPE_CHECKING:
    from argparse import ArgumentParser
    from datetime import datetime

    from django.db.models import QuerySet

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The event names, one pair per pruned kind. Two names rather than one plus a
#: `dry_run` field, because the name is what an operator alerts and reports on: a
#: rehearsal that emitted `...pruned` would be counted as a prune that happened,
#: and a table left growing would look like a table being kept.
SESSIONS_PRUNED_EVENT: Final[str] = "prune.sessions_pruned"
SESSIONS_PRUNABLE_EVENT: Final[str] = "prune.sessions_prunable"
EPOCHS_PRUNED_EVENT: Final[str] = "prune.epochs_pruned"
EPOCHS_PRUNABLE_EVENT: Final[str] = "prune.epochs_prunable"


def _prune[ModelT: Model](queryset: QuerySet[ModelT], *, label: str, dry_run: bool) -> int:
    """Delete everything the queryset selects, or count it, and report how many.

    The count comes back from `QuerySet.delete()`'s per-label mapping rather than
    from its total. The total includes anything the delete cascaded into, so a
    model that later became the parent of a related row would make this
    over-report the kind it claims to be counting -- and the number is the one
    thing this command exists to tell an operator.

    Args:
        queryset: The rows to remove, already narrowed to the expiry predicate.
        label: The model's `app_label.ModelName`, the key `delete()` reports under.
        dry_run: When true, nothing is deleted and the count is what a real run
            would have removed.

    Returns:
        The number of rows of this kind removed, or that would have been.
    """
    if dry_run:
        return queryset.count()
    _total, per_label = queryset.delete()
    return int(per_label.get(label, 0))


def _epoch_cutoff(now: datetime) -> datetime:
    """Return the instant before which an epoch row is safe to delete.

    `now` minus the clock-skew tolerance the Bearer path verifies under, and never
    `now` itself. `settings.OIDC_LEEWAY_SECONDS` is handed to `jwt.decode` by
    `config.authorization.authentication._leeway`, so a token whose `exp` has just
    passed is still **accepted** for that many seconds; the epoch row is the
    record of that credential's first sighting and the holder of AD-10's
    jti-held-by-another-identity guard, so deleting it at `now` deletes it while
    the credential is live and re-syncs on the next request that presents it.

    Clamped at zero rather than passed through, and the clamp is not decoration: a
    negative value would make this cutoff *later* than `now` and start deleting
    rows for tokens still inside their own `exp` -- the widening this function
    exists to prevent, inverted. `base.py` already clamps at declaration; a
    settings module composing the value some other way is what this catches.

    `getattr` rather than an attribute access, matching how
    `authentication._leeway` reads the same setting, so a settings module that
    never declared the name means zero leeway rather than an `AttributeError`
    raised inside a scheduled job with nobody watching.

    `tests/integration/test_prune_command.py::test_an_epoch_expiring_inside_the_leeway_window_survives`
    is what holds this: it is the only case in which the cutoff and `now` differ,
    and without it the subtraction could be deleted and every other case stay
    green, because the shipped default leeway is zero.

    Args:
        now: The instant the run is reckoned from.

    Returns:
        `now` less the configured leeway, in seconds.
    """
    leeway = max(0.0, float(getattr(settings, "OIDC_LEEWAY_SECONDS", 0.0)))
    return now - timedelta(seconds=leeway)


def _label(model: type[Model]) -> str:
    """Return one model's `app_label.ModelName`.

    Args:
        model: The model class.

    Returns:
        The label `QuerySet.delete()` keys its per-model counts by.
    """
    return str(model._meta.label)  # noqa: SLF001 - `Model._meta` is Django's documented model API


class Command(BaseCommand):
    """Prune expired session rows and expired mapper epoch records."""

    help = "Admin process: prune expired sessions and expired mapper epoch records (AD-31)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Declare the one option this process takes.

        Args:
            parser: The parser Django hands every management command.
        """
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be pruned and delete nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Prune both kinds of expired state in one pass.

        Idempotent, and safe to run beside serving traffic with one qualification
        that is worth stating precisely rather than as "nothing is locked".

        Each leg issues one unbounded `DELETE ... WHERE <expiry> < cutoff` -- no
        `LIMIT`, no chunking -- so PostgreSQL takes a row lock on every row that
        statement removes and holds it until the statement ends. What it does not
        take is a **table** lock, and nothing here truncates; and no row a live
        request is using is locked, because the predicate is expiry and a live
        session's `expire_date` cannot satisfy it. Serving traffic is therefore
        untouched by the locks, but the statement is still one statement: a
        **first** run against a table nobody has pruned in months is a single
        large `DELETE`, and it can exceed `statement_timeout` and roll back having
        made no progress at all. `--dry-run` reports the row count first, which is
        how an operator finds that out before the timeout does.

        A second invocation a second later removes nothing and says so -- both
        `prune.sessions_pruned` and `prune.epochs_pruned` carry zero, which
        `tests/integration/test_prune_command.py::test_a_second_run_removes_nothing_and_reports_zero`
        is what pins.

        Args:
            *args: Unused; Django's management interface passes none.
            **options: The parsed options. `dry_run` is the only one read here.
        """
        dry_run = bool(options.get("dry_run"))
        now = timezone.now()

        sessions = _prune(
            Session.objects.filter(expire_date__lt=now),
            label=_label(Session),
            dry_run=dry_run,
        )
        logger.info(
            SESSIONS_PRUNABLE_EVENT if dry_run else SESSIONS_PRUNED_EVENT,
            sessions=sessions,
            dry_run=dry_run,
        )

        # `_epoch_cutoff(now)` rather than `now`, and the difference is
        # `settings.OIDC_LEEWAY_SECONDS`: a token is accepted for that many
        # seconds past its own `exp`, so a row deleted at `now` is deleted while
        # the credential it records is still being honoured -- an early prune
        # that re-syncs a live credential and drops AD-10's
        # jti-held-by-another-identity guard for the width of the window.
        #
        # Never a `jti` and never a user identifier: the count is the whole of
        # what an operator needs, and a `jti` in the log is a token identifier
        # leaking out of the token -- the rule `config.authorization.mapper`
        # keeps by logging `jti_length` instead of the value.
        epochs = _prune(
            CredentialEpoch.objects.filter(expires_at__lt=_epoch_cutoff(now)),
            label=_label(CredentialEpoch),
            dry_run=dry_run,
        )
        logger.info(
            EPOCHS_PRUNABLE_EVENT if dry_run else EPOCHS_PRUNED_EVENT,
            epochs=epochs,
            dry_run=dry_run,
        )

        verb = "would prune" if dry_run else "pruned"
        self.stdout.write(f"{verb} {sessions} expired session(s) and {epochs} expired epoch record(s)")
