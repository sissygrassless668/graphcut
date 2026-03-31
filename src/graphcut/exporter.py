"""Export orchestration for social formats and quality combinations."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

from graphcut.ffmpeg_executor import FFmpegExecutor
from graphcut.filtergraph import FilterGraph
from graphcut.models import ExportPreset, ProjectManifest
from graphcut.renderer import Renderer

logger = logging.getLogger(__name__)


def _safe_filename_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-") or fallback
    return cleaned[:80]


class Exporter:
    """Manages format aspect ratio conversions and FFmpeg quality tuning."""

    def __init__(self, executor: FFmpegExecutor | None = None, renderer: Renderer | None = None) -> None:
        self.executor = executor or FFmpegExecutor()
        self.renderer = renderer or Renderer(executor=self.executor)

    @staticmethod
    def build_output_filename(manifest: ProjectManifest, preset: ExportPreset) -> str:
        project_name = _safe_filename_part(manifest.name, "project")
        preset_name = _safe_filename_part(preset.name, "export")
        return f"{project_name}_{preset_name}.mp4"

    def export(
        self,
        manifest: ProjectManifest,
        preset: ExportPreset,
        output_dir: Path,
        progress_callback: Callable[[float, str, str], None] | None = None,
        project_dir: Path | None = None,
        preferred_video_encoder: str | None = None,
    ) -> Path:
        """Export the project to a specific format preset."""
        output_path = output_dir / self.build_output_filename(manifest, preset)
        logger.info("Exporting %s to %s", preset.name, output_path.name)
        
        # We hook into Renderer by passing our own Aspect Ratio modifications onto the FilterGraph
        # We'll monkeypatch/hook the renderer's FilterGraph just before compile, or better, 
        # we can just use the Renderer but append our scale/crop/pad logic to the very end of its internal graph.
        
        # To keep it clean, let's subclass or intercept the Renderer's final_v node
        # Wait, the easiest way is to let Renderer build the base graph, then we append our nodes 
        # but Renderer expects to `.compile()` and run internally.
        # Actually, let's just use the `render()` function and let it do the complex stuff, 
        # but we need to tell it to scale/crop.
        
        # We'll adapt Renderer to accept a final filter callback, or we can just run Renderer
        # with high quality intermediate, and then re-encode. But that's slow.
        
        # Let's write the renderer graph logic here, reusing renderer's build phases:
        # Actually, the Requirements want the Exporter to orchestrate Renderer with preset configs.
        # Let's pass the preset parameters down to Renderer via new arguments, or we handle the string.
        # It's cleaner to have Exporter build the aspect ratio string and inject it into Renderer.
        
        if project_dir is None and output_dir.name == manifest.build_dir:
            project_dir = output_dir.parent

        return self._render_with_preset(
            manifest,
            preset,
            output_path,
            progress_callback,
            project_dir=project_dir,
            preferred_video_encoder=preferred_video_encoder,
        )

    def _render_with_preset(
        self,
        manifest: ProjectManifest,
        preset: ExportPreset,
        output_path: Path,
        progress_callback: Callable[[float, str, str], None] | None = None,
        project_dir: Path | None = None,
        preferred_video_encoder: str | None = None,
    ) -> Path:
        """Internal render invocation adapting the Preset bounds onto the renderer's logic."""

        # We will dynamically adjust the Renderer's `quality` checks.
        # To do this correctly inside `Renderer.render()`, we can just call renderer.render() 
        # if we modify Publisher patterns. But we need custom aspect ratios.
        
        # Let's define the filter logic for the aspect ratio:
        def ar_filter(fg: FilterGraph, final_v: str) -> str:
            # Aspect ratio conversion
            tw, th = preset.width, preset.height
            
            if preset.fit_mode == "letterbox":
                # Scale to fit inside target WxH maintaining aspect ratio, then pad
                v1 = fg.scale(final_v, f"'{tw}'", f"'{th}':force_original_aspect_ratio=decrease")
                v2 = fg.pad(v1, tw, th)
                return v2
            elif preset.fit_mode == "crop":
                # Scale to cover target WxH maintaining aspect ratio, then crop center
                v1 = fg.scale(final_v, f"'{tw}'", f"'{th}':force_original_aspect_ratio=increase")
                v2 = fg.crop_center(v1, tw, th)
                return v2
            else: # stretch
                return fg.scale(final_v, tw, th)

        # We will directly run the renderer but we inject our encoder arguments and aspect ratio logic.
        # We need to add an `export_filter` param to Renderer.render.
        return self.renderer.render(
            manifest,
            output_path,
            project_dir=project_dir,
            quality=preset.quality,
            export_filter_hook=ar_filter,
            encoder_args_factory=lambda encoder: self.build_encoder_args(encoder, preset),
            progress_callback=progress_callback,
            preferred_video_encoder=preferred_video_encoder,
        )
        
    def export_all(
        self,
        manifest: ProjectManifest,
        output_dir: Path,
        presets: list[ExportPreset] | None = None,
        progress_callback: Callable[[float, str, str], None] | None = None,
        project_dir: Path | None = None,
        preferred_video_encoder: str | None = None,
    ) -> list[Path]:
        """Export to all provided presets sequentially."""
        if project_dir is None and output_dir.name == manifest.build_dir:
            project_dir = output_dir.parent

        presets = presets or manifest.export_presets
        results = []
        for p in presets:
            res = self.export(
                manifest,
                p,
                output_dir,
                progress_callback,
                project_dir=project_dir,
                preferred_video_encoder=preferred_video_encoder,
            )
            results.append(res)
            
        return results

    def build_encoder_args(self, encoder: str, preset: ExportPreset) -> list[str]:
        """Build encoder/audio args for a preset and a specific video encoder."""
        encoder_args = self._get_encoder_params(encoder, preset.quality)

        if preset.video_bitrate and "videotoolbox" not in encoder:
            encoder_args.extend(["-b:v", preset.video_bitrate])

        encoder_args.extend(["-c:a", "aac", "-b:a", preset.audio_bitrate])
        return encoder_args

    def _get_encoder_params(self, encoder: str, quality: str) -> list[str]:
        """Return FFmpeg parameters based on quality tier and hardware encoder."""
        if encoder == "libx264" or encoder == "libx265":
            if quality == "draft":
                return ["-c:v", encoder, "-crf", "28", "-preset", "ultrafast"]
            elif quality == "preview":
                return ["-c:v", encoder, "-crf", "23", "-preset", "fast"]
            else:
                return ["-c:v", encoder, "-crf", "18", "-preset", "slow"]
                
        elif "videotoolbox" in encoder:
            # Apple Silicon hardware encoding
            # Uses -q:v instead of CRF. Lower is better, typical 45-65.
            if quality == "draft":
                return ["-c:v", encoder, "-q:v", "65", "-allow_sw", "1"]
            elif quality == "preview":
                return ["-c:v", encoder, "-q:v", "55", "-allow_sw", "1"]
            else:
                return ["-c:v", encoder, "-q:v", "45", "-allow_sw", "1"]
                
        elif "nvenc" in encoder:
            # Nvidia hardware encoding
            if quality == "draft":
                return ["-c:v", encoder, "-cq", "28", "-preset", "p1"]
            elif quality == "preview":
                return ["-c:v", encoder, "-cq", "25", "-preset", "p4"]
            else:
                return ["-c:v", encoder, "-cq", "19", "-preset", "p7"]
                
        # Fallback basic default
        return ["-c:v", encoder]
