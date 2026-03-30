"""Silence detection using FFmpeg's silencedetect filter."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from quickcut.ffmpeg_executor import FFmpegExecutor

logger = logging.getLogger(__name__)


def detect_silences(
    file_path: Path,
    threshold_db: float = -40.0,
    min_duration: float = 0.5,
    executor: FFmpegExecutor | None = None,
) -> list[dict]:
    """Detect silent sections in an audio/video file using FFmpeg silencedetect.

    Args:
        file_path: Path to the media file.
        threshold_db: Volume threshold in dB (below = silence). Default -40.
        min_duration: Minimum silence duration in seconds. Default 0.5.
        executor: Optional FFmpegExecutor instance.

    Returns:
        List of {"start": float, "end": float, "duration": float} dicts.
    """
    if not executor:
        executor = FFmpegExecutor()

    logger.info(
        "Detecting silences in %s (threshold=%sdB, min=%.1fs)...",
        file_path.name, threshold_db, min_duration,
    )

    # Run silencedetect — it outputs to stderr
    # We run with -f null to discard output, we only want the filter logs
    try:
        result = executor.run([
            "-i", str(file_path),
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
            "-f", "null",
            "-",
        ])
        output = result.stderr
    except Exception:
        # silencedetect returns non-zero sometimes; try to parse stderr anyway
        output = ""

    # Parse silence_start / silence_end / silence_duration from stderr
    silences: list[dict] = []
    start_pattern = re.compile(r"silence_start:\s*([\d.]+)")
    end_pattern = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")

    current_start: float | None = None
    for line in output.split("\n"):
        start_match = start_pattern.search(line)
        if start_match:
            current_start = float(start_match.group(1))

        end_match = end_pattern.search(line)
        if end_match and current_start is not None:
            end_time = float(end_match.group(1))
            duration = float(end_match.group(2))
            silences.append({
                "start": round(current_start, 3),
                "end": round(end_time, 3),
                "duration": round(duration, 3),
            })
            current_start = None

    logger.info("Found %d silent sections", len(silences))
    return silences


def suggest_jump_cuts(
    silences: list[dict], keep_padding: float = 0.15
) -> list[dict]:
    """Convert detected silences into jump cut suggestions.

    Trims each silence range inward by keep_padding to preserve
    natural speech rhythm.

    Args:
        silences: Silence list from detect_silences.
        keep_padding: Seconds to preserve on each end of silence.

    Returns:
        List of {"start": float, "end": float} cut suggestions.
    """
    cuts: list[dict] = []
    for s in silences:
        cut_start = s["start"] + keep_padding
        cut_end = s["end"] - keep_padding
        if cut_end > cut_start:
            cuts.append({
                "start": round(cut_start, 3),
                "end": round(cut_end, 3),
            })

    logger.info("Suggested %d jump cuts from %d silences", len(cuts), len(silences))
    return cuts
