"""Retired by AD-31. This node exists; it no longer does anything.

It used to write a `Site` row through `RunPython`, hardcoding one repository's
domain and name into the database of every component generated from this
accelerator -- which meant every deployed component advertising whatever
callback domain a data migration had baked in. AD-31 answers that by making the
`Site` domain environment-driven: `SITE_DOMAIN` and `SITE_NAME` in
`config/settings/base.py`, read from `COMPONENT_SITE_DOMAIN` and
`COMPONENT_SITE_NAME`.

Retired rather than parameterized, and rather than deleted:

* **Not parameterized.** AD-25 owns parameterization and it is Epic 7's work.
  AD-31 says this migration is retired, which is a different outcome from one
  that writes a templated value.
* **Not deleted.** `0004_alter_options_ordering_domain` depends on this node,
  and every database that has already applied it carries the row in
  `django_migrations`. Removing the node would break both. Retiring the
  *operations* is what leaves the history intact.
* **Nothing writes the row instead.** Not here, not at startup: NFR-1 requires
  the startup checks to make no query beyond migration state and AD-22 forbids
  a process performing writes at boot. The `django_site` table still has to
  exist, because allauth resolves a provider app through
  `SocialApp.objects.on_site(request)` on every lookup -- the table, never a
  row, is what that needs.

`RunPython.noop` in both directions so the node stays reversible.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("sites", "0002_alter_domain_unique")]

    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
