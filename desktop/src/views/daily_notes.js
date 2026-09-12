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

    dateInput.addEventListener('change', (e) => {
      this.currentDate = e.target.value;
      this.loadNote();
    });

    prevBtn.addEventListener('click', () => {
      const d = new Date(this.currentDate);
      d.setDate(d.getDate() - 1);
      this.currentDate = d.toISOString().split('T')[0];
      dateInput.value = this.currentDate;
      this.loadNote();
    });

    nextBtn.addEventListener('click', () => {
      const d = new Date(this.currentDate);
      d.setDate(d.getDate() + 1);
      this.currentDate = d.toISOString().split('T')[0];
      dateInput.value = this.currentDate;
      this.loadNote();
    });

    todayBtn.addEventListener('click', () => {
      this.currentDate = new Date().toISOString().split('T')[0];
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

  async loadNote() {
    const editor = document.getElementById('daily-note-editor');
    const pathLabel = document.getElementById('note-filepath-label');
    if (!editor) return;

    try {
      const res = await window.gms.getDailyNote(this.currentDate);
      editor.value = res.content || '';
      if (pathLabel) pathLabel.innerText = res.path;
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
          <div style="margin-bottom: 10px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--accent-green); margin-bottom: 4px;">✓ Facts Accepted & Ledgered:</div>
            <ul style="padding-left: 20px; font-size: 12.5px; font-family: 'SF Mono', monospace;">
              ${report.facts_saved.map((f) => `<li><strong>${f.key}</strong>: ${JSON.stringify(f.value)}</li>`).join('')}
            </ul>
          </div>
        ` : ''}

        ${rejectedCount > 0 ? `
          <div style="margin-bottom: 10px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--accent-red); margin-bottom: 4px;">✕ Schema Violations (Rejected):</div>
            <ul style="padding-left: 20px; font-size: 12.5px; font-family: 'SF Mono', monospace; color: var(--accent-red);">
              ${report.facts_rejected.map((f) => `<li><strong>${f.key}</strong>: ${f.error}</li>`).join('')}
            </ul>
          </div>
        ` : ''}
      `;

      window.App.showToast(`Consolidation complete: ${savedCount} facts, ${triplesCount} triples, ${vectorsCount} vectors.`, 'success');
      window.App.refreshSnapshot();
    } catch (err) {
      window.App.showToast(`Harvest failed: ${err.message}`, 'error');
    } finally {
      harvestBtn.disabled = false;
      harvestBtn.innerHTML = `<span>⚡</span><span>Process into Memory</span>`;
    }
  },
};
