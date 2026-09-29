window.SearchPalette = {
  isOpen: false,
  query: '',
  results: null,
  selectedIndex: -1,
  flatResults: [],
  debounceTimer: null,

  init() {
    this.injectPaletteHTML();
    this.bindEvents();
  },

  injectPaletteHTML() {
    if (document.getElementById('modal-search-palette')) return;

    const overlay = document.createElement('div');
    overlay.id = 'modal-search-palette';
    overlay.className = 'search-palette-overlay';
    overlay.style.display = 'none';

    overlay.innerHTML = `
      <div class="search-palette-modal">
        <div class="search-palette-header">
          <span class="search-palette-icon">⌕</span>
          <input type="text" id="search-palette-input" placeholder="Search memories, entities, triples, projects, and context (Cmd+K)..." autocomplete="off" spellcheck="false" />
          <kbd class="search-palette-esc">ESC</kbd>
        </div>
        <div class="search-palette-body" id="search-palette-body">
          <div class="search-palette-empty-prompt">
            <span style="font-size:24px; opacity:0.6;">⌘K</span>
            <p>Type to search across all knowledge tiers, entities, relationships, and projects.</p>
            <div class="search-palette-quick-links">
              <button class="palette-quick-btn" data-query="alphaos">AlphaOS</button>
              <button class="palette-quick-btn" data-query="decision">Decisions</button>
              <button class="palette-quick-btn" data-query="trading">Trading</button>
              <button class="palette-quick-btn" data-query="policy">Policies</button>
            </div>
          </div>
        </div>
        <div class="search-palette-footer">
          <span><kbd>↑</kbd> <kbd>↓</kbd> Navigate</span>
          <span><kbd>↵</kbd> Open</span>
          <span><kbd>ESC</kbd> Close</span>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
  },

  bindEvents() {
    const overlay = document.getElementById('modal-search-palette');
    const input = document.getElementById('search-palette-input');
    if (!overlay || !input) return;

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.close();
    });

    input.addEventListener('input', (e) => {
      clearTimeout(this.debounceTimer);
      const val = e.target.value;
      this.query = val;
      if (!val.trim()) {
        this.renderEmptyPrompt();
        return;
      }
      this.debounceTimer = setTimeout(() => this.performSearch(val.trim()), 150);
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        this.close();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.navigate(1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.navigate(-1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        this.activateSelected();
      }
    });

    overlay.addEventListener('click', (e) => {
      const quickBtn = e.target.closest('.palette-quick-btn');
      if (quickBtn) {
        input.value = quickBtn.dataset.query;
        this.query = quickBtn.dataset.query;
        this.performSearch(this.query);
        input.focus();
        return;
      }

      const item = e.target.closest('.search-palette-item');
      if (item) {
        const idx = parseInt(item.dataset.index, 10);
        if (!isNaN(idx) && this.flatResults[idx]) {
          this.executeItem(this.flatResults[idx]);
        }
      }
    });

    // Global shortcut Cmd+K or Ctrl+K
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        this.toggle();
      }
      if (e.key === 'Escape' && this.isOpen) {
        this.close();
      }
    });
  },

  open() {
    const overlay = document.getElementById('modal-search-palette');
    const input = document.getElementById('search-palette-input');
    if (!overlay || !input) return;

    overlay.style.display = 'flex';
    this.isOpen = true;
    input.focus();
    input.select();
    if (this.query.trim()) {
      this.performSearch(this.query.trim());
    } else {
      this.renderEmptyPrompt();
    }
  },

  close() {
    const overlay = document.getElementById('modal-search-palette');
    if (overlay) overlay.style.display = 'none';
    this.isOpen = false;
  },

  toggle() {
    if (this.isOpen) this.close();
    else this.open();
  },

  renderEmptyPrompt() {
    const body = document.getElementById('search-palette-body');
    if (!body) return;
    this.flatResults = [];
    this.selectedIndex = -1;
    body.innerHTML = `
      <div class="search-palette-empty-prompt">
        <span style="font-size:24px; opacity:0.6;">⌘K</span>
        <p>Type to search across all knowledge tiers, entities, relationships, and projects.</p>
        <div class="search-palette-quick-links">
          <button class="palette-quick-btn" data-query="alphaos">AlphaOS</button>
          <button class="palette-quick-btn" data-query="decision">Decisions</button>
          <button class="palette-quick-btn" data-query="trading">Trading</button>
          <button class="palette-quick-btn" data-query="policy">Policies</button>
        </div>
      </div>
    `;
  },

  async performSearch(query) {
    const body = document.getElementById('search-palette-body');
    if (!body) return;
    body.innerHTML = '<div class="search-palette-loading">Searching knowledge graph and memory...</div>';

    try {
      const res = await window.gms.hybridSearch({ q: query, limit: 15 });
      this.results = res;
      this.renderResults(res);
    } catch (err) {
      body.innerHTML = `<div class="search-palette-error">Search failed: ${this.escapeHtml(err.message)}</div>`;
    }
  },

  renderResults(res) {
    const body = document.getElementById('search-palette-body');
    if (!body) return;

    this.flatResults = [];
    let html = '';
    let globalIndex = 0;

    const memories = res.memories || [];
    const entities = res.entities || [];
    const triples = res.triples || [];
    const projects = res.projects || [];
    const vectorHits = res.vector_hits || [];

    const totalMatches = memories.length + entities.length + triples.length + projects.length + vectorHits.length;
    if (totalMatches === 0) {
      body.innerHTML = `<div class="search-palette-empty">No results found for "<strong>${this.escapeHtml(this.query)}</strong>"</div>`;
      this.flatResults = [];
      this.selectedIndex = -1;
      return;
    }

    // 1. Projects
    if (projects.length > 0) {
      html += `<div class="search-palette-group"><div class="search-palette-group-title">PROJECTS</div>`;
      projects.forEach((p) => {
        this.flatResults.push({ type: 'project', data: p });
        html += `
          <div class="search-palette-item ${globalIndex === 0 ? 'selected' : ''}" data-index="${globalIndex}">
            <span class="palette-item-icon">📁</span>
            <div class="palette-item-content">
              <div class="palette-item-title">${this.escapeHtml(p.title || p.project_id)}</div>
              <div class="palette-item-sub">${this.escapeHtml(p.purpose_preview || p.project_id)}</div>
            </div>
            <span class="badge badge-general">Project</span>
          </div>
        `;
        globalIndex++;
      });
      html += `</div>`;
    }

    // 2. Entities
    if (entities.length > 0) {
      html += `<div class="search-palette-group"><div class="search-palette-group-title">ENTITIES & CONCEPTS</div>`;
      entities.forEach((e) => {
        this.flatResults.push({ type: 'entity', data: e });
        html += `
          <div class="search-palette-item" data-index="${globalIndex}">
            <span class="palette-item-icon">✦</span>
            <div class="palette-item-content">
              <div class="palette-item-title">${this.escapeHtml(e.name)}</div>
              <div class="palette-item-sub">${this.escapeHtml(e.summary || e.entity_type)}</div>
            </div>
            <span class="badge badge-cyan">${this.escapeHtml(e.entity_type || 'CONCEPT')}</span>
          </div>
        `;
        globalIndex++;
      });
      html += `</div>`;
    }

    // 3. Memories
    if (memories.length > 0) {
      html += `<div class="search-palette-group"><div class="search-palette-group-title">MEMORIES & DECISIONS</div>`;
      memories.forEach((m) => {
        this.flatResults.push({ type: 'memory', data: m });
        const valPreview = typeof m.value === 'object' ? JSON.stringify(m.value).slice(0, 100) : String(m.value).slice(0, 100);
        html += `
          <div class="search-palette-item" data-index="${globalIndex}">
            <span class="palette-item-icon">⌁</span>
            <div class="palette-item-content">
              <div class="palette-item-title">${this.escapeHtml(m.key)}</div>
              <div class="palette-item-sub">${this.escapeHtml(valPreview)}</div>
            </div>
            <span class="badge badge-tier">${this.escapeHtml(m.tier || 'semantic')}</span>
          </div>
        `;
        globalIndex++;
      });
      html += `</div>`;
    }

    // 4. Graph Triples
    if (triples.length > 0) {
      html += `<div class="search-palette-group"><div class="search-palette-group-title">KNOWLEDGE GRAPH RELATIONSHIPS</div>`;
      triples.forEach((t) => {
        this.flatResults.push({ type: 'triple', data: t });
        html += `
          <div class="search-palette-item" data-index="${globalIndex}">
            <span class="palette-item-icon">🕸️</span>
            <div class="palette-item-content">
              <div class="palette-item-title">${this.escapeHtml(t.subject)} <span style="color:var(--accent-cyan); font-weight:400;">${this.escapeHtml(t.predicate)}</span> ${this.escapeHtml(t.object)}</div>
              <div class="palette-item-sub">Knowledge Graph triple</div>
            </div>
            <span class="badge badge-general">Graph</span>
          </div>
        `;
        globalIndex++;
      });
      html += `</div>`;
    }

    // 5. Vector / Episodic Hits
    if (vectorHits.length > 0) {
      html += `<div class="search-palette-group"><div class="search-palette-group-title">EPISODIC VECTORS & LOGS</div>`;
      vectorHits.forEach((v) => {
        this.flatResults.push({ type: 'vector', data: v });
        html += `
          <div class="search-palette-item" data-index="${globalIndex}">
            <span class="palette-item-icon">📜</span>
            <div class="palette-item-content">
              <div class="palette-item-title">${this.escapeHtml(v.header)}</div>
              <div class="palette-item-sub">${this.escapeHtml(v.snippet.slice(0, 120))}</div>
            </div>
            <span class="badge badge-general">Episodic</span>
          </div>
        `;
        globalIndex++;
      });
      html += `</div>`;
    }

    body.innerHTML = html;
    this.selectedIndex = 0;
    this.updateSelectionVisuals();
  },

  navigate(dir) {
    if (this.flatResults.length === 0) return;
    this.selectedIndex += dir;
    if (this.selectedIndex < 0) this.selectedIndex = this.flatResults.length - 1;
    if (this.selectedIndex >= this.flatResults.length) this.selectedIndex = 0;
    this.updateSelectionVisuals();
  },

  updateSelectionVisuals() {
    const items = document.querySelectorAll('.search-palette-item');
    items.forEach((it, idx) => {
      const isSelected = idx === this.selectedIndex;
      it.classList.toggle('selected', isSelected);
      if (isSelected) {
        it.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });
  },

  activateSelected() {
    if (this.selectedIndex >= 0 && this.selectedIndex < this.flatResults.length) {
      this.executeItem(this.flatResults[this.selectedIndex]);
    }
  },

  executeItem(item) {
    this.close();
    if (!item) return;

    if (item.type === 'project') {
      const pid = item.data.project_id;
      if (window.App && window.App.openProject) {
        window.App.openProject(pid);
      }
    } else if (item.type === 'entity') {
      const entityId = item.data.entity_id;
      const entityName = item.data.name;
      if (window.App && window.App.openInGraph) {
        window.App.openInGraph(String(entityId), entityName);
      }
    } else if (item.type === 'memory') {
      const key = item.data.key;
      if (window.App && window.App.exploreRelated) {
        window.App.exploreRelated(key);
      }
    } else if (item.type === 'triple') {
      const subject = item.data.subject;
      if (window.App && window.App.openInGraph) {
        window.App.openInGraph('', subject);
      }
    } else if (item.type === 'vector') {
      const data = item.data || item;
      let targetDate = data.date || item.date;
      const targetFile = data.file || item.file || '';
      const snippet = data.snippet || item.snippet || '';
      const header = data.header || item.header || '';

      if (!targetDate) {
        const textToSearch = `${header} ${snippet} ${targetFile}`;
        const match = textToSearch.match(/\b(\d{4}-\d{2}-\d{2})\b/);
        if (match) {
          targetDate = match[1];
        }
      }

      if (window.DailyNotesView && window.DailyNotesView.openHistoricalNote && targetDate) {
        window.DailyNotesView.openHistoricalNote(targetDate, snippet);
      } else {
        if (window.DailyNotesView && targetDate) {
          window.DailyNotesView.currentDate = targetDate;
          window.DailyNotesView.pendingSnippet = snippet;
        }
        if (window.App && window.App.switchView) {
          window.App.switchView('daily_notes');
        }
      }
    }
  },

  escapeHtml(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },
};
