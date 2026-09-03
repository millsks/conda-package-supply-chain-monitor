from django.urls import resolve
from django.urls import reverse


def test_detail():
    username = "testuser"
    assert reverse("users:detail", kwargs={"username": username}) == f"/users/{username}/"
    assert resolve(f"/users/{username}/").view_name == "users:detail"


def test_update():
    assert reverse("users:update") == "/users/~update/"
    assert resolve("/users/~update/").view_name == "users:update"


def test_redirect():
    assert reverse("users:redirect") == "/users/~redirect/"
    assert resolve("/users/~redirect/").view_name == "users:redirect"
