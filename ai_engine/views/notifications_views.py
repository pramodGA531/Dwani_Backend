from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from ai_engine.models import Notification

class NotificationSerializer(serializers.ModelSerializer):
    formatted_time = serializers.SerializerMethodField()
    id = serializers.CharField()

    class Meta:
        model = Notification
        fields = ['id', 'title', 'detail', 'notification_type', 'unread', 'created_at', 'formatted_time']

    def get_formatted_time(self, obj):
        # Format like '2 hours ago', 'Just now', or standard date
        from django.utils.timezone import now
        diff = now() - obj.created_at
        if diff.days > 0:
            return obj.created_at.strftime('%b %d, %Y')
        if diff.seconds < 60:
            return "Just now"
        if diff.seconds < 3600:
            minutes = diff.seconds // 60
            return f"{minutes}m ago"
        hours = diff.seconds // 3600
        return f"{hours}h ago"

class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user)
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(user=request.user, unread=True).update(unread=False)
        return Response({"message": "All notifications marked as read."}, status=status.HTTP_200_OK)

class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
            notification.unread = False
            notification.save()
            return Response(NotificationSerializer(notification).data, status=status.HTTP_200_OK)
        except Notification.DoesNotExist:
            return Response({"error": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

class DeleteNotificationView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
            notification.delete()
            return Response({"message": "Notification deleted successfully."}, status=status.HTTP_200_OK)
        except Notification.DoesNotExist:
            return Response({"error": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

class ClearAllNotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        Notification.objects.filter(user=request.user).delete()
        return Response({"message": "All notifications cleared."}, status=status.HTTP_200_OK)
