"""The package-identity override over HTTP: the first of the API's two writes.

`CPM-FR-27` gives v1 exactly two writes, and this is the one `CPM-AD-14` calls the
product's single governed write path to reference data. **This module does not
implement it.** `identity/services.override_identity` does, and everything that makes
the write safe -- the permission check, the required reason, the collision check, the
audit row written in the same transaction -- happens there.

That is the whole design. A view that re-implemented any part of it would be a second
door into governed reference data, and `CPM-AD-14`'s guarantee is that there is one.
So this validates the request's *shape*, hands the service a `Correction`, and turns
its refusals into status codes:

- no permission -> the service logs the refusal naming the actor; 403 here
- blank reason, unusable name, unknown package, name collision -> 400
- success -> 201 and the audit row, which is what `CPM-FR-32` makes queryable

**Authorization is declared here and enforced twice.** `requires_roles(LEADERSHIP)`
is `CPM-AD-13`'s declaration, so the audit can read what this surface requires without
running it. The service checks the Django permission independently, because a service
that trusted its caller would be one an internal caller could get past.

**It writes no derived status and no evidence.** AC 3's second half, and there is
nothing here that could: `CPM-AD-10` gives the application layer no write path to
either, and `tests/unit/django_apps/test_api_contract_audit.py` sweeps for one.

**On the `AD-` prefix.** A bare `AD-n` in this repository is an *inherited* platform
decision; a decision from this product's own architecture spine always carries the
`CPM-` prefix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from conda_sentinel.core.clock import SystemClock
from conda_sentinel.core.permissions import requires_roles
from conda_sentinel.core.roles import LEADERSHIP
from conda_sentinel.identity.api.serializers import CorrectionSerializer
from conda_sentinel.identity.api.serializers import IdentityOverrideSerializer
from conda_sentinel.identity.services import Correction
from conda_sentinel.identity.services import OverrideError
from conda_sentinel.identity.services import OverrideNotPermittedError
from conda_sentinel.identity.services import OverrideTargetMissingError
from conda_sentinel.identity.services import override_identity

if TYPE_CHECKING:
    from rest_framework.request import Request

    from django_service.users.models import User

__all__ = ["PackageIdentityOverrideAPIView"]


class PackageIdentityOverrideAPIView(APIView):
    """Correct a package's identity, with a reason, and record who did it.

    Restricted to the leadership role, which is what `core/roles.py` grants the
    override permission to. The narrower grant is deliberate: this is the one human
    write in the product that mutates governed reference data, and `CPM-AD-14` makes
    it attributable rather than merely permitted.
    """

    permission_classes = (requires_roles(LEADERSHIP),)

    @extend_schema(request=CorrectionSerializer, responses={201: IdentityOverrideSerializer})
    def post(self, request: Request, package_id: int) -> Response:
        """Apply one correction.

        Args:
            request: The request, carrying the correction.
            package_id: The package to correct, by the surrogate integer key
                `CPM-AD-3` fixes -- not by name, because the name is the thing being
                corrected and a request keyed on it would be ambiguous about which
                package it meant.

        Returns:
            201 and the audit row the override wrote.

        Raises:
            PermissionDenied: When the service refuses the actor. The declared role
                and the Django permission are separate checks by design; this is the
                second speaking.
            NotFound: When the package id names no row. `CPM-AD-25` makes
                `resolve_package_shell` the only creator of a package, so this is a
                refusal rather than a creation -- and 404 rather than 400, because
                the URL is what points at nothing.
            ValidationError: When the service refuses the correction -- a blank
                reason, a name the column cannot hold, or a name another package
                already holds. Every one is raised before the first write, so a
                refused override leaves nothing behind.

        """
        shape = CorrectionSerializer(data=request.data)
        shape.is_valid(raise_exception=True)
        fields: dict[str, Any] = shape.validated_data

        try:
            override = override_identity(
                package_id=package_id,
                # Narrowed rather than checked: the declared permission has already
                # refused an anonymous request, since anonymity holds no role. A
                # test in this view would be the view deciding authorization for
                # itself, which `test_permission_audit.py` sweeps for.
                actor=cast("User", request.user),
                correction=Correction(
                    reason=fields["reason"],
                    canonical_name=fields.get("canonical_name", ""),
                    display_name=fields.get("display_name"),
                ),
                clock=SystemClock(),
            )
        except OverrideTargetMissingError as refusal:
            # The URL names nothing, which is a 404 and not a bad body. Found by
            # calling the endpoint with a stale package id and reading a 400 that
            # told the caller their reason was wrong.
            raise NotFound(str(refusal)) from refusal
        except OverrideNotPermittedError as refusal:
            # A separate type rather than a message match, which is what makes this
            # branch survive somebody improving the wording. The service has already
            # logged the refusal naming the actor; this only chooses the code.
            raise PermissionDenied(str(refusal)) from refusal
        except OverrideError as refusal:
            # Every other refusal is about the correction rather than the actor.
            # Collapsing the two would tell somebody without the permission that
            # their reason was bad.
            raise ValidationError(str(refusal)) from refusal

        return Response(IdentityOverrideSerializer(override).data, status=status.HTTP_201_CREATED)
