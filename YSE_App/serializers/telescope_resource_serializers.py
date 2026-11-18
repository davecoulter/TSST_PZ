"""Observing resources (telescope time) through the API (#86, #91). A resource follows the group rule:
it is read by users in its groups, written by curators in them (access.RulePermission and
TransientService.can_curate), and needs at least one of the writer's own data groups, never 'Public'."""
from rest_framework import serializers
from YSE_App.access import GroupsField, RuleRelatedField, set_groups
from YSE_App.models import *

# The fields every resource shares (TelescopeResource), copied one by one on update.
_SHARED = ('telescope', 'principal_investigator', 'begin_date_valid', 'end_date_valid', 'description')


class _ResourceSerializer(serializers.HyperlinkedModelSerializer):
	telescope = serializers.HyperlinkedRelatedField(queryset=Telescope.objects.all(), view_name='telescope-detail')
	principal_investigator = serializers.HyperlinkedRelatedField(queryset=PrincipalInvestigator.objects.all(), allow_null=True, required=False, view_name='principalinvestigator-detail')
	# #86: who may see and use it, by name: the writer's own data groups
	groups = GroupsField(many=True, allow_empty=False)

	created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
	modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

	own_fields = ()  # the model's fields beyond _SHARED

	def create(self, validated_data):
		groups = validated_data.pop('groups')
		resource = self.Meta.model.objects.create(**validated_data)
		resource.groups.set(groups)
		return resource

	def update(self, instance, validated_data):
		for field in _SHARED + self.own_fields:
			setattr(instance, field, validated_data.get(field, getattr(instance, field)))
		instance.modified_by_id = validated_data.get('modified_by', instance.modified_by_id)
		if 'groups' in validated_data:
			set_groups(instance, validated_data.pop('groups'), self.context['request'].user)
		instance.save()
		return instance


class ToOResourceSerializer(_ResourceSerializer):
	own_fields = ('awarded_too_hours', 'used_too_hours', 'awarded_too_triggers', 'used_too_triggers')

	class Meta:
		model = ToOResource
		fields = "__all__"


class QueuedResourceSerializer(_ResourceSerializer):
	own_fields = ('awarded_hours', 'used_hours')

	class Meta:
		model = QueuedResource
		fields = "__all__"


class ClassicalResourceSerializer(_ResourceSerializer):

	class Meta:
		model = ClassicalResource
		fields = "__all__"


class ClassicalObservingDateSerializer(serializers.HyperlinkedModelSerializer):
	# #86: only a resource the writer curates (TransientService.writable)
	resource = RuleRelatedField(queryset=ClassicalResource.objects.all(), view_name='classicalresource-detail')
	night_type = serializers.HyperlinkedRelatedField(queryset=ClassicalNightType.objects.all(), view_name='classicalnighttype-detail')

	created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
	modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

	class Meta:
		model = ClassicalObservingDate
		fields = "__all__"

	def create(self, validated_data):
		return ClassicalObservingDate.objects.create(**validated_data)

	def update(self, instance, validated_data):
		instance.resource = validated_data.get('resource', instance.resource)
		instance.night_type = validated_data.get('night_type', instance.night_type)
		instance.obs_date = validated_data.get('obs_date', instance.obs_date)
		instance.modified_by_id = validated_data.get('modified_by', instance.modified_by_id)
		instance.save()
		return instance
