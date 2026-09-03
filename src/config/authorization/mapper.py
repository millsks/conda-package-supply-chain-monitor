"""The mapper: claims in, a `User` out, plus the authorization that user carries.

AD-10 splits authorization into two operations and this module holds both, under
separate names and at separate frequencies. **Resolve** takes claims and returns
the user by the identity key; it runs on every authentication, including every
Bearer request, and is a single indexed read. **Sync** diffs the asserted groups
against the stored ones, adds, removes, sets `is_staff` and `is_superuser`, and
emits the structured log line; it runs once per *credential epoch* -- every
interactive login, and once per Bearer token at the first sighting of its `jti`.
The two are kept apart deliberately: conflating them buys either
`auth_user_groups` write amplification on every API call or stale authorization,
and there is no third outcome.

**R-2, recorded so it is not mistaken for an oversight.** Syncing once per `jti`
means a group revoked at the IdP is honoured until the token expires. That is
unavoidable for bearer credentials and it narrows FR-9 and SC-6; token lifetime
is the IdP's policy lever, not this component's. Nothing here may try to close
the window: a shorter re-sync interval, a "re-sync every N minutes" timer and a
revocation callback each reintroduce the write amplification AD-10 exists to
prevent, and none of them invalidates the token. Deleting the epoch row early to
force a re-sync is the same mistake by another route -- the row's purpose is
idempotence, not freshness.

AD-11 makes `User.idp_subject` the sole store of identity. Nothing here resolves
by email, by username or through `SocialAccount`, and there is no fallback that
does: a mutable or collidable claim standing in for the identity key is account
takeover, and the same person resolving to two users depending on which flow saw
them first is the other half of the same defect. `username`, `email` and `name`
are attributes -- populated from claims, displayed, used in URLs, never resolved
by.

AD-12 governs the one conflict this creates. Two distinct identity keys asking
for the same `username` is refused and logged, never resolved by overwriting and
never allowed to reach the database as an `IntegrityError` mid-authentication.

AD-4 permits `config` to import `django_service`, so reaching into it here is
legal -- and the reverse, `django_service` importing this module, is not, which
is why nothing in this file is imported from there. The user model is reached
through `django.contrib.auth.get_user_model()` at call time rather than by
importing the concrete class, so this module does not pin `AUTH_USER_MODEL`.
`CredentialEpoch` is imported directly instead: it is not swappable, and AD-10
names `django_service` as the owner of that table, so there is nothing for a
late lookup to keep open. The two territories are deliberate -- the epoch
*table* is `django_service`-owned, the sync *logic* is this package's.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import structlog
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.db import transaction

from config.authorization.claims import read_group_claim
from config.authorization.claims import read_identity_key
from config.authorization.exceptions import ClaimsRejected
from django_service.users.models import CredentialEpoch

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django_service.users.models import User

__all__ = [
    "EMAIL_CLAIM",
    "EXPIRY_CLAIM",
    "JTI_CLAIM",
    "NAME_CLAIM",
    "USERNAME_CLAIM",
    "SyncOutcome",
    "resolve_user",
    "sync_authorization",
    "sync_for_interactive",
    "sync_once_per_epoch",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The attribute claims, by their standard OIDC names. These are *not*
#: configurable and deliberately so: the claims contract (FR-10) designates the
#: claims authorization is decided from -- the identity key and the groups --
#: and an attribute decides nothing. Making a display name configurable would
#: add three more variables an operator can get wrong for no change in who is
#: allowed to do what.
USERNAME_CLAIM: Final = "preferred_username"
EMAIL_CLAIM: Final = "email"
NAME_CLAIM: Final = "name"

#: The two registered JWT claims the epoch gate reads (RFC 7519). Not
#: configurable for the same reason the attribute claims are not: `jti` and `exp`
#: are defined by the standard rather than by an IdP's taxonomy, and the claims
#: contract designates only the claims *authorization is decided from*. An epoch
#: is not an authorization decision -- it is how often one is taken.
JTI_CLAIM: Final = "jti"
EXPIRY_CLAIM: Final = "exp"

#: The user-model fields every claim-derived value is written to. The bound each
#: value is truncated to is read from the field itself (`_field_max_length`)
#: rather than restated here as a number: this module reaches the user model
#: through `get_user_model()` at call time precisely so it does not pin
#: `AUTH_USER_MODEL`, and a hardcoded 150 would pin it right back. A claim is
#: attacker-influenced input, and the database is not the place to find out that
#: it did not fit -- `AbstractUser.username` is 150 characters while
#: `User.idp_subject` is 255, and PostgreSQL answers the difference with a
#: `DataError` mid-authentication where SQLite silently stores it.
_USERNAME_FIELD: Final = "username"
_EMAIL_FIELD: Final = "email"
_NAME_FIELD: Final = "name"
_IDENTITY_FIELD: Final = "idp_subject"

#: The epoch model's own column, spelled out separately from `JTI_CLAIM`. The
#: two names coincide today and nothing keeps them that way: one is a registered
#: JWT claim RFC 7519 defines, the other is a column on a table this project
#: owns and is free to rename. Reading the column's bound through the claim's
#: name would make a rename of either one a silent `FieldDoesNotExist`.
_JTI_FIELD: Final = "jti"

#: Everything Django's `UnicodeUsernameValidator` would reject, restricted to
#: ASCII. The validator admits `[\w.@+-]`; keeping the class ASCII-only means a
#: subject carrying non-Latin script renders to a name that is still stable and
#: still valid rather than one that depends on the database's collation.
_UNSAFE_USERNAME_CHARACTERS: Final = re.compile(r"[^\w.@+-]", re.ASCII)

#: How much of the digest a derived username carries. 128 bits: long enough that
#: two identity keys deriving the same username is not a case anyone has to
#: handle, short enough to leave the name readable in the admin.
_DERIVED_DIGEST_LENGTH: Final = 32

#: Prefix on a derived username, so that a name this module invented is
#: recognisable as one in the admin and in support. It also separates the
#: derived namespace from anything an IdP would plausibly assert as
#: `preferred_username`, which is what keeps a derived name from colliding in
#: turn.
_DERIVED_USERNAME_PREFIX: Final = "idp-"

#: The refusal reasons this module raises. Constants rather than literals at the
#: `raise`, and none of them names a claim *value*: a refusal message carrying
#: the identity key would put the token's contents into the log.
_IDENTITY_KEY_ABSENT: Final = "identity key claim absent"
_IDENTITY_KEY_TOO_LONG: Final = "identity key longer than the identity field"
_USERNAME_UNAVAILABLE: Final = "no username available for the identity key"
_GROUP_CLAIM_ABSENT: Final = "group claim absent"
#: Its own reason, deliberately not shared with any other refusal. A deactivated
#: user's claims are perfectly valid -- the refusal is an operator action taken
#: in this component, not a verdict about the token -- so reporting one of the
#: claim refusals here would send whoever reads the log to the wrong system.
_USER_DEACTIVATED: Final = "resolved user is deactivated"
_NO_JTI: Final = "token carries no jti"
_JTI_TOO_LONG: Final = "jti longer than the epoch field"
_JTI_REUSED: Final = "jti recorded for another identity"


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """What one sync did, so a caller can log or assert it without re-querying.

    Attributes:
        added: Names of the groups the claims asserted that the user did not
            already hold.
        removed: Names of the groups the user held that the claims no longer
            assert. This is the half FR-9 calls revocation, and it is why sync
            diffs rather than only adding.
        ignored: Names the claims asserted that match no Django `Group`. Ignored
            and logged, never created (AD-12).
        is_staff: The staff flag as the claims left it.
        is_superuser: The superuser flag as the claims left it.

    """

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()
    is_staff: bool = False
    is_superuser: bool = False


def resolve_user(claims: Mapping[str, Any]) -> User:
    """Resolve a set of claims to the user the identity key designates.

    Runs on every authentication, including every Bearer request (AD-10). The
    hit path is one indexed read on `User.idp_subject` and writes nothing --
    neither attributes nor groups -- because a resolve that writes is
    `auth_user_groups` amplification on every API call wearing a different name.

    Resolution is by the identity key alone, **and a resolved row must also be
    active to be returned**. The first half is about which claim *identifies* the
    user: `email` and `username` are never consulted, so two identities whose
    emails collide resolve to two users and one identity seen through two flows
    resolves to one user (AD-11). The second half is not a lookup at all -- it is
    a refusal applied to the row the identity key already found, so it restates
    the rule rather than reversing it.

    The deactivation check lives here, once, and every caller inherits it. That
    is a decision rather than a convenience: the Bearer path has no Django
    authentication backend in front of it, so a mapper that returned a
    deactivated user would authenticate a deactivated principal on every API
    request; and per-caller placement has already failed by omission once, since
    Story 2.6 shipped without an explicit check and was safe only because
    allauth's `perform_login` happens to gate inactive users after
    `pre_social_login` returns. The check costs no additional query -- the row is
    loaded by the time it runs. What it does *not* license: `is_active` does not
    become a general authorization input this mapper consults for anything else,
    and no second local-state check joins it without its own decision.

    A miss creates the user: `idp_subject` set, an unusable password, and the
    attribute claims applied under AD-12's collision rule. A deployed component
    authenticates nobody locally, so no user created here may ever carry a
    usable password.

    Args:
        claims: The decoded token claims, or the equivalent mapping an
            interactive login supplies. Read-only; nothing here mutates it.

    Returns:
        The user the identity key designates, existing or newly created.

    Raises:
        ClaimsRejected: The claims cannot be mapped onto a user. Every caller
            translates this into its own protocol's 401 (Stories 2.6 and 2.7),
            so the whole set is one outcome to them; `reason` distinguishes
            them in the log. There are four:

            * `identity key claim absent` -- the configured identity-key claim
              is absent, blank, or is not a string or a non-boolean integer.
              Refused before the query, so no database access happens at all.
            * `identity key longer than the identity field` -- the key would
              not fit `idp_subject`. A refusal rather than a truncation: a
              truncated identity key is a *different* identity, and two keys
              sharing a prefix would resolve to one user. Refused before the
              query for the same reason a `DataError` mid-authentication is
              not an acceptable answer.
            * `no username available for the identity key` -- a first sighting
              whose every deterministic candidate name is already held by
              another row. AD-12 forbids both overwriting the holder and
              letting the conflict reach the database as an `IntegrityError`,
              and a random suffix is forbidden by AC #2, which leaves refusal.
            * `resolved user is deactivated` -- the identity key resolved to a
              row whose `is_active` is False. Its own reason rather than a shared
              one: the claims are valid and the refusal is an operator action
              taken here, so a shared string would send whoever reads the log to
              the IdP for something that was decided in the admin. A user created
              on a miss is active by construction and is never affected.

    """
    subject = read_identity_key(claims, settings.CLAIMS_CONTRACT.identity_key_claim)
    if subject is None:
        raise ClaimsRejected(_IDENTITY_KEY_ABSENT)
    _reject_an_unstorable_identity_key(subject)

    user_model = get_user_model()
    # Exactly one query, and the only one on the hit path. Not `get()` in a
    # `try`, which costs the same query and reads worse; not `get_or_create`,
    # which is two queries and a write attempt on the hot read path; and no
    # `select_related`/`prefetch_related` of groups -- sync loads groups,
    # resolve does not (AD-10).
    user = user_model.objects.filter(idp_subject=subject).first()
    if user is not None:
        _reject_a_deactivated_user(user)
        return user

    return _create_user(subject, claims)


def _reject_a_deactivated_user(user: User) -> None:
    """Refuse a resolved row that an operator has deactivated.

    Checked against the row the lookup already returned, so it costs no
    additional query even on the Bearer path that runs it per request. The
    hot-path objection to putting this in the mapper was the main argument
    against it and it does not survive contact with the code.

    Args:
        user: The user the identity key resolved to.

    Raises:
        ClaimsRejected: The row is deactivated.

    """
    if user.is_active:
        return
    # `idp_subject` is the correlation key an operator has, and it is already in
    # every other event this module emits for this user, so withholding it here
    # would make the one refusal an operator most needs to explain the only one
    # they cannot attribute.
    logger.warning(
        "authorization.claims_rejected",
        reason=_USER_DEACTIVATED,
        idp_subject=user.idp_subject,
    )
    raise ClaimsRejected(_USER_DEACTIVATED)


def _reject_an_unstorable_identity_key(subject: str) -> None:
    """Refuse an identity key the identity field could not hold.

    Truncating instead would be worse than the `DataError` it avoids: a
    truncated key is a *different* identity, so two keys sharing a prefix would
    resolve to one user, which is AD-11's account takeover by another route.

    Args:
        subject: The identity key, already read and non-blank.

    Raises:
        ClaimsRejected: The key is longer than `idp_subject` can hold.

    """
    limit = _field_max_length(_IDENTITY_FIELD)
    if limit is None or len(subject) <= limit:
        return
    # The length, never the key: a refusal event carrying the identity key is
    # the token leaking into the log.
    logger.warning(
        "authorization.identity_key_rejected",
        reason=_IDENTITY_KEY_TOO_LONG,
        identity_key_length=len(subject),
        identity_field_length=limit,
    )
    raise ClaimsRejected(_IDENTITY_KEY_TOO_LONG)


def _create_user(subject: str, claims: Mapping[str, Any]) -> User:
    """Create the user a first-sighting identity key designates.

    Args:
        subject: The identity key, already read, non-blank and short enough to
            store.
        claims: The decoded token claims.

    Returns:
        The newly created user, saved -- or, when a concurrent first sighting of
        the same identity key won the race, the user that one created. Returning
        the winner is the idempotent outcome AC #2 asks for: the same identity
        resolves to the same user however many callers saw it first.

    Raises:
        ClaimsRejected: The insert lost a race for the *username* rather than for
            the identity key, which no deterministic rule can resolve.

    """
    user_model = get_user_model()
    attributes = _attributes_from_claims(claims, subject)

    with transaction.atomic():
        user = user_model(idp_subject=subject)
        user.username = _available_username(user, attributes["username"], subject)
        user.email = attributes["email"]
        user.name = attributes["name"]
        # No user this mapper creates may ever authenticate locally. An unusable
        # password is what makes that structural rather than a convention: the
        # hash cannot be produced by any input, so there is no password to leak,
        # to guess or to be reset into existence.
        user.set_unusable_password()
        try:
            # An inner `atomic()` is a savepoint, and it is load-bearing rather
            # than decorative: `ATOMIC_REQUESTS` is on, so the request's
            # transaction is already open and a constraint violation would leave
            # it broken -- the recovery read below could not run in it. The
            # savepoint confines the rollback to the insert.
            with transaction.atomic():
                user.save()
        except IntegrityError as conflict:
            return _resolve_a_lost_insert(subject, user.username, conflict)

    # The spine makes every authorization change an event, and a new principal
    # existing is one. `idp_subject` is the correlation key an operator has;
    # `django_structlog`'s RequestMiddleware has already bound `request_id`.
    logger.info(
        "authorization.user_created",
        idp_subject=subject,
        username=user.username,
    )
    return user


def _resolve_a_lost_insert(subject: str, username: str, conflict: IntegrityError) -> User:
    """Turn a unique-constraint violation on the insert into a resolution or a refusal.

    The check-then-insert in `resolve_user` is not atomic against a concurrent
    caller: two first sightings of one identity key can both miss the read and
    both insert, and `idp_subject` is unique. AD-12's "never an `IntegrityError`
    mid-authentication" covers this as much as it covers the username rule, and
    a `SELECT ... FOR UPDATE` cannot help -- there is no row to lock yet.

    Which constraint fired is decided by re-reading rather than by parsing the
    driver's message, which differs between PostgreSQL and SQLite and is not a
    contract.

    Args:
        subject: The identity key the insert carried.
        username: The name the insert carried, for the refusal event.
        conflict: The violation, chained onto the refusal so the traceback keeps
            the database's own message.

    Returns:
        The user a concurrent first sighting of the same identity key created.

    Raises:
        ClaimsRejected: The identity key is still absent, so the violation was on
            `username` -- a name free at the check and taken by the time of the
            insert. Deterministic rules have run out and a random suffix is
            forbidden, so this is a refusal.

    """
    winner = get_user_model().objects.filter(idp_subject=subject).first()
    if winner is None:
        logger.warning(
            "authorization.username_unavailable",
            idp_subject=subject,
            desired_username=username,
        )
        raise ClaimsRejected(_USERNAME_UNAVAILABLE) from conflict

    logger.info(
        "authorization.user_created_concurrently",
        idp_subject=subject,
        username=winner.username,
    )
    return winner


def _attributes_from_claims(claims: Mapping[str, Any], subject: str) -> dict[str, str]:
    """Read the three attribute claims, with the identity key as the fallback name.

    `email` is read here and written unconditionally by the caller. It is never
    part of any lookup: `AbstractUser.email` carries no uniqueness constraint in
    this model, so two identities asserting one email produce two rows and no
    conflict. That is structural rather than a branch, and it is why no
    uniqueness constraint may be added to `email`.

    Args:
        claims: The decoded token claims.
        subject: The identity key, used as the username when the IdP asserts no
            `preferred_username`. It is rendered rather than used raw -- the
            identity key may be longer than a username field and may carry
            characters Django's username validator rejects.

    Returns:
        The `username`, `email` and `name` to write, each a string and each
        bounded by the field it is written to. A claim that is absent, blank or
        not a string yields the empty string, which is what `AbstractUser`
        already means by "unset" for `email` and `name`. A `preferred_username`
        is sanitized and truncated exactly as the fallback name is -- the claim
        is attacker-influenced input, and an unsanitized one reaches the model as
        a name `UnicodeUsernameValidator` rejects and `users:detail` cannot
        reverse. A claim that sanitizes to nothing falls through to the derived
        name, exactly as a blank one does.

    """
    return {
        "username": _sanitized_username(_read_text(claims, USERNAME_CLAIM)) or _username_from_identity_key(subject),
        "email": _bounded(_read_text(claims, EMAIL_CLAIM), _EMAIL_FIELD),
        "name": _bounded(_read_text(claims, NAME_CLAIM), _NAME_FIELD),
    }


def _field_max_length(field_name: str) -> int | None:
    """Read a user-model field's length bound from the field itself.

    Args:
        field_name: The field's name on the user model.

    Returns:
        The field's `max_length`, or None when it declares none. None means
        unbounded and therefore nothing to truncate to -- a swapped-in user model
        carrying a `TextField` is not truncated at a guessed number.

    """
    field = get_user_model()._meta.get_field(field_name)  # noqa: SLF001 - `Model._meta` is Django's documented field API
    max_length = getattr(field, "max_length", None)
    return max_length if isinstance(max_length, int) else None


def _bounded(value: str, field_name: str) -> str:
    """Truncate a claim-derived value to the field it is written to.

    Args:
        value: The value read from the claims.
        field_name: The field's name on the user model.

    Returns:
        The value, truncated to the field's length when the field declares one.

    """
    limit = _field_max_length(field_name)
    return value if limit is None else value[:limit]


def _sanitized_username(value: str) -> str:
    """Render any string as something the username field and validator accept.

    The one renderer, applied to the `preferred_username` claim and to the
    identity-key fallback alike. Two renderings would be the asymmetry this
    exists to remove: the fallback was bounded and the claim was not, so the
    claim was the way an over-long or `/`-carrying name reached the model.

    Args:
        value: The name to render.

    Returns:
        The value with every character Django's username validator rejects
        replaced by a hyphen, trimmed of the hyphens that leaves at either end
        and truncated to the field's length. The empty string when nothing
        usable survives -- callers treat that as "no name asked for" and fall
        through to a derived one.

    """
    rendered = _UNSAFE_USERNAME_CHARACTERS.sub("-", value).strip("-")
    limit = _field_max_length(_USERNAME_FIELD)
    if limit is not None:
        rendered = rendered[:limit]
    # Trimmed again after the slice: truncation can land on a hyphen, and a name
    # ending in one is valid but reads as a rendering artefact.
    return rendered.strip("-")


def _read_text(claims: Mapping[str, Any], name: str) -> str:
    """Read one attribute claim as a stripped string.

    Args:
        claims: The decoded token claims.
        name: The claim name. Attribute claims are flat standard OIDC names, so
            no dotted walk applies -- that is the claims contract's business and
            only for the claims authorization is decided from.

    Returns:
        The value stripped, or the empty string when the claim is absent, blank
        or not a string. Non-strings are not coerced: `str()` of a dict or a
        list would land in the admin and in URLs as a display name.

    """
    value = claims.get(name)
    return value.strip() if isinstance(value, str) else ""


def _available_username(user: User, desired: str, subject: str) -> str:
    """Apply AD-12's collision rule and return the username to write.

    A `username` collision between two distinct `idp_subject`s is refused and
    logged. Refused means the desired name is *not* taken from its holder and
    the arriving identity authenticates normally under another name -- never an
    `IntegrityError` mid-authentication, and never a silent overwrite that would
    hand one person another's display identity.

    Args:
        user: The user the name would be written to. Excluded from the search by
            primary key so a user keeping its own name is not read as colliding
            with itself; an unsaved user has `pk` None, which Django resolves to
            `NOT (id IS NULL)` and therefore excludes nothing.
        desired: The name the claims ask for.
        subject: The arriving identity key, which is what the fallback names are
            derived from.

    Returns:
        The first candidate name that is free. `desired` when it is free and no
        event at all; otherwise a name derived from `subject`, with the collision
        logged.

    Raises:
        ClaimsRejected: Every candidate is held by another row. The derived
            namespace is forgeable -- `_derived_username` is a pure function of
            the subject, so a claim can assert the name another identity's first
            sighting will derive -- which is why the derived name is checked for
            availability rather than assumed free. When the check runs out of
            candidates the alternatives are all forbidden: overwriting a holder
            (AD-12), a random suffix or a counter (AC #2's determinism), or an
            `IntegrityError` mid-authentication (AD-12 again).

    """
    user_model = get_user_model()
    candidates = _username_candidates(desired, subject)
    # One query for the whole candidate list, and it answers both questions the
    # rule needs: which names are taken, and by which identity. `exists()`
    # answers only the first, and `held_by_idp_subject` is not optional in the
    # event -- without it the log says a collision happened and gives nobody
    # anything to look at. A holder's `idp_subject` may legitimately be None (a
    # row predating the identity key), which is why the mapping is keyed on the
    # name and read by membership rather than by truthiness.
    holders: dict[str, str | None] = dict(
        user_model.objects.filter(username__in=candidates).exclude(pk=user.pk).values_list("username", "idp_subject"),
    )
    for candidate in candidates:
        if candidate not in holders:
            if candidate != desired:
                logger.warning(
                    "authorization.username_collision",
                    idp_subject=subject,
                    desired_username=desired,
                    held_by_idp_subject=holders[desired],
                    username=candidate,
                )
            return candidate

    logger.warning(
        "authorization.username_unavailable",
        idp_subject=subject,
        desired_username=desired,
    )
    raise ClaimsRejected(_USERNAME_UNAVAILABLE)


def _username_candidates(desired: str, subject: str) -> list[str]:
    """The names to try, in order, every one of them a function of the input alone.

    Determinism is the property that matters here: the same claims produce the
    same list in every process and after every restart, so which name an identity
    ends up with depends only on which of them are already held. A counter or a
    random suffix would produce a name that depends on when the identity was
    first seen, making AC #2's "resolves to the same user in both orders" flaky
    and the collision unreproducible in support.

    Args:
        desired: The name the claims ask for, already sanitized.
        subject: The arriving identity key.

    Returns:
        The asked-for name, then the digest form, then the identity key's own
        rendering -- deduplicated, since the last two coincide for a key with no
        usable characters.

    """
    ordered = [desired, _derived_username(subject), _username_from_identity_key(subject)]
    return list(dict.fromkeys(ordered))


def _username_from_identity_key(subject: str) -> str:
    """Render an identity key as a username Django will accept.

    Args:
        subject: The identity key.

    Returns:
        The key sanitized by `_sanitized_username`. A key that renders to nothing
        -- every character unsafe, as a subject in a non-Latin script would be --
        falls through to the digest form, which is never empty. The sanitizer's
        trim is what makes that reachable: without it `sub` returns a run of
        hyphens, which is a truthy string and a meaningless username.

    """
    return _sanitized_username(subject) or _derived_username(subject)


def _derived_username(subject: str) -> str:
    """Derive a stable, collision-free username from an identity key.

    Deterministic by construction: the same identity key yields the same name on
    every call, in every process and after every restart. That is a requirement
    rather than a nicety -- a random suffix or a counter would make the same
    identity resolve to a different name depending on when it was first seen,
    which is unreproducible in support and makes "resolves to the same user in
    both orders" a flaky assertion.

    Args:
        subject: The identity key.

    Returns:
        The prefix followed by 128 bits of the key's SHA-256 digest. The digest
        rather than the key itself so the name is bounded, valid and free of
        whatever the IdP put in the subject; SHA-256 rather than a shorter hash
        because two identities sharing a username is the failure this exists to
        rule out.

    """
    digest = hashlib.sha256(subject.encode()).hexdigest()[:_DERIVED_DIGEST_LENGTH]
    return f"{_DERIVED_USERNAME_PREFIX}{digest}"


def sync_authorization(user: User, claims: Mapping[str, Any]) -> SyncOutcome:
    """Re-derive a user's authorization from the claims, additions and removals alike.

    AD-10's second operation. It takes the user it is handed -- it never looks
    one up, which is `resolve_user`'s job and runs at a different frequency -- and
    makes the stored authorization equal what the claims assert: groups added,
    groups no longer asserted removed, `is_staff` and `is_superuser` each set
    from its own designated group and each cleared when unasserted.

    All of it runs inside one transaction, which is what makes the add-then-remove
    ordering a detail rather than a security property: no observer sees the user
    holding the union or the empty intersection.

    Args:
        user: The user the claims resolved to, already saved.
        claims: The decoded token claims, or the equivalent mapping an
            interactive login supplies. Read-only.

    Returns:
        What the sync did, for the caller to log or assert without re-querying.

    Raises:
        ClaimsRejected: `group claim absent` -- the configured group claim is
            absent or unreadable. AD-12 is explicit that this is a 401 and never
            an authentication with zero groups: the two are indistinguishable on
            the row afterwards, and treating a misconfigured claim name as "this
            person has no groups" is how a misconfiguration presents as a
            permissions bug. A claim that is *present* and empty is a legitimate
            assertion of no groups and syncs normally.

    """
    contract = settings.CLAIMS_CONTRACT
    asserted = read_group_claim(claims, contract.group_claim)
    if asserted is None:
        # The refusal AD-12 asks for, said out loud rather than only raised. The
        # whole reason an absent group claim is a 401 is that a misconfigured
        # claim *name* is indistinguishable from an identity holding no groups
        # once the request is over, so the event carries the name that was
        # looked for -- the one thing the operator cannot infer from the 401.
        # The name, never the claims: a configured claim name is the operator's
        # own setting, not the token's contents.
        logger.warning(
            "authorization.claims_rejected",
            reason=_GROUP_CLAIM_ABSENT,
            idp_subject=user.idp_subject,
            group_claim=contract.group_claim,
        )
        raise ClaimsRejected(_GROUP_CLAIM_ABSENT)

    with transaction.atomic():
        # One query for the whole asserted set. Names that come back with no row
        # are the ignored set -- never created (AD-12), which is safe only
        # because Story 2.3 guarantees the designated rows already exist. Group
        # creation has exactly one call site in this repository, and it is
        # `django_service.users.provisioning`.
        resolved: dict[str, int] = dict(Group.objects.filter(name__in=asserted).values_list("name", "pk"))
        held: dict[str, int] = dict(user.groups.values_list("name", "pk"))

        # `dict.fromkeys` rather than a set: a claim asserting the same name
        # twice is one group, and the order the claims asserted them in is the
        # only order that means anything to whoever reads the event.
        ordered = tuple(dict.fromkeys(asserted))
        ignored = tuple(name for name in ordered if name not in resolved)
        added = tuple(name for name in ordered if name in resolved and name not in held)
        # Sorted because the held set arrives in the database's order, which is
        # not an order anyone declared; an unsorted tuple would make the emitted
        # event and any assertion against it depend on it.
        removed = tuple(sorted(name for name in held if name not in resolved))

        # `add`/`remove` rather than `set`: AC #1 requires the log line to record
        # what changed, and `set` hides which rows moved.
        if added:
            user.groups.add(*(resolved[name] for name in added))
        if removed:
            user.groups.remove(*(held[name] for name in removed))

        # Each flag from its own designated group, and each *cleared* when the
        # claims stop asserting it (AD-12) -- the clearing half is what makes a
        # revocation at the IdP reach the component. Read against the resolved
        # names rather than the asserted ones so a designated group that does not
        # exist cannot confer anything.
        user.is_staff = contract.staff_group in resolved
        user.is_superuser = contract.superuser_group in resolved
        user.save(update_fields=["is_staff", "is_superuser"])

        for name in ignored:
            # Handled, not swallowed: an IdP taxonomy that does not match this
            # component's groups is a configuration mistake somebody has to be
            # able to see, and it is the one thing the caller cannot infer from
            # the outcome of an otherwise successful authentication.
            logger.warning(
                "authorization.unknown_group_claim",
                idp_subject=user.idp_subject,
                group=name,
            )

        outcome = SyncOutcome(
            added=added,
            removed=removed,
            ignored=ignored,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
        )
        # The spine makes every authorization change an event, and this is the
        # authorization change. One line per sync, recording what moved.
        logger.info(
            "authorization.synced",
            idp_subject=user.idp_subject,
            groups_added=outcome.added,
            groups_removed=outcome.removed,
            groups_ignored=outcome.ignored,
            is_staff=outcome.is_staff,
            is_superuser=outcome.is_superuser,
        )
    return outcome


def sync_for_interactive(user: User, claims: Mapping[str, Any]) -> SyncOutcome:
    """Sync an interactive login, unconditionally.

    An interactive login *is* the epoch: it carries no `jti`, and there is
    nothing to record a first sighting of. Routing it through the epoch gate
    would either reject every interactive login for having no `jti` or force one
    to be invented, and both are worse than the write this saves -- an
    interactive login happens once per session, not once per API call, so the
    amplification AD-10 guards against is not on this path.

    Args:
        user: The user the claims resolved to.
        claims: The claims the provider supplied for this login.

    Returns:
        What the sync did.

    Raises:
        ClaimsRejected: As `sync_authorization`.

    """
    return sync_authorization(user, claims)


def sync_once_per_epoch(user: User, claims: Mapping[str, Any]) -> SyncOutcome | None:
    """Sync a Bearer credential at the first sighting of its `jti`, and never again.

    The gate AD-10 turns on. Syncing on every Bearer request is
    `auth_user_groups` write amplification on every API call; syncing never is
    stale authorization. Recording the epoch in a table -- never in
    `django.core.cache`, whose in-process backend in the two Redis-less
    combinations would degrade "first sighting" to
    first-sighting-per-worker-per-restart -- is what makes the frequency the same
    in all six.

    Args:
        user: The user the claims resolved to.
        claims: The decoded token claims.

    Returns:
        What the sync did, or None when this `jti` had already been seen and no
        sync was therefore performed.

    Raises:
        ClaimsRejected: There are four, and every one of them is a 401 the
            caller translates:

            * `token carries no jti` -- the token is absent a `jti`, or carries a
              blank or non-string one. Rejected rather than tolerated: without
              the rule, one builder syncs on every request and another never
              syncs again, which are exactly the two outcomes AD-10 exists to
              prevent.
            * `jti longer than the epoch field` -- the `jti` would not fit the
              column. Refused before the insert for the same reason an over-long
              identity key is: truncating would make two distinct credentials
              share one epoch, and PostgreSQL answers the alternative with a
              `DataError` in the middle of an authentication.
            * `jti recorded for another identity` -- the epoch row for this
              `jti` names a different user. Whatever produced it -- an issuer
              minting identifiers that collide, or a token presented for the
              wrong subject -- syncing would decide this user's authorization
              from another credential's epoch, which is the stale-authorization
              half of what AD-10 prevents.
            * `group claim absent` -- raised by `sync_authorization`, which this
              calls at a first sighting, and propagated rather than caught. The
              epoch row the sighting inserted rolls back with it, so the
              credential is free to sync once the claim is configured correctly
              rather than having burnt its one epoch on a refusal.

    """
    jti = _read_text(claims, JTI_CLAIM)
    if not jti:
        logger.warning(
            "authorization.jti_rejected",
            reason=_NO_JTI,
            idp_subject=user.idp_subject,
        )
        raise ClaimsRejected(_NO_JTI)
    _reject_an_unstorable_jti(jti)

    with transaction.atomic():
        try:
            # An inner `atomic()` is a savepoint, and here it is defence in depth
            # rather than the only thing keeping the request's transaction
            # usable: `get_or_create` opens one of its own around the insert.
            # `ATOMIC_REQUESTS` is on, so a violation escaping both would leave
            # the request's transaction broken and the recovery read below
            # unable to run in it. The savepoint confines the rollback.
            with transaction.atomic():
                epoch, created = CredentialEpoch.objects.get_or_create(
                    jti=jti,
                    defaults={"user": user, "expires_at": _expires_at(claims)},
                )
        except IntegrityError:
            # Not the two-worker race, despite the name of the event below.
            # Django's `get_or_create` wraps the insert in its own `atomic()`,
            # catches the violation and re-reads, so the loser of a race for one
            # first sighting comes back with `created` False and never reaches
            # here. What reaches here is a violation whose re-read *also* found
            # nothing: the user row gone under a foreign key, a null in a NOT
            # NULL column, some other constraint entirely. So this branch is the
            # second line of defence for the race and the guard against a
            # different fault being reported as a sighting -- which would skip
            # the sync outright and leave a debug line as the only trace.
            if CredentialEpoch.objects.filter(jti=jti).exists():
                # Genuinely already recorded, and the answer is a second
                # sighting's: nothing to sync. Debug rather than warning -- it is
                # the constraint working, not a fault.
                logger.debug("authorization.epoch_race", idp_subject=user.idp_subject)
                return None
            # `exception` rather than `error`: it is the same error level with
            # the database's own message attached, and which constraint the
            # driver named is the whole content of the report. Re-raised
            # afterwards rather than answered with None -- an epoch that was
            # never recorded is not a sighting, and reporting it as one would
            # skip the sync and leave this line as the only trace.
            logger.exception("authorization.epoch_insert_failed", idp_subject=user.idp_subject)
            raise

        if not created:
            _reject_a_jti_held_by_another_identity(user, epoch, jti)
            return None
        return sync_authorization(user, claims)


def _reject_a_jti_held_by_another_identity(user: User, epoch: CredentialEpoch, jti: str) -> None:
    """Refuse a credential whose epoch was recorded against a different user.

    A second sighting of a `jti` is ordinarily nothing to do, which is the whole
    point of the gate. A second sighting *belonging to somebody else* is not the
    same event: the identifier is either colliding at the issuer or being
    presented for the wrong subject, and taking the quiet path would let this
    authentication ride another credential's epoch -- authorization decided from
    a sync nobody performed for this user, which is exactly the staleness AD-10
    exists to prevent. No new exception class: `ClaimsRejected.reason` is what
    distinguishes the refusals (AD-12).

    Args:
        user: The user the claims resolved to.
        epoch: The epoch row already recorded for this `jti`.
        jti: The token identifier, for its length alone.

    Raises:
        ClaimsRejected: The recorded epoch names another user.

    """
    if epoch.user_id == user.pk:
        return
    # The length, never the value, for the reason `_reject_an_unstorable_jti`
    # gives: a `jti` in the log is a token identifier leaking out of the token.
    logger.warning(
        "authorization.epoch_jti_reuse",
        reason=_JTI_REUSED,
        idp_subject=user.idp_subject,
        jti_length=len(jti),
    )
    raise ClaimsRejected(_JTI_REUSED)


def _reject_an_unstorable_jti(jti: str) -> None:
    """Refuse a `jti` the epoch column could not hold.

    Args:
        jti: The token identifier, already read and non-blank.

    Raises:
        ClaimsRejected: The `jti` is longer than the column can store.

    """
    # `_JTI_FIELD`, not `JTI_CLAIM`: the column's name and the claim's name are
    # independent of each other and coincide only by convention.
    limit = CredentialEpoch._meta.get_field(_JTI_FIELD).max_length  # noqa: SLF001 - `Model._meta` is Django's documented field API
    if not isinstance(limit, int) or len(jti) <= limit:
        return
    # The length, never the value: a `jti` in the log is a token identifier
    # leaking out of the token.
    logger.warning(
        "authorization.jti_rejected",
        reason=_JTI_TOO_LONG,
        jti_length=len(jti),
        jti_field_length=limit,
    )
    raise ClaimsRejected(_JTI_TOO_LONG)


def _expires_at(claims: Mapping[str, Any]) -> datetime | None:
    """Read the token's expiry as the moment the epoch row stops mattering.

    The column exists so AD-31's declared admin process can prune the table
    alongside expired sessions; without it the table grows without bound. This
    story builds the column, not the pruner.

    Args:
        claims: The decoded token claims.

    Returns:
        The `exp` claim as an aware UTC datetime, or None when the token carries
        no readable one. RFC 7519 defines `exp` as a NumericDate -- seconds since
        the epoch -- so a boolean, a string or a value the platform cannot
        represent as a datetime yields None rather than an invented expiry. A
        null expiry means "not prunable by expiry", which is the safe reading:
        an epoch row pruned early would re-sync a credential, never admit one.

    """
    value = claims.get(EXPIRY_CLAIM)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except OverflowError, OSError, ValueError:
        # Handled and reported, never swallowed. The authentication proceeds --
        # an unreadable expiry is not grounds to refuse a token whose signature
        # and claims are otherwise good -- but the row is left unprunable, and
        # that is a thing an operator watching the table's size needs told.
        logger.warning("authorization.unreadable_expiry_claim")
        return None
