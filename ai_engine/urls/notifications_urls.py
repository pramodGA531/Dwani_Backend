from django.urls import path
from ai_engine.views.notifications_views import (
    NotificationListView,
    MarkAllReadView,
    MarkReadView,
    DeleteNotificationView,
    ClearAllNotificationsView
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('mark-all-read/', MarkAllReadView.as_view(), name='mark-all-read'),
    path('clear-all/', ClearAllNotificationsView.as_view(), name='clear-all'),
    path('<str:pk>/read/', MarkReadView.as_view(), name='mark-read'),
    path('<str:pk>/', DeleteNotificationView.as_view(), name='delete-notification'),
]
