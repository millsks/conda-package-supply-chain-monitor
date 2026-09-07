# `package_feedstock_presence`, the derived table CPM-CURRENCY-S07's feedstock
# presence pass owns: one row per package per policy run, keyed
# (package, policy_run) exactly as CPM-AD-21 requires. There is no data step,
# because the table starts empty and a policy run fills it.
#
# Hand-edited once, and only the dependencies, on exactly the terms
# `0001_package_currency` records. The autodetector names each app's *newest*
# migration, which here named `core.0007`, `identity.0004` and
# `collectors.0005` -- none of which this table references. What it actually
# needs is `core.PolicyRun` (created by `core.0002_run_ledger`),
# `identity.Package` (`identity.0001_package_identity`) and
# `collectors.FeedstockSnapshot` (`collectors.0004_feedstock_snapshots`), plus
# this application's own previous migration, which is what orders the two within
# `policies`.
#
# Depending on `core.0007` in particular was not merely untidy: it made this
# migration a *dependent* of the rollup column that CPM-CURRENCY-S07 also adds,
# so `tests/integration/django_apps/test_run_ledger_migration.py` -- which rolls
# `core` back to `0003` and restores `core`'s leaf -- unapplied this table and
# never put it back, stranding the session's database for every case after it.
# A migration that depends only on what it references is the fix and the rule.
#
# Amended once, in the same story, after review: the fourth constraint -- a
# determinate verdict must name the observation it rests on -- arrived before
# this migration had been applied anywhere, so it belongs in the CreateModel
# rather than in a second migration altering a table nobody has ever built. That
# is the correction CPM-CURRENCY-S06's own initial migration records.
#
# Otherwise unedited: the model declares the whole of it -- the verdict column
# over the composed FeedstockOutcome vocabulary (CPM-AD-5), the threshold, the
# activity instant and the age it was measured as, the confidence the row was
# computed under, every relation PROTECT, and the four constraints.

import datetime
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collectors', '0004_feedstock_snapshots'),
        ('core', '0002_run_ledger'),
        ('identity', '0001_package_identity'),
        ('policies', '0001_package_currency'),
    ]

    operations = [
        migrations.CreateModel(
            name='PackageFeedstockPresence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('presence_status', models.CharField(choices=[('error', 'Error'), ('unknown', 'Unknown'), ('not_found', 'Not Found'), ('not_applicable', 'Not Applicable'), ('absent', 'Absent'), ('present_and_maintained', 'Present And Maintained'), ('present_and_inactive', 'Present And Inactive'), ('staged_recipe_pending', 'Staged Recipe Pending')], editable=False, max_length=32, verbose_name='feedstock presence')),
                ('inactivity_threshold', models.DurationField(editable=False, verbose_name='inactivity threshold')),
                ('last_recipe_activity_at', models.DateTimeField(blank=True, default=None, editable=False, null=True, verbose_name='last recipe activity at')),
                ('activity_age', models.DurationField(blank=True, default=None, editable=False, null=True, verbose_name='activity age')),
                ('confidence', models.CharField(choices=[('verified', 'Verified'), ('inventory-derived', 'Inventory Derived'), ('unmapped', 'Unmapped')], editable=False, max_length=32, verbose_name='confidence')),
                ('detail', models.TextField(blank=True, default='', editable=False, verbose_name='detail')),
                ('feedstock_snapshot', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='feedstock_presence_findings', to='collectors.feedstocksnapshot', verbose_name='feedstock snapshot')),
                ('package', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='feedstock_presence_findings', to='identity.package', verbose_name='package')),
                ('policy_run', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='feedstock_presence_findings', to='core.policyrun', verbose_name='policy run')),
            ],
            options={
                'verbose_name': 'package feedstock presence',
                'verbose_name_plural': 'package feedstock presence',
                'db_table': 'package_feedstock_presence',
                'constraints': [models.UniqueConstraint(fields=('package', 'policy_run'), name='one_feedstock_presence_row_per_package_per_run'), models.CheckConstraint(condition=models.Q(('inactivity_threshold__gt', datetime.timedelta(0))), name='feedstock_threshold_is_a_positive_interval'), models.CheckConstraint(condition=models.Q(models.Q(('activity_age__isnull', True), ('last_recipe_activity_at__isnull', True)), models.Q(('activity_age__isnull', False), ('last_recipe_activity_at__isnull', False)), _connector='OR'), name='feedstock_age_exactly_when_there_is_an_instant'), models.CheckConstraint(condition=models.Q(models.Q(('presence_status__in', ('present_and_maintained', 'present_and_inactive')), _negated=True), ('last_recipe_activity_at__isnull', False), _connector='OR'), name='feedstock_maintenance_verdict_names_its_instant'), models.CheckConstraint(condition=models.Q(models.Q(('presence_status__in', ('absent', 'staged_recipe_pending', 'present_and_maintained', 'present_and_inactive')), _negated=True), ('feedstock_snapshot__isnull', False), _connector='OR'), name='feedstock_verdict_names_its_observation')],
            },
        ),
    ]
