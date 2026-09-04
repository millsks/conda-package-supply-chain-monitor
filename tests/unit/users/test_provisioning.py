"""Declaration-shape and authorship assertions for group provisioning.

No database is touched here. Two different kinds of claim live in this module,
and they are separated on purpose:

* what the permission declaration *says* -- that it is keyed by role slot and
  carries no group name, which is AC #1's "seeded from the claims contract
  rather than from hardcoded names" checked at the only place a hardcoded name
  could enter;
* who *writes* groups -- AC #3's "no path creates groups of its own", which is a
  property of the source tree rather than of any single run, and so is asserted
  against the parsed source.

The behavioural half -- idempotence, the rows that actually appear, the
permissions actually attached -- is in `tests/integration/users/test_provisioning.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings

from config.authorization.claims import ClaimsContract
from django_service.users.provisioning import DESIGNATED_GROUP_PERMISSIONS
from django_service.users.provisioning import STAFF_ROLE
from django_service.users.provisioning import SUPERUSER_ROLE
from django_service.users.provisioning import ProvisionResult
from django_service.users.provisioning import provision_designated_groups
from django_service.users.provisioning import provision_groups
from tests.group_writers import group_creation_verbs

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
PROVISIONING_MODULE = SRC_ROOT / "django_service" / "users" / "provisioning.py"

# The two role slots, and the whole set of them. Written out rather than derived
# from the module under test, which would make the assertion agree with whatever
# it found.
ROLE_SLOTS = frozenset({"staff", "superuser"})


def _source_modules() -> list[Path]:
    """Return every Python module under `src/`, migrations included.

    Migrations are not excluded. A migration that creates groups inline is
    exactly the duplication AD-27 forbids -- it is the shape the rule was
    written against -- so exempting them would leave the scan blind to the one
    place the mistake is most likely to be made.
    """
    return sorted(SRC_ROOT.rglob("*.py"))


def test_the_permission_declaration_is_keyed_by_role_slot() -> None:
    """AC #1: the declaration carries slots, and the names come from the contract.

    Keying by group name would put a name in the source, which is the thing the
    contract exists to keep out of it: two components pointed at different IdPs
    share this file and share nothing about what their groups are called.
    """
    assert set(DESIGNATED_GROUP_PERMISSIONS) == ROLE_SLOTS
    assert STAFF_ROLE in DESIGNATED_GROUP_PERMISSIONS
    assert SUPERUSER_ROLE in DESIGNATED_GROUP_PERMISSIONS


def test_the_declaration_names_no_group() -> None:
    """AC #1: no configured group name appears anywhere in the module's source.

    Checked against the source text rather than against the declaration alone,
    so a name smuggled in as a default argument, a fallback or a comparison is
    caught as well. The names are the ones the suite is configured with, which
    are arbitrary as far as this module is concerned -- that is the point.
    """
    source = PROVISIONING_MODULE.read_text(encoding="utf-8")
    contract = settings.CLAIMS_CONTRACT

    for name in (contract.staff_group, contract.superuser_group):
        assert name not in source, f"the provisioning module hardcodes the configured group name {name!r}"


def test_the_staff_slot_grants_only_what_the_admin_index_needs() -> None:
    """AC #1: a minimal, declared grant rather than an open-ended one.

    Pinned exactly. A permission added here is a widening of what every staff
    member in every component built from this accelerator can do, which is a
    decision rather than a tidy-up.
    """
    assert DESIGNATED_GROUP_PERMISSIONS[STAFF_ROLE] == ("users.view_user", "users.change_user")


def test_the_superuser_slot_grants_nothing() -> None:
    """`ModelBackend.has_perm` short-circuits on `is_superuser`.

    Anything attached to the superuser group is therefore never consulted, but
    would still be maintained and inherited from. Emptiness is the decision, so
    it is asserted rather than left to be re-derived.
    """
    assert DESIGNATED_GROUP_PERMISSIONS[SUPERUSER_ROLE] == ()


@pytest.mark.parametrize("codenames", list(DESIGNATED_GROUP_PERMISSIONS.values()), ids=str)
def test_every_declared_permission_is_an_app_label_and_a_codename(codenames: tuple[str, ...]) -> None:
    """The strings are resolved by splitting on a dot, so a bare codename resolves to nothing.

    That failure is logged and skipped rather than raised, which is correct for a
    permission an app has not created yet and useless as a signal about a typo
    here. The shape is checked at the declaration instead.
    """
    for label in codenames:
        app_label, separator, codename = label.partition(".")
        assert separator == ".", f"{label!r} is not app_label.codename"
        assert app_label, f"{label!r} names no app"
        assert codename, f"{label!r} names no codename"


def test_an_unconfigured_contract_provisions_nothing_and_raises_nothing(settings: SettingsWrapper) -> None:
    """AC #2's neighbour: bring-up must stay usable before a contract exists.

    The refusal to start on an unconfigured contract belongs at startup, where a
    locality signal exists to gate it. Raising here would fire inside `migrate`
    instead, on a fresh checkout, before anyone has a contract to supply -- and
    the database would be left mid-migration by a configuration mistake.

    This reaches no database precisely because it returns before it touches a
    model registry, which is what makes it a unit test.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="",
        group_claim="",
        staff_group="",
        superuser_group="",
    )

    result = provision_designated_groups()

    assert result == ProvisionResult()
    assert result.created == ()
    assert result.existing == ()
    assert result.permissions_attached == 0


def test_provisioning_no_groups_creates_nothing_and_raises_nothing() -> None:
    """The seam's empty case, which is what makes the unconfigured path safe.

    `provision_designated_groups` and the product's role-group migration both
    return an empty mapping when their contract is unconfigured, and both hand it
    straight here rather than branching around the call. Reaching no database is
    the assertion: the loop never runs, so `get_or_create` is never reached, and
    a mapping that names nothing cannot create a `Group` with an empty name.

    This is a unit test for exactly that reason -- it issues no query, which a
    non-empty mapping would.
    """
    result = provision_groups({})

    assert result == ProvisionResult()
    assert result.created == ()
    assert result.existing == ()
    assert result.permissions_attached == 0


def test_the_scan_finds_source_modules_to_check() -> None:
    """The two scans below mean nothing if the glob resolves to nothing."""
    modules = _source_modules()
    assert PROVISIONING_MODULE in modules
    assert len(modules) > 1, f"expected the source tree to be discoverable under {SRC_ROOT}, found {modules}"


def test_the_provisioning_module_is_the_only_writer_of_groups() -> None:
    """AC #3: no path creates groups of its own.

    The property is about authorship, not about any one run: a second call site
    is wrong the moment it is written, whether or not a test ever executes it.
    Story 3.3's persona seeding and Epic 8's smoke check are the callers this
    protects -- each will need these groups, and each reimplementing them
    slightly differently is how the bootstrap deadlock becomes invisible to the
    harness again.
    """
    writers = {path: verbs for path in _source_modules() if (verbs := group_creation_verbs(path))}

    assert set(writers) == {PROVISIONING_MODULE}, (
        f"groups are created outside the one provisioning mechanism: {sorted(str(path) for path in writers)}"
    )


def test_the_one_writer_creates_groups_idempotently() -> None:
    """AC #2: idempotence is structural rather than a re-run guard.

    `get_or_create` cannot duplicate a row; a plain `create` on a second run
    would either duplicate or raise, and a guard written around it would be one
    more thing to keep true. Asserted at the call site so the guarantee survives
    a rewrite of the surrounding code.

    It doubles as the non-vacuity check for the scan above: a detector that
    matched nothing anywhere would report a single writer just as happily.
    """
    assert group_creation_verbs(PROVISIONING_MODULE) == {"get_or_create"}
