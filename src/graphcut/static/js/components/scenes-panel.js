export class ScenesPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('tab-scenes');
    }

    render() {
        const proj = this.app.state.project;
        if (!proj) return;

        const scenes = proj.scenes || {};
        const active = proj.active_scene || '';
        const names = Object.keys(scenes).sort((a, b) => a.localeCompare(b));

        let html = `
            <div class="form-group">
                <label>Scene Name</label>
                <div style="display:flex; gap: 8px;">
                    <input id="scene-name" class="form-control" placeholder="e.g. Talking Head" style="flex:1" />
                    <button class="btn btn-sm btn-primary" id="btn-scene-save">Save</button>
                </div>
                <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 6px;">
                    Saves current Webcam, Audio Mix, Captions, Narration/Music selections.
                </div>
            </div>
        `;

        if (names.length === 0) {
            html += `<div class="empty-state" style="padding: 14px;">No scenes yet.</div>`;
        } else {
            html += `<div style="display:flex; flex-direction:column; gap: 8px;">`;
            names.forEach(name => {
                const isActive = name === active;
                html += `
                    <div class="media-item" style="cursor: default;">
                        <div class="media-info" style="flex:1;">
                            <div class="media-name">${this._escape(name)}${isActive ? ' (Active)' : ''}</div>
                            <div class="media-meta">${this._sceneMeta(scenes[name])}</div>
                        </div>
                        <div style="display:flex; gap: 6px;">
                            <button class="btn btn-sm ${isActive ? 'btn-outline' : 'btn-primary'}" data-scene-activate="${this._escapeAttr(name)}" ${isActive ? 'disabled' : ''}>Activate</button>
                            <button class="btn btn-sm btn-outline" data-scene-delete="${this._escapeAttr(name)}">Delete</button>
                        </div>
                    </div>
                `;
            });
            html += `</div>`;
        }

        this.container.innerHTML = html;
        this.bindEvents();
    }

    bindEvents() {
        const nameEl = this.container.querySelector('#scene-name');
        const saveBtn = this.container.querySelector('#btn-scene-save');
        saveBtn?.addEventListener('click', async () => {
            const name = (nameEl?.value || '').trim();
            if (!name) {
                alert('Scene name cannot be empty.');
                return;
            }
            try {
                await this.app.api.saveScene(name);
                await this.app.refreshState();
            } catch (e) {
                alert(e.message || 'Failed to save scene.');
            }
        });

        this.container.querySelectorAll('[data-scene-activate]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const name = e.currentTarget.getAttribute('data-scene-activate');
                if (!name) return;
                try {
                    await this.app.api.activateScene(name);
                    await this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to activate scene.');
                }
            });
        });

        this.container.querySelectorAll('[data-scene-delete]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const name = e.currentTarget.getAttribute('data-scene-delete');
                if (!name) return;
                if (!confirm(`Delete scene "${name}"?`)) return;
                try {
                    await this.app.api.deleteScene(name);
                    await this.app.refreshState();
                } catch (err) {
                    alert(err.message || 'Failed to delete scene.');
                }
            });
        });
    }

    _sceneMeta(scene) {
        if (!scene) return '';
        const webcam = scene.webcam?.source_id ? `Webcam: ${scene.webcam.source_id}` : 'Webcam: Off';
        const narr = scene.narration ? `Narration: ${scene.narration}` : 'Narration: None';
        const music = scene.music ? `Music: ${scene.music}` : 'Music: None';
        const caps = scene.caption_style?.style ? `Captions: ${scene.caption_style.style}` : 'Captions: ?';
        return `${webcam} • ${narr} • ${music} • ${caps}`;
    }

    _escape(s) {
        return String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    }

    _escapeAttr(s) {
        return String(s).replaceAll('"', '&quot;');
    }
}

