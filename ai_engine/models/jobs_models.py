from django.db import models
from django.conf import settings

class Job(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('draft', 'Draft'),
    )

    recruiter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='jobs')
    title = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    target_accent = models.CharField(max_length=50, default='neutral', help_text="Target accent: neutral, us, uk, in, au, agnostic")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
