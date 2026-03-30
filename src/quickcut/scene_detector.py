"""Scene detection using PySceneDetect."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_scenes(
    file_path: Path, threshold: float = 27.0
) -> list[dict]:
    """Detect scene boundaries in a video file.

    Uses PySceneDetect's AdaptiveDetector for robust motion-tolerant detection.

    Args:
        file_path: Path to the video file.
        threshold: Detection sensitivity (lower = more sensitive). Default 27.0.

    Returns:
        List of {"start": float, "end": float, "index": int} scene dicts.
    """
    try:
        from scenedetect import detect, AdaptiveDetector
    except ImportError:
        raise ImportError(
            "scenedetect is required for scene detection. "
            "Install with: pip install 'quickcut[scene]'"
        )

    logger.info("Detecting scenes in %s (threshold=%.1f)...", file_path.name, threshold)

    scene_list = detect(str(file_path), AdaptiveDetector(adaptive_threshold=threshold))

    scenes: list[dict] = []
    for i, (start, end) in enumerate(scene_list):
        scenes.append({
            "start": round(start.get_seconds(), 3),
            "end": round(end.get_seconds(), 3),
            "index": i,
        })

    logger.info("Found %d scenes", len(scenes))
    return scenes


def suggest_cuts(scenes: list[dict], min_scene_duration: float = 1.0) -> list[dict]:
    """Suggest cutting very short scenes (likely flashes/glitches).

    Args:
        scenes: Scene list from detect_scenes.
        min_scene_duration: Scenes shorter than this are suggested for removal.

    Returns:
        List of {"start": float, "end": float} cut suggestions.
    """
    cuts: list[dict] = []
    for scene in scenes:
        duration = scene["end"] - scene["start"]
        if duration < min_scene_duration:
            cuts.append({"start": scene["start"], "end": scene["end"]})

    logger.info(
        "Suggesting %d cuts from %d scenes (min_duration=%.1fs)",
        len(cuts), len(scenes), min_scene_duration,
    )
    return cuts
