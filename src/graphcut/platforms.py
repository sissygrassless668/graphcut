"""Built-in platform presets and workflow recipes for leverage-first commands."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from graphcut.models import ExportPreset


@dataclass(frozen=True)
class PlatformProfile:
    """Opinionated export settings for a publishing surface."""

    key: str
    label: str
    aspect_ratio: str
    width: int
    height: int
    fit_mode: str
    video_bitrate: str
    audio_bitrate: str
    max_duration_seconds: float
    default_caption_style: str

    def to_export_preset(self, quality: str = "final") -> ExportPreset:
        """Convert a profile to a renderer export preset."""
        return ExportPreset(
            name=self.label,
            aspect_ratio=self.aspect_ratio,  # type: ignore[arg-type]
            width=self.width,
            height=self.height,
            fit_mode=self.fit_mode,  # type: ignore[arg-type]
            quality=quality,  # type: ignore[arg-type]
            video_bitrate=self.video_bitrate,
            audio_bitrate=self.audio_bitrate,
        )

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return asdict(self)


@dataclass(frozen=True)
class WorkflowRecipe:
    """Defaults for a creator workflow."""

    key: str
    label: str
    description: str
    default_platform: str
    default_captions: str
    remove_silence: bool
    clips: int
    min_clip_seconds: float
    max_clip_seconds: float
    scene_threshold: float
    silence_min_duration: float

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return asdict(self)


PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    "tiktok": PlatformProfile(
        key="tiktok",
        label="TikTok",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fit_mode="crop",
        video_bitrate="6M",
        audio_bitrate="192k",
        max_duration_seconds=60.0,
        default_caption_style="social",
    ),
    "reels": PlatformProfile(
        key="reels",
        label="Reels",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fit_mode="crop",
        video_bitrate="6M",
        audio_bitrate="192k",
        max_duration_seconds=90.0,
        default_caption_style="social",
    ),
    "shorts": PlatformProfile(
        key="shorts",
        label="Shorts",
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fit_mode="crop",
        video_bitrate="6M",
        audio_bitrate="192k",
        max_duration_seconds=180.0,
        default_caption_style="social",
    ),
    "youtube": PlatformProfile(
        key="youtube",
        label="YouTube",
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        fit_mode="letterbox",
        video_bitrate="8M",
        audio_bitrate="192k",
        max_duration_seconds=43200.0,
        default_caption_style="clean",
    ),
    "square": PlatformProfile(
        key="square",
        label="Square",
        aspect_ratio="1:1",
        width=1080,
        height=1080,
        fit_mode="crop",
        video_bitrate="6M",
        audio_bitrate="192k",
        max_duration_seconds=600.0,
        default_caption_style="social",
    ),
}


WORKFLOW_RECIPES: dict[str, WorkflowRecipe] = {
    "podcast": WorkflowRecipe(
        key="podcast",
        label="Podcast Clips",
        description="Turn a long conversation into short captioned vertical clips.",
        default_platform="shorts",
        default_captions="social",
        remove_silence=True,
        clips=8,
        min_clip_seconds=20.0,
        max_clip_seconds=45.0,
        scene_threshold=27.0,
        silence_min_duration=0.8,
    ),
    "talking-head": WorkflowRecipe(
        key="talking-head",
        label="Talking Head",
        description="Direct-to-camera clips with conservative scene splitting.",
        default_platform="tiktok",
        default_captions="social",
        remove_silence=True,
        clips=6,
        min_clip_seconds=15.0,
        max_clip_seconds=45.0,
        scene_threshold=30.0,
        silence_min_duration=0.9,
    ),
    "gaming": WorkflowRecipe(
        key="gaming",
        label="Gaming Highlights",
        description="Short energetic cuts with lighter silence removal.",
        default_platform="shorts",
        default_captions="clean",
        remove_silence=False,
        clips=10,
        min_clip_seconds=15.0,
        max_clip_seconds=35.0,
        scene_threshold=22.0,
        silence_min_duration=1.2,
    ),
    "reaction": WorkflowRecipe(
        key="reaction",
        label="Reaction Clips",
        description="Fast vertical cuts for reaction or duet-style content.",
        default_platform="reels",
        default_captions="social",
        remove_silence=True,
        clips=8,
        min_clip_seconds=12.0,
        max_clip_seconds=30.0,
        scene_threshold=25.0,
        silence_min_duration=0.7,
    ),
}


PLATFORM_ALIASES = {
    "ig": "reels",
    "instagram": "reels",
    "yt": "youtube",
}


def _normalize_platform_name(name: str) -> str:
    key = name.strip().lower()
    return PLATFORM_ALIASES.get(key, key)


def list_platform_profiles() -> list[PlatformProfile]:
    """Return built-in platforms in display order."""
    return list(PLATFORM_PROFILES.values())


def list_workflow_recipes() -> list[WorkflowRecipe]:
    """Return built-in workflow recipes in display order."""
    return list(WORKFLOW_RECIPES.values())


def get_platform_profile(name: str) -> PlatformProfile:
    """Look up a platform profile by name or alias."""
    key = _normalize_platform_name(name)
    if key not in PLATFORM_PROFILES:
        raise KeyError(name)
    return PLATFORM_PROFILES[key]


def get_workflow_recipe(name: str) -> WorkflowRecipe:
    """Look up a workflow recipe by key."""
    key = name.strip().lower()
    if key not in WORKFLOW_RECIPES:
        raise KeyError(name)
    return WORKFLOW_RECIPES[key]
