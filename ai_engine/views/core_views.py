from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from django.core.files.storage import default_storage
from rest_framework.permissions import IsAuthenticated

class HealthCheckView(APIView):
    def get(self, request):
        return Response({"status": "ok", "message": "API is running"}, status=status.HTTP_200_OK)

class FileUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        print(f"DEBUG: Auth header: {request.headers.get('Authorization')}")
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

        # 5MB limit
        if file_obj.size > 5 * 1024 * 1024:
            return Response({'error': 'File size exceeds 5MB limit'}, status=status.HTTP_400_BAD_REQUEST)

        # PDF/DOCX validation
        allowed_extensions = ['.pdf', '.docx']
        if not any(file_obj.name.lower().endswith(ext) for ext in allowed_extensions):
            return Response({'error': 'Only PDF and DOCX files are allowed'}, status=status.HTTP_400_BAD_REQUEST)

        # Organize by type
        file_type = request.data.get('type', 'uploads')
        if file_type not in ['resume', 'jd']:
            file_type = 'uploads'
        
        # Add plural 's' for folder name if it's resume/jd
        folder = f"{file_type}s" if file_type in ['resume', 'jd'] else file_type
        
        file_path = default_storage.save(f'{folder}/{file_obj.name}', file_obj)
        file_url = default_storage.url(file_path)

        return Response({
            'url': file_url,
            'path': file_path,
            'name': file_obj.name,
            'type': file_type
        }, status=status.HTTP_201_CREATED)
