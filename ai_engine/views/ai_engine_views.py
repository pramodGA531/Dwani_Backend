from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from ai_engine.utils.document_utils import DocumentExtractor
from ai_engine.services.groq_service import GeminiExtractionService
from ai_engine.services.local_storage_service import local_storage_service
import uuid
import os

from rest_framework.parsers import MultiPartParser, FormParser

class ScreeningProcessView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 1. Get files and metadata from request
        jd_file = request.FILES.get('jd')
        resume_file = request.FILES.get('resume')
        candidate_name = request.data.get('candidate_name', 'Unknown')
        candidate_email = request.data.get('candidate_email', 'unknown@example.com')
        recruiter_email = request.user.email

        if not jd_file or not resume_file:
            return Response({'error': 'Both jd and resume files are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 2. Extract text in-memory for Gemini
            print(f"DEBUG: Extracting text from JD: {jd_file.name}")
            jd_text = DocumentExtractor.extract_from_file(jd_file, jd_file.name)
            
            print(f"DEBUG: Extracting text from Resume: {resume_file.name}")
            resume_text = DocumentExtractor.extract_from_file(resume_file, resume_file.name)

            if not jd_text or not resume_text:
                return Response({'error': 'Failed to extract text from files'}, status=status.HTTP_400_BAD_REQUEST)

            # 3. Upload to Supabase Storage
            # Generate unique paths to avoid collisions
            unique_id = str(uuid.uuid4())
            jd_remote_path = f"jds/{unique_id}_{jd_file.name}"
            resume_remote_path = f"resumes/{unique_id}_{resume_file.name}"

            print("DEBUG: Uploading to Supabase Storage...")
            jd_url = local_storage_service.upload_file(jd_file, "screening-documents", jd_remote_path)
            resume_url = local_storage_service.upload_file(resume_file, "screening-documents", resume_remote_path)

            # 4. Process with Gemini first to get real details
            print("DEBUG: Calling Gemini service...")
            ai_service = GeminiExtractionService()
            result = ai_service.process_screening(jd_text, resume_text)

            # 5. Save metadata to Supabase DB using EXTRACTED data
            print("DEBUG: Saving metadata to Supabase DB...")
            candidate_info = result.get('candidate_details', {})
            metadata = {
                "candidate_name":  candidate_info.get('name', candidate_name),
                "candidate_email": candidate_info.get('email', candidate_email),
                "recruiter_id":    str(request.user.id),   # normalised: store ID not email
                "jd_url":          jd_url,
                "resume_url":      resume_url
            }
            local_storage_service.save_screening_metadata(metadata)
            
            # Add Supabase URLs to the response
            result['jd_url'] = jd_url
            result['resume_url'] = resume_url

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"ERROR: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
