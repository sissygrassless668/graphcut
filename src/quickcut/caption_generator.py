"""Generate and burn in subtitles (SRT/VTT/ASS) from transcripts."""

from __future__ import annotations

import logging
from pathlib import Path

from quickcut.models import CaptionStyle, Transcript, TranscriptWord

logger = logging.getLogger(__name__)


def _format_time(seconds: float, comma: bool = True) -> str:
    """Format time in HH:MM:SS,mmm or HH:MM:SS.mmm format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    sep = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


def _format_ass_time(seconds: float) -> str:
    """Format time in H:MM:SS.cs (centiseconds) format for ASS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{hours:1d}:{minutes:02d}:{secs:02d}.{cs:02d}"


class CaptionGenerator:
    """Generates subtitle files from transcripts for hardcoding or export."""

    def __init__(self, style: CaptionStyle) -> None:
        self.config = style

    def _chunk_words(self, words: list[TranscriptWord]) -> list[list[TranscriptWord]]:
        """Group words into logical subtitle chunks."""
        chunks = []
        current_chunk: list[TranscriptWord] = []
        
        for w in words:
            if not current_chunk:
                current_chunk.append(w)
                continue
                
            # Create a new chunk if we exceed max words
            if len(current_chunk) >= self.config.max_words_per_line:
                chunks.append(current_chunk)
                current_chunk = [w]
                continue
                
            # Create a new chunk if there's a long pause (>0.5s)
            if w.start - current_chunk[-1].end > 0.5:
                chunks.append(current_chunk)
                current_chunk = [w]
                continue
                
            # Create a new chunk on strong punctuation
            last_word = current_chunk[-1].word.strip()
            if last_word.endswith((".", "!", "?")):
                chunks.append(current_chunk)
                current_chunk = [w]
                continue
                
            current_chunk.append(w)
            
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def to_srt(self, transcript: Transcript, output_path: Path) -> Path:
        """Export transcript as SubRip Text (.srt)."""
        words = transcript.all_words
        chunks = self._chunk_words(words)
        
        with output_path.open("w", encoding="utf-8") as f:
            for i, chunk in enumerate(chunks, 1):
                start_str = _format_time(chunk[0].start, comma=True)
                end_str = _format_time(chunk[-1].end, comma=True)
                text = " ".join(w.word.strip() for w in chunk)
                
                f.write(f"{i}\n")
                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{text}\n\n")
                
        logger.info("Exported SRT captions to %s", output_path)
        return output_path

    def to_vtt(self, transcript: Transcript, output_path: Path) -> Path:
        """Export transcript as WebVTT (.vtt)."""
        words = transcript.all_words
        chunks = self._chunk_words(words)
        
        with output_path.open("w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for i, chunk in enumerate(chunks, 1):
                start_str = _format_time(chunk[0].start, comma=False)
                end_str = _format_time(chunk[-1].end, comma=False)
                text = " ".join(w.word.strip() for w in chunk)
                
                f.write(f"{i}\n")
                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{text}\n\n")
                
        logger.info("Exported VTT captions to %s", output_path)
        return output_path

    def to_ass(self, transcript: Transcript, output_path: Path) -> Path:
        """Export transcript as Advanced SubStation Alpha (.ass) for burn-in."""
        words = transcript.all_words
        chunks = self._chunk_words(words)
        
        # Decide styling based on config preset
        if self.config.style == "social":
            font = "Arial Black"
            font_size = 36
            bold = -1
            align = 5  # Middle Center
            border_style = 3  # Opaque box
            margin_v = 100
            primary = "&H00FFFFFF" # White
            outline = "&H80000000" # Black box background (half transparent)
            outline_width = 4
        else: # "clean"
            font = "Arial"
            font_size = 24
            bold = 0
            align = 2  # Bottom Center
            border_style = 1  # Outline + drop shadow
            margin_v = 50
            primary = "&H00FFFFFF"
            outline = "&H00000000"
            outline_width = 2

        ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{primary},&H000000FF,{outline},&H80000000,{bold},0,0,0,100,100,0,0,{border_style},{outline_width},1,{align},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        with output_path.open("w", encoding="utf-8") as f:
            f.write(ass_header)
            
            for chunk in chunks:
                start_str = _format_ass_time(chunk[0].start)
                end_str = _format_ass_time(chunk[-1].end)
                text = " ".join(w.word.strip() for w in chunk)
                
                # Default style, no specific name, margins 0000
                f.write(f"Dialogue: 0,{start_str},{end_str},Default,,0000,0000,0000,,{text}\n")
                
        logger.info("Generated ASS captions for burn-in at %s", output_path)
        return output_path

    def burn_in_filter(self, ass_path: Path) -> str:
        """Generate FFmpeg subtitles filter string."""
        # Windows paths need heavy escaping for FFmpeg filters
        # e.g., C:\path\to\subs.ass -> C\\:/path/to/subs.ass
        pth = str(ass_path.absolute()).replace("\\", "/")
        if ":" in pth and len(pth) > 1 and pth[1] == ":":
            # Escape Windows drive letter
            pth = f"{pth[0]}\\\\:{pth[2:]}"
            
        return f"subtitles='{pth}'"
