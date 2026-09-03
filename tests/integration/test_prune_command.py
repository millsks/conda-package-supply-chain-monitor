"""The pruning admin process, against a real database (FR-44, AD-31, AD-10).

**The property.** One invocation of `prune_expired_state` removes expired session
rows *and* expired mapper epoch records, removes nothing that has not expired,
removes nothing whose expiry is unknown, removes no epoch row for a token the
Bearer path would still accept, and reports the count of each kind on the event
stream. A second invocation removes nothing and reports zero for both.
`--dry-run` answers the same question and deletes nothing.

**Why it is worth asserting, and what it prevents.** Two tables here grow one row
per credential and nothing in the component removes a dead row. AD-31 makes the
remover a declared *admin* process rather than a background task because Celery
exists in only two of the six combinations -- so in the other four a beat entry
would prune nothing at all, and those four are exactly the deployments whose
`django_session` nobody is watching. A pruner is therefore load-bearing, and a
pruner that is subtly wrong is worse than none: too broad and it deletes the
sessions of signed-in users or re-syncs live credentials; too narrow and the
table it was scheduled for keeps growing while the job reports success.

Three of the cases below are about that boundary specifically. `expires_at__lt`
excludes NULL in SQL, and `config.authorization.mapper._expires_at` writes `None`
for a token with no readable `exp` -- so a null-expiry epoch row is *not prunable
by expiry* and must survive. That is a property of SQL's three-valued logic
rather than of any code in this repository, which is precisely why it is asserted
against a real database instead of reasoned about.

A fourth case is about the *other* edge of that boundary, which is time rather
than SQL. `settings.OIDC_LEEWAY_SECONDS` is what
`config.authorization.authentication._leeway` hands to `jwt.decode`, so under a
non-zero leeway a token is still accepted for that many seconds past its own
`exp` -- and the epoch cutoff is `now - leeway` for that reason. The shipped
default is zero, so the subtraction is invisible to every other case in this
module and could be deleted with all of them green; the leeway case is the only
thing holding it.

And a fifth is about the state a scheduled job spends its life in rather than the
state it is written against: nothing left to prune. `QuerySet.delete()` returns an
*empty* per-model mapping when it matched nothing, so the steady state runs a
branch of `_prune` no seeded case reaches.

Disposition `core`. `src/django_service/` is `core` in its entirety (AD-29), so
this command and these assertions travel into all six combinations -- which is
the same reason the command may not depend on Celery.

**Deliberately not asserted here.**

* That the `prune` task exists in `pixi.toml`, that `component.toml` declares the
  admin process, and that neither declares a schedule --
  `tests/unit/test_process_model.py` and `tests/unit/test_component_declaration.py`
  own the declaration side.
* That the task declares no `COMPONENT_PROCESS` --
  `tests/unit/test_process_model.py::test_no_administrative_process_runs_a_task_that_declares_a_process_type`
  and `tests/unit/test_locality_declaration.py` own AD-13's task-`env` contract.
* That `SESSION_ENGINE` is set explicitly, which is what makes scanning
  `django_session` coherent at all -- `tests/unit/test_session_settings.py`.
* What writes the epoch rows in the first place. `sync_once_per_epoch` and the
  `exp` claim are Epic 2's, exercised by
  `tests/integration/authorization/test_mapper_sync.py`; rows are created inline
  here so that a defect in this pruner cannot be masked by a defect in that
  writer, and so that the null-expiry row can be constructed directly.

`@pytest.mark.django_db` without `transaction=True`: each case runs inside a
transaction that rolls back, which is what leaves the database as found.
`transaction=True` would truncate the tables the group-provisioning migration
seeds, for the reason `tests/integration/authorization/test_mapper_sync.py`
records. The directory's `conftest.py` adds `pytest.mark.integration` to
everything collected under it, so no explicit marker is needed.

These use the real database through Django's ORM and a real `call_command`
dispatch: this is an integration module -- database I/O, no network, no
subprocess.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import pytest
import structlog
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from django_service.users.models import CredentialEpoch

if TYPE_CHECKING:
    from django_service.users.models import User

#: The command's own name, as `manage.py` dispatches it and as the `prune` pixi
#: task spells it. Driven through `call_command` rather than by importing
#: `Command().handle()` directly, so that the argument parsing `--dry-run` goes
#: through is the parsing an operator's invocation goes through.
COMMAND: Final[str] = "prune_expired_state"

#: The four event names the command emits, one pair per pruned kind. Spelled here
#: rather than imported so that a rename of the constant in the command module is
#: still a rename of the *event*, which is the thing an operator's alerting is
#: keyed on and the thing this module exists to pin.
SESSIONS_PRUNED_EVENT: Final[str] = "prune.sessions_pruned"
SESSIONS_PRUNABLE_EVENT: Final[str] = "prune.sessions_prunable"
EPOCHS_PRUNED_EVENT: Final[str] = "prune.epochs_pruned"
EPOCHS_PRUNABLE_EVENT: Final[str] = "prune.epochs_prunable"

#: How far either side of *now* the fixtures are placed. Generous rather than
#: tight: a margin of seconds would make the suite depend on how long the
#: transaction takes, and `expire_date__lt=timezone.now()` is evaluated inside
#: the command rather than at row creation.
MARGIN: Final[timedelta] = timedelta(hours=1)

#: **Two** expired sessions against **one** expired epoch, and the asymmetry is
#: the whole point of the number. With one of each, every count assertion below
#: reads `1 == 1`, so a command that reported the session count under the epoch
#: key -- or the same variable twice, which is what a copy-paste of the second
#: `logger.info` call produces -- passed every one of them. The two counts have to
#: be able to disagree before asserting they are right means anything.
#:
#: Every key here and below is kept under 40 characters, which is the width of
#: `django_session.session_key`. A longer one is not a readability problem -- it
#: is a `DataError` at row creation, in a case whose subject is what survives a
#: delete.
EXPIRED_SESSION_KEYS: Final[tuple[str, ...]] = (
    "expired-session-key-for-the-pruner",
    "second-expired-session-key-for-pruner",
)
LIVE_SESSION_KEY: Final[str] = "live-session-key-for-the-pruner"

EXPIRED_JTI: Final[str] = "urn:example:jti:expired"
LIVE_JTI: Final[str] = "urn:example:jti:live"
UNDATED_JTI: Final[str] = "urn:example:jti:no-readable-exp"

#: What a run over the seeded rows must report, spelled as the seed's own shape
#: rather than as two literals: a third expired session added to the tuple above
#: has to move this number with it, and deriving it is what makes that automatic.
EXPECTED_EXPIRED_SESSIONS: Final[int] = len(EXPIRED_SESSION_KEYS)
EXPECTED_EXPIRED_EPOCHS: Final[int] = 1

#: What the epoch table holds once a run has finished, whichever run it was. Named
#: as the whole surviving set rather than counted, so the steady-state case can
#: compare the table's contents instead of its size -- a count is satisfied by a
#: pruner that deleted the live row and left the null-expiry one twice over.
SURVIVING_JTIS: Final[tuple[str, ...]] = (LIVE_JTI, UNDATED_JTI)

#: The leeway case's own rows and the tolerance it runs under. Minutes rather than
#: the seconds `docs` tells an operator to keep the setting in, because the case
#: has to place a row *inside* the window and a window of seconds would make that
#: placement a race against how long the transaction takes.
LEEWAY: Final[timedelta] = timedelta(minutes=5)
INSIDE_LEEWAY: Final[timedelta] = timedelta(minutes=1)
INSIDE_WINDOW_JTI: Final[str] = "urn:example:jti:expired-but-still-accepted"
INSIDE_WINDOW_SESSION_KEY: Final[str] = "just-expired-session-key-for-the-pruner"


def _events(captured: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """Select one event by name from a `capture_logs` recording.

    Args:
        captured: Everything `structlog.testing.capture_logs()` recorded.
        name: The event name to select.

    Returns:
        The matching events, in the order they were emitted.
    """
    return [event for event in captured if event["event"] == name]


def _seed(user: User) -> None:
    """Create the six rows every case below is written against.

    Three sessions, **two** expired and one live; three epoch records, **one**
    expired, one live and one with a null `expires_at`. Created together in every
    case rather than per-case, because the assertions that matter are about what
    survives beside what is deleted -- a case that seeded only what it expected to
    be removed would pass against a pruner that emptied both tables.

    Two expired sessions against one expired epoch is deliberate and is the
    reason the numbers are not equal. `EXPIRED_SESSION_KEYS` records why: equal
    counts make every count assertion in this module symmetric, and a symmetric
    assertion cannot tell the session number from the epoch number.

    Args:
        user: The owner every epoch record is attached to; `user` is a required
            foreign key on `CredentialEpoch`.
    """
    now = timezone.now()
    for key in EXPIRED_SESSION_KEYS:
        Session.objects.create(session_key=key, session_data="", expire_date=now - MARGIN)
    Session.objects.create(session_key=LIVE_SESSION_KEY, session_data="", expire_date=now + MARGIN)
    CredentialEpoch.objects.create(jti=EXPIRED_JTI, user=user, expires_at=now - MARGIN)
    CredentialEpoch.objects.create(jti=LIVE_JTI, user=user, expires_at=now + MARGIN)
    CredentialEpoch.objects.create(jti=UNDATED_JTI, user=user, expires_at=None)


def _run(*arguments: str) -> str:
    """Invoke the command and return what it wrote to its own stdout.

    `stdout` is captured rather than left to the terminal so the suite's output
    stays readable, and returned rather than discarded because the human-facing
    line is a second output channel the command is required to have -- structlog
    is the machine one.

    Args:
        *arguments: Command-line arguments, `--dry-run` being the only one.

    Returns:
        Everything the command wrote to stdout.
    """
    output = StringIO()
    call_command(COMMAND, *arguments, stdout=output)
    return output.getvalue()


@pytest.mark.django_db
def test_one_invocation_prunes_both_expired_sessions_and_expired_epochs(user: User) -> None:
    """AC #3: both kinds are pruned by one declared admin process, not two.

    The whole of AC #3's first clause is that a deployment repository schedules
    *one* job. Two jobs is a configuration in which one of them eventually is not
    scheduled, and a table nobody is watching is the failure this exists to
    prevent -- so the assertion is written over a single `call_command`
    invocation rather than over two, and both tables are checked after it.
    """
    _seed(user)

    _run()

    survivors = sorted(
        Session.objects.filter(session_key__in=EXPIRED_SESSION_KEYS).values_list("session_key", flat=True)
    )
    assert not survivors, (
        f"these expired session rows survived the prune: {survivors}. django_session grows without bound in "
        f"all six combinations if they are not removed here (AD-31)."
    )
    assert not CredentialEpoch.objects.filter(jti=EXPIRED_JTI).exists(), (
        "the expired epoch record survived the prune; AD-10's table is pruned alongside sessions by this "
        "same process, and by nothing else"
    )


@pytest.mark.django_db
def test_live_sessions_and_live_epochs_are_left_alone(user: User) -> None:
    """The other side of AC #3: the predicate is expiry, and only expiry.

    A pruner that deleted a live session signs out every user it reaches, and one
    that deleted a live epoch record makes the mapper re-sync a credential it was
    told once it need not. Both are worse than the unbounded growth the process
    exists to stop, which is why the survival of the live rows is asserted in its
    own case rather than as a trailing line of the one above.

    `first_seen_at` is never the column scanned, and this is where that shows:
    all five rows are created within the same transaction, so an age-based prune
    would take the live rows with the expired ones and pass every assertion in
    the previous case.
    """
    _seed(user)

    _run()

    assert Session.objects.filter(session_key=LIVE_SESSION_KEY).exists(), (
        "a session that has not expired was deleted; the predicate is expire_date < now and nothing else"
    )
    assert CredentialEpoch.objects.filter(jti=LIVE_JTI).exists(), (
        "an epoch record whose token has not expired was deleted; pruning it re-syncs a live credential"
    )


@pytest.mark.django_db
def test_an_epoch_with_no_recorded_expiry_survives(user: User) -> None:
    """AD-10: a null `expires_at` means *not prunable by expiry*, and SQL is what enforces it.

    `config.authorization.mapper._expires_at` writes `None` whenever a token
    carries no readable `exp` -- a missing claim, a string, a boolean, a value
    the platform cannot represent -- and that row records a first sighting whose
    end nobody knows. Deleting it would re-sync a credential that may still be
    live.

    Asserted against a real database rather than reasoned about, because what
    makes it true is SQL's three-valued logic: `expires_at < now` is *unknown*
    for NULL, and a `WHERE` clause keeps only rows for which it is true. A
    reimplementation in Python with `or` short-circuiting, or a switch to
    `exclude(expires_at__gte=...)`, would both delete this row and would both
    look correct in review.
    """
    _seed(user)

    _run()

    assert CredentialEpoch.objects.filter(jti=UNDATED_JTI).exists(), (
        "an epoch record with a null expires_at was pruned. `__lt` excludes NULL in SQL, which is the "
        "required behaviour and not an accident: a null expiry means the token's end is unknown (AD-10)."
    )


@pytest.mark.django_db
def test_dry_run_reports_the_same_counts_and_deletes_nothing(user: User) -> None:
    """`--dry-run` is a rehearsal, and its numbers have to be the real ones.

    A dry run that reported a different count from the run it rehearses is worse
    than no dry run: an operator sizing a first prune against a production table
    would act on a number the real invocation does not produce. So the assertion
    is not merely that nothing was deleted -- it is that the counts reported here
    are the counts the real invocation goes on to report, checked by running both
    in that order against the same seeded rows.

    The events are named differently by design. A rehearsal that emitted
    `prune.sessions_pruned` would be counted by an operator's dashboard as a
    prune that happened, so the name carries the mode and the payload carries the
    count.
    """
    _seed(user)

    with structlog.testing.capture_logs() as rehearsed:
        _run("--dry-run")

    assert Session.objects.filter(session_key__in=EXPIRED_SESSION_KEYS).count() == EXPECTED_EXPIRED_SESSIONS, (
        "--dry-run deleted a session row"
    )
    assert CredentialEpoch.objects.filter(jti=EXPIRED_JTI).exists(), "--dry-run deleted an epoch record"
    assert _events(rehearsed, SESSIONS_PRUNED_EVENT) == [], "--dry-run emitted the event a real prune emits"
    assert _events(rehearsed, EPOCHS_PRUNED_EVENT) == [], "--dry-run emitted the event a real prune emits"

    with structlog.testing.capture_logs() as performed:
        _run()

    assert (
        _events(rehearsed, SESSIONS_PRUNABLE_EVENT)[0]["sessions"]
        == _events(performed, SESSIONS_PRUNED_EVENT)[0]["sessions"]
    ), "the rehearsal's session count is not the count the real prune reported"
    assert (
        _events(rehearsed, EPOCHS_PRUNABLE_EVENT)[0]["epochs"] == _events(performed, EPOCHS_PRUNED_EVENT)[0]["epochs"]
    ), "the rehearsal's epoch count is not the count the real prune reported"


@pytest.mark.django_db
def test_the_event_stream_carries_one_count_per_pruned_kind(user: User) -> None:
    """AD-31's declaration is only useful if the run says what it did.

    An admin process scheduled by a deployment repository has no operator
    watching it. The only thing that reaches anybody afterwards is the event
    stream, so the counts are on it -- structured, one event per kind, rather
    than only on the command's stdout, which the platform is under no obligation
    to keep.

    Both counts are asserted as the exact numbers seeded, not merely as
    non-zero: a command that reported `delete()`'s *total* rather than the
    per-model count would be right here today and would start over-reporting the
    moment either model gained a cascading dependent. And the two numbers are
    seeded **different** -- two sessions, one epoch -- so that neither can stand
    in for the other: with one of each, a second `logger.info` call passing
    `epochs=sessions` reported the wrong variable and satisfied both assertions.

    Never a `jti`, never a session key and never a user identifier in any of it.
    The house rule is `config.authorization.mapper`'s -- it logs `jti_length`
    rather than the value, because a `jti` in the log is a token identifier that
    has left the token -- and a session key is the same kind of thing wearing a
    different name: it is the bearer credential in the session cookie, so a log
    line carrying one is a log line an operator with read access could sign in
    with. Both are asserted rather than assumed, since a count is a very easy
    thing to "improve" by naming what was removed.

    Both output channels are scanned, not only the structured one.
    `docs/deployment.md` promises the operator that nothing in what a run writes
    is a session key or a token identifier, and the module's own claim is that
    stdout is a *second* channel -- so a "which rows?" line added to stdout for a
    human to read would honour the event-stream assertion exactly while putting
    the credentials in whatever the platform does with a job's output.
    """
    _seed(user)

    with structlog.testing.capture_logs() as captured:
        stdout = _run()

    sessions = _events(captured, SESSIONS_PRUNED_EVENT)
    epochs = _events(captured, EPOCHS_PRUNED_EVENT)

    assert len(sessions) == 1, f"expected exactly one {SESSIONS_PRUNED_EVENT}, got {sessions}"
    assert len(epochs) == 1, f"expected exactly one {EPOCHS_PRUNED_EVENT}, got {epochs}"
    assert sessions[0]["sessions"] == EXPECTED_EXPIRED_SESSIONS, (
        f"{EXPECTED_EXPIRED_SESSIONS} session rows were expired; the run reported {sessions[0]['sessions']}"
    )
    assert epochs[0]["epochs"] == EXPECTED_EXPIRED_EPOCHS, (
        f"{EXPECTED_EXPIRED_EPOCHS} epoch record was expired; the run reported {epochs[0]['epochs']}"
    )

    secrets = (EXPIRED_JTI, LIVE_JTI, UNDATED_JTI, *EXPIRED_SESSION_KEYS, LIVE_SESSION_KEY)
    for channel, rendered in (("event stream", repr(captured)), ("stdout", stdout)):
        for secret in secrets:
            assert secret not in rendered, (
                f"the {channel} carries {secret!r}. A jti is a token identifier that has left the token and a "
                f"session key is the credential in the session cookie; the counts are the whole of what an "
                f"operator needs, and docs/deployment.md promises neither appears."
            )

    assert stdout.strip(), "the command wrote nothing to stdout; the human-facing channel is the second one"


@pytest.mark.django_db
def test_a_second_run_removes_nothing_and_reports_zero(user: User) -> None:
    """The steady state, which is the state a scheduled prune spends its life in.

    Every other case in this module seeds rows and then prunes them, so every one
    of them exercises the path where `QuerySet.delete()` came back with something
    in its per-model mapping. The path a daily job actually takes on all but its
    first run is the other one: nothing matches, and Django returns `(0, {})` --
    an *empty* mapping, not a mapping with a zero in it. `_prune`'s
    `per_label.get(label, 0)` is what turns that into the reported count, and
    without this case that fallback was never executed. Simplifying it to
    `per_label[label]`, which reads as the obvious tidy-up, would raise `KeyError`
    on every steady-state run in production with the whole suite green.

    The claim is also the one `docs/deployment.md` and the command's own docstring
    make to an operator in as many words -- "a second run a second later removes
    nothing and says so" -- so both halves are asserted: nothing further is
    deleted, *and* both events are still emitted carrying zero. An event suppressed
    when there was nothing to do is a job whose successful runs are invisible to
    the alerting built on it, which is indistinguishable from a job that stopped
    being scheduled.
    """
    _seed(user)
    _run()

    with structlog.testing.capture_logs() as captured:
        _run()

    assert [event["sessions"] for event in _events(captured, SESSIONS_PRUNED_EVENT)] == [0], (
        f"the second run did not report exactly one {SESSIONS_PRUNED_EVENT} carrying zero: {captured}. "
        f"There was nothing left to prune, and a run that says so is what an operator's alerting reads."
    )
    assert [event["epochs"] for event in _events(captured, EPOCHS_PRUNED_EVENT)] == [0], (
        f"the second run did not report exactly one {EPOCHS_PRUNED_EVENT} carrying zero: {captured}. "
        f"`delete()` returns an empty per-model mapping when it matched nothing, and reporting zero from it "
        f"is `_prune`'s `per_label.get(label, 0)` fallback doing its only job."
    )
    assert Session.objects.filter(session_key=LIVE_SESSION_KEY).exists(), (
        "the second run deleted the live session; running the job twice must be the same as running it once"
    )
    remaining = sorted(CredentialEpoch.objects.values_list("jti", flat=True))
    assert remaining == sorted(SURVIVING_JTIS), (
        f"after two runs the epoch table holds {remaining}, not {sorted(SURVIVING_JTIS)}. Idempotence means "
        f"the rows the first run correctly left alone survive every subsequent run too, not only the first."
    )


@pytest.mark.django_db
@override_settings(OIDC_LEEWAY_SECONDS=LEEWAY.total_seconds())
def test_an_epoch_expiring_inside_the_leeway_window_survives(user: User) -> None:
    """AD-10: the epoch row outlives the token by exactly the leeway, and the session does not.

    `settings.OIDC_LEEWAY_SECONDS` is handed to `jwt.decode` by
    `config.authorization.authentication._leeway`, so a token whose `exp` passed
    less than that many seconds ago is still **accepted** on the Bearer path. Its
    epoch row is AD-10's record of the first sighting of that credential and the
    holder of the jti-held-by-another-identity guard, so deleting it at `now`
    deletes it while the component is still honouring the token -- the next
    request re-syncs a credential the component was told once it need not, which
    is the outcome the whole `expires_at__lt` paragraph in the command's docstring
    argues against, arriving through the clock rather than through the predicate.

    Both sides are asserted, because the subtraction is only correct if it is
    bounded: an epoch inside the window survives, and one an hour past its `exp`
    -- outside any single-digit-second leeway an operator would set -- is still
    pruned. A cutoff that simply stopped deleting would satisfy the first
    assertion alone.

    The session leg is asserted **unchanged** in the same case, because that is
    the scope of the fix rather than a separate property: a session's lifetime is
    its own `expire_date`, written by Django and derived from no token claim, so
    there is no verification window to widen and a leeway applied there would only
    leave dead session rows behind. A run under a five-minute leeway must still
    remove a session that expired a minute ago.

    The leeway is set to minutes rather than the single-digit seconds
    `docs/deployment.md` tells an operator to keep it in, because the row has to
    be placed *inside* the window and a window of seconds would make that
    placement a race against how long the transaction takes.
    """
    _seed(user)
    now = timezone.now()
    CredentialEpoch.objects.create(jti=INSIDE_WINDOW_JTI, user=user, expires_at=now - INSIDE_LEEWAY)
    Session.objects.create(session_key=INSIDE_WINDOW_SESSION_KEY, session_data="", expire_date=now - INSIDE_LEEWAY)

    _run()

    assert CredentialEpoch.objects.filter(jti=INSIDE_WINDOW_JTI).exists(), (
        f"an epoch record whose token expired {INSIDE_LEEWAY} ago was pruned under a "
        f"{LEEWAY} leeway. OIDC_LEEWAY_SECONDS makes that token still acceptable, so its epoch row is the "
        f"record of a live credential; removing it re-syncs on the next request and drops the "
        f"jti-held-by-another-identity guard for the width of the window (AD-10)."
    )
    assert not CredentialEpoch.objects.filter(jti=EXPIRED_JTI).exists(), (
        f"an epoch record {MARGIN} past its expiry survived a run under a {LEEWAY} leeway. The cutoff is "
        f"`now - leeway`, not `never`: a pruner that stops deleting is the unbounded growth AD-31 exists to "
        f"stop, wearing the leeway as an excuse."
    )
    assert not Session.objects.filter(session_key=INSIDE_WINDOW_SESSION_KEY).exists(), (
        f"a session that expired {INSIDE_LEEWAY} ago survived a run under a {LEEWAY} leeway. The leeway is the "
        f"Bearer path's tolerance for a token's `exp`; `expire_date` is Django's own and derived from no claim, "
        f"so applying the leeway to the session leg only leaves dead rows in django_session."
    )
