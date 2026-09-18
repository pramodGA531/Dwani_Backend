from django.urls import path, include

urlpatterns = [
    path('users/', include('ai_engine.urls.users_urls')),
    path('jobs/', include('ai_engine.urls.jobs_urls')),
    path('interviews/', include('ai_engine.urls.interviews_urls')),
    path('reports/', include('ai_engine.urls.reports_urls')),
    path('notifications/', include('ai_engine.urls.notifications_urls')),
    path('ai_engine/', include('ai_engine.urls.ai_engine_urls')),
]
