# DwaniAI Backend

Welcome to the DwaniAI Backend repository! This is a Django-based application that powers the AI-driven technical interviews, real-time speech-to-text processing, and the recruiter management APIs.

## 🚀 Tech Stack
- **Framework**: Django & Django REST Framework (DRF)
- **Real-Time / WebSockets**: Django Channels & Daphne
- **AI Engine**: Groq API (LLaMA models) for dynamic question generation and evaluation
- **Speech-to-Text (STT)**: Local Faster-Whisper / Transformers for ultra-fast transcription
- **Storage**: Local Storage Service (Django `default_storage`)

---

## 📂 Project Structure

Following the recent architectural refactoring, the backend is strictly organized into logical components to prevent monolithic code files.

```text
backend/
├── ai_engine/                    # Main application handling all business logic
│   ├── services/                 # External Integrations
│   │   ├── groq_service.py       # Handles AI question generation & answer evaluation
│   │   └── local_storage_service.py # Handles file/resume uploads
│   ├── views/                    # Modular API endpoints
│   │   ├── ai_engine_views.py    # Analytics & AI-specific views
│   │   ├── core_views.py         # System health & file uploads
│   │   ├── interviews_views.py   # Interview lifecycle management
│   │   └── screening_views.py    # Candidate screening endpoints
│   ├── websockets/               # Real-Time Channels
│   │   ├── consumers.py          # Core interview progression & event broadcasting
│   │   └── stt_consumer.py       # Live audio chunk processing & transcription
│   ├── models.py                 # Database schemas (Interview, Job, Response, etc.)
│   └── urls.py                   # App-level routing
│
├── core/                         # Django Project Configuration
│   ├── settings/                 # Modularized settings
│   ├── asgi.py                   # ASGI entrypoint for Daphne
│   ├── routing.py                # WebSocket URL routing
│   └── urls.py                   # Root HTTP URL routing
│
└── manage.py                     # Django CLI
```

---

## 🌊 Core Flows & Architecture

### 1. Real-Time Interview Flow (WebSockets)
The core candidate experience is completely real-time, operating over two distinct WebSocket channels:
- **STT Consumer (`ws/stt/<token>/`)**: Receives raw audio streams from the frontend, normalizes them, and processes them locally using Faster-Whisper to provide near-instantaneous transcriptions.
- **Interview Consumer (`ws/interview/<token>/`)**: Manages the state of the interview. It receives the finalized transcriptions, sends them to the `GroqAIService` for scoring, and dynamically requests the next tailored question based on the candidate's previous response.

### 2. AI Evaluation Pipeline (`GroqAIService`)
Instead of a static list of questions, the backend uses Groq's high-speed inference to mimic a real technical interview. 
- It uses the Job context and Required Skills to frame the persona.
- When an answer is submitted, it returns structured JSON containing scores for *Relevance*, *Accuracy*, and *Clarity*, alongside a generated follow-up question.

### 3. Recruiter Management (REST API)
The Recruiter dashboard interacts purely via standard RESTful endpoints (defined in `views/`). 
- Features JWT Authentication.
- Handles CRUD operations for Jobs.
- Exposes detailed analytics and interview response logs.

---

## 🛠️ Local Development

### Setup
1. Activate your virtual environment and install dependencies.
2. Apply database migrations:
   ```bash
   python manage.py migrate
   ```
3. Start the ASGI development server (Daphne):
   ```bash
   python manage.py runserver
   ```

### Environment Variables
Ensure your `.env` file contains the required keys for AI functionality:
- `GROQ_API_KEY`: Required for question generation and scoring.
- `STT_ENGINE`: Can be configured for different transcription models (e.g., `faster-whisper`).
