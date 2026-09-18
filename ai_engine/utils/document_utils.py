import os
import PyPDF2
from docx import Document
from django.core.files.storage import default_storage

class DocumentExtractor:
    @staticmethod
    def extract_text(file_path):
        """
        Extracts text from a file (PDF or DOCX) given its storage path.
        """
        if not default_storage.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        
        # Open file from storage
        with default_storage.open(file_path, 'rb') as f:
            return DocumentExtractor.extract_from_file(f, file_path)

    @staticmethod
    def extract_from_file(file_obj, filename):
        """
        Extracts text from an in-memory file object.
        """
        ext = os.path.splitext(filename)[1].lower()
        
        # Ensure pointer is at start
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)

        if ext == '.pdf':
            return DocumentExtractor._extract_from_pdf(file_obj)
        elif ext == '.docx':
            return DocumentExtractor._extract_from_docx(file_obj)
        else:
            try:
                content = file_obj.read()
                if isinstance(content, bytes):
                    return content.decode('utf-8')
                return content
            except:
                raise ValueError(f"Unsupported file extension: {ext}")

    @staticmethod
    def _extract_from_pdf(file_stream):
        text = ""
        try:
            reader = PyPDF2.PdfReader(file_stream)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception as e:
            print(f"Error extracting PDF: {e}")
        return text.strip()

    @staticmethod
    def _extract_from_docx(file_stream):
        text = ""
        try:
            doc = Document(file_stream)
            for para in doc.paragraphs:
                text += para.text + "\n"
        except Exception as e:
            print(f"Error extracting DOCX: {e}")
        return text.strip()
