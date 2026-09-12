/**
 * concepts_view.js — Mbrain Entity Intelligence & Review Catalog
 *
 * Implements Mbrain UX Pass 2 (Stage D):
 * - Catalog view with type filters and quality signals
 * - Entity Review Queue for possible duplicates, missing summaries, unclassified, and isolated entities
 * - Deep entity evidence loading via getEntityEvidence (supporting claims, provenance, relationship breakdown)
 * - Cross-view navigation to Graph View and Exploration
 * - Extraction Lab scratchpad with candidate removal
 */

window.ConceptsView = {
  rawConcepts: {},
  filterType: '',
  searchQuery: '',
  pendingEntityId: '',
  selectedEntity: null,
  activeTab: 'catalog', // 'catalog' or 'review'
  activeReviewCategory: 'duplicates',
  duplicatesList: [],

  async render(container) {
    container.innerHTML = `
      <div class="view-heading">
        <div>
          <div class="eyebrow">Entity Intelligence</div>
          <h2>Entities</h2>
          <p>Explore canonical entities, audit evidence chains, and resolve knowledge quality issues.</p>
        </div>
        <div style="display:flex; align-items:center; gap:10px;">
          <div class="segmented-control" id="entity-tab-toggle">
            <button class="segment ${this.activeTab === 'catalog' ? 'active' : ''}" data-tab="catalog">Catalog</button>
            <button class="segment ${this.activeTab === 'review' ? 'active' : ''}" data-tab="review">Review Queue</button>
          </div>
          <button class="btn-secondary" id="toggle-extraction-lab">Extraction Lab</button>
        </div>
      </div>

      <!-- Extraction Lab Scratchpad -->
      <div id="extraction-lab" class="card extraction-lab collapsed">
        <div>
          <strong>Extraction Lab</strong>
          <p>Preview candidate facts, entities, and relationship triples without saving to memory.</p>
        </div>
        <div class="extraction-input">
          <textarea id="scratchpad-input" class="form-control" placeholder="Paste a log, note, or conversation excerpt…"></textarea>
          <button class="btn-primary" id="btn-run-extraction">Analyze text</button>
        </div>
        <div id="scratchpad-results"></div>
      </div>

      <!-- Main Entity Layout -->
      <div class="entity-layout" id="entity-main-layout">
        <!-- Dynamic content: Catalog or Review Queue -->
        <section class="entity-catalog card" id="entity-catalog-section">
          <div id="concept-type-filters" class="entity-filters"></div>
          <div id="concepts-grid" class="entity-grid">
            <div class="loading-state">Loading entities…</div>
          </div>
        </section>

        <!-- Persistent Entity Evidence Inspector -->
        <aside id="entity-inspector" class="entity-inspector card">
          <div class="empty-inspector">
            <div class="empty-icon">◈</div>
            <strong>Select an entity</strong>
            <span>Explore its summary, evidence chains, supporting claims, and relationships.</span>
          </div>
        </aside>
      </div>
    `;

    this.bindEvents(container);
    await this.loadConcepts();
  },

  bindEvents(container) {
    container.querySelector('#toggle-extraction-lab').addEventListener('click', (e) => {
      const lab = container.querySelector('#extraction-lab');
      lab.classList.toggle('collapsed');
      e.currentTarget.classList.toggle('active', !lab.classList.contains('collapsed'));
    });

    container.querySelector('#btn-run-extraction').addEventListener('click', () => this.runScratchpadExtraction());

    // Catalog vs Review Queue tabs
    container.querySelectorAll('#entity-tab-toggle .segment').forEach((btn) => {
      btn.addEventListener('click', () => {
        container.querySelectorAll('#entity-tab-toggle .segment').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        this.activeTab = btn.dataset.tab;
        if (this.activeTab === 'catalog') {
          this.renderFilters();
          this.renderEntitiesGrid();
        } else {
          this.renderReviewQueue();
        }
      });
    });
  },

  async loadConcepts() {
    const grid = document.getElementById('concepts-grid');
    try {
      const res = await window.gms.getConcepts();
      this.rawConcepts = res.groups || {};
      this.renderFilters(res.total_entities || 0);
      this.renderEntitiesGrid();

      if (this.pendingEntityId) {
        const entity = this.allEntities().find((e) => String(e.id) === String(this.pendingEntityId));
        this.pendingEntityId = '';
        if (entity) this.selectEntity(entity);
      }
    } catch (err) {
      if (grid) grid.innerHTML = `<div class="error-state">Could not load entities<br><small>${this.escapeHtml(err.message)}</small></div>`;
    }
  },

  allEntities() {
    return Object.values(this.rawConcepts).flat();
  },

  renderFilters(total) {
    const el = document.getElementById('concept-type-filters');
    if (!el) return;
    const types = Object.keys(this.rawConcepts).sort();
    const totalCount = total || this.allEntities().length;

    el.innerHTML = `
      <button class="entity-filter ${!this.filterType ? 'active' : ''}" data-type="">
        All <b>${totalCount}</b>
      </button>
    ` + types.map((type) => `
      <button class="entity-filter ${this.filterType === type ? 'active' : ''}" data-type="${this.escapeHtml(type)}">
        ${this.escapeHtml(type)} <b>${this.rawConcepts[type].length}</b>
      </button>
    `).join('');

    el.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.filterType = btn.dataset.type;
        this.selectedEntity = null;
        this.renderFilters(totalCount);
        this.renderEntitiesGrid();
        this.clearInspector();
      });
    });
  },

  renderEntitiesGrid() {
    const grid = document.getElementById('concepts-grid');
    if (!grid) return;

    let entities = this.filterType ? (this.rawConcepts[this.filterType] || []) : this.allEntities();
    if (this.searchQuery) {
      const q = this.searchQuery.toLowerCase();
      entities = entities.filter((e) => e.name.toLowerCase().includes(q) || String(e.summary || '').toLowerCase().includes(q));
    }

    entities.sort((a, b) => (b.edge_count || 0) - (a.edge_count || 0) || a.name.localeCompare(b.name));

    if (!entities.length) {
      grid.innerHTML = '<div class="empty-list"><strong>No matching entities</strong><span>Try a different type or search.</span></div>';
      return;
    }

    grid.innerHTML = entities.map((e) => {
      const initial = e.name.charAt(0).toUpperCase();
      const normType = String(e.type || 'CONCEPT').toLowerCase();
      return `
        <button class="entity-card ${this.selectedEntity && this.selectedEntity.id === e.id ? 'selected' : ''}" data-id="${this.escapeHtml(e.id)}">
          <span class="entity-orb entity-${this.escapeHtml(normType)}">${this.escapeHtml(initial)}</span>
          <span class="entity-card-copy">
            <span>
              <strong>${this.escapeHtml(e.name)}</strong>
              <em>${this.escapeHtml(e.type)}</em>
            </span>
            <p>${this.escapeHtml(e.summary || 'No summary recorded')}</p>
            <small>${e.edge_count || 0} relationship${e.edge_count === 1 ? '' : 's'}</small>
          </span>
          <span class="row-chevron">›</span>
        </button>
      `;
    }).join('');

    grid.querySelectorAll('.entity-card').forEach((card) => {
      card.addEventListener('click', () => {
        const entity = entities.find((e) => String(e.id) === card.dataset.id);
        if (entity) this.selectEntity(entity);
      });
    });
  },

  async selectEntity(entity) {
    this.selectedEntity = entity;
    this.renderEntitiesGrid();

    const inspector = document.getElementById('entity-inspector');
    if (!inspector) return;

    const initial = entity.name.charAt(0).toUpperCase();
    const normType = String(entity.type || 'CONCEPT').toLowerCase();

    inspector.innerHTML = `
      <div class="entity-hero">
        <span class="entity-orb entity-${this.escapeHtml(normType)}">${this.escapeHtml(initial)}</span>
        <div>
          <div class="entity-kicker">${this.escapeHtml(entity.type)}</div>
          <h3>${this.escapeHtml(entity.name)}</h3>
        </div>
      </div>
      <p class="entity-summary">${this.escapeHtml(entity.summary || 'No summary recorded yet.')}</p>
      <div class="entity-metrics">
        <div><strong>${entity.edge_count || 0}</strong><span>relationships</span></div>
        <div><strong>${entity.summary ? 'Yes' : 'No'}</strong><span>summary</span></div>
      </div>
      <div style="font-size:11px; color:var(--text-muted); padding:10px 0;">Loading evidence chains…</div>
    `;

    try {
      const evidence = await window.gms.getEntityEvidence(entity.id);
      const claims = evidence.claims || [];
      const rels = evidence.relationships || [];

      inspector.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <div class="entity-hero" style="margin:0;">
            <span class="entity-orb entity-${this.escapeHtml(normType)}">${this.escapeHtml(initial)}</span>
            <div>
              <div class="entity-kicker">${this.escapeHtml(evidence.type || entity.type)}</div>
              <h3 style="margin:0;">${this.escapeHtml(evidence.name || entity.name)}</h3>
            </div>
          </div>
          <span class="badge ${evidence.quality_status === 'well_supported' ? 'quality-good' : 'quality-warn'}" style="background:#172232; font-size:10px;">
            ${this.escapeHtml(evidence.quality_status || 'Active')}
          </span>
        </div>

        <p class="entity-summary">${this.escapeHtml(evidence.summary || entity.summary || 'No summary recorded yet.')}</p>

        <div class="entity-metrics">
          <div><strong>${evidence.evidence_count || 0}</strong><span>supporting refs</span></div>
          <div><strong>${evidence.active_relationships_count || 0}</strong><span>active links</span></div>
        </div>

        <!-- Quality Breakdown -->
        <div class="entity-quality">
          <div class="panel-label">Knowledge Quality</div>
          <div>
            <span>Identity Status</span>
            <b class="quality-good">Canonical</b>
          </div>
          <div>
            <span>Summary</span>
            <b class="${evidence.summary ? 'quality-good' : 'quality-warn'}">${evidence.summary ? 'Recorded' : 'Missing'}</b>
          </div>
          <div>
            <span>Evidence</span>
            <b class="${evidence.evidence_count >= 2 ? 'quality-good' : 'quality-warn'}">${evidence.evidence_count >= 2 ? 'Strong' : 'Thin'}</b>
          </div>
          <div>
            <span>Connectivity</span>
            <b class="${evidence.active_relationships_count ? 'quality-good' : 'quality-warn'}">${evidence.active_relationships_count ? 'Connected' : 'Isolated'}</b>
          </div>
        </div>

        <!-- Supporting Claims -->
        <div class="panel-label" style="margin-top:16px;">Supporting Claims (${claims.length})</div>
        ${claims.length ? claims.slice(0, 3).map((c) => `
          <div class="evidence-claim-box">
            <header>
              <strong>${this.escapeHtml(c.key)}</strong>
              <span>${this.escapeHtml(c.agent || 'system')}</span>
            </header>
            <code>${this.escapeHtml(typeof c.value === 'object' ? JSON.stringify(c.value) : String(c.value))}</code>
          </div>
        `).join('') : '<span class="muted" style="font-size:11px;">No claims recorded for this key.</span>'}

        <!-- Connected Relationships -->
        <div class="panel-label" style="margin-top:16px;">Relationships (${rels.length})</div>
        <div class="connection-list">
          ${rels.length ? rels.slice(0, 8).map((r) => `
            <button data-id="${this.escapeHtml(r.other_entity.id)}">
              <span>${r.direction === 'outgoing' ? '→' : '←'} ${this.escapeHtml(r.predicate)}</span>
              <strong>${this.escapeHtml(r.other_entity.name)}</strong>
            </button>
          `).join('') : '<span class="muted" style="font-size:11px;">No connected relationships.</span>'}
        </div>

        <!-- Actions -->
        <div class="inspector-actions stacked" style="margin-top:18px;">
          <button class="btn-primary" id="entity-view-graph">View in Graph</button>
          <button class="btn-secondary" id="entity-related-memory">Find related memories</button>
        </div>
      `;

      inspector.querySelectorAll('.connection-list button').forEach((btn) => {
        btn.addEventListener('click', () => {
          const target = this.allEntities().find((e) => String(e.id) === btn.dataset.id);
          if (target) this.selectEntity(target);
        });
      });

      inspector.querySelector('#entity-view-graph')?.addEventListener('click', () => {
        window.App.openInGraph(entity.id, entity.name);
      });
      inspector.querySelector('#entity-related-memory')?.addEventListener('click', () => {
        window.App.exploreRelated(entity.name);
      });
    } catch (e) {}
  },

  clearInspector() {
    const el = document.getElementById('entity-inspector');
    if (el) {
      el.innerHTML = `
        <div class="empty-inspector">
          <div class="empty-icon">◈</div>
          <strong>Select an entity</strong>
          <span>Explore its summary, evidence chains, supporting claims, and relationships.</span>
        </div>
      `;
    }
  },

  async renderReviewQueue() {
    const section = document.getElementById('entity-catalog-section');
    if (!section) return;

    section.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; padding:11px; border-bottom:1px solid var(--border-subtle);">
        <div class="segmented-control" id="review-cat-toggle" style="font-size:10px;">
          <button class="segment ${this.activeReviewCategory === 'duplicates' ? 'active' : ''}" data-cat="duplicates">Possible Duplicates</button>
          <button class="segment ${this.activeReviewCategory === 'missing_summary' ? 'active' : ''}" data-cat="missing_summary">Missing Summaries</button>
          <button class="segment ${this.activeReviewCategory === 'isolated' ? 'active' : ''}" data-cat="isolated">Isolated Entities</button>
          <button class="segment ${this.activeReviewCategory === 'unclassified' ? 'active' : ''}" data-cat="unclassified">Unclassified</button>
        </div>
        <span class="muted" style="font-size:11px;" id="review-cat-count">Loading review items…</span>
      </div>
      <div id="review-items-container" style="overflow:auto; flex:1; padding:12px;"></div>
    `;

    section.querySelectorAll('#review-cat-toggle .segment').forEach((btn) => {
      btn.addEventListener('click', () => {
        section.querySelectorAll('#review-cat-toggle .segment').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        this.activeReviewCategory = btn.dataset.cat;
        this.loadReviewCategoryItems();
      });
    });

    await this.loadReviewCategoryItems();
  },

  async loadReviewCategoryItems() {
    const container = document.getElementById('review-items-container');
    const countLabel = document.getElementById('review-cat-count');
    if (!container) return;

    container.innerHTML = '<div class="loading-state">Analyzing knowledge graph…</div>';
    const cat = this.activeReviewCategory;

    if (cat === 'duplicates') {
      try {
        const dups = await window.gms.getEntityDuplicates();
        countLabel.textContent = `${dups.length} candidate pair${dups.length === 1 ? '' : 's'}`;
        if (!dups.length) {
          container.innerHTML = '<div class="empty-list"><strong>No duplicate candidates</strong><span>All entity names appear distinct.</span></div>';
          return;
        }

        container.innerHTML = dups.map((d) => `
          <div class="card" style="margin-bottom:10px; background:#121824; border:1px solid var(--border-subtle); padding:12px;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
              <span class="badge quality-warn" style="font-size:10px;">${this.escapeHtml(d.reason)}</span>
              <span style="font-size:11px; color:#687c96;">${Math.round(d.similarity * 100)}% match</span>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
              <div style="background:#0c1119; padding:8px; border-radius:6px; font-size:11.5px;">
                <strong>${this.escapeHtml(d.entity_a.name)}</strong>
                <div style="color:var(--text-muted); font-size:9.5px;">ID: ${d.entity_a.id} · ${d.entity_a.type}</div>
              </div>
              <div style="background:#0c1119; padding:8px; border-radius:6px; font-size:11.5px;">
                <strong>${this.escapeHtml(d.entity_b.name)}</strong>
                <div style="color:var(--text-muted); font-size:9.5px;">ID: ${d.entity_b.id} · ${d.entity_b.type}</div>
              </div>
            </div>
            <div style="display:flex; justify-content:flex-end; gap:8px;">
              <button class="btn-secondary btn-review-graph" data-id="${d.entity_a.id}" data-name="${this.escapeHtml(d.entity_a.name)}" style="font-size:11px; padding:4px 8px;">View in Graph</button>
              <button class="btn-primary btn-merge-entities" data-src-id="${d.entity_b.id}" data-tgt-id="${d.entity_a.id}" data-src-name="${this.escapeHtml(d.entity_b.name)}" data-tgt-name="${this.escapeHtml(d.entity_a.name)}" style="font-size:11px; padding:4px 8px;">Merge B into A</button>
            </div>
          </div>
        `).join('');

        container.querySelectorAll('.btn-review-graph').forEach((b) => {
          b.addEventListener('click', () => window.App.openInGraph(b.dataset.id, b.dataset.name));
        });

        container.querySelectorAll('.btn-merge-entities').forEach((b) => {
          b.addEventListener('click', async () => {
            const srcId = parseInt(b.dataset.srcId, 10);
            const tgtId = parseInt(b.dataset.tgtId, 10);
            const srcName = b.dataset.srcName;
            const tgtName = b.dataset.tgtName;
            if (confirm(`Are you sure you want to merge "${srcName}" into "${tgtName}"? All relationships will be preserved and reassigned.`)) {
              try {
                if (window.gms.mergeEntities) {
                  await window.gms.mergeEntities({ source_id: srcId, target_id: tgtId });
                  alert(`Successfully merged "${srcName}" into "${tgtName}".`);
                  this.renderReviewList(cat, countLabel, container);
                }
              } catch (err) {
                alert(`Merge failed: ${err.message}`);
              }
            }
          });
        });
      } catch (e) {
        container.innerHTML = `<div class="error-state">Failed to check duplicates: ${this.escapeHtml(e.message)}</div>`;
      }
    } else if (cat === 'missing_summary') {
      const items = this.allEntities().filter((e) => !e.summary);
      countLabel.textContent = `${items.length} entit${items.length === 1 ? 'y' : 'ies'}`;
      if (!items.length) {
        container.innerHTML = '<div class="empty-list"><strong>All entities summarized</strong><span>Every entity in the database has a description.</span></div>';
        return;
      }
      container.innerHTML = items.slice(0, 50).map((e) => `
        <div class="entity-card" style="margin-bottom:6px;">
          <span class="entity-orb entity-concept">${this.escapeHtml(e.name.charAt(0).toUpperCase())}</span>
          <span class="entity-card-copy">
            <span><strong>${this.escapeHtml(e.name)}</strong><em>${this.escapeHtml(e.type)}</em></span>
            <p style="color:#e6aa55;">Missing summary</p>
            <small>${e.edge_count || 0} relationships</small>
          </span>
          <button class="btn-secondary btn-jump-entity" data-id="${e.id}" style="font-size:10.5px; padding:3px 7px;">Inspect</button>
        </div>
      `).join('');

      container.querySelectorAll('.btn-jump-entity').forEach((b) => {
        b.addEventListener('click', () => {
          const ent = this.allEntities().find((x) => String(x.id) === b.dataset.id);
          if (ent) this.selectEntity(ent);
        });
      });
    } else if (cat === 'isolated') {
      const items = this.allEntities().filter((e) => (e.edge_count || 0) === 0);
      countLabel.textContent = `${items.length} isolated entit${items.length === 1 ? 'y' : 'ies'}`;
      if (!items.length) {
        container.innerHTML = '<div class="empty-list"><strong>Zero isolated entities</strong><span>Every entity is connected to at least one other concept.</span></div>';
        return;
      }
      container.innerHTML = items.slice(0, 50).map((e) => `
        <div class="entity-card" style="margin-bottom:6px;">
          <span class="entity-orb entity-concept">${this.escapeHtml(e.name.charAt(0).toUpperCase())}</span>
          <span class="entity-card-copy">
            <span><strong>${this.escapeHtml(e.name)}</strong><em>${this.escapeHtml(e.type)}</em></span>
            <p>${this.escapeHtml(e.summary || 'No summary recorded')}</p>
            <small style="color:#e6aa55;">0 relationships (Isolated)</small>
          </span>
          <button class="btn-secondary btn-jump-entity" data-id="${e.id}" style="font-size:10.5px; padding:3px 7px;">Inspect</button>
        </div>
      `).join('');

      container.querySelectorAll('.btn-jump-entity').forEach((b) => {
        b.addEventListener('click', () => {
          const ent = this.allEntities().find((x) => String(x.id) === b.dataset.id);
          if (ent) this.selectEntity(ent);
        });
      });
    } else if (cat === 'unclassified') {
      const items = this.allEntities().filter((e) => e.type === 'UNCLASSIFIED' || e.type === 'CONCEPT');
      countLabel.textContent = `${items.length} general entit${items.length === 1 ? 'y' : 'ies'}`;
      container.innerHTML = items.slice(0, 50).map((e) => `
        <div class="entity-card" style="margin-bottom:6px;">
          <span class="entity-orb entity-concept">${this.escapeHtml(e.name.charAt(0).toUpperCase())}</span>
          <span class="entity-card-copy">
            <span><strong>${this.escapeHtml(e.name)}</strong><em>${this.escapeHtml(e.type)}</em></span>
            <p>${this.escapeHtml(e.summary || 'No summary recorded')}</p>
            <small>${e.edge_count || 0} relationships</small>
          </span>
          <button class="btn-secondary btn-jump-entity" data-id="${e.id}" style="font-size:10.5px; padding:3px 7px;">Inspect</button>
        </div>
      `).join('');

      container.querySelectorAll('.btn-jump-entity').forEach((b) => {
        b.addEventListener('click', () => {
          const ent = this.allEntities().find((x) => String(x.id) === b.dataset.id);
          if (ent) this.selectEntity(ent);
        });
      });
    }
  },

  async runScratchpadExtraction() {
    const input = document.getElementById('scratchpad-input');
    const results = document.getElementById('scratchpad-results');
    if (!input.value.trim()) return;

    results.innerHTML = '<div class="loading-state">Analyzing structure…</div>';
    try {
      const res = await window.gms.extractText({ text: input.value.trim() });
      const facts = res.candidate_facts || [];
      const triples = res.extracted_triples || [];
      const entities = res.entity_candidates || [];

      results.innerHTML = `
        <div class="extraction-summary">
          <span><strong>${facts.length}</strong> candidate facts</span>
          <span><strong>${entities.length}</strong> entities</span>
          <span><strong>${triples.length}</strong> relationships</span>
        </div>

        ${entities.length ? `
          <div class="extraction-section">
            <div class="panel-label">Detected Entities</div>
            ${entities.map((e, idx) => `
              <div class="extraction-row" id="extracted-entity-${idx}">
                <b class="${e.status === 'existing' ? 'quality-good' : 'quality-warn'}">${e.status === 'existing' ? 'KNOWN' : 'NEW'}</b>
                <code>${this.escapeHtml(e.name)}</code>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <span>${this.escapeHtml(e.type)} · ${e.mentions || 1} mention${e.mentions === 1 ? '' : 's'}</span>
                  <button class="btn-close" style="font-size:14px;" onclick="document.getElementById('extracted-entity-${idx}').remove()">×</button>
                </div>
              </div>
            `).join('')}
          </div>
        ` : ''}

        ${facts.length ? `
          <div class="extraction-section">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <div class="panel-label" style="margin:0;">Candidate Facts</div>
              <button class="btn-primary" id="btn-ingest-facts" style="font-size:11px; padding:4px 10px;">Ingest Valid Facts</button>
            </div>
            ${facts.map((f, idx) => `
              <div class="extraction-row" id="extracted-fact-${idx}">
                <b class="${f.valid ? 'quality-good' : 'quality-warn'}">${f.valid ? 'VALID' : 'REVIEW'}</b>
                <code>${this.escapeHtml(f.key)}</code>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <span>${this.escapeHtml(JSON.stringify(f.value))}</span>
                  <button class="btn-close" style="font-size:14px;" onclick="document.getElementById('extracted-fact-${idx}').remove()">×</button>
                </div>
              </div>
            `).join('')}
          </div>
        ` : ''}

        ${triples.length ? `
          <div class="extraction-section">
            <div class="panel-label">Extracted Relationships</div>
            ${triples.map((t, idx) => `
              <div class="triple-row" id="extracted-triple-${idx}">
                <strong>${this.escapeHtml(t.subject)}</strong>
                <span>${this.escapeHtml(t.predicate)}</span>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <strong>${this.escapeHtml(t.object)}</strong>
                  <button class="btn-close" style="font-size:14px;" onclick="document.getElementById('extracted-triple-${idx}').remove()">×</button>
                </div>
              </div>
            `).join('')}
          </div>
        ` : ''}

        ${!facts.length && !triples.length ? '<div class="empty-list"><strong>No structured knowledge detected</strong><span>Explicit keys or relationship patterns produce higher accuracy.</span></div>' : ''}
      `;

      const ingestBtn = results.querySelector('#btn-ingest-facts');
      if (ingestBtn) {
        ingestBtn.addEventListener('click', async () => {
          const validFacts = facts.filter((f) => f.valid);
          if (!validFacts.length) {
            alert('No valid facts to ingest.');
            return;
          }
          let savedCount = 0;
          for (const f of validFacts) {
            try {
              await window.gms.saveFact({ key: f.key, value: f.value, agent: 'extraction-lab', kind: 'semantic' });
              savedCount++;
            } catch (err) {
              console.error('Failed to save fact:', f.key, err);
            }
          }
          alert(`Successfully ingested ${savedCount} fact(s) to GMS.`);
          ingestBtn.disabled = true;
          ingestBtn.innerText = 'Ingested ✓';
          if (window.App && window.App.refreshSnapshot) window.App.refreshSnapshot();
        });
      }
    } catch (err) {
      results.innerHTML = `<div class="error-state">Analysis failed: ${this.escapeHtml(err.message)}</div>`;
    }
  },

  escapeHtml(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },
};
