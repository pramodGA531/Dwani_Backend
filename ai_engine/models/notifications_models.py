from django.db import models
from django.conf import settings

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('candidate_invited', 'Candidate Invited'),
        ('email_sent', 'Email Sent'),
        ('interview_started', 'Interview Started'),
        ('interview_completed', 'Interview Completed'),
        ('anomaly_detected', 'Proctoring Anomaly Detected'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        null=True,
        blank=True
    )
    title = models.CharField(max_length=255)
    detail = models.TextField()
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    unread = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'ai_engine'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.email if self.user else 'System'}"
