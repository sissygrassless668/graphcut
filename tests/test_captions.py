"""Unit tests for the caption and subtitle generator."""

import pytest
from pathlib import Path
from quickcut.models import CaptionStyle, Transcript, TranscriptWord, TranscriptSegment
from quickcut.caption_generator import CaptionGenerator


@pytest.fixture
def mock_transcript():
    """Provides a basic Transcript model."""
    w1 = TranscriptWord(word="Hello", start=0.0, end=0.4)
    w2 = TranscriptWord(word="world.", start=0.5, end=1.0)
    w3 = TranscriptWord(word="This", start=2.0, end=2.4)
    w4 = TranscriptWord(word="is", start=2.5, end=2.8)
    w5 = TranscriptWord(word="QuickCut.", start=2.9, end=3.5)
    
    seg1 = TranscriptSegment(text="Hello world.", start=0.0, end=1.0, words=[w1, w2])
    seg2 = TranscriptSegment(text="This is QuickCut.", start=2.0, end=3.5, words=[w3, w4, w5])
    
    return Transcript(segments=[seg1, seg2], source_id="test_01", duration=4.0)


def test_srt_generation(tmp_path: Path, mock_transcript: Transcript):
    """Verify SRT format is generated correctly."""
    style = CaptionStyle(max_words_per_line=4)
    cg = CaptionGenerator(style)
    
    out = tmp_path / "test.srt"
    cg.to_srt(mock_transcript, out)
    
    assert out.exists()
    content = out.read_text("utf-8")
    
    # Check SRT headers and timestamps
    assert "1\n" in content
    assert "00:00:00,000 --> 00:00:01,000" in content
    assert "Hello world." in content
    assert "00:00:02,000 --> 00:00:03,500" in content


def test_vtt_generation(tmp_path: Path, mock_transcript: Transcript):
    """Verify VTT has correct header and separators."""
    style = CaptionStyle(max_words_per_line=4)
    cg = CaptionGenerator(style)
    
    out = tmp_path / "test.vtt"
    cg.to_vtt(mock_transcript, out)
    
    content = out.read_text("utf-8")
    assert content.startswith("WEBVTT")
    # VTT uses '.' for milliseconds
    assert "00:00:00.000 --> 00:00:01.000" in content


def test_caption_word_chunking(mock_transcript: Transcript):
    """Verify words are split according to rules (max words, punctuation)."""
    # Force max words to 2
    style = CaptionStyle(max_words_per_line=2)
    cg = CaptionGenerator(style)
    
    chunks = cg._chunk_words(mock_transcript.all_words)
    assert len(chunks) == 3 
    
    assert [w.word for w in chunks[0]] == ["Hello", "world."]
    assert [w.word for w in chunks[1]] == ["This", "is"]
    assert [w.word for w in chunks[2]] == ["QuickCut."]
