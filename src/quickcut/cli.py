"""Click commands for the QuickCut editor."""

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from quickcut.media_prober import probe_files
from quickcut.project_manager import ProjectManager
from quickcut.renderer import Renderer

logger = logging.getLogger(__name__)
console = Console()


@click.group()
@click.option(
    "--verbose", "-v", is_flag=True, help="Enable debug logging output."
)
def cli(verbose: bool) -> None:
    """QuickCut — Local-first video editor CLI."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Note: Using rich for CLI outputs, keeping basicConfig simple
    if verbose:
        logger.debug("Debug logging enabled")


@cli.command()
@click.argument("name")
@click.option(
    "--directory",
    "-d",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path.cwd(),
    help="Target directory to create the project in (defaults to current dir).",
)
def new_project(name: str, directory: Path) -> None:
    """Create a new project directory and manifest."""
    try:
        manifest = ProjectManager.create_project(name=name, directory=directory)
        console.print(
            f"[bold green]Created project '{manifest.name}'[/bold green] at {directory / name}"
        )
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--id", "custom_id", help="Optional custom identifier for a single source file.")
def add_source(project_dir: Path, files: tuple[Path, ...], custom_id: str | None) -> None:
    """Add source media files to the project manifest."""
    if not files:
        console.print("No files specified.")
        return

    if custom_id and len(files) > 1:
        console.print("[bold red]Error:[/bold red] --id cannot be used with multiple files.")
        raise click.Abort()

    try:
        manifest = ProjectManager.load_project(project_dir)
        
        table = Table(title="Added Sources")
        table.add_column("Source ID", style="cyan")
        table.add_column("File", style="magenta")
        table.add_column("Duration")
        table.add_column("Resolution")

        for file_path in files:
            source_id = ProjectManager.add_source(
                manifest=manifest, file_path=file_path, source_id=custom_id
            )
            info = manifest.sources[source_id]
            
            res_str = f"{info.width}x{info.height}" if info.width and info.height else "N/A"
            dur_str = f"{info.duration_seconds:.2f}s" if info.duration_seconds else "N/A"
            table.add_row(source_id, file_path.name, dur_str, res_str)

        ProjectManager.save_project(manifest, project_dir)
        console.print(table)
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def inspect_media(files: tuple[Path, ...]) -> None:
    """Probe and display metadata for media files."""
    if not files:
        console.print("No files specified.")
        return

    try:
        results = probe_files(list(files))
        
        table = Table(title="Media Inspection")
        table.add_column("File", style="magenta")
        table.add_column("Type", style="cyan")
        table.add_column("Res/FPS", style="green")
        table.add_column("Duration", style="yellow")
        table.add_column("Video", style="blue")
        table.add_column("Audio", style="red")
        
        for name, info in results.items():
            res_fps = ""
            if info.width and info.height:
                res_fps = f"{info.width}x{info.height}"
                if info.fps:
                    res_fps += f" @ {info.fps}fps"
                    
            dur_str = f"{info.duration_seconds:.2f}s" if info.duration_seconds else "N/A"
            
            vid_str = info.video_codec or "N/A"
            
            aud_str = "N/A"
            if info.audio_codec:
                aud_str = f"{info.audio_codec} ({info.audio_channels}ch, {info.audio_sample_rate}Hz)"

            table.add_row(
                info.file_path.name,
                info.media_type,
                res_fps,
                dur_str,
                vid_str,
                aud_str,
            )

        console.print(table)
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
def render_preview(project_dir: Path) -> None:
    """Render a fast 480p preview of the project."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        renderer = Renderer()
        
        console.print(f"Rendering preview for '{manifest.name}'...")
        output_path = renderer.render_preview(manifest, project_dir)
        console.print(f"[bold green]Success![/bold green] Preview rendered to: {output_path}")
        
    except Exception as e:
        console.print(f"[bold red]Render failed:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="final", help="Render quality.")
@click.option("--output", type=click.Path(file_okay=True, dir_okay=False, path_type=Path), help="Specific output filename.")
def render(project_dir: Path, quality: str, output: Path | None) -> None:
    """Render the project to a video file."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        renderer = Renderer()
        
        out_path = output or (project_dir / manifest.build_dir / f"{quality}.mp4")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        console.print(f"Rendering '{manifest.name}' (quality: {quality})...")
        final_path = renderer.render(manifest, out_path, quality=quality)
        console.print(f"[bold green]Success![/bold green] Video rendered to: {final_path}")
        
    except Exception as e:
        console.print(f"[bold red]Render failed:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--model", default="medium", help="Whisper model name (tiny/base/small/medium/large-v3).")
@click.option("--language", default=None, help="Language code (auto-detect if omitted).")
def transcribe(project_dir: Path, model: str, language: str | None) -> None:
    """Transcribe all source audio in a project."""
    from quickcut.transcriber import Transcriber

    try:
        manifest = ProjectManager.load_project(project_dir)
        transcriber = Transcriber(model_name=model)

        for source_id, info in manifest.sources.items():
            if info.media_type in ("video", "audio"):
                console.print(f"Transcribing [cyan]{source_id}[/cyan]...")
                transcript = transcriber.transcribe(
                    info.file_path, cache_dir=project_dir, language=language
                )
                console.print(
                    f"  ✓ {len(transcript.segments)} segments, "
                    f"{len(transcript.all_words)} words, "
                    f"language: {transcript.language}"
                )
                console.print(f"  [dim]{transcript.full_text[:200]}...[/dim]")

        console.print("[bold green]Transcription complete.[/bold green]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--threshold", default=27.0, help="Detection sensitivity (lower = more sensitive).")
def detect_scenes(project_dir: Path, threshold: float) -> None:
    """Detect scene boundaries in project video sources."""
    from quickcut.scene_detector import detect_scenes as _detect

    try:
        manifest = ProjectManager.load_project(project_dir)
        table = Table(title="Scene Detection Results")
        table.add_column("Source", style="cyan")
        table.add_column("Scene #", style="magenta")
        table.add_column("Start", style="green")
        table.add_column("End", style="green")
        table.add_column("Duration", style="yellow")

        for source_id, info in manifest.sources.items():
            if info.media_type == "video":
                scenes = _detect(info.file_path, threshold=threshold)
                for s in scenes:
                    dur = s["end"] - s["start"]
                    table.add_row(
                        source_id,
                        str(s["index"]),
                        f"{s['start']:.2f}s",
                        f"{s['end']:.2f}s",
                        f"{dur:.2f}s",
                    )

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--min-duration", default=1.0, help="Minimum silence duration to cut (seconds).")
@click.option("--preview", is_flag=True, help="Preview cuts without applying them.")
def remove_silences(project_dir: Path, min_duration: float, preview: bool) -> None:
    """Detect and remove long silences from the project."""
    from quickcut.silence_detector import detect_silences, suggest_jump_cuts

    try:
        manifest = ProjectManager.load_project(project_dir)

        all_cuts: list[dict] = []
        for source_id, info in manifest.sources.items():
            if info.media_type in ("video", "audio"):
                silences = detect_silences(info.file_path, min_duration=min_duration)
                cuts = suggest_jump_cuts(silences)
                all_cuts.extend(cuts)
                console.print(
                    f"[cyan]{source_id}[/cyan]: {len(silences)} silences → {len(cuts)} cuts"
                )

        if not all_cuts:
            console.print("No significant silences detected.")
            return

        if preview:
            table = Table(title="Suggested Silence Cuts (Preview)")
            table.add_column("#", style="dim")
            table.add_column("Start", style="green")
            table.add_column("End", style="green")
            table.add_column("Duration", style="yellow")
            for i, cut in enumerate(all_cuts):
                dur = cut["end"] - cut["start"]
                table.add_row(str(i), f"{cut['start']:.2f}s", f"{cut['end']:.2f}s", f"{dur:.2f}s")
            console.print(table)
            console.print("[dim]Run without --preview to apply these cuts.[/dim]")
        else:
            from quickcut.transcript_editor import TranscriptEditor
            TranscriptEditor.apply_cuts(manifest, all_cuts)
            ProjectManager.save_project(manifest, project_dir)
            console.print(
                f"[bold green]Applied {len(all_cuts)} silence cuts to project.[/bold green]"
            )

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--duration", type=float, default=None, help="Recording duration in seconds.")
@click.option("--device", type=str, default=None, help="Input device name/ID.")
def record_voiceover(project_dir: Path, duration: float | None, device: str | None) -> None:
    """Record a voice-over and add it to the project."""
    from quickcut.voice_recorder import VoiceRecorder
    from quickcut.models import MediaInfo

    try:
        manifest = ProjectManager.load_project(project_dir)
        
        # Determine output path
        source_id = f"voiceover_{len(manifest.sources) + 1}"
        out_name = f"{source_id}.wav"
        out_path = project_dir / "sources" / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        recorder = VoiceRecorder()
        recorder.record_voiceover(
            output_path=out_path,
            duration=duration,
            device=device,
        )
        
        if out_path.exists():
            # Quick probe for duration
            from quickcut.media_prober import probe_file
            info = probe_file(out_path)
            
            manifest.sources[source_id] = info
            manifest.narration = source_id
            ProjectManager.save_project(manifest, project_dir)
            
            console.print(f"[bold green]Voice-over saved and set as narration ({source_id}).[/bold green]")
        else:
            console.print("[bold red]Recording failed (no output file created).[/bold red]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--source-gain", type=float, help="Primary source audio gain (dB).")
@click.option("--narration-gain", type=float, help="Narration gain (dB).")
@click.option("--music-gain", type=float, help="Music track gain (dB).")
@click.option("--ducking", type=float, help="Ducking strength (0.0 to 1.0).")
@click.option("--normalize/--no-normalize", default=None, help="Enable/disable EBU R128 loudness normalization.")
def set_audio(
    project_dir: Path, 
    source_gain: float | None,
    narration_gain: float | None,
    music_gain: float | None,
    ducking: float | None,
    normalize: bool | None,
) -> None:
    """Configure audio mixing settings like gain and ducking."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        mix = manifest.audio_mix
        
        if source_gain is not None:
            mix.source_gain_db = source_gain
        if narration_gain is not None:
            mix.narration_gain_db = narration_gain
        if music_gain is not None:
            mix.music_gain_db = music_gain
        if ducking is not None:
            if not 0.0 <= ducking <= 1.0:
                raise click.BadParameter("Ducking must be between 0.0 and 1.0")
            mix.ducking_strength = ducking
        if normalize is not None:
            mix.normalize = normalize
            
        ProjectManager.save_project(manifest, project_dir)
        console.print("[bold green]Audio config updated.[/bold green]")
        
        # Display current config
        table = Table(title="Audio Mix Config")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="yellow")
        
        table.add_row("Source Gain", f"{mix.source_gain_db} dB")
        table.add_row("Narration Gain", f"{mix.narration_gain_db} dB")
        table.add_row("Music Gain", f"{mix.music_gain_db} dB")
        table.add_row("Ducking Strength", f"{mix.ducking_strength}")
        table.add_row("EBU R128 Normalize", str(mix.normalize))
        table.add_row("Target LUFS", f"{mix.target_lufs}")
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


if __name__ == "__main__":
    cli()

