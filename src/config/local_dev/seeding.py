"""Materialize the declared personas as local accounts, locally and nowhere else.

Two rules carry this module and neither is negotiable.

**It refuses unless the run is local.** The first statement of `seed_personas`
asks `config.locality.is_local()` and raises `ImproperlyConfigured` when the
answer is no -- the same refusal the contract uses everywhere else (AD-13,
CG-3). Locality fails closed, so an absent or unrecognized `COMPONENT_RUNTIME`
means deployed and an operator who runs this in production gets a refusal rather
than an account. Nothing after that line may execute: not a warning, not a
no-op, not a `DEBUG` test. `DEBUG` is a rendering decision, and a deployed
component with it accidentally on would seed credentials into production.

**It does not create groups.** The designated groups come from
`provision_designated_groups()` -- the one callable Story 2.3 authored and the
same one its data migration invokes (AD-27). A seeding task that called
`Group.objects.get_or_create` itself would pass every one of this story's
happy-path tests and every local smoke check while leaving the bootstrap
deadlock invisible: a deployed component whose IdP asserts groups no `Group` row
matches grants nobody anything, and nobody can reach the admin to fix it. That
is also what makes AD-12's "an unmatched group claim is ignored and logged,
never created" safe at all.

Everything else is the mapper's. This module holds no mapping logic: it drives
`resolve_user` then `sync_for_interactive` per persona, exactly as an
interactive IdP login does, so the mapper cannot tell which path handed it the
claims. `sync_for_interactive` and not `sync_once_per_epoch` -- seeding carries
no `jti` and is not a Bearer epoch (AD-10).

Idempotence follows from resolution being by identity key: a second run resolves
the same rows and re-syncs the same memberships, and there is no re-run guard to
get wrong.
"""

from __future__ import annotations

from typing import Final

import structlog
from django.core.exceptions import ImproperlyConfigured

from config.authorization.mapper import resolve_user
from config.authorization.mapper import sync_for_interactive
from config.local_dev.personas import PERSONAS
from config.local_dev.personas import build_claims
from config.locality import RUNTIME_ENV_VAR
from config.locality import is_local
from django_service.users.provisioning import provision_designated_groups

__all__ = ["seed_personas"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The refusal, named rather than written at the `raise`. It states the variable
#: an operator has to look at, because the one thing they cannot infer from the
#: exception is which declaration was missing.
_DEPLOYED_REFUSAL: Final[str] = (
    f"persona seeding never creates a local account in a deployed environment. "
    f"{RUNTIME_ENV_VAR} does not declare this run local, and locality fails closed: "
    f"absent or unrecognized means deployed. Locally, run it as `pixi run -e dev seed-personas`."
)


def seed_personas() -> list[str]:
    """Materialize every declared persona as a local account.

    Returns:
        The keys of the personas materialized, in declaration order.

    Raises:
        ImproperlyConfigured: The run is not local. Raised before any database
            work at all -- neither the group provisioning nor the mapper is
            reached -- so a deployed invocation creates nothing to clean up.
        ClaimsRejected: The claims contract is configured such that the synthetic
            payload cannot be mapped: an unconfigured identity-key claim reads as
            absent, and an unconfigured group claim reads the same way. Raised by
            the mapper and propagated rather than caught -- refusing to *start* on
            an unconfigured contract is Epic 4's stage 1, and swallowing it here
            would seed half the personas and report success.

    """
    if not is_local():
        raise ImproperlyConfigured(_DEPLOYED_REFUSAL)

    provision_designated_groups()

    seeded: list[str] = []
    for persona in PERSONAS:
        claims = build_claims(persona)
        user = resolve_user(claims)
        outcome = sync_for_interactive(user, claims)
        # One event per persona, carrying what an operator would otherwise have
        # to open a shell to see: which declaration produced which row, and what
        # authorization it ended up with. The groups are read back off the user
        # rather than restated from the declaration -- a name the claims asserted
        # that matches no `Group` is ignored by the mapper, and reporting the
        # declaration would claim a membership that does not exist.
        logger.info(
            "local_dev.persona_seeded",
            persona=persona.key,
            user_id=user.pk,
            idp_subject=user.idp_subject,
            groups=tuple(sorted(user.groups.values_list("name", flat=True))),
            is_staff=outcome.is_staff,
            is_superuser=outcome.is_superuser,
        )
        seeded.append(persona.key)

    return seeded
