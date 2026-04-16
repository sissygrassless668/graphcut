"""Click commands for the GraphCut editor."""

import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, TextColumn, BarColumn, TimeRemainingColumn

from graphcut.agent_workflows import (
    build_publish_bundle,
    build_storyboard,
    bundle_to_markdown,
    resolve_script_text,
    viralize,
)
from graphcut.agent_runner import agent_template, build_creator_brief, run_agent_job
from graphcut.compare_sbs import run_compare_sbs
from graphcut.factory import build_plan, execute_plan
from graphcut.generation_queue import (
    fetch_job,
    get_job,
    list_jobs,
    list_provider_names,
    load_storyboard,
    submit_job,
    wait_for_job,
)
from graphcut.media_prober import probe_files
from graphcut.models import ClipRef, SceneConfig
from graphcut.platforms import list_platform_profiles, list_workflow_recipes
from graphcut.project_manager import ProjectManager
from graphcut.renderer import Renderer
from graphcut.exporter import Exporter

logger = logging.getLogger(__name__)
console = Console()

AVAILABLE_TRANSITIONS = {
    "cut": {
        "label": "Cut",
        "description": "Instant change to the next clip.",
        "default_duration": 0.0,
    },
    "fade": {
        "label": "Fade",
        "description": "Classic dissolve between clips.",
        "default_duration": 0.35,
    },
    "xfade": {
        "label": "Crossfade",
        "description": "Cinematic slide transition between clips.",
        "default_duration": 0.6,
    },
}

def _manifest_json(manifest) -> dict:
    # Uses Pydantic's JSON rendering so Paths/DateTimes become strings.
    return json.loads(manifest.model_dump_json())


def _parse_ranges(range_specs: tuple[str, ...]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for spec in range_specs:
        if not spec:
            continue
        parts = spec.split(":")
        if len(parts) != 2:
            raise click.BadParameter(f"Invalid range '{spec}'. Expected START:END (seconds).")
        try:
            start = float(parts[0])
            end = float(parts[1])
        except ValueError as e:
            raise click.BadParameter(f"Invalid range '{spec}'. START/END must be numbers.") from e
        if start < 0 or end < 0:
            raise click.BadParameter(f"Invalid range '{spec}'. START/END must be >= 0.")
        if end <= start:
            raise click.BadParameter(f"Invalid range '{spec}'. END must be > START.")
        out.append((start, end))
    return out


def _normalize_transition(name: str) -> str:
    transition = (name or "").strip().lower()
    if transition not in AVAILABLE_TRANSITIONS:
        raise click.BadParameter(
            f"Unknown transition '{name}'. Choose from: {', '.join(AVAILABLE_TRANSITIONS.keys())}."
        )
    return transition


def _print_factory_plan(plan, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(plan.to_dict()))
        return

    table = Table(title=f"{plan.mode.title()} Plan")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Output", style="cyan")
    table.add_column("Range", style="green")
    table.add_column("Duration", style="yellow")
    table.add_column("Score", style="magenta")
    table.add_column("Notes", style="blue")

    for index, item in enumerate(plan.outputs, start=1):
        score = f"{item.score:.1f}" if item.score is not None else "-"
        notes = item.reason or ""
        table.add_row(
            str(index),
            item.filename,
            f"{item.start:.2f}s -> {item.end:.2f}s",
            f"{item.duration:.2f}s",
            score,
            notes,
        )

    console.print(table)
    console.print(
        f"[bold]Platform:[/bold] {plan.platform.label}  "
        f"[bold]Captions:[/bold] {plan.captions}  "
        f"[bold]Outputs:[/bold] {len(plan.outputs)}  "
        f"[bold]Output Dir:[/bold] {plan.output_dir}"
    )
    if plan.scene_count or plan.silence_count:
        console.print(
            f"[dim]Detected {plan.scene_count} scenes and {plan.silence_count} silence cuts.[/dim]"
        )
    for warning in plan.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def _emit_payload(payload: dict, as_json: bool, output: Path | None = None, markdown: str | None = None) -> None:
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if markdown is not None and not as_json:
            output.write_text(markdown, encoding="utf-8")
        else:
            output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if as_json:
        console.print_json(json.dumps(payload))
    elif markdown is not None:
        console.print(markdown)
    else:
        console.print_json(json.dumps(payload))


@click.group()
@click.option(
    "--verbose", "-v", is_flag=True, help="Enable debug logging output."
)
def cli(verbose: bool) -> None:
    """GraphCut — Local-first video editor CLI."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Note: Using rich for CLI outputs, keeping basicConfig simple
    if verbose:
        logger.debug("Debug logging enabled")


@cli.group("platforms")
def platforms_group() -> None:
    """List built-in creator platform presets."""


@cli.group("providers")
def providers_group() -> None:
    """List available AI video generation providers."""


@providers_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def providers_list(as_json: bool) -> None:
    """List generation providers available to the CLI."""
    providers = list_provider_names()
    if as_json:
        console.print_json(json.dumps({"providers": providers}))
        return

    table = Table(title="Providers")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    for provider in providers:
        provider_type = "built-in mock" if provider == "mock" else "external"
        table.add_row(provider, provider_type)
    console.print(table)


@platforms_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def platforms_list(as_json: bool) -> None:
    """List available publishing surfaces."""
    platforms = list_platform_profiles()
    if as_json:
        console.print_json(json.dumps([platform.to_dict() for platform in platforms]))
        return

    table = Table(title="Platforms")
    table.add_column("Key", style="cyan")
    table.add_column("Label", style="green")
    table.add_column("Canvas", style="yellow")
    table.add_column("Max Dur", style="magenta")
    table.add_column("Captions", style="blue")
    for platform in platforms:
        table.add_row(
            platform.key,
            platform.label,
            f"{platform.width}x{platform.height}",
            f"{platform.max_duration_seconds:.0f}s",
            platform.default_caption_style,
        )
    console.print(table)


@cli.group("recipes")
def recipes_group() -> None:
    """List built-in workflow defaults."""


@recipes_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def recipes_list(as_json: bool) -> None:
    """List available creator workflow recipes."""
    recipes = list_workflow_recipes()
    if as_json:
        console.print_json(json.dumps([recipe.to_dict() for recipe in recipes]))
        return

    table = Table(title="Recipes")
    table.add_column("Key", style="cyan")
    table.add_column("Platform", style="green")
    table.add_column("Clips", style="yellow")
    table.add_column("Clip Range", style="magenta")
    table.add_column("Description", style="blue")
    for recipe in recipes:
        table.add_row(
            recipe.key,
            recipe.default_platform,
            str(recipe.clips),
            f"{recipe.min_clip_seconds:.0f}-{recipe.max_clip_seconds:.0f}s",
            recipe.description,
        )
    console.print(table)


@cli.command("storyboard")
@click.argument("script_input", required=False)
@click.option("--script-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Read script text from a file.")
@click.option("--text", type=str, default=None, help="Inline script text.")
@click.option("--platform", "platform_name", type=str, default="tiktok", show_default=True, help="Target platform preset.")
@click.option("--provider", type=str, default="generic", show_default=True, help="Target AI video provider label.")
@click.option("--hook-style", type=click.Choice(["curiosity", "authority", "explainer"]), default="curiosity", show_default=True)
@click.option("--shots", type=int, default=None, help="Maximum number of shots to emit.")
@click.option("--shot-seconds", type=float, default=None, help="Force each shot duration.")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write JSON plan to a file.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def storyboard_cmd(
    script_input: str | None,
    script_file: Path | None,
    text: str | None,
    platform_name: str,
    provider: str,
    hook_style: str,
    shots: int | None,
    shot_seconds: float | None,
    output: Path | None,
    as_json: bool,
) -> None:
    """Turn a script into AI-video-ready shot prompts."""
    try:
        script_text = resolve_script_text(script_input=script_input, script_file=script_file, text=text)
        storyboard = build_storyboard(
            script_text,
            platform_name=platform_name,
            provider=provider,
            hook_style=hook_style,
            shots=shots,
            shot_seconds=shot_seconds,
        )
        _emit_payload(storyboard.to_dict(), as_json=as_json, output=output)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command("package")
@click.argument("source_name")
@click.option("--platform", "platform_name", type=str, default="tiktok", show_default=True, help="Target platform preset.")
@click.option("--script-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Read script text from a file.")
@click.option("--text", type=str, default=None, help="Inline script text.")
@click.option("--format", "output_format", type=click.Choice(["json", "markdown"]), default="json", show_default=True)
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write bundle to a file.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def package_cmd(
    source_name: str,
    platform_name: str,
    script_file: Path | None,
    text: str | None,
    output_format: str,
    output: Path | None,
    as_json: bool,
) -> None:
    """Create a publish-ready metadata bundle for creator outputs."""
    try:
        script_text = None
        if script_file or text:
            script_text = resolve_script_text(script_file=script_file, text=text)
        bundle = build_publish_bundle(
            platform_name=platform_name,
            source_name=source_name,
            script_text=script_text,
        )
        markdown = bundle_to_markdown(bundle) if output_format == "markdown" and not as_json else None
        _emit_payload(bundle.to_dict(), as_json=as_json, output=output, markdown=markdown)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command("generate")
@click.argument("script_input", required=False)
@click.option("--storyboard", "storyboard_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Submit an existing storyboard JSON file.")
@click.option("--script-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Read script text from a file.")
@click.option("--text", type=str, default=None, help="Inline script text.")
@click.option("--platform", "platform_name", type=str, default="tiktok", show_default=True, help="Target platform preset.")
@click.option("--provider", type=str, default="mock", show_default=True, help="Generation provider.")
@click.option("--hook-style", type=click.Choice(["curiosity", "authority", "explainer"]), default="curiosity", show_default=True)
@click.option("--shots", type=int, default=None, help="Maximum number of storyboard shots.")
@click.option("--shot-seconds", type=float, default=None, help="Force each shot duration.")
@click.option("--queue-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Generation queue directory.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Fetched asset output directory.")
@click.option("--wait", "wait_for_completion", is_flag=True, help="Wait for provider completion before returning.")
@click.option("--fetch", "fetch_outputs", is_flag=True, help="Fetch generated assets after submission.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def generate_cmd(
    script_input: str | None,
    storyboard_path: Path | None,
    script_file: Path | None,
    text: str | None,
    platform_name: str,
    provider: str,
    hook_style: str,
    shots: int | None,
    shot_seconds: float | None,
    queue_dir: Path | None,
    output_dir: Path | None,
    wait_for_completion: bool,
    fetch_outputs: bool,
    as_json: bool,
) -> None:
    """Submit AI-video generation jobs from a storyboard or raw script."""
    try:
        if storyboard_path:
            storyboard = load_storyboard(storyboard_path)
        else:
            script_text = resolve_script_text(script_input=script_input, script_file=script_file, text=text)
            storyboard = build_storyboard(
                script_text,
                platform_name=platform_name,
                provider=provider,
                hook_style=hook_style,
                shots=shots,
                shot_seconds=shot_seconds,
            ).to_dict()

        job = submit_job(storyboard, provider=provider, queue_dir=queue_dir, output_dir=output_dir)
        if wait_for_completion or fetch_outputs:
            job = wait_for_job(job["job_id"], queue_dir=queue_dir)
        if fetch_outputs:
            job = fetch_job(job["job_id"], queue_dir=queue_dir, output_dir=output_dir)

        _emit_payload(job, as_json=as_json)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.group("queue")
def queue_group() -> None:
    """Manage queued AI video generation jobs."""


@queue_group.command("submit")
@click.argument("storyboard_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--provider", type=str, default="mock", show_default=True, help="Generation provider.")
@click.option("--queue-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Generation queue directory.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Fetched asset output directory.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def queue_submit_cmd(storyboard_path: Path, provider: str, queue_dir: Path | None, output_dir: Path | None, as_json: bool) -> None:
    """Submit a storyboard JSON file to the generation queue."""
    try:
        storyboard = load_storyboard(storyboard_path)
        job = submit_job(storyboard, provider=provider, queue_dir=queue_dir, output_dir=output_dir)
        _emit_payload(job, as_json=as_json)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@queue_group.command("list")
@click.option("--queue-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Generation queue directory.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def queue_list_cmd(queue_dir: Path | None, as_json: bool) -> None:
    """List generation queue jobs."""
    try:
        jobs = list_jobs(queue_dir=queue_dir)
        if as_json:
            _emit_payload({"jobs": jobs}, as_json=True)
            return

        table = Table(title="Generation Jobs")
        table.add_column("Job ID", style="cyan")
        table.add_column("Provider", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Created", style="magenta")
        for job in jobs:
            table.add_row(job["job_id"], job["provider"], job["status"], job["created_at"])
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@queue_group.command("status")
@click.argument("job_id")
@click.option("--queue-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Generation queue directory.")
@click.option("--refresh", "refresh_state", is_flag=True, help="Refresh provider state before showing the job.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def queue_status_cmd(job_id: str, queue_dir: Path | None, refresh_state: bool, as_json: bool) -> None:
    """Show one generation job."""
    try:
        job = get_job(job_id, queue_dir=queue_dir, refresh=refresh_state)
        _emit_payload(job, as_json=as_json)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@queue_group.command("wait")
@click.argument("job_id")
@click.option("--queue-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Generation queue directory.")
@click.option("--timeout", "timeout_seconds", type=float, default=30.0, show_default=True, help="Maximum wait time in seconds.")
@click.option("--poll", "poll_seconds", type=float, default=1.0, show_default=True, help="Polling interval in seconds.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def queue_wait_cmd(job_id: str, queue_dir: Path | None, timeout_seconds: float, poll_seconds: float, as_json: bool) -> None:
    """Wait until a generation job completes."""
    try:
        job = wait_for_job(job_id, queue_dir=queue_dir, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds)
        _emit_payload(job, as_json=as_json)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@queue_group.command("fetch")
@click.argument("job_id")
@click.option("--queue-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Generation queue directory.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Fetched asset output directory.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def queue_fetch_cmd(job_id: str, queue_dir: Path | None, output_dir: Path | None, as_json: bool) -> None:
    """Fetch local files for a completed generation job."""
    try:
        job = fetch_job(job_id, queue_dir=queue_dir, output_dir=output_dir)
        _emit_payload(job, as_json=as_json)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.group("agent")
def agent_group() -> None:
    """Agent-framework-friendly declarative workflows."""


@agent_group.command("template")
@click.argument("workflow", type=click.Choice(["viralize", "storyboard", "generate", "package", "creator-brief"]), default="viralize")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write the template JSON to a file.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def agent_template_cmd(workflow: str, output: Path | None, as_json: bool) -> None:
    """Emit a starter job spec for agent frameworks."""
    try:
        payload = agent_template(workflow)
        _emit_payload(payload, as_json=True if as_json or output else True, output=output)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@agent_group.command("run")
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Force planning-only execution.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def agent_run_cmd(spec_file: Path, dry_run: bool, as_json: bool) -> None:
    """Run a declarative creator workflow spec."""
    try:
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        result = run_agent_job(spec, dry_run_override=True if dry_run else None)
        _emit_payload(result, as_json=True if as_json or True else False)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.group("creator")
def creator_group() -> None:
    """Creator recommendation helpers for agents and workflows."""


@creator_group.command("brief")
@click.argument("source_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--script-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Read script text from a file.")
@click.option("--text", type=str, default=None, help="Inline script text.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def creator_brief_cmd(source_file: Path, script_file: Path | None, text: str | None, as_json: bool) -> None:
    """Recommend the best next creator workflow for an asset."""
    try:
        script_text = None
        if script_file or text:
            script_text = resolve_script_text(script_file=script_file, text=text)
        brief = build_creator_brief(source_file, script_text=script_text)
        _emit_payload(brief.to_dict(), as_json=as_json)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()

@cli.command("sources")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def sources_cmd(project_dir: Path, as_json: bool) -> None:
    """List project sources."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        if as_json:
            console.print_json(json.dumps(_manifest_json(manifest).get("sources", {})))
            return

        table = Table(title=f"Sources ({manifest.name})")
        table.add_column("Source ID", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Duration", style="yellow")
        table.add_column("Resolution", style="magenta")
        table.add_column("Path", style="dim")

        for sid, info in manifest.sources.items():
            res_str = f"{info.width}x{info.height}" if info.width and info.height else "N/A"
            dur_str = f"{info.duration_seconds:.2f}s" if info.duration_seconds else "N/A"
            table.add_row(sid, info.media_type, dur_str, res_str, str(info.file_path))

        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command("make")
@click.argument("source_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--platform", "platform_name", type=str, default=None, help="Target platform preset.")
@click.option("--recipe", "recipe_name", type=str, default=None, help="Optional workflow recipe.")
@click.option("--captions", type=click.Choice(["off", "clean", "social"]), default=None, help="Caption mode.")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="final", show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None)
@click.option("--remove-silence/--keep-silence", default=None, help="Trim dead air inside the output.")
@click.option("--silence-min-duration", type=float, default=None, help="Minimum silence duration to cut.")
@click.option("--dry-run", is_flag=True, help="Plan the output without rendering.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def make_cmd(
    source_file: Path,
    platform_name: str | None,
    recipe_name: str | None,
    captions: str | None,
    quality: str,
    output_dir: Path | None,
    remove_silence: bool | None,
    silence_min_duration: float | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Create one ready-to-post platform-specific output."""
    try:
        plan = build_plan(
            "make",
            source_file,
            platform_name=platform_name,
            recipe_name=recipe_name,
            captions=captions,
            quality=quality,
            output_dir=output_dir,
            remove_silence=remove_silence,
            silence_min_duration=silence_min_duration,
        )
        _print_factory_plan(plan, as_json)
        if dry_run:
            return
        rendered = execute_plan(plan)
        for path in rendered:
            console.print(f"[bold green]Created:[/bold green] {path}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command("repurpose")
@click.argument("source_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--platform", "platform_name", type=str, default=None, help="Target platform preset.")
@click.option("--recipe", "recipe_name", type=str, default=None, help="Optional workflow recipe.")
@click.option("--captions", type=click.Choice(["off", "clean", "social"]), default=None, help="Caption mode.")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="final", show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None)
@click.option("--clips", type=int, default=None, help="Number of output clips to target.")
@click.option("--min-clip", "min_clip_seconds", type=float, default=None, help="Minimum clip duration.")
@click.option("--max-clip", "max_clip_seconds", type=float, default=None, help="Maximum clip duration.")
@click.option("--scene-threshold", type=float, default=None, help="Scene detection sensitivity.")
@click.option("--remove-silence/--keep-silence", default=None, help="Trim dead air inside selected clips.")
@click.option("--silence-min-duration", type=float, default=None, help="Minimum silence duration to cut.")
@click.option("--dry-run", is_flag=True, help="Plan the outputs without rendering.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def repurpose_cmd(
    source_file: Path,
    platform_name: str | None,
    recipe_name: str | None,
    captions: str | None,
    quality: str,
    output_dir: Path | None,
    clips: int | None,
    min_clip_seconds: float | None,
    max_clip_seconds: float | None,
    scene_threshold: float | None,
    remove_silence: bool | None,
    silence_min_duration: float | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Turn one long video into multiple short-form clips."""
    try:
        plan = build_plan(
            "repurpose",
            source_file,
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
        _print_factory_plan(plan, as_json)
        if dry_run:
            return
        rendered = execute_plan(plan)
        for path in rendered:
            console.print(f"[bold green]Created:[/bold green] {path}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command("preview")
@click.argument("source_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--mode", type=click.Choice(["make", "repurpose"]), default="repurpose", show_default=True)
@click.option("--platform", "platform_name", type=str, default=None, help="Target platform preset.")
@click.option("--recipe", "recipe_name", type=str, default=None, help="Optional workflow recipe.")
@click.option("--captions", type=click.Choice(["off", "clean", "social"]), default=None, help="Caption mode.")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="final", show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None)
@click.option("--clips", type=int, default=None, help="Number of output clips to target.")
@click.option("--min-clip", "min_clip_seconds", type=float, default=None, help="Minimum clip duration.")
@click.option("--max-clip", "max_clip_seconds", type=float, default=None, help="Maximum clip duration.")
@click.option("--scene-threshold", type=float, default=None, help="Scene detection sensitivity.")
@click.option("--remove-silence/--keep-silence", default=None, help="Trim dead air inside selected clips.")
@click.option("--silence-min-duration", type=float, default=None, help="Minimum silence duration to cut.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def preview_cmd(
    source_file: Path,
    mode: str,
    platform_name: str | None,
    recipe_name: str | None,
    captions: str | None,
    quality: str,
    output_dir: Path | None,
    clips: int | None,
    min_clip_seconds: float | None,
    max_clip_seconds: float | None,
    scene_threshold: float | None,
    remove_silence: bool | None,
    silence_min_duration: float | None,
    as_json: bool,
) -> None:
    """Show the editing plan before rendering."""
    try:
        plan = build_plan(
            mode,
            source_file,
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
        _print_factory_plan(plan, as_json)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command("batch")
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--mode", type=click.Choice(["make", "repurpose"]), default="repurpose", show_default=True)
@click.option("--platform", "platform_name", type=str, default=None, help="Target platform preset.")
@click.option("--recipe", "recipe_name", type=str, default=None, help="Optional workflow recipe.")
@click.option("--captions", type=click.Choice(["off", "clean", "social"]), default=None, help="Caption mode.")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="final", show_default=True)
@click.option("--glob", "glob_pattern", type=str, default="*.mp4", show_default=True, help="Input glob.")
@click.option("--limit", type=int, default=None, help="Maximum number of source files to process.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None)
@click.option("--clips", type=int, default=None, help="Number of output clips to target.")
@click.option("--min-clip", "min_clip_seconds", type=float, default=None, help="Minimum clip duration.")
@click.option("--max-clip", "max_clip_seconds", type=float, default=None, help="Maximum clip duration.")
@click.option("--scene-threshold", type=float, default=None, help="Scene detection sensitivity.")
@click.option("--remove-silence/--keep-silence", default=None, help="Trim dead air inside selected clips.")
@click.option("--silence-min-duration", type=float, default=None, help="Minimum silence duration to cut.")
@click.option("--dry-run", is_flag=True, help="Plan outputs without rendering.")
def batch_cmd(
    input_dir: Path,
    mode: str,
    platform_name: str | None,
    recipe_name: str | None,
    captions: str | None,
    quality: str,
    glob_pattern: str,
    limit: int | None,
    output_dir: Path | None,
    clips: int | None,
    min_clip_seconds: float | None,
    max_clip_seconds: float | None,
    scene_threshold: float | None,
    remove_silence: bool | None,
    silence_min_duration: float | None,
    dry_run: bool,
) -> None:
    """Apply the same factory workflow across a folder of source videos."""
    try:
        files = sorted(input_dir.glob(glob_pattern))
        if limit is not None:
            files = files[:limit]
        if not files:
            console.print("[yellow]No matching files found.[/yellow]")
            return

        rendered_total = 0
        for source_file in files:
            if not source_file.is_file():
                continue
            plan = build_plan(
                mode,
                source_file,
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
            console.print(f"\n[bold cyan]{source_file.name}[/bold cyan]")
            _print_factory_plan(plan, as_json=False)
            if not dry_run:
                rendered_total += len(execute_plan(plan))

        if dry_run:
            console.print(f"[bold green]Planned {len(files)} source file(s).[/bold green]")
        else:
            console.print(f"[bold green]Created {rendered_total} output file(s).[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command("viralize")
@click.argument("source_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--platform", "platform_name", type=str, default=None, help="Target platform preset.")
@click.option("--recipe", "recipe_name", type=str, default="podcast", show_default=True, help="Workflow recipe.")
@click.option("--captions", type=click.Choice(["off", "clean", "social"]), default=None, help="Caption mode.")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="final", show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None)
@click.option("--clips", type=int, default=None, help="Number of output clips to target.")
@click.option("--min-clip", "min_clip_seconds", type=float, default=None, help="Minimum clip duration.")
@click.option("--max-clip", "max_clip_seconds", type=float, default=None, help="Maximum clip duration.")
@click.option("--scene-threshold", type=float, default=None, help="Scene detection sensitivity.")
@click.option("--remove-silence/--keep-silence", default=None, help="Trim dead air inside selected clips.")
@click.option("--silence-min-duration", type=float, default=None, help="Minimum silence duration to cut.")
@click.option("--script-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Read script text from a file.")
@click.option("--text", type=str, default=None, help="Inline script text.")
@click.option("--render/--dry-run", default=False, help="Render outputs instead of planning only.")
@click.option("--package-output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Write bundle JSON or Markdown to a file.")
@click.option("--format", "output_format", type=click.Choice(["json", "markdown"]), default="json", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def viralize_cmd(
    source_file: Path,
    platform_name: str | None,
    recipe_name: str | None,
    captions: str | None,
    quality: str,
    output_dir: Path | None,
    clips: int | None,
    min_clip_seconds: float | None,
    max_clip_seconds: float | None,
    scene_threshold: float | None,
    remove_silence: bool | None,
    silence_min_duration: float | None,
    script_file: Path | None,
    text: str | None,
    render: bool,
    package_output: Path | None,
    output_format: str,
    as_json: bool,
) -> None:
    """Plan or render a full short-form content bundle from one source."""
    try:
        script_text = None
        if script_file or text:
            script_text = resolve_script_text(script_file=script_file, text=text)

        plan, bundle, rendered_paths = viralize(
            source_file,
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
            script_text=script_text,
            render=render,
        )

        if as_json:
            payload = {
                "plan": plan.to_dict(),
                "package": bundle.to_dict(),
                "rendered_paths": [str(path) for path in rendered_paths],
            }
            _emit_payload(payload, as_json=True, output=package_output)
            return

        _print_factory_plan(plan, as_json=False)
        markdown = bundle_to_markdown(bundle) if output_format == "markdown" else None
        _emit_payload(bundle.to_dict(), as_json=False, output=package_output, markdown=markdown)
        if render:
            for path in rendered_paths:
                console.print(f"[bold green]Created:[/bold green] {path}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()



@cli.command("compare-sbs")
@click.argument("source_file", type=click.Path(dir_okay=False, path_type=Path), required=False, default=None)
@click.option("--pairs", "pairs_manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True, help="YAML file describing before/after clip pairs.")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None, help="Destination video file.")
@click.option("--layout", type=click.Choice(["horizontal", "vertical"]), default="horizontal", show_default=True, help="Side-by-side orientation.")
@click.option("--freeze-shorter", "freeze_mode", type=click.Choice(["last-frame", "black", "loop", "none"]), default="last-frame", show_default=True, help="What to do when one side is shorter.")
@click.option("--audio-mode", type=click.Choice(["mute", "before", "after", "mix"]), default="mute", show_default=True, help="Audio from before, after, mixed, or muted.")
@click.option("--mute", "force_mute", is_flag=True, default=False, help="Shorthand: mute all audio (same as --audio-mode mute).")
@click.option("--platform", "platform_name", type=str, default=None, help="Platform preset for canvas sizing (optional).")
@click.option("--canvas-width", type=int, default=1920, show_default=True, help="Output canvas width in pixels.")
@click.option("--canvas-height", type=int, default=1080, show_default=True, help="Output canvas height in pixels.")
@click.option("--report-format", type=click.Choice(["markdown", "csv", "none"]), default="none", show_default=True, help="Emit a coverage report.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON result.")
def compare_sbs_cmd(
    source_file: Path | None,
    pairs_manifest: Path,
    output: Path | None,
    layout: str,
    freeze_mode: str,
    audio_mode: str,
    force_mute: bool,
    platform_name: str | None,
    canvas_width: int,
    canvas_height: int,
    report_format: str,
    as_json: bool,
) -> None:
    """Build a side-by-side before/after comparison reel from a pairs manifest.

    Extracts paired subclips, composites them side-by-side (or top/bottom),
    freezes the shorter side, and concatenates all pairs into one video.

    \b
    Examples:
      graphcut compare-sbs source.mp4 --pairs pairs.yaml --output comparison.mp4
      graphcut compare-sbs --pairs pairs.yaml --output out.mp4 --layout vertical --freeze-shorter black
      graphcut compare-sbs source.mp4 --pairs pairs.yaml --mute --report-format markdown --json
    """
    try:
        effective_audio = "mute" if force_mute else audio_mode

        if source_file is not None and not source_file.exists():
            raise click.BadParameter(f"Source file not found: {source_file}", param_hint="source_file")

        out_path = output or Path("comparison.mp4")

        result = run_compare_sbs(
            primary_source=source_file,
            pairs_manifest=pairs_manifest,
            output=out_path,
            layout=layout,  # type: ignore[arg-type]
            freeze_mode=freeze_mode,  # type: ignore[arg-type]
            audio_mode=effective_audio,  # type: ignore[arg-type]
            platform_name=platform_name,
            canvas_w=canvas_width,
            canvas_h=canvas_height,
        )

        payload = result.to_dict()

        if as_json:
            console.print_json(json.dumps(payload))
        else:
            # Human-readable summary table
            table = Table(title="compare-sbs — Pair Summary")
            table.add_column("Pair ID", style="cyan")
            table.add_column("Title", style="white")
            table.add_column("Before (s)", style="green", justify="right")
            table.add_column("After (s)", style="blue", justify="right")
            table.add_column("Output (s)", style="yellow", justify="right")
            table.add_column("Freeze side", style="magenta")
            table.add_column("Freeze (s)", style="dim", justify="right")

            for p in result.pairs:
                table.add_row(
                    p.id,
                    p.title,
                    f"{p.before_duration:.1f}",
                    f"{p.after_duration:.1f}",
                    f"{p.output_duration:.1f}",
                    p.freeze.side,
                    f"{p.freeze.duration:.1f}",
                )

            console.print(table)
            console.print(
                f"[bold green]Output:[/bold green] {out_path}  "
                f"[bold]Total:[/bold] {result.total_output_duration:.1f}s"
            )

            for w in result.warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")

        if report_format == "markdown":
            console.print(result.to_markdown_table())
        elif report_format == "csv":
            lines = ["pair_id,title,before_s,after_s,output_s,freeze_side,freeze_s"]
            for p in result.pairs:
                lines.append(
                    f"{p.id},{p.title},{p.before_duration:.3f},{p.after_duration:.3f},"
                    f"{p.output_duration:.3f},{p.freeze.side},{p.freeze.duration:.3f}"
                )
            console.print("\n".join(lines))

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.group()
def timeline() -> None:
    """Timeline editing commands (agent-friendly)."""


@timeline.command("list")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def timeline_list(project_dir: Path, as_json: bool) -> None:
    """List timeline clips with trims."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        if as_json:
            console.print_json(json.dumps(_manifest_json(manifest).get("clip_order", [])))
            return

        table = Table(title=f"Timeline ({manifest.name})")
        table.add_column("#", style="dim", justify="right")
        table.add_column("Source", style="cyan")
        table.add_column("In", style="green", justify="right")
        table.add_column("Out", style="green", justify="right")
        table.add_column("Dur", style="yellow", justify="right")
        table.add_column("Transition", style="magenta")

        for i, clip in enumerate(manifest.clip_order, start=1):
            info = manifest.sources.get(clip.source_id)
            full = info.duration_seconds if info else 0.0
            t0 = clip.trim_start if clip.trim_start is not None else 0.0
            t1 = clip.trim_end if clip.trim_end is not None else full
            dur = max(0.0, t1 - t0)
            table.add_row(
                str(i),
                clip.source_id,
                f"{t0:.2f}",
                f"{t1:.2f}" if t1 else "0.00",
                f"{dur:.2f}",
                f"{clip.transition} ({clip.transition_duration:.2f}s)",
            )

        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@timeline.command("add")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("source_id")
@click.option("--in", "trim_in", type=float, default=None, help="Trim start (seconds).")
@click.option("--out", "trim_out", type=float, default=None, help="Trim end (seconds).")
@click.option("--range", "ranges", multiple=True, help="Add multiple segments as START:END (repeatable).")
@click.option(
    "--transition",
    "transition_name",
    type=click.Choice(tuple(AVAILABLE_TRANSITIONS.keys()), case_sensitive=False),
    default="cut",
    show_default=True,
    help="Outgoing transition to use after the inserted segment(s).",
)
@click.option("--transition-duration", type=float, default=None, help="Transition overlap duration in seconds.")
@click.option("--pos", type=int, default=None, help="Insert position (1-based). Default: append.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def timeline_add(
    project_dir: Path,
    source_id: str,
    trim_in: float | None,
    trim_out: float | None,
    ranges: tuple[str, ...],
    transition_name: str,
    transition_duration: float | None,
    pos: int | None,
    as_json: bool,
) -> None:
    """Add one or more trimmed segments to the timeline."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        if source_id not in manifest.sources:
            raise click.BadParameter(f"Unknown source_id: {source_id}")

        info = manifest.sources[source_id]
        full = info.duration_seconds

        segments = _parse_ranges(ranges) if ranges else []
        if not segments:
            t0 = 0.0 if trim_in is None else float(trim_in)
            t1 = full if trim_out is None else float(trim_out)
            if t0 < 0 or t1 < 0:
                raise click.BadParameter("--in/--out must be >= 0.")
            if t1 <= t0:
                raise click.BadParameter("--out must be > --in.")
            segments = [(t0, t1)]

        insert_at = len(manifest.clip_order) if pos is None else max(0, min(len(manifest.clip_order), pos - 1))
        transition = _normalize_transition(transition_name)
        duration_value = (
            AVAILABLE_TRANSITIONS[transition]["default_duration"]
            if transition_duration is None
            else max(0.0, float(transition_duration))
        )
        for (t0, t1) in segments:
            if full and t1 > full:
                t1 = full
            if t0 > t1:
                continue
            manifest.clip_order.insert(
                insert_at,
                ClipRef(
                    source_id=source_id,
                    trim_start=t0,
                    trim_end=t1,
                    transition=transition,  # type: ignore[arg-type]
                    transition_duration=duration_value,
                ),
            )
            insert_at += 1

        ProjectManager.save_project(manifest, project_dir)
        if as_json:
            console.print_json(json.dumps(_manifest_json(manifest).get("clip_order", [])))
        else:
            console.print(f"[bold green]Added {len(segments)} segment(s) for[/bold green] {source_id}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@timeline.command("trim")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("index", type=int)
@click.option("--in", "trim_in", type=float, default=None, help="Trim start (seconds).")
@click.option("--out", "trim_out", type=float, default=None, help="Trim end (seconds).")
@click.option("--reset", is_flag=True, help="Reset trim to full duration.")
def timeline_trim(project_dir: Path, index: int, trim_in: float | None, trim_out: float | None, reset: bool) -> None:
    """Update trims for a timeline clip (index is 1-based)."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        i = index - 1
        if i < 0 or i >= len(manifest.clip_order):
            raise click.BadParameter("Invalid clip index.")

        clip = manifest.clip_order[i]
        info = manifest.sources.get(clip.source_id)
        full = info.duration_seconds if info else 0.0

        if reset:
            clip.trim_start = None
            clip.trim_end = None
        else:
            t0 = (clip.trim_start if clip.trim_start is not None else 0.0) if trim_in is None else float(trim_in)
            t1 = (clip.trim_end if clip.trim_end is not None else full) if trim_out is None else float(trim_out)
            if t0 < 0 or t1 < 0:
                raise click.BadParameter("--in/--out must be >= 0.")
            if t1 <= t0:
                raise click.BadParameter("--out must be > --in.")
            clip.trim_start = t0
            clip.trim_end = t1

        manifest.clip_order[i] = clip
        ProjectManager.save_project(manifest, project_dir)
        console.print(f"[bold green]Trim updated for clip[/bold green] #{index}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@timeline.command("split")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("index", type=int)
@click.argument("time", type=float)
def timeline_split(project_dir: Path, index: int, time: float) -> None:
    """Split a clip into two at TIME (seconds, in source timeline; index is 1-based)."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        i = index - 1
        if i < 0 or i >= len(manifest.clip_order):
            raise click.BadParameter("Invalid clip index.")

        clip = manifest.clip_order[i]
        info = manifest.sources.get(clip.source_id)
        if not info:
            raise click.BadParameter("Missing source info for clip.")

        t0 = clip.trim_start if clip.trim_start is not None else 0.0
        t1 = clip.trim_end if clip.trim_end is not None else info.duration_seconds
        t = float(time)
        if t <= t0 or t >= t1:
            raise click.BadParameter("Split time must be within the current clip trim range.")

        left = ClipRef(**clip.model_dump())
        right = ClipRef(**clip.model_dump())
        left.trim_end = t
        right.trim_start = t
        right.trim_end = clip.trim_end

        manifest.clip_order[i] = left
        manifest.clip_order.insert(i + 1, right)
        ProjectManager.save_project(manifest, project_dir)
        console.print(f"[bold green]Split clip[/bold green] #{index} at {t:.2f}s")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@timeline.command("move")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("from_index", type=int)
@click.argument("to_index", type=int)
def timeline_move(project_dir: Path, from_index: int, to_index: int) -> None:
    """Move a clip (indices are 1-based)."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        n = len(manifest.clip_order)
        src = from_index - 1
        dst = to_index - 1
        if src < 0 or src >= n or dst < 0 or dst >= n:
            raise click.BadParameter("Invalid indices.")
        clip = manifest.clip_order.pop(src)
        manifest.clip_order.insert(dst, clip)
        ProjectManager.save_project(manifest, project_dir)
        console.print(f"[bold green]Moved clip[/bold green] #{from_index} -> #{to_index}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@timeline.command("delete")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("index", type=int)
def timeline_delete(project_dir: Path, index: int) -> None:
    """Delete a clip from the timeline (index is 1-based)."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        i = index - 1
        if i < 0 or i >= len(manifest.clip_order):
            raise click.BadParameter("Invalid clip index.")
        manifest.clip_order.pop(i)
        ProjectManager.save_project(manifest, project_dir)
        console.print(f"[bold green]Deleted clip[/bold green] #{index}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@timeline.command("clear")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
def timeline_clear(project_dir: Path) -> None:
    """Clear the timeline."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        manifest.clip_order = []
        ProjectManager.save_project(manifest, project_dir)
        console.print("[bold green]Cleared timeline.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@timeline.command("transition")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("index", type=int)
@click.argument("transition_name", type=click.Choice(tuple(AVAILABLE_TRANSITIONS.keys()), case_sensitive=False))
@click.option("--duration", type=float, default=None, help="Transition overlap duration in seconds.")
def timeline_transition(project_dir: Path, index: int, transition_name: str, duration: float | None) -> None:
    """Set the outgoing transition for a clip (index is 1-based)."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        i = index - 1
        if i < 0 or i >= len(manifest.clip_order):
            raise click.BadParameter("Invalid clip index.")

        transition = _normalize_transition(transition_name)
        clip = manifest.clip_order[i]
        clip.transition = transition  # type: ignore[assignment]
        clip.transition_duration = (
            AVAILABLE_TRANSITIONS[transition]["default_duration"]
            if duration is None
            else max(0.0, float(duration))
        )
        manifest.clip_order[i] = clip
        ProjectManager.save_project(manifest, project_dir)
        console.print(
            f"[bold green]Updated transition for clip[/bold green] #{index} -> "
            f"{AVAILABLE_TRANSITIONS[transition]['label']} ({clip.transition_duration:.2f}s)"
        )
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.group("effects")
def effects_group() -> None:
    """List and inspect available timeline effects/transitions."""


@effects_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def effects_list(as_json: bool) -> None:
    """List built-in transitions available to the GUI and CLI."""
    if as_json:
        console.print_json(json.dumps(AVAILABLE_TRANSITIONS))
        return

    table = Table(title="Timeline Effects")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Default Duration", style="yellow")
    table.add_column("Description", style="magenta")
    for effect_id, meta in AVAILABLE_TRANSITIONS.items():
        table.add_row(
            effect_id,
            str(meta["label"]),
            f"{float(meta['default_duration']):.2f}s",
            str(meta["description"]),
        )
    console.print(table)


@cli.command("roles")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--narration", default=None, help="Source ID to use as narration.")
@click.option("--music", default=None, help="Source ID to use as music.")
def roles_cmd(project_dir: Path, narration: str | None, music: str | None) -> None:
    """Set narration/music roles for audio mixing."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        if narration is not None and narration != "" and narration not in manifest.sources:
            raise click.BadParameter(f"Unknown narration source: {narration}")
        if music is not None and music != "" and music not in manifest.sources:
            raise click.BadParameter(f"Unknown music source: {music}")
        manifest.narration = narration or None
        manifest.music = music or None
        ProjectManager.save_project(manifest, project_dir)
        console.print("[bold green]Roles updated.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.group("scene")
def scene_group() -> None:
    """Scene snapshot commands (OBS-like)."""


@scene_group.command("list")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def scene_list(project_dir: Path, as_json: bool) -> None:
    """List saved scenes."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        if as_json:
            console.print_json(json.dumps({"active_scene": manifest.active_scene, "scenes": _manifest_json(manifest).get("scenes", {})}))
            return
        table = Table(title=f"Scenes ({manifest.name})")
        table.add_column("Name", style="cyan")
        table.add_column("Active", style="green")
        table.add_column("Webcam", style="magenta")
        table.add_column("Narration", style="yellow")
        table.add_column("Music", style="yellow")
        table.add_column("Captions", style="blue")
        for name, sc in manifest.scenes.items():
            table.add_row(
                name,
                "yes" if manifest.active_scene == name else "",
                sc.webcam.source_id if sc.webcam else "off",
                sc.narration or "",
                sc.music or "",
                sc.caption_style.style if sc.caption_style else "",
            )
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@scene_group.command("save")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("name")
def scene_save(project_dir: Path, name: str) -> None:
    """Save current webcam/audio/captions/roles as a named scene."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        nm = name.strip()
        if not nm:
            raise click.BadParameter("Scene name cannot be empty.")
        manifest.scenes[nm] = SceneConfig(
            webcam=manifest.webcam,
            audio_mix=manifest.audio_mix,
            caption_style=manifest.caption_style,
            narration=manifest.narration,
            music=manifest.music,
        )
        if manifest.active_scene is None:
            manifest.active_scene = nm
        ProjectManager.save_project(manifest, project_dir)
        console.print(f"[bold green]Saved scene:[/bold green] {nm}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@scene_group.command("activate")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("name")
def scene_activate(project_dir: Path, name: str) -> None:
    """Activate a scene (applies webcam/audio/captions/roles)."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        nm = name.strip()
        if nm not in manifest.scenes:
            raise click.BadParameter(f"Scene not found: {nm}")
        sc = manifest.scenes[nm]
        manifest.active_scene = nm
        manifest.webcam = sc.webcam
        manifest.audio_mix = sc.audio_mix
        manifest.caption_style = sc.caption_style
        manifest.narration = sc.narration
        manifest.music = sc.music
        ProjectManager.save_project(manifest, project_dir)
        console.print(f"[bold green]Activated scene:[/bold green] {nm}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@scene_group.command("delete")
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("name")
def scene_delete(project_dir: Path, name: str) -> None:
    """Delete a saved scene."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        nm = name.strip()
        if nm not in manifest.scenes:
            raise click.BadParameter(f"Scene not found: {nm}")
        del manifest.scenes[nm]
        if manifest.active_scene == nm:
            manifest.active_scene = None
        ProjectManager.save_project(manifest, project_dir)
        console.print(f"[bold green]Deleted scene:[/bold green] {nm}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


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
@click.option("--video-codec", type=str, help="Preferred FFmpeg video encoder, e.g. libx264 or h264_nvenc.")
def render_preview(project_dir: Path, video_codec: str | None) -> None:
    """Render a fast 480p preview of the project."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        renderer = Renderer()
        
        console.print(f"Rendering preview for '{manifest.name}'...")
        output_path = renderer.render_preview(
            manifest,
            project_dir,
            preferred_video_encoder=video_codec,
        )
        console.print(f"[bold green]Success![/bold green] Preview rendered to: {output_path}")
        
    except Exception as e:
        console.print(f"[bold red]Render failed:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default="final", help="Render quality.")
@click.option("--output", type=click.Path(file_okay=True, dir_okay=False, path_type=Path), help="Specific output filename.")
@click.option("--preset", type=str, help="Specific preset name to render (e.g. youtube, shorts, square).")
@click.option("--all-presets", is_flag=True, help="Render to all defined presets.")
@click.option("--video-codec", type=str, help="Preferred FFmpeg video encoder, e.g. libx264 or h264_nvenc.")
def render(
    project_dir: Path,
    quality: str,
    output: Path | None,
    preset: str | None,
    all_presets: bool,
    video_codec: str | None,
) -> None:
    """Render the project to a video file."""
    # We delegate to export under the hood, but retain `render` for legacy tests.
    try:
        manifest = ProjectManager.load_project(project_dir)
        exporter = Exporter()
        out_path = output.parent if output else (project_dir / manifest.build_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("ETA: {task.fields[eta]}"),
            TextColumn("Speed: {task.fields[speed]}x"),
            console=console
        ) as progress:
            task = progress.add_task(f"Rendering {manifest.name}", total=100.0, speed="0.0", eta="--:--")
            
            def cb(pct: float, speed: str, eta: str):
                progress.update(task, completed=pct, speed=speed, eta=eta)
                
            if all_presets:
                exporter.export_all(
                    manifest,
                    out_path,
                    progress_callback=cb,
                    preferred_video_encoder=video_codec,
                )
            elif preset:
                p = next((x for x in manifest.export_presets if x.name.lower() == preset.lower()), None)
                if not p:
                    raise click.BadParameter(f"Preset {preset} not found.")
                # apply quality
                p.quality = quality
                exporter.export(
                    manifest,
                    p,
                    out_path,
                    progress_callback=cb,
                    preferred_video_encoder=video_codec,
                )
            else:
                # Fallback to direct renderer via default configuration 
                # (1080p native bounds, final quality) just using renderer directly.
                renderer = Renderer()
                renderer.render(
                    manifest,
                    output or (out_path / f"{quality}.mp4"),
                    quality=quality,
                    progress_callback=cb,
                    preferred_video_encoder=video_codec,
                )
                
    except Exception as e:
        console.print(f"[bold red]Render failed:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--preset", type=str, help="Specific preset name to render (e.g. youtube, shorts).")
@click.option("--all", "export_all", is_flag=True, help="Render to all defined presets.")
@click.option("--quality", type=click.Choice(["draft", "preview", "final"]), default=None, help="Override preset quality.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), help="Output directory.")
@click.option("--video-codec", type=str, help="Preferred FFmpeg video encoder, e.g. libx264 or h264_nvenc.")
def export(
    project_dir: Path,
    preset: str | None,
    export_all: bool,
    quality: str | None,
    output_dir: Path | None,
    video_codec: str | None,
) -> None:
    """Export the project across social formats with HW acceleration and progress reporting."""
    try:
        manifest = ProjectManager.load_project(project_dir)
        exporter = Exporter()
        out_path = output_dir or (project_dir / manifest.build_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        # Override qualities if set
        if quality:
            for p in manifest.export_presets:
                p.quality = quality
                
        targets = []
        if export_all:
            targets = manifest.export_presets
        elif preset:
            p = next((x for x in manifest.export_presets if x.name.lower() == preset.lower()), None)
            if not p:
                raise click.BadParameter(f"Preset {preset} not found. Available: {[x.name for x in manifest.export_presets]}")
            targets.append(p)
        else:
            targets = [manifest.export_presets[0]] # Default to first (YouTube usually)

        for target in targets:
            console.print(f"\n[bold cyan]Exporting {target.name}[/bold cyan] ({target.width}x{target.height}, {target.quality})")
            
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("ETA: {task.fields[eta]}"),
                TextColumn("Speed: {task.fields[speed]}x"),
                console=console
            ) as progress:
                
                ptask = progress.add_task("Processing...", total=100.0, speed="0.0", eta="--:--")
                
                def pcb(pct: float, spd: str, rem: str):
                    progress.update(ptask, completed=pct, speed=spd, eta=rem)
                    
                final_path = exporter.export(
                    manifest,
                    target,
                    out_path,
                    progress_callback=pcb,
                    preferred_video_encoder=video_codec,
                )

            console.print(f"[bold green]✓ Done:[/bold green] {final_path}")
            
    except Exception as e:
        console.print(f"[bold red]Export failed:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--model", default="medium", help="Whisper model name (tiny/base/small/medium/large-v3).")
@click.option("--language", default=None, help="Language code (auto-detect if omitted).")
def transcribe(project_dir: Path, model: str, language: str | None) -> None:
    """Transcribe all source audio in a project."""
    from graphcut.transcriber import Transcriber

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
    from graphcut.scene_detector import detect_scenes as _detect

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
    from graphcut.silence_detector import detect_silences, suggest_jump_cuts

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
            from graphcut.transcript_editor import TranscriptEditor
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
    from graphcut.voice_recorder import VoiceRecorder
    from graphcut.models import MediaInfo

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
            from graphcut.media_prober import probe_file
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


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["srt", "vtt", "both"]), default="both", help="Export format.")
@click.option("--style", type=click.Choice(["clean", "social"]), default=None, help="Burning caption style.")
@click.option("--output-dir", type=click.Path(file_okay=False, dir_okay=True, path_type=Path), default=None, help="Output directory for subtitles.")
def export_captions(project_dir: Path, fmt: str, style: str | None, output_dir: Path | None) -> None:
    """Generate caption files (SRT/VTT) from project transcripts."""
    from graphcut.caption_generator import CaptionGenerator
    from graphcut.models import Transcript
    
    try:
        manifest = ProjectManager.load_project(project_dir)
        if style:
            manifest.caption_style.style = style
            ProjectManager.save_project(manifest, project_dir)
            
        cg = CaptionGenerator(manifest.caption_style)
        out_path = output_dir or (project_dir / "build")
        out_path.mkdir(parents=True, exist_ok=True)
        
        # Determine primary audio transcript
        primary = None
        for source_id in manifest.sources:
            t_path = project_dir / ".cache" / "transcripts" / f"{manifest.sources[source_id].file_hash}_medium.json"
            if t_path.exists():
                primary = t_path
                break
                
        if not primary:
            console.print("[bold red]No transcripts found. Run `transcribe` first.[/bold red]")
            return
            
        with open(primary) as f:
            transcript = Transcript.model_validate_json(f.read())
            
        if fmt in ("srt", "both"):
            srt_path = out_path / f"{transcript.source_id}.srt"
            cg.to_srt(transcript, srt_path)
            console.print(f"[bold green]Exported SRT -> [cyan]{srt_path}[/cyan][/bold green]")
            
        if fmt in ("vtt", "both"):
            vtt_path = out_path / f"{transcript.source_id}.vtt"
            cg.to_vtt(transcript, vtt_path)
            console.print(f"[bold green]Exported VTT -> [cyan]{vtt_path}[/cyan][/bold green]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.argument("webcam_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--position", type=click.Choice(["bottom-right", "bottom-left", "top-right", "top-left", "side-by-side"]), default="bottom-right")
@click.option("--scale", type=float, default=0.25, help="Scale relative to base video width.")
@click.option("--border", type=int, default=2, help="Border width in pixels.")
def set_webcam(project_dir: Path, webcam_file: Path, position: str, scale: float, border: int) -> None:
    """Configure webcam picture-in-picture overlay."""
    from graphcut.models import WebcamOverlay
    
    try:
        manifest = ProjectManager.load_project(project_dir)
        source_id = "webcam"
        
        # Ensure media is inside project directory
        dest_path = project_dir / "sources" / webcam_file.name
        if not dest_path.exists() and webcam_file.absolute() != dest_path.absolute():
            import shutil
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(webcam_file, dest_path)
            
        from graphcut.media_prober import probe_file
        manifest.sources[source_id] = probe_file(dest_path)
        
        manifest.webcam = WebcamOverlay(
            source_id=source_id,
            position=position,
            scale=scale,
            border_width=border
        )
        
        ProjectManager.save_project(manifest, project_dir)
        console.print("[bold green]Webcam overlay configured and bound to project.[/bold green]")
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise click.Abort()


@cli.command()
@click.argument("project_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path))
@click.option("--port", type=int, default=8420, help="Port to run the UI server on.")
@click.option("--proxy", type=str, default=None, help="Force an HTTP proxy for static downloads behind strict firewalls.")
def serve(project_dir: Path, port: int, proxy: str | None) -> None:
    """Start the GraphCut web GUI editor server."""
    import os
    import uvicorn
    import webbrowser
    from graphcut.server import create_app
    
    if proxy:
        os.environ["GRAPHCUT_HTTP_PROXY"] = proxy
    
    app = create_app(project_dir)
    
    console.print(f"[bold green]Starting GraphCut server on port {port}...[/bold green]")
    url = f"http://127.0.0.1:{port}"
    webbrowser.open(url)
    
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    cli()
