"""Clip suggestion heuristics for long-form to short-form repurposing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ClipSuggestion:
    """A suggested short-form excerpt."""

    start: float
    end: float
    score: float
    scene_count: int
    silence_seconds: float
    reason: str

    @property
    def duration(self) -> float:
        """Return clip duration in seconds."""
        return round(self.end - self.start, 3)

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation."""
        payload = asdict(self)
        payload["duration"] = self.duration
        return payload


def _overlap_seconds(start: float, end: float, cuts: list[dict]) -> float:
    total = 0.0
    for cut in cuts:
        overlap_start = max(start, float(cut["start"]))
        overlap_end = min(end, float(cut["end"]))
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
    return round(total, 3)


def _normalize_segments(
    duration: float,
    scenes: list[dict],
    max_clip_seconds: float,
) -> list[tuple[float, float]]:
    if duration <= 0:
        return []

    if scenes:
        segments = [
            (
                max(0.0, float(scene["start"])),
                min(duration, float(scene["end"])),
            )
            for scene in scenes
            if float(scene["end"]) > float(scene["start"])
        ]
    else:
        segments = [(0.0, duration)]

    normalized: list[tuple[float, float]] = []
    for start, end in segments:
        cursor = start
        while cursor < end:
            chunk_end = min(end, cursor + max_clip_seconds)
            normalized.append((round(cursor, 3), round(chunk_end, 3)))
            if chunk_end >= end:
                break
            cursor = chunk_end
    return normalized


def suggest_clips(
    *,
    duration: float,
    scenes: list[dict] | None,
    silence_cuts: list[dict] | None,
    max_clips: int,
    min_clip_seconds: float,
    max_clip_seconds: float,
) -> list[ClipSuggestion]:
    """Build non-overlapping short-form clip suggestions."""
    scene_ranges = _normalize_segments(duration, scenes or [], max_clip_seconds)
    cuts = silence_cuts or []
    candidates: list[ClipSuggestion] = []
    target_duration = (min_clip_seconds + max_clip_seconds) / 2.0

    for start_index in range(len(scene_ranges)):
        clip_start = scene_ranges[start_index][0]
        clip_end = scene_ranges[start_index][1]
        scene_count = 1

        while True:
            clip_duration = clip_end - clip_start
            if min_clip_seconds <= clip_duration <= max_clip_seconds:
                silence_seconds = _overlap_seconds(clip_start, clip_end, cuts)
                speech_ratio = max(0.0, 1.0 - (silence_seconds / clip_duration if clip_duration else 0.0))
                duration_penalty = abs(clip_duration - target_duration) / max(target_duration, 1.0)
                score = round((speech_ratio * 100.0) + (scene_count * 4.0) - (duration_penalty * 10.0), 3)
                reason = (
                    f"{scene_count} scene(s), "
                    f"{speech_ratio:.0%} speech density, "
                    f"{silence_seconds:.1f}s silence"
                )
                candidates.append(
                    ClipSuggestion(
                        start=round(clip_start, 3),
                        end=round(clip_end, 3),
                        score=score,
                        scene_count=scene_count,
                        silence_seconds=round(silence_seconds, 3),
                        reason=reason,
                    )
                )

            next_index = start_index + scene_count
            if next_index >= len(scene_ranges):
                break

            next_end = scene_ranges[next_index][1]
            if next_end - clip_start > max_clip_seconds:
                capped_end = round(clip_start + max_clip_seconds, 3)
                capped_duration = capped_end - clip_start
                if min_clip_seconds <= capped_duration <= max_clip_seconds:
                    silence_seconds = _overlap_seconds(clip_start, capped_end, cuts)
                    speech_ratio = max(0.0, 1.0 - (silence_seconds / capped_duration if capped_duration else 0.0))
                    duration_penalty = abs(capped_duration - target_duration) / max(target_duration, 1.0)
                    score = round((speech_ratio * 100.0) + ((scene_count + 1) * 4.0) - (duration_penalty * 10.0), 3)
                    reason = (
                        f"{scene_count + 1} scene(s), "
                        f"{speech_ratio:.0%} speech density, "
                        f"{silence_seconds:.1f}s silence"
                    )
                    candidates.append(
                        ClipSuggestion(
                            start=round(clip_start, 3),
                            end=capped_end,
                            score=score,
                            scene_count=scene_count + 1,
                            silence_seconds=round(silence_seconds, 3),
                            reason=reason,
                        )
                    )
                break

            clip_end = next_end
            scene_count += 1

    ranked = sorted(candidates, key=lambda clip: (clip.end, clip.start, -clip.score))
    previous_non_overlap: list[int] = []
    for index, candidate in enumerate(ranked):
        previous = -1
        for probe in range(index - 1, -1, -1):
            prior = ranked[probe]
            if prior.end <= candidate.start:
                previous = probe
                break
        previous_non_overlap.append(previous)

    @lru_cache(maxsize=None)
    def choose(last_index: int, remaining: int) -> tuple[ClipSuggestion, ...]:
        if last_index < 0 or remaining <= 0:
            return ()

        skip = choose(last_index - 1, remaining)
        take_prev = previous_non_overlap[last_index]
        take = choose(take_prev, remaining - 1) + (ranked[last_index],)

        skip_score = sum(item.score for item in skip)
        take_score = sum(item.score for item in take)
        if len(take) > len(skip):
            return take
        if len(take) == len(skip) and take_score > skip_score:
            return take
        return skip

    selected = list(choose(len(ranked) - 1, max_clips))
    return sorted(selected, key=lambda clip: clip.start)
