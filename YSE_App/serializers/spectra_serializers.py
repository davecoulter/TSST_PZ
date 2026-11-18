from rest_framework import serializers
from YSE_App.access import GroupsField, RuleRelatedField, set_groups
from YSE_App.models import *
from django.contrib.auth.models import User
from rest_framework.exceptions import PermissionDenied

class TransientSpectrumSerializer(serializers.HyperlinkedModelSerializer):
    transient = RuleRelatedField(queryset=Transient.objects.all(), view_name='transient-detail')
    instrument = serializers.HyperlinkedRelatedField(queryset=Instrument.objects.all(), view_name='instrument-detail', lookup_field="id")
    obs_group = serializers.HyperlinkedRelatedField(queryset=ObservationGroup.objects.all(), view_name='observationgroup-detail')
    followup = RuleRelatedField(queryset=TransientFollowup.objects.all(), allow_null=True, required=False, view_name='transientfollowup-detail')
    unit = serializers.HyperlinkedRelatedField(queryset=Unit.objects.all(), allow_null=True, required=False, view_name='unit-detail')
    data_quality = serializers.HyperlinkedRelatedField(queryset=DataQuality.objects.all(), many=True, view_name='dataquality-detail')

    groups = GroupsField(many=True, allow_empty=False)  # #86: by name, the user's own data groups
    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = TransientSpectrum
        fields = "__all__"
        extra_kwargs = {
            'url': {'view_name': 'transientspectrum-detail', 'lookup_field': 'id'}
        }

    def create(self, validated_data):
        groups = validated_data.pop('groups')
        transient_spectrum = TransientSpectrum.objects.create(**validated_data)
        transient_spectrum.groups.set(groups)

        return transient_spectrum

    def update(self, instance, validated_data):
        instance.transient = validated_data.get('transient', instance.transient)
        instance.instrument = validated_data.get('instrument', instance.instrument)
        instance.obs_group = validated_data.get('obs_group', instance.obs_group)
        instance.followup = validated_data.get('followup', instance.followup)
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

        instance.ra = validated_data.get('ra', instance.ra)
        instance.dec = validated_data.get('dec', instance.dec)
        instance.spec_phase = validated_data.get('spec_phase', instance.spec_phase)
        instance.obs_date = validated_data.get('obs_date', instance.obs_date)
        instance.redshift = validated_data.get('redshift', instance.redshift)
        instance.redshift_err = validated_data.get('redshift_err', instance.redshift_err)
        instance.redshift_quality = validated_data.get('redshift_quality', instance.redshift_quality)

        instance.spec_plot_file = validated_data.get('spec_plot_file', instance.spec_plot_file)
        instance.spec_data_file = validated_data.get('spec_data_file', instance.spec_data_file)
        instance.spectrum_notes = validated_data.get('spectrum_notes', instance.spectrum_notes)
        instance.rlap = validated_data.get('rlap', instance.rlap)
        instance.snid_plot_file = validated_data.get('snid_plot_file', instance.snid_plot_file)

        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)

        if 'groups' in validated_data:
            set_groups(instance, validated_data.pop('groups'), self.context['request'].user)

        instance.save()

        return instance

class HostSpectrumSerializer(serializers.HyperlinkedModelSerializer):
    host = RuleRelatedField(queryset=Host.objects.all(), view_name='host-detail', lookup_field='id')
    instrument = serializers.HyperlinkedRelatedField(queryset=Instrument.objects.all(), view_name='instrument-detail', lookup_field="id")
    obs_group = serializers.HyperlinkedRelatedField(queryset=ObservationGroup.objects.all(), view_name='observationgroup-detail')
    followup = RuleRelatedField(queryset=HostFollowup.objects.all(), allow_null=True, required=False, view_name='hostfollowup-detail')
    unit = serializers.HyperlinkedRelatedField(queryset=Unit.objects.all(), allow_null=True, required=False, view_name='unit-detail')
    data_quality = serializers.HyperlinkedRelatedField(queryset=DataQuality.objects.all(), many=True, view_name='dataquality-detail')

    groups = GroupsField(many=True, allow_empty=False)  # #86: by name, the user's own data groups
    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = HostSpectrum
        fields = "__all__"
        extra_kwargs = {
            'url': {'view_name': 'hostspectrum-detail', 'lookup_field': 'id'}
        }

    def create(self, validated_data):
        groups = validated_data.pop('groups')
        host_spectrum = HostSpectrum.objects.create(**validated_data)
        host_spectrum.groups.set(groups)

        return host_spectrum

    def update(self, instance, validated_data):
        instance.host = validated_data.get('host', instance.host)
        instance.instrument = validated_data.get('instrument', instance.instrument)
        instance.obs_group = validated_data.get('obs_group', instance.obs_group)
        instance.followup = validated_data.get('followup', instance.followup)
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

        instance.ra = validated_data.get('ra', instance.ra)
        instance.dec = validated_data.get('dec', instance.dec)
        instance.obs_date = validated_data.get('obs_date', instance.obs_date)
        instance.redshift = validated_data.get('redshift', instance.redshift)
        instance.redshift_err = validated_data.get('redshift_err', instance.redshift_err)
        instance.redshift_quality = validated_data.get('redshift_quality', instance.redshift_quality)
        instance.tdr = validated_data.get('tdr', instance.tdr)
        instance.spec_plot_file = validated_data.get('spec_plot_file', instance.spec_plot_file)
        instance.spec_data_file = validated_data.get('spec_data_file', instance.spec_data_file)
        instance.spectrum_notes = validated_data.get('spectrum_notes', instance.spectrum_notes)

        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)

        if 'groups' in validated_data:
            set_groups(instance, validated_data.pop('groups'), self.context['request'].user)

        instance.save()

        return instance

class TransientSpecDataSerializer(serializers.HyperlinkedModelSerializer):
    spectrum = RuleRelatedField(queryset=TransientSpectrum.objects.all(), view_name='transientspectrum-detail', lookup_field="id")

    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = TransientSpecData
        fields = "__all__"

    def create(self, validated_data):
        transient_spec_data = TransientSpecData.objects.create(**validated_data)


        return transient_spec_data

    def update(self, instance, validated_data):
        instance.spectrum_id = validated_data.get('spectrum', instance.spectrum)
        instance.wavelength = validated_data.get('wavelength', instance.wavelength)
        instance.flux = validated_data.get('flux', instance.flux)
        instance.wavelength_err = validated_data.get('wavelength_err', instance.wavelength_err)
        instance.flux_err = validated_data.get('flux_err', instance.flux_err)
        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)


        instance.save()

        return instance

class HostSpecDataSerializer(serializers.HyperlinkedModelSerializer):
    spectrum = RuleRelatedField(queryset=HostSpectrum.objects.all(), view_name='hostspectrum-detail', lookup_field="id")

    created_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')
    modified_by = serializers.HyperlinkedRelatedField(read_only=True, view_name='user-detail')

    class Meta:
        model = HostSpecData
        fields = "__all__"

    def create(self, validated_data):
        host_spec_data = HostSpecData.objects.create(**validated_data)


        return host_spec_data

    def update(self, instance, validated_data):
        instance.spectrum_id = validated_data.get('spectrum', instance.spectrum)
        instance.wavelength = validated_data.get('wavelength', instance.wavelength)
        instance.flux = validated_data.get('flux', instance.flux)
        instance.wavelength_err = validated_data.get('wavelength_err', instance.wavelength_err)
        instance.flux_err = validated_data.get('flux_err', instance.flux_err)
        instance.modified_by_id = validated_data.get('modified_by', instance.modified_by)


        instance.save()

        return instance

