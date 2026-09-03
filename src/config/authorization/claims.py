"""The claims contract: four claim *names*, read from the environment.

FR-10 makes the contract configuration rather than code, so a component can be
pointed at any IdP's claim taxonomy without a code change. Every field here
holds the *name* of a claim or of a group -- never a claim value and never a
group membership.

Nothing in this module defaults a conventional claim name. An unset variable
yields the empty string, and the empty string means *unconfigured*: it is what
`is_configured` reports on and what Epic 4's startup refusal acts on. Defaulting
`sub`, `groups` or `roles` here would turn a missing configuration into a
plausible-looking wrong one.

Nothing here raises either. A raise at import time would fire during the test
suite and during every management command, long before Epic 4 has a locality
signal to gate the refusal with.

AD-4 (dependency direction) applies: this module imports nothing from
`django_service` and nothing from `django.contrib.auth`. It deals in names, not
in models.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

if TYPE_CHECKING:
    import environ

__all__ = [
    "CLAIMS_ENVIRONMENT_VARIABLES",
    "ClaimsContract",
    "load_claims_contract",
    "read_group_claim",
    "read_identity_key",
]

#: The four variables the contract is read from, in field order. Declared here
#: rather than only inline in `load_claims_contract` so that the operator-facing
#: documentation can be pinned against the names actually read.
CLAIMS_ENVIRONMENT_VARIABLES: Final[tuple[str, ...]] = (
    "COMPONENT_IDENTITY_CLAIM",
    "COMPONENT_GROUP_CLAIM",
    "COMPONENT_STAFF_GROUP",
    "COMPONENT_SUPERUSER_GROUP",
)


@dataclass(frozen=True, slots=True)
class ClaimsContract:
    """The four names a component needs to map an IdP's claims onto Django.

    Each field is a name, never a value: `group_claim` is the name of the claim
    that carries groups, not a group; `staff_group` is the name of the group
    that confers `is_staff`, not a boolean.

    Attributes:
        identity_key_claim: Name of the claim holding the IdP subject (AD-11).
            May be a dotted path into nested claims.
        group_claim: Name of the claim holding the caller's groups. May be a
            dotted path, which is what makes `realm_access.roles` expressible.
        staff_group: Name of the group that confers `is_staff` (AD-12).
        superuser_group: Name of the group that confers `is_superuser` (AD-12).

    """

    identity_key_claim: str
    group_claim: str
    staff_group: str
    superuser_group: str

    @property
    def is_configured(self) -> bool:
        """Report whether all four names were supplied by the environment.

        This is a plain predicate. The refusal to start on an unconfigured
        contract is Epic 4's, and it consumes this property; nothing here
        raises.

        Returns:
            True when every field is a non-empty string.

        """
        return all(
            (
                self.identity_key_claim,
                self.group_claim,
                self.staff_group,
                self.superuser_group,
            ),
        )


def load_claims_contract(env: environ.Env) -> ClaimsContract:
    """Read the claims contract from the environment.

    Reads exactly four variables, each defaulting to the empty string. There is
    no fallback value of any kind: an unset variable stays unset rather than
    acquiring a conventional name.

    Each value is stripped. A variable holding only whitespace -- a block scalar
    in a ConfigMap, a trailing space in a `.env` line -- is therefore read as
    unset rather than as a truthy name that matches nothing. Without this, a
    blank value would report `is_configured` True and then resolve no claim at
    all: a misconfiguration presenting as a permissions bug.

    Args:
        env: The `environ.Env` the settings module already holds. Passing it in
            rather than constructing one keeps a single `.env` read (FR-38).

    Returns:
        The contract as configured, which may be entirely unconfigured.

    """
    identity_key_claim, group_claim, staff_group, superuser_group = (
        env.str(name, default="").strip() for name in CLAIMS_ENVIRONMENT_VARIABLES
    )
    return ClaimsContract(
        identity_key_claim=identity_key_claim,
        group_claim=group_claim,
        staff_group=staff_group,
        superuser_group=superuser_group,
    )


def _resolve(claims: Mapping[str, Any], path: str) -> Any:
    """Resolve a claim name, walking a dotted path through nested mappings.

    The whole path is tried as a literal key first. Auth0 and Azure AD namespace
    their custom claims as URIs -- `https://example.com/roles`,
    `http://schemas.microsoft.com/ws/2008/06/identity/claims/role` -- which carry
    literal dots. Splitting those would make two of the taxonomies a component is
    most likely to meet unreachable by configuration, which is the "any IdP
    without a code change" promise failing silently as a 401. The literal read
    wins the tie because it is the exact key the operator configured.

    Args:
        claims: The decoded token claims.
        path: A claim name, optionally dotted (`realm_access.roles`).

    Returns:
        The value at `path`, or None when `path` is empty or any segment along
        the way is missing or is not a mapping.

    """
    if not path:
        return None
    if path in claims:
        return claims[path]
    current: Any = claims
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return None
        current = current[segment]
    return current


def read_group_claim(claims: Mapping[str, Any], path: str) -> list[str] | None:
    """Read the group claim at a dotted path.

    `groups`, `roles` and `realm_access.roles` are all expressible through this
    one function: only the configured `group_claim` differs.

    The absent case returns None and the present-but-empty case returns `[]`.
    AD-12 rests on that distinction -- an absent group claim is a 401, while a
    claim asserting no groups is an authenticated caller with no groups. The two
    must never be silently equivalent.

    Args:
        claims: The decoded token claims.
        path: The configured group-claim name, optionally dotted.

    Returns:
        The asserted groups as a list of names, or None when the claim is absent
        or malformed. A scalar is read as a single group. The rule is applied to
        the elements as well as to the container: a list holding anything that is
        not a usable name -- an object, a null, a boolean, a blank string --
        denies the whole claim rather than coercing it. Coercing would turn
        `[{"name": "admins"}]` into a group named `{'name': 'admins'}`, which
        matches no Django group, is not None, and so admits a caller the
        container-level rule would have refused.

    """
    value = _resolve(claims, path)
    if isinstance(value, str | int) and not isinstance(value, bool):
        name = _read_name(value)
        return None if name is None else [name]
    if isinstance(value, list | tuple):
        names = [_read_name(item) for item in value]
        return None if any(name is None for name in names) else [name for name in names if name is not None]
    return None


def _read_name(value: Any) -> str | None:
    """Read one claim value as a name.

    Args:
        value: A single value taken from a claim.

    Returns:
        The name as a stripped string, or None when the value is not a usable
        name. A non-boolean integer is stringified -- numeric subjects and
        numeric group ids both occur -- and everything else is unusable. `bool`
        is excluded explicitly because it is an `int` subclass and `True` is not
        an identity.

    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int):
        return str(value)
    return None


def read_identity_key(claims: Mapping[str, Any], path: str) -> str | None:
    """Read the identity-key claim at a dotted path.

    Uses the same walk as `read_group_claim`, so a nested identity claim needs
    no second mechanism.

    Args:
        claims: The decoded token claims.
        path: The configured identity-key claim name, optionally dotted.

    Returns:
        The identity key as a stripped string, or None when the claim is absent,
        blank, or is not a string or a non-boolean integer. A blank key is not an
        identity, and the same reading is applied to group names, so the two
        readers cannot disagree about what counts as a name.

    """
    return _read_name(_resolve(claims, path))
