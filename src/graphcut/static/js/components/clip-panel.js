function formatSeconds(value) {
    const total = Math.max(0, Number(value) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = Math.floor(total % 60);
    const frames = Math.floor((total - Math.floor(total)) * 30);
    const base = [minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':');
    return hours > 0
        ? `${String(hours).padStart(2, '0')}:${base}:${String(frames).padStart(2, '0')}`
        : `${base}:${String(frames).padStart(2, '0')}`;
}

export class ClipPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('clip-list');
        this._saveTimers = new Map();
    }

    render() {
        if (!this.container) return;

        const clips = Array.isArray(this.app.state.clips) ? this.app.state.clips : [];
        const zoom = Number(this.app.state.timelineZoom || 1);

        if (clips.length === 0) {
            this.container.innerHTML = '<div class="empty-state">Add clips or trim segments from the library to start building a sequence.</div>';
            return;
        }

        const totalDuration = clips.reduce((sum, clip) => {
            const info = this.app.state.sources?.[clip.source_id];
            const fullDur = Number(info?.duration_seconds || 0);
            const tStart = clip.trim_start ?? 0;
            const tEnd = clip.trim_end ?? fullDur;
            return sum + Math.max(0, tEnd - tStart);
        }, 0);

        const timeline = document.createElement('div');
        timeline.className = 'timeline-shell';
        timeline.innerHTML = `
            <div class="timeline-ruler">
                <div class="timeline-timecode">${formatSeconds(totalDuration)}</div>
                <div class="timeline-track-title">Track V1 / Primary Sequence</div>
            </div>
        `;

        const rail = document.createElement('div');
        rail.className = 'timeline-rail';

        clips.forEach((clip, index) => {
            const sid = clip.source_id;
            const info = this.app.state.sources?.[sid];
            if (!info) return;

            const fullDur = Number(info.duration_seconds || 0);
            const tStart = clip.trim_start ?? 0;
            const tEnd = clip.trim_end ?? fullDur;
            const clipDur = Math.max(0, (tEnd || 0) - (tStart || 0));
            const visualWidth = Math.max(180, Math.min(560, clipDur * 130 * zoom));
            const selected = this.app.state.activeClipIndex === index;
            const transitionLabel = clip.transition === 'cut'
                ? 'Cut'
                : `${clip.transition} ${Number(clip.transition_duration || 0).toFixed(2)}s`;

            const el = document.createElement('article');
            el.className = `timeline-clip ${selected ? 'timeline-clip-selected' : ''}`;
            el.dataset.index = index;
            el.style.width = `${visualWidth}px`;
            el.innerHTML = `
                <div class="timeline-clip-head">
                    <div>
                        <div class="timeline-clip-index">Clip ${index + 1}</div>
                        <div class="timeline-clip-name" title="${sid}">${sid}</div>
                    </div>
                    <div class="timeline-clip-badge">${transitionLabel}</div>
                </div>
                <div class="timeline-clip-frame">
                    ${info.thumbnail ? `<img src="${info.thumbnail}" class="timeline-thumb" alt="${sid}">` : '<div class="timeline-thumb timeline-thumb-empty"></div>'}
                </div>
                <div class="timeline-clip-window">${formatSeconds(tStart)} -> ${formatSeconds(tEnd)}</div>
                <div class="timeline-clip-duration">${clipDur.toFixed(2)}s of ${fullDur.toFixed(2)}s</div>
                <div class="timeline-clip-fields">
                    <label>In <input type="number" class="form-control timeline-input" data-trim-start="${index}" min="0" step="0.05" value="${Number(tStart).toFixed(2)}"></label>
                    <label>Out <input type="number" class="form-control timeline-input" data-trim-end="${index}" min="0" step="0.05" value="${Number(tEnd).toFixed(2)}"></label>
                </div>
                <div class="timeline-clip-actions">
                    <button class="btn btn-sm btn-outline" data-trim-open="${index}" title="Open trim preview">Trim</button>
                    <button class="btn btn-sm btn-outline" data-dup="${index}" title="Duplicate segment">Dup</button>
                    <button class="btn btn-sm btn-outline" data-split="${index}" title="Split segment">Split</button>
                    <button class="btn btn-sm btn-outline" data-trim-reset="${index}" title="Reset trim">Reset</button>
                </div>
                <div class="timeline-clip-actions timeline-clip-actions-secondary">
                    <button class="btn btn-sm btn-outline" data-move-up="${index}" title="Move earlier">Left</button>
                    <button class="btn btn-sm btn-outline" data-move-down="${index}" title="Move later">Right</button>
                    <button class="btn btn-sm btn-icon btn-remove" data-index="${index}" title="Remove clip">x</button>
                </div>
            `;

            el.addEventListener('click', () => this.app.setActiveClip(index));

            const stopClick = (event) => event.stopPropagation();
            el.querySelectorAll('input, button').forEach((node) => {
                node.addEventListener('click', stopClick);
            });

            el.querySelector('.btn-remove')?.addEventListener('click', async () => {
                try {
                    await this.app.api.deleteClip(index);
                    await this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to remove clip.');
                }
            });

            const startEl = el.querySelector(`[data-trim-start="${index}"]`);
            const endEl = el.querySelector(`[data-trim-end="${index}"]`);
            const resetEl = el.querySelector(`[data-trim-reset="${index}"]`);

            const clamp = (value) => {
                const parsed = Number(value);
                if (!Number.isFinite(parsed)) return 0;
                if (fullDur > 0) return Math.max(0, Math.min(fullDur, parsed));
                return Math.max(0, parsed);
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
                        await this.app.refreshState();
                    } catch (err) {
                        alert(err.message || 'Failed to update trim.');
                    }
                }, 260));
            };

            startEl?.addEventListener('input', scheduleSave);
            endEl?.addEventListener('input', scheduleSave);
            resetEl?.addEventListener('click', async () => {
                try {
                    await this.app.api.updateClip(index, { trim_start: null, trim_end: null });
                    await this.app.refreshState();
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
                    await this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to duplicate clip.');
                }
            });
            el.querySelector(`[data-move-up="${index}"]`)?.addEventListener('click', async () => {
                if (index <= 0) return;
                try {
                    await this.app.api.moveClip(index, index - 1);
                    await this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to move clip.');
                }
            });
            el.querySelector(`[data-move-down="${index}"]`)?.addEventListener('click', async () => {
                if (index >= (clips.length - 1)) return;
                try {
                    await this.app.api.moveClip(index, index + 1);
                    await this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to move clip.');
                }
            });

            rail.appendChild(el);
        });

        timeline.appendChild(rail);
        this.container.innerHTML = '';
        this.container.appendChild(timeline);
    }
}
