"""Transcript-based editing — convert word deletions to time-range cuts."""

from __future__ import annotations

import logging
from quickcut.models import ProjectManifest, Transcript

logger = logging.getLogger(__name__)


class TranscriptEditor:
    """Converts transcript word operations into timeline cut ranges."""

    @staticmethod
    def delete_words(transcript: Transcript, word_indices: list[int]) -> list[dict]:
        """Given word indices to remove, return merged time ranges to cut.

        Args:
            transcript: The source transcript.
            word_indices: Indices into transcript.all_words to remove.

        Returns:
            List of {"start": float, "end": float} dicts.
        """
        all_words = transcript.all_words
        if not word_indices:
            return []

        # Sort and validate indices
        valid = sorted(set(i for i in word_indices if 0 <= i < len(all_words)))
        if not valid:
            return []

        # Build raw ranges from word timings
        raw_ranges: list[dict] = []
        for idx in valid:
            w = all_words[idx]
            raw_ranges.append({"start": w.start, "end": w.end})

        return TranscriptEditor._merge_ranges(raw_ranges)

    @staticmethod
    def delete_text(transcript: Transcript, text: str) -> list[dict]:
        """Find all occurrences of text in transcript, return time ranges to cut.

        Args:
            transcript: The source transcript.
            text: Text string to search for and remove.

        Returns:
            List of {"start": float, "end": float} dicts.
        """
        text_lower = text.lower().strip()
        all_words = transcript.all_words
        indices: list[int] = []

        # Simple word-by-word matching
        search_words = text_lower.split()
        if not search_words:
            return []

        for i in range(len(all_words) - len(search_words) + 1):
            match = True
            for j, sw in enumerate(search_words):
                # Strip punctuation for comparison
                word_clean = all_words[i + j].word.lower().strip(".,!?;:'\"")
                if word_clean != sw.strip(".,!?;:'\""):
                    match = False
                    break
            if match:
                indices.extend(range(i, i + len(search_words)))

        return TranscriptEditor.delete_words(transcript, indices)

    @staticmethod
    def remove_silences(
        transcript: Transcript, min_duration: float = 1.0, padding: float = 0.3
    ) -> list[dict]:
        """Find gaps between spoken words longer than min_duration.

        Args:
            transcript: The source transcript.
            min_duration: Minimum silence duration to consider (seconds).
            padding: Time to keep on each side of the gap (seconds).

        Returns:
            List of {"start": float, "end": float} dicts representing silence cuts.
        """
        all_words = transcript.all_words
        if len(all_words) < 2:
            return []

        ranges: list[dict] = []
        for i in range(len(all_words) - 1):
            gap_start = all_words[i].end
            gap_end = all_words[i + 1].start
            gap_duration = gap_end - gap_start

            if gap_duration >= min_duration:
                # Keep padding on each side
                cut_start = gap_start + padding
                cut_end = gap_end - padding
                if cut_end > cut_start:
                    ranges.append({
                        "start": round(cut_start, 3),
                        "end": round(cut_end, 3),
                    })

        return TranscriptEditor._merge_ranges(ranges)

    @staticmethod
    def apply_cuts(manifest: ProjectManifest, cuts: list[dict]) -> None:
        """Add cut ranges to the project manifest.

        Args:
            manifest: The project manifest to update.
            cuts: List of {"start": float, "end": float} time ranges.
        """
        manifest.transcript_cuts.extend(cuts)
        # Merge any overlapping cuts
        manifest.transcript_cuts = TranscriptEditor._merge_ranges(
            manifest.transcript_cuts
        )
        logger.info("Applied %d cuts to manifest", len(cuts))

    @staticmethod
    def get_preview_text(transcript: Transcript, cuts: list[dict]) -> str:
        """Return transcript text with deleted sections shown as ~~strikethrough~~.

        Args:
            transcript: The source transcript.
            cuts: List of {"start": float, "end": float} time ranges.

        Returns:
            Annotated transcript string.
        """
        result_parts: list[str] = []
        for word in transcript.all_words:
            is_cut = any(
                cut["start"] <= word.start and word.end <= cut["end"]
                for cut in cuts
            )
            if is_cut:
                result_parts.append(f"~~{word.word}~~")
            else:
                result_parts.append(word.word)

        return " ".join(result_parts)

    @staticmethod
    def _merge_ranges(ranges: list[dict]) -> list[dict]:
        """Merge overlapping or adjacent time ranges."""
        if not ranges:
            return []

        sorted_ranges = sorted(ranges, key=lambda r: r["start"])
        merged: list[dict] = [sorted_ranges[0].copy()]

        for r in sorted_ranges[1:]:
            if r["start"] <= merged[-1]["end"] + 0.01:  # tiny epsilon for float rounding
                merged[-1]["end"] = max(merged[-1]["end"], r["end"])
            else:
                merged.append(r.copy())

        return merged
