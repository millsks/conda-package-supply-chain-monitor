# `package_health.feedstock_presence_status`, the rollup's second domain status
# column (CPM-AD-11), added by CPM-CURRENCY-S07 in the same story as the
# FeedstockPresencePass that produces it -- a column added ahead of its pass is
# one nothing writes and one every read surface reports `unknown` for forever.
#
# The default is `unknown` and is frozen here as the string, which is what a
# migration is for: every existing row acquires it, and `core/rollup.py` puts
# that default through CPM-AD-4's gate on every compose exactly as it does a
# contributed verdict. `ok` would have made every un-evaluated package read
# clean, which is the claim CPM-FR-5 forbids.
#
# The choices are frozen as the eight FeedstockOutcome offers on the day this
# ran. Django enforces `choices` on neither `save()` nor a migration, so this
# records what the schema was asked to be rather than a rule the database keeps.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_package_health_currency_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='packagehealth',
            name='feedstock_presence_status',
            field=models.CharField(choices=[('error', 'Error'), ('unknown', 'Unknown'), ('not_found', 'Not Found'), ('not_applicable', 'Not Applicable'), ('absent', 'Absent'), ('present_and_maintained', 'Present And Maintained'), ('present_and_inactive', 'Present And Inactive'), ('staged_recipe_pending', 'Staged Recipe Pending')], default='unknown', editable=False, max_length=32, verbose_name='feedstock presence'),
        ),
    ]
