"""Render engine orchestrating FFmpeg execution from project manifests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from quickcut.ffmpeg_executor import FFmpegExecutor, FFmpegError
from quickcut.filtergraph import FilterGraph
from quickcut.models import ProjectManifest

logger = logging.getLogger(__name__)


class Renderer:
    """Orchestrates building filtergraphs and running FFmpeg."""

    def __init__(self, executor: FFmpegExecutor | None = None) -> None:
        self.executor = executor or FFmpegExecutor()

    def render(
        self,
        manifest: ProjectManifest,
        output_path: Path,
        quality: str = "final",
        progress_callback: Callable[[float], None] | None = None,
    ) -> Path:
        """Render a project manifest to an MP4 file.
        
        Args:
            manifest: The QuickCut project manifest.
            output_path: Destination path for the rendered video.
            quality: Render quality preset ('draft', 'preview', 'final').
            progress_callback: Optional callable for real-time progress (0-100).
            
        Returns:
            The path to the rendered output.
            
        Raises:
            ValueError: If the manifest is invalid for rendering.
            FFmpegError: If the render process fails.
        """
        if not manifest.clip_order:
            raise ValueError("No clips in the project to render.")

        fg = FilterGraph()
        
        # 1. Add inputs
        input_indices: dict[str, int] = {}
        for source_id, info in manifest.sources.items():
            idx = fg.add_input(info.file_path)
            input_indices[source_id] = idx

        # 2. Add trims & transitions
        processed_pairs: list[tuple[str, str]] = []
        
        for clip in manifest.clip_order:
            if clip.source_id not in input_indices:
                raise ValueError(f"Missing source info for clip: {clip.source_id}")
            
            idx = input_indices[clip.source_id]
            info = manifest.sources[clip.source_id]
            
            # Use full duration if no trim specified
            t_start = clip.trim_start if clip.trim_start is not None else 0.0
            t_end = clip.trim_end if clip.trim_end is not None else info.duration_seconds

            v_out = fg.trim(idx, start=t_start, end=t_end, stream="v")
            a_out = fg.trim(idx, start=t_start, end=t_end, stream="a")
            
            processed_pairs.append((v_out, a_out))

        # 3. Apply concat or transitions
        if len(processed_pairs) == 1:
            # Single clip, no concat
            final_v, final_a = processed_pairs[0]
        else:
            # Needs concat
            final_v, final_a = fg.concat(processed_pairs, n=len(processed_pairs))

        # 4. Handle Preview Quality (Scale)
        if quality == "preview":
            final_v = fg.scale(final_v, width=854, height=480)

        # 5. Compile FilterGraph
        inputs, graph_str = fg.compile()
        fg.debug_print()

        # 6. Build command
        encoder = self.executor.get_best_encoder()
        cmd = []
        for inp in inputs:
            cmd.extend(["-i", str(inp)])
            
        cmd.extend([
            "-filter_complex", graph_str,
            "-map", f"[{final_v}]",
            "-map", f"[{final_a}]",
            "-c:v", encoder,
        ])
        
        if quality == "preview":
            cmd.extend(["-preset", "fast", "-crf", "28"])
        else:
            cmd.extend(["-preset", "medium", "-crf", "23"])

        cmd.extend([
            "-c:a", "aac",
            "-b:a", "192k",
            "-y", str(output_path)
        ])

        # 7. Execute
        # Calculate total duration for progress
        total_duration = 0.0
        for clip in manifest.clip_order:
            if clip.trim_start is not None and clip.trim_end is not None:
                total_duration += (clip.trim_end - clip.trim_start)
            else:
                total_duration += manifest.sources[clip.source_id].duration_seconds

        logger.info("Starting render to %s using %s", output_path, encoder)
        self.executor.run(
            args=cmd,
            progress_callback=progress_callback,
            duration=total_duration
        )

        return output_path

    def render_preview(self, manifest: ProjectManifest, project_dir: Path) -> Path:
        """Render a 480p preview to the build directory."""
        build_dir = project_dir / manifest.build_dir
        build_dir.mkdir(parents=True, exist_ok=True)
        output = build_dir / "preview.mp4"
        return self.render(manifest, output, quality="preview")

    def render_final(self, manifest: ProjectManifest, project_dir: Path) -> Path:
        """Render a full-quality export to the build directory."""
        build_dir = project_dir / manifest.build_dir
        build_dir.mkdir(parents=True, exist_ok=True)
        output = build_dir / "final.mp4"
        return self.render(manifest, output, quality="final")
