from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView
from django.views.generic import RedirectView
from django.views.generic import UpdateView

from django_service.users.models import User

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.forms import ModelForm

    # Django's class-based views are generic to a type checker and plain
    # classes at runtime: `DetailView[User]` raises TypeError unless
    # django-stubs-ext monkeypatches them, and django-stubs is a dev-only
    # dependency that must never reach a production environment. Aliasing the
    # parameterised forms here gives strict mode the type arguments it demands
    # (`disallow_any_generics`) while the runtime path below keeps the bare,
    # unsubscripted classes.
    _UserForm = ModelForm[User]
    _UserDetailViewBase = DetailView[User]
    _UserSuccessMessageMixin = SuccessMessageMixin[_UserForm]
    _UserUpdateViewBase = UpdateView[User, _UserForm]
else:
    _UserDetailViewBase = DetailView
    _UserSuccessMessageMixin = SuccessMessageMixin
    _UserUpdateViewBase = UpdateView


class UserDetailView(LoginRequiredMixin, _UserDetailViewBase):
    model = User
    slug_field = "username"
    slug_url_kwarg = "username"


user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, _UserSuccessMessageMixin, _UserUpdateViewBase):
    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    def get_success_url(self) -> str:
        """Return the URL to redirect to once the profile has been saved."""
        assert self.request.user.is_authenticated  # type guard
        return self.request.user.get_absolute_url()

    def get_object(self, queryset: QuerySet[User] | None = None) -> User:
        """Return the user being edited, which is always the requesting user.

        Args:
            queryset: Ignored; the object is never looked up by URL.

        Returns:
            The authenticated user attached to the request.

        """
        assert self.request.user.is_authenticated  # type guard
        return self.request.user


user_update_view = UserUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self) -> str:
        """Return the signed-in user's own detail page."""
        return reverse("users:detail", kwargs={"username": self.request.user.username})


user_redirect_view = UserRedirectView.as_view()
