"""Unit tests for transcription models and transcript editing."""

from quickcut.models import Transcript, TranscriptSegment, TranscriptWord
from quickcut.transcript_editor import TranscriptEditor


def _make_transcript() -> Transcript:
    """Helper to build a test transcript."""
    return Transcript(
        segments=[
            TranscriptSegment(
                text="Hello world this is a test",
                start=0.0,
                end=3.0,
                words=[
                    TranscriptWord(word="Hello", start=0.0, end=0.5, confidence=0.95),
                    TranscriptWord(word="world", start=0.6, end=1.0, confidence=0.92),
                    TranscriptWord(word="this", start=1.5, end=1.8, confidence=0.90),
                    TranscriptWord(word="is", start=1.9, end=2.0, confidence=0.88),
                    TranscriptWord(word="a", start=2.1, end=2.2, confidence=0.85),
                    TranscriptWord(word="test", start=2.5, end=3.0, confidence=0.91),
                ],
            ),
        ],
        source_id="test_audio",
        model_name="medium",
        language="en",
        duration=3.0,
    )


def test_transcript_all_words():
    """Verify all_words flattens segments correctly."""
    t = _make_transcript()
    assert len(t.all_words) == 6
    assert t.all_words[0].word == "Hello"
    assert t.all_words[-1].word == "test"


def test_transcript_full_text():
    """Verify full_text concatenates segments."""
    t = _make_transcript()
    assert t.full_text == "Hello world this is a test"


def test_delete_words_returns_ranges():
    """Verify deleting specific word indices returns correct cut ranges."""
    t = _make_transcript()
    # Delete words at indices 2, 3 ("this", "is")
    cuts = TranscriptEditor.delete_words(t, [2, 3])
    assert len(cuts) == 2
    # "this" = 1.5-1.8, "is" = 1.9-2.0 (gap of 0.1s, no merge)
    assert cuts[0]["start"] == 1.5
    assert cuts[0]["end"] == 1.8
    assert cuts[1]["start"] == 1.9
    assert cuts[1]["end"] == 2.0


def test_delete_text_finds_occurrences():
    """Verify delete_text matches text and returns cut ranges."""
    t = _make_transcript()
    cuts = TranscriptEditor.delete_text(t, "this is")
    assert len(cuts) == 2
    assert cuts[0]["start"] == 1.5
    assert cuts[0]["end"] == 1.8


def test_remove_silences_finds_gaps():
    """Verify silence detection finds gaps between words."""
    t = _make_transcript()
    # Gap between "world" (end=1.0) and "this" (start=1.5) = 0.5s
    # With min_duration=0.3, this should be detected
    cuts = TranscriptEditor.remove_silences(t, min_duration=0.3, padding=0.1)
    assert len(cuts) >= 1


def test_merge_ranges_deduplicates():
    """Verify overlapping ranges are properly merged."""
    ranges = [
        {"start": 1.0, "end": 2.0},
        {"start": 1.5, "end": 3.0},
        {"start": 5.0, "end": 6.0},
    ]
    merged = TranscriptEditor._merge_ranges(ranges)
    assert len(merged) == 2
    assert merged[0]["start"] == 1.0
    assert merged[0]["end"] == 3.0
    assert merged[1]["start"] == 5.0


def test_preview_text_shows_strikethrough():
    """Verify preview text marks cut words with strikethrough."""
    t = _make_transcript()
    cuts = [{"start": 1.5, "end": 2.0}]
    preview = TranscriptEditor.get_preview_text(t, cuts)
    assert "~~this~~" in preview
    assert "~~is~~" in preview
    assert "Hello" in preview  # not cut
    assert "~~Hello~~" not in preview
