function formatClock(value) {
    const total = Math.max(0, Number(value) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = Math.floor(total % 60);
    const parts = [minutes, seconds].map((part) => String(part).padStart(2, '0'));
    return hours > 0
        ? `${String(hours).padStart(2, '0')}:${parts.join(':')}`
        : parts.join(':');
}

export class PreviewPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('preview-container');
        this.lastExpectedPreview = null;
        this.lastPreviewJobId = null;
        this.player = null;
        this.playerElements = {};

        document.getElementById('btn-render-preview').addEventListener('click', async () => {
            const btn = document.getElementById('btn-render-preview');
            const placeholder = this.container.querySelector('.placeholder-preview');
            if (placeholder) {
                placeholder.querySelector('span').textContent = 'Rendering...';
            }
            btn.textContent = 'Rendering Initial Preview...';
            btn.disabled = true;
            try {
                const res = await this.app.api.triggerExport('YouTube', 'draft');
                this.lastExpectedPreview = res.filename;
                this.lastPreviewJobId = res.job_id;
                btn.textContent = 'Check Progress Bar';
            } catch (e) {
                btn.textContent = 'Render Preview';
                btn.disabled = false;
                if (placeholder) {
                    placeholder.querySelector('span').textContent = 'No Preview Available';
                }
                alert(e.message || 'Preview render failed.');
            }
        });

        window.addEventListener('graphcut:job-complete', (e) => {
            const data = e.detail;
            if (!data?.job_id || !this.lastPreviewJobId || data.job_id !== this.lastPreviewJobId) return;

            if (data.action === 'render' && this.lastExpectedPreview) {
                this.renderVideo(this.lastExpectedPreview);
                return;
            }

            if (data.action === 'render failed') {
                this.showPreviewFailure(data.job_id, data.detail);
            }
        });
    }

    async showPreviewFailure(jobId, detail) {
        try {
            const job = await this.app.api.getJob(jobId);
            alert(`Preview render failed.\n\n${detail || job.error || jobId}`);
        } catch {
            alert(`Preview render failed.\n\n${detail || jobId}`);
        }
        const btn = document.getElementById('btn-render-preview');
        if (btn) {
            btn.textContent = 'Render Preview';
            btn.disabled = false;
        }
    }

    bindPlayer() {
        const video = this.container.querySelector('video');
        if (!video) return;
        this.player = video;
        this.playerElements = {
            play: this.container.querySelector('[data-preview-play]'),
            back: this.container.querySelector('[data-preview-back]'),
            forward: this.container.querySelector('[data-preview-forward]'),
            mute: this.container.querySelector('[data-preview-mute]'),
            fullscreen: this.container.querySelector('[data-preview-fullscreen]'),
            scrub: this.container.querySelector('[data-preview-scrub]'),
            current: this.container.querySelector('[data-preview-current]'),
            duration: this.container.querySelector('[data-preview-duration]'),
            project: this.container.querySelector('[data-preview-project]'),
        };

        const sync = () => {
            if (!this.player) return;
            const duration = Number.isFinite(this.player.duration) ? this.player.duration : 0;
            if (this.playerElements.scrub) {
                this.playerElements.scrub.max = `${duration || 0}`;
                this.playerElements.scrub.value = `${Math.min(duration, this.player.currentTime || 0)}`;
            }
            if (this.playerElements.current) {
                this.playerElements.current.textContent = formatClock(this.player.currentTime || 0);
            }
            if (this.playerElements.duration) {
                this.playerElements.duration.textContent = formatClock(duration);
            }
            if (this.playerElements.play) {
                this.playerElements.play.textContent = this.player.paused ? 'Play' : 'Pause';
            }
            if (this.playerElements.mute) {
                this.playerElements.mute.textContent = this.player.muted ? 'Unmute' : 'Mute';
            }
        };

        this.player.addEventListener('loadedmetadata', sync);
        this.player.addEventListener('timeupdate', sync);
        this.player.addEventListener('play', sync);
        this.player.addEventListener('pause', sync);
        this.player.addEventListener('volumechange', sync);

        this.playerElements.play?.addEventListener('click', () => {
            if (!this.player) return;
            if (this.player.paused) {
                this.player.play();
            } else {
                this.player.pause();
            }
        });
        this.playerElements.back?.addEventListener('click', () => {
            if (!this.player) return;
            this.player.currentTime = Math.max(0, (this.player.currentTime || 0) - 5);
            sync();
        });
        this.playerElements.forward?.addEventListener('click', () => {
            if (!this.player) return;
            const duration = Number.isFinite(this.player.duration) ? this.player.duration : 0;
            this.player.currentTime = Math.min(duration, (this.player.currentTime || 0) + 5);
            sync();
        });
        this.playerElements.mute?.addEventListener('click', () => {
            if (!this.player) return;
            this.player.muted = !this.player.muted;
            sync();
        });
        this.playerElements.fullscreen?.addEventListener('click', async () => {
            if (!this.player) return;
            if (document.fullscreenElement) {
                await document.exitFullscreen();
                return;
            }
            await this.player.requestFullscreen();
        });
        this.playerElements.scrub?.addEventListener('input', (event) => {
            if (!this.player) return;
            this.player.currentTime = Number(event.target.value || 0);
            sync();
        });

        sync();
    }

    renderVideo(filename) {
        const projectName = this.app.state.project?.name || 'GraphCut';
        this.container.innerHTML = `
            <div class="preview-player">
                <div class="preview-player-stage">
                    <video class="preview-video" autoplay loop playsinline>
                        <source src="/api/export/download/${filename}" type="video/mp4">
                        Your browser doesn't support HTML video.
                    </video>
                </div>
                <div class="preview-player-meta">
                    <div>
                        <div class="preview-project-label">Project Preview</div>
                        <div class="preview-project-name" data-preview-project>${projectName}</div>
                    </div>
                    <div class="preview-time-readout">
                        <span data-preview-current>00:00</span>
                        <span>/</span>
                        <span data-preview-duration>00:00</span>
                    </div>
                </div>
                <input type="range" class="preview-scrub" data-preview-scrub min="0" max="0" step="0.05" value="0">
                <div class="preview-controls">
                    <div class="preview-control-group">
                        <button class="btn btn-sm btn-outline" data-preview-back>Back 5s</button>
                        <button class="btn btn-sm btn-primary" data-preview-play>Pause</button>
                        <button class="btn btn-sm btn-outline" data-preview-forward>Fwd 5s</button>
                    </div>
                    <div class="preview-control-group">
                        <button class="btn btn-sm btn-outline" data-preview-mute>Mute</button>
                        <button class="btn btn-sm btn-outline" data-preview-fullscreen>Fullscreen</button>
                    </div>
                </div>
            </div>
        `;

        const btn = document.getElementById('btn-render-preview');
        if (btn) {
            btn.textContent = 'Render Preview';
            btn.disabled = false;
        }
        this.bindPlayer();
    }

    render() {
        const projectName = this.app.state.project?.name || 'GraphCut';
        if (this.playerElements.project) {
            this.playerElements.project.textContent = projectName;
        }
    }
}
