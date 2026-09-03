"""Provision the designated groups so they exist before the first authentication.

Hand-written, not generated. It carries no logic of its own: the whole body of
the work lives in `django_service.users.provisioning`, which Epic 3's persona
seeding and Epic 8's smoke check call as well (AD-27). Two further reasons the
logic is not inline here -- `*/migrations/*` is omitted from coverage, so logic
written in this file would be invisible to the floor, and a migration that owns
behaviour cannot be re-run by anything but `migrate`.
"""

from django.db import migrations


def forward(apps, schema_editor):
    """Create the permission rows this migration needs, then provision the groups.

    `Permission` rows are created by the `post_migrate` signal, not by a
    migration. On a fresh database the whole `migrate` invocation runs before
    that signal fires, so a data migration here would find `auth_permission`
    empty for the `users` models and attach nothing at all -- silently, because
    attaching zero permissions is not an error. `create_permissions` is
    therefore called first, against the historical registry.

    `app_config.models_module` is set truthy and cleared again because
    `create_permissions` returns early on an app config without one, and the
    historical registry's app configs are stubs that have no models module. This
    is Django's own documented workaround for the ordering. It is applied to the
    stub rather than to the live app config on purpose: clearing the live one
    would make `post_migrate` skip permission creation for `users` for the rest
    of the process.
    """
    from django.contrib.auth.management import create_permissions

    from django_service.users.provisioning import provision_designated_groups

    app_config = apps.get_app_config("users")
    app_config.models_module = True
    try:
        create_permissions(
            app_config,
            apps=apps,
            using=schema_editor.connection.alias,
            verbosity=0,
        )
    finally:
        app_config.models_module = None

    provision_designated_groups(apps)


def reverse(apps, schema_editor):
    """Remove only the group rows the contract names, and only those.

    Permissions and users are left alone: they are not this migration's to
    create and are not its to destroy. An unconfigured contract names nothing,
    so nothing is deleted.
    """
    from django.conf import settings

    contract = settings.CLAIMS_CONTRACT
    names = {name for name in (contract.staff_group, contract.superuser_group) if name}
    if not names:
        return

    group_model = apps.get_model("auth", "Group")
    group_model.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):
    """Seed the designated groups from the claims contract (FR-11, AD-27)."""

    dependencies = [
        ("users", "0002_user_idp_subject"),
        # Both are touched by the forward function: `Group` and `Permission`
        # come from `auth`, and `create_permissions` resolves content types.
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        # Not elidable. Squashing this away would take the only guarantee that
        # the designated groups exist with it, which is the deadlock AD-27 names.
        migrations.RunPython(forward, reverse, elidable=False),
    ]
