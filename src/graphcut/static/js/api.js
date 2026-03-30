/** GraphCut REST API and WebSocket wrapper encapsulating Python endpoints into JS promises */

export class GraphCutAPI {
    constructor() {
        this.baseUrl = window.location.origin + '/api';
        const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        this.wsUrl = `${wsProtocol}://${window.location.host}/api/ws/progress`;
        this.ws = null;
    }

    // -- Internal Fetch Wrapper --
    async _fetch(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        try {
            const res = await fetch(url, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });
            if (!res.ok) {
                let detail = res.statusText;
                try {
                    const errBody = await res.json();
                    if (errBody?.detail) {
                        detail = errBody.detail;
                    }
                } catch {
                    // Keep status text if response is not JSON.
                }
                throw new Error(`API Error: ${detail}`);
            }
            return await res.json();
        } catch (err) {
            console.error('API Error:', err);
            throw err;
        }
    }

    // -- Project --
    getProject() { return this._fetch('/project'); }

    // -- Sources --
    getSources() { return this._fetch('/sources'); }

    /** Returns absolute path to thumbnail image or null natively */
    getSourceThumbnail(sourceId) {
        return `${this.baseUrl}/sources/${encodeURIComponent(sourceId)}/thumbnail`;
    }
    getSourceMedia(sourceId) {
        return `${this.baseUrl}/sources/${encodeURIComponent(sourceId)}/media`;
    }

    uploadSource(file) {
        const formData = new FormData();
        formData.append('file', file);
        return fetch(`${this.baseUrl}/sources/upload`, {
            method: 'POST',
            body: formData
        }).then(res => res.json());
    }

    removeSource(sourceId, options = {}) {
        const { deleteFile = true } = options;
        return this._fetch(
            `/sources/${encodeURIComponent(sourceId)}?delete_file=${deleteFile ? 'true' : 'false'}`,
            { method: 'DELETE' }
        );
    }

    // -- Clips --
    getClips() { return this._fetch('/clips'); }
    addClip(sourceId) { return this._fetch('/clips/add', { method: 'POST', body: JSON.stringify({ source_id: sourceId }) }); }
    insertClip(payload) { return this._fetch('/clips/insert', { method: 'POST', body: JSON.stringify(payload || {}) }); }
    duplicateClip(index, position = null) { return this._fetch('/clips/duplicate', { method: 'POST', body: JSON.stringify({ index, position }) }); }
    splitClip(index, time) { return this._fetch('/clips/split', { method: 'POST', body: JSON.stringify({ index, time }) }); }
    moveClip(from_index, to_index) { return this._fetch('/clips/move', { method: 'POST', body: JSON.stringify({ from_index, to_index }) }); }
    reorderClips(indices) { return this._fetch('/clips/reorder', { method: 'PUT', body: JSON.stringify(indices) }); }
    updateClip(index, payload) { return this._fetch(`/clips/${encodeURIComponent(index)}`, { method: 'PUT', body: JSON.stringify(payload || {}) }); }
    deleteClip(index) { return this._fetch(`/clips/${encodeURIComponent(index)}`, { method: 'DELETE' }); }

    // -- Transcripts --
    getTranscript() { return this._fetch('/transcript'); }
    generateTranscript() { return this._fetch('/transcript/generate', { method: 'POST' }); }
    applyTranscriptCuts(cuts) { return this._fetch('/transcript/cuts', { method: 'POST', body: JSON.stringify(cuts || []) }); }
    
    // -- Audio & Overlays --
    getAudio() { return this._fetch('/audio'); }
    updateAudio(payload) { return this._fetch('/audio', { method: 'PUT', body: JSON.stringify(payload) }); }
    
    getOverlays() { return this._fetch('/overlays'); }
    updateWebcam(payload) { return this._fetch('/overlays/webcam', { method: 'PUT', body: JSON.stringify(payload) }); }
    deleteWebcam() { return this._fetch('/overlays/webcam', { method: 'DELETE' }); }
    updateCaptionStyle(payload) { return this._fetch('/overlays/caption_style', { method: 'PUT', body: JSON.stringify(payload) }); }
    setRoles(payload) { return this._fetch('/project/roles', { method: 'PUT', body: JSON.stringify(payload) }); }
    
    // -- Export --
    getExportPresets() { return this._fetch('/export/presets'); }
    triggerExport(presetName, quality) { return this._fetch('/export/render', { method: 'POST', body: JSON.stringify({ preset: presetName, quality: quality }) }); }
    getJob(jobId) { return this._fetch(`/jobs/${encodeURIComponent(jobId)}`); }
    listJobs(limit = 20) { return this._fetch(`/jobs?limit=${encodeURIComponent(limit)}`); }

    // -- Scenes --
    getScenes() { return this._fetch('/scenes'); }
    saveScene(name) { return this._fetch('/scenes/save', { method: 'POST', body: JSON.stringify({ name }) }); }
    activateScene(name) { return this._fetch('/scenes/activate', { method: 'POST', body: JSON.stringify({ name }) }); }
    deleteScene(name) { return this._fetch(`/scenes/${encodeURIComponent(name)}`, { method: 'DELETE' }); }

    // -- Websocket streams --
    connectProgressStream(onProgressUpdate) {
        if (this.ws) {
            this.ws.close();
        }
        
        this.ws = new WebSocket(this.wsUrl);
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (onProgressUpdate) onProgressUpdate(data);
            } catch (err) {
                console.error("Failed parsing WS msg", err);
            }
        };

        this.ws.onopen = () => console.log('WebSocket connected');
        this.ws.onerror = (e) => console.error('WebSocket error:', e);
        this.ws.onclose = () => {
            console.log('WebSocket closed, attempting reconnect...');
            setTimeout(() => this.connectProgressStream(onProgressUpdate), 5000);
        };
    }
}
