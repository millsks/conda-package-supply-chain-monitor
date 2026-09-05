# Hand-written, and it has to be. `makemigrations` reads the change from
# `package_id = PositiveBigIntegerField(...)` to `package = ForeignKey(...)` as a
# field removed and a different field added, because the attribute names differ
# -- and `RemoveField` plus `AddField` drops the column and re-creates it empty,
# taking every recorded run's package reference with it. `CPM-EVIDENCE-S09`'s
# second acceptance criterion is that no row is lost and the column is preserved
# rather than dropped and re-added, so the three operations below are the whole
# migration:
#
# * `RenameField` carries the existing column across to the new attribute name,
#   which is what keeps its rows.
# * `RunPython` clears the references that name no package, because the old
#   contract permitted them and the new constraint does not -- see below.
# * `AlterField` then turns that column into the relation, adding the foreign-key
#   constraint `CPM-AD-3` asks for and `CPM-AD-25` needs `PROTECT` on.
#
# **Why the `RunPython` is not optional.** Until this migration, `core/ledger.py`
# accepted any non-negative integer as a package key and wrote it, so a deployed
# `collection_runs` can hold references to packages that never existed. Adding
# the foreign key validates the rows already there -- PostgreSQL's
# `ADD CONSTRAINT ... FOREIGN KEY` validates by default, and SQLite's table
# rebuild runs its own check -- so without this step `migrate` fails on exactly
# the data the old contract permitted, which is the worst possible place to
# discover it. Setting those references to NULL loses nothing: the value pointed
# at no package, and NULL is what this column already means by "not scoped to one
# package". Every *row* survives, which is what AC 2 is about.
#
# The column is named twice on the way through -- `package_id` to `package` and
# back to `package_id`, because Django names a `ForeignKey`'s column by its
# `attname` -- and it is the same column throughout: a rename moves the data with
# it. `tests/unit/django_apps/test_run_ledger_migration.py` asserts the sequence
# and that no destructive operation is present;
# `tests/integration/django_apps/test_run_ledger_migration.py` runs it against a
# populated table on whichever backend the suite is pointed at.

import django.db.models.deletion
from django.db import migrations, models


def null_references_that_name_no_package(apps, schema_editor):
    """Clear every package reference the new foreign key would reject.

    Written against the historical models rather than an import of
    `core.models`: this migration must keep doing what it did when it was
    written, and an import would follow the models forward until the day the
    column is renamed again and this step silently touches something else.

    At this point in the migration the attribute is already `package` and is
    still a plain integer, so the comparison is against `Package`'s primary keys
    rather than through a relation that does not exist yet.
    """
    collection_run = apps.get_model("core", "CollectionRun")
    package = apps.get_model("identity", "Package")
    collection_run.objects.exclude(package=None).exclude(
        package__in=package.objects.values("pk"),
    ).update(package=None)


def nothing_to_restore(apps, schema_editor):
    """Reversing drops the constraint, and the discarded references are gone.

    A no-op rather than a restoration, because there is nothing to restore from:
    the forward step overwrote each orphaned value with NULL and no record of it
    is kept. It named no package, which is why it was cleared.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_package_health'),
        ('identity', '0001_package_identity'),
    ]

    operations = [
        migrations.RenameField(
            model_name='collectionrun',
            old_name='package_id',
            new_name='package',
        ),
        migrations.RunPython(null_references_that_name_no_package, nothing_to_restore),
        migrations.AlterField(
            model_name='collectionrun',
            name='package',
            field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='collection_runs', to='identity.package', verbose_name='package'),
        ),
    ]
