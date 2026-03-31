"""Declarative agent contracts for creator workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from graphcut.agent_workflows import (
    build_publish_bundle,
    build_storyboard,
    bundle_to_markdown,
    resolve_script_text,
    viralize,
)
from graphcut.factory import build_plan, execute_plan
from graphcut.generation_queue import (
    fetch_job,
    load_storyboard,
    submit_job,
    wait_for_job,
)
from graphcut.media_prober import probe_file


@dataclass(frozen=True)
class CreatorBrief:
    """A machine-friendly recommendation bundle for creators and agents."""

    source_file: str
    duration_seconds: float
    media_type: str
    orientation: str
    recommended_platform: str
    recommended_recipe: str
    recommended_workflow: str
    recommended_command: str
    next_actions: tuple[str, ...]
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return asdict(self)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_orientation(width: int | None, height: int | None) -> str:
    if width and height:
        if height > width:
            return "vertical"
        if width > height:
            return "horizontal"
        return "square"
    return "unknown"


def build_creator_brief(source_path: Path, script_text: str | None = None) -> CreatorBrief:
    """Recommend the best creator workflow for a source asset."""
    info = probe_file(source_path)
    orientation = _normalize_orientation(info.width, info.height)

    if info.duration_seconds >= 300:
        platform = "shorts"
        recipe = "podcast"
        workflow = "viralize"
        command = f"graphcut viralize {source_path} --recipe podcast --clips 8 --render"
        rationale = (
            "Long-form footage is a strong candidate for multi-clip repurposing.",
            "Short-form vertical outputs create the highest leverage for creator reuse.",
        )
    elif info.duration_seconds >= 45:
        platform = "tiktok" if orientation != "horizontal" else "shorts"
        recipe = "talking-head"
        workflow = "repurpose"
        command = f"graphcut repurpose {source_path} --recipe talking-head --clips 4"
        rationale = (
            "Mid-length footage benefits from clip extraction instead of a single export.",
            "Talking-head defaults preserve speech clarity and captions.",
        )
    else:
        platform = "tiktok" if orientation != "horizontal" else "youtube"
        recipe = "reaction" if orientation == "vertical" else "talking-head"
        workflow = "make"
        command = f"graphcut make {source_path} --platform {platform} --captions social"
        rationale = (
            "Short footage is already close to publishable and needs platform packaging more than clip mining.",
            "A single polished export is the fastest route to posting.",
        )

    next_actions = [
        "Run the recommended command or use `graphcut preview` first.",
        "Generate a publish bundle with `graphcut package`.",
    ]
    if script_text:
        next_actions.append("Use `graphcut storyboard` or `graphcut generate` to create AI-shot variants from the script.")
    if workflow != "make":
        next_actions.append("Use `graphcut viralize` for a one-command plan + package flow.")

    return CreatorBrief(
        source_file=str(source_path),
        duration_seconds=info.duration_seconds,
        media_type=info.media_type,
        orientation=orientation,
        recommended_platform=platform,
        recommended_recipe=recipe,
        recommended_workflow=workflow,
        recommended_command=command,
        next_actions=tuple(next_actions),
        rationale=rationale,
    )


def agent_template(workflow: str = "viralize") -> dict[str, Any]:
    """Return a starter job spec for an agent framework."""
    templates: dict[str, dict[str, Any]] = {
        "viralize": {
            "workflow": "viralize",
            "render": False,
            "params": {
                "source_file": "podcast.mp4",
                "recipe_name": "podcast",
                "clips": 8,
                "captions": "social",
            },
        },
        "storyboard": {
            "workflow": "storyboard",
            "params": {
                "text": "Lead with a hook. Then explain the payoff.",
                "platform_name": "tiktok",
                "provider": "mock",
            },
        },
        "generate": {
            "workflow": "generate",
            "wait_for_completion": True,
            "fetch_outputs": True,
            "params": {
                "text": "Lead with a hook. Then explain the payoff.",
                "platform_name": "tiktok",
                "provider": "mock",
            },
        },
        "package": {
            "workflow": "package",
            "format": "json",
            "params": {
                "source_name": "podcast.mp4",
                "text": "Creator workflow for faster posting.",
                "platform_name": "shorts",
            },
        },
        "creator-brief": {
            "workflow": "creator-brief",
            "params": {
                "source_file": "podcast.mp4",
            },
        },
    }
    if workflow not in templates:
        raise ValueError(f"Unknown template workflow: {workflow}")
    return templates[workflow]


def run_agent_job(spec: dict[str, Any], *, dry_run_override: bool | None = None) -> dict[str, Any]:
    """Run a declarative job spec and return a stable result payload."""
    workflow = spec.get("workflow")
    params = dict(spec.get("params") or {})
    dry_run = spec.get("dry_run", False)
    if dry_run_override is not None:
        dry_run = dry_run_override

    if workflow == "storyboard":
        script_text = resolve_script_text(
            script_input=params.pop("script_input", None),
            script_file=Path(params.pop("script_file")) if params.get("script_file") else None,
            text=params.pop("text", None),
        )
        storyboard = build_storyboard(script_text, **params)
        return {"workflow": workflow, "result": storyboard.to_dict()}

    if workflow == "package":
        script_text = None
        if params.get("text") or params.get("script_file"):
            script_text = resolve_script_text(
                script_file=Path(params.pop("script_file")) if params.get("script_file") else None,
                text=params.pop("text", None),
            )
        bundle = build_publish_bundle(script_text=script_text, **params)
        format_name = spec.get("format", "json")
        result: dict[str, Any] = {"workflow": workflow, "result": bundle.to_dict()}
        if format_name == "markdown":
            result["markdown"] = bundle_to_markdown(bundle)
        return result

    if workflow == "creator-brief":
        script_text = None
        if params.get("text") or params.get("script_file"):
            script_text = resolve_script_text(
                script_file=Path(params.pop("script_file")) if params.get("script_file") else None,
                text=params.pop("text", None),
            )
        brief = build_creator_brief(Path(params["source_file"]), script_text=script_text)
        return {"workflow": workflow, "result": brief.to_dict()}

    if workflow == "make":
        plan = build_plan("make", Path(params.pop("source_file")), **params)
        rendered = [] if dry_run else [str(path) for path in execute_plan(plan)]
        return {"workflow": workflow, "plan": plan.to_dict(), "rendered_paths": rendered}

    if workflow == "repurpose":
        plan = build_plan("repurpose", Path(params.pop("source_file")), **params)
        rendered = [] if dry_run else [str(path) for path in execute_plan(plan)]
        return {"workflow": workflow, "plan": plan.to_dict(), "rendered_paths": rendered}

    if workflow == "viralize":
        source_file = Path(params.pop("source_file"))
        plan, bundle, rendered = viralize(source_file, render=not dry_run and spec.get("render", False), **params)
        return {
            "workflow": workflow,
            "plan": plan.to_dict(),
            "package": bundle.to_dict(),
            "rendered_paths": [str(path) for path in rendered],
        }

    if workflow == "generate":
        if params.get("storyboard_path"):
            storyboard = load_storyboard(Path(params.pop("storyboard_path")))
            provider = params.pop("provider", "mock")
        else:
            provider = params.get("provider", "mock")
            script_text = resolve_script_text(
                script_input=params.pop("script_input", None),
                script_file=Path(params.pop("script_file")) if params.get("script_file") else None,
                text=params.pop("text", None),
            )
            storyboard = build_storyboard(script_text, **params).to_dict()
        queue_dir = Path(spec["queue_dir"]) if spec.get("queue_dir") else None
        output_dir = Path(spec["output_dir"]) if spec.get("output_dir") else None
        job = submit_job(storyboard, provider=provider, queue_dir=queue_dir, output_dir=output_dir)
        if spec.get("wait_for_completion", False):
            job = wait_for_job(job["job_id"], queue_dir=queue_dir)
        if spec.get("fetch_outputs", False):
            job = fetch_job(job["job_id"], queue_dir=queue_dir, output_dir=output_dir)
        return {"workflow": workflow, "result": job}

    raise ValueError(f"Unsupported workflow: {workflow}")
