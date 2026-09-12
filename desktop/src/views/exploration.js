window.ExplorationView = {
  currentTier: 'all',
  currentNamespace: '',
  currentSort: 'recent',
  searchQuery: '',
  memories: [],
  selectedKey: '',
  cachedFacetCounts: null,
  cachedSourceCounts: null,
  cachedTierTotal: 0,

  async render(container) {
    container.innerHTML = `
      <div class="view-heading">
        <div><div class="eyebrow">Knowledge workspace</div><h2>Explore</h2><p>Move through memories by type, namespace, source, and relationship.</p></div>
        <div style="display:flex;gap:10px;align-items:center"><button class="btn-secondary open-memory-quality">Memory Quality</button><div class="segmented-control" id="tier-filters">
          ${['all', 'semantic', 'episodic', 'operational', 'procedural'].map((tier) => `<button class="segment filter-tier ${this.currentTier === tier ? 'active' : ''}" data-tier="${tier}">${tier === 'all' ? 'All' : this.title(tier)}</button>`).join('')}
        </div></div>
      </div>
      <div class="explore-layout">
        <aside class="explore-facets card"><div class="panel-label">Namespaces</div><div id="namespace-list" class="facet-list"></div><div class="panel-label source-heading">Sources</div><div id="source-list" class="source-list"></div></aside>
        <section class="memory-browser card">
          <div class="browser-toolbar">
            <div><strong id="memory-result-count">Loading…</strong><span class="muted"> memories</span></div>
            <div style="display:flex; align-items:center; gap:8px;">
              <label for="sort-select" style="color:var(--text-muted); font-size:11px;">Sort:</label>
              <select id="sort-select" class="sort-select" style="background:#151c27; color:#c5d2e3; border:1px solid var(--border-color); border-radius:6px; padding:3px 8px; font-size:11px; outline:none; cursor:pointer;">
                <option value="recent">Recent activity</option>
                <option value="newest">Newest recorded</option>
                <option value="oldest">Oldest recorded</option>
                <option value="alpha">Name (A–Z)</option>
              </select>
            </div>
          </div>
          <div id="memories-list" class="memory-list"></div>
        </section>
        <aside class="memory-inspector card" id="memory-inspector"><div class="empty-inspector"><div class="empty-icon">⌁</div><strong>Select a memory</strong><span>Its complete value, provenance, and actions will appear here.</span></div></aside>
      </div>`;
    this.bindEvents(container);
    await this.loadMemories();
  },

  bindEvents(container) {
    const mq=container.querySelector('.open-memory-quality'); if(mq) mq.addEventListener('click',()=>window.App.openMemoryQuality());
    container.querySelectorAll('.filter-tier').forEach((btn) => btn.addEventListener('click', (e) => {
      container.querySelectorAll('.filter-tier').forEach((b) => b.classList.remove('active'));
      e.currentTarget.classList.add('active');
      this.currentTier = e.currentTarget.dataset.tier;
      this.currentNamespace = '';
      this.cachedFacetCounts = null;
      this.cachedSourceCounts = null;
      this.selectedKey = '';
      this.loadMemories();
    }));

    const sortSelect = container.querySelector('#sort-select');
    if (sortSelect) {
      sortSelect.value = this.currentSort;
      sortSelect.addEventListener('change', (e) => {
        this.currentSort = e.target.value;
        this.loadMemories();
      });
    }
  },

  async loadMemories() {
    const list = document.getElementById('memories-list');
    if (!list) return;
    list.innerHTML = '<div class="loading-state">Loading your memory…</div>';
    try {
      const res = await window.gms.getMemories({
        tier: this.currentTier,
        namespace: this.currentNamespace,
        q: this.searchQuery,
        sort: this.currentSort,
        limit: 250
      });
      this.memories = res.memories || [];
      this.renderFacets();
      this.renderList(res.total || 0);
      if (this.selectedKey) {
        const selected = this.memories.find((m) => m.key === this.selectedKey);
        if (selected) this.selectMemory(selected);
        else {
          const inspector = document.getElementById('memory-inspector');
          if (inspector) inspector.innerHTML = '<div class="empty-inspector"><div class="empty-icon">⌁</div><strong>Select a memory</strong><span>Its complete value, provenance, and actions will appear here.</span></div>';
        }
      } else {
        const inspector = document.getElementById('memory-inspector');
        if (inspector) inspector.innerHTML = '<div class="empty-inspector"><div class="empty-icon">⌁</div><strong>Select a memory</strong><span>Its complete value, provenance, and actions will appear here.</span></div>';
      }
    } catch (err) {
      list.innerHTML = `<div class="error-state">Could not load memories<br><small>${this.escapeHtml(err.message)}</small></div>`;
    }
  },

  renderFacets() {
    if (!this.currentNamespace || !this.cachedFacetCounts) {
      const nsCounts = {}, sourceCounts = {};
      this.memories.forEach((m) => {
        const ns = m.namespace || 'general';
        nsCounts[ns] = (nsCounts[ns] || 0) + 1;
        sourceCounts[m.source] = (sourceCounts[m.source] || 0) + 1;
      });
      this.cachedFacetCounts = nsCounts;
      this.cachedSourceCounts = sourceCounts;
      this.cachedTierTotal = this.memories.length;
    }

    const nsCounts = this.cachedFacetCounts || {};
    const sourceCounts = this.cachedSourceCounts || {};
    const totalAll = this.cachedTierTotal || this.memories.length;

    const nsEl = document.getElementById('namespace-list');
    const sourceEl = document.getElementById('source-list');
    if (nsEl) {
      const entries = Object.entries(nsCounts).sort((a, b) => b[1] - a[1]);
      nsEl.innerHTML = `<button class="facet-item ${!this.currentNamespace ? 'active' : ''}" data-ns=""><span>All memory</span><b>${totalAll}</b></button>` +
        entries.map(([ns, count]) => `<button class="facet-item ${this.currentNamespace === ns ? 'active' : ''}" data-ns="${this.escapeHtml(ns)}"><span><i class="namespace-dot ns-${this.escapeHtml(ns)}"></i>${this.escapeHtml(ns)}</span><b>${count}</b></button>`).join('');
      nsEl.querySelectorAll('.facet-item').forEach((btn) => btn.addEventListener('click', () => {
        this.currentNamespace = btn.dataset.ns;
        this.selectedKey = '';
        this.loadMemories();
      }));
    }
    if (sourceEl) {
      sourceEl.innerHTML = Object.entries(sourceCounts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([source, count]) => `<div class="source-item"><span title="${this.escapeHtml(source)}">${this.escapeHtml(source)}</span><b>${count}</b></div>`).join('');
    }
  },

  formatTimeAgo(dateStr) {
    if (!dateStr) return '';
    try {
      const s = String(dateStr);
      const d = new Date(s.replace(' ', 'T'));
      if (isNaN(d.getTime())) return s.slice(0, 10);
      const now = new Date();
      const diffSec = Math.floor((now - d) / 1000);
      if (diffSec <= 60) return 'Just now';
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      if (diffSec < 86400 * 7) return `${Math.floor(diffSec / 86400)}d ago`;
      return d.toISOString().slice(0, 10);
    } catch (e) {
      return String(dateStr).slice(0, 10);
    }
  },

  timeGroup(dateStr) {
    if (!dateStr) return 'Unknown date';
    const s = String(dateStr);
    const date = new Date(s.replace(' ', 'T'));
    if (isNaN(date.getTime())) return 'Unknown date';
    const now = new Date();
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const days = Math.floor((startToday - startDate) / 86400000);
    if (days <= 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return 'Earlier this week';
    if (days < 31) return 'This month';
    if (date.getFullYear() === now.getFullYear()) return date.toLocaleDateString(undefined, { month: 'long' });
    return String(date.getFullYear());
  },

  renderList(total) {
    const list = document.getElementById('memories-list');
    const count = document.getElementById('memory-result-count');
    if (count) count.textContent = total;
    if (!this.memories.length) {
      list.innerHTML = '<div class="empty-list"><strong>No memories found</strong><span>Try another type, namespace, or search.</span></div>';
      return;
    }
    let previousGroup = '';
    list.innerHTML = this.memories.map((m) => {
      let preview = '';
      let parsedObj = null;
      if (typeof m.value === 'object' && m.value !== null) {
        parsedObj = m.value;
      } else if (typeof m.value === 'string' && m.value.trim().startsWith('{')) {
        try { parsedObj = JSON.parse(m.value); } catch (e) {}
      }
      if (parsedObj) {
        const recType = parsedObj.record_type;
        if (recType === 'decision' || recType === 'policy' || parsedObj.decision) {
          const stmt = parsedObj.statement || parsedObj.decision || m.key;
          const rat = parsedObj.rationale ? ` — Rationale: ${parsedObj.rationale}` : '';
          preview = (stmt + rat).replace(/\s+/g, ' ').slice(0, 155);
        } else if (recType === 'fact' || parsedObj.statement) {
          const stmt = parsedObj.statement || m.key;
          const ev = (parsedObj.provenance?.source_refs || [])[0] ? ` [${parsedObj.provenance.source_refs[0]}]` : '';
          preview = (stmt + ev).replace(/\s+/g, ' ').slice(0, 155);
        } else if (recType === 'project_state') {
          const stmt = parsedObj.statement || m.key;
          const eff = parsedObj.freshness?.effective_at ? ` (${parsedObj.freshness.effective_at.slice(0, 10)})` : '';
          preview = (stmt + eff).replace(/\s+/g, ' ').slice(0, 155);
        } else if (recType === 'question') {
          const q = parsedObj.question || parsedObj.statement || m.key;
          const why = parsedObj.why_it_matters ? ` (Why: ${parsedObj.why_it_matters})` : '';
          preview = (q + why).replace(/\s+/g, ' ').slice(0, 155);
        }
      }
      if (!preview) {
        const raw = typeof m.value === 'object' ? JSON.stringify(m.value) : String(m.value);
        preview = raw.replace(/\s+/g, ' ').slice(0, 155);
      }
      const rawLen = typeof m.value === 'object' ? JSON.stringify(m.value).length : String(m.value).length;
      const displayTime = this.currentSort === 'newest' || this.currentSort === 'oldest' ? m.created_at : m.activity_at;
      const timeAgo = this.formatTimeAgo(displayTime);
      let groupHeader = '';
      if (this.currentSort !== 'alpha') {
        const group = this.timeGroup(displayTime);
        if (group !== previousGroup) {
          previousGroup = group;
          groupHeader = `<div class="memory-time-group"><span>${this.escapeHtml(group)}</span></div>`;
        }
      }
      return `${groupHeader}<button class="memory-row ${this.selectedKey === m.key ? 'selected' : ''}" data-key="${this.escapeHtml(m.key)}"><span class="memory-type-mark type-${this.escapeHtml(m.tier)}"></span><span class="memory-row-body"><span class="memory-row-top"><strong>${this.escapeHtml(m.key)}</strong><span style="display:flex; align-items:center; gap:6px;">${timeAgo ? `<time style="color:#8ea3c0; font-size:10px;" title="${this.escapeHtml(displayTime)}">${this.escapeHtml(timeAgo)}</time>` : ''}<em>${this.escapeHtml(m.namespace || m.tier)}</em></span></span><span class="memory-preview">${this.escapeHtml(preview)}${rawLen > 155 ? '…' : ''}</span><span class="memory-source">${this.escapeHtml(m.source)}${m.agent ? ` · <span style="color:#6d7f96;">${this.escapeHtml(m.agent)}</span>` : ''}</span></span><span class="row-chevron">›</span></button>`;
    }).join('');
    list.querySelectorAll('.memory-row').forEach((row) => row.addEventListener('click', () => {
      const memory = this.memories.find((m) => m.key === row.dataset.key);
      if (memory) this.selectMemory(memory);
    }));
  },

  selectMemory(memory) {
    if (!memory) return;
    this.selectedKey = memory.key;
    document.querySelectorAll('.memory-row').forEach((row) => row.classList.toggle('selected', row.dataset.key === memory.key));
    const inspector = document.getElementById('memory-inspector');
    if (!inspector) return;

    try {
      const value = typeof memory.value === 'object' ? JSON.stringify(memory.value, null, 2) : String(memory.value);
      const terms = [String(memory.key || ''), ...String(memory.key || '').split(/[._/-]/).filter((x) => x.length > 2)];
      const valueHtml = this.renderValueBlock(memory, value);

      inspector.innerHTML = `<div class="inspector-header"><div><span class="badge badge-general">${this.escapeHtml(memory.tier)}</span><h3>${this.escapeHtml(memory.key)}</h3></div><button class="icon-button" id="close-memory-inspector" title="Close">×</button></div><div class="inspector-meta"><div><span>Namespace</span><button class="text-link" id="inspect-namespace">${this.escapeHtml(memory.namespace || 'general')}</button></div><div><span>Source</span><strong>${this.escapeHtml(memory.source)}</strong></div>${memory.created_at ? `<div><span>First recorded</span><strong title="${this.escapeHtml(memory.created_at)}">${this.escapeHtml(this.formatTimeAgo(memory.created_at))}</strong></div>` : ''}${memory.updated_at ? `<div><span>Last changed</span><strong title="${this.escapeHtml(memory.updated_at)}">${this.escapeHtml(this.formatTimeAgo(memory.updated_at))}</strong></div>` : ''}${memory.agent ? `<div><span>Author</span><strong style="color:#8da5c4;">${this.escapeHtml(memory.agent)}</strong></div>` : ''}</div><div class="panel-label">Complete value</div>${valueHtml}<div class="panel-label">Entity paths</div><div class="related-chips">${terms.slice(0, 5).map((term) => `<button data-term="${this.escapeHtml(term)}">${this.escapeHtml(term)}</button>`).join('')}</div><div class="inspector-actions"><button class="btn-secondary" id="inspect-view-graph" style="display:flex; align-items:center; gap:5px;"><span>🕸️</span><span>View in Graph</span></button><button class="btn-secondary" id="inspect-find-related">Find related</button><button class="btn-primary" id="inspect-edit">Edit memory</button></div>`;
      inspector.querySelector('#close-memory-inspector').addEventListener('click', () => { this.selectedKey = ''; this.renderList(this.memories.length); inspector.innerHTML = '<div class="empty-inspector"><div class="empty-icon">⌁</div><strong>Select a memory</strong><span>Its complete value, provenance, and actions will appear here.</span></div>'; });
      inspector.querySelector('#inspect-namespace').addEventListener('click', () => { this.currentNamespace = memory.namespace || ''; this.selectedKey = ''; this.loadMemories(); });
      inspector.querySelector('#inspect-edit').addEventListener('click', () => window.App.openEditFactModal(memory));
      inspector.querySelector('#inspect-view-graph').addEventListener('click', () => window.App.openInGraph('', memory.key));
      inspector.querySelector('#inspect-find-related').addEventListener('click', () => this.setSearchQuery(String(memory.key || '').split(/[._/-]/).pop()));
      inspector.querySelectorAll('.related-chips button').forEach((btn) => btn.addEventListener('click', () => {
        window.App.openInGraph('', btn.dataset.term);
      }));
    } catch (err) {
      console.error('Failed to render inspector:', err);
      inspector.innerHTML = `<div class="empty-inspector"><div class="empty-icon">⚠</div><strong>Could not render memory</strong><span>${this.escapeHtml(err.message)}</span></div>`;
    }
  },

  renderValueBlock(memory, valueStr) {
    let obj = null;
    if (typeof memory.value === 'object' && memory.value !== null) {
      obj = memory.value;
    } else if (typeof memory.value === 'string' && memory.value.trim().startsWith('{')) {
      try { obj = JSON.parse(memory.value); } catch (e) {}
    }

    const keyStr = String(memory.key || '');
    const isTyped = obj && (obj.schema_version === 'gms-context-record-v1' || obj.record_type || obj.decision || obj.rationale || obj.implications || keyStr.startsWith('mbrain.') || keyStr.startsWith('decisions.'));
    if (isTyped) {
      const recType = obj.record_type || (obj.decision ? 'decision' : 'record');
      const decText = obj.statement || obj.decision || obj.choice || obj.title || keyStr;
      const ratText = obj.rationale || obj.reason || obj.context || '';
      const rawImpl = obj.implications || obj.effects || obj.next_steps || [];
      const implList = Array.isArray(rawImpl) ? rawImpl : (rawImpl ? [rawImpl] : []);
      const scopeVal = obj.scope;
      const scopeText = typeof scopeVal === 'object' && scopeVal !== null
        ? (scopeVal.project || scopeVal.level || 'project')
        : String(scopeVal || memory.namespace || 'global');

      const prov = obj.provenance || {};
      const sourceRef = (prov.source_refs || [])[0] || '';

      return `
        <div class="decision-inspect-card" style="background:#131b26; border:1px solid rgba(56,189,248,0.2); border-radius:8px; padding:12px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span style="background:rgba(56,189,248,0.15); color:var(--accent-cyan); font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; letter-spacing:0.5px;">${this.escapeHtml(recType.toUpperCase())}</span>
            <span style="font-size:10px; color:var(--text-muted); background:rgba(255,255,255,0.06); padding:2px 6px; border-radius:4px;">${this.escapeHtml(scopeText)}</span>
          </div>
          <div style="font-size:13px; font-weight:600; color:var(--text-primary); margin-bottom:8px; line-height:1.4;">${this.escapeHtml(decText)}</div>
          ${ratText ? `
          <div style="margin-bottom:8px;">
            <div style="font-size:10px; text-transform:uppercase; color:var(--text-muted); font-weight:600; margin-bottom:3px;">Rationale</div>
            <div style="font-size:12px; color:#c5d2e3; line-height:1.4;">${this.escapeHtml(ratText)}</div>
          </div>` : ''}
          ${implList.length ? `
          <div style="margin-bottom:8px;">
            <div style="font-size:10px; text-transform:uppercase; color:var(--text-muted); font-weight:600; margin-bottom:3px;">Implications</div>
            <ul style="margin: 0 0 0 16px; padding: 0; font-size: 12px; color: #a0aec0; line-height: 1.4;">
              ${implList.map((imp) => `<li>${this.escapeHtml(imp)}</li>`).join('')}
            </ul>
          </div>` : ''}
          ${sourceRef ? `
          <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px;">
            Source: <strong style="color: #94a3b8;">${this.escapeHtml(sourceRef)}</strong>
          </div>` : ''}
          <details style="margin-top:10px; border-top:1px solid rgba(255,255,255,0.08); padding-top:8px;">
            <summary style="cursor:pointer; font-size:11px; color:var(--text-muted); outline:none;">View Raw JSON</summary>
            <pre class="memory-value" style="margin-top:6px; max-height:180px; overflow:auto;">${this.escapeHtml(valueStr)}</pre>
          </details>
        </div>
      `;
    }

    return `<pre class="memory-value">${this.escapeHtml(valueStr)}</pre>`;
  },

  setSearchQuery(q) {
    this.searchQuery = q || '';
    this.currentNamespace = '';
    this.cachedFacetCounts = null;
    this.cachedSourceCounts = null;
    this.selectedKey = '';
    this.loadMemories();
  },
  title(str) { return str.charAt(0).toUpperCase() + str.slice(1); },
  escapeHtml(str) { return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); },
};
