from django.urls import path
from ai_engine.websockets.consumers import InterviewConsumer
from ai_engine.websockets.stt_consumer import STTConsumer

websocket_urlpatterns = [
    path('ws/interview/<str:session_token>/', InterviewConsumer.as_asgi()),
    path('ws/stt/<str:session_token>/', STTConsumer.as_asgi()),
]
