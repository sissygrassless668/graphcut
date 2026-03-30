<div align="center">
  <img src="https://via.placeholder.com/120x120.png?text=GraphCut" alt="GraphCut Logo" width="120" />
  
  # GraphCut 🎬✂️

  **The Local-First, Automation-Powered Video Editor for Solo Creators**
  
  <p>
    <a href="https://github.com/colleybrb/graphcut/stargazers"><img src="https://img.shields.io/github/stars/colleybrb/graphcut?style=social" alt="Stars" /></a>
    <a href="https://github.com/colleybrb/graphcut/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Fair%20Source-blue.svg" alt="License: Fair Source" /></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+" /></a>
    <a href="#"><img src="https://img.shields.io/badge/FFmpeg-Backend-green.svg" alt="Powered by FFmpeg" /></a>
    <a href="#"><img src="https://img.shields.io/badge/Local-First-success.svg" alt="Local First" /></a>
  </p>
</div>

---

**GraphCut** is a blistering-fast, privacy-respecting video editor aimed at solo creators who want the speed of automation with the raw power of Python and FFmpeg. 

Tired of waiting for cloud processing? Frustrated by bloated timelines for simple tasks? GraphCut effortlessly merges multiple clips, overlays webcams, mixes audio, syncs offline AI transcriptions, and generates burn-in captions natively on your own machine. 

## ✨ Why GraphCut?

* 🔒 **100% Local-First:** All editing, rendering, and AI transcription happens offline. No media or transcripts are ever sent to a cloud endpoint.
* ⚡ **Hardware Accelerated:** Automatically detects CPU vs. NVENC (NVIDIA CUDA) vs. VideoToolbox (Mac) and uses the best available native hardware acceleration to slice render times. 
* 🧠 **AI Transcription Built-in:** Features local Whisper AI integrations for hyper-fast, word-accurate transcription and caption burn-in out of the box.
* 💻 **Code as the Editor:** No proprietary, corruptible binary project formats. Your project manifest is a standard, human-readable YAML file that statically drives FFmpeg filtergraphs.
* 🚀 **Automation Ready:** Every single GUI or CLI action translates directly to programmable backend rendering functions. Build your own mass-rendering loops or integrate with your existing automation suites.

## 🤖 Built for AI Agents

Because GraphCut is entirely deterministic and backed by simple JSON/YAML manifests, **it is the ultimate video editor for AI coding agents.**

Instead of wrestling with headless browsers or proprietary GUI scripting, an AI agent can simply:
1. Ingest your raw footage.
2. Generate a `project.yaml` containing precise cut timestamps, overlay logic, and styling.
3. Run `graphcut export my-video` via the CLI.

Zero GUI required. You can completely automate your video pipeline—letting your locally running LLMs assemble, narrate, and polish YouTube or TikTok clips while you sleep!

### Example Agent Actions

```bash
# Automatically transcribe speech and burn-in subtitles
graphcut transcribe my-awesome-video

# Automatically chop out all dead-air silence from the timeline
graphcut remove-silences my-awesome-video --threshold -35dB

# Configure a picture-in-picture webcam overlay over the main footage
graphcut set-webcam my-awesome-video face_cam.mp4 --position bottom-right

# Generate a fast draft preview 
graphcut render-preview my-awesome-video
```

## 📸 Interactive Web GUI

GraphCut isn't just a CLI script. It features a full, decoupled native Web UI designed to edit video from the browser without the lag.

> *Edit transcripts like a text document to automatically cut the underlying video! Manage scenes, tweak audio mixing, apply transition overlays, and stream native rendering previews — all powered by a FastAPI backend.*

## 🛠️ Installation

**Prerequisites:** You must have Python 3.11+ and `ffmpeg` / `ffprobe` installed on your system's `PATH`.

```bash
# Clone the repository
git clone https://github.com/colleybrb/graphcut.git
cd graphcut

# Minimal install (Core FFmpeg bindings)
pip install -e .

# Full suite install (Includes Local AI Whisper transcription & Scene Detection)
pip install -e ".[all]"
```

## 🚀 Quick Start

Creating a polished, captioned video takes just a few commands.

```bash
# 1. Initialize a new video project directory
graphcut new-project my-awesome-video

# 2. Add raw media (video, webcam, audio) to the project
graphcut add-source my-awesome-video main_clip.mp4 background_audio.mp3

# 3. Boot up the local Web GUI editor to start cutting
graphcut serve my-awesome-video
```

Navigate to `http://localhost:8420` in your web browser. Upload your media, hit **Generate Transcript**, delete the words you don't want, and click **Export** to render YouTube, TikTok, and Reels formats simultaneously!

## 🏗️ Architecture

Under the hood, GraphCut completely bypasses slow per-frame Python processing (like MoviePy or OpenCV). Instead, it orchestrates complex `FFmpeg` filtergraphs via `subprocess`, delivering maximum bare-metal rendering performance. 

* **Backend:** FastAPI, Python 3.11+, Pydantic v2
* **Frontend:** Vanilla JS, CSS Grid (Dependency-free HTML5)
* **AI:** `faster-whisper` (CUDA/Metal supported!)

## 🤝 Contributing & License

GraphCut is licensed under the **Fair Source License**. 

The codebase is completely open, transparent, and **free for any personal, educational, or non-commercial usage indefinitely.** If you use GraphCut to produce content that generates revenue over a certain threshold, or deploy it within a corporate environment, please see [LICENSE.md](LICENSE.md) for commercial licensing requirements.

**Love the project? Please consider leaving a ⭐ on GitHub!**
