"""Audio normalization using ffmpeg-normalize for EBU R128 compliance."""

from __future__ import annotations

import logging
from pathlib import Path

from quickcut.ffmpeg_executor import FFmpegExecutor

logger = logging.getLogger(__name__)


class AudioNormalizer:
    """Provides two-pass loudness normalization using ffmpeg-normalize."""

    def __init__(self, executor: FFmpegExecutor | None = None) -> None:
        self.executor = executor or FFmpegExecutor()

    def normalize(
        self,
        input_path: Path,
        output_path: Path,
        target_lufs: float = -23.0,
        true_peak: float = -2.0,
    ) -> Path:
        """Normalize audio stream in media file.

        Args:
            input_path: Source media file.
            output_path: Target media file.
            target_lufs: Target LUFS (default: -23.0 EBU recommendation).
            true_peak: True peak limit in dB.

        Returns:
            The normalized file path.
        """
        logger.info(
            "Normalizing %s to %.1f LUFS (TP %.1f dB)...",
            input_path.name, target_lufs, true_peak,
        )
        
        try:
            from ffmpeg_normalize import FFmpegNormalize
            norm = FFmpegNormalize(
                target_level=target_lufs,
                true_peak=true_peak,
                loudness_range_target=7.0,
                audio_codec="aac",
                audio_bitrate="192k",
                video_codec="copy",  # Passthrough video
                subtitle_codec="copy",
            )
            
            norm.add_media_file(str(input_path), str(output_path))
            norm.run_normalization()
            logger.info("Normalization complete.")
            return output_path
            
        except ImportError:
            logger.warning(
                "ffmpeg-normalize not found. Falling back to single-pass FFmpeg loudnorm."
            )
            self._fallback_normalize(input_path, output_path, target_lufs, true_peak)
            return output_path

    def _fallback_normalize(
        self, input_path: Path, output_path: Path, target_lufs: float, true_peak: float
    ) -> None:
        """Single-pass FFmpeg fallback for loudnorm."""
        self.executor.run([
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=7.0",
            "-c:a", "aac",
            "-b:a", "192k",
            "-y", str(output_path),
        ])
    
    def check_loudness(self, file_path: Path) -> dict:
        """Measure current loudness of a file.

        Returns:
            Dictionary containing integrated_lufs, true_peak, lra.
        """
        import json
        import re
        
        result = self.executor.run([
            "-i", str(file_path),
            "-af", "loudnorm=print_format=json",
            "-f", "null",
            "-",
        ])
        
        output = result.stderr
        match = re.search(r"(\{.*\})", output, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return {
                    "integrated_lufs": float(data.get("input_i", -99.0)),
                    "true_peak": float(data.get("input_tp", -99.0)),
                    "lra": float(data.get("input_lra", 0.0)),
                }
            except (json.JSONDecodeError, ValueError):
                pass
                
        logger.warning("Could not parse loudnorm output.")
        return {"integrated_lufs": -99.0, "true_peak": -99.0, "lra": 0.0}
