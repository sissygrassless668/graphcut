"""Export orchestration for social formats and quality combinations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from quickcut.ffmpeg_executor import FFmpegExecutor
from quickcut.filtergraph import FilterGraph
from quickcut.models import ExportPreset, ProjectManifest
from quickcut.renderer import Renderer

logger = logging.getLogger(__name__)


class Exporter:
    """Manages format aspect ratio conversions and FFmpeg quality tuning."""

    def __init__(self, executor: FFmpegExecutor | None = None, renderer: Renderer | None = None) -> None:
        self.executor = executor or FFmpegExecutor()
        self.renderer = renderer or Renderer(executor=self.executor)

    def export(
        self,
        manifest: ProjectManifest,
        preset: ExportPreset,
        output_dir: Path,
        progress_callback: Callable[[float, str, str], None] | None = None
    ) -> Path:
        """Export the project to a specific format preset."""
        output_path = output_dir / f"{manifest.name}_{preset.name}.mp4"
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
        
        return self._render_with_preset(manifest, preset, output_path, progress_callback)

    def _render_with_preset(
        self,
        manifest: ProjectManifest,
        preset: ExportPreset,
        output_path: Path,
        progress_callback: Callable[[float, str, str], None] | None = None
    ) -> Path:
        """Internal render invocation adapting the Preset bounds onto the renderer's logic."""
        
        # 1. Determine base encoder and params based on quality
        encoder = self.executor.get_best_encoder()
        encoder_args = self._get_encoder_params(encoder, preset.quality)
        
        # 2. Add bitrate args depending on the preset
        if preset.video_bitrate:
            if "videotoolbox" not in encoder:  # VTB relies on -q:v primarily
                encoder_args.extend(["-b:v", preset.video_bitrate])
        
        encoder_args.extend(["-c:a", "aac", "-b:a", preset.audio_bitrate])
        
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
            quality=preset.quality,
            export_filter_hook=ar_filter,
            encoder_args_override=encoder_args,
            progress_callback=progress_callback
        )
        
    def export_all(
        self,
        manifest: ProjectManifest,
        output_dir: Path,
        presets: list[ExportPreset] | None = None,
        progress_callback: Callable[[float, str, str], None] | None = None
    ) -> list[Path]:
        """Export to all provided presets sequentially."""
        presets = presets or manifest.export_presets
        results = []
        for p in presets:
            res = self.export(manifest, p, output_dir, progress_callback)
            results.append(res)
            
        return results

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
