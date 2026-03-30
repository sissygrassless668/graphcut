import { GraphCutAPI } from './api.js';
import { SourcePanel } from './components/source-panel.js';
import { ClipPanel } from './components/clip-panel.js';
import { TranscriptPanel } from './components/transcript-panel.js';
import { PreviewPanel } from './components/preview-panel.js';
import { AudioPanel } from './components/audio-panel.js';
import { OverlaysPanel } from './components/overlays-panel.js';
import { ScenesPanel } from './components/scenes-panel.js';
import { ExportPanel } from './components/export-panel.js';
import { TrimModal } from './components/trim-modal.js';

class App {
    constructor() {
        this.api = new GraphCutAPI();
        this.state = {
            project: null,
            sources: null,
            clips: null,
            transcript: null,
            audioConfig: null,
            overlays: null,
            presets: null,
            activeJob: null
        };
        this.components = {};
        this.progress = {
            container: null,
            fill: null,
            label: null,
            eta: null,
            hideTimer: null
        };
    }

    async init() {
        this.progress.container = document.getElementById('global-progress');
        this.progress.fill = document.getElementById('progress-fill');
        this.progress.label = document.getElementById('progress-label');
        this.progress.eta = document.getElementById('progress-eta');

        this.api.connectProgressStream((data) => {
            this.updateProgress({
                action: data.action || 'Working',
                progress: data.progress ?? 0,
                eta: data.eta || '--:--',
                speed: data.speed || '0.0'
            });

            if ((data.progress ?? 0) >= 100) {
                const action = (data.action || '').toLowerCase();
                const hideDelay = action.includes('failed') ? 8000 : 1500;
                this.hideProgress(hideDelay);
                window.dispatchEvent(new CustomEvent('graphcut:job-complete', { detail: data }));
            }
        });

        // Resolve component dependencies 
        this.components.sources = new SourcePanel(this);
        this.components.clips = new ClipPanel(this);
        this.components.transcript = new TranscriptPanel(this);
        this.components.preview = new PreviewPanel(this);
        this.components.audio = new AudioPanel(this);
        this.components.overlays = new OverlaysPanel(this);
        this.components.scenes = new ScenesPanel(this);
        this.components.export = new ExportPanel(this);
        this.components.trimModal = new TrimModal(this);
        
        await this.refreshState();
        this.bindTabNavigation();
        console.log("App Initialized", this.state);
    }

    async refreshState() {
        try {
            document.getElementById('save-status').textContent = "Syncing with GraphCut CLI...";
            
            // Parallel fetches
            const [proj, srcs, clps, trx, aud, ovr, exp] = await Promise.all([
                this.api.getProject(),
                this.api.getSources(),
                this.api.getClips(),
                this.api.getTranscript(),
                this.api.getAudio(),
                this.api.getOverlays(),
                this.api.getExportPresets(),
            ]);

            this.state.project = proj;
            this.state.sources = srcs;
            this.state.clips = clps;
            this.state.transcript = trx;
            this.state.audioConfig = aud;
            this.state.overlays = ovr;
            this.state.presets = exp;
            
            // Notify components cleanly mapping DOM updates across boundary limits.
            Object.values(this.components).forEach(c => c.render());

            document.getElementById('save-status').textContent = "All changes saved";
        } catch(e) {
            document.getElementById('save-status').textContent = "Disconnected from CLI";
            console.error("State refresh failed", e);
        }
    }

    bindTabNavigation() {
        const tabs = document.querySelectorAll('.tab-btn');
        tabs.forEach(tab => {
            tab.addEventListener('click', (e) => {
                const target = e.target.dataset.tab;
                
                document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                e.target.classList.add('active');
                document.getElementById(`tab-${target}`).classList.add('active');
            });
        });
    }

    updateProgress({ action = 'Working', progress = 0, eta = '--:--', speed = '0.0' } = {}) {
        if (!this.progress.container || !this.progress.fill || !this.progress.label || !this.progress.eta) {
            return;
        }
        if (this.progress.hideTimer) {
            clearTimeout(this.progress.hideTimer);
            this.progress.hideTimer = null;
        }

        const pct = Math.max(0, Math.min(100, Number(progress) || 0));
        this.progress.container.style.display = 'flex';
        this.progress.fill.style.width = `${pct}%`;
        this.progress.label.textContent = `${action}: ${pct.toFixed(1)}%`;
        this.progress.eta.textContent = `ETA: ${eta} | Speed: ${speed}`;
    }

    hideProgress(delayMs = 0) {
        if (!this.progress.container) return;
        if (this.progress.hideTimer) {
            clearTimeout(this.progress.hideTimer);
            this.progress.hideTimer = null;
        }
        const hide = () => {
            if (this.progress.container) {
                this.progress.container.style.display = 'none';
            }
            if (this.progress.fill) {
                this.progress.fill.style.width = '0%';
            }
        };
        if (delayMs > 0) {
            this.progress.hideTimer = setTimeout(hide, delayMs);
            return;
        }
        hide();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.app = new App();
    window.app.init();
});
