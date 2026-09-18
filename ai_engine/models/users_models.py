from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('The Email field must be set'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_approved', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Central auth table. Stores ONLY authentication and permission data.
    All profile-specific data lives in AdminProfile, RecruiterProfile,
    or CandidateProfile linked via OneToOneField.
    """
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('recruiter', 'Recruiter'),
        ('candidate', 'Candidate'),
    )

    email       = models.EmailField(_('email address'), unique=True)
    role        = models.CharField(max_length=20, choices=ROLE_CHOICES, default='candidate')
    is_approved = models.BooleanField(default=False)   # For recruiters awaiting admin approval
    is_first_login = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return f"{self.email} ({self.role})"


# ---------------------------------------------------------------------------
# Profile tables — one per role
# ---------------------------------------------------------------------------

class AdminProfile(models.Model):
    """
    Profile for admin users.
    Table: users_adminprofile
    """
    user         = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin_profile', primary_key=True)
    full_name    = models.CharField(max_length=255, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    title        = models.CharField(max_length=255, blank=True)   # Job title
    department   = models.CharField(max_length=255, blank=True)
    phone        = models.BigIntegerField(null=True, blank=True)
    location     = models.CharField(max_length=255, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AdminProfile({self.user.email})"


class RecruiterProfile(models.Model):
    """
    Profile for recruiter users.
    Table: users_recruiterprofile
    """
    user         = models.OneToOneField(User, on_delete=models.CASCADE, related_name='recruiter_profile', primary_key=True)
    full_name    = models.CharField(max_length=255, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    title        = models.CharField(max_length=255, blank=True)   # Job title, e.g. "Senior Recruiter"
    department   = models.CharField(max_length=255, blank=True)
    phone        = models.BigIntegerField(null=True, blank=True)   # Stored as integer (no formatting noise)
    location     = models.CharField(max_length=255, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"RecruiterProfile({self.user.email})"


class CandidateProfile(models.Model):
    """
    Profile for candidate users.
    Table: users_candidateprofile
    """
    user        = models.OneToOneField(User, on_delete=models.CASCADE, related_name='candidate_profile', primary_key=True)
    full_name   = models.CharField(max_length=255, blank=True)
    phone       = models.BigIntegerField(null=True, blank=True)   # Stored as integer (no formatting noise)
    location    = models.CharField(max_length=255, blank=True)
    resume_text = models.TextField(blank=True, null=True)         # Optional cached resume text
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CandidateProfile({self.user.email})"


# ---------------------------------------------------------------------------
# Signals — auto-create the correct profile on User creation
# ---------------------------------------------------------------------------

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Automatically create the matching profile row when a User is saved."""
    if created:
        if instance.role == 'admin':
            AdminProfile.objects.get_or_create(user=instance)
        elif instance.role == 'recruiter':
            RecruiterProfile.objects.get_or_create(user=instance)
        elif instance.role == 'candidate':
            CandidateProfile.objects.get_or_create(user=instance)


# ---------------------------------------------------------------------------
# Proxy models (kept for Django admin compatibility)
# ---------------------------------------------------------------------------

class AdminProxy(User):
    class Meta:
        app_label = 'ai_engine'
        proxy = True
        verbose_name = 'Admin'
        verbose_name_plural = 'Admins'


class RecruiterProxy(User):
    class Meta:
        app_label = 'ai_engine'
        proxy = True
        verbose_name = 'Recruiter'
        verbose_name_plural = 'Recruiters'


class CandidateProxy(User):
    class Meta:
        app_label = 'ai_engine'
        proxy = True
        verbose_name = 'Candidate'
        verbose_name_plural = 'Candidates'
