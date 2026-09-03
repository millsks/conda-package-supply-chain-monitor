from celery import shared_task

from .models import User


# celery ships no `py.typed` marker and conda-forge carries no stub package for
# it, so `ignore_missing_imports` resolves `shared_task` to `Any` and strict
# mode reports that the decorator erases the annotated signature below. The
# annotations are still the contract this module publishes.
# `warn_unused_ignores` removes the marker when celery starts publishing types.
@shared_task()  # type: ignore[untyped-decorator]
def get_users_count() -> int:
    """A pointless Celery task to demonstrate usage.

    Returns:
        The number of rows in the user table.

    """
    return User.objects.count()
