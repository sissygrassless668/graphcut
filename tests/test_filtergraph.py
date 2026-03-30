"""Unit tests for the GraphCut FFmpeg FilterGraph builder."""

from pathlib import Path

from graphcut.filtergraph import FilterGraph, FilterNode


def test_trim_generates_valid_filter():
    """Verify trim filter builds correctly."""
    fg = FilterGraph()
    vid_idx = fg.add_input(Path("test.mp4"))
    
    vout = fg.trim(vid_idx, 5.0, 10.0, "v")
    
    assert vout == "vout0"
    assert len(fg.nodes) == 1
    
    compiled = fg.nodes[0].compile()
    assert compiled == "[0:v]trim=start=5.0:end=10.0,setpts=PTS-STARTPTS[vout0]"


def test_concat_generates_valid_filter():
    """Verify concat filter builds correctly."""
    fg = FilterGraph()
    
    vid_idx1 = fg.add_input(Path("test1.mp4"))
    vid_idx2 = fg.add_input(Path("test2.mp4"))
    
    vout, aout = fg.concat([("v0", "a0"), ("v1", "a1")], n=2)
    
    assert vout == "vout0"
    assert aout == "aout0"
    assert len(fg.nodes) == 1
    
    compiled = fg.nodes[0].compile()
    assert compiled == "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout0][aout0]"


def test_xfade_generates_valid_filter():
    """Verify xfade filter builds correctly."""
    fg = FilterGraph()
    vout = fg.xfade("v1", "v2", duration=0.5, offset=4.5)
    
    assert vout == "vout0"
    compiled = fg.nodes[0].compile()
    assert compiled == "[v1][v2]xfade=transition=fade:duration=0.5:offset=4.5[vout0]"


def test_single_clip_no_concat():
    """Verify a single clip workflow correctly routes outputs."""
    fg = FilterGraph()
    fg.add_input(Path("single.mp4"))
    
    vout = fg.trim(0, 0.0, 5.0, "v")
    aout = fg.trim(0, 0.0, 5.0, "a")
    
    inputs, graph = fg.compile()
    
    assert len(inputs) == 1
    assert "concat" not in graph
    assert "trim" in graph


def test_compile_returns_inputs_and_graph():
    """Verify compile splits the Graph logically."""
    fg = FilterGraph()
    
    p1 = Path("1.mp4")
    p2 = Path("2.mp4")
    
    fg.add_input(p1)
    fg.add_input(p2)
    
    fg.trim(0, 0, 5, "v")
    
    inputs, graph = fg.compile()
    
    assert inputs == [p1, p2]
    assert "[0:v]trim=start=0:end=5,setpts=PTS-STARTPTS[vout0]" == graph
