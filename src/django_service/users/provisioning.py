"""The one mechanism that creates the designated `Group` rows.

AD-27 exists to prevent a specific deadlock: a deployed component whose IdP
asserts groups that no `Group` row matches grants nobody any authorization, and
nobody can reach the admin to fix it -- while every local smoke check passes,
because a developer's database was seeded by hand. The fix is that the component
provisions the rows itself, from the claims contract, before the first
authentication.

The other half of AD-27 is that there is exactly *one* mechanism. A migration
that creates groups inline leaves the local persona seeding task (Epic 3, Story
3.3) nothing to call, so it reimplements the same thing slightly differently,
and the two drift -- which is how the deadlock becomes invisible to the harness
again. Hence `provision_groups`: a single callable that takes an optional
historical model registry, so every migration and every live caller share one
body. Its `apps` parameter is that seam and nothing more.

`provision_groups` takes group *names*, and `provision_designated_groups` is the
claims contract's reader in front of it. The split is what lets a second
contract -- the product's three role groups, in
`conda_package_supply_chain_monitor.core.roles` -- be provisioned through the one
writer without this platform module learning a single product concept, and
without changing what any existing caller of `provision_designated_groups` gets.
Deciding which groups a contract asks for belongs to whoever owns that contract;
creating them belongs here.

AD-12 leans on this module. "A claim asserting a group with no matching Django
`Group` is ignored and logged, never created" is only a defensible rule because
the designated groups are guaranteed to exist; without that guarantee, ignoring
unknown groups would silently deny the very administrator who is meant to be
established by claim.

AD-4 (dependency direction) governs where the contract is read from.
`django_service` may never import `config`, and `config.settings.base` imports
`config.authorization.claims`, so importing the contract's own module here would
close a cycle. `django.conf.settings` is the legal seam and the only one: the
four names arrive as `settings.CLAIMS_CONTRACT` and nowhere else.

Nothing here raises on an unconfigured contract. A migration that raised would
make `pixi run migrate` unusable during bring-up, before any contract has been
supplied; the refusal to *start* on an unconfigured contract is Epic 4's stage 1
and belongs at startup, not inside a schema operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import structlog
from django.apps import apps as global_apps
from django.conf import settings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.migrations.state import StateApps

__all__ = [
    "DESIGNATED_GROUP_PERMISSIONS",
    "STAFF_ROLE",
    "SUPERUSER_ROLE",
    "ProvisionResult",
    "provision_designated_groups",
    "provision_groups",
]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The two role slots the claims contract fills. They are slots, not names: the
#: name of the group that occupies each one is configuration and is read at call
#: time. Declared as constants so the declaration below and the readers of it
#: cannot disagree about the spelling.
STAFF_ROLE: Final = "staff"
SUPERUSER_ROLE: Final = "superuser"

#: What each designated group may do, keyed by **role slot** and never by group
#: name. AC #1 requires the rows to be seeded from the claims contract rather
#: than from hardcoded names, so no group name may appear in this file at all --
#: which is exactly what keying by slot buys.
#:
#: Values are `app_label.codename` strings resolved against the `auth_permission`
#: table at call time. A codename that resolves to nothing is logged and skipped,
#: never created: creating a permission row for an unrecognised codename is the
#: same class of mistake AD-12 forbids for unknown group claims, where inventing
#: the missing row turns a typo into a grant.
DESIGNATED_GROUP_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    # The minimum that makes the admin index useful to a staff member rather
    # than an empty page: `view_user` is what puts the Users entry on the index
    # at all -- `ModelAdmin.has_module_permission` consults the app's
    # permissions -- and `change_user` is what makes the rows it lists openable.
    # Nothing else is granted; a staff member who needs more gets a group of
    # their own rather than a wider default here.
    STAFF_ROLE: ("users.view_user", "users.change_user"),
    # Deliberately empty. `ModelBackend.has_perm` short-circuits on
    # `is_superuser` and returns True without consulting a single group, so any
    # permission attached here is never read. It would still be *maintained* --
    # showing up in the admin, in audits, and in whatever the next person infers
    # from it -- which is how a decorative grant drifts into a load-bearing one.
    SUPERUSER_ROLE: (),
}


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    """What one provisioning pass did, so callers can log it without re-querying.

    Attributes:
        created: Names of the groups this pass inserted.
        existing: Names of the groups that were already present.
        permissions_attached: How many `Permission` rows this pass attached
            across every group it provisioned. Counted after resolution, so a
            codename that resolved to nothing is not counted as attached, and it
            counts what *this* declaration asked for rather than what the rows
            hold -- a group named by two declarations is counted by each.

    """

    created: tuple[str, ...] = ()
    existing: tuple[str, ...] = ()
    permissions_attached: int = 0


def provision_groups(
    groups: Mapping[str, Sequence[str]],
    apps: StateApps | Apps | None = None,
    *,
    declared_by: str = "",
    preserve_existing: bool = False,
) -> ProvisionResult:
    """Create the named groups and attach the permissions asked of each.

    The one and only place in this repository that creates a `Group` row. Every
    other path that needs a group to exist -- this module's own
    `provision_designated_groups`, the product's role-group migration, Epic 3's
    persona seeding, Epic 8's smoke check -- calls this rather than creating
    groups of its own (AC #3, AD-27).

    It takes names rather than reading a contract, which is what lets a second
    contract be provisioned through it without teaching this platform module
    anything about the product's concepts. Deciding *which* groups a contract
    asks for belongs to whoever owns that contract; creating them belongs here.

    Idempotence is structural rather than a re-run guard: `get_or_create` on the
    name and `permissions.set`/`add` on the resolved rows all converge, so the
    second call and the hundredth leave the database in the state the first did.

    **More than one contract may name the same group, and `preserve_existing` is
    what stops the second one silently disarming the first.** Nothing prevents an
    operator pointing `CPM_LEADERSHIP_GROUP` at the directory group
    `COMPONENT_STAFF_GROUP` already names -- "platform and engineering
    leadership" and the staff group are frequently one group -- and this module
    already treats the analogous collision *within* the claims contract as a
    configuration rather than a mistake. A pass that then called `set` with its
    own (empty) declaration would clear `users.view_user` and `users.change_user`
    from that row, and the only symptom would be staff members landing on an
    empty admin index: no refusal fires, because `stage_two`'s condition asks
    whether the row *exists*, not what it holds.

    Args:
        groups: Group name to the `app_label.codename` permission strings that
            group should hold, keyed by name so that two role slots pointing at
            one group have already been unioned by the caller. An empty mapping
            creates nothing and issues no query.
        apps: A historical model registry, as a data migration receives. None
            means the live registry, which is what every runtime caller wants.
            This parameter is the entire reason one implementation can serve
            both, and it must stay optional for that reason.
        declared_by: The declaration this pass provisions, carried into the
            event so a log reader can tell a missing role pass from a missing
            designated pass. Both emit `authorization.groups_provisioned` and
            they would otherwise be indistinguishable.
        preserve_existing: False -- the default, and what the claims contract
            uses -- makes the row equal the declaration, so a codename dropped
            from `DESIGNATED_GROUP_PERMISSIONS` is revoked on the next pass.
            True adds this declaration's permissions and removes none, which is
            what a *secondary* declaration owes a row it shares: it speaks for
            what it asks for and never for what another contract asked. The
            trade is that a secondary declaration cannot revoke by omission;
            whoever removes one of its codenames has to say so.

    Returns:
        What the pass did.

    """
    registry: Apps = global_apps if apps is None else apps
    # A historical model is a class generated from migration state at runtime,
    # so no static type describes it, and the live `auth.Group` and its
    # historical counterpart are different classes with the same shape. `Any` is
    # the honest annotation for the pair; narrowing it would mean either lying
    # about the migration path or splitting this into two bodies, which is the
    # duplication AD-27 forbids.
    group_model: Any = registry.get_model("auth", "Group")
    permission_model: Any = registry.get_model("auth", "Permission")

    created: list[str] = []
    existing: list[str] = []
    attached = 0

    for name, codenames in groups.items():
        group, was_created = group_model.objects.get_or_create(name=name)
        (created if was_created else existing).append(name)

        permissions = _resolve_permissions(permission_model, name, codenames)
        if preserve_existing:
            group.permissions.add(*permissions)
        else:
            group.permissions.set(permissions)
        attached += len(permissions)

    result = ProvisionResult(
        created=tuple(created),
        existing=tuple(existing),
        permissions_attached=attached,
    )
    # The spine makes every authorization change an event. Provisioning is one:
    # this is the record that the groups an operator configured are the groups
    # that exist, emitted whether or not anything was inserted.
    logger.info(
        "authorization.groups_provisioned",
        declared_by=declared_by,
        created=result.created,
        existing=result.existing,
        permissions_attached=result.permissions_attached,
    )
    return result


def provision_designated_groups(apps: StateApps | Apps | None = None) -> ProvisionResult:
    """Create the groups the claims contract names and attach their permissions.

    The claims contract's half of provisioning: it reads the contract, decides
    which names it asks for, and hands them to `provision_groups`. What it
    provisions is unchanged by that delegation -- the two designated groups, with
    the permissions their slots declare, and nothing else.

    Args:
        apps: A historical model registry, as a data migration receives. None
            means the live registry. Passed straight through.

    Returns:
        What the pass did. An unconfigured contract returns an empty result and
        raises nothing -- see the module docstring for why the refusal is not
        here.

    """
    contract = settings.CLAIMS_CONTRACT
    if not contract.is_configured:
        # Not an error, and not silence either. The contract being unset is the
        # normal state of a freshly cloned checkout being migrated for the first
        # time; Epic 4 is what refuses to *serve* in that state.
        logger.warning(
            "authorization.provisioning_skipped",
            reason="claims_contract_unconfigured",
        )
        return ProvisionResult()

    return provision_groups(
        _designated_groups(contract.staff_group, contract.superuser_group),
        apps,
        declared_by="claims_contract",
    )


def _designated_groups(staff_group: str, superuser_group: str) -> dict[str, tuple[str, ...]]:
    """Collapse the two role slots onto the group names the contract gives them.

    Keyed by name rather than by role because nothing stops an operator pointing
    both `COMPONENT_STAFF_GROUP` and `COMPONENT_SUPERUSER_GROUP` at one group --
    a small deployment where every administrator is also staff. Iterating the
    roles directly would then call `permissions.set` twice on the same row, and
    the second call, carrying the superuser slot's empty set, would clear what
    the first attached. Unioning first makes that configuration mean what it
    reads as instead of quietly disarming the staff grant.

    Args:
        staff_group: The configured name of the group conferring `is_staff`.
        superuser_group: The configured name of the group conferring
            `is_superuser`.

    Returns:
        One entry per distinct group name, in the order the roles declare them,
        each carrying the union of the permissions its roles ask for. This is the
        mapping `provision_groups` takes.

    """
    by_name: dict[str, tuple[str, ...]] = {}
    for role, name in ((STAFF_ROLE, staff_group), (SUPERUSER_ROLE, superuser_group)):
        held = by_name.get(name, ())
        by_name[name] = (*held, *(code for code in DESIGNATED_GROUP_PERMISSIONS[role] if code not in held))
    return by_name


def _resolve_permissions(permission_model: Any, name: str, codenames: Sequence[str]) -> list[Any]:
    """Resolve `app_label.codename` strings to the `Permission` rows they name.

    Args:
        permission_model: The `auth.Permission` model, live or historical.
        name: The group being provisioned, carried so an unresolved codename can
            be reported against the group that asked for it.
        codenames: The `app_label.codename` strings that group asks for.

    Returns:
        The rows that resolved, in declaration order. A codename matching no row
        is logged at warning and left out -- handled, not swallowed. It is never
        created: an unrecognised codename is a mistake in a permission
        declaration or an app whose permissions have not been created yet, and
        inventing the row would turn either one into a grant nobody wrote down.

    Note:
        The warning carried a `roles` field until `provision_groups` was
        extracted. It was dropped deliberately rather than lost: the writer now
        takes a name-to-codenames mapping, so which *slot* asked for a codename
        has already been unioned away by the time this runs, and the group name
        plus the codename are what an operator needs to find the declaration.

    """
    resolved: list[Any] = []
    for label in codenames:
        app_label, _, codename = label.partition(".")
        permission = permission_model.objects.filter(
            content_type__app_label=app_label,
            codename=codename,
        ).first()
        if permission is None:
            logger.warning(
                "authorization.permission_unresolved",
                permission=label,
                group=name,
            )
            continue
        resolved.append(permission)
    return resolved
