"""Tests for creator-facing content factory planning."""

from pathlib import Path

from click.testing import CliRunner

from graphcut.cli import cli
from graphcut.factory import plan_make, plan_repurpose
from graphcut.models import MediaInfo


def test_plan_make_applies_platform_duration_cap(tmp_path: Path):
    """Single-output plans should respect platform duration guidance."""
    source = tmp_path / "podcast.mp4"
    source.write_bytes(b"fake")
    info = MediaInfo(file_path=source, duration_seconds=120.0, media_type="video")

    plan = plan_make(source, platform_name="tiktok", media_info=info)

    assert len(plan.outputs) == 1
    assert plan.outputs[0].end == 60.0
    assert plan.warnings


def test_plan_repurpose_uses_scene_windows_and_relative_cuts(tmp_path: Path, monkeypatch):
    """Repurpose plans should emit multiple clips with relative silence cuts."""
    source = tmp_path / "episode.mp4"
    source.write_bytes(b"fake")
    info = MediaInfo(file_path=source, duration_seconds=90.0, media_type="video")

    monkeypatch.setattr(
        "graphcut.factory._detect_scenes_for_file",
        lambda file_info, threshold: (
            [
                {"start": 0.0, "end": 15.0},
                {"start": 15.0, "end": 30.0},
                {"start": 30.0, "end": 50.0},
                {"start": 50.0, "end": 70.0},
            ],
            [],
        ),
    )
    monkeypatch.setattr(
        "graphcut.factory._detect_silences_for_file",
        lambda file_info, min_duration: (
            [{"start": 18.0, "end": 19.0}, {"start": 55.0, "end": 56.0}],
            [],
        ),
    )

    plan = plan_repurpose(
        source,
        platform_name="shorts",
        clips=2,
        min_clip_seconds=20.0,
        max_clip_seconds=35.0,
        remove_silence=True,
        media_info=info,
    )

    assert len(plan.outputs) == 2
    assert plan.outputs[0].filename.endswith(".mp4")
    assert all(output.duration <= 35.0 for output in plan.outputs)


def test_cli_preview_json_uses_factory_plan(tmp_path: Path, monkeypatch):
    """Preview should surface a machine-readable plan."""
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake")

    monkeypatch.setattr(
        "graphcut.factory.probe_file",
        lambda path: MediaInfo(file_path=path, duration_seconds=42.0, media_type="video"),
    )
    monkeypatch.setattr(
        "graphcut.factory._detect_scenes_for_file",
        lambda file_info, threshold: ([{"start": 0.0, "end": 21.0}, {"start": 21.0, "end": 42.0}], []),
    )
    monkeypatch.setattr(
        "graphcut.factory._detect_silences_for_file",
        lambda file_info, min_duration: ([], []),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["preview", str(source), "--json"])

    assert result.exit_code == 0
    assert '"mode": "repurpose"' in result.output
    assert '"outputs"' in result.output
