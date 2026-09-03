from typing import TYPE_CHECKING

from allauth.account.forms import SignupForm
from allauth.socialaccount.forms import SignupForm as SocialSignupForm
from django.contrib.auth import forms as admin_forms
from django.utils.translation import gettext_lazy as _

from .models import User

if TYPE_CHECKING:
    from collections.abc import Collection

    from django.db.models import Model
    from django.utils.functional import Promise

    # django-stubs makes UserChangeForm generic in the user model, but the
    # runtime class is not subscriptable and django-stubs is dev-only. See the
    # same pattern and its reasoning in django_service/users/views.py.
    _UserChangeFormBase = admin_forms.UserChangeForm[User]

    class _AdminFormMeta:
        """Typed stand-in for the nested ``Meta`` django-stubs does not declare.

        django-stubs stubs no form's nested ``Meta`` at all -- it models the
        options through ``ModelFormOptions`` instead -- so
        ``admin_forms.UserChangeForm.Meta`` and
        ``admin_forms.UserCreationForm.Meta`` are undefined names to mypy even
        though Django declares both at runtime, in
        ``django/contrib/auth/forms.py``. Silencing that with an ignore on the
        subclass would make the base ``Any`` and stop mypy checking the bodies
        of the two ``Meta`` classes below -- the classes whose whole job is to
        constrain the admin forms -- so the base is given a real type here
        instead. This exists at type-check time only; the ``else`` branch below
        inherits Django's own ``Meta`` and nothing about the forms changes at
        runtime.
        """

        model: type[Model]
        fields: Collection[str]
        error_messages: dict[str, dict[str, str | Promise]]

    _UserChangeFormMetaBase = _AdminFormMeta
    _UserCreationFormMetaBase = _AdminFormMeta
else:
    _UserChangeFormBase = admin_forms.UserChangeForm
    _UserChangeFormMetaBase = admin_forms.UserChangeForm.Meta
    _UserCreationFormMetaBase = admin_forms.UserCreationForm.Meta


class UserAdminChangeForm(_UserChangeFormBase):
    class Meta(_UserChangeFormMetaBase):
        model = User


class UserAdminCreationForm(admin_forms.AdminUserCreationForm):
    """
    Form for User Creation in the Admin Area.
    To change user signup, see UserSignupForm and UserSocialSignupForm.
    """

    class Meta(_UserCreationFormMetaBase):
        model = User
        error_messages = {
            "username": {"unique": _("This username has already been taken.")},
        }


# django-allauth ships no `py.typed` marker and no stub package exists for it on
# conda-forge, so `ignore_missing_imports` resolves every allauth name to `Any`
# and strict mode refuses the subclass. The base class is real; only its type is
# missing upstream. `warn_unused_ignores` removes these the moment allauth
# starts publishing types.
class UserSignupForm(SignupForm):  # type: ignore[misc]
    """
    Form that will be rendered on a user sign up section/screen.
    Default fields will be added automatically.
    Check UserSocialSignupForm for accounts created from social.
    """


class UserSocialSignupForm(SocialSignupForm):  # type: ignore[misc]
    """
    Renders the form when user has signed up using social accounts.
    Default fields will be added automatically.
    See UserSignupForm otherwise.
    """
