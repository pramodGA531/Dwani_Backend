from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from ai_engine.views.core_views import HealthCheckView, FileUploadView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('ai_engine.urls.users_urls')),
    path('api/v1/health/', HealthCheckView.as_view(), name='health_check'),
    path('api/v1/upload/', FileUploadView.as_view(), name='file_upload'),
    path('api/v1/interviews/', include('ai_engine.urls.interviews_urls')),
    path('api/v1/ai/', include('ai_engine.urls.ai_engine_urls')),
    path('api/v1/notifications/', include('ai_engine.urls.notifications_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
