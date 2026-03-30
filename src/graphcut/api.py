"""REST API endpoints for the GraphCut underlying FFmpeg and project state logic."""

import logging
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import anyio
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from graphcut.models import (
    ProjectManifest,
    ClipRef,
    AudioMix,
    WebcamOverlay,
    CaptionStyle,
    ExportPreset,
    SceneConfig,
)
from graphcut.ffmpeg_executor import FFmpegError
from graphcut.project_manager import ProjectManager
from graphcut.transcriber import Transcriber
from graphcut.exporter import Exporter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["GraphCut"])


# Background job task tracker
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = Lock()
_WS_CLIENTS: list[WebSocket] = []

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_update(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            job = {"job_id": job_id, "created_at": _utcnow_iso()}
            _JOBS[job_id] = job
        job.update(fields)
        job["updated_at"] = _utcnow_iso()


async def broadcast_progress(
    job_id: str,
    action: str,
    progress: float,
    speed: str = "0.0",
    eta: str = "--:--",
    detail: str | None = None,
):
    """Broadcast progress to all connected frontend clients."""
    msg = {
        "job_id": job_id,
        "action": action,
        "progress": progress,
        "speed": speed,
        "eta": eta
    }
    if detail:
        msg["detail"] = detail
    for client in _WS_CLIENTS.copy():
        try:
            await client.send_json(msg)
        except WebSocketDisconnect:
            _WS_CLIENTS.remove(client)


def get_manifest(request: Request) -> ProjectManifest:
    """Helper verifying active UI project context."""
    pdir = getattr(request.app.state, "project_dir", None)
    if not pdir or not pdir.exists():
        raise HTTPException(status_code=400, detail="No active project assigned during server boot.")
    try:
        return ProjectManager.load_project(pdir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def save_manifest(manifest: ProjectManifest, request: Request):
    """Save changes explicitly out to YML disk bounds."""
    ProjectManager.save_project(manifest, request.app.state.project_dir)

# ----------------- #
#   Project Admin   #
# ----------------- #

@router.get("/project", response_model=ProjectManifest)
def get_project(request: Request):
    return get_manifest(request)


class OpenReq(BaseModel):
    path: str

@router.post("/project/open")
def open_project(req: OpenReq, request: Request):
    p = Path(req.path)
    if not p.exists() or not (p / "project.yaml").exists():
        raise HTTPException(status_code=404, detail="Invalid project directory.")
    request.app.state.project_dir = p
    return {"status": "ok", "project": get_manifest(request)}


# ----------------- #
#      Sources      #
# ----------------- #

@router.get("/sources")
def list_sources(request: Request):
    manifest = get_manifest(request)
    # Trigger thumbnails caching
    from graphcut.thumbnails import generate_thumbnails
    thumb_paths = generate_thumbnails(manifest, request.app.state.project_dir)
    
    res = {}
    for sid, info in manifest.sources.items():
        res[sid] = info.model_dump()
        res[sid]["thumbnail"] = f"/api/sources/{sid}/thumbnail" if sid in thumb_paths else None
    return res

from fastapi import UploadFile, File
import shutil

@router.post("/sources/upload")
async def upload_source(request: Request, file: UploadFile = File(...)):
    manifest = get_manifest(request)
    pdir = request.app.state.project_dir
    media_dir = pdir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    
    safe_name = file.filename or "uploaded_media.mp4"
    dest_path = media_dir / safe_name
    
    with dest_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    ProjectManager.add_source(manifest, dest_path)
    save_manifest(manifest, request)
    return {"status": "ok", "filename": safe_name}

@router.delete("/sources/{source_id}")
def delete_source(source_id: str, request: Request, delete_file: bool = False):
    manifest = get_manifest(request)
    try:
        file_deleted = ProjectManager.remove_source(
            manifest,
            source_id,
            delete_file=delete_file,
            project_dir=request.app.state.project_dir,
        )
        save_manifest(manifest, request)
        return {"status": "ok", "file_deleted": file_deleted}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/sources/{source_id}/thumbnail")
def source_thumbnail(source_id: str, request: Request):
    manifest = get_manifest(request)
    if source_id not in manifest.sources:
        raise HTTPException(404, "Source not found")
        
    pdir = request.app.state.project_dir
    tf = pdir / ".cache" / "thumbnails" / f"{manifest.sources[source_id].file_hash}_{source_id}.jpg"
    if tf.exists():
        return FileResponse(tf, media_type="image/jpeg")
    raise HTTPException(404, "Thumbnail not found/generated.")


@router.get("/sources/{source_id}/media")
def source_media(source_id: str, request: Request):
    manifest = get_manifest(request)
    if source_id not in manifest.sources:
        raise HTTPException(404, "Source not found")

    pdir = request.app.state.project_dir.resolve()
    path = manifest.sources[source_id].file_path.resolve()
    if not path.exists():
        raise HTTPException(404, "Media file not found")
    if not path.is_relative_to(pdir):
        raise HTTPException(403, "Media file is outside the active project directory")

    mt = "application/octet-stream"
    if manifest.sources[source_id].media_type == "video":
        mt = "video/mp4"
    elif manifest.sources[source_id].media_type == "audio":
        mt = "audio/mpeg"

    return FileResponse(path, media_type=mt, filename=path.name)


# ----------------- #
#       Clips       #
# ----------------- #

@router.get("/clips")
def get_clips(request: Request):
    manifest = get_manifest(request)
    return manifest.clip_order

@router.put("/clips/reorder")
def reorder_clips(indices: list[int], request: Request):
    manifest = get_manifest(request)
    if len(indices) != len(manifest.clip_order):
        raise HTTPException(400, "Reorder list length must match current clip count.")
    if any((i < 0 or i >= len(manifest.clip_order)) for i in indices):
        raise HTTPException(400, "Invalid clip index in reorder list.")
    if len(set(indices)) != len(indices):
        raise HTTPException(400, "Reorder list cannot contain duplicates.")
    new_order = [manifest.clip_order[i] for i in indices]
    manifest.clip_order = new_order
    save_manifest(manifest, request)
    return {"status": "success"}

class AddClipReq(BaseModel):
    source_id: str

@router.post("/clips/add")
def add_clip(req: AddClipReq, request: Request):
    manifest = get_manifest(request)
    if req.source_id not in manifest.sources:
        raise HTTPException(404, "Source not found")
    manifest.clip_order.append(ClipRef(source_id=req.source_id))
    save_manifest(manifest, request)
    return manifest.clip_order


class InsertClipReq(BaseModel):
    source_id: str
    trim_start: float | None = None
    trim_end: float | None = None
    position: int | None = None


@router.post("/clips/insert")
def insert_clip(req: InsertClipReq, request: Request):
    manifest = get_manifest(request)
    if req.source_id not in manifest.sources:
        raise HTTPException(404, "Source not found")
    if req.trim_start is not None and req.trim_start < 0:
        raise HTTPException(400, "trim_start must be >= 0")
    if req.trim_end is not None and req.trim_end < 0:
        raise HTTPException(400, "trim_end must be >= 0")
    if req.trim_start is not None and req.trim_end is not None and req.trim_end <= req.trim_start:
        raise HTTPException(400, "trim_end must be greater than trim_start")

    clip = ClipRef(
        source_id=req.source_id,
        trim_start=req.trim_start,
        trim_end=req.trim_end,
    )
    pos = req.position if req.position is not None else len(manifest.clip_order)
    pos = max(0, min(len(manifest.clip_order), int(pos)))
    manifest.clip_order.insert(pos, clip)
    save_manifest(manifest, request)
    return {"status": "ok", "clips": manifest.clip_order}


class DuplicateClipReq(BaseModel):
    index: int
    position: int | None = None


@router.post("/clips/duplicate")
def duplicate_clip(req: DuplicateClipReq, request: Request):
    manifest = get_manifest(request)
    if req.index < 0 or req.index >= len(manifest.clip_order):
        raise HTTPException(404, "Clip not found")

    original = manifest.clip_order[req.index]
    clip = ClipRef(**original.model_dump())
    pos = req.position if req.position is not None else (req.index + 1)
    pos = max(0, min(len(manifest.clip_order), int(pos)))
    manifest.clip_order.insert(pos, clip)
    save_manifest(manifest, request)
    return {"status": "ok", "clips": manifest.clip_order}


class SplitClipReq(BaseModel):
    index: int
    time: float


@router.post("/clips/split")
def split_clip(req: SplitClipReq, request: Request):
    manifest = get_manifest(request)
    if req.index < 0 or req.index >= len(manifest.clip_order):
        raise HTTPException(404, "Clip not found")

    clip = manifest.clip_order[req.index]
    info = manifest.sources.get(clip.source_id)
    if not info:
        raise HTTPException(400, "Missing source info for clip")

    t0 = clip.trim_start if clip.trim_start is not None else 0.0
    t1 = clip.trim_end if clip.trim_end is not None else info.duration_seconds
    t = float(req.time)
    if t <= t0 or t >= t1:
        raise HTTPException(400, "Split time must be within the clip trim range")

    left = ClipRef(**clip.model_dump())
    right = ClipRef(**clip.model_dump())
    left.trim_end = t
    right.trim_start = t
    right.trim_end = t1 if clip.trim_end is not None else None

    manifest.clip_order[req.index] = left
    manifest.clip_order.insert(req.index + 1, right)
    save_manifest(manifest, request)
    return {"status": "ok", "clips": manifest.clip_order}


class MoveClipReq(BaseModel):
    from_index: int
    to_index: int


@router.post("/clips/move")
def move_clip(req: MoveClipReq, request: Request):
    manifest = get_manifest(request)
    n = len(manifest.clip_order)
    if req.from_index < 0 or req.from_index >= n:
        raise HTTPException(404, "Clip not found")
    if req.to_index < 0 or req.to_index >= n:
        raise HTTPException(400, "Invalid destination index")

    clip = manifest.clip_order.pop(req.from_index)
    manifest.clip_order.insert(req.to_index, clip)
    save_manifest(manifest, request)
    return {"status": "ok", "clips": manifest.clip_order}


class UpdateClipReq(BaseModel):
    trim_start: float | None = None
    trim_end: float | None = None
    transition: str | None = None
    transition_duration: float | None = None


@router.put("/clips/{index}")
def update_clip(index: int, req: UpdateClipReq, request: Request):
    manifest = get_manifest(request)
    if index < 0 or index >= len(manifest.clip_order):
        raise HTTPException(404, "Clip not found")

    clip = manifest.clip_order[index]
    provided_fields = getattr(req, "model_fields_set", set())
    if "trim_start" in provided_fields:
        clip.trim_start = max(0.0, float(req.trim_start)) if req.trim_start is not None else None

    if "trim_end" in provided_fields:
        clip.trim_end = max(0.0, float(req.trim_end)) if req.trim_end is not None else None

    if clip.trim_start is not None and clip.trim_end is not None and clip.trim_end <= clip.trim_start:
        raise HTTPException(400, "trim_end must be greater than trim_start")

    if req.transition is not None:
        # ClipRef model will validate at save time; keep basic sanity here.
        clip.transition = req.transition  # type: ignore[assignment]
    if req.transition_duration is not None:
        clip.transition_duration = max(0.0, float(req.transition_duration))

    manifest.clip_order[index] = clip
    save_manifest(manifest, request)
    return {"status": "ok", "clip": clip}


@router.delete("/clips/{index}")
def delete_clip(index: int, request: Request):
    manifest = get_manifest(request)
    if index < 0 or index >= len(manifest.clip_order):
        raise HTTPException(404, "Clip not found")
    manifest.clip_order.pop(index)
    save_manifest(manifest, request)
    return {"status": "ok", "clips": manifest.clip_order}


# ----------------- #
#    Transcripts    #
# ----------------- #

@router.get("/transcript")
def get_transcript(request: Request):
    manifest = get_manifest(request)
    pdir = request.app.state.project_dir
    results = {}
    for sid, info in manifest.sources.items():
        tp = pdir / ".cache" / "transcripts" / f"{info.file_hash}_medium.json"
        if tp.exists():
            import json
            with tp.open() as f:
                results[sid] = json.load(f)
    return results

@router.post("/transcript/generate")
async def generate_transcript(request: Request, bg_tasks: BackgroundTasks):
    manifest = get_manifest(request)
    pdir = request.app.state.project_dir
    
    def transcribe_task():
        transcriber = Transcriber("medium")
        for sid, info in manifest.sources.items():
            if info.media_type in ("video", "audio"):
                try:
                    transcriber.transcribe(info.file_path, pdir)
                except Exception as e:
                    logger.error("Transcription failed for %s: %s", sid, e)

    bg_tasks.add_task(transcribe_task)
    return {"status": "ok", "message": "Transcription job started"}

@router.post("/transcript/cuts")
def apply_transcript_cuts(cuts: list[dict], request: Request):
    manifest = get_manifest(request)
    manifest.transcript_cuts = cuts
    save_manifest(manifest, request)
    return {"status": "ok"}


# ----------------- #
#       Audio       #
# ----------------- #

@router.get("/audio")
def get_audio(request: Request) -> AudioMix:
    return get_manifest(request).audio_mix

@router.put("/audio")
def update_audio(mix: AudioMix, request: Request):
    manifest = get_manifest(request)
    manifest.audio_mix = mix
    save_manifest(manifest, request)
    return {"status": "ok"}


# ----------------- #
#     Overlays      #
# ----------------- #

@router.get("/overlays")
def get_overlays(request: Request):
    m = get_manifest(request)
    return {"webcam": m.webcam, "caption_style": m.caption_style}

@router.put("/overlays/webcam")
def set_webcam(overlay: WebcamOverlay, request: Request):
    m = get_manifest(request)
    m.webcam = overlay
    save_manifest(m, request)
    return {"status": "ok"}

@router.delete("/overlays/webcam")
def delete_webcam(request: Request):
    m = get_manifest(request)
    m.webcam = None
    save_manifest(m, request)
    return {"status": "ok"}


@router.put("/overlays/caption_style")
def set_caption_style(style: CaptionStyle, request: Request):
    m = get_manifest(request)
    m.caption_style = style
    save_manifest(m, request)
    return {"status": "ok"}


class RolesReq(BaseModel):
    narration: str | None = None
    music: str | None = None


@router.put("/project/roles")
def set_roles(req: RolesReq, request: Request):
    m = get_manifest(request)
    m.narration = req.narration
    m.music = req.music
    save_manifest(m, request)
    return {"status": "ok"}


class SceneNameReq(BaseModel):
    name: str


@router.get("/scenes")
def get_scenes(request: Request):
    m = get_manifest(request)
    return {"active_scene": m.active_scene, "scenes": m.scenes}


@router.post("/scenes/save")
def save_scene(req: SceneNameReq, request: Request):
    m = get_manifest(request)
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Scene name cannot be empty")

    m.scenes[name] = SceneConfig(
        webcam=m.webcam,
        audio_mix=m.audio_mix,
        caption_style=m.caption_style,
        narration=m.narration,
        music=m.music,
    )
    if m.active_scene is None:
        m.active_scene = name
    save_manifest(m, request)
    return {"status": "ok", "active_scene": m.active_scene, "scenes": m.scenes}


@router.post("/scenes/activate")
def activate_scene(req: SceneNameReq, request: Request):
    m = get_manifest(request)
    name = req.name.strip()
    if name not in m.scenes:
        raise HTTPException(404, "Scene not found")

    sc = m.scenes[name]
    m.active_scene = name
    m.webcam = sc.webcam
    m.audio_mix = sc.audio_mix
    m.caption_style = sc.caption_style
    m.narration = sc.narration
    m.music = sc.music

    save_manifest(m, request)
    return {"status": "ok", "active_scene": m.active_scene}


@router.delete("/scenes/{scene_name}")
def delete_scene(scene_name: str, request: Request):
    m = get_manifest(request)
    if scene_name not in m.scenes:
        raise HTTPException(404, "Scene not found")
    del m.scenes[scene_name]
    if m.active_scene == scene_name:
        m.active_scene = None
    save_manifest(m, request)
    return {"status": "ok", "active_scene": m.active_scene, "scenes": m.scenes}


# ----------------- #
#      Export       #
# ----------------- #

@router.get("/export/presets")
def list_presets(request: Request):
    return get_manifest(request).export_presets

class RenderReq(BaseModel):
    preset: str
    quality: str = "final"

@router.post("/export/render")
async def trigger_render(req: RenderReq, request: Request, bg_tasks: BackgroundTasks):
    manifest = get_manifest(request)
    pdir = request.app.state.project_dir
    exporter = Exporter()
    if not manifest.clip_order:
        raise HTTPException(400, "No clips in timeline. Add at least one source to the timeline first.")
    
    p = next((x for x in manifest.export_presets if x.name.lower() == req.preset.lower()), None)
    if not p:
        raise HTTPException(400, f"Preset {req.preset} not found.")

    p.quality = req.quality
    job_id = f"render_{p.name}_{p.quality}_{uuid.uuid4().hex[:8]}"
    out_filename = f"{manifest.name}_{p.name}.mp4"
    out = pdir / manifest.build_dir
    out.mkdir(parents=True, exist_ok=True)

    _job_update(
        job_id,
        type="render",
        status="queued",
        project_name=manifest.name,
        preset=p.name,
        quality=p.quality,
        output_filename=out_filename,
        output_dir=str(out),
    )
    
    def render_task():
        try:
            _job_update(job_id, status="running", started_at=_utcnow_iso(), last_progress=0.0)

            def cb(pct: float, spd: str, rem: str):
                _job_update(job_id, last_progress=pct, speed=spd, eta=rem)
                anyio.from_thread.run(broadcast_progress, job_id, "render", pct, spd, rem)
                
            exporter.export(manifest, p, out, progress_callback=cb, project_dir=pdir)
            anyio.from_thread.run(broadcast_progress, job_id, "render", 100.0, "0.0", "00:00")
            _job_update(job_id, status="succeeded", finished_at=_utcnow_iso(), last_progress=100.0)
        except Exception as e:
            logger.exception("Render job %s failed", job_id)

            err_detail = str(e)
            fields: dict[str, Any] = {
                "status": "failed",
                "finished_at": _utcnow_iso(),
                "error": err_detail,
                "traceback": traceback.format_exc(),
                "last_progress": 100.0,
            }

            if isinstance(e, FFmpegError):
                fields["ffmpeg_returncode"] = e.returncode
                fields["ffmpeg_cmd"] = " ".join(e.cmd) if e.cmd else None
                fields["ffmpeg_stderr_tail"] = (e.stderr or "")[-8000:]

            _job_update(job_id, **fields)
            anyio.from_thread.run(
                broadcast_progress,
                job_id,
                "render failed",
                100.0,
                "0.0",
                "--:--",
                detail=err_detail,
            )
            
    bg_tasks.add_task(render_task)
    return {"status": "started", "job_id": job_id, "filename": out_filename}

@router.get("/jobs")
def list_jobs(limit: int = 20):
    with _JOBS_LOCK:
        jobs = list(_JOBS.values())
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs[: max(1, min(limit, 200))]


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

@router.get("/export/download/{filename}")
def download_export(filename: str, request: Request):
    pdir = request.app.state.project_dir
    manifest = get_manifest(request)
    path = pdir / manifest.build_dir / filename
    if not path.exists():
        raise HTTPException(404, "Export not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.websocket("/ws/progress")
async def ws_progress(websocket: WebSocket):
    await websocket.accept()
    _WS_CLIENTS.append(websocket)
    try:
        while True:
            # Keep alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _WS_CLIENTS:
            _WS_CLIENTS.remove(websocket)
