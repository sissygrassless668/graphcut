"""Agent-first planning helpers for AI-generated creator workflows."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import re

from graphcut.factory import ContentPlan, build_plan, execute_plan
from graphcut.platforms import PlatformProfile, get_platform_profile


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "we",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class StoryboardShot:
    """A provider-agnostic shot plan item."""

    shot_id: str
    beat: str
    duration_seconds: float
    voiceover: str
    visual_prompt: str
    on_screen_text: str
    camera_move: str
    asset_type: str
    aspect_ratio: str

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return asdict(self)


@dataclass(frozen=True)
class StoryboardPlan:
    """A full shot plan for a creator workflow."""

    platform: str
    provider: str
    hook_style: str
    total_duration_seconds: float
    shots: tuple[StoryboardShot, ...]

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return {
            "platform": self.platform,
            "provider": self.provider,
            "hook_style": self.hook_style,
            "total_duration_seconds": self.total_duration_seconds,
            "shots": [shot.to_dict() for shot in self.shots],
        }


@dataclass(frozen=True)
class PublishAsset:
    """Metadata for one publishable asset."""

    filename: str
    title_options: tuple[str, ...]
    description: str
    hashtags: tuple[str, ...]
    hook_text: str
    clip_start: float | None = None
    clip_end: float | None = None

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return {
            "filename": self.filename,
            "title_options": list(self.title_options),
            "description": self.description,
            "hashtags": list(self.hashtags),
            "hook_text": self.hook_text,
            "clip_start": self.clip_start,
            "clip_end": self.clip_end,
        }


@dataclass(frozen=True)
class PublishBundle:
    """A publish-ready bundle for one or more outputs."""

    platform: str
    summary: str
    keywords: tuple[str, ...]
    assets: tuple[PublishAsset, ...]

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return {
            "platform": self.platform,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "assets": [asset.to_dict() for asset in self.assets],
        }


def _slug_to_words(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip().title()


def resolve_script_text(
    *,
    script_input: str | None = None,
    script_file: Path | None = None,
    text: str | None = None,
) -> str:
    """Resolve script text from raw text, a file, or a positional input."""
    if text:
        return text.strip()
    if script_file:
        return script_file.read_text(encoding="utf-8").strip()
    if script_input:
        candidate = Path(script_input)
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
        return script_input.strip()
    raise ValueError("Provide script text via an argument, --script-file, or --text.")


def _split_script(script_text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", script_text) if part.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    return [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+", script_text)
        if segment.strip()
    ]


def _extract_keywords(script_text: str, limit: int = 6) -> tuple[str, ...]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]+", script_text.lower())
    filtered = [word for word in words if word not in STOPWORDS and len(word) > 3]
    if not filtered:
        return ("creator", "content")
    counts = Counter(filtered)
    return tuple(word for word, _ in counts.most_common(limit))


def _build_visual_prompt(beat: str, platform: PlatformProfile, provider: str) -> str:
    framing = "vertical short-form framing" if platform.aspect_ratio == "9:16" else "clean creator framing"
    return (
        f"{beat}. {framing}, strong focal subject, social-media pacing, "
        f"provider target: {provider}, safe text margins, high contrast."
    )


def build_storyboard(
    script_text: str,
    *,
    platform_name: str = "tiktok",
    provider: str = "generic",
    hook_style: str = "curiosity",
    shots: int | None = None,
    shot_seconds: float | None = None,
) -> StoryboardPlan:
    """Create a provider-agnostic storyboard from a script."""
    platform = get_platform_profile(platform_name)
    beats = _split_script(script_text)
    if not beats:
        raise ValueError("Script text is empty.")

    if shots is not None and shots > 0:
        beats = beats[:shots]

    shot_count = len(beats)
    default_seconds = round(min(platform.max_duration_seconds / max(shot_count, 1), 8.0), 2)
    duration = round(shot_seconds or max(2.5, default_seconds), 2)

    planned_shots: list[StoryboardShot] = []
    for index, beat in enumerate(beats, start=1):
        hook_text = ""
        camera_move = "slow push-in"
        asset_type = "generated-video"
        if index == 1:
            if hook_style == "curiosity":
                hook_text = "Wait for it..."
            elif hook_style == "authority":
                hook_text = "Most people miss this"
            else:
                hook_text = "Here is the key move"
            camera_move = "fast punch-in"
        elif index % 3 == 0:
            camera_move = "subtle lateral drift"
            asset_type = "b-roll"

        planned_shots.append(
            StoryboardShot(
                shot_id=f"shot_{index:02d}",
                beat=beat,
                duration_seconds=duration,
                voiceover=beat,
                visual_prompt=_build_visual_prompt(beat, platform, provider),
                on_screen_text=hook_text or beat[:70],
                camera_move=camera_move,
                asset_type=asset_type,
                aspect_ratio=platform.aspect_ratio,
            )
        )

    return StoryboardPlan(
        platform=platform.key,
        provider=provider,
        hook_style=hook_style,
        total_duration_seconds=round(duration * len(planned_shots), 2),
        shots=tuple(planned_shots),
    )


def build_publish_bundle(
    *,
    platform_name: str,
    source_name: str,
    script_text: str | None = None,
    plan: ContentPlan | None = None,
) -> PublishBundle:
    """Create publish-ready metadata for one or more outputs."""
    platform = get_platform_profile(platform_name)
    source_label = _slug_to_words(Path(source_name).stem)
    base_text = (script_text or source_label).strip()
    keywords = _extract_keywords(base_text)
    primary = keywords[0].title()
    secondary = keywords[1].title() if len(keywords) > 1 else "Creators"
    description_seed = " ".join(_split_script(base_text)[:2])[:280]
    summary = description_seed or f"{source_label} prepared for {platform.label}."

    title_options = (
        f"{primary}: What Most People Miss",
        f"How {primary} Changes {secondary}",
        f"{primary} in Under 60 Seconds",
    )
    hashtags = tuple(f"#{re.sub(r'[^A-Za-z0-9]', '', word.title())}" for word in keywords[:5])

    assets: list[PublishAsset] = []
    if plan and plan.outputs:
        for output in plan.outputs:
            assets.append(
                PublishAsset(
                    filename=output.filename,
                    title_options=title_options,
                    description=summary,
                    hashtags=hashtags,
                    hook_text=(output.reason or "Strong opening hook"),
                    clip_start=output.start,
                    clip_end=output.end,
                )
            )
    else:
        filename = f"{Path(source_name).stem}_{platform.key}.mp4"
        assets.append(
            PublishAsset(
                filename=filename,
                title_options=title_options,
                description=summary,
                hashtags=hashtags,
                hook_text="Strong opening hook",
            )
        )

    return PublishBundle(
        platform=platform.key,
        summary=summary,
        keywords=keywords,
        assets=tuple(assets),
    )


def bundle_to_markdown(bundle: PublishBundle) -> str:
    """Render a publish bundle as Markdown for humans."""
    lines = [
        f"# {bundle.platform.title()} Package",
        "",
        bundle.summary,
        "",
        f"Keywords: {', '.join(bundle.keywords)}",
        "",
    ]
    for asset in bundle.assets:
        lines.extend(
            [
                f"## {asset.filename}",
                "",
                "Title Options:",
                *[f"- {title}" for title in asset.title_options],
                "",
                f"Description: {asset.description}",
                "",
                f"Hashtags: {' '.join(asset.hashtags)}",
                "",
                f"Hook: {asset.hook_text}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def viralize(
    source_path: Path,
    *,
    platform_name: str | None = None,
    recipe_name: str | None = None,
    captions: str | None = None,
    quality: str = "final",
    output_dir: Path | None = None,
    remove_silence: bool | None = None,
    silence_min_duration: float | None = None,
    clips: int | None = None,
    min_clip_seconds: float | None = None,
    max_clip_seconds: float | None = None,
    scene_threshold: float | None = None,
    script_text: str | None = None,
    render: bool = False,
) -> tuple[ContentPlan, PublishBundle, list[Path]]:
    """Build a repurposing plan plus publish bundle, optionally rendering outputs."""
    plan = build_plan(
        "repurpose",
        source_path,
        platform_name=platform_name,
        recipe_name=recipe_name,
        captions=captions,
        quality=quality,
        output_dir=output_dir,
        remove_silence=remove_silence,
        silence_min_duration=silence_min_duration,
        clips=clips,
        min_clip_seconds=min_clip_seconds,
        max_clip_seconds=max_clip_seconds,
        scene_threshold=scene_threshold,
    )
    bundle = build_publish_bundle(
        platform_name=plan.platform.key,
        source_name=source_path.name,
        script_text=script_text,
        plan=plan,
    )
    rendered_paths = execute_plan(plan) if render else []
    return plan, bundle, rendered_paths
