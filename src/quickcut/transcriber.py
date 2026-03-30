"""Transcription engine using faster-whisper with caching."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from quickcut.ffmpeg_executor import FFmpegExecutor
from quickcut.media_prober import compute_file_hash
from quickcut.models import Transcript, TranscriptSegment, TranscriptWord

logger = logging.getLogger(__name__)


class Transcriber:
    """Generates word-level transcripts from audio/video using faster-whisper.

    Transcripts are cached by file hash + model name so repeated runs
    return instantly.
    """

    def __init__(
        self,
        model_name: str = "medium",
        device: str = "auto",
        compute_type: str = "auto",
    ) -> None:
        self.model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._executor = FFmpegExecutor()

    def _resolve_device(self) -> tuple[str, str]:
        """Resolve device and compute_type from 'auto' settings."""
        device = self._device
        compute_type = self._compute_type

        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        return device, compute_type

    def _ensure_model(self) -> None:
        """Lazy-load the faster-whisper model on first use."""
        if self._model is not None:
            return

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper is required for transcription. "
                "Install with: pip install 'quickcut[transcription]'"
            )

        device, compute_type = self._resolve_device()
        logger.info(
            "Loading whisper model '%s' on %s (%s)...",
            self.model_name, device, compute_type,
        )
        self._model = WhisperModel(
            self.model_name, device=device, compute_type=compute_type
        )
        logger.info("Model loaded successfully.")

    def _get_cache_path(self, file_path: Path, cache_dir: Path) -> Path:
        """Return the cache path for a transcription result."""
        file_hash = compute_file_hash(file_path)
        cache_dir = cache_dir / ".cache" / "transcripts"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{file_hash}_{self.model_name}.json"

    def _extract_audio(self, file_path: Path) -> Path:
        """Extract audio from a media file to a 16kHz mono WAV."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="quickcut_audio_"))
        wav_path = tmp_dir / "audio.wav"

        self._executor.run([
            "-i", str(file_path),
            "-vn",                    # no video
            "-acodec", "pcm_s16le",   # 16-bit PCM
            "-ar", "16000",           # 16kHz
            "-ac", "1",               # mono
            "-y", str(wav_path),
        ])

        logger.debug("Extracted audio to %s", wav_path)
        return wav_path

    def transcribe(
        self,
        file_path: Path,
        cache_dir: Path,
        language: str | None = None,
    ) -> Transcript:
        """Transcribe a media file and return a word-level transcript.

        Results are cached by file hash + model name.

        Args:
            file_path: Path to audio or video file.
            cache_dir: Directory for transcript cache.
            language: Optional language code (auto-detect if None).

        Returns:
            Transcript with word-level timestamps.
        """
        cache_path = self._get_cache_path(file_path, cache_dir)

        # Check cache first
        if cache_path.exists():
            logger.info("Loading cached transcript from %s", cache_path)
            data = json.loads(cache_path.read_text())
            return Transcript.model_validate(data)

        # Generate transcript
        self._ensure_model()
        wav_path = self._extract_audio(file_path)

        logger.info("Transcribing %s...", file_path.name)
        kwargs: dict = {
            "word_timestamps": True,
            "vad_filter": True,
        }
        if language:
            kwargs["language"] = language

        segments_iter, info = self._model.transcribe(str(wav_path), **kwargs)

        # Convert to our models
        segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            words: list[TranscriptWord] = []
            if seg.words:
                for w in seg.words:
                    words.append(TranscriptWord(
                        word=w.word.strip(),
                        start=round(w.start, 3),
                        end=round(w.end, 3),
                        confidence=round(w.probability, 3),
                    ))

            segments.append(TranscriptSegment(
                text=seg.text.strip(),
                start=round(seg.start, 3),
                end=round(seg.end, 3),
                words=words,
            ))

        transcript = Transcript(
            segments=segments,
            source_id=file_path.stem,
            model_name=self.model_name,
            language=info.language if hasattr(info, "language") else (language or "en"),
            duration=info.duration if hasattr(info, "duration") else 0.0,
        )

        # Cache result
        cache_path.write_text(transcript.model_dump_json(indent=2))
        logger.info(
            "Transcript cached (%d segments, %d words)",
            len(transcript.segments),
            len(transcript.all_words),
        )

        # Cleanup temp audio
        try:
            wav_path.unlink()
            wav_path.parent.rmdir()
        except OSError:
            pass

        return transcript

    @staticmethod
    def clear_cache(cache_dir: Path) -> int:
        """Remove all cached transcripts. Returns count of files removed."""
        cache_path = cache_dir / ".cache" / "transcripts"
        if not cache_path.exists():
            return 0

        count = 0
        for f in cache_path.glob("*.json"):
            f.unlink()
            count += 1

        logger.info("Cleared %d cached transcripts", count)
        return count
