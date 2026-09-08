window.ConceptsView = {
  rawConcepts: {},
  filterType: '',
  searchQuery: '',

  async render(container) {
    container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <div>
          <h2 style="font-size: 20px; font-weight: 700; margin-bottom: 4px;">Concepts & Entity Catalog</h2>
          <p style="font-size: 13px; color: var(--text-secondary);">Browse structured concepts, infrastructure nodes, models, and policies extracted across all sessions.</p>
        </div>
      </div>

      <!-- Extraction Scratchpad Card -->
      <div class="card" style="border-left: 4px solid var(--accent-purple);">
        <div class="card-title" style="font-size: 14px; margin-bottom: 8px;">
          <span>🧪 Real-Time Entity & Triple Extraction Scratchpad</span>
        </div>
        <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: 10px;">
          Paste raw text, terminal output, or logs to test GMS entity extraction and relationship discovery without saving.
        </p>
        <div style="display: flex; gap: 10px;">
          <textarea id="scratchpad-input" class="form-control" style="min-height: 70px; font-size: 12px; flex: 1;" placeholder="Paste sample text here... e.g. Model Qwen-2.5 is hosted on node infra.minipc running port 11434..."></textarea>
          <button class="btn-primary" id="btn-run-extraction" style="align-self: flex-start; padding: 8px 14px;">Extract</button>
        </div>
        <div id="scratchpad-results" style="margin-top: 12px; display: none;"></div>
      </div>

      <!-- Type Filter Chips -->
      <div id="concept-type-filters" style="display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;"></div>

      <!-- Concepts Grid -->
      <div id="concepts-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px;">
        <div style="text-align: center; color: var(--text-muted); padding: 30px; grid-column: 1 / -1;">Loading concept entities...</div>
      </div>
    `;

    this.bindEvents(container);
    await this.loadConcepts();
  },

  bindEvents(container) {
    const extractBtn = container.querySelector('#btn-run-extraction');
    if (extractBtn) {
      extractBtn.addEventListener('click', () => this.runScratchpadExtraction());
    }
  },

  async loadConcepts() {
    const grid = document.getElementById('concepts-grid');
    const filtersContainer = document.getElementById('concept-type-filters');
    if (!grid) return;

    try {
      const res = await window.gms.getConcepts();
      this.rawConcepts = res.groups || {};

      // Render filter chips
      if (filtersContainer) {
        const types = Object.keys(this.rawConcepts);
        filtersContainer.innerHTML = `
          <button class="badge filter-type-btn active" data-type="" style="cursor: pointer; border: 1px solid var(--accent-blue); background: rgba(88, 166, 255, 0.15); color: var(--accent-blue);">
            All (${res.total_entities || 0})
          </button>
          ${types.map((t) => `
            <button class="badge filter-type-btn" data-type="${t}" style="cursor: pointer; border: 1px solid var(--border-color); background: var(--bg-surface); color: var(--text-secondary);">
              ${t} (${this.rawConcepts[t].length})
            </button>
          `).join('')}
        `;

        filtersContainer.querySelectorAll('.filter-type-btn').forEach((btn) => {
          btn.addEventListener('click', (e) => {
            filtersContainer.querySelectorAll('.filter-type-btn').forEach((b) => {
              b.style.borderColor = 'var(--border-color)';
              b.style.color = 'var(--text-secondary)';
              b.style.background = 'var(--bg-surface)';
            });
            e.target.style.borderColor = 'var(--accent-blue)';
            e.target.style.color = 'var(--accent-blue)';
            e.target.style.background = 'rgba(88, 166, 255, 0.15)';
            this.filterType = e.target.dataset.type;
            this.renderEntitiesGrid();
          });
        });
      }

      this.renderEntitiesGrid();
    } catch (err) {
      grid.innerHTML = `<div style="color: var(--accent-red); padding: 20px; grid-column: 1 / -1;">Error loading concepts: ${err.message}</div>`;
    }
  },

  renderEntitiesGrid() {
    const grid = document.getElementById('concepts-grid');
    if (!grid) return;

    let entities = [];
    if (this.filterType && this.rawConcepts[this.filterType]) {
      entities = this.rawConcepts[this.filterType];
    } else {
      Object.values(this.rawConcepts).forEach((group) => {
        entities = entities.concat(group);
      });
    }

    if (this.searchQuery) {
      const q = this.searchQuery.toLowerCase();
      entities = entities.filter((e) => e.name.toLowerCase().includes(q) || (e.summary && e.summary.toLowerCase().includes(q)));
    }

    if (entities.length === 0) {
      grid.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 40px; grid-column: 1 / -1;">No concepts match current filter.</div>`;
      return;
    }

    grid.innerHTML = entities.slice(0, 90).map((e) => {
      return `
        <div style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 12px 14px; display: flex; flex-direction: column;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
            <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); word-break: break-all;">${this.escapeHtml(e.name)}</div>
            <span class="badge" style="font-size: 10px; background: rgba(88, 166, 255, 0.12); color: var(--accent-blue);">${e.type}</span>
          </div>
          <div style="font-size: 11.5px; color: var(--text-secondary); margin-bottom: 8px; flex: 1;">
            ${e.summary ? this.escapeHtml(e.summary) : '<span style="color: var(--text-muted); font-style: italic;">No summary</span>'}
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--border-subtle); padding-top: 6px; font-size: 11px; color: var(--text-muted);">
            <span>Connected Edges: <strong>${e.edge_count || 0}</strong></span>
          </div>
        </div>
      `;
    }).join('');
  },

  async runScratchpadExtraction() {
    const input = document.getElementById('scratchpad-input');
    const resultsContainer = document.getElementById('scratchpad-results');
    if (!input || !resultsContainer || !input.value.trim()) return;

    try {
      resultsContainer.style.display = 'block';
      resultsContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 12px;">Extracting entities and triples...</div>';

      const res = await window.gms.extractText({ text: input.value.trim() });
      const facts = res.candidate_facts || [];
      const triples = res.extracted_triples || [];

      resultsContainer.innerHTML = `
        <div style="background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 12px;">
          <div style="display: flex; gap: 14px; margin-bottom: 8px;">
            <span style="font-size: 12px; font-weight: 600; color: var(--accent-green);">Candidate Facts: ${facts.length}</span>
            <span style="font-size: 12px; font-weight: 600; color: var(--accent-purple);">Extracted Triples: ${triples.length}</span>
          </div>

          ${facts.length > 0 ? `
            <div style="font-size: 11.5px; font-family: 'SF Mono', monospace; margin-bottom: 6px;">
              ${facts.map((f) => `<div style="color: ${f.valid ? 'var(--accent-green)' : 'var(--accent-red)'};">• [${f.key}] = ${JSON.stringify(f.value)} ${f.valid ? '✓' : '✕ ' + f.error}</div>`).join('')}
            </div>
          ` : ''}

          ${triples.length > 0 ? `
            <div style="font-size: 11.5px; font-family: 'SF Mono', monospace;">
              ${triples.map((t) => `<div style="color: var(--accent-blue);">• (${t.subject}) ──[${t.predicate}]──▶ (${t.object})</div>`).join('')}
            </div>
          ` : ''}

          ${facts.length === 0 && triples.length === 0 ? '<div style="font-size: 12px; color: var(--text-muted);">No structured facts or entity triples identified in input text.</div>' : ''}
        </div>
      `;
    } catch (err) {
      resultsContainer.innerHTML = `<div style="color: var(--accent-red); font-size: 12px;">Extraction failed: ${err.message}</div>`;
    }
  },

  escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};
