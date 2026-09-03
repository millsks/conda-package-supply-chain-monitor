"""Declaration-shape and claims-construction assertions for the local personas.

No database, no network, no filesystem: everything here operates on the frozen
dataclasses and on `django.conf.settings`. The behavioural half -- that the
declarations actually become users, with those memberships -- is in
`tests/integration/test_local_dev_seeding.py`.

Two claims are separated on purpose. What the *declarations* say is AC #1's
"each declares its groups, its profile fields, and the identity-key claim the
mapper resolves by", checked at the only place a hardcoded group name could
enter. What `build_claims` *produces* is the round trip: every payload it builds
is asserted through Story 2.2's own readers rather than by inspecting keys the
test chose, because a payload that only this file can read would satisfy an
inspection and still be unreadable by the mapper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.authorization.claims import ClaimsContract
from config.authorization.claims import read_group_claim
from config.authorization.claims import read_identity_key
from config.authorization.mapper import EMAIL_CLAIM
from config.authorization.mapper import NAME_CLAIM
from config.authorization.mapper import USERNAME_CLAIM
from config.local_dev.personas import DESIGNATED_STAFF
from config.local_dev.personas import DESIGNATED_SUPERUSER
from config.local_dev.personas import PERSONAS
from config.local_dev.personas import Persona
from config.local_dev.personas import UnknownPersonaError
from config.local_dev.personas import build_claims
from config.local_dev.personas import get_persona
from config.local_dev.personas import persona_keys
from config.local_dev.personas import resolve_groups

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

# The minimum AC #1 asks for: two personas with different memberships, one of
# them carrying the designated staff group.
MINIMUM_PERSONAS = 2

# Names that appear nowhere in `src/`, so an assertion that the payload moved
# with the configuration cannot be satisfied by a coincidence.
IDENTITY_CLAIM = "urn:example:principal-id"
STAFF_GROUP = "shipping-desk-operators"
SUPERUSER_GROUP = "shipping-desk-owners"

# The three taxonomies FR-10 promises are expressible by configuration alone.
# The third is the one that has to nest.
GROUP_CLAIM_TAXONOMIES = ("groups", "roles", "realm_access.roles")

# Auth0 and Azure AD namespace their custom claims as URIs, which carry literal
# dots. Included because it is the shape most likely to break a dotted writer.
URI_GROUP_CLAIM = "https://example.com/roles"

# The registered claims of the programmatic flow. Story 3.5's token minting adds
# them; an interactive persona sign-in is itself the epoch and carries none.
REGISTERED_CLAIMS = ("jti", "iss", "aud", "exp")


def _contract(*, identity_key_claim: str = IDENTITY_CLAIM, group_claim: str = "groups") -> ClaimsContract:
    """Build a claims contract pointed at deliberately unconventional names."""
    return ClaimsContract(
        identity_key_claim=identity_key_claim,
        group_claim=group_claim,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )


@pytest.fixture(autouse=True)
def _configured(settings: SettingsWrapper) -> None:
    """Point the claims contract away from every name spelled in `src/`."""
    settings.CLAIMS_CONTRACT = _contract()


def test_at_least_two_personas_are_declared() -> None:
    """AC #1: the declarations exist and there are enough of them to differ."""
    assert len(PERSONAS) >= MINIMUM_PERSONAS


def test_the_declared_memberships_genuinely_differ() -> None:
    """AC #1: two personas that assert the same groups demonstrate nothing.

    The whole point of the pair is that the same page admits one and refuses the
    other, and that the difference is produced by the mapper. Identical
    memberships would make Story 3.4's divergence unprovable while every test
    here still passed.
    """
    declared = {persona.key: frozenset(persona.groups) for persona in PERSONAS}
    assert len(set(declared.values())) == len(declared), declared


def test_exactly_one_persona_carries_the_designated_staff_sentinel() -> None:
    """AC #1: one persona carries the designated staff group, and only one.

    One, because a second would make the read-only persona's refusal in Story
    3.4 depend on which persona the test happened to pick.
    """
    carriers = [persona.key for persona in PERSONAS if DESIGNATED_STAFF in persona.groups]
    assert carriers == ["staff"]


def test_one_persona_carries_neither_sentinel() -> None:
    """AC #1: a read-only persona exists, holding no designated group at all."""
    plain = [
        persona.key
        for persona in PERSONAS
        if DESIGNATED_STAFF not in persona.groups and DESIGNATED_SUPERUSER not in persona.groups
    ]
    assert plain, [persona.key for persona in PERSONAS]


def test_no_persona_hardcodes_a_group_name() -> None:
    """Every declared group is a sentinel, so no persona pins a taxonomy.

    A literal `platform-staff` here would be silently wrong in every component
    that configures a different group name -- the coupling FR-10 made the
    contract configuration to remove.
    """
    sentinels = {DESIGNATED_STAFF, DESIGNATED_SUPERUSER}
    declared = {name for persona in PERSONAS for name in persona.groups}
    assert declared <= sentinels, sorted(declared - sentinels)


@pytest.mark.parametrize("field", ["key", "subject", "username", "email", "name"])
def test_every_persona_declares_the_field(field: str) -> None:
    """AC #1: every persona declares its profile fields and its identity key."""
    missing = [persona.key for persona in PERSONAS if not getattr(persona, field)]
    assert not missing, missing


@pytest.mark.parametrize("field", ["key", "subject", "username", "email"])
def test_the_personas_are_distinct_in_the_field(field: str) -> None:
    """Two personas sharing a subject would be one user, which defeats the pair.

    `username` and `email` are attributes rather than identities, but a shared
    username would collide under AD-12 and one persona would end up renamed --
    a difference nobody declared.
    """
    values = [getattr(persona, field) for persona in PERSONAS]
    assert len(set(values)) == len(values), values


def test_persona_keys_names_every_declaration() -> None:
    """`persona_keys` is what a URL and a task argument are validated against."""
    assert persona_keys() == tuple(persona.key for persona in PERSONAS)


def test_get_persona_returns_the_declaration() -> None:
    """The key is a lookup slug, and it resolves to the declaration it names."""
    assert get_persona("staff").key == "staff"


def test_get_persona_refuses_an_unknown_key() -> None:
    """An unrecognised key is a refusal, never a fallback to the first persona.

    Signing in under a misspelled name and silently getting the staff persona is
    the worst answer available.
    """
    with pytest.raises(UnknownPersonaError):
        get_persona("no-such-persona")


def test_resolve_groups_substitutes_the_configured_names(settings: SettingsWrapper) -> None:
    """AC #1: the designated groups come from the contract, not from this file."""
    settings.CLAIMS_CONTRACT = _contract()
    both = Persona(
        key="both",
        subject="s",
        username="u",
        email="e@localhost.invalid",
        name="n",
        groups=(DESIGNATED_STAFF, DESIGNATED_SUPERUSER),
    )
    assert resolve_groups(both) == (STAFF_GROUP, SUPERUSER_GROUP)


def test_resolve_groups_follows_a_reconfigured_contract(settings: SettingsWrapper) -> None:
    """Change the contract and the personas assert the new names, with no edit."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim="groups",
        staff_group="another-staff-group",
        superuser_group="another-superuser-group",
    )
    assert resolve_groups(get_persona("staff")) == ("another-staff-group",)


def test_resolve_groups_deduplicates_one_group_serving_both_roles(settings: SettingsWrapper) -> None:
    """An operator may point both designated variables at one group.

    Nothing forbids it -- a small deployment where every administrator is also
    staff -- and a persona carrying both sentinels would then assert it twice.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim="groups",
        staff_group="everyone-in-charge",
        superuser_group="everyone-in-charge",
    )
    both = Persona(
        key="both",
        subject="s",
        username="u",
        email="e@localhost.invalid",
        name="n",
        groups=(DESIGNATED_STAFF, DESIGNATED_SUPERUSER),
    )
    assert resolve_groups(both) == ("everyone-in-charge",)


def test_resolve_groups_passes_a_literal_group_through(settings: SettingsWrapper) -> None:
    """A persona may name an ordinary, non-designated group and keep it verbatim."""
    settings.CLAIMS_CONTRACT = _contract()
    ordinary = Persona(
        key="ordinary",
        subject="s",
        username="u",
        email="e@localhost.invalid",
        name="n",
        groups=("manifest-readers",),
    )
    assert resolve_groups(ordinary) == ("manifest-readers",)


def test_build_claims_carries_the_profile_fields_under_the_oidc_names() -> None:
    """The three attribute claims are the ones `_attributes_from_claims` reads.

    They are not configurable and deliberately so: an attribute decides nothing
    about who is allowed to do what.
    """
    persona = get_persona("staff")
    claims = build_claims(persona)
    assert claims[USERNAME_CLAIM] == persona.username
    assert claims[EMAIL_CLAIM] == persona.email
    assert claims[NAME_CLAIM] == persona.name


def test_build_claims_keys_the_identity_by_the_configured_claim_name() -> None:
    """AC #1: the identity key sits where the *contract* says, not at `sub`."""
    persona = get_persona("staff")
    claims = build_claims(persona)
    assert read_identity_key(claims, IDENTITY_CLAIM) == persona.subject
    assert "sub" not in claims


def test_the_payload_moves_when_the_contract_moves(settings: SettingsWrapper) -> None:
    """Reconfigure the claim names and the keys move with them.

    This is the assertion that distinguishes "keyed by the configured name" from
    "keyed by a name that happens to match the fixture".
    """
    settings.CLAIMS_CONTRACT = _contract(identity_key_claim="oid", group_claim="roles")
    claims = build_claims(get_persona("staff"))
    assert set(claims) == {"oid", "roles", USERNAME_CLAIM, EMAIL_CLAIM, NAME_CLAIM}
    assert IDENTITY_CLAIM not in claims


@pytest.mark.parametrize("group_claim", [*GROUP_CLAIM_TAXONOMIES, URI_GROUP_CLAIM])
def test_the_group_claim_round_trips_through_the_reader(
    settings: SettingsWrapper,
    group_claim: str,
) -> None:
    """Every configured taxonomy is readable back by Story 2.2's own reader.

    Asserted through `read_group_claim` rather than by looking the key up here:
    a payload only this test can read would pass an inspection and still be
    unreadable by the mapper, which is the whole failure the round trip exists
    to rule out.
    """
    settings.CLAIMS_CONTRACT = _contract(group_claim=group_claim)
    claims = build_claims(get_persona("staff"))
    assert read_group_claim(claims, group_claim) == [STAFF_GROUP]


@pytest.mark.parametrize("identity_claim", ["sub", "realm_access.principal", URI_GROUP_CLAIM])
def test_the_identity_claim_round_trips_through_the_reader(
    settings: SettingsWrapper,
    identity_claim: str,
) -> None:
    """A nested identity claim needs no second mechanism, on either side."""
    settings.CLAIMS_CONTRACT = _contract(identity_key_claim=identity_claim)
    persona = get_persona("reader")
    claims = build_claims(persona)
    assert read_identity_key(claims, identity_claim) == persona.subject


def test_a_dotted_group_claim_produces_a_nested_payload(settings: SettingsWrapper) -> None:
    """`realm_access.roles` nests, because that is the shape Keycloak emits.

    The reader would in fact also accept a flat key literally named
    `"realm_access.roles"` -- `_resolve` tries the whole path as a literal key
    first, for the sake of URI-shaped claim names. So the round trip alone does
    not pin the shape, and shape is the point: a flat write would round-trip and
    still be a payload no IdP produces, leaving the local paths exercising a
    nesting the deployed path never sees.
    """
    settings.CLAIMS_CONTRACT = _contract(group_claim="realm_access.roles")
    claims = build_claims(get_persona("staff"))
    assert claims["realm_access"] == {"roles": [STAFF_GROUP]}
    assert "realm_access.roles" not in claims


def test_the_read_only_persona_asserts_a_present_but_empty_group_claim() -> None:
    """An empty membership is an assertion of no groups, never an absent claim.

    AD-12 makes the difference a 200 versus a 401: an absent group claim is
    refused, while a claim asserting no groups is an authenticated caller with no
    groups. A read-only persona is the second thing.
    """
    claims = build_claims(get_persona("reader"))
    assert read_group_claim(claims, "groups") == []


@pytest.mark.parametrize("claim", REGISTERED_CLAIMS)
def test_build_claims_adds_no_registered_claim(claim: str) -> None:
    """No `jti`, `iss`, `aud` or `exp`: an interactive sign-in is itself the epoch.

    Story 3.5's token minting adds them. A `jti` invented here would either be
    discarded by `sync_for_interactive`, which does not read one, or burn a real
    epoch row on a synthetic credential.
    """
    for persona in PERSONAS:
        assert claim not in build_claims(persona)


def test_build_claims_writes_nothing_for_an_unconfigured_claim_name(settings: SettingsWrapper) -> None:
    """An unconfigured contract writes no key, exactly as the reader reads none.

    The refusal to *start* on an unconfigured contract is Epic 4's; what this
    pins is that nothing here invents a conventional name to stand in for the
    missing one, which would turn a missing configuration into a plausible
    looking wrong one.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="",
        group_claim="",
        staff_group="",
        superuser_group="",
    )
    claims = build_claims(get_persona("staff"))
    assert set(claims) == {USERNAME_CLAIM, EMAIL_CLAIM, NAME_CLAIM}


def test_overlapping_claim_names_are_refused(settings: SettingsWrapper) -> None:
    """Two claim names that cannot share a payload are a refusal, not an overwrite.

    `sub` and `sub.roles` ask for the identity key to be both a string and a
    mapping. Overwriting would drop whichever was written first, and a payload
    silently missing its identity key presents as an authentication bug.
    """
    settings.CLAIMS_CONTRACT = _contract(identity_key_claim="sub", group_claim="sub.roles")
    with pytest.raises(ImproperlyConfigured):
        build_claims(get_persona("staff"))


def test_the_payload_is_a_plain_mutable_mapping() -> None:
    """Story 3.5 mints a token from this payload, so it has to be serializable.

    Nothing exotic may creep in: a sentinel object or a frozen dataclass would
    read back fine here and fail at `json.dumps` in the story that signs it.
    """
    claims: dict[str, Any] = build_claims(get_persona("staff"))
    assert all(isinstance(key, str) for key in claims)
    assert all(isinstance(value, str | list | dict) for value in claims.values())
