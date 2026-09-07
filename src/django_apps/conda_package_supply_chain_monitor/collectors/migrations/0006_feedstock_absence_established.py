# `feedstock_snapshots.absence_established`, added by CPM-CURRENCY-S07.
#
# `not_found` on this table is reachable four ways and only one of them is
# evidence that conda-forge has nothing: the repository answered absent, the
# repository could not be read, the staged-recipes queue could not be read, and
# the queue answered ambiguously or overflowed its page. Every one of those
# already wrote a distinct `detail`, which is prose; this column says the same
# thing structurally so the feedstock presence policy can tell an established
# absence from a failure to find out without matching on a sentence across an
# application boundary.
#
# The default is `False` and every existing row takes it. That is the safe
# direction and it is the honest one: no row written before this migration
# recorded which of the four shapes it was, so none of them may claim to have
# established anything.
#
# Hand-edited once, and only the dependencies. The autodetector named
# `identity.0004`, which this field does not reference -- `AddField` and
# `AddConstraint` on a table `collectors.0004` created need `collectors.0005`
# and nothing else. The correction is the one `collectors.0002` through `0005`
# each carry.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collectors', '0005_conda_package_snapshots'),
    ]

    operations = [
        migrations.AddField(
            model_name='feedstocksnapshot',
            name='absence_established',
            field=models.BooleanField(default=False, verbose_name='absence established'),
        ),
        migrations.AddConstraint(
            model_name='feedstocksnapshot',
            constraint=models.CheckConstraint(condition=models.Q(('absence_established', False), ('state', 'not_found'), _connector='OR'), name='absence_established_only_on_an_absence'),
        ),
    ]
