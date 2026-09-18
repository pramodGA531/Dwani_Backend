from django.contrib import admin
from ai_engine.models import (
    User, AdminProfile, RecruiterProfile, CandidateProfile, 
    AdminProxy, RecruiterProxy, CandidateProxy, 
    Job, Interview, Response, AnomalyLog, 
    CandidateReview, Report, Notification
)

# Register models
admin.site.register(User)
admin.site.register(AdminProfile)
admin.site.register(RecruiterProfile)
admin.site.register(CandidateProfile)
admin.site.register(AdminProxy)
admin.site.register(RecruiterProxy)
admin.site.register(CandidateProxy)
admin.site.register(Job)
admin.site.register(Interview)
admin.site.register(Response)
admin.site.register(AnomalyLog)
admin.site.register(CandidateReview)
admin.site.register(Report)
admin.site.register(Notification)
