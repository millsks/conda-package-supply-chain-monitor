import contextlib
from http import HTTPStatus
from importlib import reload

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from django_service.users.admin import UserAdmin
from django_service.users.models import User


class TestUserAdmin:
    def test_changelist(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

    def test_search(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url, data={"q": "test"})
        assert response.status_code == HTTPStatus.OK

    def test_add(self, admin_client):
        url = reverse("admin:users_user_add")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

        response = admin_client.post(
            url,
            data={
                "username": "test",
                "password1": "My_R@ndom-P@ssw0rd",
                "password2": "My_R@ndom-P@ssw0rd",
            },
        )
        assert response.status_code == HTTPStatus.FOUND
        assert User.objects.filter(username="test").exists()

    def test_view_user(self, admin_client):
        user = User.objects.get(username="admin")
        url = reverse("admin:users_user_change", kwargs={"object_id": user.pk})
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

    def test_the_change_form_carries_no_editable_identity_key(self, rf, admin_user):
        """AD-11: an operator editing the identity key is account takeover.

        `UserAdminChangeForm` inherits `Meta.fields = "__all__"` from Django's
        `UserChangeForm`, so `readonly_fields` on the admin is the only thing
        subtracting the field. Deleting that one line is a silent takeover
        vector, and every other test in this file stays green when it goes.
        """
        request = rf.get("/fake-url")
        request.user = admin_user
        form = UserAdmin(User, admin.site).get_form(request, admin_user, change=True)

        assert "idp_subject" not in form.base_fields

    def test_the_change_view_ignores_a_posted_identity_key(self, admin_client):
        """The read-only guarantee holds against a crafted POST, not just the rendered form."""
        user = User.objects.get(username="admin")
        url = reverse("admin:users_user_change", kwargs={"object_id": user.pk})

        response = admin_client.post(
            url,
            data={
                "username": user.username,
                "name": user.name,
                "email": user.email,
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
                "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
                "idp_subject": "idp|attacker",
            },
        )

        assert response.status_code == HTTPStatus.FOUND
        user.refresh_from_db()
        assert user.idp_subject is None

    def test_the_identity_key_is_not_a_lookup_surface(self):
        """Task 3's negatives: the identity key is displayed on one page, never listed or searched."""
        assert "idp_subject" not in UserAdmin.list_display
        assert "idp_subject" not in UserAdmin.search_fields

    @pytest.fixture
    def _force_allauth(self, settings):
        """Re-apply the default, and reload the admin so the wrapper is installed.

        `DJANGO_ADMIN_FORCE_ALLAUTH` defaults true since Story 2.6, so this no
        longer *changes* anything -- it pins the value the test depends on, and
        the reload is what re-wraps `admin.site.login` after another test's
        reload may have replaced the module object.
        """
        settings.DJANGO_ADMIN_FORCE_ALLAUTH = True
        # Reload the admin module to apply the setting change
        import django_service.users.admin as users_admin  # noqa: PLC0415

        with contextlib.suppress(admin.sites.AlreadyRegistered):  # type: ignore[attr-defined]
            reload(users_admin)

    @pytest.mark.django_db
    @pytest.mark.usefixtures("_force_allauth")
    def test_allauth_login(self, rf, settings):
        """AC #6: `/admin/` sign-in is the IdP redirect, through the existing wrapper."""
        request = rf.get("/fake-url")
        request.user = AnonymousUser()
        response = admin.site.login(request)

        # The `admin` login view should redirect to the `allauth` login view.
        # `str`, not `reverse`: `LOGIN_URL` is the provider's resolved login
        # route now rather than a URL name -- which is the whole of AC #6.
        target_url = str(settings.LOGIN_URL) + "?next=" + request.path
        assertRedirects(response, target_url, fetch_redirect_response=False)
        assert reverse("account_login") not in response.url

    @pytest.mark.django_db
    def test_the_admin_login_is_wrapped_without_any_variable_being_set(self, rf, settings):
        """The default alone is what forces it: no fixture flips the flag here.

        `test_allauth_login` above pins the value it needs, which means it would
        keep passing if the default went back to false. This one does not, and
        that is the point -- FR-7's guarantee is about the *default*.
        """
        assert settings.DJANGO_ADMIN_FORCE_ALLAUTH is True
        request = rf.get("/fake-url")
        request.user = AnonymousUser()

        response = admin.site.login(request)

        assert response.status_code == HTTPStatus.FOUND
        assert response.url.startswith(str(settings.LOGIN_URL))
