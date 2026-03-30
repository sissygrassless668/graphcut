export class ClipPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('clip-list');
        this._saveTimers = new Map(); // per-index debounce
    }

    render() {
        if (!this.app.state.clips) return;
        this.container.innerHTML = '';
        
        this.app.state.clips.forEach((clip, index) => {
            const sid = clip.source_id;
            const info = this.app.state.sources?.[sid];
            if (!info) return;

            const el = document.createElement('div');
            el.className = 'media-item';
            el.dataset.index = index;

            const fullDur = Number(info.duration_seconds || 0);
            const tStart = clip.trim_start ?? 0;
            const tEnd = clip.trim_end ?? (fullDur || 0);
            const clipDur = Math.max(0, (tEnd || 0) - (tStart || 0));
            const durStr = fullDur ? `${clipDur.toFixed(2)}s (of ${fullDur.toFixed(2)}s)` : `${clipDur.toFixed(2)}s`;

            el.innerHTML = `
                <div style="font-size:0.8rem;color:var(--text-muted);font-weight:bold">${index + 1}</div>
                ${info.thumbnail ? `<img src="${info.thumbnail}" class="thumbnail" />` : `<div class="thumbnail"></div>`}
                <div class="media-info" style="flex:1; overflow:hidden;">
                    <div class="media-name" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${sid}">${sid}</div>
                    <div class="media-meta">${durStr}</div>
                    <div style="display:flex; gap: 6px; margin-top: 6px; align-items:center;">
                        <label style="font-size:0.75rem;color:var(--text-muted);">In</label>
                        <input type="number" class="form-control" data-trim-start="${index}" min="0" step="0.05" value="${Number(tStart).toFixed(2)}" style="width: 86px; padding: 4px 6px; font-size: 0.8rem;">
                        <label style="font-size:0.75rem;color:var(--text-muted);">Out</label>
                        <input type="number" class="form-control" data-trim-end="${index}" min="0" step="0.05" value="${Number(tEnd).toFixed(2)}" style="width: 86px; padding: 4px 6px; font-size: 0.8rem;">
                        <button class="btn btn-sm btn-outline" data-trim-reset="${index}" title="Reset trim">Reset</button>
                    </div>
                </div>
                <div style="display:flex; flex-direction:column; gap: 6px;">
                    <button class="btn btn-sm btn-outline" data-move-up="${index}" title="Move Up">↑</button>
                    <button class="btn btn-sm btn-outline" data-move-down="${index}" title="Move Down">↓</button>
                    <button class="btn btn-sm btn-outline" data-trim-open="${index}" title="Trim With Preview">Trim</button>
                    <button class="btn btn-sm btn-outline" data-dup="${index}" title="Duplicate Segment">Dup</button>
                    <button class="btn btn-sm btn-outline" data-split="${index}" title="Split Segment">Split</button>
                    <button class="btn btn-sm btn-icon btn-remove" data-index="${index}" title="Remove clip">x</button>
                </div>
            `;

            el.querySelector('.btn-remove').addEventListener('click', async () => {
                try {
                    await this.app.api.deleteClip(index);
                    this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to remove clip.');
                }
            });

            const startEl = el.querySelector(`[data-trim-start="${index}"]`);
            const endEl = el.querySelector(`[data-trim-end="${index}"]`);
            const resetEl = el.querySelector(`[data-trim-reset="${index}"]`);

            const clamp = (v) => {
                const n = Number(v);
                if (!Number.isFinite(n)) return 0;
                if (fullDur > 0) return Math.max(0, Math.min(fullDur, n));
                return Math.max(0, n);
            };

            const scheduleSave = () => {
                const key = String(index);
                const existing = this._saveTimers.get(key);
                if (existing) clearTimeout(existing);
                this._saveTimers.set(key, setTimeout(async () => {
                    try {
                        const nextStart = clamp(startEl?.value);
                        const nextEnd = clamp(endEl?.value);
                        await this.app.api.updateClip(index, {
                            trim_start: nextStart,
                            trim_end: nextEnd
                        });
                        this.app.refreshState();
                    } catch (err) {
                        alert(err.message || 'Failed to update trim.');
                    }
                }, 300));
            };

            startEl?.addEventListener('input', scheduleSave);
            endEl?.addEventListener('input', scheduleSave);
            resetEl?.addEventListener('click', async () => {
                try {
                    await this.app.api.updateClip(index, { trim_start: null, trim_end: null });
                    this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to reset trim.');
                }
            });

            el.querySelector(`[data-trim-open="${index}"]`)?.addEventListener('click', () => {
                this.app.components?.trimModal?.openForClip(index);
            });
            el.querySelector(`[data-split="${index}"]`)?.addEventListener('click', () => {
                this.app.components?.trimModal?.openSplit(index);
            });
            el.querySelector(`[data-dup="${index}"]`)?.addEventListener('click', async () => {
                try {
                    await this.app.api.duplicateClip(index);
                    this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to duplicate clip.');
                }
            });
            el.querySelector(`[data-move-up="${index}"]`)?.addEventListener('click', async () => {
                if (index <= 0) return;
                try {
                    await this.app.api.moveClip(index, index - 1);
                    this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to move clip.');
                }
            });
            el.querySelector(`[data-move-down="${index}"]`)?.addEventListener('click', async () => {
                if (index >= (this.app.state.clips.length - 1)) return;
                try {
                    await this.app.api.moveClip(index, index + 1);
                    this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to move clip.');
                }
            });

            this.container.appendChild(el);
        });
    }
}
