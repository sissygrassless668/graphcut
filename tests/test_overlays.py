"""Unit tests for the overlay compositor logic."""

import pytest
from quickcut.models import WebcamOverlay
from quickcut.filtergraph import FilterGraph
from quickcut.overlay_compositor import OverlayCompositor


def test_webcam_positioning():
    """Verify position presets generate correct x,y."""
    fg = FilterGraph()
    compositor = OverlayCompositor()
    
    # Needs a mock base width and height to check the math mappings
    c_br = WebcamOverlay(source_id="mock", position="bottom-right", scale=0.5, border_width=0)
    
    lbl = compositor.add_webcam_overlay(
        fg, 
        base_label="base", 
        webcam_input_idx=1,
        config=c_br,
        base_width=1920,
        base_height=1080,
    )
    
    _, g_str = fg.compile()
    
    # scale calculation w should be 1920*0.5=960
    assert "scale=w=960:h=-1" in g_str
    
    # Overlay should calculate: x=main_w-overlay_w-20, y=main_h-overlay_h-20
    assert "x=main_w-overlay_w-20:y=main_h-overlay_h-20" in g_str
    

def test_watermark_opacity():
    """Verify watermark mapping logic checks."""
    fg = FilterGraph()
    compositor = OverlayCompositor()
    
    lbl = compositor.add_watermark(fg, base_label="base", watermark_input_idx=2, opacity=0.7)
    _, g_str = fg.compile()
    
    # Check format=rgba,colorchannelmixer=aa=0.7
    assert "colorchannelmixer=aa=0.7" in g_str
