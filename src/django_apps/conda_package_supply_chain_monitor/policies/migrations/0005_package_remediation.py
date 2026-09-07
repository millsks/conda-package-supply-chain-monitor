# `package_remediation`, the derived table CPM-SECURITY-S06's readiness pass owns:
# one row per package per policy run, keyed (package, policy_run) exactly as
# CPM-AD-21 requires. There is no data step, because the table starts empty and a
# policy run fills it. It is emphatically **not** the health rollup and adds no
# column to it -- CPM-AD-21 says no pass writes `package_health`.
#
# Hand-edited twice, and only the file name and the dependencies, on exactly the
# terms `0002_package_feedstock_presence`, `0003_package_vulnerability` and
# `0004_package_license` record at length. The autodetector named the file
# `0005_packageremediation` and named each app's *newest* migration --
# `core.0007` and `identity.0004` -- neither of which this table references. What
# it actually needs is `core.PolicyRun` (`core.0002_run_ledger`),
# `identity.Package` (`identity.0001_package_identity`), the five collector
# tables it reads and references (`collectors.0007_vulnerability_findings`, the
# newest of the five and therefore the one that orders them all) and this
# application's own previous migration, which is what orders the five within
# `policies`.
#
# Depending on a newer migration than it references is not merely untidy:
# `tests/integration/django_apps/test_run_ledger_migration.py` rolls `core` back
# and restores the graph's leaves, and a table hanging off a migration it does
# not need is unapplied by that rollback and never put back, stranding the
# session's database for every case after it. A migration that depends only on
# what it references is the fix and the rule.
#
# Otherwise unedited: the model declares the whole of it -- the readiness column
# over the composed RemediationReadiness vocabulary (CPM-AD-5), the four
# per-surface `*_fix` columns over the three-valued FixAvailability, the fixed
# version this row looked for, the staleness marker CPM-FR-38 supplies, the
# policy version and cut-off the row was computed under, five PROTECT evidence
# relations, and eight constraints -- one unique and seven check. (An earlier
# header said seven, having counted the check constraints and forgotten the
# unique one that keeps CPM-AD-21's key.) `blocked_needs_every_surface_read` and
# `decided_surface_names_its_observation` are the two this story exists for:
# together they refuse a `blocked` row resting on a surface this run never read,
# here, in PostgreSQL, rather than merely avoiding one in the pass.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collectors', '0007_vulnerability_findings'),
        ('core', '0002_run_ledger'),
        ('identity', '0001_package_identity'),
        ('policies', '0004_package_license'),
    ]

    operations = [
        migrations.CreateModel(
            name='PackageRemediation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('readiness_status', models.CharField(choices=[('error', 'Error'), ('unknown', 'Unknown'), ('not_found', 'Not Found'), ('not_applicable', 'Not Applicable'), ('ready', 'Ready'), ('awaiting_build', 'Awaiting Build'), ('awaiting_packaging', 'Awaiting Packaging'), ('blocked', 'Blocked')], editable=False, max_length=32, verbose_name='remediation readiness')),
                ('source_fix', models.CharField(choices=[('published', 'Published'), ('not_published', 'Not Published'), ('not_read', 'Not Read')], editable=False, max_length=32, verbose_name='source fix availability')),
                ('pypi_fix', models.CharField(choices=[('published', 'Published'), ('not_published', 'Not Published'), ('not_read', 'Not Read')], editable=False, max_length=32, verbose_name='PyPI fix availability')),
                ('feedstock_fix', models.CharField(choices=[('published', 'Published'), ('not_published', 'Not Published'), ('not_read', 'Not Read')], editable=False, max_length=32, verbose_name='feedstock fix availability')),
                ('conda_package_fix', models.CharField(choices=[('published', 'Published'), ('not_published', 'Not Published'), ('not_read', 'Not Read')], editable=False, max_length=32, verbose_name='published conda package fix availability')),
                ('fixed_version', models.CharField(blank=True, default='', editable=False, max_length=1024, verbose_name='fixed version')),
                ('evidence_stale', models.BooleanField(default=False, editable=False, verbose_name='evidence stale')),
                ('policy_version', models.CharField(editable=False, max_length=128, verbose_name='policy version')),
                ('evidence_cutoff', models.DateTimeField(editable=False, verbose_name='evidence cutoff')),
                ('detail', models.TextField(blank=True, default='', editable=False, verbose_name='detail')),
                ('conda_package_snapshot', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='remediation_findings', to='collectors.condapackagesnapshot', verbose_name='conda package snapshot')),
                ('feedstock_snapshot', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='remediation_findings', to='collectors.feedstocksnapshot', verbose_name='feedstock snapshot')),
                ('package', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='remediation_findings', to='identity.package', verbose_name='package')),
                ('policy_run', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='remediation_findings', to='core.policyrun', verbose_name='policy run')),
                ('pypi_snapshot', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='remediation_findings', to='collectors.pypireleasesnapshot', verbose_name='PyPI release snapshot')),
                ('source_snapshot', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='remediation_findings', to='collectors.sourcereleasesnapshot', verbose_name='source release snapshot')),
                ('vulnerability_finding', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='remediation_findings', to='collectors.vulnerabilityfinding', verbose_name='vulnerability finding')),
            ],
            options={
                'verbose_name': 'package remediation',
                'verbose_name_plural': 'package remediation',
                'db_table': 'package_remediation',
                'constraints': [models.UniqueConstraint(fields=('package', 'policy_run'), name='one_remediation_row_per_package_per_run'), models.CheckConstraint(condition=models.Q(models.Q(('readiness_status__in', ('ready', 'awaiting_build', 'awaiting_packaging', 'blocked')), _negated=True), ('vulnerability_finding__isnull', False), _connector='OR'), name='readiness_names_its_finding'), models.CheckConstraint(condition=models.Q(models.Q(('readiness_status', 'ready'), _negated=True), ('conda_package_fix', 'published'), _connector='OR'), name='ready_names_the_channel_that_carries_the_fix'), models.CheckConstraint(condition=models.Q(models.Q(('readiness_status', 'awaiting_build'), _negated=True), ('feedstock_fix', 'published'), _connector='OR'), name='awaiting_build_names_the_recipe_that_carries_the_fix'), models.CheckConstraint(condition=models.Q(models.Q(('readiness_status', 'awaiting_packaging'), _negated=True), ('source_fix', 'published'), ('pypi_fix', 'published'), _connector='OR'), name='awaiting_packaging_names_the_release_that_carries_the_fix'), models.CheckConstraint(condition=models.Q(models.Q(('readiness_status', 'blocked'), _negated=True), models.Q(('source_fix', 'not_published'), ('pypi_fix', 'not_published'), ('feedstock_fix', 'not_published'), ('conda_package_fix', 'not_published')), _connector='OR'), name='blocked_needs_every_surface_read'), models.CheckConstraint(condition=models.Q(models.Q(('source_fix', 'not_read'), ('source_snapshot__isnull', False), _connector='OR'), models.Q(('pypi_fix', 'not_read'), ('pypi_snapshot__isnull', False), _connector='OR'), models.Q(('feedstock_fix', 'not_read'), ('feedstock_snapshot__isnull', False), _connector='OR'), models.Q(('conda_package_fix', 'not_read'), ('conda_package_snapshot__isnull', False), _connector='OR')), name='decided_surface_names_its_observation'), models.CheckConstraint(condition=models.Q(('policy_version', ''), _negated=True), name='remediation_row_names_its_policy_version')],
            },
        ),
    ]
