"""Render engine orchestrating FFmpeg execution from project manifests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from graphcut.ffmpeg_executor import FFmpegExecutor, FFmpegError
from graphcut.filtergraph import FilterGraph
from graphcut.models import ProjectManifest, Transcript
from graphcut.audio_mixer import AudioMixer
from graphcut.audio_normalizer import AudioNormalizer
from graphcut.overlay_compositor import OverlayCompositor
from graphcut.caption_generator import CaptionGenerator
from graphcut.transcript_editor import TranscriptEditor

logger = logging.getLogger(__name__)

TRANSITION_FILTERS = {
    "fade": "fade",
    "xfade": "slideleft",
}


class Renderer:
    """Orchestrates building filtergraphs and running FFmpeg."""

    def __init__(self, executor: FFmpegExecutor | None = None) -> None:
        self.executor = executor or FFmpegExecutor()

    @staticmethod
    def _resolve_transcript_cuts(
        manifest: ProjectManifest,
        project_dir: Path | None,
        model_name: str = "medium",
    ) -> list[dict]:
        """Return merged global time ranges for transcript cuts.

        Supports mixed cut formats in `manifest.transcript_cuts`:
        - {"start": float, "end": float} interpreted as global timeline seconds
        - {"source_id": str, "word_index": int} interpreted as word deletions per-source,
          converted to local time ranges via cached transcript JSON, then mapped to global time.
        """
        if not manifest.transcript_cuts:
            return []

        global_ranges: list[dict] = []
        word_indices_by_source: dict[str, list[int]] = {}

        for cut in manifest.transcript_cuts:
            if not isinstance(cut, dict):
                continue
            if "start" in cut and "end" in cut:
                try:
                    s = float(cut["start"])
                    e = float(cut["end"])
                except (TypeError, ValueError):
                    continue
                if e > s:
                    global_ranges.append({"start": s, "end": e})
                continue

            sid = cut.get("source_id")
            idx = cut.get("word_index")
            if isinstance(sid, str) and isinstance(idx, int):
                word_indices_by_source.setdefault(sid, []).append(idx)

        if project_dir is None or not word_indices_by_source:
            return TranscriptEditor._merge_ranges(global_ranges)

        # Precompute each clip's global offset based on trims (before any cuts are applied).
        clip_offsets: list[float] = []
        offset = 0.0
        for clip in manifest.clip_order:
            info = manifest.sources.get(clip.source_id)
            if not info:
                clip_offsets.append(offset)
                continue
            t_start = clip.trim_start if clip.trim_start is not None else 0.0
            t_end = clip.trim_end if clip.trim_end is not None else info.duration_seconds
            clip_offsets.append(offset)
            offset += max(0.0, t_end - t_start)

        # Convert word indices -> local time ranges -> global time ranges.
        for source_id, indices in word_indices_by_source.items():
            info = manifest.sources.get(source_id)
            if not info:
                continue
            tp = project_dir / ".cache" / "transcripts" / f"{info.file_hash}_{model_name}.json"
            if not tp.exists():
                continue

            try:
                transcript = Transcript.model_validate_json(tp.read_text())
            except Exception:
                continue

            local_ranges = TranscriptEditor.delete_words(transcript, indices)
            if not local_ranges:
                continue

            # Apply to every occurrence of the source in the timeline.
            for clip_i, clip in enumerate(manifest.clip_order):
                if clip.source_id != source_id:
                    continue
                t_start = clip.trim_start if clip.trim_start is not None else 0.0
                t_end = clip.trim_end if clip.trim_end is not None else info.duration_seconds
                base = clip_offsets[clip_i]

                for r in local_ranges:
                    try:
                        rs = float(r["start"])
                        re = float(r["end"])
                    except (TypeError, ValueError, KeyError):
                        continue

                    # Intersect with trimmed region.
                    s = max(rs, t_start)
                    e = min(re, t_end)
                    if e <= s:
                        continue

                    global_ranges.append({
                        "start": round(base + (s - t_start), 3),
                        "end": round(base + (e - t_start), 3),
                    })

        return TranscriptEditor._merge_ranges(global_ranges)

    def render(
        self,
        manifest: ProjectManifest,
        output_path: Path,
        project_dir: Path | None = None,
        quality: str = "final",
        progress_callback: Callable[[float, str, str], None] | None = None,
        export_filter_hook: Callable[[FilterGraph, str], str] | None = None,
        encoder_args_override: list[str] | None = None,
    ) -> Path:
        """Render a project manifest to an MP4 file.
        
        Args:
            manifest: The GraphCut project manifest.
            output_path: Destination path for the rendered video.
            project_dir: Project directory (used for caches like transcripts/captions).
            quality: Render quality preset ('draft', 'preview', 'final').
            progress_callback: Optional callable for real-time progress.
            export_filter_hook: Optional intercept to attach dynamic overlay scaling constraints via filtergraph string modification.
            encoder_args_override: Optional list replacing final video outputs commands formatting mapping.
            
        Returns:
            The path to the rendered output.
            
        Raises:
            ValueError: If the manifest is invalid for rendering.
            FFmpegError: If the render process fails.
        """
        if not manifest.clip_order:
            raise ValueError("No clips in the project to render.")

        global_cuts = self._resolve_transcript_cuts(manifest, project_dir)

        fg = FilterGraph()
        
        # 1. Add inputs
        input_indices: dict[str, int] = {}
        for source_id, info in manifest.sources.items():
            idx = fg.add_input(info.file_path)
            input_indices[source_id] = idx

        # 2. Add trims & transitions
        processed_clips: list[dict[str, str | float]] = []
        
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

            processed_clips.append(
                {
                    "video": v_out,
                    "audio": a_out,
                    "duration": max(0.0, t_end - t_start),
                    "transition": clip.transition,
                    "transition_duration": max(0.0, float(clip.transition_duration)),
                }
            )

        # 2b. Apply transcript_cuts — split segments around cut ranges
        if global_cuts:
            cut_clips: list[dict[str, str | float]] = []
            # Calculate global timeline position for each clip
            timeline_pos = 0.0
            for clip in manifest.clip_order:
                info = manifest.sources[clip.source_id]
                idx = input_indices[clip.source_id]
                t_start = clip.trim_start if clip.trim_start is not None else 0.0
                t_end = clip.trim_end if clip.trim_end is not None else info.duration_seconds
                clip_duration = t_end - t_start

                # Find cuts that overlap this clip's global timeline range
                clip_global_start = timeline_pos
                clip_global_end = timeline_pos + clip_duration

                # Collect local cut points (relative to clip start)
                local_cuts: list[tuple[float, float]] = []
                for cut in global_cuts:
                    cut_s = cut["start"]
                    cut_e = cut["end"]
                    # Check overlap with this clip's global range
                    if cut_s < clip_global_end and cut_e > clip_global_start:
                        # Convert to local clip time
                        local_s = max(0.0, cut_s - clip_global_start) + t_start
                        local_e = min(clip_duration, cut_e - clip_global_start) + t_start
                        local_cuts.append((local_s, local_e))

                if local_cuts:
                    # Build keep-segments between cuts
                    keep_start = t_start
                    kept_segments: list[tuple[str, str, float]] = []
                    for ls, le in sorted(local_cuts):
                        if ls > keep_start:
                            v = fg.trim(idx, start=keep_start, end=ls, stream="v")
                            a = fg.trim(idx, start=keep_start, end=ls, stream="a")
                            kept_segments.append((v, a, max(0.0, ls - keep_start)))
                        keep_start = le
                    if keep_start < t_end:
                        v = fg.trim(idx, start=keep_start, end=t_end, stream="v")
                        a = fg.trim(idx, start=keep_start, end=t_end, stream="a")
                        kept_segments.append((v, a, max(0.0, t_end - keep_start)))

                    for seg_index, (v, a, duration) in enumerate(kept_segments):
                        cut_clips.append(
                            {
                                "video": v,
                                "audio": a,
                                "duration": duration,
                                "transition": clip.transition if seg_index == len(kept_segments) - 1 else "cut",
                                "transition_duration": max(0.0, float(clip.transition_duration)) if seg_index == len(kept_segments) - 1 else 0.0,
                            }
                        )
                else:
                    cut_clips.append(
                        {
                            "video": fg.trim(idx, start=t_start, end=t_end, stream="v"),
                            "audio": fg.trim(idx, start=t_start, end=t_end, stream="a"),
                            "duration": clip_duration,
                            "transition": clip.transition,
                            "transition_duration": max(0.0, float(clip.transition_duration)),
                        }
                    )

                timeline_pos += clip_duration

            processed_clips = cut_clips

        if not processed_clips:
            raise ValueError("All timeline content was removed by cuts. Add or restore clips before rendering.")

        # 3. Apply concat or transitions
        if len(processed_clips) == 1:
            # Single clip, no concat
            final_v = str(processed_clips[0]["video"])
            final_a = str(processed_clips[0]["audio"])
            total_duration = float(processed_clips[0]["duration"])
        else:
            current = processed_clips[0]
            final_v = str(current["video"])
            final_a = str(current["audio"])
            total_duration = float(current["duration"])

            for index, nxt in enumerate(processed_clips[1:]):
                prev = processed_clips[index]
                next_v = str(nxt["video"])
                next_a = str(nxt["audio"])
                next_duration = float(nxt["duration"])
                transition = str(prev["transition"])
                transition_duration = float(prev["transition_duration"])

                if transition in TRANSITION_FILTERS and transition_duration > 0:
                    overlap = min(transition_duration, total_duration, next_duration)
                    if overlap > 0:
                        final_v = fg.xfade(
                            final_v,
                            next_v,
                            duration=overlap,
                            offset=max(0.0, total_duration - overlap),
                            transition=TRANSITION_FILTERS[transition],
                        )
                        final_a = fg.acrossfade(final_a, next_a, duration=overlap)
                        total_duration += next_duration - overlap
                        continue

                final_v, final_a = fg.concat([(final_v, final_a), (next_v, next_a)], n=2)
                total_duration += next_duration

        # 4. Handle Overlays (Webcam, Watermark)
        compositor = OverlayCompositor()
        
        # We need base dimensions for proportional scaling
        base_w, base_h = 1920, 1080
        if len(manifest.clip_order) > 0:
            first_src = manifest.sources[manifest.clip_order[0].source_id]
            base_w = first_src.width or 1920
            base_h = first_src.height or 1080
            
        if manifest.webcam and manifest.webcam.source_id in input_indices:
            idx = input_indices[manifest.webcam.source_id]
            final_v = compositor.add_webcam_overlay(
                fg, 
                base_label=f"[{final_v}]", 
                webcam_input_idx=idx, 
                config=manifest.webcam,
                base_width=base_w,
                base_height=base_h
            )

        # 5. Handle Preview Quality (Scale)
        if quality == "preview":
            final_v = fg.scale(f"[{final_v}]" if not final_v.startswith("[") and not manifest.webcam else final_v, width=854, height=480)

        # 6. Add Captions (Burn-in)
        # Assuming we check if there's a cached transcript mapped to the primary source
        try:
            if project_dir and manifest.clip_order and manifest.burn_captions:
                main_src_id = manifest.clip_order[0].source_id
                main_src = manifest.sources[main_src_id]
                transcript_path = project_dir / ".cache" / "transcripts" / f"{main_src.file_hash}_medium.json"
                if transcript_path.exists():
                    with open(transcript_path) as f:
                        t_data = f.read()
                    transcript = Transcript.model_validate_json(t_data)
                    
                    cg = CaptionGenerator(manifest.caption_style)
                    ass_path = project_dir / ".cache" / "transcripts" / f"{main_src.file_hash}_burn.ass"
                    cg.to_ass(transcript, ass_path)
                    
                    captions_filter_str = cg.burn_in_filter(ass_path)
                    
                    # Add to FilterGraph
                    cap_out = fg._next_v_label()
                    fg.nodes.append(
                        __import__("graphcut.filtergraph", fromlist=["FilterNode"]).FilterNode(
                            filter_name=captions_filter_str,
                            inputs=[f"[{final_v}]" if not final_v.startswith("[") else final_v.strip("[]")],
                            outputs=[cap_out]
                        )
                    )
                    final_v = cap_out
                    logger.info("Added caption burn-in node to filtergraph.")
        except Exception as e:
            logger.warning("Failed to setup caption burn-in: %s", e)

        # 7. Compile final FilterGraph
        inputs, graph_str = fg.compile()
        fg.debug_print()

        # 4b. Mix Audio
        mixer = AudioMixer(manifest.audio_mix)
        source_lbls = [final_a]
        
        narr_lbl = None
        if manifest.narration and manifest.narration in input_indices:
            idx = input_indices[manifest.narration]
            narr_lbl = fg.atrim(f"{idx}:a", start=0.0, end=total_duration)

        music_lbl = None
        if manifest.music and manifest.music in input_indices:
            idx = input_indices[manifest.music]
            music_lbl = mixer._apply_music_loop(fg, f"{idx}:a", total_duration)

        final_a = mixer.build_audio_graph(
            fg, source_labels=source_lbls, 
            narration_label=narr_lbl, 
            music_label=music_lbl
        )

        # 6. Apply Export Filter Hook
        if export_filter_hook:
            final_v = export_filter_hook(fg, final_v)

        # 7. Compile final FilterGraph
        inputs, graph_str = fg.compile()
        fg.debug_print()
        
        # 8. Build command
        encoder = self.executor.get_best_encoder()
        cmd = []
        for inp in inputs:
            cmd.extend(["-i", str(inp)])
            
        cmd.extend([
            "-filter_complex", graph_str,
            "-map", f"[{final_v}]",
            "-map", f"[{final_a}]",
        ])
        
        if encoder_args_override:
            cmd.extend(encoder_args_override)
        else:
            cmd.append("-c:v")
            cmd.append(encoder)
            if quality == "preview":
                cmd.extend(["-preset", "fast", "-crf", "28"])
            else:
                cmd.extend(["-preset", "medium", "-crf", "23"])
            
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "192k"
            ])
            
        cmd.extend([
            "-y", str(output_path)
        ])

        # 7. Execute
        logger.info("Starting render to %s using %s", output_path, encoder)
        self.executor.run(
            args=cmd,
            progress_callback=progress_callback,
            duration=total_duration
        )

        # 8. Normalize output audio if configured
        if manifest.audio_mix.normalize:
            norm = AudioNormalizer(self.executor)
            out_tmp = output_path.with_name(f"{output_path.stem}_norm{output_path.suffix}")
            norm.normalize(
                input_path=output_path,
                output_path=out_tmp,
                target_lufs=manifest.audio_mix.target_lufs,
                true_peak=-1.0, # Slight headroom to prevent inter-sample clipping
            )
            # Replace original with normalized
            out_tmp.replace(output_path)

        return output_path

    def render_preview(self, manifest: ProjectManifest, project_dir: Path) -> Path:
        """Render a 480p preview to the build directory."""
        build_dir = project_dir / manifest.build_dir
        build_dir.mkdir(parents=True, exist_ok=True)
        output = build_dir / "preview.mp4"
        return self.render(manifest, output, project_dir=project_dir, quality="preview")

    def render_final(self, manifest: ProjectManifest, project_dir: Path) -> Path:
        """Render a full-quality export to the build directory."""
        build_dir = project_dir / manifest.build_dir
        build_dir.mkdir(parents=True, exist_ok=True)
        output = build_dir / "final.mp4"
        return self.render(manifest, output, project_dir=project_dir, quality="final")
