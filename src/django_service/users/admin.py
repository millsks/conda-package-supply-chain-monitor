from typing import TYPE_CHECKING

from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.translation import gettext_lazy as _

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import User

if TYPE_CHECKING:
    # django-stubs makes ModelAdmin generic in the model it administers, but
    # the runtime class is not subscriptable and django-stubs is dev-only. See
    # the same pattern and its reasoning in django_service/users/views.py.
    _UserAdminBase = auth_admin.UserAdmin[User]
else:
    _UserAdminBase = auth_admin.UserAdmin

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


@admin.register(User)
class UserAdmin(_UserAdminBase):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password", "idp_subject")}),
        (_("Personal info"), {"fields": ("name", "email")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    # The identity key is displayed but never editable: an operator changing it
    # is account takeover (AD-11).
    readonly_fields = ["idp_subject"]
    list_display = ["username", "name", "is_superuser"]
    search_fields = ["name"]
