"""High-level content factory planning and execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import re

from graphcut.clip_selector import ClipSuggestion, suggest_clips
from graphcut.exporter import Exporter
from graphcut.media_prober import probe_file
from graphcut.models import AudioMix, CaptionStyle, ClipRef, MediaInfo, ProjectManifest
from graphcut.platforms import (
    PlatformProfile,
    WorkflowRecipe,
    get_platform_profile,
    get_workflow_recipe,
)
from graphcut.project_manager import ProjectManager


@dataclass(frozen=True)
class PlannedOutput:
    """A single planned export artifact."""

    filename: str
    start: float
    end: float
    duration: float
    platform: str
    captions: str
    score: float | None = None
    reason: str | None = None
    transcript_cuts: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return {
            "filename": self.filename,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "platform": self.platform,
            "captions": self.captions,
            "score": self.score,
            "reason": self.reason,
            "transcript_cuts": [dict(item) for item in self.transcript_cuts],
        }


@dataclass(frozen=True)
class ContentPlan:
    """A creator-facing content production plan."""

    mode: str
    source_file: Path
    output_dir: Path
    platform: PlatformProfile
    captions: str
    quality: str
    recipe: WorkflowRecipe | None
    outputs: tuple[PlannedOutput, ...]
    warnings: tuple[str, ...] = ()
    scene_count: int = 0
    silence_count: int = 0

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        return {
            "mode": self.mode,
            "source_file": str(self.source_file),
            "output_dir": str(self.output_dir),
            "platform": self.platform.to_dict(),
            "captions": self.captions,
            "quality": self.quality,
            "recipe": self.recipe.to_dict() if self.recipe else None,
            "outputs": [item.to_dict() for item in self.outputs],
            "warnings": list(self.warnings),
            "scene_count": self.scene_count,
            "silence_count": self.silence_count,
        }


def _slugify(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return clean or "graphcut"


def _default_output_dir(source_path: Path) -> Path:
    return source_path.parent / "graphcut_output"


def _resolve_recipe(recipe_name: str | None) -> WorkflowRecipe | None:
    if not recipe_name:
        return None
    return get_workflow_recipe(recipe_name)


def _resolve_platform(platform_name: str | None, recipe: WorkflowRecipe | None) -> PlatformProfile:
    if platform_name:
        return get_platform_profile(platform_name)
    if recipe:
        return get_platform_profile(recipe.default_platform)
    return get_platform_profile("tiktok")


def _resolve_captions(
    captions: str | None,
    platform: PlatformProfile,
    recipe: WorkflowRecipe | None,
) -> str:
    if captions:
        return captions
    if recipe:
        return recipe.default_captions
    return platform.default_caption_style


def _resolve_remove_silence(remove_silence: bool | None, recipe: WorkflowRecipe | None) -> bool:
    if remove_silence is not None:
        return remove_silence
    if recipe:
        return recipe.remove_silence
    return False


def _resolve_clip_target(value: int | None, recipe: WorkflowRecipe | None, default: int) -> int:
    if value is not None:
        return max(1, value)
    if recipe:
        return max(1, recipe.clips)
    return default


def _resolve_seconds(
    value: float | None,
    recipe_value: float | None,
    fallback: float,
) -> float:
    if value is not None:
        return max(0.1, value)
    if recipe_value is not None:
        return max(0.1, recipe_value)
    return fallback


def _clip_filename(source_path: Path, platform: PlatformProfile, index: int | None = None) -> str:
    stem = _slugify(source_path.stem)
    if index is None:
        return f"{stem}_{platform.key}.mp4"
    return f"{stem}_{platform.key}_clip{index:02d}.mp4"


def _intersect_cuts(cuts: list[dict], start: float, end: float, *, relative_to: float | None = None) -> tuple[dict, ...]:
    intersected: list[dict] = []
    for cut in cuts:
        cut_start = max(start, float(cut["start"]))
        cut_end = min(end, float(cut["end"]))
        if cut_end <= cut_start:
            continue
        if relative_to is None:
            intersected.append({"start": round(cut_start, 3), "end": round(cut_end, 3)})
        else:
            intersected.append(
                {
                    "start": round(cut_start - relative_to, 3),
                    "end": round(cut_end - relative_to, 3),
                }
            )
    return tuple(intersected)


def _duration_after_cuts(start: float, end: float, cuts: tuple[dict, ...]) -> float:
    removed = sum(float(cut["end"]) - float(cut["start"]) for cut in cuts)
    return round(max(0.0, (end - start) - removed), 3)


def _detect_scenes_for_file(file_info: MediaInfo, threshold: float) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    if file_info.media_type != "video":
        return [], warnings
    try:
        from graphcut.scene_detector import detect_scenes
    except ImportError:
        warnings.append("Scene detection dependency not installed; falling back to duration-only chunking.")
        return [], warnings

    try:
        return detect_scenes(file_info.file_path, threshold=threshold), warnings
    except Exception as exc:
        warnings.append(f"Scene detection failed: {exc}")
        return [], warnings


def _detect_silences_for_file(file_info: MediaInfo, min_duration: float) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    try:
        from graphcut.silence_detector import detect_silences, suggest_jump_cuts
    except ImportError:
        warnings.append("Silence detection unavailable.")
        return [], warnings

    try:
        silences = detect_silences(file_info.file_path, min_duration=min_duration)
        return suggest_jump_cuts(silences), warnings
    except Exception as exc:
        warnings.append(f"Silence detection failed: {exc}")
        return [], warnings


def plan_make(
    source_path: Path,
    *,
    platform_name: str | None = None,
    recipe_name: str | None = None,
    captions: str | None = None,
    quality: str = "final",
    output_dir: Path | None = None,
    remove_silence: bool | None = None,
    silence_min_duration: float | None = None,
    media_info: MediaInfo | None = None,
) -> ContentPlan:
    """Plan a single platform-ready output."""
    recipe = _resolve_recipe(recipe_name)
    platform = _resolve_platform(platform_name, recipe)
    caption_mode = _resolve_captions(captions, platform, recipe)
    silence_enabled = _resolve_remove_silence(remove_silence, recipe)
    silence_window = _resolve_seconds(silence_min_duration, recipe.silence_min_duration if recipe else None, 1.0)
    info = media_info or probe_file(source_path)
    out_dir = (output_dir or _default_output_dir(source_path)).resolve()

    end = min(info.duration_seconds, platform.max_duration_seconds)
    warnings: list[str] = []
    if info.duration_seconds > platform.max_duration_seconds:
        warnings.append(
            f"Trimmed source to {platform.max_duration_seconds:.0f}s to fit {platform.label} duration guidance."
        )

    silence_cuts: tuple[dict, ...] = ()
    silence_count = 0
    if silence_enabled:
        raw_cuts, cut_warnings = _detect_silences_for_file(info, silence_window)
        warnings.extend(cut_warnings)
        silence_cuts = _intersect_cuts(raw_cuts, 0.0, end)
        silence_count = len(silence_cuts)

    planned = PlannedOutput(
        filename=_clip_filename(source_path, platform),
        start=0.0,
        end=round(end, 3),
        duration=_duration_after_cuts(0.0, end, silence_cuts),
        platform=platform.key,
        captions=caption_mode,
        transcript_cuts=silence_cuts,
        reason="Full-source platform conversion.",
    )

    return ContentPlan(
        mode="make",
        source_file=source_path.resolve(),
        output_dir=out_dir,
        platform=platform,
        captions=caption_mode,
        quality=quality,
        recipe=recipe,
        outputs=(planned,),
        warnings=tuple(warnings),
        silence_count=silence_count,
    )


def plan_repurpose(
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
    media_info: MediaInfo | None = None,
) -> ContentPlan:
    """Plan multiple short-form clip outputs from a long-form source."""
    recipe = _resolve_recipe(recipe_name)
    platform = _resolve_platform(platform_name, recipe)
    caption_mode = _resolve_captions(captions, platform, recipe)
    silence_enabled = _resolve_remove_silence(remove_silence, recipe)
    clip_target = _resolve_clip_target(clips, recipe, 6)
    min_seconds = _resolve_seconds(min_clip_seconds, recipe.min_clip_seconds if recipe else None, 15.0)
    max_seconds = _resolve_seconds(max_clip_seconds, recipe.max_clip_seconds if recipe else None, 45.0)
    max_seconds = min(max_seconds, platform.max_duration_seconds)
    min_seconds = min(min_seconds, max_seconds)
    silence_window = _resolve_seconds(silence_min_duration, recipe.silence_min_duration if recipe else None, 1.0)
    scene_sensitivity = _resolve_seconds(scene_threshold, recipe.scene_threshold if recipe else None, 27.0)
    info = media_info or probe_file(source_path)
    out_dir = (output_dir or _default_output_dir(source_path)).resolve()

    warnings: list[str] = []
    scenes, scene_warnings = _detect_scenes_for_file(info, scene_sensitivity)
    warnings.extend(scene_warnings)

    silence_cuts: list[dict] = []
    if silence_enabled:
        silence_cuts, silence_warnings = _detect_silences_for_file(info, silence_window)
        warnings.extend(silence_warnings)

    suggestions = suggest_clips(
        duration=info.duration_seconds,
        scenes=scenes,
        silence_cuts=silence_cuts,
        max_clips=clip_target,
        min_clip_seconds=min_seconds,
        max_clip_seconds=max_seconds,
    )

    if not suggestions and info.duration_seconds > 0:
        fallback_end = min(info.duration_seconds, max_seconds)
        suggestions = [
            ClipSuggestion(
                start=0.0,
                end=round(fallback_end, 3),
                score=50.0,
                scene_count=1,
                silence_seconds=0.0,
                reason="Fallback chunk because no ranked scene windows were available.",
            )
        ]
        warnings.append("Fell back to a simple leading segment because no ranked clips were found.")

    outputs: list[PlannedOutput] = []
    for index, suggestion in enumerate(suggestions, start=1):
        relative_cuts = _intersect_cuts(
            silence_cuts,
            suggestion.start,
            suggestion.end,
            relative_to=suggestion.start,
        ) if silence_enabled else ()
        outputs.append(
            PlannedOutput(
                filename=_clip_filename(source_path, platform, index=index),
                start=suggestion.start,
                end=suggestion.end,
                duration=_duration_after_cuts(suggestion.start, suggestion.end, relative_cuts),
                platform=platform.key,
                captions=caption_mode,
                score=suggestion.score,
                reason=suggestion.reason,
                transcript_cuts=relative_cuts,
            )
        )

    return ContentPlan(
        mode="repurpose",
        source_file=source_path.resolve(),
        output_dir=out_dir,
        platform=platform,
        captions=caption_mode,
        quality=quality,
        recipe=recipe,
        outputs=tuple(outputs),
        warnings=tuple(warnings),
        scene_count=len(scenes),
        silence_count=len(silence_cuts),
    )


def build_plan(
    mode: str,
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
    media_info: MediaInfo | None = None,
) -> ContentPlan:
    """Build a content plan for the requested factory mode."""
    if mode == "make":
        return plan_make(
            source_path,
            platform_name=platform_name,
            recipe_name=recipe_name,
            captions=captions,
            quality=quality,
            output_dir=output_dir,
            remove_silence=remove_silence,
            silence_min_duration=silence_min_duration,
            media_info=media_info,
        )
    if mode == "repurpose":
        return plan_repurpose(
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
            media_info=media_info,
        )
    raise ValueError(f"Unsupported factory mode: {mode}")


def _workspace_project_dir(source_path: Path, output_dir: Path) -> Path:
    digest = hashlib.sha256(str(source_path.resolve()).encode("utf-8")).hexdigest()[:8]
    hidden_root = output_dir / ".graphcut"
    return hidden_root / f"{_slugify(source_path.stem)}-{digest}"


def _reset_manifest(manifest: ProjectManifest, platform: PlatformProfile, captions: str, quality: str) -> None:
    manifest.sources = {}
    manifest.clip_order = []
    manifest.narration = None
    manifest.music = None
    manifest.webcam = None
    manifest.audio_mix = AudioMix()
    manifest.caption_style = CaptionStyle(style="clean" if captions == "off" else captions)  # type: ignore[arg-type]
    manifest.burn_captions = captions != "off"
    manifest.export_presets = [platform.to_export_preset(quality=quality)]
    manifest.scenes = {}
    manifest.active_scene = None
    manifest.transcript_cuts = []


def _ensure_project(source_path: Path, plan: ContentPlan) -> tuple[Path, ProjectManifest]:
    project_dir = _workspace_project_dir(source_path, plan.output_dir)
    if project_dir.exists():
        manifest = ProjectManager.load_project(project_dir)
    else:
        project_dir.parent.mkdir(parents=True, exist_ok=True)
        ProjectManager.create_project(project_dir.name, project_dir.parent)
        manifest = ProjectManager.load_project(project_dir)

    _reset_manifest(manifest, plan.platform, plan.captions, plan.quality)
    ProjectManager.add_source(manifest, source_path, source_id="source")
    return project_dir, manifest


def _ensure_transcript(source_path: Path, project_dir: Path) -> None:
    try:
        from graphcut.transcriber import Transcriber
    except ImportError:
        return

    transcriber = Transcriber(model_name="medium")
    transcriber.transcribe(source_path, cache_dir=project_dir)


def execute_plan(plan: ContentPlan) -> list[Path]:
    """Render all outputs described by a plan."""
    plan.output_dir.mkdir(parents=True, exist_ok=True)
    project_dir, manifest = _ensure_project(plan.source_file, plan)
    if plan.captions != "off":
        _ensure_transcript(plan.source_file, project_dir)

    exporter = Exporter()
    rendered_paths: list[Path] = []
    for planned_output in plan.outputs:
        _reset_manifest(manifest, plan.platform, plan.captions, plan.quality)
        if "source" not in manifest.sources:
            ProjectManager.add_source(manifest, plan.source_file, source_id="source")
        manifest.clip_order = [
            ClipRef(
                source_id="source",
                trim_start=planned_output.start,
                trim_end=planned_output.end,
                transition="cut",
                transition_duration=0.0,
            )
        ]
        manifest.transcript_cuts = [dict(item) for item in planned_output.transcript_cuts]
        ProjectManager.save_project(manifest, project_dir)

        rendered = exporter.export(
            manifest,
            manifest.export_presets[0],
            plan.output_dir,
            project_dir=project_dir,
        )
        target = plan.output_dir / planned_output.filename
        if rendered != target:
            if target.exists():
                target.unlink()
            rendered.replace(target)
        rendered_paths.append(target)

    return rendered_paths
