from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.routers import DefaultRouter
from ai_engine.views.users_views import (
    CustomTokenObtainPairView, RecruiterRegisterView,
    AdminApproveRecruiterView, AdminRejectRecruiterView,
    PendingRecruitersView, CandidateViewSet, RecruiterViewSet,
    FirstLoginPasswordResetView, CurrentUserView, ChangePasswordView
)

urlpatterns = [
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', CurrentUserView.as_view(), name='current_user'),
    path('register/recruiter/', RecruiterRegisterView.as_view(), name='register_recruiter'),
    path('admin/pending/', PendingRecruitersView.as_view(), name='pending_recruiters'),
    path('admin/approve/<int:pk>/', AdminApproveRecruiterView.as_view(), name='approve_recruiter'),
    path('admin/reject/<int:pk>/', AdminRejectRecruiterView.as_view(), name='reject_recruiter'),
    path('password-reset/first-login/', FirstLoginPasswordResetView.as_view(), name='first_login_password_reset'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
]

router = DefaultRouter()
router.register(r'candidates', CandidateViewSet, basename='candidate')
router.register(r'recruiters', RecruiterViewSet, basename='recruiter')

urlpatterns += router.urls
