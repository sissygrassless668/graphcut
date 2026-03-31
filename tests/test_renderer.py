"""Renderer tests for timeline transitions and encoder fallback."""

from pathlib import Path

from graphcut.ffmpeg_executor import FFmpegError
from graphcut.models import AudioMix, ClipRef, MediaInfo, ProjectManifest
from graphcut.renderer import Renderer


class DummyExecutor:
    def __init__(self) -> None:
        self.args = None
        self.calls: list[list[str]] = []
        self.duration = None

    def get_best_encoder(self, preferred: str | None = None) -> str:
        if preferred:
            return preferred
        return "libx264"

    def run(self, args, progress_callback=None, duration=None) -> None:
        self.args = list(args)
        self.calls.append(list(args))
        self.duration = duration

    def should_retry_with_software(self, encoder: str, error: FFmpegError) -> bool:
        return False


class FlakyHardwareExecutor(DummyExecutor):
    def get_best_encoder(self, preferred: str | None = None) -> str:
        if preferred:
            return preferred
        return "h264_nvenc"

    def run(self, args, progress_callback=None, duration=None) -> None:
        self.args = list(args)
        self.calls.append(list(args))
        self.duration = duration
        if len(self.calls) == 1:
            raise FFmpegError(
                "FFmpeg failed: nvenc init",
                returncode=1,
                stderr="Could not open encoder before EOF",
                cmd=list(args),
            )

    def should_retry_with_software(self, encoder: str, error: FFmpegError) -> bool:
        return encoder == "h264_nvenc" and "could not open encoder" in error.stderr.lower()


def test_renderer_builds_xfade_for_transition(tmp_path: Path):
    """A clip transition should emit xfade/acrossfade filters instead of plain concat."""
    executor = DummyExecutor()
    renderer = Renderer(executor=executor)
    manifest = ProjectManifest(name="Transition Test")
    manifest.audio_mix = AudioMix(normalize=False)
    manifest.sources = {
        "a": MediaInfo(file_path=Path("a.mp4"), duration_seconds=1.0, media_type="video"),
        "b": MediaInfo(file_path=Path("b.mp4"), duration_seconds=1.0, media_type="video"),
    }
    manifest.clip_order = [
        ClipRef(source_id="a", trim_start=0.0, trim_end=1.0, transition="fade", transition_duration=0.4),
        ClipRef(source_id="b", trim_start=0.0, trim_end=1.0),
    ]

    renderer.render(manifest, tmp_path / "out.mp4")

    assert executor.args is not None
    graph_str = executor.args[executor.args.index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=0.4:offset=0.6" in graph_str
    assert "acrossfade=d=0.4" in graph_str
    assert executor.duration == 1.6


def test_renderer_retries_with_libx264_after_hw_encoder_failure(tmp_path: Path):
    """A failed hardware encoder init should transparently retry with software encoding."""
    executor = FlakyHardwareExecutor()
    renderer = Renderer(executor=executor)
    manifest = ProjectManifest(name="Fallback Test")
    manifest.audio_mix = AudioMix(normalize=False)
    manifest.sources = {
        "a": MediaInfo(file_path=Path("a.mp4"), duration_seconds=1.0, media_type="video"),
    }
    manifest.clip_order = [
        ClipRef(source_id="a", trim_start=0.0, trim_end=1.0),
    ]

    renderer.render(manifest, tmp_path / "out.mp4")

    assert len(executor.calls) == 2
    assert executor.calls[0][executor.calls[0].index("-c:v") + 1] == "h264_nvenc"
    assert executor.calls[1][executor.calls[1].index("-c:v") + 1] == "libx264"
