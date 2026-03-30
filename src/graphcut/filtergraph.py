"""FFmpeg filtergraph builder for GraphCut editing core."""

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

    def xfade(
        self,
        label_a: str,
        label_b: str,
        duration: float,
        offset: float,
        transition: str = "fade",
    ) -> str:
        """Add a video crossfade transition."""
        vout = self._next_v_label()
        node = FilterNode(
            filter_name="xfade",
            inputs=[label_a, label_b],
            outputs=[vout],
            params={"transition": transition, "duration": duration, "offset": offset}
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

    def pad(self, label: str, width: int | str, height: int | str, x: str = "(ow-iw)/2", y: str = "(oh-ih)/2", color: str = "black") -> str:
        """Add a pad filter (often used for letterboxing)."""
        vout = self._next_v_label()
        node = FilterNode(
            filter_name="pad",
            inputs=[label],
            outputs=[vout],
            params={
                "w": width,
                "h": height,
                "x": x,
                "y": y,
                "color": color
            }
        )
        self.nodes.append(node)
        return vout

    def crop_center(self, label: str, width: int | str, height: int | str) -> str:
        """Add a crop filter centered on the input."""
        vout = self._next_v_label()
        node = FilterNode(
            filter_name="crop",
            inputs=[label],
            outputs=[vout],
            params={
                "w": width,
                "h": height,
                "x": "(in_w-out_w)/2",
                "y": "(in_h-out_h)/2"
            }
        )
        self.nodes.append(node)
        return vout

    def scale(self, label: str, width: int | str, height: int | str) -> str:
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

    def volume(self, label: str, gain_db: float) -> str:
        """Add a volume filter to adjust audio gain in dB."""
        aout = self._next_a_label()
        node = FilterNode(
            filter_name="volume",
            inputs=[label],
            outputs=[aout],
            params={"volume": f"{gain_db}dB"}
        )
        self.nodes.append(node)
        return aout

    def amix(self, labels: list[str], weights: list[float] | None = None) -> str:
        """Mix multiple audio streams."""
        aout = self._next_a_label()
        params: dict[str, Any] = {"inputs": len(labels)}
        if weights:
            # e.g., weights="1.0 0.5 0.5"
            params["weights"] = " ".join(str(w) for w in weights)
            
        node = FilterNode(
            filter_name="amix",
            inputs=labels,
            outputs=[aout],
            params=params
        )
        self.nodes.append(node)
        return aout

    def sidechaincompress(
        self, main_label: str, sidechain_label: str,
        threshold: float = 0.02, ratio: float = 8.0, 
        attack: float = 200.0, release: float = 1000.0
    ) -> str:
        """Duck main audio when sidechain audio is active."""
        aout = self._next_a_label()
        node = FilterNode(
            filter_name="sidechaincompress",
            inputs=[main_label, sidechain_label],
            outputs=[aout],
            params={
                "threshold": threshold,
                "ratio": ratio,
                "attack": attack,
                "release": release,
            }
        )
        self.nodes.append(node)
        return aout

    def aloop(self, label: str, loop_count: int = -1) -> str:
        """Loop audio endlessly (or count times). Note: Requires asetpts to fix timestamps."""
        # [label]aloop=loop=-1:size=2e9[looped]
        aout = self._next_a_label()
        node = FilterNode(
            filter_name="aloop",
            inputs=[label],
            outputs=[aout],
            # Use a large size so it loops the whole file (size is in samples, 2e9 is very large)
            params={"loop": loop_count, "size": "2147483647"}
        )
        self.nodes.append(node)
        return aout

    def atrim(self, label: str, start: float = 0.0, end: float | None = None) -> str:
        """Trim audio and reset PTS."""
        aout = self._next_a_label()
        params = {"start": start}
        if end is not None:
            params["end"] = end
            
        # Needs asetpts=PTS-STARTPTS to reset timestamps cleanly
        def compile_chained() -> str:
            in_str = "".join(f"[{i}]" for i in node.inputs)
            out_str = "".join(f"[{o}]" for o in node.outputs)
            p_str = ":".join(f"{k}={v}" for k, v in params.items())
            return f"{in_str}atrim={p_str},asetpts=PTS-STARTPTS{out_str}"
            
        node = FilterNode(
            filter_name="atrim",
            inputs=[label],
            outputs=[aout],
            params=params
        )
        node.compile = compile_chained # type: ignore
        self.nodes.append(node)
        return aout

    def overlay(self, base_label: str, overlay_label: str, x: str, y: str, enable: str | None = None) -> str:
        """Add an overlay filter at a specific position."""
        vout = self._next_v_label()
        params = {"x": x, "y": y}
        if enable:
            params["enable"] = enable
            
        node = FilterNode(
            filter_name="overlay",
            inputs=[base_label, overlay_label],
            outputs=[vout],
            params=params
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
