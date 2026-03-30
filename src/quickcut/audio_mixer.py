"""Audio mixing and ducking using FFmpeg filtergraphs."""

from __future__ import annotations

import logging

from quickcut.filtergraph import FilterGraph
from quickcut.models import AudioMix

logger = logging.getLogger(__name__)


class AudioMixer:
    """Builds audio filtergraphs with ducking and per-track gains."""

    def __init__(self, mix_config: AudioMix) -> None:
        self.config = mix_config

    def build_audio_graph(
        self,
        fg: FilterGraph,
        source_labels: list[str],
        narration_label: str | None = None,
        music_label: str | None = None,
    ) -> str:
        """Construct the audio mixing graph.
        
        Args:
            fg: The active FilterGraph instance.
            source_labels: Labels of all primary video/audio tracks.
            narration_label: Optional label for voice-over track.
            music_label: Optional label for background music track.
            
        Returns:
            The output label of the final mixed audio stream.
        """
        active_sources: list[str] = []

        # 1. Process primary source audio
        for label in source_labels:
            if self.config.source_gain_db != 0.0:
                label = fg.volume(label, self.config.source_gain_db)
            active_sources.append(label)

        # 2. Process Narration
        processed_narration = None
        if narration_label:
            lbl = narration_label
            if self.config.narration_gain_db != 0.0:
                lbl = fg.volume(lbl, self.config.narration_gain_db)
            processed_narration = lbl
            active_sources.append(lbl)

        # 3. Process Music with ducking
        if music_label:
            lbl = music_label
            if self.config.music_gain_db != 0.0:
                lbl = fg.volume(lbl, self.config.music_gain_db)
                
            if processed_narration and self.config.ducking_strength > 0:
                # Calculate threshold based on silence_threshold.
                # Threshold for sidechaincompress is typically quite low (e.g. 0.01-0.08)
                # Map ducking_strength (0.0=min, 1.0=max) to ratio (1 to 20)
                duck_ratio = 1.0 + (19.0 * self.config.ducking_strength)
                
                logger.debug(
                    "Applying ducking to music: ratio=%.1f based on strength=%.2f",
                    duck_ratio, self.config.ducking_strength
                )
                lbl = fg.sidechaincompress(
                    main_label=lbl,
                    sidechain_label=processed_narration,
                    threshold=0.08,  # kick in when narration is present
                    ratio=duck_ratio,
                    attack=200.0,
                    release=1000.0,
                )
                
            active_sources.append(lbl)
            
        # 4. Final Mix
        if not active_sources:
            # Fallback if no audio exists at all (handle gracefully)
            return "0:a" 

        if len(active_sources) == 1:
            return active_sources[0]
            
        # Mix them all down. For amix, keeping weights equal since we applied 
        # separate volume filters beforehand. The filter naturally reduces total 
        # volume based on N inputs to prevent clipping. 
        # But we want to maintain the specific volumes we set, so we can set weights=1 
        # However, amix still averages them.
        weights = [1.0] * len(active_sources)
        return fg.amix(active_sources, weights=weights)

    def _apply_music_loop(self, fg: FilterGraph, music_label: str, target_duration: float) -> str:
        """Loop and trim music track to match timeline duration."""
        looped = fg.aloop(music_label, loop_count=-1)
        trimmed = fg.atrim(looped, start=0.0, end=target_duration)
        return trimmed
