from django.db import models
from ai_engine.models import Interview

class Report(models.Model):
    interview = models.OneToOneField(Interview, on_delete=models.CASCADE, related_name='report')
    
    overall_score = models.FloatField(null=True, blank=True)
    overall_summary = models.TextField(blank=True, null=True)
    strengths = models.TextField(blank=True)
    weaknesses = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    
    resume_mismatch_flag = models.BooleanField(default=False)
    pdf_s3_url = models.URLField(max_length=500, blank=True)
    
    is_visible_to_candidate = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for Interview {self.interview.id}"
