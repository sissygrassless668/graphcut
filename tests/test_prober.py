"""Unit tests for media prober and FFmpeg executor."""

from quickcut.ffmpeg_executor import FFmpegExecutor


def test_ffmpeg_executor_init():
    """Verify FFmpegExecutor finds ffmpeg binary."""
    executor = FFmpegExecutor()
    assert executor.ffmpeg_path.exists()
    assert executor.ffmpeg_path.name in ("ffmpeg", "ffmpeg.exe")


def test_encoder_detection():
    """Verify detect_encoders returns dict with at least libx264."""
    executor = FFmpegExecutor()
    encoders = executor.detect_encoders()
    
    assert isinstance(encoders, dict)
    assert "libx264" in encoders
    assert encoders["libx264"] is True  # libx264 should always be present


def test_best_encoder():
    """Verify get_best_encoder returns a string."""
    executor = FFmpegExecutor()
    best = executor.get_best_encoder()
    
    assert isinstance(best, str)
    assert len(best) > 0
    assert best in ("h264_videotoolbox", "h264_nvenc", "h264_qsv", "libx264")
