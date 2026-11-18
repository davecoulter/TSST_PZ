from rest_framework import serializers
from YSE_App.access import GroupsField, RuleRelatedField, set_groups
from YSE_App.models import *
from django.contrib.auth.models import User, Group
from rest_framework.exceptions import PermissionDenied

class TransientPhotometrySerializer(serializers.HyperlinkedModelSerializer):
    transient = RuleRelatedField(queryset=Transient.objects.all(), view_name='transient-detail')
    instrument = serializers.HyperlinkedRelatedField(queryset=Instrument.objects.all(), view_name='instrument-detail', lookup_field="id")
    obs_group = serializers.HyperlinkedRelatedField(queryset=ObservationGroup.objects.all(), view_name='observationgroup-detail')

    host = RuleRelatedField(queryset=Host.objects.all(), allow_null=True, required=False, view_name='host-detail', lookup_field="id")
    followup = RuleRelatedField(queryset=TransientFollowup.objects.all(), allow_null=True, required=False, view_name='transientfollowup-detail')

    groups = GroupsField(many=True, allow_empty=False)  # #86: by name, the user's own data groups
    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = TransientPhotometry
        fields = "__all__"
        extra_kwargs = {
            'url': {'view_name': 'transientphotometry-detail', 'lookup_field': 'id'}
        }

    def create(self, validated_data):

        groups = validated_data.pop('groups')
        transient_photometry = TransientPhotometry.objects.create(**validated_data)
        transient_photometry.groups.set(groups)

        return transient_photometry

    def update(self, instance, validated_data):
        instance.transient_id = validated_data.get('transient', instance.transient)
        instance.obs_group_id = validated_data.get('obs_group', instance.obs_group)
        instance.instrument_id = validated_data.get('instrument', instance.instrument)
        instance.host_id = validated_data.get('host', instance.host)
        instance.followup_id = validated_data.get('followup', instance.followup)
        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)

        if 'groups' in validated_data:
            set_groups(instance, validated_data.pop('groups'), self.context['request'].user)

        instance.save()

        return instance

class HostPhotometrySerializer(serializers.HyperlinkedModelSerializer):
    host = RuleRelatedField(queryset=Host.objects.all(), view_name='host-detail', lookup_field="id")
    instrument = serializers.HyperlinkedRelatedField(queryset=Instrument.objects.all(), view_name='instrument-detail', lookup_field="id")
    obs_group = serializers.HyperlinkedRelatedField(queryset=ObservationGroup.objects.all(), view_name='observationgroup-detail')

    followup = RuleRelatedField(queryset=HostFollowup.objects.all(), allow_null=True, required=False, view_name='hostfollowup-detail')

    groups = GroupsField(many=True, allow_empty=False)  # #86: by name, the user's own data groups
    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = HostPhotometry
        fields = "__all__"
        extra_kwargs = {
            'url': {'view_name': 'hostphotometry-detail', 'lookup_field': 'id'}
        }

    def create(self, validated_data):

        groups = validated_data.pop('groups')
        host_photometry = HostPhotometry.objects.create(**validated_data)
        host_photometry.groups.set(groups)

        return host_photometry

    def update(self, instance, validated_data):
        instance.host_id = validated_data.get('host', instance.host)
        instance.obs_group_id = validated_data.get('obs_group', instance.obs_group)
        instance.instrument_id = validated_data.get('instrument', instance.instrument)
        instance.followup_id = validated_data.get('followup', instance.followup)
        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)

        if 'groups' in validated_data:
            set_groups(instance, validated_data.pop('groups'), self.context['request'].user)

        instance.save()

        return instance

class TransientPhotDataSerializer(serializers.HyperlinkedModelSerializer):
    photometry = RuleRelatedField(queryset=TransientPhotometry.objects.all(), view_name='transientphotometry-detail', lookup_field="id")
    band = serializers.HyperlinkedRelatedField(queryset=PhotometricBand.objects.all(), view_name='photometricband-detail', lookup_field="id")

    unit = serializers.HyperlinkedRelatedField(queryset=Unit.objects.all(), allow_null=True, required=False, view_name='unit-detail')
    data_quality = serializers.HyperlinkedRelatedField(queryset=DataQuality.objects.all(), many=True, view_name='dataquality-detail')
    
    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = TransientPhotData
        fields = "__all__"

    def create(self, validated_data):

        # Need to use a set operation to associate many-to-many
        dqs = validated_data.pop('data_quality')
        transient_phot_data = TransientPhotData.objects.create(**validated_data)
        transient_phot_data.data_quality.set(dqs)


        return transient_phot_data


    def update(self, instance, validated_data):
        instance.photometry = validated_data.get('photometry', instance.photometry)
        instance.band = validated_data.get('obs_group', instance.band)
        instance.unit = validated_data.get('unit', instance.unit)

        # Data Quality Flags are many-to-many.
        if 'data_quality' in validated_data.keys():

            # First Disassociate existing `Transient Tags`
            data_quality_flags = instance.data_quality.all()
            for dq in data_quality_flags:
                instance.data_quality.remove(dq)

            # Next get all dq flags from the form and associate
            dqs = validated_data.pop('data_quality')
            for dq in dqs:
                dq_result = DataQuality.objects.filter(pk=dq.id)
                if dq_result.exists():
                    d = dq_result.first()
                    instance.data_quality.add(d)

        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)
        instance.obs_date = validated_data.get('obs_date', instance.obs_date)
        instance.flux_zero_point = validated_data.get('flux_zero_point', instance.flux_zero_point)
        instance.flux = validated_data.get('flux', instance.flux)
        instance.flux_err = validated_data.get('flux_err', instance.flux_err)
        instance.mag = validated_data.get('mag', instance.mag)
        instance.mag_err = validated_data.get('mag_err', instance.mag_err)
        instance.forced = validated_data.get('forced', instance.forced)
        # instance.dq = validated_data.get('dq', instance.dq)
        instance.discovery_point = validated_data.get('discovery_point', instance.discovery_point)


        instance.save()

        return instance

class HostPhotDataSerializer(serializers.HyperlinkedModelSerializer):
    photometry = RuleRelatedField(queryset=HostPhotometry.objects.all(), view_name='hostphotometry-detail', lookup_field="id")
    band = serializers.HyperlinkedRelatedField(queryset=PhotometricBand.objects.all(), view_name='photometricband-detail', lookup_field="id")

    unit = serializers.HyperlinkedRelatedField(queryset=Unit.objects.all(), allow_null=True, required=False, view_name='unit-detail')
    data_quality = serializers.HyperlinkedRelatedField(queryset=DataQuality.objects.all(), many=True, view_name='dataquality-detail')

    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = HostPhotData
        fields = "__all__"

    def create(self, validated_data):

        # Need to use a set operation to associate many-to-many
        dqs = validated_data.pop('data_quality')
        host_phot_data = HostPhotData.objects.create(**validated_data)
        host_phot_data.data_quality.set(dqs)


        return host_phot_data

    def update(self, instance, validated_data):
        instance.photometry = validated_data.get('photometry', instance.photometry)
        instance.band = validated_data.get('obs_group', instance.band)
        instance.unit = validated_data.get('unit', instance.unit)

        # Data Quality Flags are many-to-many.
        if 'data_quality' in validated_data.keys():

            # First Disassociate existing `Transient Tags`
            data_quality_flags = instance.data_quality.all()
            for dq in data_quality_flags:
                instance.data_quality.remove(dq)

            # Next get all dq flags from the form and associate
            dqs = validated_data.pop('data_quality')
            for dq in dqs:
                dq_result = DataQuality.objects.filter(pk=dq.id)
                if dq_result.exists():
                    d = dq_result.first()
                    instance.data_quality.add(d)

        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)
        instance.obs_date = validated_data.get('obs_date', instance.obs_date)
        instance.flux_zero_point = validated_data.get('flux_zero_point', instance.flux_zero_point)
        instance.flux = validated_data.get('flux', instance.flux)
        instance.flux_err = validated_data.get('flux_err', instance.flux_err)
        instance.mag = validated_data.get('mag', instance.mag)
        instance.mag_err = validated_data.get('mag_err', instance.mag_err)
        instance.forced = validated_data.get('forced', instance.forced)


        instance.save()

        return instance

class TransientImageSerializer(serializers.HyperlinkedModelSerializer):
    phot_data = RuleRelatedField(queryset=TransientPhotData.objects.all(), view_name='transientphotdata-detail')

    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = TransientImage
        fields = "__all__"

    def create(self, validated_data):
        return TransientImage.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.phot_data_id = validated_data.get('phot_data', instance.phot_data)

        instance.img_file = validated_data.get('img_file', instance.img_file)
        instance.zero_point = validated_data.get('zero_point', instance.zero_point)
        instance.zero_point_err = validated_data.get('zero_point_err', instance.zero_point_err)
        instance.sky = validated_data.get('sky', instance.sky)
        instance.sky_rms = validated_data.get('sky_rms', instance.sky_rms)
        instance.dcmp_file = validated_data.get('dcmp_file', instance.dcmp_file)

        instance.save()

        return instance

class TransientDiffImageSerializer(serializers.HyperlinkedModelSerializer):
    phot_data = RuleRelatedField(queryset=TransientPhotData.objects.all(), view_name='transientphotdata-detail')

    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = TransientImage
        fields = "__all__"

    def create(self, validated_data):
        return TransientImage.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.phot_data_id = validated_data.get('phot_data', instance.phot_data)
        instance.valid_pixels = validated_data.get('valid_pixels', instance.valid_pixels)

        instance.postage_stamp_file = validated_data.get('postage_stamp_file', instance.postage_stamp_file)
        instance.postage_stamp_ref = validated_data.get('postage_stamp_ref', instance.postage_stamp_ref)
        instance.postage_stamp_diff = validated_data.get('postage_stamp_diff', instance.postage_stamp_diff)
        instance.postage_stamp_file_fits = validated_data.get('postage_stamp_file_fits', instance.postage_stamp_file_fits)
        instance.postage_stamp_ref_fits = validated_data.get('postage_stamp_ref_fits', instance.postage_stamp_ref_fits)
        instance.postage_stamp_diff_fits = validated_data.get('postage_stamp_diff_fits', instance.postage_stamp_diff_fits)

        instance.zero_point = validated_data.get('zero_point', instance.zero_point)
        instance.zero_point_err = validated_data.get('zero_point_err', instance.zero_point_err)
        instance.sky = validated_data.get('sky', instance.sky)
        instance.sky_rms = validated_data.get('sky_rms', instance.sky_rms)
        instance.dcmp_file = validated_data.get('dcmp_file', instance.dcmp_file)

        instance.save()

        return instance


class HostImageSerializer(serializers.HyperlinkedModelSerializer):
    phot_data = RuleRelatedField(queryset=HostPhotData.objects.all(), view_name='hostphotdata-detail')

    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = HostImage
        fields = "__all__"

    def create(self, validated_data):
        return HostImage.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.phot_data_id = validated_data.get('phot_data', instance.phot_data)

        instance.img_file = validated_data.get('img_file', instance.img_file)
        instance.zero_point = validated_data.get('zero_point', instance.zero_point)
        instance.zero_point_err = validated_data.get('zero_point_err', instance.zero_point_err)
        instance.sky = validated_data.get('sky', instance.sky)
        instance.sky_rms = validated_data.get('sky_rms', instance.sky_rms)
        instance.dcmp_file = validated_data.get('dcmp_file', instance.dcmp_file)

        instance.save()

        return instance
