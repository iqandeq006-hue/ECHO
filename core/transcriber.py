"""
Faster-Whisper Inference Engine — Pure CTranslate2 Model Router

Focused exclusively on the faster-whisper family:
- Standard: tiny, base, small, medium, large-v1, large-v2, large-v3, large-v3-turbo
- English-only: tiny.en, base.en, small.en, medium.en
- Distil-Whisper: distil-small.en, distil-medium.en, distil-large-v2, distil-large-v3
- Local model subdirectories in `models/`

Loads directly from disk if available in `models/<model_name>`, or downloads
automatically from HuggingFace on first run into `models/<model_name>`.
"""

import os
import sys
import logging
import platform
import importlib.util
import glob

logger = logging.getLogger(__name__)

# Fallback sequence of faster-whisper models if requested model fails
FALLBACK_CHAIN = ["large-v3-turbo", "distil-large-v3", "small", "base", "tiny"]


def _register_nvidia_dll_dirs():
    """Register CUDA/cuDNN DLL paths on Windows for CTranslate2 GPU execution."""
    if platform.system() != "Windows":
        return
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.nvjitlink", "nvidia.cuda_nvrtc"):
        try:
            spec = importlib.util.find_spec(pkg)
            if not spec or not spec.submodule_search_locations:
                continue
            for base in spec.submodule_search_locations:
                for sub in ("bin", "lib"):
                    loc = os.path.join(base, sub)
                    if os.path.isdir(loc) and loc not in os.environ.get("PATH", ""):
                        os.add_dll_directory(loc)
                        os.environ["PATH"] = loc + os.pathsep + os.environ["PATH"]
                        logger.info("Registered DLL directory: %s", loc)
        except Exception:
            pass


_register_nvidia_dll_dirs()


class TranscriptionError(Exception):
    """Raised when transcription genuinely fails on faster-whisper."""
    pass


def _get_models_dir() -> str:
    """Returns the absolute path to the local `models` directory, creating it if needed."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(__file__))
    candidate = os.path.join(base, 'models')
    os.makedirs(candidate, exist_ok=True)
    return candidate


def _pick_device() -> str:
    """Check GPU availability via ctranslate2 or torch."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class Transcriber:
    """Pure Faster-Whisper Transcriber engine with local caching & fallback recovery."""

    def __init__(self, model="tiny"):
        self.model_name = model
        self.backend = "faster-whisper"
        self.model = None
        self.device = None
        self._load_with_fallbacks(model)

    def _load_with_fallbacks(self, initial_model: str):
        """Attempts to load initial_model, and falls back gracefully down the chain if missing/failing.

        Two-pass strategy:
          Pass 1 (LOCAL ONLY): Try the requested model offline, then every
                 fallback model offline. No network requests at all.
          Pass 2 (ONLINE, last resort): If nothing loaded locally, try
                 downloading the requested model from HuggingFace, then
                 each fallback in order.
        """
        # --- PASS 1: exhaust every local model before touching the network ---
        if self._try_load_faster_whisper(initial_model, offline_only=True):
            return

        logger.warning("Requested model '%s' not available locally. Trying local fallbacks...", initial_model)

        for fallback in FALLBACK_CHAIN:
            if fallback == initial_model:
                continue
            logger.info("Trying local fallback model: %s", fallback)
            if self._try_load_faster_whisper(fallback, offline_only=True):
                logger.info("Successfully loaded local fallback model: %s", fallback)
                return

        # --- PASS 2: no local model worked — try online download as last resort ---
        logger.warning("No local models available. Attempting online download...")

        if self._try_load_faster_whisper(initial_model, offline_only=False):
            return

        for fallback in FALLBACK_CHAIN:
            if fallback == initial_model:
                continue
            logger.warning("Attempting online download of fallback model: %s", fallback)
            if self._try_load_faster_whisper(fallback, offline_only=False):
                logger.info("Successfully downloaded fallback model: %s", fallback)
                return

        # If everything failed
        raise TranscriptionError(f"Could not load requested faster-whisper model '{initial_model}' or any fallback models.")

    def _try_load_faster_whisper(self, model_input: str, offline_only: bool = True) -> bool:
        """Loads a faster-whisper model by name or local directory.

        When offline_only=True (default), ONLY checks the local models/
        directory — never touches the network.
        When offline_only=False, attempts to download from HuggingFace if
        no local files are found.
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            logger.error("faster-whisper package is not installed: %s", e)
            return False

        device = _pick_device()
        compute_type = "int8"
        devices_to_try = [device]
        if device == "cuda":
            devices_to_try.append("cpu")

        models_dir = _get_models_dir()
        safe_folder_name = os.path.basename(model_input.rstrip('/\\'))
        local_model_path = os.path.join(models_dir, safe_folder_name)

        is_explicit_dir = os.path.isdir(model_input)
        target_local_dir = model_input if is_explicit_dir else local_model_path

        has_local_files = os.path.isdir(target_local_dir) and any(
            os.path.isfile(os.path.join(target_local_dir, fname))
            for fname in ("model.bin", "model.safetensors", "config.json")
        )

        # HuggingFace's download_root creates a nested cache layout:
        #   models/<name>/models--Systran--faster-whisper-<name>/snapshots/<hash>/model.bin
        # If we didn't find files at the top level, probe the HF cache tree.
        if not has_local_files and os.path.isdir(target_local_dir):
            hf_pattern = os.path.join(target_local_dir, "models--*", "snapshots", "*")
            for snapshot_dir in sorted(glob.glob(hf_pattern), reverse=True):
                if any(
                    os.path.isfile(os.path.join(snapshot_dir, fname))
                    for fname in ("model.bin", "model.safetensors", "config.json")
                ):
                    logger.info(
                        "Found model files inside HuggingFace cache at '%s'",
                        snapshot_dir,
                    )
                    target_local_dir = snapshot_dir
                    has_local_files = True
                    break

        # --- LOCAL LOAD (always attempted first) ---
        if has_local_files:
            logger.info("Found local model files at '%s'. Loading 100%% offline...", target_local_dir)
            os.environ["HF_HUB_OFFLINE"] = "1"
            for dev in devices_to_try:
                try:
                    self.model = WhisperModel(target_local_dir, device=dev, compute_type=compute_type)
                    self.device = dev
                    self.model_name = model_input
                    logger.info("Successfully loaded local faster-whisper model from '%s' (device=%s)", target_local_dir, dev)
                    return True
                except Exception as exc:
                    logger.warning("Local offline load failed at '%s' (device=%s): %s", target_local_dir, dev, exc)
            logger.warning("Local model directory '%s' is present but failed to load.", target_local_dir)

        # If offline_only, stop here — do not attempt any network access.
        if offline_only:
            return False

        # --- ONLINE DOWNLOAD (only when offline_only=False) ---
        logger.info("Model '%s' not present locally at '%s'. Starting auto-download from HuggingFace...", model_input, local_model_path)
        os.environ.pop("HF_HUB_OFFLINE", None)

        for dev in devices_to_try:
            logger.info("Downloading & loading faster-whisper model: %s -> %s (device=%s)", model_input, models_dir, dev)
            try:
                self.model = WhisperModel(model_input, device=dev, compute_type=compute_type, download_root=models_dir)
                self.device = dev
                self.model_name = model_input
                os.environ["HF_HUB_OFFLINE"] = "1"
                logger.info("Successfully downloaded & loaded faster-whisper model '%s' (device=%s)", model_input, dev)
                return True
            except Exception as exc:
                if dev == "cuda" and devices_to_try[-1] == "cpu":
                    logger.warning("CUDA download/load failed for '%s', retrying on CPU...", model_input)
                    continue
                logger.error("Download/load failed for model '%s': %s", model_input, exc)
                os.environ["HF_HUB_OFFLINE"] = "1"
                return False
        os.environ["HF_HUB_OFFLINE"] = "1"
        return False

    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio file using faster-whisper CTranslate2 runtime."""
        if not self.model:
            raise TranscriptionError("No faster-whisper model is currently loaded")

        logger.info("Transcribing audio (%s) using faster-whisper (model=%s)", audio_path, self.model_name)

        try:
            segments, _info = self.model.transcribe(audio_path)
            text = " ".join(segment.text for segment in segments).strip()
            logger.info("Transcription success: '%s'", text)
            return text
        except Exception as exc:
            logger.exception("Transcription execution error on audio file: %s", audio_path)
            raise TranscriptionError(f"Faster-Whisper transcription failed: {exc}") from exc


# Alias for backward/forward compatibility
CompatibleTranscriber = Transcriber
