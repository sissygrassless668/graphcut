"""Tests for repurposing clip suggestion heuristics."""

from graphcut.clip_selector import suggest_clips


def test_suggest_clips_returns_non_overlapping_ranked_windows():
    """Suggestions should respect duration bounds and not overlap."""
    scenes = [
        {"start": 0.0, "end": 10.0},
        {"start": 10.0, "end": 22.0},
        {"start": 22.0, "end": 34.0},
        {"start": 34.0, "end": 48.0},
    ]
    silence_cuts = [
        {"start": 4.0, "end": 5.0},
        {"start": 28.0, "end": 29.0},
    ]

    clips = suggest_clips(
        duration=48.0,
        scenes=scenes,
        silence_cuts=silence_cuts,
        max_clips=2,
        min_clip_seconds=15.0,
        max_clip_seconds=25.0,
    )

    assert len(clips) == 2
    assert all(15.0 <= clip.duration <= 25.0 for clip in clips)
    assert clips[0].end <= clips[1].start


def test_suggest_clips_falls_back_to_chunking_long_scenes():
    """A long scene should still produce chunkable candidates."""
    clips = suggest_clips(
        duration=70.0,
        scenes=[{"start": 0.0, "end": 70.0}],
        silence_cuts=[],
        max_clips=3,
        min_clip_seconds=15.0,
        max_clip_seconds=30.0,
    )

    assert clips
    assert all(clip.duration <= 30.0 for clip in clips)
