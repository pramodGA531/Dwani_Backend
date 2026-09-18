from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import json

class LocalStorageService:
    """
    Local Storage Service that uses Django's native
    default_storage (FileSystemStorage) and the native SQLite DB.
    """
    def __init__(self):
        self.client = None

    def upload_file(self, file_obj, bucket_name: str, remote_path: str):
        """
        Uploads a file object to local Django storage.
        Returns the public URL of the uploaded file.
        """
        file_obj.seek(0)
        saved_path = default_storage.save(remote_path, file_obj)
        return default_storage.url(saved_path)

    def save_screening_metadata(self, data: dict):
        """
        Saves screening metadata to the native Django Screening model.
        Expected keys: candidate_name, candidate_email, recruiter_id, jd_url, resume_url
        """
        from ai_engine.models.interviews_models import Screening
        screening = Screening.objects.create(
            candidate_name=data.get("candidate_name"),
            candidate_email=data.get("candidate_email"),
            recruiter_id=data.get("recruiter_id"),
            jd_url=data.get("jd_url"),
            resume_url=data.get("resume_url"),
            status=data.get("status", "pending")
        )
        return {"id": screening.id}

    def upload_json_report(self, report_dict: dict, remote_path: str, bucket_name: str = "screening-documents"):
        """
        Uploads a JSON report as a .json file to local Django storage.
        Returns the public URL of the uploaded file.
        """
        json_bytes = json.dumps(report_dict, indent=2, ensure_ascii=False).encode("utf-8")
        saved_path = default_storage.save(remote_path, ContentFile(json_bytes))
        return default_storage.url(saved_path)

    def update_screening_with_report(self, candidate_email: str, report_url: str):
        """
        Updates the Screening model row matching candidate_email with the report_url.
        """
        from ai_engine.models.interviews_models import Screening
        Screening.objects.filter(candidate_email=candidate_email).update(report_url=report_url)

local_storage_service = LocalStorageService()
