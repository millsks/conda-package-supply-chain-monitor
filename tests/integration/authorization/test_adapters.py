"""The interactive adapter against a real database.

`tests/unit/authorization/test_adapters.py` patches the mapper out and proves the
seam. These do the opposite: the mapper is real, allauth's bookkeeping is really
written, and what is under test is the outcome AC #3 describes -- allauth's
adapter invokes the mapper, and the `SocialAccount` row lands on whichever user
the mapper chose rather than on one allauth invented.

No network: `SocialLogin` objects are built directly, the way allauth's callback
would have built them from a provider response.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialLogin
from django.contrib.auth.models import Group
from django.test import RequestFactory

from config.authorization.adapters import OIDCSocialAccountAdapter
from django_service.users.models import User

pytestmark = pytest.mark.django_db

SUBJECT = "idp|00000000-0000-4000-8000-000000000001"


@pytest.fixture
def http_request():
    return RequestFactory().get("/accounts/oidc/oidc/login/callback/")


def _sociallogin(claims: dict[str, Any]) -> SocialLogin:
    """Build the `SocialLogin` allauth's OIDC callback hands to `pre_social_login`."""
    account = SocialAccount(
        provider="openid_connect",
        uid=str(claims.get("sub", "")),
        extra_data={"userinfo": claims},
    )
    return SocialLogin(user=User(), account=account)


def test_an_interactive_login_resolves_a_user_and_syncs_what_they_may_do(http_request):
    """AD-11: the mapper is the authority, and the adapter's job is to ask it."""
    Group.objects.get_or_create(name="engineering")
    Group.objects.get_or_create(name="platform-staff")
    login = _sociallogin(
        {"sub": SUBJECT, "groups": ["engineering", "platform-staff"], "preferred_username": "ada"},
    )

    OIDCSocialAccountAdapter().pre_social_login(http_request, login)

    user = User.objects.get(idp_subject=SUBJECT)
    assert user.username == "ada"
    assert set(user.groups.values_list("name", flat=True)) == {"engineering", "platform-staff"}
    assert user.is_staff is True
    assert user.has_usable_password() is False


def test_the_social_account_lands_on_the_user_the_mapper_chose(http_request):
    """`SocialAccount` is bookkeeping (AD-11): it records the mapper's answer, never decides it."""
    existing = User.objects.create(username="already-here", idp_subject=SUBJECT)
    Group.objects.get_or_create(name="engineering")
    login = _sociallogin({"sub": SUBJECT, "groups": ["engineering"], "preferred_username": "somebody-else"})

    OIDCSocialAccountAdapter().pre_social_login(http_request, login)

    assert login.user == existing
    account = SocialAccount.objects.get(uid=SUBJECT)
    assert account.user == existing
    # The identity key resolved the user; the asserted `preferred_username` did
    # not rename them, because a resolve never re-derives attributes.
    existing.refresh_from_db()
    assert existing.username == "already-here"


def test_a_refused_login_writes_nothing(http_request):
    """A refusal is a 403 and leaves no row -- neither a user nor allauth's bookkeeping."""
    login = _sociallogin({"groups": ["engineering"]})

    with pytest.raises(ImmediateHttpResponse) as refusal:
        OIDCSocialAccountAdapter().pre_social_login(http_request, login)

    assert refusal.value.response.status_code == HTTPStatus.FORBIDDEN
    assert SocialAccount.objects.count() == 0
    assert User.objects.filter(idp_subject=SUBJECT).count() == 0


def test_an_absent_group_claim_is_refused_rather_than_read_as_no_access(http_request):
    """AD-12: a misconfigured claim name must not present as an identity holding nothing."""
    login = _sociallogin({"sub": SUBJECT, "preferred_username": "ada"})

    with pytest.raises(ImmediateHttpResponse) as refusal:
        OIDCSocialAccountAdapter().pre_social_login(http_request, login)

    assert refusal.value.response.status_code == HTTPStatus.FORBIDDEN
    assert SocialAccount.objects.count() == 0


def test_the_claims_are_read_from_the_id_token_when_that_is_where_they_are(http_request):
    """allauth stores the claims one envelope down, and an IdP may fill only one of the two."""
    Group.objects.get_or_create(name="engineering")
    account = SocialAccount(
        provider="openid_connect",
        uid=SUBJECT,
        extra_data={
            "id_token": {"sub": SUBJECT, "groups": ["engineering"]},
            "userinfo": {"sub": SUBJECT, "preferred_username": "ada"},
        },
    )
    login = SocialLogin(user=User(), account=account)

    OIDCSocialAccountAdapter().pre_social_login(http_request, login)

    user = User.objects.get(idp_subject=SUBJECT)
    assert user.username == "ada"
    assert list(user.groups.values_list("name", flat=True)) == ["engineering"]


def test_no_provider_row_is_created_in_the_database():
    """AC #4: the provider comes from settings, so nothing may seed a `SocialApp` row.

    Configuring the same provider in settings *and* the database is what makes
    allauth's `get_app` raise `MultipleObjectsReturned` at login, so a fixture or
    a migration adding one would break sign-in rather than help it.
    """
    from allauth.socialaccount.models import SocialApp  # noqa: PLC0415

    assert SocialApp.objects.count() == 0


def test_a_deactivated_person_is_refused_by_the_mapper_rather_than_by_allauth(http_request):
    """AC #7 (Story 2.7): the interactive path answers 403, and now for a stated reason.

    This is a new assertion over Story 2.6's shipped behaviour and it is
    deliberate. Until the mapper acquired the check, this path was gated only
    because allauth's `perform_login` happens to test `is_active` *after*
    `pre_social_login` returns -- an accidental gate that no test pinned and that
    nothing would have noticed losing. The refusal now happens earlier, inside
    `resolve_user`, and leaves through the adapter's own refusal response.

    That it is refused *here* rather than downstream is what the assertions
    below say: `pre_social_login` raises, so allauth never reaches the login, and
    no `SocialAccount` row is written for the deactivated identity.
    """
    Group.objects.get_or_create(name="engineering")
    User.objects.create(username="retired", idp_subject=SUBJECT, is_active=False)
    login = _sociallogin({"sub": SUBJECT, "groups": ["engineering"], "preferred_username": "ada"})

    with pytest.raises(ImmediateHttpResponse) as refusal:
        OIDCSocialAccountAdapter().pre_social_login(http_request, login)

    assert refusal.value.response.status_code == HTTPStatus.FORBIDDEN
    assert SocialAccount.objects.count() == 0


def test_reactivating_a_person_admits_them_again(http_request):
    """The control: the refusal tracks `is_active` and nothing else about the row."""
    Group.objects.get_or_create(name="engineering")
    person = User.objects.create(username="retired", idp_subject=SUBJECT, is_active=False)
    login = _sociallogin({"sub": SUBJECT, "groups": ["engineering"], "preferred_username": "ada"})
    with pytest.raises(ImmediateHttpResponse):
        OIDCSocialAccountAdapter().pre_social_login(http_request, login)

    person.is_active = True
    person.save(update_fields=["is_active"])
    OIDCSocialAccountAdapter().pre_social_login(http_request, _sociallogin({"sub": SUBJECT, "groups": ["engineering"]}))

    assert SocialAccount.objects.get(uid=SUBJECT).user == person
