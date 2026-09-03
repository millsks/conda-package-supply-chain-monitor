from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from django_service.users.models import User

from .serializers import UserSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.request import Request


class UserViewSet(RetrieveModelMixin, ListModelMixin, UpdateModelMixin, GenericViewSet[User]):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "username"

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[User]:
        """Restrict every action on this viewset to the requesting user's own row.

        Args:
            *args: Router arguments, unused.
            **kwargs: Router keyword arguments, unused.

        Returns:
            A queryset containing at most the requesting user.

        """
        assert isinstance(self.request.user.id, int)
        return self.queryset.filter(id=self.request.user.id)

    @action(detail=False)
    def me(self, request: Request) -> Response:
        """Return the requesting user's own serialized representation.

        Args:
            request: The authenticated request.

        Returns:
            A 200 response carrying the serialized user.

        """
        # The default permission class is IsAuthenticated, set in
        # config/settings/base.py, so an AnonymousUser never reaches this
        # action. The guard states that for the type checker, in the same shape
        # get_queryset above already uses.
        assert isinstance(request.user, User)
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(status=status.HTTP_200_OK, data=serializer.data)
