"""Tests for audio normalization compatibility handling."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from graphcut.audio_normalizer import AudioNormalizer


def test_normalizer_omits_unsupported_ffmpeg_normalize_kwargs(monkeypatch, tmp_path: Path):
    """Older ffmpeg-normalize versions should still work without subtitle_codec support."""
    captured: dict[str, object] = {}

    class FakeFFmpegNormalize:
        def __init__(
            self,
            target_level,
            true_peak,
            loudness_range_target,
            audio_codec,
            audio_bitrate,
            video_codec,
        ) -> None:
            captured["kwargs"] = {
                "target_level": target_level,
                "true_peak": true_peak,
                "loudness_range_target": loudness_range_target,
                "audio_codec": audio_codec,
                "audio_bitrate": audio_bitrate,
                "video_codec": video_codec,
            }

        def add_media_file(self, input_path: str, output_path: str) -> None:
            captured["input_path"] = input_path
            captured["output_path"] = output_path

        def run_normalization(self) -> None:
            captured["ran"] = True

    fake_module = ModuleType("ffmpeg_normalize")
    fake_module.FFmpegNormalize = FakeFFmpegNormalize
    monkeypatch.setitem(sys.modules, "ffmpeg_normalize", fake_module)

    normalizer = AudioNormalizer()
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    input_path.write_bytes(b"demo")

    result = normalizer.normalize(input_path, output_path)

    assert result == output_path
    assert captured["kwargs"] == {
        "target_level": -23.0,
        "true_peak": -2.0,
        "loudness_range_target": 7.0,
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "video_codec": "copy",
    }
    assert captured["input_path"] == str(input_path)
    assert captured["output_path"] == str(output_path)
    assert captured["ran"] is True
