"""The local sign-in views: the one mechanism by which a persona gets a session.

AD-21 makes this a URL route "and by no other mechanism -- not a development
authentication backend, not a management command that writes a session, not a
query-parameter shim". Everything in this module exists to keep that true, and
three properties carry it.

**It holds no mapping logic.** The views build a synthetic claims payload with
`personas.build_claims` -- the sole constructor, shared with the seeding task and
with Story 3.5's token minting -- and hand it to `resolve_user` and then
`sync_for_interactive`, exactly as an interactive IdP login does. Nothing here
reads a persona's groups to set anything on a user, writes `is_staff` or
`is_superuser`, or decides a permission. That is AD-11 and AD-10: the mapper owns
identity and authorization, and the whole value of this route is that the mapper
cannot tell which path handed it the claims. A branch here that promoted the
staff persona would make the local behaviour agree with the deployed behaviour by
coincidence rather than by construction, and the disagreement would surface in
production.

`sync_for_interactive` and never `sync_once_per_epoch`: an interactive login *is*
the epoch, carries no `jti`, and routing it through the epoch gate would make a
changed declaration apply once and never again.

**Signing in is a `POST`.** The index is a `GET` that lists what can be signed in
as; the act itself is `POST`-only. A credential path reachable by following a
link is a drive-by session -- a page anywhere, a prefetch, or an image tag would
establish one -- and the persona is selected by a *path segment* rather than a
query parameter, which AD-21 names as a forbidden shape in its own right.

**They refuse unless the run is local.** The first statement of each view asks
`config.locality.is_local()` and raises `Http404`. That is defence in depth
behind the URLconf gate in `config/urls.py`, not a substitute for it, and it is
`Http404` rather than `ImproperlyConfigured` deliberately: a view reached in a
deployed component must not answer 500 with a configuration message, because that
announces the path exists and turns a guarded route into an error-rate signal.
The seeding task's `ImproperlyConfigured` is right for something an operator
invoked and wrong for something a stranger requested.

The method check is written out rather than delegated to `require_POST` or
`require_safe`, and the order is the reason. A decorator runs *before* the
function body, so a `require_POST`-wrapped view answers `405` to a `GET` without
ever reaching the locality guard -- and `405` is not "nothing": it confirms the
path exists and that only the verb was wrong, which is the disclosure the
`404`-over-`ImproperlyConfigured` choice above exists to avoid. Locality is asked
first, so a route that became reachable in a deployed component answers `404` to
every verb.

Both views make that check. The index is the listing half of a credential path,
and a listing that answered a `POST`, a `PUT` or a `DELETE` identically to a
`GET` would be a write-shaped request served out of a read-only view -- nothing
is written today, and the guard is what keeps "nothing is written" from being a
property of the body rather than of the contract.

The module's *location* is load-bearing. Epic 4's stage-2 predicate resolves the
URLconf and refuses any route whose view callable belongs to `config.local_dev`
(AD-26: predicates resolve objects, never strings). So these callables stay here,
un-relocated and un-re-exported, and any decorator applied to them must preserve
`__module__`.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

import structlog
from django.conf import settings
from django.contrib.auth import login
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import Http404
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from config.authorization.exceptions import ClaimsRejected
from config.authorization.mapper import resolve_user
from config.authorization.mapper import sync_for_interactive
from config.local_dev.constants import LOCAL_SIGNIN_URL_NAME
from config.local_dev.personas import UnknownPersonaError
from config.local_dev.personas import build_claims
from config.local_dev.personas import get_persona
from config.local_dev.personas import persona_keys
from config.local_dev.personas import resolve_groups
from config.locality import is_local

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

__all__ = ["persona_index", "persona_signin"]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

#: The one template these views render. It lives under `django_service`, which is
#: where `base.html` and the error templates stay in every combination (AD-29).
TEMPLATE: Final[str] = "local_dev/persona_index.html"

#: The backend named when the session is established. It is
#: *already* in `AUTHENTICATION_BACKENDS`; naming it adds no credential path,
#: which matters because FR-17's allowlist is evaluated over that setting. Django
#: requires the argument only because more than one backend is configured and
#: nothing here called `authenticate()` to record which one answered.
SESSION_BACKEND: Final[str] = "django.contrib.auth.backends.ModelBackend"

#: The one verb that signs anybody in. Named rather than spelled twice, so the
#: guard and the `Allow` header it answers with cannot disagree.
_POST: Final[str] = "POST"

#: The verbs that may list the personas: the safe pair, and `HEAD` alongside `GET`
#: because Django answers a `HEAD` by running the view and discarding the body, so
#: refusing it here would refuse a request `GET` already permits. Named for the
#: same reason `_POST` is -- the guard and the `Allow` header read one list.
_SAFE_METHODS: Final[tuple[str, ...]] = ("GET", "HEAD")

#: The refusals, named rather than written at the `raise`. Neither says anything
#: a 404 body would not already say; they exist so a log or a traceback in a
#: developer's console explains itself.
_NOT_LOCAL: Final[str] = "local persona sign-in is mounted only where the component runtime declares itself local"
_UNKNOWN_PERSONA: Final[str] = "no persona is declared under that key"


def persona_index(request: HttpRequest) -> HttpResponse:
    """List the declared personas, each with a form that signs in as it.

    A `GET`, because listing is not signing in. Rendering it requires no database
    access and establishes nothing.

    Args:
        request: The incoming request. Safe verbs only.

    Returns:
        The rendered persona list, or `405` when the verb is not a safe one.

    Raises:
        Http404: The run is not local.

    """
    if not is_local():
        raise Http404(_NOT_LOCAL)
    if request.method not in _SAFE_METHODS:
        # After the locality guard, never before it -- which is why this is not
        # `@require_safe`. See the module docstring.
        return HttpResponseNotAllowed(_SAFE_METHODS)
    return _render_index(request)


def persona_signin(request: HttpRequest, persona_key: str) -> HttpResponse:
    """Sign in as one declared persona, through the mapper and nothing else.

    Args:
        request: The incoming request. `POST` only.
        persona_key: The persona's key, taken from a path segment.

    Returns:
        A redirect to `LOGIN_REDIRECT_URL` once the session is established, `405`
        when the verb is not `POST`, or the re-rendered index with status 400
        when the claims could not be built or were refused.

    Raises:
        Http404: The run is not local, or the key names no declared persona.

    """
    if not is_local():
        raise Http404(_NOT_LOCAL)
    if request.method != _POST:
        # After the locality guard, never before it -- which is why this is not
        # `@require_POST`. See the module docstring.
        return HttpResponseNotAllowed([_POST])

    try:
        persona = get_persona(persona_key)
    except UnknownPersonaError as unknown:
        # Narrow on purpose: `UnknownPersonaError` and not `LookupError` or
        # `KeyError`, so an incidental dictionary miss inside the personas module
        # stays a 500 rather than presenting as a missing persona.
        raise Http404(_UNKNOWN_PERSONA) from unknown

    try:
        claims = build_claims(persona)
        # `ATOMIC_REQUESTS` is on, so a `ClaimsRejected` caught *here* would
        # otherwise leave the request's transaction to commit whatever
        # `resolve_user` had already created: a sign-in reported as refused, with
        # an account behind it holding no groups and no sync. The savepoint makes
        # the pair all-or-nothing.
        with transaction.atomic():
            user = resolve_user(claims)
            outcome = sync_for_interactive(user, claims)
    except (ClaimsRejected, ImproperlyConfigured) as refusal:
        # Handled, not swallowed, and both types rather than only the mapper's.
        # `ClaimsRejected` is reachable on a fresh clone, where nothing configures
        # the identity-key claim and the mapper correctly answers "identity key
        # claim absent"; `ImproperlyConfigured` is `build_claims` refusing two
        # configured claim names that overlap. Both are the same misconfiguration
        # from the developer's chair, and answering one with a form error and the
        # other with a traceback would be an arbitrary distinction. Neither
        # message carries a claim *value*, so rendering it leaks nothing.
        reason = refusal.reason if isinstance(refusal, ClaimsRejected) else str(refusal)
        logger.warning("local_dev.persona_signin_rejected", persona=persona.key, reason=reason)
        return _render_index(request, rejection=reason, status=HTTPStatus.BAD_REQUEST)

    login(request, user, backend=SESSION_BACKEND)
    logger.info(
        "local_dev.persona_signed_in",
        persona=persona.key,
        user_id=user.pk,
        is_staff=outcome.is_staff,
        is_superuser=outcome.is_superuser,
        # The names the claims asserted that match no `Group`. Ignored and never
        # created (AD-12), so without this the "I seeded, and the staff persona
        # still is not staff" case -- designated groups never provisioned --
        # leaves no trace anywhere a developer would look.
        groups_ignored=list(outcome.ignored),
    )
    return redirect(settings.LOGIN_REDIRECT_URL)


def _render_index(
    request: HttpRequest,
    rejection: str | None = None,
    status: HTTPStatus = HTTPStatus.OK,
) -> HttpResponse:
    """Render the persona list, optionally carrying a refusal from the mapper.

    The form action for each persona is reversed here rather than built in the
    template, so the route's name is spelled in one module and the template needs
    no knowledge of it.

    Args:
        request: The incoming request.
        rejection: The mapper's reason for refusing a set of claims, when this
            render is the answer to a refused sign-in.
        status: The response status.

    Returns:
        The rendered persona list.

    """
    context: dict[str, Any] = {
        "personas": [
            {
                "key": key,
                "groups": resolve_groups(get_persona(key)),
                "action": reverse(LOCAL_SIGNIN_URL_NAME, kwargs={"persona_key": key}),
            }
            for key in persona_keys()
        ],
        "rejection": rejection,
    }
    return render(request, TEMPLATE, context, status=status)
