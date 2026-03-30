export class SourcePanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('source-list');
        // Add source handler via hidden file input
        document.getElementById('btn-add-source').addEventListener('click', () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = 'video/*,audio/*';
            input.multiple = true;
            input.onchange = async (e) => {
                const files = Array.from(e.target.files);
                if (files.length === 0) return;
                
                document.getElementById('save-status').textContent = `Uploading ${files.length} file(s)...`;
                try {
                    this.app.updateProgress({
                        action: 'upload',
                        progress: 0,
                        eta: '--:--',
                        speed: `${files.length} file(s)`
                    });
                    for (let i = 0; i < files.length; i++) {
                        const f = files[i];
                        await this.app.api.uploadSource(f);
                        this.app.updateProgress({
                            action: 'upload',
                            progress: ((i + 1) / files.length) * 100,
                            eta: '--:--',
                            speed: `${i + 1}/${files.length}`
                        });
                    }
                } finally {
                    this.app.hideProgress(900);
                }
                this.app.refreshState();
            };
            input.click();
        });
    }

    render() {
        if (!this.app.state.sources) return;
        this.container.innerHTML = '';
        Object.entries(this.app.state.sources).forEach(([id, info]) => {
            if (info.media_type !== 'video' && info.media_type !== 'audio') return;
            const el = document.createElement('div');
            el.className = 'media-item source-card';
            const meta = info.media_type === 'audio'
                ? `${(info.duration_seconds || 0).toFixed(1)}s • audio`
                : `${(info.duration_seconds || 0).toFixed(1)}s • ${info.width || '--'}x${info.height || '--'}`;
            el.innerHTML = `
                ${info.thumbnail ? `<img src="${info.thumbnail}" class="thumbnail source-thumb" />` : `<div class="thumbnail source-thumb"></div>`}
                <div class="media-info source-info" style="flex-grow: 1; overflow: hidden; text-overflow: ellipsis;">
                    <div class="media-name" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${id}">${id}</div>
                    <div class="media-meta">${meta}</div>
                </div>
                <div class="source-card-actions" style="display: flex; gap: 4px; padding-right: 8px;">
                    <button class="btn btn-sm btn-icon btn-add-clip" data-id="${id}" title="Add to Timeline">+</button>
                    <button class="btn btn-sm btn-icon btn-trim-add" data-id="${id}" title="Trim + Add Segment">✂</button>
                    <button class="btn btn-sm btn-icon btn-delete-source" style="color: var(--color-accent)" data-id="${id}" title="Delete Source">&times;</button>
                </div>
            `;
            el.querySelector('.btn-add-clip').addEventListener('click', async () => {
                await this.app.api.addClip(id);
                this.app.refreshState();
            });
            el.querySelector('.btn-trim-add').addEventListener('click', async () => {
                this.app.components?.trimModal?.openForSource(id);
            });
            el.querySelector('.btn-delete-source').addEventListener('click', async () => {
                if (confirm(`Delete ${id} from this project and remove its media file from disk (if it is inside this project)?`)) {
                    document.getElementById('save-status').textContent = `Deleting ${id}...`;
                    try {
                        this.app.updateProgress({
                            action: 'delete',
                            progress: 20,
                            eta: '--:--',
                            speed: 'working'
                        });
                        await this.app.api.removeSource(id, { deleteFile: true });
                        this.app.updateProgress({
                            action: 'delete',
                            progress: 100,
                            eta: '00:00',
                            speed: 'done'
                        });
                    } finally {
                        this.app.hideProgress(700);
                    }
                    this.app.refreshState();
                }
            });
            this.container.appendChild(el);
        });
    }
}
