# Authentication

Authentication is delegated to an OpenID Connect provider. A component never
issues or verifies a local password; it reads an access token and maps the
claims it carries onto Django's `User` and `Group` model.

## How an identity becomes a user

An identity is recognised by the claim the contract names as the identity key,
not by an email address or a username. That value is stored on the user row as
`idp_subject` — unique, indexed, and the sole store of the key. Email addresses
and usernames change at the provider; the subject does not, so matching on it is
what keeps one person one user across a rename.

The groups a caller holds arrive in the claim the contract names for them, as a
name or a list of names. Each asserted name is matched against a Django `Group`
row by name:

- A name that matches a row confers that group's permissions.
- A name that matches **nothing** is ignored and logged. It is never created.
  Creating it would turn a typo at the provider into a grant nobody wrote down.
- Membership of the group named by `COMPONENT_STAFF_GROUP` confers `is_staff`;
  membership of the group named by `COMPONENT_SUPERUSER_GROUP` confers
  `is_superuser`.

Both flags are derived from the claims on each authentication rather than being
edited in the admin and left. The provider is the authority on who is staff; a
component that let the two drift would be answering an access question from a
copy of the answer.

Ignoring an unmatched group name is only safe because the groups the contract
names are guaranteed to exist — which is what the next section is about.

The token verification and the backend that performs this mapping are not landed
yet; what is landed is the contract the mapping reads (below) and the
provisioning that the mapping depends on.

## How the first administrator is established

**The first administrator is established by IdP group claim.** An identity whose
claims assert the configured superuser-conferring group receives `is_superuser`
on its next authentication. No one runs `createsuperuser` against a deployed
component, and nothing needs to be seeded by hand for a deployment to have an
administrator.

That works only if the group named by `COMPONENT_SUPERUSER_GROUP` already exists
when that first authentication arrives. Otherwise the claim asserts a group that
matches no row, the rule above ignores it, nobody is granted anything, and
nobody can reach the admin to repair it — while every local check passes,
because a developer's database was seeded by hand. The component therefore
provisions the rows itself:

- A data migration inside `django_service`
  (`users/0003_provision_designated_groups`) creates the `Group` rows named by
  `COMPONENT_STAFF_GROUP` and `COMPONENT_SUPERUSER_GROUP` and attaches their
  permissions.
- The names are read from the claims contract, never hardcoded. Whatever an
  operator configured is what gets created.
- The staff group is granted the minimum that makes the admin index useful —
  viewing and changing users. The superuser group is granted nothing, because a
  superuser short-circuits every permission check and a decorative grant would
  only drift.
- It is idempotent. Rows are created only if absent and permissions are set
  rather than added, so running `pixi run migrate` again changes nothing.
- Every other path that needs those groups calls the same mechanism,
  `django_service.users.provisioning.provision_designated_groups`. Nothing else
  in the source creates a group, which is what keeps local seeding and the
  deployed path from drifting apart.
- Provisioning emits `authorization.groups_provisioned` with the names created,
  the names already present, and the permission count.

If the contract is unconfigured, provisioning is skipped with a
`authorization.provisioning_skipped` warning and nothing is created. It does not
raise: a migration that refused to run without a contract would make `pixi run
migrate` unusable on a fresh checkout, long before an operator has one to
supply. Refusing to *serve* on an unconfigured contract is a startup check, and
it has not landed yet.

## The claims contract

Which claims carry that information is **configuration, not code**, so a
component can be pointed at any IdP's taxonomy without a change to the source.
Four environment variables hold it:

| Variable | What it names |
| --- | --- |
| `COMPONENT_IDENTITY_CLAIM` | The claim holding the IdP subject — the stable identity key |
| `COMPONENT_GROUP_CLAIM` | The claim holding the caller's groups |
| `COMPONENT_STAFF_GROUP` | The group that confers `is_staff` |
| `COMPONENT_SUPERUSER_GROUP` | The group that confers `is_superuser` |

Each variable holds a **name**, never a value. `COMPONENT_GROUP_CLAIM` is the
name of the claim that carries groups, not a group; `COMPONENT_STAFF_GROUP` is
the name of the group that confers staff, not a boolean.

The two claim variables accept a dotted path, which is what lets one component
read `groups`, another read `roles`, and a third read `realm_access.roles` with
no code change between them. A claim name is tried as a literal key before it is
split on dots, so a namespaced name that contains dots of its own —
`https://example.com/roles`, or an Azure AD schema URI — is read as written.

A value that is blank, or blank after stripping, is treated as unset rather than
as a name. A group claim whose value is not a name or a list of names — an
object, a null, a boolean — is read as absent, so a malformed claim denies
rather than admitting a caller with a nonsense group.

No value is shown here on purpose. **Nothing is defaulted** — not `sub`, not
`groups`, not `roles`. An unset variable means the contract is unconfigured, and
a deployed component will refuse to start on an unconfigured contract once the
startup checks land. Defaulting a conventional name would turn a missing
configuration into a plausible-looking wrong one, which presents as a
permissions bug rather than as a misconfiguration.

No pixi task sets these variables yet: today a component with an unconfigured
contract starts normally and the contract is inert. When local values arrive
they belong in a task's own `env` table in `pixi.toml` — never in
`[activation.env]`, where a local convenience would leak into every environment.

The contract is read once, in `config/settings/base.py`, into the
`CLAIMS_CONTRACT` setting; `config/authorization/claims.py` holds the reader.

## `createsuperuser` and where it is still available

Superuser creation is **retired as the deployed bootstrap path** — retired, not
deleted. The distinction matters, because the command is still the right tool in
one place.

`pixi run createsuperuser` remains, and it is a local convenience: a developer's
own database, on their own machine, where a password-authenticated administrator
is the quickest way to get an admin session for a template being built or a form
being checked. Nothing about that is a credential surface, because nothing about
it is reachable.

It is not the bootstrap path anywhere else. A deployed component delegates its
admin login, so an account created this way has a password nothing will ever ask
for, and it acquires `is_staff` and `is_superuser` from a source the provider
does not know about — precisely the drift the previous sections exist to
prevent. Where a deployed component needs an administrator, configure the
superuser-conferring group at the provider and let the claim do it.

Stated as a rule: `createsuperuser` is available **only where the refusals do not
apply**, which today means local development. Those refusals — refusing to start
on an unconfigured contract, and refusing the credential-bearing paths where they
are not legitimate — are not landed yet. Until they are, the command's
availability is a matter of discipline rather than of enforcement, which is
exactly why it is written down here.

## Retired surfaces

**The static-token credential surface is removed entirely.** A component no longer
mints API tokens of its own: the API credentials it accepts are the ones the
provider issues — a Bearer access token, and the session an interactive sign-in
through the provider establishes. Three things went, and this is what they were:

| Removed | Where it lived |
| --- | --- |
| `rest_framework.authtoken` | `INSTALLED_APPS` |
| `rest_framework.authentication.TokenAuthentication` | `REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]` |
| The `obtain_auth_token` route at `/api/auth-token/` | `config/urls.py` |

They were deleted rather than deprecated. No 410, no redirect, no shim: a
credential-minting route that still resolves is still a route, and a refusal
softened into a warning is not a refusal.

This is the static-token surface only. It is **not** the claim that no local
credential path exists anywhere: `AUTHENTICATION_BACKENDS` still carries
`django.contrib.auth.backends.ModelBackend` and allauth's local account URLs are
still mounted at `accounts/`. Closing those is the refusal contract's job, not
this removal's — see "`createsuperuser` and where it is still available" above,
which concedes the same gap for the same reason.

### What an API client sends instead

A client that used to POST a username and password to `/api/auth-token/` and
replay the returned `Authorization: Token …` header now obtains an access token
from the identity provider and sends `Authorization: Bearer …`. The trade is
deliberate and worth stating plainly: programmatic access now depends on a
reachable, configured provider. A component with no provider configured has no
programmatic credential path at all, which is the intended posture rather than an
oversight.

### What remains in an already-migrated database

Removing the app from `INSTALLED_APPS` does not touch a database that already ran
its migrations. Such a database still holds:

- the `authtoken_token` table — `TokenProxy` is a proxy model and never had a
  table of its own — and
- the app's rows in `django_migrations`.

**No migration is written in this repository to drop them.** That is deliberate. A
destructive drop authored here would run against every environment on the next
release with no operator having decided it. Dropping the table is a release-stage
step performed by the deployment repository, at a time an operator chooses.

Two things an operator needs before choosing that time:

- **The residue is not inert.** `authtoken_token` still holds usable secrets, and
  `rest_framework.authentication.TokenAuthentication` ships inside the installed
  `djangorestframework` package — it is one settings line from reading them
  again. Treat the rows as live credential material until they are dropped.
- **The retained foreign key outlives the app.** The `user_id` column carries a
  DB-level `OneToOneField` constraint against the user table, but with the app
  uninstalled Django's deletion collector no longer knows to cascade it. Deleting
  a user who still has a token row therefore fails on the constraint. Either drop
  the table before the first user deletion, or drop it as part of the same
  release.
