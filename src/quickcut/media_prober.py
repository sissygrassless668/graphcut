"""Media probing module using ffprobe to extract metadata."""

from __future__ import annotations

import logging
import hashlib
from pathlib import Path
from typing import Any

from quickcut.ffmpeg_executor import FFmpegExecutor, FFmpegError
from quickcut.models import MediaInfo

logger = logging.getLogger(__name__)


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of the first 1MB of a file for cache keying."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        chunk = f.read(1024 * 1024)  # Read first 1MB
        hasher.update(chunk)
    return hasher.hexdigest()


def probe_file(
    file_path: Path, executor: FFmpegExecutor | None = None
) -> MediaInfo:
    """Probe a media file and return its metadata.

    Args:
        file_path: Path to the media file.
        executor: Optional initialized FFmpegExecutor to use.

    Returns:
        MediaInfo object with extracted metadata.
    """
    if not executor:
        executor = FFmpegExecutor()

    try:
        data = executor.run_ffprobe(file_path)
    except FFmpegError as e:
        logger.error("Failed to probe file %s: %s", file_path, e)
        raise e

    format_info = data.get("format", {})
    duration = float(format_info.get("duration", 0.0))
    file_size = int(format_info.get("size", 0))

    width = None
    height = None
    fps = None
    video_codec = None
    audio_codec = None
    audio_channels = None
    audio_sample_rate = None

    has_video = False
    has_audio = False

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        
        if codec_type == "video":
            has_video = True
            width = width or int(stream.get("width", 0))
            height = height or int(stream.get("height", 0))
            video_codec = video_codec or stream.get("codec_name")
            
            # Parse fps (e.g., "30000/1001" or "30/1")
            r_frame_rate = stream.get("r_frame_rate", "0/0")
            num, den = r_frame_rate.split("/")
            if den != "0":
                fps = round(float(num) / float(den), 3)

        elif codec_type == "audio":
            has_audio = True
            audio_codec = audio_codec or stream.get("codec_name")
            audio_channels = audio_channels or int(stream.get("channels", 0))
            audio_sample_rate = audio_sample_rate or int(stream.get("sample_rate", 0))

    # Determine media type
    if has_video and has_audio:
        media_type = "video"
    elif has_video and not has_audio:
        if duration < 1.0:
            # Short durations with only video are typically images
            # But checking format name could also be useful. Let's stick to < 1s heuristic
            media_type = "image"
        else:
            media_type = "video"
    elif has_audio and not has_video:
        media_type = "audio"
    else:
        media_type = "video"  # Default fallback

    file_hash = compute_file_hash(file_path)

    return MediaInfo(
        file_path=file_path,
        file_hash=file_hash,
        duration_seconds=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=video_codec,
        audio_codec=audio_codec,
        audio_channels=audio_channels,
        audio_sample_rate=audio_sample_rate,
        file_size_bytes=file_size,
        media_type=media_type,
    )


def probe_files(
    paths: list[Path], executor: FFmpegExecutor | None = None
) -> dict[str, MediaInfo]:
    """Batch probe multiple files.

    Args:
        paths: List of paths to media files.
        executor: Optional initialized FFmpegExecutor to use.

    Returns:
        Dict mapping filename stem to MediaInfo.
    """
    if not executor:
        executor = FFmpegExecutor()

    result: dict[str, MediaInfo] = {}
    for path in paths:
        try:
            info = probe_file(path, executor=executor)
            result[path.stem] = info
        except Exception as e:
            logger.error("Skipping file %s due to error: %s", path, e)

    return result
