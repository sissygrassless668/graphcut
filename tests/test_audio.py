"""Unit tests for the audio mixer and filtergraph components."""

from quickcut.models import AudioMix
from quickcut.audio_mixer import AudioMixer
from quickcut.filtergraph import FilterGraph


def test_audio_mixer_builds_graph():
    """Verify AudioMixer produces valid filtergraph structure."""
    fg = FilterGraph()
    mix = AudioMix(
        source_gain_db=0.0,
        narration_gain_db=0.0,
        music_gain_db=-12.0,
        ducking_strength=0.7,
    )
    mixer = AudioMixer(mix)
    
    # Needs some inputs added to fg to test properly, 
    # but the mixer just takes labels.
    fg._a_counter = 1 # Setup arbitrary start limits
    
    final_lbl = mixer.build_audio_graph(
        fg, 
        source_labels=["aout0"], 
        narration_label="aout1", 
        music_label="aout2"
    )
    
    _, graph_str = fg.compile()
    
    assert "amix" in graph_str
    assert "volume=-12.0dB" in graph_str
    assert "sidechaincompress" in graph_str


def test_gain_applied():
    """Verify volume filters are generated with correct dB values."""
    fg = FilterGraph()
    # No ducking, just gains
    mix = AudioMix(source_gain_db=5.5, narration_gain_db=2.0, ducking_strength=0.0)
    mixer = AudioMixer(mix)
    
    mixer.build_audio_graph(fg, source_labels=["aout0"], narration_label="aout1")
    
    _, graph_str = fg.compile()
    assert "volume=5.5dB" in graph_str
    assert "volume=2.0dB" in graph_str


def test_ducking_generates_sidechain():
    """Verify sidechaincompress is in graph when music + narration exist."""
    fg = FilterGraph()
    mix = AudioMix(ducking_strength=0.8)
    mixer = AudioMixer(mix)
    
    mixer.build_audio_graph(
        fg, 
        source_labels=["aout0"], 
        narration_label="aout1", 
        music_label="aout2"
    )
    
    _, graph_str = fg.compile()
    assert "sidechaincompress=" in graph_str
    
    # If ducking strength is 0, no sidechain
    fg2 = FilterGraph()
    mix2 = AudioMix(ducking_strength=0.0)
    mixer2 = AudioMixer(mix2)
    mixer2.build_audio_graph(
        fg2, 
        source_labels=["aout0"], 
        narration_label="aout1", 
        music_label="aout2"
    )
    _, graph_str2 = fg2.compile()
    assert "sidechaincompress=" not in graph_str2
