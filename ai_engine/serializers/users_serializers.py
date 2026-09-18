from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from ai_engine.models import RecruiterProfile, CandidateProfile, AdminProfile

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        # Recruiters must be approved before they can log in
        if self.user.role == 'recruiter' and not self.user.is_approved:
            raise serializers.ValidationError("Your account is pending admin approval.")

        data['user'] = {
            'email': self.user.email,
            'role':  self.user.role,
        }
        return data


class RecruiterRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model  = User
        fields = ('email', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            role='recruiter',
            is_approved=False,
        )
        return user


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Flat serializer that merges base User fields with role-specific profile
    fields.  Profile fields are declared as writable CharField/IntegerField
    so DRF puts them in validated_data on PATCH.  to_representation() fills
    them from the profile table on the way out.
    """

    # Writable profile fields — NOT SerializerMethodField (which is read-only)
    full_name    = serializers.CharField(required=False, allow_blank=True, default='')
    company_name = serializers.CharField(required=False, allow_blank=True, default='')
    title        = serializers.CharField(required=False, allow_blank=True, default='')
    department   = serializers.CharField(required=False, allow_blank=True, default='')
    phone        = serializers.IntegerField(required=False, allow_null=True, default=None)
    location     = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model  = User
        fields = (
            'id', 'email', 'role', 'is_approved', 'created_at', 'is_active',
            'full_name', 'company_name', 'title', 'department', 'phone', 'location',
        )
        read_only_fields = ('id', 'email', 'role', 'created_at', 'is_approved', 'is_active')

    # ------------------------------------------------------------------
    # Read — pull profile data into the outgoing response
    # ------------------------------------------------------------------

    def _get_profile(self, user):
        if user.role == 'recruiter':
            return getattr(user, 'recruiter_profile', None)
        elif user.role == 'candidate':
            return getattr(user, 'candidate_profile', None)
        elif user.role == 'admin':
            return getattr(user, 'admin_profile', None)
        return None

    def to_representation(self, instance):
        """Merge base user fields with profile fields into one flat dict."""
        data = super().to_representation(instance)
        profile = self._get_profile(instance)

        # Override profile-field values from the actual profile table
        data['full_name']    = getattr(profile, 'full_name',    '') if profile else ''
        data['company_name'] = getattr(profile, 'company_name', '') if profile else ''
        data['title']        = getattr(profile, 'title',        '') if profile else ''
        data['department']   = getattr(profile, 'department',   '') if profile else ''
        data['phone']        = getattr(profile, 'phone',        None) if profile else None
        data['location']     = getattr(profile, 'location',     '') if profile else ''
        return data

    # ------------------------------------------------------------------
    # Write — save profile fields to the profile table on PATCH / PUT
    # ------------------------------------------------------------------

    PROFILE_FIELDS = {
        'recruiter': ('full_name', 'company_name', 'title', 'department', 'phone', 'location'),
        'candidate': ('full_name', 'phone', 'location'),
        'admin':     ('full_name', 'company_name', 'title', 'department', 'phone', 'location'),
    }

    PROFILE_MODELS = {
        'recruiter': RecruiterProfile,
        'candidate': CandidateProfile,
        'admin':     AdminProfile,
    }

    def update(self, instance, validated_data):
        allowed_fields = self.PROFILE_FIELDS.get(instance.role, ())
        ProfileModel   = self.PROFILE_MODELS.get(instance.role)

        # Separate profile fields from base User fields
        profile_data = {}
        for field in list(validated_data.keys()):
            if field in allowed_fields:
                profile_data[field] = validated_data.pop(field)

        # 1. Save any base User-level changes (none expected, but safe)
        instance = super().update(instance, validated_data)

        # 2. Save profile fields → profile table
        if profile_data and ProfileModel:
            profile = self._get_profile(instance)
            if not profile:
                profile = ProfileModel(user=instance)
                
            for field, value in profile_data.items():
                if hasattr(profile, field):
                    setattr(profile, field, value)
            profile.save()
            
            # Manually update the instance's cached property so to_representation sees the fresh data
            if instance.role == 'recruiter':
                instance.recruiter_profile = profile
            elif instance.role == 'candidate':
                instance.candidate_profile = profile
            elif instance.role == 'admin':
                instance.admin_profile = profile

        return instance
