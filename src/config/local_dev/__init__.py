"""The local development contract: everything that exists only for a developer.

FR-19 declares named local identities as configuration and materializes them
with a task, so a developer can exercise real authorization differences with no
identity realm running. This package is the whole of that contract's code
surface, and it is deliberately one package rather than a handful of modules
scattered by topic.

**It is `core` and ships in every component.** FR-19 chose shipping the path and
guarding it over stripping it from materialized output, "because a stripped path
cannot be tested by the component's own gate. The cost is that the product now
creates a credential path of its own -- which is why it is enumerated in the
refusal contract rather than trusted to stay unused." So nothing here is removed
by a materializer, no `feature:*` disposition applies to it, and every module in
it is guarded: `seeding.py` refuses to run unless `config.locality.is_local()`,
and Epic 4's stage-2 condition refuses to *start* a deployed component that
mounts the local sign-in route.

**One package, because the refusal resolves a module.** AD-21 and AD-26 make
Epic 4's stage-2 predicate resolve the local sign-in *view callable's owning
module* rather than match a URL name or a path prefix, which a rename or a
second mount would defeat. That predicate needs exactly one identifiable home to
resolve against. A second home for local-development code -- a view in a tenant
app, a management command in `django_service`, a helper in `config.settings` --
would be reachable by the same routes and invisible to the predicate, which is
the refusal failing open. Do not create one.

AD-4 governs the direction: `config` may import `django_service`, and nothing in
`django_service` may reach back into this package. That is why the seeding entry
point is `python -m config.local_dev.seed` rather than a Django management
command -- a management command must live inside an installed app, and the only
installed app package is `django_service`.

This module is a package marker and deliberately re-exports nothing. `personas`,
`seeding` and `seed` are each imported from their own module, so an import names
the concern rather than the package.
"""
