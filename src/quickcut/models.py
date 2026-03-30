"""Pydantic v2 data models for QuickCut project manifest and media metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class MediaInfo(BaseModel):
    """Probed media metadata from ffprobe."""

    file_path: Path
    file_hash: str = ""  # SHA256 of first 1MB for cache keying
    duration_seconds: float = 0.0
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    file_size_bytes: int = 0
    media_type: Literal["video", "audio", "image"] = "video"


class TranscriptWord(BaseModel):
    """A single word with timing from transcription."""

    word: str
    start: float
    end: float
    confidence: float = 0.0


class TranscriptSegment(BaseModel):
    """A segment of transcribed text (typically a sentence or phrase)."""

    text: str
    start: float
    end: float
    words: list[TranscriptWord] = Field(default_factory=list)


class Transcript(BaseModel):
    """Full transcript with word-level timestamps."""

    segments: list[TranscriptSegment] = Field(default_factory=list)
    source_id: str = ""
    model_name: str = "medium"
    language: str = "en"
    duration: float = 0.0

    @property
    def all_words(self) -> list[TranscriptWord]:
        """Flatten all words across segments."""
        return [w for seg in self.segments for w in seg.words]

    @property
    def full_text(self) -> str:
        """Return the full transcript as a single string."""
        return " ".join(seg.text.strip() for seg in self.segments)


class ClipRef(BaseModel):
    """Reference to a source clip with trim and transition settings."""

    source_id: str
    trim_start: float | None = None
    trim_end: float | None = None
    transition: Literal["cut", "fade", "xfade"] = "cut"
    transition_duration: float = 0.5


class WebcamOverlay(BaseModel):
    """Webcam picture-in-picture overlay configuration."""

    source_id: str
    position: Literal[
        "bottom-right", "bottom-left", "top-right", "top-left", "side-by-side"
    ] = "bottom-right"
    scale: float = 0.25
    border_width: int = 2
    border_color: str = "white"
    corner_radius: int = 0


class AudioMix(BaseModel):
    """Audio mixing settings."""

    source_gain_db: float = 0.0
    narration_gain_db: float = 0.0
    music_gain_db: float = -12.0
    ducking_strength: float = 0.7
    silence_threshold_db: float = -40.0
    normalize: bool = True
    target_lufs: float = -23.0


class CaptionStyle(BaseModel):
    """Caption rendering configuration."""

    style: Literal["clean", "social"] = "clean"
    font: str = "Arial"
    font_size: int = 24
    outline_width: int = 2
    position: Literal["bottom", "top", "center"] = "bottom"
    max_words_per_line: int = 8
    margin_bottom: int = 50


class ExportPreset(BaseModel):
    """Export configuration for a target format."""

    name: str
    aspect_ratio: Literal["16:9", "9:16", "1:1"]
    width: int
    height: int
    fit_mode: Literal["letterbox", "crop", "stretch"] = "letterbox"
    quality: Literal["draft", "preview", "final"] = "final"
    video_bitrate: str | None = None
    audio_bitrate: str = "192k"


# Default presets for common social platforms
DEFAULT_EXPORT_PRESETS: list[ExportPreset] = [
    ExportPreset(
        name="YouTube",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        video_bitrate="8M",
    ),
    ExportPreset(
        name="Shorts",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        video_bitrate="6M",
    ),
    ExportPreset(
        name="Square",
        aspect_ratio="1:1",
        width=1080,
        height=1080,
        video_bitrate="6M",
    ),
]


def _path_representer(dumper: yaml.Dumper, data: Path) -> yaml.Node:
    """YAML representer for pathlib.Path objects."""
    return dumper.represent_str(str(data))


def _datetime_representer(dumper: yaml.Dumper, data: datetime) -> yaml.Node:
    """YAML representer for datetime objects."""
    return dumper.represent_str(data.isoformat())


yaml.add_representer(Path, _path_representer)
yaml.add_representer(datetime, _datetime_representer)


class ProjectManifest(BaseModel):
    """Complete QuickCut project manifest — the single source of truth."""

    version: str = "1.0"
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources: dict[str, MediaInfo] = Field(default_factory=dict)
    clip_order: list[ClipRef] = Field(default_factory=list)
    narration: str | None = None  # source_id
    music: str | None = None  # source_id
    webcam: WebcamOverlay | None = None
    audio_mix: AudioMix = Field(default_factory=AudioMix)
    caption_style: CaptionStyle = Field(default_factory=CaptionStyle)
    export_presets: list[ExportPreset] = Field(
        default_factory=lambda: list(DEFAULT_EXPORT_PRESETS)
    )
    transcript_cuts: list[dict] = Field(default_factory=list)
    build_dir: str = "build"

    def save_yaml(self, path: Path) -> None:
        """Save manifest to a YAML file."""
        data = json.loads(self.model_dump_json())
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    @classmethod
    def load_yaml(cls, path: Path) -> ProjectManifest:
        """Load manifest from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
