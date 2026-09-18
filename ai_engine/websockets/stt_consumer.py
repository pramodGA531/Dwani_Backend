"""
STT WebSocket Consumer
Accepts raw Int16 PCM audio at 16 kHz from the frontend MediaRecorder pipeline,
transcribes incrementally using Faster-Whisper (CPU/int8), and returns
{ type, text, is_final } JSON messages.

Route: ws/stt/<session_token>/?token=<jwt_access_token>
"""

import json
import asyncio
import numpy as np
import wave
from io import BytesIO
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from decouple import config
import os
from django.conf import settings
import gc
import torch
from faster_whisper import WhisperModel
from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

# ── Configuration ────────────────────────────────────────────────────────────
# STT_ENGINE can be "faster-whisper" (optimized) or "transformers" (standard huggingface)
STT_ENGINE = config("STT_ENGINE", default="faster-whisper")

# Model size for faster-whisper
STT_MODEL_SIZE = config("STT_MODEL_SIZE", default="medium")
# Full huggingface path for transformers
HF_MODEL_ID = config("HF_MODEL_ID", default="openai/whisper-medium")

_stt_model_fw = None
_stt_model_hf = None
_stt_processor_hf = None

_device = "cuda" if torch.cuda.is_available() else "cpu"
_compute_type_fw = "float16" if _device == "cuda" else "int8"
_dtype_hf = torch.float16 if _device == "cuda" else torch.float32

def _get_local_model():
    global _stt_model_fw, _stt_model_hf, _stt_processor_hf
    if STT_ENGINE == "faster-whisper":
        if _stt_model_fw is None:
            print(f"[STT] Loading faster-whisper Model: {STT_MODEL_SIZE} on {_device} ({_compute_type_fw})")
            _stt_model_fw = WhisperModel(STT_MODEL_SIZE, device=_device, compute_type=_compute_type_fw)
        return _stt_model_fw
    else:
        if _stt_model_hf is None or _stt_processor_hf is None:
            print(f"[STT] Loading Transformers Whisper: {HF_MODEL_ID} on {_device}")
            _stt_processor_hf = AutoProcessor.from_pretrained(HF_MODEL_ID)
            _stt_model_hf = AutoModelForSpeechSeq2Seq.from_pretrained(HF_MODEL_ID, torch_dtype=_dtype_hf)
            _stt_model_hf.to(_device)
            _stt_model_hf.eval()
        return _stt_processor_hf, _stt_model_hf


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
        print(f"[STT] Connected: {user.email}")

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
                    transcript = await self._transcribe()
                if transcript is not None:
                    final_text = transcript.strip()
                else:
                    final_text = ""
                    
                # Clear buffer for next answer
                self.audio_buffer = np.array([], dtype=np.float32)
                await self.send(json.dumps({
                    "type": "transcript",
                    "text": final_text,
                    "is_final": True,
                }))

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _transcribe(self):
        """Transcribe using local Whisper model."""
        try:
            if len(self.audio_buffer) == 0:
                return ""

            # --- LOCAL FASTER-WHISPER IMPLEMENTATION ---
            model = _get_local_model()
            
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
                "i am a native english speaker"
            ]
            
            for trigger in hallucination_triggers:
                if trigger in lower_text:
                    print(f"[STT] Filtered Whisper hallucination: {text}")
                    return "candidate didnt respondedd"
            
            # If the result is literally empty after Whisper (pure silence)
            if not text:
                return "candidate didnt respondedd"
                
            return text
        except Exception as e:
            print(f"[STT] Transcription error: {e}")
            return None

    def _run_inference_sync(self, audio_array, prompt_text):
        """Runs the CPU-heavy AI inference synchronously."""
        if STT_ENGINE == "faster-whisper":
            model = _get_local_model()
            try:
                segments, info = model.transcribe(
                    audio_array,
                    language="en",
                    initial_prompt=prompt_text,
                    vad_filter=True
                )
                return "".join([segment.text for segment in segments]).strip()
            except Exception as e:
                print(f"[STT] Faster-Whisper Error: {e}")
                return "candidate didnt respondedd"
        else:
            processor, model = _get_local_model()
            inputs = processor(
                audio_array,
                sampling_rate=16000,
                return_tensors="pt"
            )
            input_features = inputs.input_features.to(
                device=_device,
                dtype=_dtype_hf
            )
            prompt_ids_tensor = None
            try:
                if hasattr(processor, 'get_prompt_ids'):
                    prompt_ids = processor.get_prompt_ids(prompt_text)
                    if not isinstance(prompt_ids, torch.Tensor):
                        prompt_ids_tensor = torch.tensor(prompt_ids).to(_device)
                    else:
                        prompt_ids_tensor = prompt_ids.to(_device)
            except Exception as e:
                print(f"[STT] Could not generate prompt IDs: {e}")
            
            with torch.no_grad():
                generate_kwargs = {
                    "language": "en",
                    "task": "transcribe"
                }
                if prompt_ids_tensor is not None:
                    generate_kwargs["prompt_ids"] = prompt_ids_tensor
                    
                generated_ids = model.generate(
                    input_features,
                    **generate_kwargs
                )
            return processor.batch_decode(
                generated_ids,
                skip_special_tokens=True
            )[0].strip()

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
