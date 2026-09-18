from django.db import models
from django.conf import settings
from ai_engine.models import Job


class Interview(models.Model):
    """
    Represents one AI interview session.
    candidate_name is NO LONGER stored here — it is fetched from
    users_candidateprofile via interview.candidate.candidate_profile.full_name
    """
    STATUS_CHOICES = (
        ('pending',      'Pending'),
        ('scheduled',    'Scheduled'),
        ('in_progress',  'In Progress'),
        ('completed',    'Completed'),
        ('malpractice',  'Malpractice'),
        ('shortlisted',  'Shortlisted'),
        ('rejected',     'Rejected'),
        ('on_hold',      'On Hold'),
    )

    job       = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='interviews')
    candidate = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='interviews')

    session_token = models.CharField(max_length=255, unique=True, null=True, blank=True)
    link1         = models.URLField(max_length=500, blank=True)
    link2         = models.URLField(max_length=500, blank=True)
    link1_expiry  = models.DateTimeField(null=True, blank=True)

    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    resume_text  = models.TextField(blank=True, null=True)
    ats_score    = models.FloatField(null=True, blank=True)
    question_bank = models.JSONField(default=list, blank=True)
    skills       = models.JSONField(default=list, blank=True)
    highlights   = models.JSONField(default=list, blank=True)
    num_questions = models.IntegerField(default=5)
    created_at   = models.DateTimeField(auto_now_add=True)

    @property
    def candidate_name(self):
        """Resolve name from CandidateProfile — single source of truth."""
        try:
            return self.candidate.candidate_profile.full_name or self.candidate.email
        except Exception:
            return self.candidate.email

    def __str__(self):
        return f"{self.candidate.email} - {self.job.title}"


class Response(models.Model):
    interview      = models.ForeignKey(Interview, on_delete=models.CASCADE, related_name='responses')
    question_index = models.IntegerField()
    question_text  = models.TextField()
    answer_text    = models.TextField()

    relevance_score = models.FloatField(null=True, blank=True)
    accuracy_score  = models.FloatField(null=True, blank=True)
    clarity_score   = models.FloatField(null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Response {self.question_index} for Interview {self.interview.id}"


class AnomalyLog(models.Model):
    SEVERITY_CHOICES = (
        ('low',    'Low'),
        ('medium', 'Medium'),
        ('high',   'High'),
    )

    interview    = models.ForeignKey(Interview, on_delete=models.CASCADE, related_name='anomalies')
    event_type   = models.CharField(max_length=100)
    severity     = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='low')
    snapshot_url = models.URLField(max_length=500, blank=True)
    timestamp    = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} - Interview {self.interview.id}"


class CandidateReview(models.Model):
    """
    Feedback submitted by the candidate after their interview.
    candidate_email is NO LONGER stored here — resolved via interview.candidate.email.
    """
    interview           = models.OneToOneField(Interview, on_delete=models.CASCADE, related_name='review')
    overall_experience  = models.IntegerField(null=True, blank=True)   # 1-5 stars
    ai_clarity          = models.IntegerField(null=True, blank=True)
    ease_of_use         = models.IntegerField(null=True, blank=True)
    technical_stability = models.IntegerField(null=True, blank=True)
    comment             = models.TextField(blank=True)
    submitted_at        = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review by {self.interview.candidate.email}"

class Screening(models.Model):
    candidate_name = models.CharField(max_length=255, blank=True, null=True)
    candidate_email = models.EmailField()
    recruiter_id = models.CharField(max_length=255, blank=True, null=True)
    jd_url = models.URLField(max_length=1000, blank=True, null=True)
    resume_url = models.URLField(max_length=1000, blank=True, null=True)
    report_url = models.URLField(max_length=1000, blank=True, null=True)
    status = models.CharField(max_length=50, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.candidate_email
