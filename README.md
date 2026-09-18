# 🤖 InterviewAI: Autonomous AI Technical Screening & Recruitment Suite

[![Django](https://img.shields.io/badge/Backend-Django%205.0-092E20?style=for-the-badge&logo=django&logoColor=white)](https://djangoproject.com)
[![React](https://img.shields.io/badge/Frontend-React%2019-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)](https://react.dev)
[![Vite](https://img.shields.io/badge/Build%20Tool-Vite%208-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vite.dev)
[![Groq Llama 3.3](https://img.shields.io/badge/AI--Engine-Groq%20Llama%203.3-orange?style=for-the-badge&logo=openai&logoColor=white)](https://groq.com)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%20(Neon)-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://neon.tech)
[![CapacitorJS](https://img.shields.io/badge/Mobile-CapacitorJS%208-119EFF?style=for-the-badge&logo=capacitor&logoColor=white)](https://capacitorjs.com)

**InterviewAI** is a premium, full-stack, enterprise-ready technical screening platform designed to completely automate and elevate the early-stage engineering recruitment pipeline. Leveraging highly optimized local LLM endpoints via the **Groq API** (`openai/gpt-oss-20b`) and Google's **Gemini API**, the system serves as an autonomous, adaptive technical interviewer that screens resumes, conducts interviews, evaluates complex responses in real-time, logs candidate behavior anomalies, and compiles comprehensive reports.

---

## ⚡ Core Architecture Flow

```mermaid
graph TD
    %% Define actors and roles
    Recruiter[Recruiter / HR]
    Candidate[Candidate / Interviewee]
    
    %% Main Database and services
    DB[(PostgreSQL Database)]
    Redis[(Redis Service)]
    Groq[Groq AI Service]

    %% Recruiter workflow
    Recruiter -->|1. Creates Job & Uploads JD| RecruiterPortal[React Recruiter Portal]
    RecruiterPortal -->|2. Saves Job| Backend[Django REST API / Channels]
    RecruiterPortal -->|3. Invites Candidate with Resume| Backend
    Backend -->|4. Runs ATS Match & Generates Tokens| Groq
    
    %% Candidate workflow
    Backend -->|5. Sends Verification Email| Candidate
    Candidate -->|6. Logs in & System Check| CandidatePortal[React Candidate Portal]
    CandidatePortal -->|7. Establishes Session| WS[WebSocket / Django Channels]
    WS <-->|8. Dynamic Adaptive Interviewing & Evaluation| Groq
    CandidatePortal -->|9. Submits Feedback| Backend
    
    %% Reports
    Backend -->|10. Compiles ATS, Cheating Logs, Feedback & Answers| DB
    DB -->|11. Generates Detailed Hiring Report| RecruiterPortal
    
    %% Event and WebSocket link
    WS <-->|Websocket Broker| Redis
```

---

## ✨ Cutting-Edge Features

### 1. 🧠 Dynamic & Adaptive AI Interviewer
*   **Contextual Interviewing**: Generates technical questions customized around the specific Job Description (JD) and the candidate's resume keywords.
*   **Adaptive Difficulty**: Dynamically adapts interview question difficulty on-the-fly. Excellent candidate responses trigger highly technical, architecture-level inquiries, while weaker responses downscale difficulty to verify core foundational engineering concepts.
*   **Real-time WebSocket Streaming**: Leverages **Django Channels** and **Redis** to conduct instant question-answer loops, minimizing latency and rendering an immersive conversational atmosphere.
*   **Lightning-Fast Voice STT**: Integrates Groq's `whisper-large-v3` over WebSockets for hyper-accurate, low-latency Speech-to-Text, capturing every nuance of a candidate's response.
*   **Persistent Audio Graph Architecture**: Utilizes a robust singleton `AudioContext` and dynamically spawned `ScriptProcessorNode`s in the browser to guarantee zero microphone dropouts and seamless transition between questions.

### 2. 📝 Rigorous 3D Response Evaluation
*   Every technical answer submitted by the candidate is evaluated in real-time by a specialized prompt routing layer across three key dimensions:
    *   **Relevance**: Does the response directly target the core of the engineering problem?
    *   **Accuracy**: Is the factual content precise and correct?
    *   **Clarity**: Is the explanation structured professionally and easy to comprehend?
*   Calculates dynamic overall metrics and records conversational logs immediately.

### 3. 🎯 Intelligent Resume Parser & ATS Matching
*   Extracts candidate names, emails, and specialized skill matrices from resume text.
*   Performs semantic matching between candidate profiles and job requirements to calculate a granular **ATS Alignment Score** (0-100%) and highlights key strengths and vulnerabilities.

### 4. 🛡️ Advanced Proctoring & Anomaly Tracking
*   Tracks candidate interactions, focus changes, tab-switching, and exit events during active interview sessions.
*   Generates proctoring anomaly records classified by severity levels (`Low`, `Medium`, `High`) to guarantee the utmost screening integrity.

### 5. 💼 Executive Recruiter Portal
*   **Job Manager**: Create, edit, and archive job descriptions, tracking invited applicant metrics.
*   **Monitoring Hub**: Observe live-monitoring updates for underway candidate sessions.
*   **Comprehensive Reports**: Display in-depth results, overall summaries, candidate strengths and weaknesses, PDF/HTML download configurations, and resume mismatch flags.

### 6. 📱 Seamless Mobile Capabilities
*   Pre-configured with **CapacitorJS** supporting native target distributions for Android and iOS. Take technical assessments directly on standard mobile viewports with camera, microphone, and system verification checks integrated.

---

## 🗄️ Database Schema Blueprint

The platform's backend schema is built around modular relational architectures optimized for fast execution, proctoring logging, and AI feedback compiling:

```
  +--------------+          +-------------------+          +--------------------+
  |     User     | 1      N |        Job        | 1      N |     Interview      |
  |  (Auth/Rec)  +--------->+ (recruiter_id)   +--------->+  (job_id, cand_id) |
  +--------------+          +-------------------+          +---------+----------+
                                                                     |
         +-------------------+-----------------+---------------------+
         | 1                 | 1               | 1                   | 1
         v 1                 v N               v N                   v 1
  +------+-------+   +-------+-------+   +-----+-----+       +-------+-------+
  |    Report    |   |   Response    |   | AnomalyLog|       |CandidateReview|
  | (ATS, Summary|   | (Q/A, Scores  |   | (Events,  |       | (Feedback,    |
  |  Strengths)  |   | Rel/Acc/Clar) |   | Severity) |       | Ratings 1-5)  |
  +--------------+   +---------------+   +-----------+       +---------------+
```

*   **`User`**: Custom user representation separating Admins, Recruiters, and Candidates. Includes an approval flag requiring recruiters to be vetted before accessing their dashboards.
*   **`Job`**: Defines job designations, comprehensive descriptive parameters, status configurations (`Draft`, `Active`, `Closed`), and logs the creator user.
*   **`Interview`**: Represents an active assessment session. Houses candidate references, dynamic ATS scores, custom session tokens, secure expirable access links, and status configurations (`Pending`, `In Progress`, `Completed`, `Malpractice`, `Shortlisted`, `Rejected`).
*   **`Response`**: Logs the exact transcripts of questions asked and the candidate's answer text, together with AI-evaluated Relevance, Accuracy, and Clarity scoring dimensions.
*   **`AnomalyLog`**: Tracks event occurrences during session proctoring, noting severity levels (`low`, `medium`, `high`) and capture references.
*   **`Report`**: Compiles overall scores, strengths, weaknesses, resume mismatches, and custom recommendations.
*   **`CandidateReview`**: Captures rating attributes (`overall_experience`, `ai_clarity`, `ease_of_use`, `technical_stability`) and suggestions submitted upon completion.

---

## 📂 Repository Structure

```hl
├── backend/                        # Django & Django Channels Web Server
│   ├── ai_engine/                  # Adaptive LLM engines, Groq / Gemini integrations
│   ├── core/                       # ASGI/WSGI servers, database routers, JWT settings
│   ├── interviews/                 # WebSockets (Consumers), dynamic API views, proctoring
│   ├── jobs/                       # Job listings, descriptions, and candidate invitations
│   ├── reports/                    # Aggregated hiring PDF reports, resume parsers
│   ├── users/                      # User authentication, recruiter approval flows
│   ├── templates/                  # Email styling & HTML wrappers
│   ├── manage.py                   # Django CLI executable
│   └── requirements.txt            # Python dependencies (Daphne, Groq, Pytest)
│
├── frontend/                       # Responsive React Unified Portal (Recruiter + Candidate)
│   ├── src/
│   │   ├── components/             # Common UI, layouts, auth route guards
│   │   ├── pages/                  # Unified views (Dashboard, Jobs, Live Monitoring, System Checks, Interviews)
│   │   ├── context/                # Shared and Candidate auth/interview state contexts
│   │   └── App.jsx                 # Unified routing tree mapping Recruiter & Candidate flows
│   ├── android/                    # CapacitorJS Android Studio configuration folder
│   ├── ios/                        # CapacitorJS Xcode configuration folder
│   ├── capacitor.config.json       # Native compilation preferences
│   └── package.json                # Front-end dependencies & scripts
│
├── docker-compose.yml              # Orchestrator setting up local Redis container
└── README_SETUP.md                 # Granular teammate setup documentation
```

---

## ⚙️ Environment Configuration

Generate a `.env` in the root folder, copying from `.env.example`:

```ini
# Django Settings
SECRET_KEY=your-django-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (Neon.tech PostgreSQL recommended)
DATABASE_URL=postgresql://user:password@host.neon.tech/dbname?sslmode=require

# AI Engine Models
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=openai/gpt-oss-20b
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-flash-latest

# Redis (For WebSockets / Django Channels)
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0

# SMTP Email Configuration (Gmail SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-16-character-gmail-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com
```

---

## 🚀 Fast Deployment Guide

For a highly detailed, step-by-step setup walkthrough, please refer directly to the **[Project Setup Guide](README_SETUP.md)**. Below is a fast-track version:

### 1. Launch Redis (Docker)
We use Redis as the ASGI channel layer backplane. Run:
```bash
docker run --name redis-server -p 6379:6379 -d redis
```

### 2. Set Up the Backend
Activate your Python virtual environment and run migrations:
```bash
# In the root or backend folder:
python -m venv venv
# Activate on Windows:
.\venv\Scripts\activate
# Activate on Unix:
source venv/bin/activate

cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### 3. Launch the Frontend
The candidate portal and recruiter dashboard are consolidated into a single unified frontend application. Launch it as follows:

```bash
cd frontend
npm install
npm run dev
```

The unified React portal runs on `http://localhost:5173/` by default. Recruiter workflows (Login, Dashboards, Live Monitoring) and Candidate workflows (Waiting Room, System Checks, Active Interviews) are dynamically managed and routed under this single running instance! Recruiters must register and can be approved by logging in to the Django Admin console at `http://localhost:8000/admin/`.

---

## 📄 License
This project is proprietary. All rights reserved. Built with 💻 and 🤖 for seamless engineering recruitment.
