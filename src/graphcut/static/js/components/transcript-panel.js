export class TranscriptPanel {
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('transcript-content');
        this.selectedWords = new Set();
        this.deletedWords = new Set();
        this.wordsMap = new Map(); // Global index map 
        this.anchorWord = null;

        document.getElementById('btn-clear-cuts').addEventListener('click', async () => {
            await this.app.api.applyTranscriptCuts([]);
            this.app.refreshState();
        });

        document.getElementById('btn-apply-cuts').addEventListener('click', async () => {
            // Cut format: { source_id: str, word_index: int }
            const payload = Array.from(this.deletedWords)
                .map(idx => this.wordsMap.get(idx))
                .filter(Boolean)
                .map(w => ({ source_id: w.source_id, word_index: w.local_index }));
            await this.app.api.applyTranscriptCuts(payload);
            this.app.refreshState();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' || e.key === 'Delete') {
                if (this.selectedWords.size > 0) {
                    // Toggle: if selection is already cut, uncut it; else cut it.
                    const selected = Array.from(this.selectedWords);
                    const allCut = selected.every(idx => this.deletedWords.has(idx));

                    selected.forEach(idx => {
                        const el = document.querySelector(`.word[data-gidx="${idx}"]`);
                        if (allCut) {
                            this.deletedWords.delete(idx);
                            if (el) el.classList.remove('cut');
                        } else {
                            this.deletedWords.add(idx);
                            if (el) el.classList.add('cut');
                        }
                    });

                    this.selectedWords.clear();
                    document.querySelectorAll('.word.selected').forEach(el => el.classList.remove('selected'));
                    this.anchorWord = null;
                    this._updateCutButtons();
                }
            }
        });
    }

    _updateCutButtons() {
        const applyBtn = document.getElementById('btn-apply-cuts');
        if (applyBtn) {
            const n = this.deletedWords.size;
            applyBtn.textContent = n > 0 ? `Apply Cuts (${n})` : 'Apply Cuts';
            applyBtn.disabled = n === 0;
        }
    }

    _flattenWords(data) {
        // Supports either legacy `{all_words: [...]}` or Transcript JSON `{segments:[{words:[...]}]}`.
        if (Array.isArray(data?.all_words)) return data.all_words;
        const out = [];
        const segments = Array.isArray(data?.segments) ? data.segments : [];
        segments.forEach(seg => {
            const words = Array.isArray(seg?.words) ? seg.words : [];
            words.forEach(w => out.push(w));
        });
        return out;
    }

    render() {
        if (!this.app.state.transcript || Object.keys(this.app.state.transcript).length === 0) {
            this.container.innerHTML = `
                <div class="empty-state">
                    <p style="margin-bottom: 15px;">No transcript found. Try generating one.</p>
                    <button class="btn btn-primary" id="btn-generate-transcript">Generate Transcript</button>
                </div>
            `;
            const btn = document.getElementById('btn-generate-transcript');
            if (btn) {
                btn.addEventListener('click', async () => {
                    btn.textContent = "Generating...";
                    btn.disabled = true;
                    await this.app.api.generateTranscript();
                });
            }
            return;
        }

        // Initialize state arrays
        this.wordsMap.clear();
        this.selectedWords.clear();
        this.deletedWords.clear();
        this.anchorWord = null;
        
        // Parse applied cuts from API into local state hash maps
        const serverCuts = new Set(
            (this.app.state.project.transcript_cuts || [])
                .filter(c => c && typeof c.source_id === 'string' && Number.isInteger(c.word_index))
                .map(c => `${c.source_id}_${c.word_index}`)
        );

        this.container.innerHTML = `
            <div style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 10px;">
                Tip: Click a word. Shift-click to range select. Delete/Backspace toggles cut/un-cut. Use “Apply Cuts” to save.
            </div>
        `;
        let globalIndexCounter = 0;

        Object.entries(this.app.state.transcript).forEach(([sid, data]) => {
            const block = document.createElement('div');
            block.style.marginBottom = '20px';
            block.innerHTML = `<h3 style="font-size:0.8rem;color:var(--text-muted);border-bottom:1px solid var(--border-color);margin-bottom:8px">${sid}</h3>`;
            
            const wordsContainer = document.createElement('div');
            
            const flatWords = this._flattenWords(data);
            flatWords.forEach((word, localIndex) => {
                const gIdx = globalIndexCounter++;
                this.wordsMap.set(gIdx, { source_id: sid, local_index: localIndex, word });
                
                const span = document.createElement('span');
                span.className = 'word';
                span.dataset.gidx = gIdx;
                span.textContent = (word?.word ?? word?.text ?? '').trim();
                
                if (serverCuts.has(`${sid}_${localIndex}`)) {
                    this.deletedWords.add(gIdx);
                    span.classList.add('cut');
                }

                span.addEventListener('click', (e) => {
                    if (e.shiftKey) {
                        // Range select from anchor.
                        if (this.anchorWord !== null) {
                            const min = Math.min(this.anchorWord, gIdx);
                            const max = Math.max(this.anchorWord, gIdx);
                            for (let i = min; i <= max; i++) {
                                this.selectedWords.add(i);
                                document.querySelector(`.word[data-gidx="${i}"]`)?.classList.add('selected');
                            }
                        } else {
                            this.selectedWords.add(gIdx);
                            span.classList.add('selected');
                        }
                    } else if (e.metaKey || e.ctrlKey) {
                        if (this.selectedWords.has(gIdx)) {
                            this.selectedWords.delete(gIdx);
                            span.classList.remove('selected');
                        } else {
                            this.selectedWords.add(gIdx);
                            span.classList.add('selected');
                        }
                        this.anchorWord = gIdx;
                    } else {
                        this.selectedWords.clear();
                        document.querySelectorAll('.word.selected').forEach(el => el.classList.remove('selected'));
                        this.selectedWords.add(gIdx);
                        span.classList.add('selected');
                        this.anchorWord = gIdx;
                    }
                });
                
                wordsContainer.appendChild(span);
                wordsContainer.appendChild(document.createTextNode(' '));
            });
            
            block.appendChild(wordsContainer);
            this.container.appendChild(block);
        });

        this._updateCutButtons();
    }
}
