"""Voice recording using system microphones via FFmpeg."""

from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path

from quickcut.ffmpeg_executor import FFmpegExecutor

logger = logging.getLogger(__name__)


class VoiceRecorder:
    """Records voice-over from system microphone."""

    def __init__(self, executor: FFmpegExecutor | None = None) -> None:
        self.executor = executor or FFmpegExecutor()

    def record_voiceover(
        self,
        output_path: Path,
        duration: float | None = None,
        sample_rate: int = 48000,
        device: str | None = None,
    ) -> Path:
        """Record audio from default microphone to WAV.

        Args:
            output_path: Path to save the recording.
            duration: Total duration to record (seconds). If None, run indefinitely.
            sample_rate: Recording sample rate. Default 48000.
            device: Optional specific device name/id instead of default.

        Returns:
            The recorded file path.
        """
        sys_os = platform.system().lower()
        dev_args = []
        
        # Determine capture format and device
        if sys_os == "darwin":
            dev_args.extend(["-f", "avfoundation", "-i", device or ":0"])
        elif sys_os == "windows":
            dev_args.extend(["-f", "dshow", "-i", f"audio={device or 'Microphone'}"])
        elif sys_os == "linux":
            dev_args.extend(["-f", "pulse", "-i", device or "default"])
        else:
            raise RuntimeError(f"Unsupported OS for voice recording: {sys_os}")

        cmd = []
        if duration is not None:
            cmd.extend(["-t", str(duration)])
            
        cmd.extend(dev_args)
        cmd.extend([
            "-ac", "1",
            "-ar", str(sample_rate),
            "-y", str(output_path),
        ])

        logger.info("Starting voice recording... (saving to %s)", output_path.name)
        if duration is None:
            logger.info("Press Ctrl+C to stop recording.")

        try:
            # We run directly with subprocess to allow user Ctrl+C interception
            ff_binary = self.executor._find_ffmpeg()
            subprocess.run([ff_binary] + cmd, check=True)
            logger.info("Recording finished successfully.")
        except KeyboardInterrupt:
            logger.info("Recording stopped by user.")
        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg recording failed: %s", e)
            raise e
            
        return output_path

    @staticmethod
    def list_audio_devices() -> list[str]:
        """List available audio input devices (experimental)."""
        sys_os = platform.system().lower()
        if sys_os == "darwin":
            # Very crude parsing, just for debugging.
            result = subprocess.run(
                ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", '""'],
                capture_output=True, text=True
            )
            return [line for line in result.stderr.splitlines() if "audio" in line.lower()]
            
        return ["Listing devices only supported on macOS for now."]
