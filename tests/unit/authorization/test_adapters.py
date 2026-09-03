"""Tests for the interactive allauth adapter.

Unit tests: every one of them runs against unsaved model instances with the
mapper patched out, so nothing here opens a database connection or a socket.
What is under test is the *seam* -- that the adapter asks the mapper and does
nothing itself -- and the mapper's own behaviour is covered by
`tests/unit/authorization/test_mapper_*.py` and its integration counterparts.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialLogin
from django.test import RequestFactory

from config.authorization import adapters
from config.authorization.adapters import OIDCSocialAccountAdapter
from config.authorization.adapters import claims_from
from config.authorization.exceptions import ClaimsRejected
from django_service.users.models import User

if TYPE_CHECKING:
    from django.http import HttpRequest

# AC #3's "contains no mapping logic of its own", read off the module's own
# source. Every authorization decision this component takes is spelled with one
# of these three names, so their absence is what "the adapter decides nothing"
# means concretely -- and it is checked as text because a decision written into
# the adapter would otherwise be caught only by whichever test happened to
# notice the wrong outcome.
MAPPING_VOCABULARY = ("Group", "is_" + "staff", "is_" + "superuser")

REFUSED = "claims refused for the purposes of this test"


@pytest.fixture
def http_request() -> HttpRequest:
    return RequestFactory().get("/accounts/oidc/oidc/login/callback/")


def _sociallogin(extra_data: dict[str, Any] | None = None) -> SocialLogin:
    """Build an unsaved `SocialLogin` the way allauth's OIDC callback would."""
    account = SocialAccount(
        provider="openid_connect",
        uid="idp|1",
        extra_data={} if extra_data is None else extra_data,
    )
    return SocialLogin(user=User(), account=account)


class TestIsOpenForSignup:
    def test_open_for_signup_by_default(self, http_request: HttpRequest):
        assert OIDCSocialAccountAdapter().is_open_for_signup(http_request, _sociallogin()) is True

    def test_registration_can_be_disabled(self, settings, http_request: HttpRequest):
        settings.ACCOUNT_ALLOW_REGISTRATION = False
        assert OIDCSocialAccountAdapter().is_open_for_signup(http_request, _sociallogin()) is False


class TestClaimsFrom:
    """The envelope allauth's OIDC provider stores, unwrapped -- and nothing more."""

    def test_a_flat_extra_data_is_the_claims(self):
        assert claims_from(_sociallogin({"sub": "idp|1"})) == {"sub": "idp|1"}

    def test_the_id_token_envelope_is_unwrapped(self):
        login = _sociallogin({"id_token": {"sub": "idp|1", "groups": ["a"]}})
        assert claims_from(login) == {"sub": "idp|1", "groups": ["a"]}

    def test_the_userinfo_envelope_is_unwrapped(self):
        login = _sociallogin({"userinfo": {"sub": "idp|1"}})
        assert claims_from(login) == {"sub": "idp|1"}

    def test_both_envelopes_are_merged_with_userinfo_winning(self):
        """Neither source is dropped: an IdP may assert the group claim in only one."""
        login = _sociallogin(
            {
                "id_token": {"sub": "idp|1", "groups": ["from-id-token"], "name": "from id token"},
                "userinfo": {"sub": "idp|1", "name": "from userinfo"},
            },
        )

        assert claims_from(login) == {
            "sub": "idp|1",
            "groups": ["from-id-token"],
            "name": "from userinfo",
        }

    def test_a_non_mapping_envelope_is_not_unwrapped(self):
        """A provider that happens to assert a scalar `id_token` claim is left alone."""
        login = _sociallogin({"sub": "idp|1", "id_token": "a.b.c"})
        assert claims_from(login) == {"sub": "idp|1", "id_token": "a.b.c"}

    def test_an_account_without_extra_data_yields_an_empty_mapping(self):
        login = SocialLogin(user=User(), account=SocialAccount(provider="openid_connect", uid="idp|1"))
        login.account.extra_data = None

        assert claims_from(login) == {}


class TestPreSocialLogin:
    def test_the_mapper_resolves_and_syncs_and_allauth_connects(
        self,
        monkeypatch: pytest.MonkeyPatch,
        http_request: HttpRequest,
    ):
        """AD-11: the adapter asks the mapper, then attaches allauth's bookkeeping to the answer."""
        chosen = User(username="resolved")
        resolved: list[Any] = []
        synced: list[Any] = []
        connected: list[Any] = []
        monkeypatch.setattr(adapters, "resolve_user", lambda claims: resolved.append(claims) or chosen)
        monkeypatch.setattr(adapters, "sync_for_interactive", lambda user, claims: synced.append((user, claims)))
        login = _sociallogin({"userinfo": {"sub": "idp|1", "groups": ["platform-staff"]}})
        monkeypatch.setattr(login, "connect", lambda request, user: connected.append((request, user)))

        OIDCSocialAccountAdapter().pre_social_login(http_request, login)

        claims = {"sub": "idp|1", "groups": ["platform-staff"]}
        assert resolved == [claims]
        assert synced == [(chosen, claims)]
        assert connected == [(http_request, chosen)]

    @pytest.mark.parametrize("refusing", ["resolve_user", "sync_for_interactive"])
    def test_a_refusal_becomes_an_immediate_403(
        self,
        monkeypatch: pytest.MonkeyPatch,
        http_request: HttpRequest,
        refusing: str,
    ):
        """The interactive flow has no 401 to return, so `ClaimsRejected` leaves as a 403."""

        def refuse(*_args: Any, **_kwargs: Any) -> None:
            raise ClaimsRejected(REFUSED)

        monkeypatch.setattr(adapters, "resolve_user", lambda claims: User(username="resolved"))
        monkeypatch.setattr(adapters, "sync_for_interactive", lambda user, claims: None)
        monkeypatch.setattr(adapters, refusing, refuse)
        login = _sociallogin({"sub": "idp|1"})
        connected: list[Any] = []
        monkeypatch.setattr(login, "connect", lambda request, user: connected.append(user))

        with pytest.raises(ImmediateHttpResponse) as refusal:
            OIDCSocialAccountAdapter().pre_social_login(http_request, login)

        assert refusal.value.response.status_code == HTTPStatus.FORBIDDEN
        assert connected == [], "a refused login must not be connected to a user"

    def test_the_refusal_body_carries_no_claim_detail(
        self,
        monkeypatch: pytest.MonkeyPatch,
        http_request: HttpRequest,
    ):
        """A refusal reason rendered into the page is the token leaking to its presenter."""

        def refuse(_claims: Any) -> None:
            raise ClaimsRejected(REFUSED)

        monkeypatch.setattr(adapters, "resolve_user", refuse)
        login = _sociallogin({"sub": "idp|1"})

        with pytest.raises(ImmediateHttpResponse) as refusal:
            OIDCSocialAccountAdapter().pre_social_login(http_request, login)

        body = refusal.value.response.content.decode()
        assert REFUSED not in body
        assert "idp|1" not in body


class TestTheAdapterHoldsNoAuthorizationLogic:
    def test_the_module_source_names_none_of_the_mapping_vocabulary(self):
        """AC #3: the adapter extracts claims, calls the mapper, connects the login."""
        source = Path(adapters.__file__).read_text(encoding="utf-8")

        found = [name for name in MAPPING_VOCABULARY if name in source]

        assert found == [], f"{found} in config/authorization/adapters.py -- that decision belongs to the mapper"

    def test_mapping_is_not_placed_in_populate_user(self):
        """Story 2.5 AC #5: `populate_user` runs only at first sighting, so nothing may map there."""
        assert "populate_user" not in vars(OIDCSocialAccountAdapter)

    def test_the_hook_that_runs_on_every_login_is_the_one_overridden(self):
        assert "pre_social_login" in vars(OIDCSocialAccountAdapter)
