"""
STT WebSocket Consumer
Accepts raw Int16 PCM audio at 16 kHz from the frontend MediaRecorder pipeline,
transcribes incrementally using Faster-Whisper or HuggingFace Transformers Whisper,
and returns { type, text, is_final } JSON messages.

Route: ws/stt/<session_token>/?token=<jwt_access_token>

Engine modules:
    stt_faster_whisper.py  - CTranslate2-backed (faster, recommended for CPU)
    stt_transformers.py    - HuggingFace Transformers (standard, more model options)
"""

import json
import asyncio
import numpy as np
import wave
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from decouple import config

# ── Engine Selection ──────────────────────────────────────────────────────────
#
#  TO SWITCH ENGINES: change STT_ENGINE in your .env file.
#
#  Option A – Faster-Whisper (CTranslate2, recommended for CPU servers)
#      STT_ENGINE=faster-whisper
#      STT_MODEL_SIZE=medium      # tiny | base | small | medium | large-v2 | large-v3
#
#  Option B – HuggingFace Transformers (standard, supports more community models)
#      STT_ENGINE=transformers
#      HF_MODEL_ID=openai/whisper-medium   # any HF Whisper-compatible model ID
#
#  Each engine lives in its own module in this directory:
#      ai_engine/websockets/stt_faster_whisper.py
#      ai_engine/websockets/stt_transformers.py
#
STT_ENGINE = config("STT_ENGINE", default="faster-whisper")

if STT_ENGINE == "faster-whisper":
    from ai_engine.websockets import stt_faster_whisper as _stt_engine
else:
    from ai_engine.websockets import stt_transformers as _stt_engine

# ─────────────────────────────────────────────────────────────────────────────


# ── Consumer ─────────────────────────────────────────────────────────────────
class STTConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = await self._get_user_from_query()
        if user is None:
            await self.close(code=4001)
            return

        self.audio_buffer = np.array([], dtype=np.float32)
        self.job_title, self.skills = await self._get_interview_context()
        self.transcribe_lock = asyncio.Lock()
        self.client_sample_rate = 16000
        await self.accept()
        print(f"[STT] Connected: {user.email} (engine: {STT_ENGINE})")

    async def disconnect(self, close_code):
        print(f"[STT] Disconnected ({close_code})")

    async def receive(self, text_data=None, bytes_data=None):
        # ── Binary frame: Audio Data ─────────────────────────────────────────
        if bytes_data:
            chunk = np.frombuffer(bytes_data, dtype=np.float32)
            self.audio_buffer = np.concatenate([self.audio_buffer, chunk])

        # ── Text frame: ──────────────────────────────────────────────────────
        elif text_data:
            data = json.loads(text_data)
            if data.get("type") == "config":
                self.client_sample_rate = data.get("sampleRate", 16000)
                print(f"[STT] Client sample rate configured to {self.client_sample_rate} Hz")
            elif data.get("type") == "finalize":
                async with self.transcribe_lock:
                    # Run transcription and keepalive pings concurrently so the
                    # WS connection stays alive during the long CPU inference.
                    transcript, _ = await asyncio.gather(
                        self._transcribe(),
                        self._send_keepalives(),
                    )
                final_text = transcript.strip() if transcript is not None else ""

                # Clear buffer for next answer
                self.audio_buffer = np.array([], dtype=np.float32)
                await self.send(json.dumps({
                    "type": "transcript",
                    "text": final_text,
                    "is_final": True,
                }))

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _transcribe(self):
        """Transcribe the current audio buffer using the configured STT engine."""
        try:
            if len(self.audio_buffer) == 0:
                return ""

            # DEBUG: Save audio to file to verify it's not corrupted
            audio_int16 = (self.audio_buffer * 32767).astype(np.int16)
            with wave.open('debug_audio.wav', 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())

            # --- Normalize Audio ---
            # Browser microphones often output very quiet audio.
            # Whisper expects normalized audio (-1.0 to 1.0) for optimal transcription.
            audio_array = self.audio_buffer.copy()
            max_amp = np.max(np.abs(audio_array))
            if max_amp > 0 and max_amp < 0.9:
                audio_array = audio_array / max_amp

            # --- Generate Prompt to fix misconceptions ---
            prompt_text = "Technical interview."
            if hasattr(self, 'job_title') and self.job_title:
                prompt_text += f" Job role: {self.job_title}."
            if hasattr(self, 'skills') and self.skills:
                prompt_text += f" Keywords: {self.skills}."

            # Offload heavy CPU inference to a separate thread to prevent blocking the ASGI event loop
            text = await asyncio.to_thread(self._run_inference_sync, audio_array, prompt_text)

            # Filter out empty responses
            if not text:
                return "candidate didnt respondedd"

            # Filter out known Whisper hallucinations
            lower_text = text.lower()
            hallucination_triggers = [
                "candidate speaks english",
                "indian accent",
                "indian-english",
                "technical terms, names",
                "candidate is not a professional",
                "technical interview. machine learning",
                "native english speaker",
                "i'm a native english speaker",
                "i am a native english speaker",
            ]
            for trigger in hallucination_triggers:
                if trigger in lower_text:
                    print(f"[STT] Filtered Whisper hallucination: {text}")
                    return "candidate didnt respondedd"

            return text

        except Exception as e:
            print(f"[STT] Transcription error: {e}")
            return None

    async def _send_keepalives(self):
        """Send a ping every 5 s to keep the WS alive during long inference.
        The transcription task runs in parallel; this task exits naturally when
        the gather() completes (i.e. when _transcribe() returns)."""
        try:
            while True:
                await asyncio.sleep(5)
                await self.send(json.dumps({"type": "keepalive"}))
        except Exception:
            pass

    def _run_inference_sync(self, audio_array, prompt_text):
        """Delegate synchronous inference to the active STT engine module."""
        return _stt_engine.run_inference(audio_array, prompt_text)

    @sync_to_async
    def _get_user_from_query(self):
        from rest_framework_simplejwt.tokens import AccessToken
        from django.contrib.auth import get_user_model
        from ai_engine.models import Interview
        User = get_user_model()
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        token = qs.get("token", [None])[0]
        if not token:
            return None

        try:
            payload = AccessToken(token)
            return User.objects.get(id=payload["user_id"])
        except Exception:
            # Fallback for candidates connecting with interview_session_token
            try:
                interview = Interview.objects.get(session_token=token)
                class DummyUser:
                    email = f"Candidate: {interview.candidate_name}"
                return DummyUser()
            except Exception:
                if token == "test_stt":
                    class TestUser:
                        email = "Test User"
                    return TestUser()
                return None

    @sync_to_async
    def _get_interview_context(self):
        from ai_engine.models import Interview
        session_token = self.scope['url_route']['kwargs'].get('session_token')
        if not session_token:
            return "", ""
        if session_token == "test_stt":
            # Provide realistic tech skills for the test page so the model has context!
            return "Software Engineer", "Tech Stack, ReactJS, Django, PostgreSQL, Database"
        try:
            interview = Interview.objects.get(session_token=session_token)
            skills = ", ".join(interview.skills) if interview.skills else ""
            title = interview.job.title if interview.job else ""
            return title, skills
        except Exception:
            return "", ""
