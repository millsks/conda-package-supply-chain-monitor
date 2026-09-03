from http import HTTPStatus

import pytest
from django.urls import reverse
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

# The scheme name `OIDCBearerScheme` registers, and the shape an API client reads
# to learn that the value is a signed token rather than an opaque string.
BEARER_SCHEME_NAME = "bearerAuth"
BEARER_SCHEME = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}

# The name drf-spectacular generates for `TokenAuthentication`, retired in Story 2.8.
RETIRED_SCHEME_NAME = "tokenAuth"

# The warning drf-spectacular emits for an authenticator it has no extension for.
# Matched as a substring because the full text names the class and the view.
UNRESOLVED_AUTHENTICATOR = "could not resolve authenticator"


def _generated_schema() -> tuple[dict, list[str]]:
    """Generate the OpenAPI document and collect the warnings that generating it produced.

    Returns:
        The schema and the unique warning messages, in that order.

    """
    GENERATOR_STATS.reset()
    schema = SchemaGenerator().get_schema(request=None, public=True)
    return schema, list(GENERATOR_STATS._warn_cache)  # noqa: SLF001 - the only record of what was emitted


def test_api_docs_accessible_by_admin(admin_client):
    url = reverse("api-docs")
    response = admin_client.get(url)
    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_api_docs_not_accessible_by_anonymous_users(client):
    """Refused, and refused as 401 since Story 2.7 -- an intended change, not a regression.

    This asserted 403 until the Bearer class was installed, because no
    authenticator in `DEFAULT_AUTHENTICATION_CLASSES` offered a
    `WWW-Authenticate` challenge and DRF falls back to "forbidden" when none
    does. `OIDCBearerAuthentication.authenticate_header` now offers one, which is
    what makes every "rejected with 401" in Story 2.7 true, and it necessarily
    changes the answer for an unauthenticated request to any DRF route.

    401 is also the spine's stated answer -- "authentication failure is 401" --
    so this moves the response onto the rule rather than away from it. What is
    unchanged, and is what this test is actually for, is that the document is not
    served: an anonymous caller still gets a refusal.
    """
    url = reverse("api-docs")
    response = client.get(url)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_api_schema_generated_successfully(admin_client):
    url = reverse("api-schema")
    response = admin_client.get(url)
    assert response.status_code == HTTPStatus.OK


def test_the_bearer_credential_is_described_in_the_published_contract():
    """Story 2.7's subject is programmatic API authentication, so the document must describe it.

    drf-spectacular resolves an authenticator to a security scheme only through a
    registered `OpenApiAuthenticationExtension`, and it ships none for a
    `BaseAuthentication` subclass of ours. Without `OIDCBearerScheme` the
    generated document lists `cookieAuth` alone and says nothing about the
    credential every API client is expected to present -- so the one artifact a
    client author reads describes the session cookie and omits the credential
    that is the point of the API.

    The published contract is also the fourth surface Story 2.8's removal reaches,
    and the only one a client author reads: before that story the document listed
    `tokenAuth` for the static token. Its absence is asserted here rather than
    merely narrated, because a `tokenAuth` scheme reappearing would advertise a
    retired credential to every client that generates from this document.
    """
    schema, _ = _generated_schema()

    schemes = schema["components"]["securitySchemes"]

    assert schemes[BEARER_SCHEME_NAME] == BEARER_SCHEME
    assert RETIRED_SCHEME_NAME not in schemes


def test_generating_the_schema_resolves_every_authenticator():
    """An unresolved authenticator is how the scheme goes missing, and it is only a warning.

    Generation succeeds either way -- `test_api_schema_generated_successfully`
    above passes with the scheme absent -- so the status code cannot detect this.
    The warning is the signal, which makes its absence the assertion.
    """
    _, warnings = _generated_schema()

    unresolved = [warning for warning in warnings if UNRESOLVED_AUTHENTICATOR in warning]

    assert unresolved == []
