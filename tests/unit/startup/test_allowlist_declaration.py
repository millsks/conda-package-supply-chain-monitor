"""The allowlist's shape: one declaration, closed by explicit key, and self-consistent.

FR-17's allowlist and AD-8's contributable surface are **one declaration** (AD-26),
which is a claim about structure rather than about any particular entry. These
cases assert the structure:

* the two halves cannot drift into contradiction, because every settings key the
  FR-17 rosters govern is a key AD-8 refuses a contribution to;
* the contributable surface is enumerated by explicit key and never by namespace;
* the route scopes declare exactly one prefix each, and the summary tuple is
  derived from them rather than respelled beside them;
* nothing else under `src/` declares any of these names.

`tests/unit/startup/test_authentication_allowlist.py` owns the other half -- what
the declaration says about the component's actual settings and routes. The split
is deliberate: a structural assertion still holds in a materialized combination
whose surface differs, while the behavioural ones are statements about this tree.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from config.local_dev.constants import LOCAL_SIGNIN_PATH_PREFIX
from config.startup import allowlist
from config.startup.allowlist import ALLOWED_API_AUTHENTICATION_CLASSES
from config.startup.allowlist import ALLOWED_AUTHENTICATION_BACKENDS
from config.startup.allowlist import ALLOWED_AUTHENTICATION_ROUTE_PREFIXES
from config.startup.allowlist import ALLOWED_AUTHENTICATION_ROUTE_SCOPES
from config.startup.allowlist import CONTRIBUTABLE_KEYS
from config.startup.allowlist import FORBIDDEN_CONTRIBUTABLE_KEYS
from config.startup.allowlist import GOVERNED_SETTING_KEYS
from config.startup.allowlist import AuthenticationRouteScope
from tests.conftest import valid_deployed_settings_namespace

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"

#: The module that is allowed to declare these names. Every other module under
#: `src/` that assigns one is a second declaration site (AD-1).
DECLARATION_SITE = SRC_ROOT / "config" / "startup" / "allowlist.py"

#: The names whose single declaration site this module polices. Read off the
#: module's own `__all__` would be circular -- a name dropped from `__all__`
#: would drop out of the check with it -- so they are listed.
DECLARED_NAMES = frozenset(
    {
        "ALLOWED_API_AUTHENTICATION_CLASSES",
        "ALLOWED_AUTHENTICATION_BACKENDS",
        "ALLOWED_AUTHENTICATION_ROUTE_PREFIXES",
        "ALLOWED_AUTHENTICATION_ROUTE_SCOPES",
        "CONTRIBUTABLE_KEYS",
        "FORBIDDEN_CONTRIBUTABLE_KEYS",
        "GOVERNED_SETTING_KEYS",
    }
)

#: AD-8's four global-default keys, verbatim. Written out rather than read from
#: the module so the case is a statement about the architecture decision rather
#: than a tautology about whatever the module currently holds.
AD_8_FORBIDDEN_KEYS = frozenset(
    {
        "AUTHENTICATION_BACKENDS",
        "DEFAULT_AUTHENTICATION_CLASSES",
        "DEFAULT_PERMISSION_CLASSES",
        "MIDDLEWARE",
    }
)


def _module_level_assignments(path: Path) -> set[str]:
    """Return the names a module assigns at module scope.

    Args:
        path: The module to read.

    Returns:
        Every name bound by a module-level assignment, annotated or not. Nested
        scopes are excluded on purpose: a local variable inside a function that
        happens to share a name is not a second declaration of anything.

    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


class TestTheTwoHalvesAreOneDeclaration:
    """AD-26: adding a credential path and adopting an app are checked by one mechanism."""

    def test_every_governed_key_is_refused_to_contributors(self) -> None:
        """The mechanical proof that the halves cannot contradict each other.

        A key whose contents FR-17 fixes *exactly* cannot also be a key an
        adopted app may contribute to: a contribution would be an entry FR-17
        never approved, so the two rules would disagree about the same settings
        key on the day the first app was adopted. Asserting the containment is
        what makes "one declaration" a property rather than a description of how
        the file happens to be laid out.
        """
        governed = set(GOVERNED_SETTING_KEYS.values())

        assert governed <= FORBIDDEN_CONTRIBUTABLE_KEYS, (
            f"these keys are governed by an FR-17 roster but are not refused to contributors: "
            f"{sorted(governed - FORBIDDEN_CONTRIBUTABLE_KEYS)}"
        )

    @pytest.mark.parametrize("roster_name", sorted(GOVERNED_SETTING_KEYS))
    def test_every_governed_roster_name_resolves_to_a_roster(self, roster_name: str) -> None:
        """A mapping key naming an attribute that is not there is a lie the gate should catch."""
        roster = getattr(allowlist, roster_name)

        assert isinstance(roster, frozenset)
        assert roster, f"{roster_name} is empty, so the key it governs would be asserted to hold nothing"
        assert all(isinstance(entry, str) for entry in roster)

    def test_the_rosters_hold_dotted_paths_rather_than_key_names(self) -> None:
        """The rosters hold *values*; the forbidden set holds *keys*. A collision means one is wrong.

        The two are different kinds of string and a member of one appearing in
        the other is a category error -- an allowlist entry that was actually a
        settings key, or a forbidden key that was actually a class path. Neither
        would fail any other case here, and both would read as deliberate.
        """
        values = ALLOWED_AUTHENTICATION_BACKENDS | ALLOWED_API_AUTHENTICATION_CLASSES

        assert not (values & FORBIDDEN_CONTRIBUTABLE_KEYS)
        assert not (values & CONTRIBUTABLE_KEYS)
        assert all("." in entry for entry in values), "an allowlisted class path with no dot is a key name"


class TestTheContributableSurfaceIsClosed:
    """AD-8: enumerated by explicit key, never by namespace."""

    def test_the_two_key_sets_are_disjoint(self) -> None:
        """A key that is both contributable and refused has no defined behaviour at all."""
        overlap = CONTRIBUTABLE_KEYS & FORBIDDEN_CONTRIBUTABLE_KEYS

        assert not overlap, f"these keys are both permitted and refused: {sorted(overlap)}"

    def test_the_forbidden_keys_are_the_four_the_decision_names(self) -> None:
        """Exact equality. AD-8 names four; a fifth added quietly is a narrowing nobody decided."""
        assert FORBIDDEN_CONTRIBUTABLE_KEYS == AD_8_FORBIDDEN_KEYS

    @pytest.mark.parametrize("key", sorted(CONTRIBUTABLE_KEYS))
    def test_no_contributable_entry_is_a_namespace_rather_than_a_key(self, key: str) -> None:
        """AD-8's own words: "by explicit key, never by namespace".

        A namespace is a rule that admits keys nobody has read, which is the
        thing a closed surface is closed against. The shapes refused here are the
        ones a namespace is actually written as: a dotted path, a trailing
        separator, or a glob.
        """
        assert key == key.upper(), f"{key!r} is not a settings key"
        assert "." not in key, f"{key!r} is a dotted namespace rather than a key"
        assert "*" not in key, f"{key!r} is a glob rather than a key"
        assert not key.endswith("_"), f"{key!r} is a prefix rather than a key"

    def test_the_navigation_registry_is_on_the_surface(self) -> None:
        """AD-8 revision 3 puts it there, and the reason is why it is not `MIDDLEWARE`.

        It confers presentation and never authorization. The case exists because
        the key is the one contributable thing rendered on every page, so it is
        the entry most likely to be removed by somebody applying the rule that
        refuses `MIDDLEWARE` without reading why that rule stops where it does.
        """
        assert "NAVIGATION_REGISTRY" in CONTRIBUTABLE_KEYS


class TestTheRouteScopes:
    """The scoping declaration: which routes the allowlist has authority over."""

    def test_every_scope_declares_exactly_one_prefix(self) -> None:
        """Enforced by `__post_init__`, asserted here against the declared records."""
        for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES:
            assert (scope.prefix is None) != (scope.prefix_setting is None), scope.key

    def test_a_scope_declaring_both_is_refused(self) -> None:
        """The invariant is enforced rather than documented, so the case constructs the violation."""
        with pytest.raises(ValueError, match="exactly one of prefix and prefix_setting"):
            AuthenticationRouteScope(
                key="both",
                permitted_view_packages=frozenset(),
                why="",
                prefix="both/",
                prefix_setting="ADMIN_URL",
            )

    def test_a_scope_declaring_neither_is_refused(self) -> None:
        """The other half. A record with no prefix would silently judge no routes at all."""
        with pytest.raises(ValueError, match="exactly one of prefix and prefix_setting"):
            AuthenticationRouteScope(key="neither", permitted_view_packages=frozenset(), why="")

    def test_the_scope_keys_are_unique(self) -> None:
        """Two records under one key make one of them unreachable by name."""
        keys = [scope.key for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES]

        assert len(keys) == len(set(keys))

    def test_the_literal_prefixes_are_derived_from_the_scopes(self) -> None:
        """`ALLOWED_AUTHENTICATION_ROUTE_PREFIXES` summarizes the scopes; it does not restate them.

        A hand-written summary is a second declaration that agrees on the day it
        is written. This asserts the derivation rather than the contents, so a
        scope added later appears here without anybody remembering to add it.
        """
        expected = tuple(
            scope.prefix + scope.suffix for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES if scope.prefix is not None
        )

        assert expected == ALLOWED_AUTHENTICATION_ROUTE_PREFIXES
        assert all(prefix.endswith("/") for prefix in ALLOWED_AUTHENTICATION_ROUTE_PREFIXES)

    def test_the_local_sign_in_prefix_is_imported_rather_than_respelled(self) -> None:
        """Object identity, which is what proves the constant was imported and not retyped.

        `config.local_dev.constants` declares the prefix once and says this
        allowlist is one of the two consumers it exists for. A string equal to it
        would pass an equality check and drift the first time the constant moved
        into `accelerator.toml`, which Epic 7 does.
        """
        scope = next(scope for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES if scope.key == "local-sign-in")

        assert scope.prefix is LOCAL_SIGNIN_PATH_PREFIX

    def test_the_reserved_scopes_permit_nothing(self) -> None:
        """A reserved prefix with one permitted package would be a hole with a comment over it."""
        reserved = {"local-sign-in", "token-issuance"}

        for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES:
            if scope.key in reserved:
                assert not scope.permitted_view_packages, scope.key

    @pytest.mark.parametrize(
        ("key", "expected"),
        [("admin-login", "somewhere-else/login/"), ("admin-password-change", "somewhere-else/password_change/")],
    )
    def test_the_admin_prefixes_are_read_from_a_setting(self, key: str, expected: str) -> None:
        """`production.py` takes the admin mount from `DJANGO_ADMIN_URL`, so a literal would be wrong.

        The credential routes beneath it are Django's own fixed names, so each
        scope is a parameterized base plus a fixed suffix. Resolved against a
        moved mount rather than the default one: `admin/` is what `base.py`
        happens to default to, and a case asserting it would pass just as well
        against a scope that ignored the setting entirely.
        """
        scope = next(scope for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES if scope.key == key)

        assert scope.prefix is None
        assert scope.prefix_setting == "ADMIN_URL"
        assert scope.resolve_prefix({"ADMIN_URL": "somewhere-else/"}) == expected

    def test_resolving_a_parameterized_prefix_without_its_setting_raises(self) -> None:
        """Raised rather than defaulted: a missing admin URL would narrow the scope to nothing."""
        scope = next(scope for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES if scope.key == "admin-login")

        with pytest.raises(KeyError):
            scope.resolve_prefix({})

    def test_the_admin_mount_as_a_whole_is_not_a_scope(self) -> None:
        """The deliberate narrowing, asserted so it is not quietly widened back.

        A scope over the bare `ADMIN_URL` would judge every installed app's
        `ModelAdmin` views and would break the build on the first adopted app --
        AC #2's "deleted within a week", one prefix down. Anyone who widens it
        should have to delete this case and read why it is here.
        """
        bare_admin = [
            scope.key
            for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES
            if scope.prefix_setting == "ADMIN_URL" and not scope.suffix
        ]

        assert bare_admin == []

    def test_every_scope_carries_its_reason(self) -> None:
        """The mirror Epic 7 writes into `accelerator.toml` carries the reason with the rule."""
        for scope in ALLOWED_AUTHENTICATION_ROUTE_SCOPES:
            assert scope.why.strip(), scope.key


class TestThereIsOneDeclarationSite:
    """AD-1, mechanically, until Epic 7's two-way reconciliation with the carrier exists."""

    def test_the_declaration_site_declares_every_name(self) -> None:
        """The other direction of the case below: the file is where the names actually are."""
        assert _module_level_assignments(DECLARATION_SITE) >= DECLARED_NAMES

    def test_no_other_module_under_src_declares_any_of_them(self) -> None:
        """A second module assigning one of these names is a second list, however it is spelled."""
        offenders = {
            str(path.relative_to(SRC_ROOT)): sorted(DECLARED_NAMES & _module_level_assignments(path))
            for path in sorted(SRC_ROOT.rglob("*.py"))
            if path != DECLARATION_SITE and DECLARED_NAMES & _module_level_assignments(path)
        }

        assert offenders == {}, f"these modules declare allowlist names of their own: {offenders}"


class TestTheSuitesOwnValidNamespaceAgreesWithTheDeclaration:
    """`tests.conftest.valid_deployed_settings_namespace` spells the approved surface too.

    It predates this module -- Story 4.2 needed a namespace every condition
    accepts before there was an allowlist to build one from -- and it hardcodes
    both rosters. Rather than derive it from the allowlist and lose the ordering
    that makes the DRF list realistic, the two are reconciled here in both
    directions, which is the same shape the rest of this package uses for a value
    that legitimately appears twice.
    """

    def test_the_namespaces_backends_are_the_allowlisted_ones(self) -> None:
        """Exactly, not as a subset: a namespace with fewer entries would accept a narrower tree."""
        namespace = valid_deployed_settings_namespace()

        assert set(namespace.AUTHENTICATION_BACKENDS) == ALLOWED_AUTHENTICATION_BACKENDS

    def test_the_namespaces_api_classes_are_the_allowlisted_ones(self) -> None:
        """Same, for DRF's defaults. Order is the namespace's own concern and is not asserted here."""
        namespace = valid_deployed_settings_namespace()

        assert set(namespace.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]) == ALLOWED_API_AUTHENTICATION_CLASSES
