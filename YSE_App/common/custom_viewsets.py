from rest_framework import mixins
from rest_framework import permissions
from rest_framework import viewsets

from YSE_App.common import custom_mixins

class ListCreateRetrieveUpdateViewSet(mixins.CreateModelMixin,
						mixins.RetrieveModelMixin,
						mixins.UpdateModelMixin,
						mixins.ListModelMixin,
						custom_mixins.UpdateModelMixin,
						viewsets.GenericViewSet):
	def perform_create(self, serializer):
		serializer.save(created_by=self.request.user, modified_by=self.request.user)

	def perform_update(self, serializer):
		serializer.save(modified_by=self.request.user.id)

	def perform_partial_update(self, serializer):
		serializer.save(modified_by=self.request.user.id)


class ListCreateRetrieveUpdateDestroyViewSet(ListCreateRetrieveUpdateViewSet,
						mixins.DestroyModelMixin):
	"""Standard viewset plus DELETE, restricted to admin (is_staff) users.

	Non-admin authenticated users are forbidden (403) from deleting; all other
	actions keep whatever ``permission_classes`` the concrete viewset declares.
	"""
	def get_permissions(self):
		if self.action == 'destroy':
			return [permissions.IsAdminUser()]
		return super().get_permissions()