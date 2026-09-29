window.DailyNotesView = {
  currentDate: new Date().toISOString().split('T')[0],

  async render(container) {
    container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <div>
          <h2 style="font-size: 20px; font-weight: 700; margin-bottom: 4px;">Daily Notes</h2>
          <p style="font-size: 13px; color: var(--text-secondary);">Capture the day, then review and consolidate durable knowledge into Mbrain.</p>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <button class="btn-secondary" id="btn-prev-day">◀ Prev</button>
          <input type="date" class="form-control" id="daily-note-date" value="${this.currentDate}" style="width: 150px; text-align: center;">
          <button class="btn-secondary" id="btn-next-day">Next ▶</button>
          <button class="btn-secondary" id="btn-today">Today</button>
        </div>
      </div>

      <!-- Editor Card -->
      <div class="card" style="display: flex; flex-direction: column; height: calc(100vh - 280px); min-height: 420px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <span style="font-size: 12px; color: var(--text-muted);" id="note-filepath-label">Loading note...</span>
          <div style="display: flex; gap: 10px;">
            <button class="btn-secondary" id="btn-save-note">💾 Save Note</button>
            <button class="btn-primary" id="btn-harvest-note" style="background: linear-gradient(135deg, #1f6feb, #238636);">
              <span>⚡</span>
              <span>Process into Memory</span>
            </button>
          </div>
        </div>

        <textarea id="daily-note-editor" class="form-control" style="flex: 1; font-family: 'SF Mono', Monaco, monospace; font-size: 13px; line-height: 1.6; resize: none;" placeholder="# Daily Note&#10;&#10;- Today I upgraded cluster node infra.minipc to 64GB RAM...&#10;- [FACT:trading.nvda] {&quot;ticker&quot;: &quot;NVDA&quot;, &quot;action&quot;: &quot;buy&quot;, &quot;price&quot;: 120.0, &quot;status&quot;: &quot;open&quot;}&#10;"></textarea>
      </div>

      <!-- Ingestion Results Card -->
      <div id="harvest-result-card" class="card" style="display: none; background: rgba(88, 166, 255, 0.05); border-color: rgba(88, 166, 255, 0.3);">
        <div class="card-title" style="color: var(--accent-blue);">
          <span>🧠 GMS Consolidation Report</span>
          <button class="btn-close" id="btn-close-harvest-card">×</button>
        </div>
        <div id="harvest-result-content"></div>
      </div>
    `;

    this.bindEvents(container);
    await this.loadNote();
  },

  bindEvents(container) {
    const dateInput = container.querySelector('#daily-note-date');
    const prevBtn = container.querySelector('#btn-prev-day');
    const nextBtn = container.querySelector('#btn-next-day');
    const todayBtn = container.querySelector('#btn-today');
    const saveBtn = container.querySelector('#btn-save-note');
    const harvestBtn = container.querySelector('#btn-harvest-note');
    const closeHarvestBtn = container.querySelector('#btn-close-harvest-card');

    // Helper: parse YYYY-MM-DD as local date (not UTC) to avoid timezone shift bugs
    const parseLocalDate = (dateStr) => {
      const [y, m, d] = dateStr.split('-').map(Number);
      return new Date(y, m - 1, d);
    };
    const formatDate = (d) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    };

    // Dirty-check: warn if editor has unsaved changes
    const confirmIfDirty = () => {
      const editor = document.getElementById('daily-note-editor');
      if (editor && this._savedContent !== undefined && editor.value !== this._savedContent) {
        return confirm('You have unsaved changes. Discard and navigate away?');
      }
      return true;
    };

    dateInput.addEventListener('change', (e) => {
      if (!confirmIfDirty()) { dateInput.value = this.currentDate; return; }
      this.currentDate = e.target.value;
      this.loadNote();
    });

    prevBtn.addEventListener('click', () => {
      if (!confirmIfDirty()) return;
      const d = parseLocalDate(this.currentDate);
      d.setDate(d.getDate() - 1);
      this.currentDate = formatDate(d);
      dateInput.value = this.currentDate;
      this.loadNote();
    });

    nextBtn.addEventListener('click', () => {
      if (!confirmIfDirty()) return;
      const d = parseLocalDate(this.currentDate);
      d.setDate(d.getDate() + 1);
      this.currentDate = formatDate(d);
      dateInput.value = this.currentDate;
      this.loadNote();
    });

    todayBtn.addEventListener('click', () => {
      if (!confirmIfDirty()) return;
      const now = new Date();
      this.currentDate = formatDate(now);
      dateInput.value = this.currentDate;
      this.loadNote();
    });

    saveBtn.addEventListener('click', () => this.saveNote());
    harvestBtn.addEventListener('click', () => this.harvestNote());

    if (closeHarvestBtn) {
      closeHarvestBtn.addEventListener('click', () => {
        document.getElementById('harvest-result-card').style.display = 'none';
      });
    }
  },

  pendingSnippet: null,

  async openHistoricalNote(date, snippet = '') {
    if (date) {
      this.currentDate = date;
    }
    this.pendingSnippet = snippet || null;

    if (window.App) {
      if (window.App.activeView !== 'daily_notes') {
        window.App.switchView('daily_notes');
      } else {
        const dateInput = document.getElementById('daily-note-date');
        if (dateInput) dateInput.value = this.currentDate;
        await this.loadNote();
      }
    }
  },

  highlightSnippet(snippet) {
    if (!snippet) return;
    const editor = document.getElementById('daily-note-editor');
    if (!editor) return;

    const fullText = editor.value || '';
    if (!fullText) return;

    // Clean snippet: remove markdown headers like "### YYYY-MM-DD [HH:MM] - Codex - " or score prefixes
    const cleanSnippet = snippet
      .replace(/^###\s+\d{4}-\d{2}-\d{2}\s+\[\d{2}:\d{2}\]\s*-\s*[^-]+-\s*/i, '')
      .replace(/^\d+\.\s+score=[\d.]+\s+/i, '')
      .trim();

    let startIndex = -1;
    let matchLen = 0;

    // 1. Try exact cleaned snippet match
    if (cleanSnippet.length >= 5) {
      startIndex = fullText.toLowerCase().indexOf(cleanSnippet.toLowerCase());
      if (startIndex !== -1) {
        matchLen = cleanSnippet.length;
      }
    }

    // 2. Try raw snippet match
    if (startIndex === -1 && snippet.trim().length >= 5) {
      const raw = snippet.trim();
      startIndex = fullText.toLowerCase().indexOf(raw.toLowerCase());
      if (startIndex !== -1) {
        matchLen = raw.length;
      }
    }

    // 3. Try clause/sentence segments (split by punctuation or newlines)
    if (startIndex === -1) {
      const phrases = cleanSnippet
        .split(/[.\n—–;]/)
        .map((s) => s.trim())
        .filter((s) => s.length >= 15);
      for (const phrase of phrases) {
        startIndex = fullText.toLowerCase().indexOf(phrase.toLowerCase());
        if (startIndex !== -1) {
          matchLen = phrase.length;
          break;
        }
      }
    }

    // 4. Try first 5-7 words
    if (startIndex === -1) {
      const words = cleanSnippet.split(/\s+/).slice(0, 6).join(' ');
      if (words.length >= 10) {
        startIndex = fullText.toLowerCase().indexOf(words.toLowerCase());
        if (startIndex !== -1) {
          matchLen = words.length;
        }
      }
    }

    if (startIndex !== -1) {
      const endIndex = startIndex + matchLen;
      editor.focus();
      editor.setSelectionRange(startIndex, endIndex);

      // Scroll so the match is vertically centered or near the top
      const linesBefore = fullText.substring(0, startIndex).split('\n').length;
      const totalLines = fullText.split('\n').length;
      const lineHeight = editor.scrollHeight / (totalLines || 1);
      editor.scrollTop = Math.max(0, (linesBefore - 3) * lineHeight);

      // Flash visual highlight indicator on editor border
      editor.style.transition = 'box-shadow 0.3s ease, border-color 0.3s ease';
      editor.style.boxShadow = '0 0 0 3px rgba(56, 189, 248, 0.45)';
      editor.style.borderColor = 'var(--accent-cyan)';
      setTimeout(() => {
        editor.style.boxShadow = '';
        editor.style.borderColor = '';
      }, 2200);
    }
  },

  async loadNote() {
    const editor = document.getElementById('daily-note-editor');
    const pathLabel = document.getElementById('note-filepath-label');
    if (!editor) return;

    try {
      const res = await window.gms.getDailyNote(this.currentDate);
      editor.value = res.content || '';
      this._savedContent = editor.value;
      if (pathLabel) pathLabel.innerText = res.path;

      if (this.pendingSnippet) {
        const targetSnippet = this.pendingSnippet;
        this.pendingSnippet = null;
        setTimeout(() => {
          this.highlightSnippet(targetSnippet);
        }, 80);
      }
    } catch (err) {
      window.App.showToast(`Error loading note: ${err.message}`, 'error');
    }
  },

  async saveNote() {
    const editor = document.getElementById('daily-note-editor');
    if (!editor) return;

    try {
      await window.gms.saveDailyNote({
        date: this.currentDate,
        content: editor.value,
      });
      this._savedContent = editor.value;
      window.App.showToast(`Note saved for ${this.currentDate}`, 'success');
    } catch (err) {
      window.App.showToast(`Failed to save: ${err.message}`, 'error');
    }
  },

  async harvestNote() {
    const editor = document.getElementById('daily-note-editor');
    const harvestCard = document.getElementById('harvest-result-card');
    const harvestContent = document.getElementById('harvest-result-content');
    const harvestBtn = document.getElementById('btn-harvest-note');

    if (!editor) return;

    try {
      harvestBtn.disabled = true;
      harvestBtn.innerText = 'Consolidating...';
      window.App.showToast('Extracting facts, entities, and relationships...', 'warning');

      const report = await window.gms.harvestDailyNote({
        date: this.currentDate,
        content: editor.value,
      });

      harvestCard.style.display = 'block';
      const savedCount = report.facts_saved ? report.facts_saved.length : 0;
      const rejectedCount = report.facts_rejected ? report.facts_rejected.length : 0;
      const triplesCount = report.triples_recorded || 0;
      const vectorsCount = report.vectors_indexed || 0;

      harvestContent.innerHTML = `
        <div style="display: flex; gap: 20px; margin-bottom: 14px; flex-wrap: wrap;">
          <div class="stat-pill">Saved Facts: <strong style="color: var(--accent-green);">${savedCount}</strong></div>
          <div class="stat-pill">Rejected/Violations: <strong style="color: var(--accent-red);">${rejectedCount}</strong></div>
          <div class="stat-pill">Knowledge Triples: <strong style="color: var(--accent-purple);">${triplesCount}</strong></div>
          <div class="stat-pill">Vectors Indexed: <strong style="color: var(--accent-cyan);">${vectorsCount}</strong></div>
        </div>

        ${savedCount > 0 ? `
          <div style="margin-bottom: 12px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--accent-green); margin-bottom: 6px;">✓ Facts Accepted & Ledgered:</div>
            <ul style="padding-left: 20px; font-size: 12.5px; font-family: 'SF Mono', monospace; margin: 0;">
              ${report.facts_saved.map((f) => `<li><strong>${this.escapeHtml(f.key)}</strong>: ${this.escapeHtml(JSON.stringify(f.value))}</li>`).join('')}
            </ul>
          </div>
        ` : ''}

        ${rejectedCount > 0 ? `
          <div style="margin-bottom: 10px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--accent-red); margin-bottom: 8px;">✕ Schema Violations (Action Required):</div>
            <div class="rejected-facts-list" style="display: flex; flex-direction: column; gap: 8px;">
              ${report.facts_rejected.map((f, idx) => {
                const valPreview = f.value !== undefined
                  ? (typeof f.value === 'object' ? JSON.stringify(f.value) : String(f.value))
                  : '';
                return `
                  <div class="rejected-fact-card" data-idx="${idx}" style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 10px 14px; background: rgba(248, 81, 73, 0.08); border: 1px solid rgba(248, 81, 73, 0.25); border-radius: 6px;">
                    <div style="flex: 1; min-width: 0;">
                      <div style="display: flex; align-items: baseline; gap: 8px;">
                        <strong style="color: var(--accent-red); font-family: 'SF Mono', monospace; font-size: 13px;">${this.escapeHtml(f.key)}</strong>
                        ${valPreview ? `<span style="font-size: 11px; font-family: 'SF Mono', monospace; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px;">${this.escapeHtml(valPreview)}</span>` : ''}
                      </div>
                      <div style="font-size: 12px; color: #f87171; margin-top: 4px;">
                        ${this.escapeHtml(f.error)}
                      </div>
                    </div>
                    <div style="display: flex; gap: 8px; flex-shrink: 0; align-items: center;">
                      <button class="btn-secondary btn-sm btn-stage-quarantine" data-idx="${idx}" style="font-size: 11.5px; padding: 4px 10px;" title="Stage into Quarantine for Steering triage">
                        <span>⚠️ Stage in Quarantine</span>
                      </button>
                      <button class="btn-primary btn-sm btn-fix-fact" data-idx="${idx}" style="font-size: 11.5px; padding: 4px 10px;" title="Open editor to correct schema errors and ledger fact">
                        <span>✏️ Fix Fact</span>
                      </button>
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        ` : ''}
      `;

      // Bind remediation buttons for rejected facts
      harvestContent.querySelectorAll('.btn-stage-quarantine').forEach((btn) => {
        btn.addEventListener('click', async (e) => {
          const idx = Number(e.currentTarget.dataset.idx);
          const item = report.facts_rejected[idx];
          if (!item) return;

          const button = e.currentTarget;
          try {
            button.disabled = true;
            button.innerText = 'Staging...';
            const res = await window.gms.stageInQuarantine({
              fact_key: item.key,
              value: item.value !== undefined ? item.value : (item.raw_value || ''),
              agent_id: 'daily-note',
              branch: 'main',
            });
            if (res && res.status === 'success') {
              button.innerHTML = '<span>✓ Staged</span>';
              button.style.borderColor = 'var(--accent-green)';
              button.style.color = 'var(--accent-green)';
              window.App.showToast(`Staged "${item.key}" into Quarantine for Steering triage`, 'success');
              if (window.App && window.App.refreshSnapshot) {
                window.App.refreshSnapshot();
              }
            } else {
              button.disabled = false;
              button.innerText = '⚠️ Stage in Quarantine';
              window.App.showToast(`Failed to stage: ${res?.message || 'unknown error'}`, 'error');
            }
          } catch (err) {
            button.disabled = false;
            button.innerText = '⚠️ Stage in Quarantine';
            window.App.showToast(`Failed to stage: ${err.message}`, 'error');
          }
        });
      });

      harvestContent.querySelectorAll('.btn-fix-fact').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const idx = Number(e.currentTarget.dataset.idx);
          const item = report.facts_rejected[idx];
          if (!item) return;

          // Attempt to highlight the corresponding line in daily-note-editor if present
          this.highlightSnippet(item.key);

          // Open the global edit fact modal with pre-populated key, value, and schema error
          if (window.App && window.App.openEditFactModal) {
            window.App.openEditFactModal({
              key: item.key,
              value: item.value !== undefined ? item.value : '',
              error: item.error,
            });
          }
        });
      });

      window.App.showToast(`Consolidation complete: ${savedCount} facts, ${triplesCount} triples, ${vectorsCount} vectors.`, 'success');
      window.App.refreshSnapshot();
    } catch (err) {
      window.App.showToast(`Harvest failed: ${err.message}`, 'error');
    } finally {
      harvestBtn.disabled = false;
      harvestBtn.innerHTML = `<span>⚡</span><span>Process into Memory</span>`;
    }
  },

  escapeHtml(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },
};
