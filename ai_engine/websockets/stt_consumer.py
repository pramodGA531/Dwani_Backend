"""
STT WebSocket Consumer
Supports: deepgram (streaming), gemini (live), faster-whisper (local), transformers (local)

Route: ws/stt/<session_token>/?token=<jwt_access_token>
"""

import json
import asyncio
import base64
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

try:
    import torch
    from faster_whisper import WhisperModel
    from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _compute_type_fw = "float16" if _device == "cuda" else "int8"
    _dtype_hf = torch.float16 if _device == "cuda" else torch.float32
except ImportError:
    torch = None
    WhisperModel = None
    AutoProcessor = None
    AutoModelForSpeechSeq2Seq = None
    _device = "cpu"
    _compute_type_fw = "int8"
    _dtype_hf = None

# ── Configuration ────────────────────────────────────────────────────────────
# STT_ENGINE: "gemini" | "deepgram" | "faster-whisper" | "transformers"
STT_ENGINE = config("STT_ENGINE", default="faster-whisper")

STT_MODEL_SIZE = config("STT_MODEL_SIZE", default="medium")
HF_MODEL_ID = config("HF_MODEL_ID", default="openai/whisper-medium")
DEEPGRAM_API_KEY = config("DEEPGRAM_API", default="")
GEMINI_STT_MODEL = config("GEMINI_STT_MODEL", default="models/gemini-3.5-transcribe-live")

_stt_model_fw = None
_stt_model_hf = None
_stt_processor_hf = None


def _get_local_model():
    global _stt_model_fw, _stt_model_hf, _stt_processor_hf
    if STT_ENGINE == "faster-whisper":
        if _stt_model_fw is None:
            print(f"[STT] Loading faster-whisper: {STT_MODEL_SIZE} on {_device} ({_compute_type_fw})")
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

        # ── Deepgram state ───────────────────────────────────────────────────
        self.dg_ws = None
        self.dg_task = None
        self.dg_transcript = ""       # accumulated finals
        self.dg_current = ""          # latest interim
        self.dg_ready = False          # True once DG WS connected
        self.dg_pre_buffer = []        # audio bytes buffered before DG connects
        self.dg_session_peak = 0.0    # loudest amplitude seen — for stable gain

        # ── Gemini state ─────────────────────────────────────────────────────
        self.gemini_ws = None
        self.gemini_task = None
        self.gemini_transcript = ""   # accumulated text from Gemini
        self.gemini_turn_done = asyncio.Event()
        self.gemini_ready = False          # True once setupComplete received
        self.gemini_pre_buffer = []        # audio msgs buffered before setup done

        await self.accept()
        print(f"[STT] Connected: {user.email} | engine={STT_ENGINE}")

        # ── Connect to cloud engines ─────────────────────────────────────────
        if STT_ENGINE == "deepgram":
            # Run as background task — audio arriving before DG connects is buffered
            asyncio.create_task(self._connect_deepgram())
        elif STT_ENGINE == "gemini":
            # Run setup as a background task so connect() returns immediately.
            # Audio arriving during setup is buffered and flushed once ready.
            asyncio.create_task(self._connect_gemini())

    # ── Engine connection helpers ─────────────────────────────────────────────

    async def _connect_deepgram(self):
        try:
            import websockets
            # nova-3: latest Deepgram model — best accuracy, better handling of
            # accents and domain-specific vocabulary than nova-2.
            DEEPGRAM_MODEL = config("DEEPGRAM_MODEL", default="nova-3")
            url = (
                f'wss://api.deepgram.com/v1/listen'
                f'?model={DEEPGRAM_MODEL}'
                f'&encoding=linear16&sample_rate=16000&channels=1'
                f'&smart_format=true&punctuate=true'
                f'&interim_results=true'
            )
            headers = {'Authorization': f'Token {DEEPGRAM_API_KEY}'}

            # websockets library changed the keyword across versions
            for kw in ('extra_headers', 'additional_headers', 'headers'):
                try:
                    self.dg_ws = await websockets.connect(url, **{kw: headers})
                    break
                except TypeError:
                    continue

            if self.dg_ws:
                self.dg_task = asyncio.create_task(self._receive_deepgram())
                # Mark ready and flush buffered audio
                self.dg_ready = True
                if self.dg_pre_buffer:
                    print(f"[STT] Flushing {len(self.dg_pre_buffer)} buffered chunks to Deepgram")
                    for chunk_bytes in self.dg_pre_buffer:
                        try:
                            await self.dg_ws.send(chunk_bytes)
                        except Exception:
                            pass
                    self.dg_pre_buffer.clear()
                print(f"[STT] Deepgram {DEEPGRAM_MODEL} WS connected")
            else:
                print("[STT] Could not connect to Deepgram — no valid header kwarg found")
        except ImportError:
            print("[STT] 'websockets' package missing — pip install websockets")
        except Exception as e:
            print(f"[STT] Deepgram connection failed: {e}")

    async def _connect_gemini(self):
        try:
            import websockets
            GEMINI_API_KEY = config("GEMINI_API_KEY", default="")
            if not GEMINI_API_KEY:
                print("[STT] GEMINI_API_KEY is not set in .env")
                return

            url = (
                f"wss://generativelanguage.googleapis.com/ws/"
                f"google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"
                f"?key={GEMINI_API_KEY}"
            )
            self.gemini_ws = await websockets.connect(url)

            setup_msg = {
                "setup": {
                    "model": GEMINI_STT_MODEL,
                    "realtimeInputConfig": {
                        "automaticActivityDetection": {}
                    },
                    "inputAudioTranscription": {}
                }
            }
            await self.gemini_ws.send(json.dumps(setup_msg))
            print(f"[STT] Gemini setup sent — model={GEMINI_STT_MODEL}")

            # Wait for setupComplete
            async def _await_setup():
                while True:
                    raw = await self.gemini_ws.recv()
                    resp = json.loads(raw)
                    print(f"[STT] Gemini setup phase msg: {list(resp.keys())}")
                    if "setupComplete" in resp:
                        print("[STT] Gemini setup complete — ready for audio")
                        return

            try:
                await asyncio.wait_for(_await_setup(), timeout=10.0)
            except asyncio.TimeoutError:
                print("[STT] Gemini setupComplete timed out — proceeding anyway")

            # Start background receiver BEFORE flushing the buffer
            self.gemini_task = asyncio.create_task(self._receive_gemini())

            # Mark ready and flush any audio that arrived during setup
            self.gemini_ready = True
            if self.gemini_pre_buffer:
                print(f"[STT] Flushing {len(self.gemini_pre_buffer)} buffered audio chunks to Gemini")
                for buffered_msg in self.gemini_pre_buffer:
                    try:
                        await self.gemini_ws.send(buffered_msg)
                    except Exception:
                        pass
                self.gemini_pre_buffer.clear()

            print("[STT] Gemini Live WS ready")
        except ImportError:
            print("[STT] 'websockets' package missing — pip install websockets")
        except Exception as e:
            print(f"[STT] Gemini connection failed: {e}")

    # ── Disconnect ────────────────────────────────────────────────────────────

    async def disconnect(self, close_code):
        print(f"[STT] Disconnected ({close_code})")
        for attr in ('dg_task', 'gemini_task'):
            task = getattr(self, attr, None)
            if task:
                task.cancel()
        for attr in ('dg_ws', 'gemini_ws'):
            ws = getattr(self, attr, None)
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass

    # ── Cloud receive loops ───────────────────────────────────────────────────

    async def _receive_deepgram(self):
        try:
            async for message in self.dg_ws:
                data = json.loads(message)
                if data.get("type") == "Results":
                    is_final = data.get("is_final", False)
                    transcript = (
                        data.get("channel", {})
                        .get("alternatives", [{}])[0]
                        .get("transcript", "")
                    )
                    print(f"[STT] Deepgram msg - is_final: {is_final}, transcript: {transcript!r}")
                    if is_final:
                        if transcript:
                            self.dg_transcript += (" " + transcript)
                        self.dg_current = ""
                    elif transcript:
                        self.dg_current = transcript

                    full = (self.dg_transcript + " " + self.dg_current).strip()
                    if full:
                        try:
                            await self.send(json.dumps({
                                "type": "transcript",
                                "text": full,
                                "is_final": False,
                            }))
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[STT] Deepgram recv error: {e}")

    async def _receive_gemini(self):
        """
        Receive loop for gemini-3.5-transcribe-live (dedicated STT model).

        Response format differs from general Gemini Live:
          - Transcriptions arrive as: serverContent.inputTranscription.text
          - Turn end is signalled by: serverContent.turnComplete == True
          - General modelTurn.parts[] is checked as a fallback.
        """
        try:
            async for message in self.gemini_ws:
                data = json.loads(message)

                if "serverContent" not in data:
                    print(f"[STT] Gemini non-serverContent msg keys: {list(data.keys())}")
                    continue

                sc = data["serverContent"]

                # ── Interim transcription: partial, streaming result ───────────
                # Show in the UI while the user is still speaking.
                interim = sc.get("interimInputTranscription", {})
                interim_text = interim.get("text", "")
                if interim_text:
                    print(f"[STT] Gemini interim: {interim_text!r}")
                    try:
                        await self.send(json.dumps({
                            "type": "transcript",
                            "text": (self.gemini_transcript + " " + interim_text).strip(),
                            "is_final": False,
                        }))
                    except Exception:
                        pass

                # ── Final transcription: confirmed text chunk ─────────────────
                final_trans = sc.get("inputTranscription", {})
                final_text = final_trans.get("text", "")
                if final_text:
                    self.gemini_transcript += (" " + final_text)
                    print(f"[STT] Gemini final chunk: {final_text!r}")
                    try:
                        await self.send(json.dumps({
                            "type": "transcript",
                            "text": self.gemini_transcript.strip(),
                            "is_final": False,
                        }))
                    except Exception:
                        pass

                # ── Fallback: general Gemini model uses modelTurn ─────────────
                model_turn = sc.get("modelTurn", {})
                for part in model_turn.get("parts", []):
                    part_text = part.get("text", "")
                    if part_text:
                        self.gemini_transcript += (" " + part_text)
                        print(f"[STT] Gemini modelTurn chunk: {part_text!r}")
                        try:
                            await self.send(json.dumps({
                                "type": "transcript",
                                "text": self.gemini_transcript.strip(),
                                "is_final": False,
                            }))
                        except Exception:
                            pass

                # ── generationComplete: the STT model is done ─────────────────
                # gemini-3.5-transcribe-live uses generationComplete, NOT turnComplete.
                if sc.get("generationComplete"):
                    print("[STT] Gemini generationComplete — transcript ready")
                    self.gemini_turn_done.set()

                # ── turnComplete: used by general Gemini Live models ──────────
                if sc.get("turnComplete"):
                    print("[STT] Gemini turnComplete — transcript ready")
                    self.gemini_turn_done.set()

                # ── speechState: VAD info (optional logging) ──────────────────
                speech_state = sc.get("speechState", "")
                if speech_state:
                    print(f"[STT] Gemini speechState: {speech_state}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[STT] Gemini recv error: {e}")

    # ── Receive from frontend ─────────────────────────────────────────────────

    async def receive(self, text_data=None, bytes_data=None):

        # ── Binary: raw Float32 PCM at 16 kHz ────────────────────────────────
        if bytes_data:
            chunk = np.frombuffer(bytes_data, dtype=np.float32)
            self.audio_buffer = np.concatenate([self.audio_buffer, chunk])

            if STT_ENGINE == "deepgram":
                pcm = np.clip(chunk, -1.0, 1.0)

                # Session-level normalization: track the loudest chunk so far and
                # apply a STABLE gain factor. Per-chunk normalization is wrong because
                # it boosts silence (tiny peak) to full volume, making Deepgram's VAD
                # think silence = speech. Session-level normalization preserves dynamics:
                # silence stays quiet, speech stays loud — VAD works correctly.
                peak = float(np.max(np.abs(pcm)))
                if peak > self.dg_session_peak:
                    self.dg_session_peak = peak

                if self.dg_session_peak > 0.05:  # only apply once we've seen real speech
                    gain = min(0.9 / self.dg_session_peak, 8.0)  # cap at 8x
                    pcm = pcm * gain

                raw_bytes = (pcm * 32767).astype(np.int16).tobytes()
                if not self.dg_ready:
                    self.dg_pre_buffer.append(raw_bytes)
                elif self.dg_ws:
                    try:
                        await self.dg_ws.send(raw_bytes)
                    except Exception as e:
                        print(f"[STT] Deepgram audio send failed: {e}")

            elif STT_ENGINE == "gemini" and self.gemini_ws:
                pcm_int16 = np.clip(chunk, -1.0, 1.0)
                pcm_int16 = (pcm_int16 * 32767).astype(np.int16)
                b64 = base64.b64encode(pcm_int16.tobytes()).decode("utf-8")
                msg = json.dumps({
                    "realtimeInput": {
                        "mediaChunks": [{
                            "mimeType": "audio/pcm;rate=16000",
                            "data": b64
                        }]
                    }
                })
                if not self.gemini_ready:
                    # Gemini setup still in progress — buffer for later
                    self.gemini_pre_buffer.append(msg)
                else:
                    try:
                        await self.gemini_ws.send(msg)
                    except Exception as e:
                        print(f"[STT] Gemini audio send failed: {e}")

        # ── Text: control messages ────────────────────────────────────────────
        elif text_data:
            data = json.loads(text_data)

            if data.get("type") == "config":
                self.client_sample_rate = data.get("sampleRate", 16000)
                print(f"[STT] Client sample rate: {self.client_sample_rate} Hz")

            elif data.get("type") == "finalize":
                await self._handle_finalize()

    async def _handle_finalize(self):
        """Triggered when the user stops speaking. Returns the final transcript."""
        async with self.transcribe_lock:
            transcript = ""

            if STT_ENGINE == "deepgram" and self.dg_ws:
                # Send an empty byte array to explicitly tell Deepgram the stream is over.
                # This forces Deepgram to instantly flush any remaining audio buffer and
                # return the final words, instead of waiting for a silence timeout.
                try:
                    await self.dg_ws.send(b'')
                except Exception as e:
                    print(f"[STT] Deepgram end-of-stream signal failed: {e}")
                
                # Wait for Deepgram to send the last Results message and close the connection
                if self.dg_task:
                    try:
                        await asyncio.wait_for(self.dg_task, timeout=3.0)
                    except asyncio.TimeoutError:
                        print("[STT] Deepgram response timed out — using partial text")
                transcript = (self.dg_transcript + " " + self.dg_current).strip()
                self.dg_transcript = ""
                self.dg_current = ""

            elif STT_ENGINE == "gemini" and self.gemini_ws:
                # With automaticActivityDetection, the server VAD may have already
                # detected silence and set gemini_turn_done BEFORE the frontend
                # sent 'finalize'. We must NOT blindly call .clear() first or we
                # wipe the event that already fired — causing a 10s timeout.
                #
                # Strategy:
                #   1. If already done (VAD fired) — use the text immediately.
                #   2. If not done yet — send turnComplete to nudge Gemini, then wait.

                if self.gemini_turn_done.is_set():
                    # VAD already finished, transcript is ready right now
                    print("[STT] Gemini VAD already done — using accumulated text")
                else:
                    # VAD hasn't finished yet. Nudge Gemini with explicit turnComplete
                    # and wait up to 12s for the server to finish processing.
                    try:
                        await self.gemini_ws.send(json.dumps({
                            "clientContent": {"turnComplete": True}
                        }))
                    except Exception as e:
                        print(f"[STT] Gemini turnComplete signal failed: {e}")

                    try:
                        await asyncio.wait_for(self.gemini_turn_done.wait(), timeout=12.0)
                    except asyncio.TimeoutError:
                        print("[STT] Gemini response timed out — using partial text")

                transcript = self.gemini_transcript.strip()
                # Reset state for the next turn
                self.gemini_transcript = ""
                self.gemini_turn_done.clear()

            else:
                # Local Whisper (faster-whisper / transformers)
                transcript = await self._transcribe_local()

        # ── Debug: save audio for inspection ─────────────────────────────────
        self._save_debug_wav()

        # ── Build final response ──────────────────────────────────────────────
        if transcript and transcript.strip():
            final_text = transcript.strip()
        else:
            final_text = self._empty_transcript_message()

        self.audio_buffer = np.array([], dtype=np.float32)
        await self.send(json.dumps({
            "type": "transcript",
            "text": final_text,
            "is_final": True,
        }))

    # ── Local Whisper transcription ───────────────────────────────────────────

    async def _transcribe_local(self):
        try:
            if len(self.audio_buffer) == 0:
                return ""

            # Normalize to peak 0.9 so Whisper always gets well-levelled audio.
            # Without this, quiet mics produce RMS~0.04 which Whisper struggles with.
            audio_array = self.audio_buffer.copy()
            max_amp = np.max(np.abs(audio_array))
            if max_amp > 0.001:  # skip if near-silent (pure silence/noise)
                audio_array = audio_array * (0.9 / max_amp)

            prompt_text = "Technical interview."
            if getattr(self, 'job_title', ''):
                prompt_text += f" Job role: {self.job_title}."
            if getattr(self, 'skills', ''):
                prompt_text += f" Keywords: {self.skills}."

            text = await asyncio.to_thread(self._run_inference_sync, audio_array, prompt_text)

            if not text:
                return ""

            # Filter known Whisper hallucinations on silent audio
            hallucination_triggers = [
                "candidate speaks english", "indian accent", "indian-english",
                "technical terms, names", "candidate is not a professional",
                "technical interview. machine learning", "native english speaker",
                "i'm a native english speaker", "i am a native english speaker"
            ]
            lower = text.lower()
            for trigger in hallucination_triggers:
                if trigger in lower:
                    print(f"[STT] Hallucination filtered: {text!r}")
                    return ""

            return text
        except Exception as e:
            print(f"[STT] Local transcription error: {e}")
            return ""

    def _run_inference_sync(self, audio_array, prompt_text):
        """Synchronous inference — called in a thread."""
        if STT_ENGINE == "faster-whisper":
            model = _get_local_model()
            try:
                segments, _ = model.transcribe(
                    audio_array,
                    language="en",
                    initial_prompt=prompt_text,
                    vad_filter=True,
                )
                return "".join(seg.text for seg in segments).strip()
            except Exception as e:
                print(f"[STT] faster-whisper error: {e}")
                return ""
        else:
            # HuggingFace transformers Whisper
            processor, model = _get_local_model()
            inputs = processor(audio_array, sampling_rate=16000, return_tensors="pt")
            input_features = inputs.input_features.to(device=_device, dtype=_dtype_hf)

            prompt_ids_tensor = None
            try:
                if hasattr(processor, 'get_prompt_ids'):
                    ids = processor.get_prompt_ids(prompt_text)
                    prompt_ids_tensor = (
                        ids.to(_device) if isinstance(ids, torch.Tensor)
                        else torch.tensor(ids).to(_device)
                    )
            except Exception as e:
                print(f"[STT] prompt_ids error: {e}")

            gen_kwargs = {"language": "en", "task": "transcribe"}
            if prompt_ids_tensor is not None:
                gen_kwargs["prompt_ids"] = prompt_ids_tensor

            with torch.no_grad():
                generated_ids = model.generate(input_features, **gen_kwargs)

            return processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _save_debug_wav(self):
        try:
            if len(self.audio_buffer) == 0:
                return
            audio_int16 = (self.audio_buffer * 32767).astype(np.int16)
            with wave.open('debug_audio.wav', 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_int16.tobytes())
            print(f"[STT] debug_audio.wav saved ({len(self.audio_buffer)} frames)")
        except Exception as e:
            print(f"[STT] debug_audio.wav save failed: {e}")

    def _empty_transcript_message(self):
        if STT_ENGINE == "deepgram":
            return (
                "DEBUG: Deepgram connected but received empty transcript. Speak louder?"
                if self.dg_ws else
                "DEBUG: Deepgram WS not connected. Check DEEPGRAM_API key."
            )
        if STT_ENGINE == "gemini":
            return (
                "DEBUG: Gemini connected but received empty transcript."
                if self.gemini_ws else
                "DEBUG: Gemini WS not connected. Check GEMINI_API_KEY."
            )
        return "candidate did not respond"

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
            return "Software Engineer", "Tech Stack, ReactJS, Django, PostgreSQL"
        try:
            interview = Interview.objects.get(session_token=session_token)
            skills = ", ".join(interview.skills) if interview.skills else ""
            title = interview.job.title if interview.job else ""
            return title, skills
        except Exception:
            return "", ""
