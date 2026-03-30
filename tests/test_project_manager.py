"""Tests for project manager source deletion behavior."""

from pathlib import Path

from graphcut.models import ClipRef, MediaInfo, ProjectManifest
from graphcut.project_manager import ProjectManager


def test_remove_source_cleans_manifest_references(tmp_project_dir: Path):
    """Removing a source should also clear clip and role references."""
    media_path = tmp_project_dir / "media" / "clip.mp4"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"test")

    manifest = ProjectManifest(name="demo")
    manifest.sources["clip"] = MediaInfo(file_path=media_path, media_type="video")
    manifest.clip_order = [ClipRef(source_id="clip")]
    manifest.narration = "clip"
    manifest.music = "clip"

    deleted = ProjectManager.remove_source(manifest, "clip")

    assert deleted is False
    assert "clip" not in manifest.sources
    assert manifest.clip_order == []
    assert manifest.narration is None
    assert manifest.music is None


def test_remove_source_can_delete_project_file(tmp_project_dir: Path):
    """Deleting with delete_file=True should remove local project media."""
    media_path = tmp_project_dir / "media" / "clip.mp4"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"test")

    manifest = ProjectManifest(name="demo")
    manifest.sources["clip"] = MediaInfo(file_path=media_path, media_type="video")

    deleted = ProjectManager.remove_source(
        manifest,
        "clip",
        delete_file=True,
        project_dir=tmp_project_dir,
    )

    assert deleted is True
    assert media_path.exists() is False


def test_remove_source_skips_file_outside_project(tmp_path: Path):
    """Deletion should not remove files outside the active project root."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    external_file = tmp_path / "outside.mp4"
    external_file.write_bytes(b"test")

    manifest = ProjectManifest(name="demo")
    manifest.sources["external"] = MediaInfo(file_path=external_file, media_type="video")

    deleted = ProjectManager.remove_source(
        manifest,
        "external",
        delete_file=True,
        project_dir=project_dir,
    )

    assert deleted is False
    assert external_file.exists() is True
