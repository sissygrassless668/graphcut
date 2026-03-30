export class PreviewPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('preview-container');
        this.lastExpectedPreview = null;
        this.lastPreviewJobId = null;
        
        document.getElementById('btn-render-preview').addEventListener('click', async () => {
            const btn = document.getElementById('btn-render-preview');
            const placeholder = this.container.querySelector('.placeholder-preview');
            if (placeholder) {
                placeholder.querySelector('span').textContent = "Rendering...";
            }
            btn.textContent = "Rendering Initial Preview...";
            btn.disabled = true;
            try {
                const res = await this.app.api.triggerExport("YouTube", "draft");
                this.lastExpectedPreview = res.filename;
                this.lastPreviewJobId = res.job_id;
                btn.textContent = "Check Progress Bar";
            } catch(e) {
                btn.textContent = "Render Preview";
                btn.disabled = false;
                if (placeholder) {
                    placeholder.querySelector('span').textContent = "No Preview Available";
                }
                alert(e.message || "Preview render failed.");
            }
        });
        
        window.addEventListener('graphcut:job-complete', (e) => {
            const data = e.detail;
            if (!data?.job_id || !this.lastPreviewJobId || data.job_id !== this.lastPreviewJobId) return;

            if (data.action === 'render' && this.lastExpectedPreview) {
                // Render the `<video>` element!
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
            btn.textContent = "Render Preview";
            btn.disabled = false;
        }
    }

    renderVideo(filename) {
        this.container.innerHTML = `
            <video class="w-100" style="display:block; max-width: 100%; border-radius: 8px; border: 1px solid var(--border-color);" controls autoplay loop>
                <source src="/api/export/download/${filename}" type="video/mp4">
                Your browser doesn't support HTML video.
            </video>
        `;
    }

    render() {
        const p = this.app.state.project;
        if (!p) return;
    }
}
