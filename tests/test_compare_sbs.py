"""Tests for compare_sbs — manifest parsing, pair analysis, and result models.

All rendering tests patch the thin ``_moviepy_*`` wrappers so no real video
I/O or FFmpeg binary is required.  Integration tests that produce actual video
are marked ``@pytest.mark.integration`` and skipped in CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from graphcut.compare_sbs import (
    ClipPair,
    ClipSegment,
    ComparisonResult,
    FreezeInfo,
    ManifestOptions,
    PairResult,
    SBSManifest,
    _analyze_pair,
    load_pairs_manifest,
    run_compare_sbs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "pairs.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def _simple_manifest_data(source: str | None = None) -> dict:
    pair: dict = {
        "id": "pair-a",
        "title": "Feature A",
        "before": {"label": "Before", "in": 0.0, "out": 10.0},
        "after": {"label": "After", "in": 20.0, "out": 25.0},
    }
    if source:
        pair["before"]["source"] = source
        pair["after"]["source"] = source
    return {
        "pairs": [pair],
        "options": {"layout": "horizontal", "gap_between_pairs": 0.5},
    }


# ---------------------------------------------------------------------------
# FakeClip — minimal stand-in for a MoviePy VideoClip
# ---------------------------------------------------------------------------

class FakeClip:
    def __init__(self, duration: float = 5.0, size: tuple[int, int] = (960, 540)):
        self.duration = duration
        self.size = size
        self.audio = None

    def subclipped(self, start: float, end: float) -> "FakeClip":
        return FakeClip(duration=end - start, size=self.size)

    def with_effects(self, _effects: list) -> "FakeClip":
        return self

    def with_duration(self, duration: float) -> "FakeClip":
        return FakeClip(duration=duration, size=self.size)

    def with_position(self, _pos: Any) -> "FakeClip":
        return self

    def with_audio(self, audio: Any) -> "FakeClip":
        self.audio = audio
        return self

    def without_audio(self) -> "FakeClip":
        self.audio = None
        return self

    def to_ImageClip(self, t: float = 0.0) -> "FakeClip":
        return self

    def write_videofile(self, path: str, **_kwargs: Any) -> None:
        Path(path).touch()


def _fake_concat(clips: list, **_kw: Any) -> FakeClip:
    return FakeClip(duration=sum(c.duration for c in clips))


def _fake_clips_array(grid: list) -> FakeClip:
    flat = [c for row in grid for c in row]
    return FakeClip(duration=max(c.duration for c in flat) if flat else 0.0)


def _fake_color_clip(size: Any, color: Any, duration: float) -> FakeClip:
    return FakeClip(duration=duration, size=size)


def _fake_composite(clips: list, size: Any) -> FakeClip:
    return FakeClip(duration=max(c.duration for c in clips), size=size)


# ---------------------------------------------------------------------------
# ClipSegment validation
# ---------------------------------------------------------------------------

class TestClipSegment:
    def test_valid_segment(self):
        seg = ClipSegment(label="Before", **{"in": 0.0, "out": 12.0})
        assert seg.duration == pytest.approx(12.0)

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError, match="out"):
            ClipSegment(label="Bad", **{"in": 10.0, "out": 5.0})

    def test_equal_in_out_raises(self):
        with pytest.raises(ValueError):
            ClipSegment(label="Bad", **{"in": 5.0, "out": 5.0})

    def test_populate_by_name(self):
        seg = ClipSegment(label="X", in_point=1.0, out_point=3.0)
        assert seg.duration == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# SBSManifest model
# ---------------------------------------------------------------------------

class TestSBSManifest:
    def test_full_manifest_parses(self):
        data = _simple_manifest_data()
        manifest = SBSManifest.model_validate(data)

        assert len(manifest.pairs) == 1
        pair = manifest.pairs[0]
        assert pair.id == "pair-a"
        assert pair.before.duration == pytest.approx(10.0)
        assert pair.after.duration == pytest.approx(5.0)
        assert manifest.options.gap_between_pairs == pytest.approx(0.5)

    def test_default_options(self):
        data = {"pairs": [_simple_manifest_data()["pairs"][0]]}
        manifest = SBSManifest.model_validate(data)
        assert manifest.options.layout == "horizontal"
        assert manifest.options.gap_between_pairs == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# load_pairs_manifest
# ---------------------------------------------------------------------------

class TestLoadPairsManifest:
    def test_loads_from_yaml(self, tmp_path):
        src = tmp_path / "video.mp4"
        src.touch()
        yaml_path = _write_yaml(tmp_path, _simple_manifest_data(str(src)))
        manifest = load_pairs_manifest(yaml_path)
        assert len(manifest.pairs) == 1
        assert manifest.pairs[0].before.source == src

    def test_fills_primary_source_when_missing(self, tmp_path):
        data = {
            "pairs": [
                {
                    "id": "p1",
                    "title": "T",
                    "before": {"in": 0.0, "out": 5.0},
                    "after": {"in": 10.0, "out": 15.0},
                }
            ]
        }
        yaml_path = _write_yaml(tmp_path, data)
        primary = tmp_path / "main.mp4"
        primary.touch()

        manifest = load_pairs_manifest(yaml_path, primary_source=primary)
        assert manifest.pairs[0].before.source == primary
        assert manifest.pairs[0].after.source == primary

    def test_raises_if_no_source_and_no_primary(self, tmp_path):
        data = {
            "pairs": [
                {
                    "id": "p1",
                    "title": "T",
                    "before": {"in": 0.0, "out": 5.0},
                    "after": {"in": 10.0, "out": 15.0},
                }
            ]
        }
        yaml_path = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="no primary source"):
            load_pairs_manifest(yaml_path, primary_source=None)


# ---------------------------------------------------------------------------
# _analyze_pair
# ---------------------------------------------------------------------------

class TestAnalyzePair:
    def _pair(self, before_dur: float, after_dur: float) -> ClipPair:
        return ClipPair(
            id="test",
            title="Test",
            before=ClipSegment(label="B", in_point=0.0, out_point=before_dur),
            after=ClipSegment(label="A", in_point=0.0, out_point=after_dur),
        )

    def test_equal_durations_no_freeze(self):
        pair = self._pair(10.0, 10.0)
        out_dur, freeze, warns = _analyze_pair(pair, "last-frame")
        assert out_dur == pytest.approx(10.0)
        assert freeze.side == "none"
        assert freeze.duration == pytest.approx(0.0)
        assert warns == []

    def test_before_shorter_freeze_before(self):
        pair = self._pair(8.0, 12.0)
        out_dur, freeze, warns = _analyze_pair(pair, "last-frame")
        assert out_dur == pytest.approx(12.0)
        assert freeze.side == "before"
        assert freeze.duration == pytest.approx(4.0)
        assert freeze.mode == "last-frame"

    def test_after_shorter_freeze_after(self):
        pair = self._pair(15.0, 10.0)
        out_dur, freeze, warns = _analyze_pair(pair, "black")
        assert out_dur == pytest.approx(15.0)
        assert freeze.side == "after"
        assert freeze.duration == pytest.approx(5.0)
        assert freeze.mode == "black"

    def test_freeze_none_trims_to_min(self):
        pair = self._pair(20.0, 8.0)
        out_dur, freeze, warns = _analyze_pair(pair, "none")
        assert out_dur == pytest.approx(8.0)
        assert freeze.side == "none"

    def test_large_mismatch_warning(self):
        pair = self._pair(4.0, 25.0)
        _, _, warns = _analyze_pair(pair, "last-frame")
        assert "large_duration_mismatch" in warns

    def test_no_warning_for_small_mismatch(self):
        pair = self._pair(10.0, 15.0)
        _, _, warns = _analyze_pair(pair, "last-frame")
        assert warns == []


# ---------------------------------------------------------------------------
# ComparisonResult serialization
# ---------------------------------------------------------------------------

class TestComparisonResult:
    def _make_result(self) -> ComparisonResult:
        r = ComparisonResult(input_source="src.mp4", output="out.mp4")
        r.pairs = [
            PairResult(
                id="p1",
                title="Feature A",
                before_duration=10.0,
                after_duration=8.0,
                output_duration=10.0,
                freeze=FreezeInfo("after", "last-frame", 2.0),
                warnings=[],
            ),
            PairResult(
                id="p2",
                title="Feature B",
                before_duration=5.0,
                after_duration=12.0,
                output_duration=12.0,
                freeze=FreezeInfo("before", "black", 7.0),
                warnings=["large_duration_mismatch"],
            ),
        ]
        r.total_output_duration = 22.0
        return r

    def test_to_dict_structure(self):
        result = self._make_result()
        d = result.to_dict()
        assert d["input"] == "src.mp4"
        assert d["output"] == "out.mp4"
        assert len(d["pairs"]) == 2
        assert d["total_output_duration"] == 22.0
        assert d["pairs"][0]["freeze"]["side"] == "after"
        assert d["pairs"][1]["warnings"] == ["large_duration_mismatch"]

    def test_to_dict_is_json_serialisable(self):
        d = self._make_result().to_dict()
        serialised = json.dumps(d)
        assert "Feature A" in serialised

    def test_to_markdown_table(self):
        md = self._make_result().to_markdown_table()
        assert "p1" in md
        assert "Feature A" in md
        assert "**Total output duration:**" in md
        assert "---" in md

    def test_to_markdown_table_after_freeze_side(self):
        md = self._make_result().to_markdown_table()
        assert "after" in md


# ---------------------------------------------------------------------------
# run_compare_sbs — mocked via _moviepy_* wrappers + _build_pair_clip
# ---------------------------------------------------------------------------

def _make_fake_build(freeze_mode_: str = "last-frame") -> Any:
    """Return a _build_pair_clip side_effect that uses real _analyze_pair."""
    def _build(pair, layout, freeze_mode, audio_mode, canvas_w, canvas_h):
        out_dur, freeze, warnings = _analyze_pair(pair, freeze_mode)
        pr = PairResult(
            id=pair.id,
            title=pair.title,
            before_duration=round(pair.before.duration, 3),
            after_duration=round(pair.after.duration, 3),
            output_duration=round(out_dur, 3),
            freeze=freeze,
            warnings=warnings,
        )
        return FakeClip(duration=out_dur), pr
    return _build


def _run_with_mocks(
    tmp_path: Path,
    pairs_data: dict,
    **kwargs: Any,
) -> ComparisonResult:
    src = tmp_path / "source.mp4"
    src.touch()
    yaml_path = _write_yaml(tmp_path, pairs_data)
    output = tmp_path / "out.mp4"

    with (
        patch("graphcut.compare_sbs._import_moviepy", return_value=None),
        patch("graphcut.compare_sbs._build_pair_clip", side_effect=_make_fake_build()),
        patch("graphcut.compare_sbs._moviepy_concat", side_effect=_fake_concat),
        patch("graphcut.compare_sbs._moviepy_color_clip", side_effect=_fake_color_clip),
    ):
        final_clip = FakeClip()

        # Patch write_videofile on whatever _moviepy_concat returns
        def _concat_with_write(clips, **kw):
            clip = _fake_concat(clips, **kw)
            clip.write_videofile = lambda path, **_: Path(path).touch()
            return clip

        with patch("graphcut.compare_sbs._moviepy_concat", side_effect=_concat_with_write):
            return run_compare_sbs(
                primary_source=src,
                pairs_manifest=yaml_path,
                output=output,
                **kwargs,
            )


class TestRunCompareSbs:
    def test_single_pair_produces_result(self, tmp_path):
        data = _simple_manifest_data()
        result = _run_with_mocks(tmp_path, data)
        assert len(result.pairs) == 1
        assert result.pairs[0].id == "pair-a"

    def test_total_duration_includes_gap(self, tmp_path):
        data = _simple_manifest_data()
        # Add a second pair (before=10s, after=8s → output=10s)
        data["pairs"].append({
            "id": "pair-b",
            "title": "Feature B",
            "before": {"in": 30.0, "out": 40.0},
            "after": {"in": 50.0, "out": 58.0},
        })
        result = _run_with_mocks(tmp_path, data, gap_between_pairs=1.0)
        # pair-a: 10s, pair-b: 10s, one gap: 1s → total 21s
        assert result.total_output_duration == pytest.approx(21.0, abs=0.1)

    def test_freeze_mode_passed_to_build(self, tmp_path):
        captured: list[str] = []

        def _build_capture(pair, layout, freeze_mode, audio_mode, canvas_w, canvas_h):
            captured.append(freeze_mode)
            return _make_fake_build()(pair, layout, freeze_mode, audio_mode, canvas_w, canvas_h)

        src = tmp_path / "source.mp4"
        src.touch()
        yaml_path = _write_yaml(tmp_path, _simple_manifest_data(str(src)))
        output = tmp_path / "out.mp4"

        with (
            patch("graphcut.compare_sbs._import_moviepy", return_value=None),
            patch("graphcut.compare_sbs._build_pair_clip", side_effect=_build_capture),
            patch("graphcut.compare_sbs._moviepy_color_clip", side_effect=_fake_color_clip),
        ):
            def _concat_write(clips, **kw):
                c = _fake_concat(clips, **kw)
                c.write_videofile = lambda path, **_: Path(path).touch()
                return c

            with patch("graphcut.compare_sbs._moviepy_concat", side_effect=_concat_write):
                run_compare_sbs(
                    primary_source=src,
                    pairs_manifest=yaml_path,
                    output=output,
                    freeze_mode="black",
                )
        assert "black" in captured

    def test_layout_passed_to_build(self, tmp_path):
        captured: list[str] = []

        def _build_capture(pair, layout, freeze_mode, audio_mode, canvas_w, canvas_h):
            captured.append(layout)
            return _make_fake_build()(pair, layout, freeze_mode, audio_mode, canvas_w, canvas_h)

        src = tmp_path / "source.mp4"
        src.touch()
        yaml_path = _write_yaml(tmp_path, _simple_manifest_data(str(src)))
        output = tmp_path / "out.mp4"

        with (
            patch("graphcut.compare_sbs._import_moviepy", return_value=None),
            patch("graphcut.compare_sbs._build_pair_clip", side_effect=_build_capture),
            patch("graphcut.compare_sbs._moviepy_color_clip", side_effect=_fake_color_clip),
        ):
            def _concat_write(clips, **kw):
                c = _fake_concat(clips, **kw)
                c.write_videofile = lambda path, **_: Path(path).touch()
                return c

            with patch("graphcut.compare_sbs._moviepy_concat", side_effect=_concat_write):
                run_compare_sbs(
                    primary_source=src,
                    pairs_manifest=yaml_path,
                    output=output,
                    layout="vertical",
                )
        assert "vertical" in captured

    def test_empty_manifest_raises(self, tmp_path):
        yaml_path = _write_yaml(tmp_path, {"pairs": []})
        with (
            patch("graphcut.compare_sbs._import_moviepy", return_value=None),
            pytest.raises(ValueError, match="empty"),
        ):
            run_compare_sbs(
                primary_source=tmp_path / "src.mp4",
                pairs_manifest=yaml_path,
                output=tmp_path / "out.mp4",
            )

    def test_output_dict_is_valid_json(self, tmp_path):
        result = _run_with_mocks(tmp_path, _simple_manifest_data())
        parsed = json.loads(json.dumps(result.to_dict()))
        assert parsed["pairs"][0]["id"] == "pair-a"

    def test_markdown_report_from_result(self, tmp_path):
        result = _run_with_mocks(tmp_path, _simple_manifest_data())
        md = result.to_markdown_table()
        assert "pair-a" in md
        assert "**Total output duration:**" in md
