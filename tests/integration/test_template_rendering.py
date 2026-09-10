"""Render every project template through the full request/response cycle.

`RequestFactory`-based view tests never render a response, so template bugs --
a bad tag, a renamed context variable, a missing include -- go unnoticed until
runtime. These tests drive the real test client so the templates in
`src/django_service/templates/` are actually executed.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse
from django.views import defaults as default_views
from django.views.csrf import csrf_failure

if TYPE_CHECKING:
    from django.test import Client
    from django.test import RequestFactory

    from django_service.users.models import User

pytestmark = pytest.mark.django_db


class TestPublicPages:
    def test_the_root_leads_to_this_product_and_asks_who_you_are(self, client: Client):
        """`CPM-APP-S12` AC 1, still true after `CPM-APP-S13` moved the pages.

        The root was the accelerator's landing page. It now leads to
        `conda_sentinel:home`, which is gated like every other screen -- so the
        assertion changed from "renders for anybody" to "sends an anonymous visitor to
        sign in". That is the product working, not a regression: this service has
        nothing to show somebody who holds no role, and the page it used to show them
        described a different product.
        """
        response = client.get("/", follow=True)

        # The configured sign-in flow rather than `account_login` by name: this
        # deployment signs people in through the identity provider (`CPM-FR-17`), and
        # asserting the allauth URL would be asserting a flow this product does not
        # use. What matters is that the reader is sent somewhere to identify
        # themselves and brought back to the page they asked for.
        final, _status = response.redirect_chain[-1]
        assert "login" in final
        assert final.endswith(f"next={reverse('conda_sentinel:home')}")

    def test_about(self, client: Client):
        response = client.get(reverse("about"))
        assert response.status_code == HTTPStatus.OK


class TestAllauthPages:
    """Exercises allauth/layouts/entrance.html and the shared element partials."""

    @pytest.mark.parametrize(
        "url_name",
        [
            "account_login",
            "account_signup",
            "account_reset_password",
        ],
    )
    def test_entrance_pages_render(self, client: Client, url_name: str):
        response = client.get(reverse(url_name))
        assert response.status_code == HTTPStatus.OK

    def test_password_change_renders(self, client: Client, user: User):
        """Covers allauth/layouts/manage.html and account/base_manage_password.html."""
        client.force_login(user)
        response = client.get(reverse("account_change_password"))
        assert response.status_code == HTTPStatus.OK


class TestManagePages:
    """These render the shared element partials -- badge, field, alert -- which
    the entrance pages do not touch."""

    @pytest.mark.parametrize(
        "url_name",
        [
            "account_email",
            "socialaccount_connections",
        ],
    )
    def test_manage_pages_render(self, client: Client, user: User, url_name: str):
        client.force_login(user)
        response = client.get(reverse(url_name))
        assert response.status_code == HTTPStatus.OK

    def test_email_address_row_renders(self, client: Client, user: User):
        """allauth/elements/badge.html only renders once a verified row exists."""
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=True,
        )
        client.force_login(user)
        response = client.get(reverse("account_email"))
        assert response.status_code == HTTPStatus.OK

    def test_queued_message_renders_alert(self, client: Client, user: User):
        """allauth/elements/alert.html only renders when a message is queued."""
        client.force_login(user)
        updated = client.post(reverse("users:update"), {"name": "Ada Lovelace"})
        assert updated.status_code == HTTPStatus.FOUND

        response = client.get(reverse("account_email"))
        assert response.status_code == HTTPStatus.OK


class TestUserPages:
    def test_detail_renders(self, client: Client, user: User):
        client.force_login(user)
        response = client.get(
            reverse("users:detail", kwargs={"username": user.username}),
        )
        assert response.status_code == HTTPStatus.OK

    def test_the_detail_action_links_present_as_links(self, client: Client, user: User):
        """Both action controls navigate, so neither may claim the button role.

        `role="button"` on a navigating anchor tells assistive tech the control
        activates in place and answers a Space key, and an anchor does neither.
        Asserted on the rendered page rather than on the template text, because
        what a screen reader is handed is the render.

        Both halves. The links are still there and still styled as buttons -- an
        assertion that only counted `role="button"` would pass just as happily
        against a page that had lost the controls altogether.
        """
        client.force_login(user)
        response = client.get(
            reverse("users:detail", kwargs={"username": user.username}),
        )
        body = response.content.decode()

        assert reverse("users:update") in body
        assert reverse("account_email") in body
        assert 'role="button"' not in body

    def test_update_form_renders(self, client: Client, user: User):
        client.force_login(user)
        response = client.get(reverse("users:update"))
        assert response.status_code == HTTPStatus.OK

    def test_detail_requires_login(self, client: Client, user: User):
        response = client.get(
            reverse("users:detail", kwargs={"username": user.username}),
        )
        assert response.status_code == HTTPStatus.FOUND


class TestErrorPages:
    """The error templates are only wired to URLs when DEBUG is on, so the
    default views are invoked directly -- which is what those URLs do anyway."""

    def test_404_renders_for_an_unknown_url(self, client: Client):
        response = client.get("/no-such-page/")
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_403(self, rf: RequestFactory):
        response = default_views.permission_denied(
            rf.get("/403/"),
            Exception("Permission Denied"),
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_400(self, rf: RequestFactory):
        response = default_views.bad_request(rf.get("/400/"), Exception("Bad Request"))
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_500(self, rf: RequestFactory):
        response = default_views.server_error(rf.get("/500/"))
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_403_csrf(self, rf: RequestFactory):
        response = csrf_failure(rf.post("/"), reason="CSRF token missing")
        assert response.status_code == HTTPStatus.FORBIDDEN
