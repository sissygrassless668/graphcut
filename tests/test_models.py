"""Unit tests for GraphCut Pydantic models."""

from pathlib import Path

from graphcut.models import ClipRef, ExportPreset, MediaInfo, ProjectManifest


def test_media_info_creation():
    """Verify MediaInfo creates properly and stores fields."""
    info = MediaInfo(
        file_path=Path("video.mp4"),
        duration_seconds=10.5,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        audio_channels=2,
        audio_sample_rate=48000,
        file_size_bytes=1024,
        media_type="video",
    )
    assert info.file_path == Path("video.mp4")
    assert info.duration_seconds == 10.5
    assert info.width == 1920
    assert info.video_codec == "h264"


def test_project_manifest_defaults():
    """Verify ProjectManifest initializes with proper defaults."""
    manifest = ProjectManifest(name="Test Project")
    assert manifest.name == "Test Project"
    assert manifest.version == "1.0"
    assert manifest.sources == {}
    assert manifest.clip_order == []
    assert manifest.scenes == {}
    assert manifest.active_scene is None
    assert manifest.burn_captions is True
    assert len(manifest.export_presets) == 3
    assert manifest.export_presets[0].name == "YouTube"


def test_project_manifest_yaml_roundtrip(tmp_project_dir: Path):
    """Verify manifest can save to YAML and load back."""
    manifest = ProjectManifest(name="Roundtrip Test")
    
    # Add a dummy source
    manifest.sources["clip1"] = MediaInfo(
        file_path=Path("/tmp/test.mp4"),
        media_type="video",
    )
    manifest.clip_order.append(ClipRef(source_id="clip1"))
    
    yaml_path = tmp_project_dir / "project.yaml"
    manifest.save_yaml(yaml_path)
    
    assert yaml_path.exists()
    
    loaded = ProjectManifest.load_yaml(yaml_path)
    assert loaded.name == manifest.name
    assert loaded.version == manifest.version
    assert "clip1" in loaded.sources
    assert loaded.clip_order[0].source_id == "clip1"
    assert loaded.sources["clip1"].file_path == Path("/tmp/test.mp4")


def test_clip_ref_defaults():
    """Verify default transition is 'cut'."""
    clip = ClipRef(source_id="src1")
    assert clip.transition == "cut"
    assert clip.transition_duration == 0.5


def test_export_preset_defaults():
    """Verify default export presets exist within manifest."""
    manifest = ProjectManifest(name="Test Presets")
    presets = {p.name: p for p in manifest.export_presets}
    
    assert "YouTube" in presets
    assert presets["YouTube"].aspect_ratio == "16:9"
    
    assert "Shorts" in presets
    assert presets["Shorts"].aspect_ratio == "9:16"
    
    assert "Square" in presets
    assert presets["Square"].aspect_ratio == "1:1"
