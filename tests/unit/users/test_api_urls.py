from django.urls import resolve
from django.urls import reverse


def test_user_detail():
    username = "testuser"
    assert reverse("api:user-detail", kwargs={"username": username}) == f"/api/users/{username}/"
    assert resolve(f"/api/users/{username}/").view_name == "api:user-detail"


def test_user_list():
    assert reverse("api:user-list") == "/api/users/"
    assert resolve("/api/users/").view_name == "api:user-list"


def test_user_me():
    assert reverse("api:user-me") == "/api/users/me/"
    assert resolve("/api/users/me/").view_name == "api:user-me"
