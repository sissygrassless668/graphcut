const TRANSITIONS = [
    {
        id: 'cut',
        label: 'Cut',
        description: 'Instant switch to the next shot.',
        duration: 0.0
    },
    {
        id: 'fade',
        label: 'Fade',
        description: 'Soft dissolve between neighboring clips.',
        duration: 0.35
    },
    {
        id: 'xfade',
        label: 'Crossfade',
        description: 'A more cinematic overlap with motion.',
        duration: 0.6
    }
];

export class EffectsPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('effects-list');
    }

    render() {
        if (!this.container) return;

        const clipIndex = this.app.state.activeClipIndex;
        const clip = Number.isInteger(clipIndex) ? this.app.state.clips?.[clipIndex] : null;

        let html = `
            <div style="display:flex; flex-direction:column; gap:10px;">
                <div style="padding:10px 12px; border:1px solid var(--border-color); border-radius:var(--radius-md); background:rgba(15,52,96,0.18);">
                    <div style="font-size:0.8rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em;">Selected Clip</div>
                    <div style="margin-top:6px; font-weight:600;">
                        ${clip ? `${clip.source_id} (#${clipIndex + 1})` : 'Choose a clip in the timeline'}
                    </div>
                    <div style="margin-top:4px; color:var(--text-muted); font-size:0.82rem;">
                        ${clip ? `Transition: ${clip.transition} (${clip.transition_duration.toFixed(2)}s)` : 'Apply transitions and defaults from here.'}
                    </div>
                </div>
        `;

        TRANSITIONS.forEach((effect) => {
            const active = clip && clip.transition === effect.id;
            html += `
                <button class="btn effect-card ${active ? 'effect-card-active' : ''}" data-effect-id="${effect.id}" style="text-align:left; padding:14px;">
                    <div style="display:flex; align-items:center; justify-content:space-between;">
                        <strong>${effect.label}</strong>
                        <span style="font-size:0.75rem; color:${active ? 'var(--text-main)' : 'var(--text-muted)'};">${effect.duration.toFixed(2)}s</span>
                    </div>
                    <div style="margin-top:6px; color:var(--text-muted); font-size:0.82rem;">${effect.description}</div>
                </button>
            `;
        });

        html += `
                <div class="form-group" style="margin-top:4px;">
                    <label>Transition Duration</label>
                    <input type="number" class="form-control" id="effect-duration" min="0" max="3" step="0.05" value="${clip ? clip.transition_duration.toFixed(2) : '0.50'}" ${clip ? '' : 'disabled'}>
                </div>
                <div style="display:flex; gap:8px;">
                    <button class="btn btn-primary" id="btn-apply-effect" ${clip ? '' : 'disabled'}>Apply To Clip</button>
                    <button class="btn btn-outline" id="btn-clear-effect" ${clip ? '' : 'disabled'}>Reset To Cut</button>
                </div>
            </div>
        `;

        this.container.innerHTML = html;
        this.bindEvents();
    }

    bindEvents() {
        if (!this.container) return;
        let selectedEffect = this.app.state.clips?.[this.app.state.activeClipIndex ?? -1]?.transition || 'cut';

        this.container.querySelectorAll('[data-effect-id]').forEach((btn) => {
            btn.addEventListener('click', () => {
                selectedEffect = btn.getAttribute('data-effect-id') || 'cut';
                this.container.querySelectorAll('[data-effect-id]').forEach((node) => {
                    node.classList.toggle('effect-card-active', node === btn);
                });
            });
        });

        this.container.querySelector('#btn-apply-effect')?.addEventListener('click', async () => {
            const clipIndex = this.app.state.activeClipIndex;
            if (!Number.isInteger(clipIndex)) return;
            const durationEl = this.container.querySelector('#effect-duration');
            const duration = Math.max(0, Number(durationEl?.value || 0));
            try {
                await this.app.api.updateClip(clipIndex, {
                    transition: selectedEffect,
                    transition_duration: duration
                });
                await this.app.refreshState();
            } catch (err) {
                alert(err.message || 'Failed to apply transition.');
            }
        });

        this.container.querySelector('#btn-clear-effect')?.addEventListener('click', async () => {
            const clipIndex = this.app.state.activeClipIndex;
            if (!Number.isInteger(clipIndex)) return;
            try {
                await this.app.api.updateClip(clipIndex, {
                    transition: 'cut',
                    transition_duration: 0.0
                });
                await this.app.refreshState();
            } catch (err) {
                alert(err.message || 'Failed to reset transition.');
            }
        });
    }
}
