"""Local persona sign-in, driven through the real request/response cycle.

The unit file next to this one pins the route's *shape*. This one pins what the
route does: that a `POST` establishes a session, that the payload handed to the
mapper is the one `build_claims` produced and carries nothing telling the mapper
where it came from, and -- the story's centre of gravity -- that the same admin
page admits the staff persona and refuses the read-only one, with the difference
produced by the mapper rather than by any branch in the view.

That last claim is asserted by removing the mapper's contribution rather than by
observing its result. A test that only checked "staff reaches the admin, reader
does not" would pass just as happily against a view that set `is_staff` itself,
which is exactly the implementation AD-11 forbids and exactly the one that makes
local behaviour and deployed behaviour agree by coincidence. With
`sync_for_interactive` patched to a no-op the staff persona must *also* be
refused; nothing else distinguishes the two hypotheses.

`COMPONENT_RUNTIME` is declared in every test rather than inherited from the
`dev` pixi environment the suite runs in, for the reason
`test_local_dev_seeding.py` gives: the tests would otherwise be asserting the
pixi manifest, and would go green in a component that had lost the declaration.
The claims contract is likewise pointed at names that appear nowhere in `src/`,
so nothing here can pass because a literal in the source happened to match.

The admin half is written against an *already established* session. Story 2.6
forces the admin through allauth (`DJANGO_ADMIN_FORCE_ALLAUTH`, defaulting true),
so an unauthenticated admin request redirects to the identity provider rather
than to a local form -- and that setting is not weakened here to make the admin
reachable, because weakening it would make the admission being asserted a
different admission from the one a developer actually gets.

Every test rolls back: the `django_db` marker wraps each in a transaction, and
the one test that reloads the URLconf restores it in a `finally` and asserts the
restoration before it ends. A leaked URLconf breaks every later test in the
session.
"""

from __future__ import annotations

import importlib
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
import structlog
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import Client
from django.urls import NoReverseMatch
from django.urls import clear_url_caches
from django.urls import reverse

from config import urls as project_urls
from config.authorization.claims import ClaimsContract
from config.authorization.mapper import SyncOutcome
from config.authorization.mapper import resolve_user
from config.authorization.mapper import sync_for_interactive
from config.local_dev import views
from config.local_dev.constants import LOCAL_SIGNIN_URL_NAME
from config.local_dev.personas import build_claims
from config.local_dev.personas import get_persona
from config.local_dev.personas import persona_keys
from config.locality import RUNTIME_ENV_VAR
from django_service.users.provisioning import provision_designated_groups

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.test import RequestFactory
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

# Names that appear nowhere in `src/`, matching the seeding suite's convention.
IDENTITY_CLAIM = "urn:example:principal-id"
GROUP_CLAIM = "realm_access.roles"
STAFF_GROUP = "shipping-desk-operators"
SUPERUSER_GROUP = "shipping-desk-owners"

# The mapper's refusal when no identity-key claim is configured. It is the case a
# freshly cloned component is in, and the reason the route renders it as a form
# error rather than letting it become a 500 on the first thing anyone clicks.
IDENTITY_KEY_ABSENT = "identity key claim absent"

# The session key Django writes when a user is signed in. Asserted directly
# because "no session was established" is half of what the GET test claims.
SESSION_USER_KEY = "_auth_user_id"


@pytest.fixture(autouse=True)
def _local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare this run local, explicitly rather than by inheritance."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, "local")


@pytest.fixture(autouse=True)
def _contract(settings: SettingsWrapper) -> None:
    """Point the claims contract at names that appear nowhere in the source."""
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim=GROUP_CLAIM,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )


@pytest.fixture
def _groups(db: None) -> None:
    """Provision the designated groups through the component's own one callable.

    The contract above names groups the migration never created, so without this
    the mapper would correctly ignore every asserted group (AD-12) and both
    personas would be indistinguishable.
    """
    provision_designated_groups()


def _events(captured: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """Select one event by name from a `capture_logs` recording."""
    return [event for event in captured if event.get("event") == name]


def signin_path(persona_key: str) -> str:
    """Return the sign-in path for a persona key.

    Args:
        persona_key: The key the route's path segment carries.

    Returns:
        The path, reversed through the loaded URLconf.

    """
    return reverse(LOCAL_SIGNIN_URL_NAME, kwargs={"persona_key": persona_key})


def signed_in_client(persona_key: str) -> Client:
    """Return a client that has signed in as one persona through the route.

    The sign-in response is asserted rather than discarded. Without that, every
    "this persona is refused the admin" assertion downstream is satisfied just as
    well by a client whose sign-in answered 400, 404 or 405 and which is simply
    anonymous -- which would make the refusing half of AC #4 vacuous and the
    admitting half the only real one.

    Args:
        persona_key: The persona to sign in as.

    Returns:
        The client, carrying the session the route established.

    """
    client = Client()
    response = client.post(signin_path(persona_key))
    assert response.status_code == HTTPStatus.FOUND, f"sign-in as {persona_key} did not happen: {response.status_code}"
    assert SESSION_USER_KEY in client.session
    return client


@pytest.mark.usefixtures("_groups")
def test_signin_establishes_a_session_through_the_mapper(client: Client) -> None:
    """AC #3: a `POST` signs in, and the user it signed in is the one the identity key names.

    The redirect target is `LOGIN_REDIRECT_URL` -- a route present in every
    combination -- rather than `home`, which the spine's revision 3 deletes as
    demonstration content in Epic 7.
    """
    persona = get_persona("staff")

    response = client.post(signin_path(persona.key))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == reverse("users:redirect")

    user = get_user_model().objects.get(pk=client.session[SESSION_USER_KEY])
    assert user.idp_subject == persona.subject
    assert user.username == persona.username


@pytest.mark.usefixtures("_groups")
def test_the_mapper_receives_the_same_claims_shape_as_the_idp_flows(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #3: the mapper is unaware which path produced the claims.

    Both entry points are spied on with `*args, **kwargs` rather than a fixed
    signature, because what is being asserted is that there is no *extra*
    argument -- no flag saying "this came from local sign-in", no persona object
    riding alongside the payload. A spy with a fixed signature would raise on
    such an argument rather than record it, and the failure would read as a test
    bug.
    """
    resolve_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    sync_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def spy_resolve(*args: Any, **kwargs: Any) -> Any:
        resolve_calls.append((args, kwargs))
        return resolve_user(*args, **kwargs)

    def spy_sync(*args: Any, **kwargs: Any) -> Any:
        sync_calls.append((args, kwargs))
        return sync_for_interactive(*args, **kwargs)

    monkeypatch.setattr(views, "resolve_user", spy_resolve)
    monkeypatch.setattr(views, "sync_for_interactive", spy_sync)

    persona = get_persona("staff")
    client.post(signin_path(persona.key))

    expected = build_claims(persona)
    assert resolve_calls == [((expected,), {})]
    assert len(sync_calls) == 1
    assert sync_calls[0][0][1] == expected
    assert sync_calls[0][1] == {}


@pytest.mark.usefixtures("_groups")
def test_staff_persona_reaches_the_admin_index_and_read_only_persona_does_not() -> None:
    """AC #4, and the story's centre of gravity: one admin page, two answers.

    The refusal is a redirect to the admin's own login, which Story 2.6's wrapper
    then forwards to the identity provider. It is asserted rather than followed:
    following it would drive allauth's provider login, and nothing in this
    repository opens a socket.
    """
    admin_index = reverse("admin:index")

    admitted = signed_in_client("staff").get(admin_index)
    refused = signed_in_client("reader").get(admin_index)

    assert admitted.status_code == HTTPStatus.OK
    assert refused.status_code == HTTPStatus.FOUND
    assert refused.url.startswith(reverse("admin:login"))


@pytest.mark.usefixtures("_groups")
def test_the_difference_is_produced_by_the_mapper(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC #4's second half: the divergence survives nothing but the mapper's sync.

    Two claims in one test, because they are one claim. The read-only persona
    holds no staff group and no `is_staff` -- and with the mapper's sync replaced
    by a no-op the *staff* persona is refused the same page, which is only
    possible if nothing in the view ever wrote `is_staff` itself.
    """
    reader = get_persona("reader")
    signed_in_client(reader.key)

    reader_user = get_user_model().objects.get(idp_subject=reader.subject)
    assert reader_user.is_staff is False
    assert STAFF_GROUP not in set(reader_user.groups.values_list("name", flat=True))

    monkeypatch.setattr(views, "sync_for_interactive", lambda _user, _claims: SyncOutcome())

    refused = signed_in_client("staff").get(reverse("admin:index"))

    assert refused.status_code == HTTPStatus.FOUND
    staff_user = get_user_model().objects.get(idp_subject=get_persona("staff").subject)
    assert staff_user.is_staff is False


@pytest.mark.usefixtures("_groups")
def test_get_does_not_sign_in(client: Client) -> None:
    """A credential path reachable by following a link is a drive-by session.

    405 rather than 404: the path exists, the verb does not. Both halves are
    asserted, because a 405 that had already written a session would be the same
    bug wearing a different status code.
    """
    response = client.get(signin_path("staff"))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert SESSION_USER_KEY not in client.session


def test_the_index_lists_every_declared_persona(client: Client) -> None:
    """The `GET` half, and the render that puts the template under measurement.

    The groups are rendered as the *resolved* names -- what the configured
    contract designates -- rather than the sentinels a persona declares, so the
    page tells a developer what the mapper will actually be asked for.
    """
    response = client.get(reverse(f"{LOCAL_SIGNIN_URL_NAME}_index"))

    assert response.status_code == HTTPStatus.OK
    body = response.content.decode()
    for key in persona_keys():
        assert signin_path(key) in body
    assert STAFF_GROUP in body


def test_an_unknown_persona_key_is_a_404(client: Client) -> None:
    """`UnknownPersonaError` is a `LookupError` narrowed on purpose, and it is a 404.

    Narrow, because catching `KeyError` here would turn an incidental dictionary
    miss inside the personas module into a missing persona.
    """
    response = client.post(signin_path("no-such-persona"))

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert SESSION_USER_KEY not in client.session


def test_refused_claims_render_as_a_form_error(client: Client, settings: SettingsWrapper) -> None:
    """The fresh-clone case: an unconfigured identity claim is a 400, not a traceback.

    `ClaimsRejected.reason` never carries a claim *value*, so rendering it leaks
    nothing -- which is what makes showing it to the developer the right answer
    rather than a compromise.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="",
        group_claim=GROUP_CLAIM,
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )

    response = client.post(signin_path("staff"))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert IDENTITY_KEY_ABSENT in response.content.decode()
    assert SESSION_USER_KEY not in client.session


@pytest.mark.usefixtures("_groups")
def test_a_cross_site_post_without_a_token_is_refused() -> None:
    """`POST`-only stops a link; only CSRF stops a form.

    The drive-by session this route is shaped against comes in two forms. A link,
    a prefetch or an `<img>` issues a `GET`, which `test_get_does_not_sign_in`
    covers. A cross-origin auto-submitting form issues a `POST`, and the only
    thing that refuses it is `CsrfViewMiddleware`. Django's test client runs with
    `enforce_csrf_checks=False`, so every other test in this file would go on
    passing if the view were made `csrf_exempt` tomorrow -- which is to say the
    security property with the most prose behind it is the one with no coverage
    unless it is asked for explicitly.
    """
    enforcing = Client(enforce_csrf_checks=True)

    response = enforcing.post(signin_path("staff"))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert SESSION_USER_KEY not in enforcing.session


@pytest.mark.usefixtures("_groups")
def test_the_index_form_posts_to_the_signin_path() -> None:
    """The rendered form's method, asserted -- not only the action it points at.

    A form that degraded to `method="get"` would leave every assertion in
    `test_the_index_lists_every_declared_persona` green while every Sign in button
    answered 405, because the action URL is unchanged and the 405 is exactly what
    the direct-`GET` test already expects.
    """
    enforcing = Client(enforce_csrf_checks=True)

    body = enforcing.get(reverse(f"{LOCAL_SIGNIN_URL_NAME}_index")).content.decode()

    for key in persona_keys():
        assert f'<form method="post" action="{signin_path(key)}">' in body
    assert "csrfmiddlewaretoken" in body


@pytest.mark.usefixtures("_groups")
def test_a_signin_emits_one_structured_event(client: Client) -> None:
    """The sign-in is auditable, in the same shape the seeding task's event has.

    `groups_ignored` is carried because it is the one field that explains the
    otherwise silent case: designated groups never provisioned, so the claims
    assert names matching no `Group`, the mapper ignores them (AD-12), and the
    staff persona lands without `is_staff` with nothing anywhere saying why.
    """
    with structlog.testing.capture_logs() as captured:
        client.post(signin_path("staff"))

    events = _events(captured, "local_dev.persona_signed_in")
    assert len(events) == 1
    assert events[0]["persona"] == "staff"
    assert events[0]["user_id"] is not None
    assert events[0]["is_staff"] is True
    assert events[0]["groups_ignored"] == []


def test_overlapping_claim_names_render_as_a_form_error(client: Client, settings: SettingsWrapper) -> None:
    """The other misconfiguration, answered the same way as the first.

    `build_claims` refuses two configured claim names that overlap -- one is a
    dotted path through the other's value -- with `ImproperlyConfigured`. From the
    developer's chair that is the same kind of problem as an unconfigured identity
    claim, and answering one with a form error and the other with a traceback
    would be an arbitrary distinction.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim="principal",
        group_claim="principal.roles",
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )

    response = client.post(signin_path("staff"))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert SESSION_USER_KEY not in client.session


def test_a_refused_signin_leaves_no_account_behind(client: Client, settings: SettingsWrapper) -> None:
    """`ATOMIC_REQUESTS` commits a 400 response, so the rejection has to roll itself back.

    With the identity claim configured and the group claim not, `resolve_user`
    succeeds and creates the row before `sync_for_interactive` refuses. Returning
    a 400 rather than raising leaves the request's transaction to commit, so
    without the savepoint the developer is told the sign-in was refused and an
    account with no groups and no sync exists anyway.
    """
    settings.CLAIMS_CONTRACT = ClaimsContract(
        identity_key_claim=IDENTITY_CLAIM,
        group_claim="",
        staff_group=STAFF_GROUP,
        superuser_group=SUPERUSER_GROUP,
    )
    before = get_user_model().objects.count()

    response = client.post(signin_path("staff"))

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert get_user_model().objects.count() == before
    assert not get_user_model().objects.filter(idp_subject=get_persona("staff").subject).exists()


def test_the_index_view_refuses_a_deployed_run(rf: RequestFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defence in depth behind the URLconf gate: `Http404`, never `ImproperlyConfigured`.

    A view reached in a deployed component must not answer 500 with a
    configuration message: that announces the path exists and turns a guarded
    route into an error-rate signal.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    request: HttpRequest = rf.get("/")

    with pytest.raises(Http404):
        views.persona_index(request)


def test_the_signin_view_refuses_a_deployed_run(rf: RequestFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same guard on the view that actually writes a session."""
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    request: HttpRequest = rf.post("/")

    with pytest.raises(Http404):
        views.persona_signin(request, persona_key="staff")


@pytest.mark.parametrize("verb", ["get", "put", "delete"])
def test_a_deployed_run_answers_404_to_every_verb(
    verb: str,
    rf: RequestFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The locality guard runs before the method check, and the order is the point.

    `@require_POST` would answer `405` to a `GET` without ever reaching the
    locality guard -- and `405` is not the "answers nothing" the module and the
    documentation both promise: it confirms the path exists and that only the verb
    was wrong, which is exactly the disclosure `Http404`-over-`ImproperlyConfigured`
    was chosen to avoid. A method check that precedes the locality check is the
    quiet way to lose that property, and it would leave every other assertion in
    this file green.
    """
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    request: HttpRequest = getattr(rf, verb)("/")

    with pytest.raises(Http404):
        views.persona_signin(request, persona_key="staff")


def test_route_is_absent_when_not_local(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """AD-21: the module ships everywhere, the route is mounted only where locality is local.

    The unit suite pins the decision by calling `local_signin_urlpatterns()`
    directly. This pins that the decision reaches the resolver, which needs the
    URLconf re-imported under a deployed environment -- the one thing a
    monkeypatched variable alone cannot show, because the branch was evaluated at
    import time.

    The restoration is asserted, not merely performed. A restoration nobody
    checks is a restoration nobody notices failing, and a leaked URLconf breaks
    every later test in the session.
    """
    path = signin_path("staff")
    monkeypatch.setenv(RUNTIME_ENV_VAR, "production")
    try:
        clear_url_caches()
        importlib.reload(project_urls)
        clear_url_caches()

        assert client.post(path).status_code == HTTPStatus.NOT_FOUND
        with pytest.raises(NoReverseMatch):
            signin_path("staff")
    finally:
        monkeypatch.setenv(RUNTIME_ENV_VAR, "local")
        clear_url_caches()
        importlib.reload(project_urls)
        clear_url_caches()

    assert signin_path("staff") == path
