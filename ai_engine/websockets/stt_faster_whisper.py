"""
STT Engine: Faster-Whisper
Optimised CTranslate2-backed Whisper inference (CPU/GPU).
Loaded lazily on first use and cached as a module-level singleton.

.env configuration:
    STT_ENGINE=faster-whisper       # <- set this to use this engine
    STT_MODEL_SIZE=medium           # tiny | base | small | medium | large-v2 | large-v3
"""

from decouple import config
import torch
from faster_whisper import WhisperModel

# -- Config -------------------------------------------------------------------
STT_MODEL_SIZE = config("STT_MODEL_SIZE", default="medium")

_device = "cuda" if torch.cuda.is_available() else "cpu"
_compute_type = "float16" if _device == "cuda" else "int8"

_model = None  # Singleton


def get_model() -> WhisperModel:
    """Return the cached Faster-Whisper model, loading it on first call."""
    global _model
    if _model is None:
        print(
            f"[STT][faster-whisper] Loading model '{STT_MODEL_SIZE}' "
            f"on {_device} ({_compute_type})"
        )
        _model = WhisperModel(STT_MODEL_SIZE, device=_device, compute_type=_compute_type)
    return _model


def run_inference(audio_array, prompt_text: str) -> str:
    """
    Run synchronous Faster-Whisper transcription.

    Args:
        audio_array: float32 numpy array, 16 kHz mono, range [-1, 1].
        prompt_text: Optional initial prompt to bias decoding.

    Returns:
        Transcribed text string (may be empty).
    """
    model = get_model()
    try:
        segments, _ = model.transcribe(
            audio_array,
            language="en",
            initial_prompt=prompt_text,
            vad_filter=True,
        )
        return "".join(segment.text for segment in segments).strip()
    except Exception as e:
        print(f"[STT][faster-whisper] Inference error: {e}")
        return ""
