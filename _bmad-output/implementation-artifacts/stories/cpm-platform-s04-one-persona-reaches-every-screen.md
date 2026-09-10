# CPM-PLATFORM-S04: One local persona reaches every screen

Status: done

Epic: `CPM-EP-PLATFORM` — The service platform

> **Acceptance criteria invented**, on the terms `CPM-APP-S09` established. Asked for
> by the product owner, who found — correctly — that no persona on the local sign-in
> page could open the whole navigation bar. See the epic entry.

## Story

As a maintainer,
I want one local persona that reaches every screen the product has,
so that I can check the whole navigation bar without signing in three times.

## Acceptance Criteria

1. **Given** the local sign-in page
   **When** a persona holding all three product roles and administrative access is
   offered
   **Then** signing in as it opens Home, Packages, Reports, Coverage, all three
   queues and the Django admin

2. **Given** the three single-role personas
   **When** the new one is added
   **Then** each of them still holds exactly one product role and no administrative
   access, so a scoped surface can still be seen refusing somebody

3. **Given** the role contract
   **When** the persona is declared
   **Then** it holds the three roles that already exist and adds no fourth — no new
   environment variable, and nothing for a deployment to provision

4. **Given** the sign-in page's list
   **When** it is rendered
   **Then** the persona that reaches everything is not the first one offered

## Tasks / Subtasks

- [x] `config/local_dev/personas.py` — the `operations` declaration, last, with the
      three role sentinels and `DESIGNATED_STAFF`.
- [x] `tests/unit/test_local_dev_personas.py` — three rules narrowed, two cases added.
- [x] `tests/integration/test_local_dev_seeding.py` — one assertion corrected.
- [x] `docs/conda-sentinel/running-it.md`, `docs/conda-sentinel/development.md`.

## Dev Notes

**Governed by:** `CPM-AD-13` — the authorization this persona satisfies rather than
bypasses. It carries group claims like every other persona and every surface gates it
by the same check; what differs is which groups it claims.

### Not a fourth product role

`core/roles.py` declares three slots, each backed by an entry in
`ROLE_ENVIRONMENT_VARIABLES` and provisioned by the deployment from an
identity-provider claim. A genuine platform-operations role would be a change to that
contract and to whoever provisions the groups. This is a row in the local sign-in
fixture; it reaches nothing deployed, and
`tests/unit/django_apps/test_permission_audit.py` still pins the contract at three.

The product owner was offered both and chose the persona.

### Not a superuser, either

A superuser bypasses every permission check, so a superuser persona would make every
local authorization check pass whether or not the surface checked anything. This one
holds groups the surfaces genuinely resolve — it reaches every screen *through* the
authorization, which is why signing in as it is still a real exercise of the gate,
even though it is a useless exercise of the scoping.

## Dev Agent Record

### Completion Notes

**Files changed:** `src/config/local_dev/personas.py`,
`tests/unit/test_local_dev_personas.py`,
`tests/integration/test_local_dev_seeding.py`,
`docs/conda-sentinel/running-it.md`, `docs/conda-sentinel/development.md`.

No new file. The persona is a declaration in a tuple; everything downstream — the
sign-in page, the seeder, the claim builder, the group resolver — reads the tuple.

### Three audits narrowed, none dropped

Each of these had been true since `CPM-APP-S09` and each is now false as written. The
temptation was to delete them; what they protect has not changed, so each was narrowed
to say *what* the exception is, which means a **second** exception is still a failure.

| Was | Now |
| --- | --- |
| no persona holds more than one product role | only `operations` does, and it holds all three |
| no persona holding a role also reaches the admin | no *single-role* persona does |
| exactly one persona carries the staff sentinel | exactly one carries it *and nothing else*, and that is `staff` |

The third is the one worth reading twice. What that case protected was never the
count — it was the existence of a persona that is administrative access **alone**,
which is what makes "administrative access does not imply a product role" observable.
`operations` carrying staff as well does not touch that; a second staff-*only* persona
would, and that is what the narrowed case still catches.

`MULTI_ROLE_PERSONA` is spelled once so the three exceptions cannot drift apart.

### The failure the integration suite reported was the test's

`test_seeding_surfaces_missing_groups_rather_than_creating_them` compared the *list*
of unresolved group claims against a one-item list. Two personas now carry
`DESIGNATED_STAFF`, so the unprovisioned staff group is reported twice and the list
had two items.

Nothing about the mapper changed. The count is a fact about how many personas hold the
group; what the case is for is which group went unresolved and that nothing created
it. It compares the set now, and asserts the set is non-empty so that "reported
nothing at all" cannot pass.

### Verified by signing in as each one

Not by the suite. Six sign-ins against the running stack, reading which navigation
links each persona's rendered page offers and what `/admin/` returns:

```
persona              opens
engineer-persona     Home Packages Reports Coverage remediation                          admin:302
leader-persona       Home Packages Reports Coverage identity_review                       admin:302
operations-persona   Home Packages Reports Coverage identity_review remediation
                     compliance_review                                                    admin:200
reader-persona       nothing                                                              admin:302
reviewer-persona     Home Packages Reports Coverage compliance_review                     admin:302
staff-persona        nothing                                                              admin:200
```

That is AC #1 and AC #2 in one table: the new row reaches everything, and the five
that were there reach exactly what they reached before.
