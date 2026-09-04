"""Provision the product's three role groups so a role claim resolves to a row.

Hand-written, not generated, and carrying no logic of its own. The names come
from `conda_package_supply_chain_monitor.core.roles`, and the rows are created by
`django_service.users.provisioning.provision_groups` -- the one mechanism in this
repository permitted to create a `Group` (AD-27). This file decides nothing and
creates nothing itself.

That matters more here than it looks. `AD-12` makes a claim naming a nonexistent
`Group` ignored and logged, never created, which is defensible only while the
groups an operator configured are guaranteed to exist. A role group that was
never provisioned means the identity provider asserts a role, nothing matches,
and the person is authenticated with no access at all -- a misconfiguration that
presents as a permissions bug.

**The role contract is a secondary declaration over the same `auth_group` table
the claims contract writes to.** Nothing stops an operator pointing
`CPM_LEADERSHIP_GROUP` at the group `COMPONENT_STAFF_GROUP` already names, and
this migration runs *after* `users/0003_provision_designated_groups` by
declaration. So both directions defer to the claims contract on a shared row:
`forward` adds rather than replaces, and `reverse` deletes no name the claims
contract designates.

Two further reasons the work is not inline: `*/migrations/*` is omitted from
coverage, so logic written here would be invisible to the floor, and a migration
that owns behaviour cannot be re-run by anything but `migrate`.
"""

import structlog
from django.db import migrations

logger = structlog.get_logger(__name__)


def forward(apps, schema_editor):
    """Provision the role groups the contract names, or nothing when it names none.

    No `create_permissions` call, unlike `users/0003_provision_designated_groups`:
    every role slot declares an empty permission tuple, so there is nothing to
    resolve and nothing for the `post_migrate` ordering trap to catch. When
    `CPM-EP-APP` attaches the first real codename, that call has to be added here
    the way it was added there -- and the permission-unresolved warning is what
    will say so.

    `preserve_existing=True` is what makes a name shared with the claims contract
    safe. Without it this pass would `set` its own empty declaration over that
    row and clear the staff group's permissions, leaving staff members on an
    empty admin index with nothing refusing and nothing logged.

    An unconfigured contract logs and returns. It raises nothing: a fresh clone
    is migrated long before anyone has role groups to declare, and a migration
    that refused would make `migrate` unusable during bring-up. Refusing to
    *serve* on an unconfigured contract is a startup concern and is not this
    migration's. The warning is the signal an operator who set two of the three
    variables would otherwise never get.
    """
    from django.conf import settings

    from conda_package_supply_chain_monitor.core.roles import role_group_permissions
    from django_service.users.provisioning import provision_groups

    contract = settings.ROLE_CONTRACT
    if not contract.is_configured:
        logger.warning(
            "authorization.provisioning_skipped",
            reason="role_contract_unconfigured",
        )
        return

    provision_groups(
        role_group_permissions(contract),
        apps,
        declared_by="role_contract",
        preserve_existing=True,
    )


def reverse(apps, schema_editor):
    """Remove only the group rows this migration is entitled to remove.

    Two exclusions, and both are the same rule: this migration deletes only what
    its own declaration is solely responsible for.

    *Unconfigured names nothing.* Guarded on `is_configured` rather than on each
    name being non-empty, so it undoes exactly what `forward` does -- a partially
    configured contract provisions nothing and so has nothing to roll back.
    Falling through to a filter on the configured names alone would, on an
    unconfigured contract, delete whatever group happened to carry an empty name
    rather than declining to act.

    *A name the claims contract designates is not this migration's to delete.*
    `forward` did not create such a row -- `users/0003` did -- and deleting it
    would cascade away every membership it holds and turn the next start into a
    stage-two refusal for a missing designated group.

    Users and permissions are left alone. What is *not* left alone, on the rows
    this does delete, is membership: deleting a `Group` cascades through
    `auth_user_groups`, so everyone who held a role loses it. That is correct for
    a rollback of the migration that created the group -- the row is going, and a
    membership of a row that does not exist is not a thing -- and it is why the
    exclusion above matters: the same cascade against a designated group would
    take the component's administrators with it.
    """
    from django.conf import settings

    from conda_package_supply_chain_monitor.core.roles import role_group_permissions

    contract = settings.ROLE_CONTRACT
    if not contract.is_configured:
        return

    claims = settings.CLAIMS_CONTRACT
    names = set(role_group_permissions(contract)) - {claims.staff_group, claims.superuser_group}
    if not names:
        return

    group_model = apps.get_model("auth", "Group")
    group_model.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):
    """Seed the three product role groups from the role contract (CPM-FR-30)."""

    dependencies = [
        # `Group` comes from `auth`.
        ("auth", "0012_alter_user_first_name_max_length"),
        # The one writer's own migration, so the mechanism this calls has already
        # run once against this database and the designated groups exist before
        # any role group does.
        ("users", "0003_provision_designated_groups"),
    ]

    operations = [
        # Not elidable, for the reason `users/0003_provision_designated_groups`
        # is not: squashing this away would take the only guarantee that the role
        # groups exist with it, and an asserted role would resolve to nothing.
        migrations.RunPython(forward, reverse, elidable=False),
    ]
