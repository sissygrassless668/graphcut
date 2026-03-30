export class ExportPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('tab-export');
        this.trackedJobs = {};
        this.lastDebugJobId = null;
        
        window.addEventListener('graphcut:job-complete', (e) => {
            const data = e.detail;
            if (this.trackedJobs[data.job_id] && data.action === 'render') {
                const targetName = this.trackedJobs[data.job_id].preset;
                const filename = this.trackedJobs[data.job_id].filename;
                
                const btnNode = this.container.querySelector(`.btn-export[data-preset="${targetName}"]`);
                if (btnNode) {
                    const downloadBtn = document.createElement('a');
                    downloadBtn.href = `/api/export/download/${filename}`;
                    downloadBtn.download = filename;
                    downloadBtn.target = '_blank';
                    downloadBtn.className = "btn btn-outline";
                    downloadBtn.style.marginTop = "8px";
                    downloadBtn.style.display = "block";
                    downloadBtn.textContent = "Download " + filename;
                    
                    // Prevent duplicate injections
                    if (!btnNode.parentElement.querySelector(`a[download="${filename}"]`)) {
                        btnNode.parentElement.appendChild(downloadBtn);
                    }
                }
            }

            if (data.action === 'render failed') {
                this.lastDebugJobId = data.job_id;
                this.showJobDebug(data.job_id);
                alert(data.detail || `Render failed (${data.job_id}). Open Render Debug for details.`);
            }
        });
    }

    render() {
        if (!this.app.state.presets) return;

        let html = `
            <div class="form-group mb-lg" style="margin-bottom:20px">
                <label>Export Quality (CRF/Bitrate target)</label>
                <select id="export-quality" class="form-control">
                    <option value="draft">Draft (Ultrafast, Low Q)</option>
                    <option value="preview">Preview (Fast, Med Q)</option>
                    <option value="final" selected>Final (Slow, High Q)</option>
                </select>
            </div>
            <div class="export-grid" id="export-grid-box">
        `;

        this.app.state.presets.forEach(p => {
            html += `
                <div style="margin-bottom: 10px;">
                    <button class="btn btn-export" style="width:100%" data-preset="${p.name}">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                        <strong>${p.name}</strong>
                        <div class="export-meta">${p.width}x${p.height} (${p.aspect_ratio})</div>
                    </button>
                </div>
            `;
        });

        html += `</div>
            <button class="btn btn-primary" style="margin-top:20px;width:100%" id="btn-export-all">Export All Presets</button>
            <details style="margin-top: 16px;" id="render-debug">
                <summary style="cursor: pointer; user-select: none;">Render Debug</summary>
                <div style="margin-top: 10px; display: flex; gap: 8px; align-items: center;">
                    <button class="btn btn-sm btn-outline" id="btn-debug-refresh">Refresh</button>
                    <span style="color: var(--text-muted); font-size: 0.8rem;">Shows last render error details (FFmpeg cmd/stderr when available)</span>
                </div>
                <pre id="render-debug-pre" style="margin-top: 10px; white-space: pre-wrap; word-break: break-word; background: var(--bg-main); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 10px; max-height: 240px; overflow: auto;">No render failures yet.</pre>
            </details>
        `;

        this.container.innerHTML = html;
        this.bindEvents();
    }

    bindEvents() {
        const quality = () => document.getElementById('export-quality').value;
        const hasClips = () => Array.isArray(this.app.state.clips) && this.app.state.clips.length > 0;

        this.container.querySelectorAll('.btn-export').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                if (!hasClips()) {
                    alert('No clips in timeline. Add at least one source using the + button in Sources before rendering.');
                    return;
                }
                const target = e.currentTarget.dataset.preset;
                try {
                    const res = await this.app.api.triggerExport(target, quality());
                    this.trackedJobs[res.job_id] = { preset: target, filename: res.filename };
                    alert(`Export for ${target} started! See bottom bar for progress.`);
                } catch (err) {
                    alert(err.message || `Export failed for ${target}.`);
                }
            });
        });

        document.getElementById('btn-export-all')?.addEventListener('click', async () => {
            if (!hasClips()) {
                alert('No clips in timeline. Add at least one source using the + button in Sources before rendering.');
                return;
            }
            try {
                for (const p of this.app.state.presets) {
                    const res = await this.app.api.triggerExport(p.name, quality());
                    this.trackedJobs[res.job_id] = { preset: p.name, filename: res.filename };
                }
                alert("Export queue started!");
            } catch (err) {
                alert(err.message || 'Export queue failed to start.');
            }
        });

        this.container.querySelector('#btn-debug-refresh')?.addEventListener('click', async () => {
            const jobId = this.lastDebugJobId;
            if (!jobId) {
                alert('No render failure captured yet.');
                return;
            }
            await this.showJobDebug(jobId);
        });

        // On first render, try to show most recent failed job (if any).
        this.bootstrapDebug();
    }

    async showJobDebug(jobId) {
        const pre = this.container.querySelector('#render-debug-pre');
        const details = this.container.querySelector('#render-debug');
        if (!pre || !details) return;

        try {
            const job = await this.app.api.getJob(jobId);
            pre.textContent = JSON.stringify(job, null, 2);
            details.open = true;
        } catch (err) {
            pre.textContent = err.message || `Failed to load job ${jobId}`;
            details.open = true;
        }
    }

    async bootstrapDebug() {
        if (this.lastDebugJobId) return;
        const pre = this.container.querySelector('#render-debug-pre');
        if (!pre || pre.textContent !== 'No render failures yet.') return;

        try {
            const jobs = await this.app.api.listJobs(20);
            const failed = Array.isArray(jobs) ? jobs.find(j => j && j.status === 'failed') : null;
            if (failed && failed.job_id) {
                this.lastDebugJobId = failed.job_id;
                pre.textContent = JSON.stringify(failed, null, 2);
            }
        } catch {
            // Ignore bootstrap failures.
        }
    }
}
