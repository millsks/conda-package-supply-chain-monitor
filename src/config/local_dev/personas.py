"""The persona declarations, and the one constructor of synthetic claims.

A persona is a named local identity declared as configuration: its groups, its
profile fields, and the identity-key *value* the mapper resolves it by (FR-19).
Nothing here authenticates anybody and nothing here writes to the database --
`seeding.py` materializes these declarations, `Story 3.4`'s route signs one in,
and both go through the same mapper an IdP flow does.

**No persona names a group.** A persona lists `DESIGNATED_STAFF` or
`DESIGNATED_SUPERUSER` where it should carry whichever group the claims contract
designates, and `resolve_groups` substitutes the configured name at call time.
Hardcoding `platform-staff` here would make the personas silently wrong in every
component that configures a different taxonomy, which is exactly the coupling
FR-10 made the contract configuration to remove.

**`build_claims` is the sole constructor of synthetic claims.** Stories 3.4 and
3.5 both call it; neither builds a payload of its own. A second constructor is
how the interactive path and the token path drift into asserting differently
shaped claims, and the whole value of the local paths is that the mapper cannot
tell which one produced what it was handed.

**What the payload deliberately does not carry.** No `jti`, `iss`, `aud` or
`exp`. Those are registered claims of the programmatic flow and Story 3.5's
token minting adds them; an interactive persona sign-in *is* the epoch, carries
no `jti`, and drives `sync_for_interactive` rather than the epoch gate (AD-10).
Inventing a `jti` here would either be discarded by the interactive path or
burn a real epoch on a synthetic credential.

AD-4 permits `config` to import `django_service`; the attribute-claim names are
imported from the mapper rather than restated, so the writer and the reader
cannot disagree about which claim carries the display name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Final

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.authorization.mapper import EMAIL_CLAIM
from config.authorization.mapper import NAME_CLAIM
from config.authorization.mapper import USERNAME_CLAIM

__all__ = [
    "DESIGNATED_STAFF",
    "DESIGNATED_SUPERUSER",
    "PERSONAS",
    "Persona",
    "UnknownPersonaError",
    "build_claims",
    "get_persona",
    "persona_keys",
    "resolve_groups",
]

#: The two placeholders a persona lists in place of a group *name*. They are
#: substituted by `resolve_groups` for whatever the claims contract designates,
#: which is what keeps every group name in this file out of it. The angle
#: brackets are not decoration: a sentinel that escaped substitution has to be
#: recognisable as one in a log line, and it must not plausibly match a group an
#: operator would create -- an unmatched name is ignored and logged by the
#: mapper (AD-12), never created, so the failure is visible rather than a
#: silently invented group.
DESIGNATED_STAFF: Final[str] = "<designated-staff-group>"
DESIGNATED_SUPERUSER: Final[str] = "<designated-superuser-group>"

#: Raised when two configured claim names overlap so that one would have to be
#: nested inside the other's value. Named here rather than written at the
#: `raise` so the refusal reads the same wherever it is asserted.
_OVERLAPPING_CLAIM_NAMES: Final[str] = (
    "the configured claim names overlap: one is a dotted path through another's value, "
    "so no single payload can carry both. Check COMPONENT_IDENTITY_CLAIM and COMPONENT_GROUP_CLAIM."
)


class UnknownPersonaError(LookupError):
    """Raised when a key names no declared persona.

    A `LookupError` rather than a bespoke base: Story 3.4's route turns an
    unknown key into a 404, and a caller that wants to be liberal can catch the
    standard type. It is narrow deliberately -- `KeyError` would also be raised
    by any incidental dictionary miss inside this module, and a route catching
    that would turn a real defect into a 404.
    """


@dataclass(frozen=True, slots=True)
class Persona:
    """One declared local identity.

    Attributes:
        key: The slug the sign-in URL and the seeding task's output name it by.
            It is not an identity: nothing resolves a user from it.
        subject: The identity-key *value* the mapper resolves by (AD-11). It
            populates `User.idp_subject` and is the only field resolution ever
            reads, which is why two sign-ins as one persona are one user however
            its username changes.
        username: The `preferred_username` claim. An attribute -- displayed and
            used in URLs, never resolved by.
        email: The `email` claim. An attribute, and carrying no uniqueness
            constraint on the model.
        name: The `name` claim, the display name.
        groups: The groups this persona asserts, each either a literal group
            name or one of the two sentinels above.

    """

    key: str
    subject: str
    username: str
    email: str
    name: str
    groups: tuple[str, ...] = ()


#: The declared personas. Two, with genuinely different memberships, which is
#: the minimum AC #1 asks for and the minimum that makes the divergence Story
#: 3.4 demonstrates real: the same admin page admits one and refuses the other,
#: and the difference is produced by the mapper rather than by a local branch.
#:
#: Exactly one carries `DESIGNATED_STAFF`. Neither carries
#: `DESIGNATED_SUPERUSER`: a superuser bypasses every permission check
#: (`ModelBackend.has_perm` short-circuits on `is_superuser`), so a superuser
#: persona would make every local authorization check pass and prove nothing.
#: The sentinel exists for a component that declares one deliberately.
#:
#: The addresses are on `.invalid`, which RFC 2606 reserves precisely so that a
#: development fixture cannot be a real mailbox.
PERSONAS: Final[tuple[Persona, ...]] = (
    Persona(
        key="staff",
        subject="local-dev:persona:staff",
        username="staff-persona",
        email="staff-persona@localhost.invalid",
        name="Staff Persona",
        groups=(DESIGNATED_STAFF,),
    ),
    Persona(
        key="reader",
        subject="local-dev:persona:reader",
        username="reader-persona",
        email="reader-persona@localhost.invalid",
        name="Reader Persona",
        groups=(),
    ),
)

_BY_KEY: Final[dict[str, Persona]] = {persona.key: persona for persona in PERSONAS}


def persona_keys() -> tuple[str, ...]:
    """Return the declared persona keys, in declaration order.

    Returns:
        Every key `get_persona` accepts.

    """
    return tuple(_BY_KEY)


def get_persona(key: str) -> Persona:
    """Return the persona a key names.

    Args:
        key: The slug a URL or a task argument carries.

    Returns:
        The declared persona.

    Raises:
        UnknownPersonaError: The key names no declared persona. A refusal rather
            than a fallback to the first persona: signing in as an unrecognised
            name and silently getting the staff one is the worst answer
            available.

    """
    persona = _BY_KEY.get(key)
    if persona is None:
        raise UnknownPersonaError(key)
    return persona


def resolve_groups(persona: Persona) -> tuple[str, ...]:
    """Substitute the designated-group sentinels for the configured names.

    Read through `django.conf.settings` rather than from a literal, so a
    component that designates `shipping-desk-operators` gets personas that
    assert *that*, with no edit to this file.

    Args:
        persona: The declared persona.

    Returns:
        The group names this persona asserts, deduplicated and in declaration
        order. Deduplication is not cosmetic: an operator may legitimately point
        `COMPONENT_STAFF_GROUP` and `COMPONENT_SUPERUSER_GROUP` at one group, and
        a persona carrying both sentinels would then assert it twice.

    """
    contract = settings.CLAIMS_CONTRACT
    designated = {
        DESIGNATED_STAFF: contract.staff_group,
        DESIGNATED_SUPERUSER: contract.superuser_group,
    }
    return tuple(dict.fromkeys(designated.get(name, name) for name in persona.groups))


def build_claims(persona: Persona) -> dict[str, Any]:
    """Build the synthetic claims payload a persona signs in with.

    The identity key and the groups are keyed by the *configured* claim names,
    never by `sub` and `groups`: the payload has to be readable by the same
    `read_identity_key` and `read_group_claim` an IdP's token goes through, and
    those read whatever the contract designates.

    Args:
        persona: The declared persona.

    Returns:
        A payload carrying the identity key at the configured identity-key
        claim, the resolved groups at the configured group claim, and the three
        profile fields under the standard OIDC attribute names. No `jti`, `iss`,
        `aud` or `exp` -- see the module docstring.

    Raises:
        ImproperlyConfigured: The two configured claim names overlap, so one
            would have to be nested inside the other's value.

    """
    contract = settings.CLAIMS_CONTRACT
    claims: dict[str, Any] = {
        USERNAME_CLAIM: persona.username,
        EMAIL_CLAIM: persona.email,
        NAME_CLAIM: persona.name,
    }
    _set_dotted(claims, contract.identity_key_claim, persona.subject)
    _set_dotted(claims, contract.group_claim, list(resolve_groups(persona)))
    return claims


def _set_dotted(payload: dict[str, Any], path: str, value: Any) -> None:
    """Write a claim at a name that may be a dotted path, nesting as it goes.

    The writing half of `config.authorization.claims._resolve`, and it splits on
    exactly the same rule so the round trip holds for every configured name.
    `realm_access.roles` therefore lands as `{"realm_access": {"roles": [...]}}`,
    which is the shape Keycloak actually emits -- and shape is the point. The
    reader would in fact also accept a flat key literally named
    `"realm_access.roles"`, because `_resolve` tries the whole path as a literal
    key first for the sake of Auth0's and Azure AD's URI-shaped claim names; a
    flat write would round-trip through it and still be a payload no IdP
    produces, so the local paths would exercise a nesting the deployed path
    never sees.

    A URI-shaped name nests too -- `https://example.com/roles` splits at the dot
    in the host -- and it round-trips for the same reason: the reader's literal
    read misses and its split is this one.

    Args:
        payload: The payload being built. Mutated in place.
        path: The configured claim name, optionally dotted. An empty name -- an
            unconfigured contract -- writes nothing, exactly as `_resolve` reads
            nothing from one.
        value: The value to write.

    Raises:
        ImproperlyConfigured: A segment of the path is already held by something
            that is not a mapping, which means two configured claim names
            overlap. A refusal rather than an overwrite: overwriting would drop
            whichever claim was written first, and a payload silently missing its
            identity key presents as an authentication bug.

    """
    if not path:
        return
    head, separator, tail = path.partition(".")
    if not separator:
        payload[path] = value
        return
    nested = payload.setdefault(head, {})
    if not isinstance(nested, dict):
        raise ImproperlyConfigured(_OVERLAPPING_CLAIM_NAMES)
    _set_dotted(nested, tail, value)
