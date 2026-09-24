"""
STT Engine: Transformers (HuggingFace Whisper)
Standard HuggingFace Transformers-based Whisper inference (CPU/GPU).
Loaded lazily on first use and cached as a module-level singleton.

.env configuration:
    STT_ENGINE=transformers         # <- set this to use this engine
    HF_MODEL_ID=openai/whisper-medium  # any HF Whisper model ID, e.g.:
                                       #   openai/whisper-tiny
                                       #   openai/whisper-base
                                       #   openai/whisper-small
                                       #   openai/whisper-medium   (default)
                                       #   openai/whisper-large-v3
                                       #   vasista22/whisper-hindi-large-v2 (multilingual)
"""

from decouple import config
import torch
from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

# -- Config -------------------------------------------------------------------
HF_MODEL_ID = config("HF_MODEL_ID", default="openai/whisper-medium")

_device = "cuda" if torch.cuda.is_available() else "cpu"
_dtype = torch.float16 if _device == "cuda" else torch.float32

_model = None      # Singleton
_processor = None  # Singleton


def _load():
    """Load model and processor if not already loaded."""
    global _model, _processor
    if _model is None or _processor is None:
        print(f"[STT][transformers] Loading model '{HF_MODEL_ID}' on {_device}")
        _processor = AutoProcessor.from_pretrained(HF_MODEL_ID)
        _model = AutoModelForSpeechSeq2Seq.from_pretrained(HF_MODEL_ID, torch_dtype=_dtype)
        _model.to(_device)
        _model.eval()


def get_model():
    """Return the cached (processor, model) tuple, loading on first call."""
    _load()
    return _processor, _model


def run_inference(audio_array, prompt_text: str) -> str:
    """
    Run synchronous HuggingFace Transformers Whisper transcription.

    Args:
        audio_array: float32 numpy array, 16 kHz mono, range [-1, 1].
        prompt_text: Optional initial prompt to bias decoding.

    Returns:
        Transcribed text string (may be empty).
    """
    processor, model = get_model()
    try:
        inputs = processor(audio_array, sampling_rate=16000, return_tensors="pt")
        input_features = inputs.input_features.to(device=_device, dtype=_dtype)

        prompt_ids_tensor = None
        try:
            if hasattr(processor, "get_prompt_ids"):
                prompt_ids = processor.get_prompt_ids(prompt_text)
                if not isinstance(prompt_ids, torch.Tensor):
                    prompt_ids_tensor = torch.tensor(prompt_ids).to(_device)
                else:
                    prompt_ids_tensor = prompt_ids.to(_device)
        except Exception as e:
            print(f"[STT][transformers] Could not generate prompt IDs: {e}")

        with torch.no_grad():
            generate_kwargs = {"language": "en", "task": "transcribe"}
            if prompt_ids_tensor is not None:
                generate_kwargs["prompt_ids"] = prompt_ids_tensor
            generated_ids = model.generate(input_features, **generate_kwargs)

        return processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
    except Exception as e:
        print(f"[STT][transformers] Inference error: {e}")
        return ""
