from django.urls import path
from ai_engine.views.ai_engine_views import ScreeningProcessView

urlpatterns = [
    path('screening/process/', ScreeningProcessView.as_view(), name='screening_process'),
]
