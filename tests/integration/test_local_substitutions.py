"""FR-18's substitutions exercised, rather than read back off the settings.

`tests/unit/test_settings.py` and `tests/unit/test_database_selection.py` assert
what the settings modules *declare*. That is not the same claim: a component can
declare `LocMemCache` and still fail to cache, or declare eager execution and
still hand the caller a result the task never produced. This file makes the
round trips -- a row written and read back, a value cached and retrieved, a task
body that runs and one that raises -- so the story's "it runs with nothing
running alongside it" is demonstrated rather than asserted about a dict.

Nothing here is engine-aware or backend-aware. In the gate `DATABASE_URL` names
PostgreSQL and these tests run against it unchanged; locally they run against
the sqlite substitution. That is the point: the substitutions preserve the API,
so a test that branched on which one is active would be evidence against the
claim it was written to support.

State is left as found. Every database test takes pytest-django's `db` fixture
(via `user`), which wraps the test in a transaction and rolls it back, and the
cache key is deleted on both sides of the test that uses it -- `LocMemCache` is
process-global and outlives the test that wrote to it. The one thing that does
persist is `fail_deliberately`'s registration in the Celery task registry, which
is unavoidable: a task has to be registered to be called. It is registered here
rather than in `src/` precisely so that production code does not grow a failure
fixture, and its name is specific enough not to collide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from celery import shared_task
from celery.result import EagerResult
from django.core.cache import cache

from django_service.users.models import User
from django_service.users.tasks import get_users_count

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

# Namespaced by the module that owns it, so a leaked key is traceable to here.
CACHE_KEY = "tests.integration.test_local_substitutions.round-trip"
CACHED_VALUE = {"substitution": "locmem", "nested": [1, 2, 3]}

# Returned by `cache.get` when the key is absent, and distinguishable from a
# cached `None` -- which is a value the cache API is required to round-trip too.
_ABSENT = object()


class LocalSubstitutionTaskError(RuntimeError):
    """The failure `fail_deliberately` raises, and nothing else raises.

    A dedicated type rather than a bare `RuntimeError`: `pytest.raises` on a
    common exception class would also be satisfied by the task machinery failing
    for some unrelated reason, which is the opposite of what that test claims.
    """


@shared_task()
def fail_deliberately() -> None:
    """Raise, so that eager propagation has something to propagate.

    Registered in the test suite rather than in `src/django_service/users/tasks.py`:
    the only task the application ships, `get_users_count`, has no exception
    path, and giving production code one purely so a test can catch it would put
    a failure fixture in every generated component.

    Raises:
        LocalSubstitutionTaskError: Always.

    """
    msg = "raised inside the task body; eager propagation must carry this to the caller"
    raise LocalSubstitutionTaskError(msg)


@pytest.fixture
def cache_key() -> Iterator[str]:
    """Yield a cache key that is absent before the test and deleted after it.

    Deleted on both sides rather than just afterwards: `LocMemCache` is a
    process-global dict, so a previous run of this test in the same process --
    or a `-p no:randomly` reordering -- could otherwise leave the key populated
    and turn the "starts absent" assertion into a false pass.

    Yields:
        The cache key to write under.

    """
    cache.delete(CACHE_KEY)
    yield CACHE_KEY
    cache.delete(CACHE_KEY)


# ---------------------------------------------------------------------------
# AC #1 -- the ORM works against the substituted database.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_orm_round_trips_against_the_substituted_database(user: User) -> None:
    """A row written through the ORM is readable through it, with no server running.

    The substitution is only worth having if the ORM, the migrations and the
    suite are preserved across it -- so this writes through the ordinary manager
    and reads back through an ordinary lookup, using nothing a PostgreSQL
    deployment would not also use. The migrations half is covered by the fact
    that this test can find a `users_user` table at all: pytest-django applies
    every migration to the substituted database before the suite starts.
    """
    stored = User.objects.get(pk=user.pk)

    assert stored.username == user.username
    assert User.objects.filter(pk=user.pk).exists()

    stored.name = "Renamed Through The ORM"
    stored.save(update_fields=["name"])

    assert User.objects.get(pk=user.pk).name == "Renamed Through The ORM"


# ---------------------------------------------------------------------------
# AC #2 -- the in-process cache round-trips through the ordinary cache API.
# ---------------------------------------------------------------------------


def test_the_cache_round_trips_through_the_in_process_backend(cache_key: str) -> None:
    """`django.core.cache.cache` set/get/delete behave with no cache server running.

    Written against `django.core.cache.cache` -- the module-level handle every
    call site uses -- rather than against the `CACHES` setting, because "the
    cache API is preserved at every call site" is a claim about that handle. A
    structured value is cached rather than a string so that the assertion would
    also notice a backend that round-tripped through a serializer it should not
    have needed.
    """
    assert cache.get(cache_key, _ABSENT) is _ABSENT

    cache.set(cache_key, CACHED_VALUE)

    assert cache.get(cache_key) == CACHED_VALUE

    cache.delete(cache_key)

    assert cache.get(cache_key, _ABSENT) is _ABSENT


# ---------------------------------------------------------------------------
# AC #3, #4 -- tasks execute eagerly and propagate, with no broker.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_task_body_is_invoked_synchronously_with_no_broker(user: User) -> None:
    """`.delay()` runs the body in the calling process, and the row proves it.

    The `EagerResult` type says the call did not go to a broker; the *value*
    says the body ran here. `user` was created inside this test's transaction and
    has not been committed, so a worker in another process -- the thing this
    substitution stands in for -- could not see it. A count that includes it can
    only have been produced by a query on this connection, in this call.
    """
    result = get_users_count.delay()

    assert isinstance(result, EagerResult)
    assert result.result == User.objects.count()
    assert result.result >= 1, "the task did not see the uncommitted row, so it did not run in this process"


def test_a_failing_task_body_propagates_to_the_caller() -> None:
    """`CELERY_TASK_EAGER_PROPAGATES` is what makes a failing task fail the caller.

    With eager execution alone the exception is captured into the result object,
    so `.delay()` returns normally and a caller that never inspects the result
    sees a broken task as a working one -- locally silent, and loud only once a
    real broker is in front of it. This asserts the raise reaches the caller,
    which is the behaviour a synchronous call is expected to have.
    """
    with pytest.raises(LocalSubstitutionTaskError):
        fail_deliberately.delay()
