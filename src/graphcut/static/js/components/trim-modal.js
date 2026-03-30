export class TrimModal {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('trim-modal-root');
        this.body = document.getElementById('trim-modal-body');
        this.titleEl = document.getElementById('trim-modal-title');
        this.closeBtn = document.getElementById('trim-modal-close');

        this.state = null; // {mode, sourceId, clipIndex, insertPosition, trimStart, trimEnd}

        this.closeBtn?.addEventListener('click', () => this.close());
        this.root?.querySelector('[data-modal-close="1"]')?.addEventListener('click', () => this.close());
    }

    openForSource(sourceId, opts = {}) {
        this.state = {
            mode: 'add',
            sourceId,
            clipIndex: null,
            insertPosition: opts.insertPosition ?? null,
            trimStart: 0,
            trimEnd: null
        };
        this.render();
        this.show();
    }

    openForClip(clipIndex) {
        const clip = this.app.state.clips?.[clipIndex];
        if (!clip) return;
        const sourceId = clip.source_id;
        const info = this.app.state.sources?.[sourceId];
        if (!info) return;

        this.state = {
            mode: 'edit',
            sourceId,
            clipIndex,
            insertPosition: null,
            trimStart: clip.trim_start ?? 0,
            trimEnd: clip.trim_end ?? (info.duration_seconds ?? null)
        };
        this.render();
        this.show();
    }

    openSplit(clipIndex) {
        const clip = this.app.state.clips?.[clipIndex];
        if (!clip) return;
        const sourceId = clip.source_id;
        this.state = {
            mode: 'split',
            sourceId,
            clipIndex,
            insertPosition: null,
            trimStart: clip.trim_start ?? 0,
            trimEnd: clip.trim_end ?? null
        };
        this.render();
        this.show();
    }

    show() {
        if (this.root) this.root.style.display = 'flex';
    }

    close() {
        if (this.root) this.root.style.display = 'none';
        if (this.body) this.body.innerHTML = '';
        this.state = null;
    }

    render() {
        if (!this.state || !this.body) return;
        const { mode, sourceId } = this.state;
        const info = this.app.state.sources?.[sourceId];
        const duration = Number(info?.duration_seconds || 0);

        const title = mode === 'edit'
            ? `Trim Clip (#${(this.state.clipIndex ?? 0) + 1})`
            : mode === 'split'
                ? `Split Clip (#${(this.state.clipIndex ?? 0) + 1})`
                : `Trim Source (${sourceId})`;
        if (this.titleEl) this.titleEl.textContent = title;

        const mediaUrl = this.app.api.getSourceMedia(sourceId);
        const initialIn = Number(this.state.trimStart || 0);
        const initialOut = this.state.trimEnd ?? (duration || null);

        this.body.innerHTML = `
            <div style="display:grid; grid-template-columns: 1.4fr 1fr; gap: 12px;">
                <div>
                    <video id="trim-video" src="${mediaUrl}" controls style="width:100%; max-height: 360px; background:#000; border:1px solid var(--border-color); border-radius: var(--radius-sm);"></video>
                    <div style="display:flex; gap: 8px; margin-top: 10px; align-items:center; flex-wrap:wrap;">
                        <button class="btn btn-sm btn-outline" id="btn-trim-start">Start (Set In)</button>
                        <button class="btn btn-sm btn-outline" id="btn-trim-stop">Stop (Set Out)</button>
                        ${mode === 'split' ? `<button class="btn btn-sm btn-primary" id="btn-split-here">Split Here</button>` : ``}
                    </div>
                    <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 6px;">
                        Play the source, click Start then Stop. You can repeat “Add Segment” multiple times.
                    </div>
                </div>
                <div>
                    <div class="form-group">
                        <label>In (seconds)</label>
                        <input type="number" class="form-control" id="trim-in" min="0" step="0.05" value="${initialIn.toFixed(2)}">
                    </div>
                    <div class="form-group">
                        <label>Out (seconds)</label>
                        <input type="number" class="form-control" id="trim-out" min="0" step="0.05" value="${(initialOut ?? 0).toFixed(2)}">
                    </div>
                    <div class="form-group">
                        <label>Current Time</label>
                        <div id="trim-cur" style="font-variant-numeric: tabular-nums; padding: 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: var(--bg-main);">0.00</div>
                    </div>
                    <div style="display:flex; gap: 8px; margin-top: 10px; flex-wrap:wrap;">
                        ${mode === 'edit' ? `<button class="btn btn-primary" id="btn-apply-trim">Apply To Clip</button>` : ``}
                        ${mode === 'add' ? `<button class="btn btn-primary" id="btn-add-segment">Add Segment</button>` : ``}
                        <button class="btn btn-outline" id="btn-close-trim">Close</button>
                    </div>
                    <div id="trim-msg" style="margin-top:10px; color: var(--text-muted); font-size:0.85rem;"></div>
                </div>
            </div>
        `;

        this.bind(duration);
    }

    bind(duration) {
        const video = this.body.querySelector('#trim-video');
        const inEl = this.body.querySelector('#trim-in');
        const outEl = this.body.querySelector('#trim-out');
        const curEl = this.body.querySelector('#trim-cur');
        const msgEl = this.body.querySelector('#trim-msg');

        const clamp = (v) => {
            const n = Number(v);
            if (!Number.isFinite(n)) return 0;
            if (duration > 0) return Math.max(0, Math.min(duration, n));
            return Math.max(0, n);
        };
        const readInOut = () => {
            const tin = clamp(inEl?.value);
            const tout = clamp(outEl?.value);
            return { tin, tout };
        };
        const writeInOut = (tin, tout) => {
            if (inEl) inEl.value = clamp(tin).toFixed(2);
            if (outEl) outEl.value = clamp(tout).toFixed(2);
        };

        const updateCur = () => {
            if (!video || !curEl) return;
            curEl.textContent = Number(video.currentTime || 0).toFixed(2);
        };
        video?.addEventListener('timeupdate', updateCur);
        video?.addEventListener('loadedmetadata', () => {
            // Default Out to duration if not set.
            if (duration > 0 && outEl && Number(outEl.value) === 0) {
                outEl.value = duration.toFixed(2);
            }
        });

        this.body.querySelector('#btn-trim-start')?.addEventListener('click', () => {
            if (!video) return;
            const t = clamp(video.currentTime);
            const { tout } = readInOut();
            writeInOut(t, Math.max(tout, t));
            msgEl.textContent = `In set to ${t.toFixed(2)}s`;
        });
        this.body.querySelector('#btn-trim-stop')?.addEventListener('click', () => {
            if (!video) return;
            const t = clamp(video.currentTime);
            const { tin } = readInOut();
            writeInOut(Math.min(tin, t), t);
            msgEl.textContent = `Out set to ${t.toFixed(2)}s`;
        });

        this.body.querySelector('#btn-close-trim')?.addEventListener('click', () => this.close());

        this.body.querySelector('#btn-apply-trim')?.addEventListener('click', async () => {
            if (!this.state) return;
            const { tin, tout } = readInOut();
            if (tout <= tin) {
                alert('Out must be greater than In.');
                return;
            }
            try {
                await this.app.api.updateClip(this.state.clipIndex, { trim_start: tin, trim_end: tout });
                await this.app.refreshState();
                msgEl.textContent = 'Trim applied to clip.';
            } catch (e) {
                alert(e.message || 'Failed to apply trim.');
            }
        });

        this.body.querySelector('#btn-add-segment')?.addEventListener('click', async () => {
            if (!this.state) return;
            const { tin, tout } = readInOut();
            if (tout <= tin) {
                alert('Out must be greater than In.');
                return;
            }
            try {
                await this.app.api.insertClip({
                    source_id: this.state.sourceId,
                    trim_start: tin,
                    trim_end: tout,
                    position: this.state.insertPosition
                });
                await this.app.refreshState();
                msgEl.textContent = `Added segment ${tin.toFixed(2)}s → ${tout.toFixed(2)}s`;
            } catch (e) {
                alert(e.message || 'Failed to add segment.');
            }
        });

        this.body.querySelector('#btn-split-here')?.addEventListener('click', async () => {
            if (!this.state || !video) return;
            const t = clamp(video.currentTime);
            try {
                await this.app.api.splitClip(this.state.clipIndex, t);
                await this.app.refreshState();
                msgEl.textContent = `Split at ${t.toFixed(2)}s`;
                this.close();
            } catch (e) {
                alert(e.message || 'Failed to split clip.');
            }
        });
    }
}

