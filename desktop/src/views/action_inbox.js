// desktop/src/views/action_inbox.js
// Mbrain Pass 8: Action Inbox View
// Consequence-ranked operational control plane, zero-mutation preview, and memory repair workflow.

window.ActionInboxView = {
  items: [],
  categories: {},
  totalItems: 0,
  selectedCategory: 'all',
  selectedProject: 'all',
  searchQuery: '',
  projectsList: [],
  activePreviewItem: null,
  previewData: null,
  repairData: null,
  repairEvidence: null,
  repairQuestions: [],
  repairKey: null,

  esc(value) {
    const d = document.createElement('div');
    d.textContent = String(value ?? '');
    return d.innerHTML;
  },

  async render(container) {
    container.innerHTML = `
      <div class="action-inbox-layout">
        <!-- Left Column: Consequence Categories Sidebar -->
        <aside class="inbox-sidebar card">
          <div class="inbox-sidebar-header">
            <div class="panel-label">ACTION INBOX</div>
            <h2 style="font-size: 16px; margin: 4px 0 2px; font-weight: 700;">Consequence Tiers</h2>
            <p class="muted" style="font-size: 11px; margin: 0 0 10px;">9 prioritized consequence classes</p>
          </div>
          <div class="inbox-category-list" id="inbox-category-list">
            <div class="loading-state">Loading categories...</div>
          </div>
        </aside>

        <!-- Center / Main Column: Items List & Filter Bar -->
        <main class="inbox-main-col card">
          <header class="inbox-main-header">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
              <div>
                <div class="eyebrow" style="color: var(--accent-cyan);">OPERATIONAL INBOX</div>
                <h1 style="font-size: 22px; font-weight: 700; margin: 4px 0;">Consequence-Ranked Action Inbox</h1>
                <p style="font-size: 12px; color: var(--text-secondary); margin: 0;">
                  Review pending decisions, collisions, broken handoffs, and repair needs. Zero durable writes occur without explicit review.
                </p>
              </div>
              <div style="display: flex; gap: 8px;">
                <button class="btn-secondary" id="btn-refresh-inbox" style="font-size: 12px; padding: 6px 12px;">↻ Refresh</button>
              </div>
            </div>

            <!-- Controls bar: Search, Project Filter, Category info -->
            <div class="inbox-controls-bar">
              <div class="search-box" style="flex: 1; min-width: 200px;">
                <input type="text" id="inbox-search-input" class="search-input" placeholder="Search inbox items by key, title, consequence..." value="${this.esc(this.searchQuery)}">
              </div>
              <div style="display: flex; align-items: center; gap: 6px;">
                <label for="inbox-project-filter" style="font-size: 11px; color: var(--text-muted);">Project:</label>
                <select id="inbox-project-filter" class="form-control" style="font-size: 11px; padding: 4px 8px; width: 140px;">
                  <option value="all">All Projects</option>
                </select>
              </div>
            </div>

            <!-- Zero-Mutation Guarantee Banner -->
            <div class="zero-mutation-banner">
              <span style="font-size: 14px;">🛡️</span>
              <div>
                <strong>Zero-Mutation Operational Invariant:</strong>
                <span>All actions generate deterministic previews first. Legacy facts and active claims remain completely untouched until explicit user confirmation.</span>
              </div>
            </div>
          </header>

          <!-- Items Deck -->
          <div class="inbox-items-deck" id="inbox-items-deck">
            <div class="loading-state">Loading action items...</div>
          </div>
        </main>
      </div>

      <!-- Modal: Zero-Mutation Action Preview -->
      <div class="modal-overlay" id="modal-inbox-preview" style="display: none;">
        <div class="modal-card inbox-preview-modal" style="max-width: 680px; width: 90vw;">
          <div class="modal-header">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 20px;">🔬</span>
              <div>
                <h3 style="margin: 0; font-size: 16px;">Zero-Mutation Action Preview</h3>
                <span class="muted" style="font-size: 11px;">Inspect deterministic consequence before executing</span>
              </div>
            </div>
            <button class="btn-close" id="btn-close-inbox-preview">×</button>
          </div>
          <div class="modal-body" id="inbox-preview-body" style="padding: 18px 24px; max-height: 70vh; overflow-y: auto;">
            <!-- Rendered dynamically -->
          </div>
        </div>
      </div>

      <!-- Modal: Memory Repair Wizard -->
      <div class="modal-overlay" id="modal-memory-repair" style="display: none;">
        <div class="modal-card memory-repair-modal" style="max-width: 780px; width: 92vw;">
          <div class="modal-header">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 20px;">🛠️</span>
              <div>
                <h3 style="margin: 0; font-size: 16px;">Source-Grounded Memory Repair</h3>
                <span class="muted" id="repair-modal-subtitle" style="font-size: 11px;">Repairing opaque record with provenance and honest field labels</span>
              </div>
            </div>
            <button class="btn-close" id="btn-close-memory-repair">×</button>
          </div>
          <div class="modal-body" id="memory-repair-body" style="padding: 18px 24px; max-height: 72vh; overflow-y: auto;">
            <!-- Rendered dynamically -->
          </div>
        </div>
      </div>
    `;

    this.bindEvents(container);
    await this.loadData(container);
  },

  bindEvents(container) {
    const refreshBtn = container.querySelector('#btn-refresh-inbox');
    if (refreshBtn) refreshBtn.onclick = () => this.loadData(container);

    const searchInput = container.querySelector('#inbox-search-input');
    if (searchInput) {
      searchInput.oninput = (e) => {
        this.searchQuery = e.target.value;
        this.renderItems(container);
      };
    }

    const projFilter = container.querySelector('#inbox-project-filter');
    if (projFilter) {
      projFilter.onchange = (e) => {
        this.selectedProject = e.target.value;
        this.renderItems(container);
      };
    }

    const closePreviewBtn = container.querySelector('#btn-close-inbox-preview');
    if (closePreviewBtn) {
      closePreviewBtn.onclick = () => {
        const modal = container.querySelector('#modal-inbox-preview');
        if (modal) modal.style.display = 'none';
      };
    }

    const closeRepairBtn = container.querySelector('#btn-close-memory-repair');
    if (closeRepairBtn) {
      closeRepairBtn.onclick = () => {
        const modal = container.querySelector('#modal-memory-repair');
        if (modal) modal.style.display = 'none';
      };
    }
  },

  async loadData(container) {
    try {
      const [inboxRes, projRes] = await Promise.all([
        window.gms.getActionInbox({ project: this.selectedProject === 'all' ? '' : this.selectedProject }),
        window.gms.getProjects ? window.gms.getProjects() : Promise.resolve({ projects: [] })
      ]);

      this.items = inboxRes.items || [];
      this.categories = inboxRes.categories || {};
      this.totalItems = inboxRes.total_items || this.items.length;
      this.projectsList = projRes.projects || [];

      // Update badge in sidebar if present
      const badgeInbox = document.getElementById('badge-inbox');
      if (badgeInbox) {
        badgeInbox.innerText = this.totalItems;
        badgeInbox.style.display = this.totalItems > 0 ? 'inline-block' : 'none';
      }

      this.populateProjectSelect(container);
      this.renderCategoriesSidebar(container);
      this.renderItems(container);
    } catch (err) {
      console.error('Failed to load Action Inbox:', err);
      const deck = container.querySelector('#inbox-items-deck');
      if (deck) deck.innerHTML = `<div class="empty-state" style="color: #f87171;">Failed to load Action Inbox: ${this.esc(err.message)}</div>`;
    }
  },

  populateProjectSelect(container) {
    const sel = container.querySelector('#inbox-project-filter');
    if (!sel) return;
    const current = this.selectedProject;
    sel.innerHTML = '<option value="all">All Projects</option>' +
      this.projectsList.map(p => `<option value="${this.esc(p.id)}" ${p.id === current ? 'selected' : ''}>${this.esc(p.name || p.id)}</option>`).join('');
  },

  renderCategoriesSidebar(container) {
    const list = container.querySelector('#inbox-category-list');
    if (!list) return;

    const catDefs = [
      { id: 'all', rank: null, label: 'All Action Items', icon: '📥' },
      { id: 'blocking_contradiction', rank: 1, label: 'Blocking Contradictions', icon: '🚨' },
      { id: 'human_decision_required', rank: 2, label: 'Required Human Decisions', icon: '⚖️' },
      { id: 'invalid_missing_evidence', rank: 3, label: 'Evidence Failures', icon: '🔍' },
      { id: 'stale_operational_fact', rank: 4, label: 'Stale Operational Truth', icon: '⌛' },
      { id: 'broken_task_handoff', rank: 5, label: 'Broken Handoffs / Leases', icon: '⛓️' },
      { id: 'proposed_decision', rank: 6, label: 'Proposed Decisions & Policies', icon: '📜' },
      { id: 'alias_collision', rank: 7, label: 'Canonical Key Collisions', icon: '⚡' },
      { id: 'opaque_status', rank: 8, label: 'Opaque Memory Repair', icon: '🛠️' },
      { id: 'candidate_review', rank: 9, label: 'Context Candidate Review', icon: '✨' },
    ];

    list.innerHTML = catDefs.map(cat => {
      const count = cat.id === 'all' ? this.totalItems : (this.categories[cat.id] || 0);
      const isActive = this.selectedCategory === cat.id;
      return `
        <div class="inbox-cat-item ${isActive ? 'active' : ''}" data-cat="${cat.id}">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span>${cat.icon}</span>
            <div style="display: flex; flex-direction: column;">
              <span style="font-size: 12px; font-weight: 500;">${this.esc(cat.label)}</span>
              ${cat.rank ? `<span class="muted" style="font-size: 10px;">Severity #${cat.rank}</span>` : ''}
            </div>
          </div>
          <span class="badge ${count > 0 ? (cat.rank && cat.rank <= 3 ? 'alert' : '') : 'muted'}" style="font-size: 11px;">
            ${count}
          </span>
        </div>
      `;
    }).join('');

    list.querySelectorAll('.inbox-cat-item').forEach(el => {
      el.onclick = () => {
        this.selectedCategory = el.dataset.cat;
        this.renderCategoriesSidebar(container);
        this.renderItems(container);
      };
    });
  },

  renderItems(container) {
    const deck = container.querySelector('#inbox-items-deck');
    if (!deck) return;

    let filtered = this.items.filter(item => {
      if (this.selectedCategory !== 'all' && item.category !== this.selectedCategory) return false;
      if (this.selectedProject !== 'all') {
        const itemProj = (item.affected_scope && item.affected_scope.project) || '';
        if (itemProj && itemProj !== 'global' && itemProj !== this.selectedProject) return false;
      }
      if (this.searchQuery.trim()) {
        const q = this.searchQuery.toLowerCase();
        const hay = `${item.title} ${item.description} ${item.consequence} ${item.inbox_id} ${item.target_id || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      deck.innerHTML = `
        <div class="empty-state" style="padding: 40px 20px; text-align: center;">
          <div style="font-size: 32px; margin-bottom: 8px;">✨</div>
          <strong style="font-size: 15px; color: var(--text-primary);">Inbox is clear</strong>
          <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            ${this.selectedCategory !== 'all' ? 'No items matching this category filter.' : 'No pending high-consequence contradictions, broken handoffs, or repair issues.'}
          </p>
        </div>
      `;
      return;
    }

    deck.innerHTML = filtered.map(item => this.renderItemCard(item)).join('');

    // Wire action buttons
    deck.querySelectorAll('.btn-preview-action').forEach(btn => {
      btn.onclick = () => {
        const inboxId = btn.dataset.inboxId;
        const action = btn.dataset.action || 'accept';
        this.openPreviewModal(container, inboxId, action);
      };
    });

    deck.querySelectorAll('.btn-open-repair').forEach(btn => {
      btn.onclick = () => {
        const key = btn.dataset.key;
        this.openRepairModal(container, key);
      };
    });
  },

  renderItemCard(item) {
    const isRepair = item.category === 'opaque_status';
    const isCollision = item.category === 'alias_collision' || item.category === 'blocking_contradiction';
    const isDecision = item.category === 'proposed_decision';

    let severityClass = 'low';
    if (item.severity <= 2) severityClass = 'high';
    else if (item.severity <= 5) severityClass = 'medium';

    return `
      <article class="inbox-card card" data-inbox-id="${this.esc(item.inbox_id)}">
        <div class="inbox-card-top">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span class="risk ${severityClass}" style="font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 999px;">
              #${item.severity} ${this.esc(item.category.replace(/_/g, ' ').toUpperCase())}
            </span>
            ${item.affected_scope?.project ? `<span class="badge" style="font-size: 10px;">${this.esc(item.affected_scope.project)}</span>` : ''}
            <span class="muted" style="font-size: 11px; font-family: monospace;">${this.esc(item.inbox_id)}</span>
          </div>
          <div style="display: flex; gap: 6px;">
            ${isRepair ? `
              <button class="btn-primary btn-open-repair" data-key="${this.esc(item.target_id)}" style="font-size: 11px; padding: 4px 10px;">
                🛠️ Repair Context
              </button>
            ` : `
              <button class="btn-secondary btn-preview-action" data-inbox-id="${this.esc(item.inbox_id)}" data-action="accept" style="font-size: 11px; padding: 4px 10px;">
                🔬 Preview Action
              </button>
            `}
          </div>
        </div>

        <div style="margin: 8px 0 6px;">
          <h3 style="font-size: 14px; font-weight: 600; margin: 0 0 4px; color: var(--text-primary);">
            ${this.esc(item.title)}
          </h3>
          <p style="font-size: 12px; color: var(--text-secondary); margin: 0;">
            ${this.esc(item.description)}
          </p>
        </div>

        <!-- Consequence Callout -->
        <div class="inbox-consequence-callout">
          <strong style="color: #fbbf24; font-size: 11px;">CONSEQUENCE:</strong>
          <span style="font-size: 11px; color: var(--text-muted);">${this.esc(item.consequence)}</span>
        </div>

        <!-- Evidence List -->
        ${item.evidence && item.evidence.length > 0 ? `
          <div style="margin-top: 8px; font-size: 11px;">
            <span class="muted">Evidence refs:</span>
            <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">
              ${item.evidence.map(ev => `
                <span class="evidence-chip" title="${this.esc(ev.detail || ev.value || '')}">
                  ${this.esc(ev.source || ev.ref || 'evidence')}
                </span>
              `).join('')}
            </div>
          </div>
        ` : ''}
      </article>
    `;
  },

  async openPreviewModal(container, inboxId, action) {
    const modal = container.querySelector('#modal-inbox-preview');
    const body = container.querySelector('#inbox-preview-body');
    if (!modal || !body) return;

    body.innerHTML = '<div class="loading-state">Generating deterministic zero-mutation preview…</div>';
    modal.style.display = 'flex';

    try {
      const prev = await window.gms.previewInboxAction({
        inbox_id: inboxId,
        action: action,
        project: this.selectedProject === 'all' ? '' : this.selectedProject,
        reviewer: 'mihir',
      });
      this.previewData = prev;

      body.innerHTML = `
        <div class="preview-report">
          <div style="background: rgba(56,189,248,0.08); border: 1px solid rgba(56,189,248,0.25); border-radius: 8px; padding: 12px; margin-bottom: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <strong style="color: var(--accent-cyan); font-size: 13px;">Deterministic Action Preview</strong>
              <span class="stat-badge" style="background: rgba(34,197,94,0.15); color: #4ade80; border: 1px solid rgba(34,197,94,0.3); font-size: 10px;">
                Durable writes: ${prev.durable_writes} (Zero Mutation)
              </span>
            </div>
            <p style="font-size: 12px; color: var(--text-secondary); margin: 6px 0 0;">
              ${this.esc(prev.consequence_summary || 'Review deterministic state change.')}
            </p>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; font-size: 11px;">
            <div><span class="muted">Target ID:</span> <code>${this.esc(prev.target_id)}</code></div>
            <div><span class="muted">Target Type:</span> <code>${this.esc(prev.target_type)}</code></div>
            <div><span class="muted">Action:</span> <code>${this.esc(prev.action)}</code></div>
            <div><span class="muted">Reviewer:</span> <code>${this.esc(prev.reviewer)}</code></div>
            <div style="grid-column: 1 / -1;"><span class="muted">Expected Content Hash:</span> <code>${this.esc(prev.expected_hash || 'none')}</code></div>
          </div>

          <div class="preview-warning" style="background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.25); border-radius: 8px; padding: 10px 14px; font-size: 11px; margin-bottom: 14px; color: #fbbf24;">
            ⚠️ Review the deterministic preview above before applying. This action will permanently modify memory state.
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 8px;">
            <button class="btn-secondary" id="btn-close-preview-inner">Close Preview</button>
            <button class="btn-primary" id="btn-apply-action" style="background: linear-gradient(135deg, #238636, #1f6feb);">Apply Action</button>
          </div>
        </div>
      `;

      body.querySelector('#btn-close-preview-inner').onclick = () => {
        modal.style.display = 'none';
      };
      body.querySelector('#btn-apply-action').onclick = async () => {
        if (!confirm('Are you sure you want to apply this action? This will permanently modify memory state.')) return;
        try {
          const applyBtn = body.querySelector('#btn-apply-action');
          applyBtn.disabled = true;
          applyBtn.innerText = 'Applying…';
          await window.gms.applyInboxAction({
            inbox_id: prev.inbox_id || item.inbox_id || item.id,
            action: prev.action,
            reviewer: prev.reviewer || 'mihir',
            expected_hash: prev.expected_hash || '',
          });
          modal.style.display = 'none';
          window.App.showToast('Action applied successfully.', 'success');
          window.App.refreshSnapshot();
          await this.loadInbox(container);
        } catch (applyErr) {
          if (window.App && window.App.showToast) {
            window.App.showToast(`Apply failed: ${applyErr.message}`, 'error');
          } else {
            console.error('Apply failed:', applyErr);
          }
          const applyBtn = body.querySelector('#btn-apply-action');
          if (applyBtn) { applyBtn.disabled = false; applyBtn.innerText = 'Apply Action'; }
        }
      };
    } catch (err) {
      body.innerHTML = `<div class="empty-state" style="color: #f87171;">Preview error: ${this.esc(err.message)}</div>`;
    }
  },

  async openRepairModal(container, key) {
    const modal = container.querySelector('#modal-memory-repair');
    const subtitle = container.querySelector('#repair-modal-subtitle');
    const body = container.querySelector('#memory-repair-body');
    if (!modal || !body) return;

    this.repairKey = key;
    if (subtitle) subtitle.innerText = `Analyzing source evidence for '${key}' without guessing`;
    body.innerHTML = '<div class="loading-state">Searching project banks, daily notes, and episodic history for source evidence…</div>';
    modal.style.display = 'flex';

    try {
      const [evRes, analysis] = await Promise.all([
        window.gms.getRepairEvidence(key),
        window.gms.analyzeRepairRecord(key),
      ]);

      this.repairEvidence = evRes.evidence || [];
      this.repairData = analysis;
      this.repairQuestions = analysis.questions_for_user || [];

      this.renderRepairWizard(container);
    } catch (err) {
      body.innerHTML = `<div class="empty-state" style="color: #f87171;">Repair analysis failed: ${this.esc(err.message)}</div>`;
    }
  },

  renderRepairWizard(container) {
    const body = container.querySelector('#memory-repair-body');
    if (!body) return;

    const analysis = this.repairData;
    const ev = this.repairEvidence;
    const fields = analysis.fields || {};

    body.innerHTML = `
      <div class="repair-wizard-content">
        <!-- 1. Source Evidence Strip -->
        <section style="margin-bottom: 16px;">
          <h4 style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); margin: 0 0 8px;">
            1. Discovered Source Evidence (${ev.length} references found)
          </h4>
          ${ev.length > 0 ? `
            <div style="max-height: 140px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px;">
              ${ev.map(item => `
                <div style="background: var(--bg-tertiary); border: 1px solid var(--border-subtle); border-radius: 6px; padding: 8px 10px; font-size: 11px;">
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <strong style="color: var(--accent-cyan);">${this.esc(item.ref)}</strong>
                    <span class="muted">${this.esc(item.source_type)}</span>
                  </div>
                  <div style="color: var(--text-secondary); font-style: italic;">"${this.esc(item.excerpt)}"</div>
                </div>
              `).join('')}
            </div>
          ` : `
            <div style="background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2); border-radius: 6px; padding: 8px 12px; font-size: 11px; color: #f87171;">
              Zero source references found in episodic history, project briefs, or claim ledger. Context must not be fabricated.
            </div>
          `}
        </section>

        <!-- 2. Honest Field Classification -->
        <section style="margin-bottom: 16px;">
          <h4 style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); margin: 0 0 8px;">
            2. Field-by-Field Context Reconstruction
          </h4>
          <div style="border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden;">
            ${Object.entries(fields).map(([fname, fmeta]) => {
              let badgeColor = '#94a3b8';
              let badgeBg = 'rgba(148,163,184,0.1)';
              if (fmeta.status === 'recovered_from_source') {
                badgeColor = '#4ade80';
                badgeBg = 'rgba(74,222,128,0.15)';
              } else if (fmeta.status === 'suggested_by_ai') {
                badgeColor = '#38bdf8';
                badgeBg = 'rgba(56,189,248,0.15)';
              } else if (fmeta.status === 'user_supplied') {
                badgeColor = '#a78bfa';
                badgeBg = 'rgba(167,139,250,0.15)';
              } else if (fmeta.status === 'still_unknown') {
                badgeColor = '#fbbf24';
                badgeBg = 'rgba(251,191,36,0.15)';
              }

              return `
                <div style="display: grid; grid-template-columns: 130px 150px 1fr; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); align-items: center; font-size: 11px;">
                  <strong style="color: var(--text-primary);">${this.esc(fname)}</strong>
                  <span>
                    <span style="background: ${badgeBg}; color: ${badgeColor}; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 600;">
                      ${this.esc(fmeta.status)}
                    </span>
                  </span>
                  <span style="color: var(--text-secondary); overflow-wrap: anywhere;">
                    ${fmeta.value ? this.esc(typeof fmeta.value === 'object' ? JSON.stringify(fmeta.value) : fmeta.value) : '<em class="muted">unknown</em>'}
                  </span>
                </div>
              `;
            }).join('')}
          </div>
        </section>

        <!-- 3. Targeted User Questions -->
        ${this.repairQuestions.length > 0 ? `
          <section style="margin-bottom: 16px;">
            <h4 style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); margin: 0 0 8px;">
              3. Questions for User (Clarifying missing context)
            </h4>
            <div style="display: flex; flex-direction: column; gap: 8px;">
              ${this.repairQuestions.map((q, idx) => `
                <div style="background: rgba(251,191,36,0.06); border: 1px solid rgba(251,191,36,0.2); border-radius: 6px; padding: 10px 12px; font-size: 12px;">
                  <div style="font-weight: 600; color: #fbbf24; margin-bottom: 4px;">❓ ${this.esc(q.question)}</div>
                  <input type="text" class="form-control repair-user-input" data-field="${this.esc(q.field)}" placeholder="Enter operational rationale..." style="font-size: 11px; margin-top: 6px; width: 100%;">
                </div>
              `).join('')}
            </div>
          </section>
        ` : ''}

        <!-- Actions -->
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 18px;">
          <span class="muted" style="font-size: 11px;">
            Staging creates a review candidate. Legacy fact remains readable.
          </span>
          <div style="display: flex; gap: 8px;">
            <button class="btn-secondary" id="btn-cancel-repair">Cancel</button>
            <button class="btn-primary" id="btn-stage-repair-candidate">Stage Review Candidate</button>
          </div>
        </div>
      </div>
    `;

    body.querySelector('#btn-cancel-repair').onclick = () => {
      container.querySelector('#modal-memory-repair').style.display = 'none';
    };

    body.querySelector('#btn-stage-repair-candidate').onclick = async () => {
      const inputs = body.querySelectorAll('.repair-user-input');
      const userSupplied = {};
      inputs.forEach(inp => {
        if (inp.value.trim()) {
          userSupplied[inp.dataset.field] = inp.value.trim();
        }
      });

      const payload = {
        key: this.repairKey,
        statement: fields.statement?.value || 'repaired',
        rationale: userSupplied.rationale || fields.rationale?.value || '',
        scope: fields.scope?.value || { project: 'global-memory' },
        source: fields.source?.value || (ev[0]?.ref || 'user_repaired'),
      };

      try {
        const res = await window.gms.stageRepairRecord({
          key: this.repairKey,
          payload: payload,
          apply: false, // Preview staging
          actor: 'mihir',
          rationale: userSupplied.rationale || 'User-guided memory repair',
        });

        if (window.App && window.App.showToast) {
          window.App.showToast(`Candidate staged: ${res.candidate_id || this.repairKey} (Legacy preserved)`, 'success');
        } else {
          alert(`Candidate staged: ${res.candidate_id || this.repairKey}\nLegacy preserved: ${res.legacy_preserved}`);
        }
        container.querySelector('#modal-memory-repair').style.display = 'none';
        this.loadData(container);
      } catch (err) {
        if (window.App && window.App.showToast) {
          window.App.showToast(`Failed to stage candidate: ${err.message}`, 'error');
        } else {
          console.error(`Failed to stage candidate: ${err.message}`);
        }
      }
    };
  }
};
