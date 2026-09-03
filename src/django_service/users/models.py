from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db.models import CASCADE
from django.db.models import CharField
from django.db.models import DateTimeField
from django.db.models import ForeignKey
from django.db.models import Model
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Default custom user model for Django 15-Factor Application Accelerator.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = CharField(_("Name of User"), blank=True, max_length=255)
    # The identity key (AD-11): unique, indexed, nullable, and the sole store.
    # `unique=True` already creates the index -- Django's schema editor emits an
    # explicit one only for `db_index and not unique` -- so no `db_index=True`.
    # Nullable because existing rows carry no key until their next
    # authentication; both PostgreSQL and SQLite allow repeated NULLs under a
    # UNIQUE constraint, which is what makes that work without a backfill.
    idp_subject = CharField(
        _("IdP subject"),
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        default=None,
    )
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})


class CredentialEpoch(Model):
    """One row per credential the mapper has already synced authorization for.

    AD-10 splits authorization into resolve, which runs on every request, and
    sync, which runs once per *credential epoch* -- every interactive login, and
    once per Bearer token at the first sighting of its `jti`. This table is the
    record of that first sighting, and it is a table rather than
    `django.core.cache` deliberately: two of the six declared combinations ship
    no Redis, so their cache is Django's in-process backend and "first sighting"
    would degrade to first-sighting-per-worker-per-restart -- syncing on every
    request in one deployment and never again in another, which are the only two
    outcomes AD-10 exists to prevent.

    The rows accumulate and are pruned by AD-31's declared admin process
    alongside expired sessions, not by a background task -- Celery exists in only
    two of the six combinations. `expires_at` is the column that process scans,
    which is why it carries its own index and why it is populated here from the
    token's `exp` claim.

    AD-29 makes `src/django_service/` core in its entirety, so this model carries
    no `feature:*` marker, and AD-10 records that adding it is internal surface
    rather than an API version bump.
    """

    # `unique=True` is what makes "first sighting" a database guarantee rather
    # than a check-then-act: two workers racing the same token both try to
    # insert, one loses on the constraint, and exactly one of them syncs. The
    # constraint already creates the index, so no `db_index=True` here.
    jti = CharField(_("JWT ID"), max_length=255, unique=True)
    user = ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=CASCADE,
        related_name="credential_epochs",
        verbose_name=_("user"),
    )
    first_seen_at = DateTimeField(_("first seen at"), auto_now_add=True)
    # Indexed because the pruning process (AD-31) scans on it. Nullable because a
    # token need not carry `exp`; such a row is simply not prunable by expiry.
    expires_at = DateTimeField(_("expires at"), null=True, blank=True, db_index=True)

    def __str__(self) -> str:
        """Identify the epoch by the credential it records.

        Returns:
            str: The `jti` the epoch was recorded for.

        """
        return self.jti
