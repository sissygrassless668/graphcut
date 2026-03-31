"""Provider-agnostic generation queue for AI video workflows."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_queue_dir() -> Path:
    return Path.cwd() / "artifacts" / "generation_jobs"


def _job_path(queue_dir: Path, job_id: str) -> Path:
    return queue_dir / f"{job_id}.json"


def _read_job(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_job(path: Path, payload: dict) -> None:
    payload["updated_at"] = _utcnow_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_storyboard(storyboard_path: Path) -> dict:
    """Load a storyboard JSON payload from disk."""
    payload = json.loads(storyboard_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "shots" not in payload:
        raise ValueError("Storyboard JSON must contain a top-level 'shots' field.")
    return payload


def list_provider_names() -> list[str]:
    """List available generation providers."""
    return ["mock"]


def submit_job(
    storyboard: dict,
    *,
    provider: str = "mock",
    queue_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    """Submit a storyboard to a provider-backed generation queue."""
    if provider != "mock":
        raise ValueError(f"Unknown provider: {provider}")

    queue_root = (queue_dir or _default_queue_dir()).resolve()
    output_root = (output_dir or (Path.cwd() / "artifacts" / "generated")).resolve()
    shots = storyboard.get("shots") or []
    if not isinstance(shots, list) or not shots:
        raise ValueError("Storyboard must contain at least one shot.")

    job_id = f"gen_{provider}_{uuid.uuid4().hex[:10]}"
    payload = {
        "job_id": job_id,
        "provider": provider,
        "status": "queued",
        "created_at": _utcnow_iso(),
        "output_dir": str(output_root),
        "storyboard": storyboard,
        "provider_job_id": f"{provider}_{uuid.uuid4().hex[:8]}",
        "remote_assets": [
            {
                "shot_id": shot.get("shot_id", f"shot_{index:02d}"),
                "prompt": shot.get("visual_prompt", ""),
                "duration_seconds": shot.get("duration_seconds", 0),
                "aspect_ratio": shot.get("aspect_ratio", storyboard.get("platform", "9:16")),
                "status": "queued",
            }
            for index, shot in enumerate(shots, start=1)
        ],
    }
    _write_job(_job_path(queue_root, job_id), payload)
    return payload


def refresh_job(job_id: str, queue_dir: Path | None = None) -> dict:
    """Refresh a job from its provider."""
    queue_root = (queue_dir or _default_queue_dir()).resolve()
    job_file = _job_path(queue_root, job_id)
    if not job_file.exists():
        raise ValueError(f"Job not found: {job_id}")

    payload = _read_job(job_file)
    if payload["provider"] != "mock":
        raise ValueError(f"Unknown provider: {payload['provider']}")

    if payload["status"] in {"queued", "running"}:
        payload["status"] = "succeeded"
        payload["completed_at"] = _utcnow_iso()
        for asset in payload.get("remote_assets", []):
            asset["status"] = "succeeded"
            asset["remote_uri"] = f"mock://{job_id}/{asset['shot_id']}"

    _write_job(job_file, payload)
    return payload


def get_job(job_id: str, queue_dir: Path | None = None, *, refresh: bool = False) -> dict:
    """Load a queue job, optionally refreshing its provider state first."""
    if refresh:
        return refresh_job(job_id, queue_dir=queue_dir)
    queue_root = (queue_dir or _default_queue_dir()).resolve()
    job_file = _job_path(queue_root, job_id)
    if not job_file.exists():
        raise ValueError(f"Job not found: {job_id}")
    return _read_job(job_file)


def list_jobs(queue_dir: Path | None = None) -> list[dict]:
    """List queued generation jobs."""
    queue_root = (queue_dir or _default_queue_dir()).resolve()
    if not queue_root.exists():
        return []
    jobs = [_read_job(path) for path in sorted(queue_root.glob("gen_*.json"))]
    jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jobs


def wait_for_job(
    job_id: str,
    *,
    queue_dir: Path | None = None,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 1.0,
) -> dict:
    """Wait for a queue job to finish."""
    deadline = time.time() + timeout_seconds
    while True:
        payload = refresh_job(job_id, queue_dir=queue_dir)
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for job {job_id}")
        time.sleep(poll_seconds)


def fetch_job(job_id: str, *, queue_dir: Path | None = None, output_dir: Path | None = None) -> dict:
    """Fetch provider assets for a completed job into local files."""
    payload = refresh_job(job_id, queue_dir=queue_dir)
    if payload["status"] != "succeeded":
        raise ValueError(f"Job {job_id} is not ready to fetch.")

    output_root = (output_dir or Path(payload["output_dir"])).resolve()
    target_dir = output_root / job_id
    target_dir.mkdir(parents=True, exist_ok=True)

    local_assets: list[dict] = []
    for asset in payload.get("remote_assets", []):
        target_file = target_dir / f"{asset['shot_id']}.json"
        asset_payload = {
            "shot_id": asset["shot_id"],
            "prompt": asset["prompt"],
            "duration_seconds": asset["duration_seconds"],
            "aspect_ratio": asset["aspect_ratio"],
            "remote_uri": asset.get("remote_uri"),
            "provider": payload["provider"],
        }
        target_file.write_text(json.dumps(asset_payload, indent=2), encoding="utf-8")
        local_assets.append(
            {
                "shot_id": asset["shot_id"],
                "path": str(target_file),
                "prompt": asset["prompt"],
            }
        )

    payload["fetched_at"] = _utcnow_iso()
    payload["local_assets"] = local_assets
    _write_job(_job_path((queue_dir or _default_queue_dir()).resolve(), job_id), payload)
    return payload
