from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from ai_engine.models import Job
from ai_engine.models import Interview
from ai_engine.utils.notifications_utils import send_html_email
from ai_engine.models import Notification
import uuid
import secrets
import string
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

class InviteCandidateView(APIView):
    permission_classes = [IsAuthenticated] # Assuming Recruiter

    def post(self, request):
        email = request.data.get('email')
        job_id = request.data.get('job_id')
        job_title = request.data.get('job_title') # Support for extracted jobs
        resume_text = request.data.get('resume_text', '') # Fetch resume text from request
        candidate_name = request.data.get('name', '') # Capture candidate name sent by UI

        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Handle job creation if job_id is not provided
        if not job_id:
            if not job_title:
                return Response({"error": "Job ID or Job Title is required"}, status=status.HTTP_400_BAD_REQUEST)
            job, _ = Job.objects.get_or_create(
                title=job_title, 
                recruiter=request.user,
                defaults={'description': f"Auto-generated job for {job_title}"}
            )
        else:
            try:
                job = Job.objects.get(id=job_id, recruiter=request.user)
            except Job.DoesNotExist:
                return Response({"error": "Job not found or unauthorized"}, status=status.HTTP_404_NOT_FOUND)

        user, created = User.objects.get_or_create(email=email, defaults={'role': 'candidate'})

        if not created and user.role == 'recruiter':
            return Response({"error": "This email belongs to an existing recruiter and cannot be invited as a candidate."}, status=status.HTTP_400_BAD_REQUEST)

        # Always generate a fresh temp password on every invite
        # so the candidate always receives working credentials in their email
        alphabet = string.ascii_letters + string.digits
        temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
        user.set_password(temp_password)
        user.is_first_login = True
        user.role = 'candidate'
        user.is_active = True
        user.save()

        # Create Interview Session
        session_token = str(uuid.uuid4())
        # Link 1: time-bound candidate interview link
        invite_link = f"{settings.FRONTEND_URL}/interview/{session_token}"
        # Link 2: permanent recruiter tracking link
        tracking_link = f"{settings.FRONTEND_URL}/recruiter/interviews/{session_token}/track"

        ats_score = request.data.get('ats_score')
        skills = request.data.get('skills', [])
        highlights = request.data.get('highlights', [])
        question_count = int(request.data.get('questionCount', 5))

        interview = Interview.objects.create(
            job=job,
            candidate=user,
            session_token=session_token,
            link1=invite_link,
            link2=tracking_link,
            link1_expiry=timezone.now() + timedelta(hours=settings.SESSION_LINK_EXPIRY_HOURS),
            resume_text=resume_text,
            ats_score=ats_score,
            skills=skills,
            highlights=highlights,
            num_questions=question_count
        )

        # Store candidate name in the normalised CandidateProfile table
        if candidate_name:
            from ai_engine.models import CandidateProfile
            profile, _ = CandidateProfile.objects.get_or_create(user=user)
            if not profile.full_name:
                profile.full_name = candidate_name
                profile.save()

        # Send Email with credentials and both links
        context = {
            'job_title': job.title,
            'email': user.email,
            'invite_link': invite_link,
            'tracking_link': tracking_link,
        }
        send_html_email("Interview Invitation", "emails/invite_email.html", context, [user.email])

        # Create In-App Notifications
        try:
            Notification.objects.create(
                user=request.user,
                title="Candidate Account Created",
                detail=f"Candidate account created for {user.email}.",
                notification_type="candidate_invited"
            )
            Notification.objects.create(
                user=request.user,
                title="Invitation Email Sent",
                detail=f"Interview invitation email successfully sent to {user.email} for the {job.title} role.",
                notification_type="email_sent"
            )
        except Exception as e:
            print(f"[NOTIFICATION ERROR] Failed to create candidate invitation notification: {e}")

        return Response({
            "message": "Candidate invited successfully",
            "interview_id": str(interview.id),
            "session_token": session_token,
            "invite_link": invite_link,
            "tracking_link": tracking_link,
        }, status=status.HTTP_201_CREATED)

class CandidateDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        email = request.GET.get('email')
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Delete from local Storage and Screening model
        from ai_engine.models.interviews_models import Screening
        from django.core.files.storage import default_storage
        try:
            screenings = Screening.objects.filter(candidate_email=email)
            for screening in screenings:
                def get_path(url):
                    if not url: return None
                    parts = url.split(settings.MEDIA_URL) if hasattr(settings, 'MEDIA_URL') and settings.MEDIA_URL in url else url.split('/media/')
                    return parts[1] if len(parts) > 1 else url

                for url in [screening.resume_url, screening.jd_url, screening.report_url]:
                    path = get_path(url)
                    if path and default_storage.exists(path):
                        default_storage.delete(path)
                
            screenings.delete()
        except Exception as e:
            print(f"Error deleting from local DB/Storage: {e}")

        # 2. Delete from Postgres User table (Cascades to Profiles, Interviews, Reports, etc.)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            # We enforce role='candidate' so recruiter doesn't accidentally delete another recruiter
            users = User.objects.filter(email=email, role='candidate')
            for user in users:
                user.delete()
        except Exception as e:
            print(f"Error deleting user from Postgres: {e}")
            return Response({"error": "Failed to delete candidate data from database."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_204_NO_CONTENT)

import threading
from django.core.cache import cache

def finalize_abandoned(interview_id):
    try:
        from ai_engine.models import Interview
        if cache.get(f"abandon_pending_{interview_id}"):
            interview = Interview.objects.get(id=interview_id)
            if interview.status == 'in_progress':
                interview.status = 'malpractice'
                interview.save()
                generate_interview_report(interview)
    except Exception as e:
        print(f"Error in finalize_abandoned: {e}")

class AbandonSessionView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        token = request.data.get('token')
        if token:
            try:
                from ai_engine.models import Interview
                interview = Interview.objects.get(session_token=token)
                cache.set(f"abandon_pending_{interview.id}", True, 15)
                threading.Timer(10.0, finalize_abandoned, args=[interview.id]).start()
            except Interview.DoesNotExist:
                pass
        return Response(status=status.HTTP_200_OK)

class ValidateSessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            interview = Interview.objects.get(session_token=token)
            
            # Check Expiry
            if interview.link1_expiry and interview.link1_expiry < timezone.now():
                return Response({"error": "Session link has expired"}, status=status.HTTP_403_FORBIDDEN)
            
            # Block retests for completed or malpractice/terminated sessions
            if interview.status in ['completed', 'malpractice', 'shortlisted', 'rejected']:
                return Response({"error": "This interview link has already been used and is no longer valid."}, status=status.HTTP_403_FORBIDDEN)
            
            # If the session is currently in progress, only allow joining if it's a page refresh (same tab)
            if interview.status == 'in_progress':
                is_refresh = request.GET.get('is_refresh') == 'true'
                if not is_refresh:
                    return Response({"error": "This interview session is already active or was abandoned. You cannot rejoin it from a new window."}, status=status.HTTP_403_FORBIDDEN)
                else:
                    from django.core.cache import cache
                    cache.delete(f"abandon_pending_{interview.id}")
            
            # Try to extract name if not already set
            if not interview.candidate_name and interview.resume_text:
                try:
                    from ai_engine.services.groq_service import GroqAIService
                    ai_service = GroqAIService()
                    jd_text = interview.job.description if interview.job else ""
                    screening_data = ai_service.process_screening(jd_text, interview.resume_text)
                    extracted_name = screening_data.get('candidate_details', {}).get('name')
                    if extracted_name and extracted_name != "N/A":
                        interview.candidate_name = extracted_name
                        interview.save()
                except Exception as e:
                    print(f"Name extraction error in validate session: {e}")

            refresh = RefreshToken.for_user(interview.candidate)
            return Response({
                "valid": True,
                "candidate_name": interview.candidate_name or interview.candidate.email,
                "job_title": interview.job.title,
                "status": interview.status,
                "interview_id": str(interview.id),
                "recruiter_name": interview.job.recruiter.email,
                "access_token": str(refresh.access_token)
            }, status=status.HTTP_200_OK)

            
        except Interview.DoesNotExist:
            return Response({"error": "Invalid session token"}, status=status.HTTP_404_NOT_FOUND)

from ai_engine.services.groq_service import GroqAIService
from ai_engine.models import Interview, Response as InterviewResponse

class StartInterviewView(APIView):
    permission_classes = [AllowAny] # Session token provides security

    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response({"error": "Session token required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            interview = Interview.objects.get(session_token=token)
            
            # Create In-App Notification: Interview Started (on transition from pending)
            if interview.status == 'pending':
                try:
                    Notification.objects.create(
                        user=interview.job.recruiter,
                        title="Interview Started",
                        detail=f"{interview.candidate_name or interview.candidate.email} has started the live interview session for {interview.job.title}.",
                        notification_type="interview_started"
                    )
                except Exception as e:
                    print(f"[NOTIFICATION ERROR] Failed to create interview started notification: {e}")

            ai_service = GroqAIService()

            # 1. Extract candidate name from resume if not already set
            if not interview.candidate_name and interview.resume_text:
                jd_text = interview.job.description if interview.job else ""
                screening_data = ai_service.process_screening(jd_text, interview.resume_text)
                candidate_info = screening_data.get('candidate_details', {})
                extracted_name = candidate_info.get('name')
                if extracted_name and extracted_name != "N/A":
                    interview.candidate_name = extracted_name
                    interview.save()

            # 2. Generate first question if bank is empty
            if not interview.question_bank:
                first_q = ai_service.generate_next_question(interview)
                interview.question_bank = [{"text": first_q, "index": 0}]
                interview.status = 'in_progress'
                interview.save()
                
                # Broadcast first question to live monitoring
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'interview_{interview.session_token}',
                    {
                        'type': 'question_event',
                        'question_index': 0,
                        'question_text': first_q
                    }
                )
            
            # 3. Fetch existing responses if any to support page reloads
            existing_responses = InterviewResponse.objects.filter(interview=interview).order_by('question_index')
            answers_dict = {str(r.question_index): r.answer_text for r in existing_responses}

            return Response({
                "questions": interview.question_bank,
                "answers": answers_dict,
                "candidate_name": interview.candidate_name or interview.candidate.email,
                "job_title": interview.job.title,
                "status": interview.status,
                "num_questions": interview.num_questions
            }, status=status.HTTP_200_OK)

        except Interview.DoesNotExist:
            return Response({"error": "Invalid session token"}, status=status.HTTP_404_NOT_FOUND)


def generate_interview_report(interview):
    try:
        from ai_engine.models import Report
        from ai_engine.services.groq_service import GroqAIService
        
        ai_service = GroqAIService()
        responses = InterviewResponse.objects.filter(interview=interview)
        
        status_note = ""
        if interview.status == 'malpractice':
            status_note = "\nCRITICAL NOTE: This interview was TERMINATED EARLY due to suspected malpractice (e.g. cheating, tab switching, multiple people). You must give an overall score of 0, and strongly recommend 'Reject'."
            
        if not responses.exists() and interview.status == 'malpractice':
            responses_text = "No responses provided (Interview terminated early)."
        else:
            responses_text = "\n".join([f"Q: {r.question_text}\nA: {r.answer_text}\nScore: {r.relevance_score+r.accuracy_score+r.clarity_score}/300" for r in responses])
        
        report_prompt = f"""
You are a Senior Talent Acquisition Lead. Summarize this technical interview.
Job Description: {interview.job.description[:500]}
Responses:
{responses_text}{status_note}

Provide:
1. Overall Score (0-100)
2. Overall Summary (brief 2-3 sentence overview of the performance)
3. Strengths
4. Weaknesses
5. Recommendation (Hire/Reject/Maybe)

Return ONLY a JSON object:
{{
    "overall_score": 85,
    "overall_summary": "A brief overview...",
    "strengths": "List strengths",
    "weaknesses": "List weaknesses",
    "recommendation": "Hire"
}}
"""
        report_data = ai_service._chat_json(report_prompt)
        report_obj = Report.objects.create(
            interview=interview,
            overall_score=report_data.get('overall_score', 0),
            overall_summary=report_data.get('overall_summary', 'No summary generated.'),
            strengths=report_data.get('strengths', ''),
            weaknesses=report_data.get('weaknesses', ''),
            recommendation=report_data.get('recommendation', 'Reject'),
            is_visible_to_candidate=True
        )

        try:
            from ai_engine.services.local_storage_service import local_storage_service
            import uuid as _uuid
            candidate_email = interview.candidate.email
            unique_id = str(_uuid.uuid4())
            report_remote_path = f"reports/{unique_id}_{interview.id}_report.json"

            all_responses = InterviewResponse.objects.filter(interview=interview).order_by('question_index')
            supabase_report_payload = {
                "interview_id": str(interview.id),
                "candidate_name": interview.candidate_name or candidate_email,
                "candidate_email": candidate_email,
                "job_title": interview.job.title if interview.job else "",
                "overall_score": report_data.get('overall_score'),
                "overall_summary": report_data.get('overall_summary'),
                "strengths": report_data.get('strengths'),
                "weaknesses": report_data.get('weaknesses'),
                "recommendation": report_data.get('recommendation'),
                "status": interview.status,
                "responses": [
                    {
                        "question_index": r.question_index,
                        "question": r.question_text,
                        "answer": r.answer_text,
                        "relevance_score": r.relevance_score,
                        "accuracy_score": r.accuracy_score,
                        "clarity_score": r.clarity_score,
                    }
                    for r in all_responses
                ]
            }

            report_url = local_storage_service.upload_json_report(
                supabase_report_payload,
                report_remote_path
            )

            local_storage_service.update_screening_with_report(candidate_email, report_url)
            report_obj.pdf_s3_url = report_url
            report_obj.save()
            print(f"Report uploaded to Supabase: {report_url}")
        except Exception as supabase_err:
            print(f"Supabase report upload failed: {supabase_err}")
    except Exception as e:
        print(f"Error generating report: {e}")

class SubmitAnswerView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        interview_id = request.data.get('interview_id')
        question_text = request.data.get('question_text')
        answer_text = request.data.get('answer_text')
        question_index = request.data.get('question_index', 0)
        token = request.data.get('token')
        force_finish = request.data.get('force_finish', False)

        try:
            if token:
                interview = Interview.objects.get(session_token=token)
            else:
                if request.user and request.user.is_authenticated:
                    interview = Interview.objects.get(id=interview_id, candidate=request.user)
                else:
                    return Response({"error": "Session token or authentication required"}, status=status.HTTP_401_UNAUTHORIZED)
            
            ai_service = GroqAIService()

            import concurrent.futures

            next_index = question_index + 1
            evaluation = {}
            next_q_text = None

            # Run evaluation and next question generation concurrently to save time
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future_eval = executor.submit(ai_service.evaluate_answer, question_text, answer_text)
                
                # We only need a next question if we are not at the end of the interview
                future_next_q = None
                if next_index < interview.num_questions and not force_finish:
                    future_next_q = executor.submit(
                        ai_service.generate_next_question, 
                        interview, 
                        previous_answer=answer_text, 
                        previous_score=None # Pass None for now since evaluation is running in parallel
                    )
                
                try:
                    evaluation = future_eval.result(timeout=15)
                except Exception as e:
                    print(f"Error in evaluate_answer thread: {e}")
                    evaluation = {
                        "relevance_score": 50,
                        "accuracy_score": 50,
                        "clarity_score": 50,
                        "overall_score": 50,
                        "feedback": "Could not evaluate due to a timeout or error."
                    }

                if future_next_q:
                    try:
                        next_q_text = future_next_q.result(timeout=15)
                    except Exception as e:
                        print(f"Error in generate_next_question thread: {e}")
                        next_q_text = "Can you elaborate on your experience related to the job description?"
            
            # 2. Save Response
            InterviewResponse.objects.create(
                interview=interview,
                question_index=question_index,
                question_text=question_text,
                answer_text=answer_text,
                relevance_score=evaluation.get('relevance_score'),
                accuracy_score=evaluation.get('accuracy_score'),
                clarity_score=evaluation.get('clarity_score')
            )

            # Broadcast Answer to Live Monitoring
            channel_layer = get_channel_layer()
            room_group_name = f'interview_{interview.session_token}'
            
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'answer_event',
                    'question_index': question_index,
                    'question_text': question_text,
                    'answer_text': answer_text,
                    'evaluation': evaluation
                }
            )

            # 3. Handle next question or completion
            if next_index < interview.num_questions and not force_finish:
                # Update question bank
                interview.question_bank.append({"text": next_q_text, "index": next_index})
                interview.save()
                
                # Broadcast Next Question to Live Monitoring
                async_to_sync(channel_layer.group_send)(
                    room_group_name,
                    {
                        'type': 'question_event',
                        'question_index': next_index,
                        'question_text': next_q_text
                    }
                )

                return Response({
                    "next_question": next_q_text,
                    "index": next_index,
                    "evaluation": evaluation,
                    "is_complete": False
                }, status=status.HTTP_200_OK)
            else:
                interview.status = 'completed'
                interview.save()
                
                # Broadcast End Session
                async_to_sync(channel_layer.group_send)(
                    room_group_name,
                    {
                        'type': 'end_session_event',
                        'message': 'Session completed.'
                    }
                )

                # Generate Final Report asynchronously after transaction commits
                import threading
                from django.db import transaction
                transaction.on_commit(lambda: threading.Thread(target=generate_interview_report, args=[interview]).start())

                # Create In-App Notification: Interview Completed
                try:
                    from ai_engine.models import Report
                    score = 0
                    try:
                        report = Report.objects.get(interview=interview)
                        score = int(report.overall_score or 0)
                    except Report.DoesNotExist:
                        pass
                    
                    Notification.objects.create(
                        user=interview.job.recruiter,
                        title="AI Interview Completed",
                        detail=f"{interview.candidate_name or interview.candidate.email} completed the {interview.job.title} interview. Score: {score}%",
                        notification_type="interview_completed"
                    )
                except Exception as e:
                    print(f"[NOTIFICATION ERROR] Failed to create interview completed notification: {e}")

                return Response({
                    "is_complete": True,
                    "evaluation": evaluation,
                    "interview_id": str(interview.id),
                    "message": "Interview completed successfully"
                }, status=status.HTTP_200_OK)

        except Interview.DoesNotExist:
            return Response({"error": "Interview not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"SubmitAnswerView general error: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GetResultsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        interview_id = request.query_params.get('interview_id')
        token = request.query_params.get('token')
        user = request.user
        
        try:
            if token:
                interview = Interview.objects.get(session_token=token)
            elif interview_id:
                if user and user.is_authenticated and user.role == 'recruiter':
                    interview = Interview.objects.get(id=interview_id, job__recruiter=user)
                elif user and user.is_authenticated:
                    interview = Interview.objects.get(id=interview_id, candidate=user)
                else:
                    return Response({"error": "Authentication or session token required"}, status=status.HTTP_401_UNAUTHORIZED)
            else:
                if user and user.is_authenticated:
                    if user.role == 'recruiter':
                        interview = Interview.objects.filter(job__recruiter=user, status='completed').latest('created_at')
                    else:
                        interview = Interview.objects.filter(candidate=user, status='completed').latest('created_at')
                else:
                    return Response({"error": "Authentication required"}, status=status.HTTP_401_UNAUTHORIZED)
        except Interview.DoesNotExist:
            return Response({"error": "Interview not found"}, status=status.HTTP_404_NOT_FOUND)

        # Fetch Q&A responses
        responses = InterviewResponse.objects.filter(interview=interview).order_by('question_index')
        qa_list = [
            {
                "question": r.question_text,
                "answer": r.answer_text,
                "relevance_score": r.relevance_score,
                "accuracy_score": r.accuracy_score,
                "clarity_score": r.clarity_score,
            }
            for r in responses
        ]

        # Fetch the AI-generated report
        report_data = {}
        try:
            report = interview.report
            report_data = {
                "overall_score": report.overall_score,
                "overall_summary": report.overall_summary,
                "strengths": report.strengths,
                "weaknesses": report.weaknesses,
                "recommendation": report.recommendation,
            }
        except Exception:
            pass

        return Response({
            "interview_id": str(interview.id),
            "candidate_name": interview.candidate_name or interview.candidate.email,
            "candidate_email": interview.candidate.email,
            "job_title": interview.job.title if interview.job else "",
            "status": interview.status,
            "skills": interview.skills,
            "highlights": interview.highlights,
            "created_at": interview.created_at,
            "responses": qa_list,
            **report_data,
        }, status=status.HTTP_200_OK)


from rest_framework import viewsets, serializers

class InterviewSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    job_title = serializers.CharField(source='job.title', read_only=True)
    candidate_email = serializers.CharField(source='candidate.email', read_only=True)
    # candidate_name is a property on Interview — resolved from CandidateProfile
    candidate_name = serializers.SerializerMethodField()

    def get_candidate_name(self, obj):
        return obj.candidate_name  # calls the @property

    class Meta:
        model = Interview
        fields = ['id', 'job_title', 'candidate_email', 'candidate_name', 'status', 'ats_score', 'created_at', 'link1_expiry', 'skills', 'highlights', 'resume_text']
        read_only_fields = ['id', 'job_title', 'candidate_email', 'candidate_name', 'ats_score', 'created_at', 'link1_expiry']

class InterviewViewSet(viewsets.ModelViewSet):
    serializer_class = InterviewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'recruiter':
            return Interview.objects.filter(job__recruiter=user)
        elif user.role == 'candidate':
            return Interview.objects.filter(candidate=user)
        return Interview.objects.none()


class SubmitReviewView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from ai_engine.models import CandidateReview
        interview_id = request.data.get('interview_id')
        token = request.data.get('token')

        if not interview_id and not token:
            return Response({"error": "interview_id or token is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if token:
                interview = Interview.objects.get(session_token=token)
            else:
                if request.user and request.user.is_authenticated:
                    interview = Interview.objects.get(id=interview_id, candidate=request.user)
                else:
                    return Response({"error": "Authentication or token required"}, status=status.HTTP_401_UNAUTHORIZED)
        except Interview.DoesNotExist:
            return Response({"error": "Interview not found"}, status=status.HTTP_404_NOT_FOUND)

        # candidate_email is no longer stored — resolved from interview.candidate FK
        review, _ = CandidateReview.objects.update_or_create(
            interview=interview,
            defaults={
                'overall_experience':  request.data.get('overall_experience'),
                'ai_clarity':          request.data.get('ai_clarity'),
                'ease_of_use':         request.data.get('ease_of_use'),
                'technical_stability': request.data.get('technical_stability'),
                'comment':             request.data.get('comment', ''),
            }
        )
        return Response({"message": "Review submitted successfully"}, status=status.HTTP_201_CREATED)


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role != 'recruiter':
            return Response({"error": "Only recruiters can view dashboard statistics."}, status=status.HTTP_403_FORBIDDEN)
        
        # 1. Total Jobs
        total_jobs = Job.objects.filter(recruiter=user).count()

        # 2. Total Candidates / Interviews
        total_candidates = Interview.objects.filter(job__recruiter=user).count()

        # 3. Active Interviews
        active_interviews = Interview.objects.filter(
            job__recruiter=user, 
            status__in=['in_progress', 'scheduled', 'pending']
        ).count()

        # 4. Recent Activity
        recent_interviews = Interview.objects.filter(job__recruiter=user).order_by('-created_at')[:10]
        
        activities = []
        for interview in recent_interviews:
            has_report = hasattr(interview, 'report')
            name = interview.candidate_name or interview.candidate.email
            
            # Map status/type
            if interview.status == 'completed':
                score_str = f" scored {round(interview.report.overall_score)}%" if (has_report and interview.report.overall_score) else ""
                desc = f"{name}{score_str} for the {interview.job.title} role."
                title = "AI Interview Completed"
                icon = "check_circle"
                icon_color = "text-emerald-600"
                icon_bg = "bg-emerald-50"
            elif interview.status == 'in_progress':
                desc = f"{name} is currently taking the interview for {interview.job.title}."
                title = "Interview Started"
                icon = "video_chat"
                icon_color = "text-violet-600"
                icon_bg = "bg-violet-50"
            elif interview.status == 'malpractice':
                desc = f"System warning: malpractice suspected for candidate {name}."
                title = "System Warning"
                icon = "warning"
                icon_color = "text-amber-600"
                icon_bg = "bg-amber-50"
            else:
                desc = f"Interview invite link generated and email sent to {name}."
                title = "Interview Invited"
                icon = "mail"
                icon_color = "text-blue-600"
                icon_bg = "bg-blue-50"

            # Dynamic time display helper
            diff = timezone.now() - interview.created_at
            if diff.days == 0:
                if diff.seconds < 3600:
                    time_str = f"{max(1, diff.seconds // 60)} minutes ago"
                else:
                    time_str = f"{diff.seconds // 3600} hours ago"
            elif diff.days == 1:
                time_str = "Yesterday"
            else:
                time_str = f"{diff.days} days ago"

            activities.append({
                "title": title,
                "detail": desc,
                "time": time_str,
                "icon": icon,
                "iconColor": icon_color,
                "iconBg": icon_bg
            })

        return Response({
            "total_jobs": total_jobs,
            "total_candidates": total_candidates,
            "active_interviews": active_interviews,
            "activities": activities
        }, status=status.HTTP_200_OK)


class ReportsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        user = request.user
        if user.role != 'recruiter':
            return Response({"error": "Only recruiters can view reports."}, status=status.HTTP_403_FORBIDDEN)
        
        from ai_engine.models import Report

        if pk:
            try:
                try:
                    report = Report.objects.select_related('interview', 'interview__job', 'interview__candidate').get(
                        interview_id=pk, 
                        interview__job__recruiter=user
                    )
                except (Report.DoesNotExist, ValueError):
                    report = Report.objects.select_related('interview', 'interview__job', 'interview__candidate').get(
                        id=pk, 
                        interview__job__recruiter=user
                    )
                
                responses = InterviewResponse.objects.filter(interview=report.interview).order_by('question_index')
                
                transcript = []
                for r in responses:
                    t_str = r.timestamp.strftime('%I:%M %p') if r.timestamp else ""
                    transcript.append({
                        "id": f"q-{r.id}",
                        "role": "ai",
                        "text": r.question_text,
                        "timestamp": t_str
                    })
                    transcript.append({
                        "id": f"a-{r.id}",
                        "role": "candidate",
                        "text": r.answer_text,
                        "timestamp": t_str
                    })

                def clean_list(text):
                    if not text:
                        return []
                    items = []
                    for line in text.split('\n'):
                        line = line.strip().lstrip('-').lstrip('*').lstrip('1234567890.').strip()
                        if line:
                            items.append(line)
                    return items

                total_responses = responses.count()
                if total_responses > 0:
                    avg_relevance = sum(r.relevance_score or 0 for r in responses) / total_responses
                    avg_accuracy = sum(r.accuracy_score or 0 for r in responses) / total_responses
                    avg_clarity = sum(r.clarity_score or 0 for r in responses) / total_responses
                else:
                    avg_relevance = report.overall_score or 80.0
                    avg_accuracy = report.overall_score or 80.0
                    avg_clarity = report.overall_score or 80.0

                scores_dict = {
                    "technical": round(avg_accuracy),
                    "communication": round(avg_clarity),
                    "confidence": round(avg_relevance),
                    "problem_solving": round(avg_accuracy),
                    "behavioral": round(avg_relevance)
                }

                return Response({
                    "id": str(report.interview.id),
                    "candidate_name": report.interview.candidate_name or report.interview.candidate.email,
                    "candidate_email": report.interview.candidate.email,
                    "job_title": report.interview.job.title,
                    "overall_score": report.overall_score,
                    "overall_summary": report.overall_summary,
                    "recommendation": report.recommendation,
                    "interview_status": report.interview.status,
                    "strengths": clean_list(report.strengths),
                    "weaknesses": clean_list(report.weaknesses),
                    "transcript": transcript,
                    "scores": scores_dict,
                    "pdf_url": report.pdf_s3_url,
                    "created_at": report.created_at.strftime('%Y-%m-%d')
                }, status=status.HTTP_200_OK)
            except Report.DoesNotExist:
                return Response({"error": "Report not found"}, status=status.HTTP_404_NOT_FOUND)
        
        else:
            reports = Report.objects.select_related('interview', 'interview__job', 'interview__candidate').filter(
                interview__job__recruiter=user
            ).order_by('-created_at')
            
            reports_list = []
            for r in reports:
                score = r.overall_score or 0
                if score >= 85:
                    match_tier = "Expert Match"
                elif score >= 70:
                    match_tier = "Strong Match"
                elif score >= 50:
                    match_tier = "Good Match"
                else:
                    match_tier = "Low Match"

                status_val = "shortlisted" if r.interview.status == "shortlisted" else "rejected" if r.interview.status == "rejected" else (r.recommendation or "Maybe")
                
                reports_list.append({
                    "id": str(r.interview.id),
                    "name": r.interview.candidate_name or r.interview.candidate.email,
                    "email": r.interview.candidate.email,
                    "role": r.interview.job.title,
                    "score": score,
                    "match": match_tier,
                    "status": status_val,
                    "created_at": r.created_at.strftime('%Y-%m-%d')
                })
            
            return Response(reports_list, status=status.HTTP_200_OK)

    def post(self, request, pk):
        user = request.user
        if user.role != 'recruiter':
            return Response({"error": "Only recruiters can update candidate status."}, status=status.HTTP_403_FORBIDDEN)
        
        status_value = request.data.get('status')
        # Map frontend actions 'hire' -> 'shortlisted', 'reject' -> 'rejected'
        if status_value == 'hire':
            status_value = 'shortlisted'
        elif status_value == 'reject':
            status_value = 'rejected'

        if status_value not in ['shortlisted', 'rejected', 'on_hold', 'pending']:
            return Response({"error": "Invalid status value"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            interview = Interview.objects.get(id=pk, job__recruiter=user)
            interview.status = status_value
            interview.save()
            
            # Send notification email to candidate
            try:
                from ai_engine.utils.notifications_utils import send_candidate_accepted_email, send_candidate_rejected_email
                candidate_user = interview.candidate
                job_title = interview.job.title if interview.job else "the position"
                name = interview.candidate_name
                
                if status_value == 'shortlisted':
                    send_candidate_accepted_email(candidate_user, job_title, name)
                elif status_value == 'rejected':
                    send_candidate_rejected_email(candidate_user, job_title, name)
            except Exception as e:
                print(f"Error sending status update email: {e}")

            return Response({"message": f"Candidate status updated to {status_value}."})
        except Interview.DoesNotExist:
            return Response({"error": "Interview not found"}, status=status.HTTP_404_NOT_FOUND)


class LiveMonitoringDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_token):
        user = request.user
        if user.role != 'recruiter':
            return Response({"error": "Only recruiters can monitor live interviews."}, status=status.HTTP_403_FORBIDDEN)
        
        try:
            from django.db.models import Q
            try:
                interview_id = int(session_token)
                query = Q(id=interview_id) | Q(session_token=session_token)
            except ValueError:
                query = Q(session_token=session_token)
                
            interview = Interview.objects.select_related('job', 'candidate').get(
                query,
                job__recruiter=user
            )
            
            responses = InterviewResponse.objects.filter(interview=interview).order_by('question_index')
            
            messages = []
            for r in responses:
                t_str = r.timestamp.strftime('%I:%M %p') if r.timestamp else ""
                messages.append({
                    "id": f"q-{r.id}",
                    "role": "ai",
                    "text": r.question_text,
                    "timestamp": t_str
                })
                messages.append({
                    "id": f"a-{r.id}",
                    "role": "candidate",
                    "text": r.answer_text,
                    "timestamp": t_str
                })
            
            total_responses = responses.count()
            if total_responses > 0:
                avg_relevance = sum(r.relevance_score or 0 for r in responses) / total_responses
                avg_accuracy = sum(r.accuracy_score or 0 for r in responses) / total_responses
                avg_clarity = sum(r.clarity_score or 0 for r in responses) / total_responses
            else:
                avg_relevance = 80.0
                avg_accuracy = 80.0
                avg_clarity = 80.0

            scores = {
                "technical": round(avg_accuracy),
                "communication": round(avg_clarity),
                "confidence": round(avg_relevance),
                "problem_solving": round(avg_accuracy),
                "behavioral": round(avg_relevance)
            }

            return Response({
                "interview_id": str(interview.id),
                "candidate_name": interview.candidate_name or interview.candidate.email,
                "candidate_email": interview.candidate.email,
                "job_title": interview.job.title if interview.job else "Unknown Role",
                "match_score": interview.ats_score,
                "status": interview.status,
                "progress": total_responses,
                "messages": messages,
                "scores": scores
            }, status=status.HTTP_200_OK)
            
        except Interview.DoesNotExist:
            return Response({"error": "Interview session not found"}, status=status.HTTP_404_NOT_FOUND)

from ai_engine.models import AnomalyLog

class AnomalyLogView(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        token = request.data.get('token')
        event_type = request.data.get('event_type')
        severity = request.data.get('severity', 'medium')
        image = request.FILES.get('image')
        terminate = request.data.get('terminate', 'false').lower() == 'true'

        if not token or not event_type:
            return Response({"error": "token and event_type required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            interview = Interview.objects.get(session_token=token)
            
            snapshot_url = ""
            if image:
                import uuid
                remote_path = f"anomalies/{interview.id}_{uuid.uuid4()}.png"
                try:
                    from django.core.files.storage import default_storage
                    saved_path = default_storage.save(remote_path, image)
                    snapshot_url = request.build_absolute_uri(default_storage.url(saved_path))
                except Exception as e:
                    print(f"Failed to upload anomaly image to S3/Supabase: {e}. Falling back to local storage.")
                    try:
                        from django.core.files.storage import FileSystemStorage
                        from django.conf import settings
                        fs = FileSystemStorage(location=settings.MEDIA_ROOT, base_url=settings.MEDIA_URL)
                        
                        # We need to reset the file pointer because it might have been read by default_storage
                        image.seek(0)
                        saved_path = fs.save(remote_path, image)
                        snapshot_url = request.build_absolute_uri(fs.url(saved_path))
                    except Exception as fallback_e:
                        print(f"Fallback local storage also failed: {fallback_e}")
            
            anomaly = AnomalyLog.objects.create(
                interview=interview,
                event_type=event_type,
                severity=severity,
                snapshot_url=snapshot_url
            )

            if terminate:
                interview.status = 'malpractice'
                interview.save()
                
                # Generate a report even if terminated due to malpractice
                generate_interview_report(interview)

            # Broadcast to recruiter
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'interview_{interview.session_token}',
                {
                    'type': 'anomaly_event',
                    'event_type': event_type,
                    'severity': severity,
                    'snapshot_url': snapshot_url,
                    'timestamp': anomaly.timestamp.isoformat(),
                    'is_termination': terminate
                }
            )

            # Create In-App Notification: Proctoring Anomaly
            try:
                Notification.objects.create(
                    user=interview.job.recruiter,
                    title=f"Proctoring Alert: {event_type}",
                    detail=f"Proctoring violation detected during {interview.candidate_name or interview.candidate.email}'s session: {event_type}. Severity: {severity}.",
                    notification_type="anomaly_detected"
                )
            except Exception as e:
                print(f"[NOTIFICATION ERROR] Failed to create proctoring anomaly notification: {e}")

            return Response({"status": "Anomaly logged successfully"}, status=status.HTTP_201_CREATED)
        except Interview.DoesNotExist:
            return Response({"error": "Invalid session token"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"Error logging anomaly: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
