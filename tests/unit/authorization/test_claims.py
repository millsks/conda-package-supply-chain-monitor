"""Tests for the claims contract.

Everything here is pure: mappings in, names out. No database, no network, no
filesystem, and no read of the real environment -- `environ.Env` instances are
constructed in-test and `monkeypatch` owns every variable that is set.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import environ
import pytest
from django.conf import settings

from config.authorization.claims import CLAIMS_ENVIRONMENT_VARIABLES
from config.authorization.claims import ClaimsContract
from config.authorization.claims import load_claims_contract
from config.authorization.claims import read_group_claim
from config.authorization.claims import read_identity_key

VARIABLE_TO_FIELD = {
    "COMPONENT_IDENTITY_CLAIM": "identity_key_claim",
    "COMPONENT_GROUP_CLAIM": "group_claim",
    "COMPONENT_STAFF_GROUP": "staff_group",
    "COMPONENT_SUPERUSER_GROUP": "superuser_group",
}
CONTRACT_VARIABLES = tuple(VARIABLE_TO_FIELD)

# The conventional names that must never appear unless the environment said so.
CONVENTIONAL_NAMES = ("sub", "groups", "roles")


@pytest.fixture
def empty_env(monkeypatch: pytest.MonkeyPatch) -> environ.Env:
    """An `environ.Env` with none of the four contract variables set."""
    for name in CONTRACT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return environ.Env()


# ---------------------------------------------------------------------------
# AC #1 -- each of the four names is read from the environment, independently.
# ---------------------------------------------------------------------------


def test_all_four_names_are_read_from_the_environment(
    empty_env: environ.Env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPONENT_IDENTITY_CLAIM", "oid")
    monkeypatch.setenv("COMPONENT_GROUP_CLAIM", "realm_access.roles")
    monkeypatch.setenv("COMPONENT_STAFF_GROUP", "ops-staff")
    monkeypatch.setenv("COMPONENT_SUPERUSER_GROUP", "ops-admin")

    contract = load_claims_contract(empty_env)

    assert contract.identity_key_claim == "oid"
    assert contract.group_claim == "realm_access.roles"
    assert contract.staff_group == "ops-staff"
    assert contract.superuser_group == "ops-admin"
    assert contract.is_configured is True


@pytest.mark.parametrize("variable", CONTRACT_VARIABLES)
def test_each_variable_lands_on_its_own_field(
    empty_env: environ.Env,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    """Each variable is independently settable and reaches exactly one field."""
    monkeypatch.setenv(variable, "only-this-one")

    contract = load_claims_contract(empty_env)

    assert getattr(contract, VARIABLE_TO_FIELD[variable]) == "only-this-one"
    assert all(getattr(contract, field) == "" for name, field in VARIABLE_TO_FIELD.items() if name != variable)
    # One field set is not four: the contract is still unconfigured.
    assert contract.is_configured is False


def test_the_contract_is_frozen() -> None:
    """A contract read once at settings time is not rewritable at runtime."""
    contract = ClaimsContract(
        identity_key_claim="sub",
        group_claim="groups",
        staff_group="staff",
        superuser_group="admin",
    )
    with pytest.raises(AttributeError):
        contract.group_claim = "roles"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC #2 -- differing IdP taxonomies, one code path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("group_claim", "claims"),
    [
        ("groups", {"groups": ["a"]}),
        ("roles", {"roles": ["a"]}),
        ("realm_access.roles", {"realm_access": {"roles": ["a"]}}),
    ],
)
def test_three_taxonomies_resolve_identically(
    group_claim: str,
    claims: dict[str, Any],
) -> None:
    """Only the configured name differs; the code that reads it does not."""
    assert read_group_claim(claims, group_claim) == ["a"]


def test_a_deeply_nested_group_claim_resolves() -> None:
    claims = {"resource_access": {"component": {"roles": ["a", "b"]}}}
    assert read_group_claim(claims, "resource_access.component.roles") == ["a", "b"]


def test_group_members_are_returned_as_strings() -> None:
    assert read_group_claim({"groups": [1, "b"]}, "groups") == ["1", "b"]


def test_a_scalar_group_claim_reads_as_a_single_group() -> None:
    assert read_group_claim({"groups": "a"}, "groups") == ["a"]


def test_a_scalar_numeric_group_claim_reads_the_same_as_a_numeric_member() -> None:
    """The scalar and single-element-list forms of one numeric id agree."""
    assert read_group_claim({"groups": 42}, "groups") == ["42"]
    assert read_group_claim({"groups": [42]}, "groups") == ["42"]


@pytest.mark.parametrize(
    "path",
    [
        "https://example.com/roles",
        "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
    ],
)
def test_a_namespaced_claim_name_is_read_as_a_literal_key(path: str) -> None:
    """Auth0 and Azure AD namespace claims as URIs, which carry literal dots.

    Splitting those on `.` would make the taxonomies a component is most likely
    to meet unreachable by configuration -- every token a 401, while the contract
    reports itself configured.
    """
    assert read_group_claim({path: ["a"]}, path) == ["a"]
    assert read_identity_key({path: "abc"}, path) == "abc"


def test_a_literal_key_wins_over_the_dotted_walk() -> None:
    """The exact key the operator configured is the one that is read."""
    claims = {"realm_access.roles": ["literal"], "realm_access": {"roles": ["nested"]}}
    assert read_group_claim(claims, "realm_access.roles") == ["literal"]


# ---------------------------------------------------------------------------
# AD-12 -- absent is not empty.
# ---------------------------------------------------------------------------


def test_a_missing_group_claim_is_none() -> None:
    assert read_group_claim({"sub": "s"}, "groups") is None


def test_a_missing_intermediate_segment_is_none() -> None:
    assert read_group_claim({"groups": ["a"]}, "realm_access.roles") is None


def test_a_non_mapping_intermediate_segment_is_none() -> None:
    assert read_group_claim({"realm_access": "opaque"}, "realm_access.roles") is None


def test_an_empty_path_is_none() -> None:
    """An unconfigured group claim reads as absent, never as zero groups."""
    assert read_group_claim({"groups": ["a"]}, "") is None


def test_a_malformed_group_claim_is_none() -> None:
    """A shape that cannot be a group list denies rather than admits."""
    assert read_group_claim({"groups": {"a": 1}}, "groups") is None


@pytest.mark.parametrize(
    "value",
    [
        [{"name": "admins"}],
        [None],
        [True],
        ["a", {"name": "admins"}],
        ["a", ""],
        ["a", "   "],
        "",
        "   ",
        True,
        None,
    ],
    ids=[
        "object-member",
        "null-member",
        "boolean-member",
        "one-bad-member-among-good",
        "blank-member",
        "whitespace-member",
        "empty-scalar",
        "whitespace-scalar",
        "boolean-scalar",
        "null-scalar",
    ],
)
def test_an_unusable_group_member_denies_the_whole_claim(value: Any) -> None:
    """The malformed rule applies to the members, not only to the container.

    Coercing would turn `[{"name": "admins"}]` into a group named
    `{'name': 'admins'}`: not None, so not a 401, and matching no Django group,
    so an authenticated caller with no privileges where a refusal was owed.
    """
    assert read_group_claim({"groups": value}, "groups") is None


def test_a_present_but_empty_group_claim_is_an_empty_list() -> None:
    """Present-and-empty is `[]`, never None: Story 2.5's 401 rule rests on it."""
    result = read_group_claim({"groups": []}, "groups")
    assert result == []
    assert result is not None


# ---------------------------------------------------------------------------
# The identity key, over the same walk.
# ---------------------------------------------------------------------------


def test_the_identity_key_reads_from_a_flat_claim() -> None:
    assert read_identity_key({"sub": "abc"}, "sub") == "abc"


def test_the_identity_key_reads_from_a_nested_claim() -> None:
    assert read_identity_key({"token": {"oid": "abc"}}, "token.oid") == "abc"


def test_a_numeric_identity_key_is_stringified() -> None:
    assert read_identity_key({"sub": 42}, "sub") == "42"


@pytest.mark.parametrize(
    ("claims", "path"),
    [
        ({"sub": "abc"}, "oid"),
        ({"sub": "abc"}, ""),
        ({"sub": ""}, "sub"),
        ({"sub": "   "}, "sub"),
        ({"sub": None}, "sub"),
        ({"sub": True}, "sub"),
        ({"sub": ["abc"]}, "sub"),
        ({"token": "opaque"}, "token.oid"),
    ],
)
def test_an_unusable_identity_key_is_none(claims: dict[str, Any], path: str) -> None:
    assert read_identity_key(claims, path) is None


# ---------------------------------------------------------------------------
# AC #3 -- nothing is defaulted in the absence of configuration.
# ---------------------------------------------------------------------------


def test_an_empty_environment_yields_four_empty_strings(empty_env: environ.Env) -> None:
    contract = load_claims_contract(empty_env)

    assert contract.identity_key_claim == ""
    assert contract.group_claim == ""
    assert contract.staff_group == ""
    assert contract.superuser_group == ""
    assert contract.is_configured is False


def test_no_conventional_name_is_defaulted(empty_env: environ.Env) -> None:
    """`sub`, `groups` and `roles` are never supplied on the environment's behalf."""
    contract = load_claims_contract(empty_env)

    for field in (
        contract.identity_key_claim,
        contract.group_claim,
        contract.staff_group,
        contract.superuser_group,
    ):
        assert field not in CONVENTIONAL_NAMES


def test_conventional_names_still_apply_when_the_environment_says_so(
    empty_env: environ.Env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The names are not forbidden -- only never assumed."""
    monkeypatch.setenv("COMPONENT_IDENTITY_CLAIM", "sub")
    monkeypatch.setenv("COMPONENT_GROUP_CLAIM", "groups")

    contract = load_claims_contract(empty_env)

    assert contract.identity_key_claim == "sub"
    assert contract.group_claim == "groups"


@pytest.mark.parametrize(
    "variables",
    [
        ("COMPONENT_IDENTITY_CLAIM",),
        ("COMPONENT_IDENTITY_CLAIM", "COMPONENT_GROUP_CLAIM"),
        (
            "COMPONENT_IDENTITY_CLAIM",
            "COMPONENT_GROUP_CLAIM",
            "COMPONENT_STAFF_GROUP",
        ),
    ],
)
def test_a_partial_contract_is_not_configured(
    empty_env: environ.Env,
    monkeypatch: pytest.MonkeyPatch,
    variables: tuple[str, ...],
) -> None:
    for variable in variables:
        monkeypatch.setenv(variable, "x")

    assert load_claims_contract(empty_env).is_configured is False


def test_loading_an_unconfigured_contract_does_not_raise(empty_env: environ.Env) -> None:
    """The refusal is Epic 4's. Reading the contract never raises here."""
    assert load_claims_contract(empty_env).is_configured is False


@pytest.mark.parametrize("blank", ["   ", "\t", "\n", " \n "])
def test_a_blank_variable_reads_as_unset(
    empty_env: environ.Env,
    monkeypatch: pytest.MonkeyPatch,
    blank: str,
) -> None:
    """Whitespace is not a claim name, and `is_configured` must not think it is.

    A block scalar in a ConfigMap or a trailing space in a `.env` line would
    otherwise report a configured contract that resolves nothing -- the
    misconfiguration-as-permissions-bug AD-12 exists to prevent.
    """
    for variable in CONTRACT_VARIABLES:
        monkeypatch.setenv(variable, blank)

    contract = load_claims_contract(empty_env)

    assert contract.is_configured is False
    assert contract.identity_key_claim == ""
    assert contract.group_claim == ""


def test_surrounding_whitespace_is_stripped_from_a_real_name(
    empty_env: environ.Env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPONENT_GROUP_CLAIM", "  realm_access.roles \n")

    assert load_claims_contract(empty_env).group_claim == "realm_access.roles"


# ---------------------------------------------------------------------------
# The declared surface: the names read, the names documented, the names wired.
# ---------------------------------------------------------------------------


def test_the_declared_variables_are_the_variables_read() -> None:
    """`CLAIMS_ENVIRONMENT_VARIABLES` is not a second, drifting list."""
    assert set(CLAIMS_ENVIRONMENT_VARIABLES) == set(VARIABLE_TO_FIELD)


def test_the_documented_variables_are_the_variables_read() -> None:
    """`docs/authentication.md` is the only operator-facing home for these names.

    With no `.env.example` in the tree, a rename in `claims.py` would otherwise
    leave the published documentation instructing operators to set a variable
    nothing reads.
    """
    doc = Path(settings.BASE_DIR) / "docs" / "authentication.md"
    documented = set(re.findall(r"COMPONENT_[A-Z_]+", doc.read_text(encoding="utf-8")))

    assert documented == set(CLAIMS_ENVIRONMENT_VARIABLES)


def test_the_active_settings_carry_a_configured_contract() -> None:
    """The suite runs against the fixture in `config/settings/test.py`.

    Pinned so the override cannot be deleted or drift back to whatever
    `COMPONENT_` variables a developer's shell happens to hold.
    """
    assert (
        ClaimsContract(
            identity_key_claim="sub",
            group_claim="groups",
            staff_group="platform-staff",
            superuser_group="platform-superuser",
        )
        == settings.CLAIMS_CONTRACT
    )
