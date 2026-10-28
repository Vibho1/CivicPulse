"""Audio normalisation for model input.

Browsers record ``audio/webm;codecs=opus`` (Chrome/Android) or ``audio/mp4``
(Safari/iOS). Gemini officially accepts WAV/MP3/AIFF/AAC/OGG/FLAC, so we
transcode anything else to 16 kHz mono FLAC with ffmpeg when it is available.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from .base import Media

log = logging.getLogger(__name__)

DIRECT_MIME = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/aac",
    "audio/flac",
    "audio/x-flac",
    "audio/aiff",
    "audio/x-aiff",
}

_EXT_FOR = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "video/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/3gpp": ".3gp",
    "audio/amr": ".amr",
}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def normalise_audio(audio: Media) -> Media:
    """Return model-ready audio. Never raises; falls back to the original."""
    base_mime = audio.mime_type.split(";")[0].strip().lower() or "audio/webm"
    if base_mime in DIRECT_MIME:
        return Media(audio.data, base_mime, audio.label)
    if not ffmpeg_available():
        log.warning("ffmpeg not found; sending %s to the model as-is", base_mime)
        return Media(audio.data, base_mime, audio.label)
    ext = _EXT_FOR.get(base_mime, ".bin")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{ext}"
        dst = Path(tmp) / "out.flac"
        src.write_bytes(audio.data)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "flac", str(dst)]
        try:
            subprocess.run(cmd, check=True, timeout=30, capture_output=True)
            return Media(dst.read_bytes(), "audio/flac", audio.label)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            log.warning("ffmpeg transcode failed (%s); sending original bytes", exc)
            return Media(audio.data, base_mime, audio.label)


WAV_MIME = {"audio/wav", "audio/x-wav", "audio/wave"}


def _ffprobe(path: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", *args, str(path)], check=True, timeout=15, capture_output=True, text=True)
        return out.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def probe_duration_s(audio: Media) -> float | None:
    """Best-effort clip length in seconds; None when it cannot be determined. Never raises."""
    base_mime = audio.mime_type.split(";")[0].strip().lower()
    if base_mime in WAV_MIME:
        try:
            with wave.open(io.BytesIO(audio.data)) as w:
                return w.getnframes() / float(w.getframerate())
        except (wave.Error, EOFError, ZeroDivisionError):
            pass  # not plain PCM; let ffprobe try
    if shutil.which("ffprobe") is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{_EXT_FOR.get(base_mime, '.wav' if base_mime in WAV_MIME else '.bin')}"
        src.write_bytes(audio.data)
        out = _ffprobe(src, "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1")
        try:
            return float((out or "").strip())
        except ValueError:
            pass
        # Browser (MediaRecorder) WebM carries no duration header: use the last packet timestamp.
        out = _ffprobe(src, "-select_streams", "a:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0")
        times = []
        for line in (out or "").splitlines():
            try:
                times.append(float(line.strip().strip(",")))
            except ValueError:
                continue
        return max(times) if times else None
