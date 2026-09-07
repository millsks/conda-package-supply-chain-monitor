# `package_license`, the derived table CPM-SECURITY-S05's licence pass owns: one
# row per package per policy run, keyed (package, policy_run) exactly as
# CPM-AD-21 requires. There is no data step, because the table starts empty and a
# policy run fills it. It is emphatically **not** the health rollup and adds no
# column to it -- CPM-AD-21 says no pass writes `package_health`.
#
# Hand-edited once, and only the dependencies, on exactly the terms
# `0002_package_feedstock_presence` and `0003_package_vulnerability` record at
# length. The autodetector names each app's *newest* migration, which here named
# `core.0007` and `identity.0004` -- neither of which this table references. What
# it actually needs is `core.PolicyRun` (`core.0002_run_ledger`),
# `identity.Package` (`identity.0001_package_identity`),
# `collectors.LicenseFinding` (`collectors.0009_license_findings`) and this
# application's own previous migration, which is what orders the four within
# `policies`.
#
# Depending on a newer migration than it references is not merely untidy:
# `tests/integration/django_apps/test_run_ledger_migration.py` rolls `core` back
# and restores the graph's leaves, and a table hanging off a migration it does
# not need is unapplied by that rollback and never put back, stranding the
# session's database for every case after it. A migration that depends only on
# what it references is the fix and the rule.
#
# Otherwise unedited: the model declares the whole of it -- the outcome column
# over the composed PackageLicenseOutcome vocabulary (CPM-AD-5), the matched rule
# with no `choices` because the rules are versioned data, the policy version and
# cut-off the row was computed under, the evidence relation PROTECT, and the five
# constraints. `license_outcome_names_the_rule_that_produced_it` is the one this
# story exists for: an `allowed` row that names no rule is refused here, by
# PostgreSQL, rather than merely avoided by the pass.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collectors', '0009_license_findings'),
        ('core', '0002_run_ledger'),
        ('identity', '0001_package_identity'),
        ('policies', '0003_package_vulnerability'),
    ]

    operations = [
        migrations.CreateModel(
            name='PackageLicense',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('license_outcome', models.CharField(choices=[('error', 'Error'), ('unknown', 'Unknown'), ('not_found', 'Not Found'), ('not_applicable', 'Not Applicable'), ('allowed', 'Allowed'), ('restricted', 'Restricted'), ('forbidden', 'Forbidden'), ('manual_review', 'Manual Review')], editable=False, max_length=32, verbose_name='license outcome')),
                ('matched_rule', models.CharField(blank=True, default='', editable=False, max_length=2048, verbose_name='matched rule')),
                ('policy_version', models.CharField(editable=False, max_length=128, verbose_name='policy version')),
                ('evidence_cutoff', models.DateTimeField(editable=False, verbose_name='evidence cutoff')),
                ('detail', models.TextField(blank=True, default='', editable=False, verbose_name='detail')),
                ('license_finding', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='license_policy_findings', to='collectors.licensefinding', verbose_name='license finding')),
                ('package', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='license_policy_findings', to='identity.package', verbose_name='package')),
                ('policy_run', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='license_policy_findings', to='core.policyrun', verbose_name='policy run')),
            ],
            options={
                'verbose_name': 'package license',
                'verbose_name_plural': 'package license',
                'db_table': 'package_license',
                'constraints': [models.UniqueConstraint(fields=('package', 'policy_run'), name='one_license_row_per_package_per_run'), models.CheckConstraint(condition=models.Q(models.Q(('license_outcome__in', ('allowed', 'restricted', 'forbidden', 'manual_review')), _negated=True), ('license_finding__isnull', False), _connector='OR'), name='license_outcome_names_its_finding'), models.CheckConstraint(condition=models.Q(models.Q(('license_outcome__in', ('allowed', 'restricted', 'forbidden')), _negated=True), models.Q(('matched_rule', ''), _negated=True), _connector='OR'), name='license_outcome_names_the_rule_that_produced_it'), models.CheckConstraint(condition=models.Q(('matched_rule', ''), ('license_outcome__in', ('allowed', 'restricted', 'forbidden')), _connector='OR'), name='license_rule_only_where_a_rule_decided'), models.CheckConstraint(condition=models.Q(('policy_version', ''), _negated=True), name='license_row_names_its_policy_version')],
            },
        ),
    ]
