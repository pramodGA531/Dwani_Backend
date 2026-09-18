from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import viewsets
from ai_engine.serializers.users_serializers import CustomTokenObtainPairSerializer, RecruiterRegistrationSerializer, UserProfileSerializer
from django.contrib.auth import get_user_model
from ai_engine.utils.notifications_utils import send_approval_email, send_rejection_email, send_new_recruiter_notification

User = get_user_model()

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class RecruiterRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RecruiterRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            # Notify the admin (you)
            send_new_recruiter_notification(user)
            return Response(
                {"message": "Registration successful. Your request has been sent to the admin for approval. You will receive an email once reviewed."},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AdminApproveRecruiterView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            user = User.objects.get(pk=pk, role='recruiter')
            if user.is_approved:
                return Response({"message": "Recruiter is already approved."}, status=status.HTTP_200_OK)
            user.is_approved = True
            user.save()
            send_approval_email(user)
            return Response({"message": f"Recruiter {user.email} approved. Notification email sent."})
        except User.DoesNotExist:
            return Response({"error": "Recruiter not found."}, status=status.HTTP_404_NOT_FOUND)

class AdminRejectRecruiterView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            user = User.objects.get(pk=pk, role='recruiter')
            reason = request.data.get('reason', '')
            send_rejection_email(user, reason)
            user.is_active = False  # Deactivate the account on rejection
            user.save()
            return Response({"message": f"Recruiter {user.email} rejected. Notification email sent."})
        except User.DoesNotExist:
            return Response({"error": "Recruiter not found."}, status=status.HTTP_404_NOT_FOUND)

class PendingRecruitersView(APIView):
    """Returns list of recruiters awaiting approval — for admin dashboard."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        pending = User.objects.filter(role='recruiter', is_approved=False, is_active=True)
        serializer = UserProfileSerializer(pending, many=True)
        return Response(serializer.data)

class CandidateViewSet(viewsets.ModelViewSet):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(role='candidate')

class RecruiterViewSet(viewsets.ModelViewSet):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get_queryset(self):
        return User.objects.filter(role='recruiter')

class FirstLoginPasswordResetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.is_first_login:
            return Response({"error": "Password has already been reset."}, status=status.HTTP_400_BAD_REQUEST)
        
        new_password = request.data.get('new_password')
        if not new_password:
            return Response({"error": "New password is required."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.is_first_login = False
        user.save()

        return Response({"message": "Password updated successfully."}, status=status.HTTP_200_OK)

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        user = request.user
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')

        if not current_password or not new_password:
            return Response({"error": "Both current_password and new_password are required."}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(current_password):
            return Response({"error": "Incorrect current password."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
        return Response({"message": "Password updated successfully."}, status=status.HTTP_200_OK)
