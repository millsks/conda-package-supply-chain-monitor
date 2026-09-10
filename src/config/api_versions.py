"""What this application's API answers when asked for a version it does not serve.

`CPM-APP-S14` put `v1` in the path. The half that is easy to leave out is what happens
at `v2`: Django's own answer is a 404, and a 404 on
`/conda-sentinel/api/v2/packages/` is indistinguishable from a missing endpoint.

Those two send an integrator looking in different places. "This endpoint does not
exist" sends them to the schema to find the right path. "This *version* does not
exist" sends them to change one segment. Answering the first when the second is true
costs somebody an afternoon, and nothing in a log would show it.

**It is deliberately not DRF's `URLPathVersioning`.** That class reads the version out
of a URL keyword argument, which would mean `<str:version>` in every mounted pattern
and a `version` argument in every one of the thirty-odd `reverse()` calls that name
these routes. The refusal is the only behaviour this product wants from versioning
today -- nothing branches on `request.version` -- so this buys it for one route rather
than for every call site.

**One version, and the roster is here rather than in the message.** When there is a
second, this file is where it is added, and the message says both without being
rewritten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Final

from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.response import Response

__all__ = ["SERVED_VERSIONS", "UNKNOWN_VERSION", "UnknownApiVersion"]

#: The versions of this application's API that exist.
#:
#: One. `CPM-APP-S07` published the contract and its own acceptance criteria call it
#: v1; `CPM-APP-S14` is what put that in a path, while it was still free to.
SERVED_VERSIONS: Final[tuple[str, ...]] = ("v1",)

#: What a request for any other version is told.
#:
#: It names the versions that exist, because that is the whole difference between this
#: and a 404: a caller who knows `v1` is served changes one segment, and a caller who
#: is told only "not found" goes looking for a path that was never wrong.
UNKNOWN_VERSION: Final[str] = (
    "this API serves {served}; {asked!r} is not a version of it. The path is "
    "/conda-sentinel/api/<version>/, and the contract for each served version is published at "
    "/conda-sentinel/api/<version>/schema/."
)


class UnknownApiVersion(APIView):
    """Refuse a version this API does not serve, and say which it does.

    **Unauthenticated, and that is the point rather than an oversight.** A caller who
    has the version wrong has not reached an endpoint, so there is nothing to
    authorize -- and answering 401 or 403 here would tell somebody debugging a URL
    that their *credential* was the problem. `CPM-AD-13` scopes access to evidence,
    and this view reads none.
    """

    authentication_classes: tuple[Any, ...] = ()
    permission_classes: tuple[Any, ...] = ()

    def get(self, request: Request, version: str, *args: Any, **kwargs: Any) -> Response:
        """Answer any method with the same refusal.

        Args:
            request: The request.
            version: What was asked for.
            *args: Django's positional URL arguments.
            **kwargs: Django's keyword URL arguments.

        Returns:
            Never; the refusal is raised.

        Raises:
            NotFound: Always. 404 rather than 400, because a version is part of the
                path: the caller named a resource that is not there, which is what a
                404 means, and the body is what makes it actionable.

        """
        raise NotFound(UNKNOWN_VERSION.format(served=", ".join(SERVED_VERSIONS), asked=version))

    # Every verb answers the same way. A caller who posts to a version that does not
    # exist should not be told the method is wrong -- `405` would send them to look at
    # their verb, which is the one thing about their request that was fine.
    post = get
    put = get
    patch = get
    delete = get
