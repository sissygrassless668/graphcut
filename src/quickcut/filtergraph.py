"""FFmpeg filtergraph builder for QuickCut editing core."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FilterNode:
    """A single filter operation in an FFmpeg filtergraph."""
    filter_name: str
    inputs: list[str]
    outputs: list[str]
    params: dict[str, Any] = field(default_factory=dict)

    def compile(self) -> str:
        """Compile this node to a filtergraph string segment."""
        # e.g. [0:v]trim=start=1:end=5[vout1]
        in_str = "".join(f"[{i}]" for i in self.inputs)
        out_str = "".join(f"[{o}]" for o in self.outputs)
        
        if self.params:
            param_str = ":".join(f"{k}={v}" for k, v in self.params.items())
            filter_str = f"{self.filter_name}={param_str}"
        else:
            filter_str = self.filter_name
            
        return f"{in_str}{filter_str}{out_str}"


class FilterGraph:
    """Builder for constructing complex FFmpeg filtergraphs."""

    def __init__(self) -> None:
        self.nodes: list[FilterNode] = []
        self.inputs: list[Path] = []
        self._v_counter: int = 0
        self._a_counter: int = 0

    def _next_v_label(self) -> str:
        label = f"vout{self._v_counter}"
        self._v_counter += 1
        return label

    def _next_a_label(self) -> str:
        label = f"aout{self._a_counter}"
        self._a_counter += 1
        return label

    def add_input(self, file_path: Path) -> int:
        """Register an input file and return its index."""
        self.inputs.append(file_path)
        return len(self.inputs) - 1

    def add_filter(self, node: FilterNode) -> None:
        """Add a custom filter node to the graph."""
        self.nodes.append(node)

    def trim(self, input_idx: int, start: float, end: float, stream: str = "v") -> str:
        """Add a trim + setpts filter.
        
        For video: trim=start=X:end=Y,setpts=PTS-STARTPTS
        For audio: atrim=start=X:end=Y,asetpts=PTS-STARTPTS
        """
        is_video = stream == "v"
        trim_name = "trim" if is_video else "atrim"
        setpts_name = "setpts" if is_video else "asetpts"
        
        label_out = self._next_v_label() if is_video else self._next_a_label()
        
        # [0:v]trim=start=X:end=Y,setpts=PTS-STARTPTS[vout]
        # We model the chained filter as one node for simplicity here
        node = FilterNode(
            filter_name=f"{trim_name}=start={start}:end={end},{setpts_name}",
            inputs=[f"{input_idx}:{stream}"],
            outputs=[label_out],
            params={"PTS-STARTPTS": ""} # using empty value for special syntax
        )
        
        # Override compile logic for this special chained node to format it neatly
        def compile_chained() -> str:
            in_str = "".join(f"[{i}]" for i in node.inputs)
            out_str = "".join(f"[{o}]" for o in node.outputs)
            return f"{in_str}{trim_name}=start={start}:end={end},{setpts_name}=PTS-STARTPTS{out_str}"
            
        node.compile = compile_chained # type: ignore
        self.nodes.append(node)
        return label_out

    def concat(self, labels: list[tuple[str, str]], n: int) -> tuple[str, str]:
        """Add a concat filter for video+audio pairs.
        
        Args:
            labels: List of tuples [(vid_label, aud_label), ...]
            n: Number of segments
            
        Returns:
            Tuple of (video_out_label, audio_out_label)
        """
        inputs = []
        for v, a in labels:
            inputs.extend([v, a])
            
        vout = self._next_v_label()
        aout = self._next_a_label()
        
        node = FilterNode(
            filter_name="concat",
            inputs=inputs,
            outputs=[vout, aout],
            params={"n": n, "v": 1, "a": 1}
        )
        self.nodes.append(node)
        return vout, aout

    def xfade(self, label_a: str, label_b: str, duration: float, offset: float) -> str:
        """Add a video crossfade transition."""
        vout = self._next_v_label()
        node = FilterNode(
            filter_name="xfade",
            inputs=[label_a, label_b],
            outputs=[vout],
            params={"duration": duration, "offset": offset}
        )
        self.nodes.append(node)
        return vout

    def acrossfade(self, label_a: str, label_b: str, duration: float) -> str:
        """Add an audio crossfade transition."""
        aout = self._next_a_label()
        node = FilterNode(
            filter_name="acrossfade",
            inputs=[label_a, label_b],
            outputs=[aout],
            params={"d": duration}
        )
        self.nodes.append(node)
        return aout

    def scale(self, label: str, width: int, height: int) -> str:
        """Add a scale filter."""
        vout = self._next_v_label()
        node = FilterNode(
            filter_name="scale",
            inputs=[label],
            outputs=[vout],
            params={"w": width, "h": height}
        )
        self.nodes.append(node)
        return vout

    def compile(self) -> tuple[list[Path], str]:
        """Compile the full graph into input paths and the filter_complex string."""
        graph_str = ";".join(node.compile() for node in self.nodes)
        return self.inputs, graph_str

    def debug_print(self) -> None:
        """Log the compiled filtergraph for debugging."""
        inputs, graph_str = self.compile()
        logger.debug("--- FilterGraph ---")
        for i, p in enumerate(inputs):
            logger.debug("Input %d: %s", i, p)
        logger.debug("Graph: %s", graph_str)
        logger.debug("-------------------")
