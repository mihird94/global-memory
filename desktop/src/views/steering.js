window.SteeringView = {
  activeTab: 'overview',
  agentSort: 'recent',
  showUtilityAgents: false,
  quarantineItems: [],
  harvestCandidates: [],
  harvestStatus: null,
  harvestTypeFilter: '',
  harvestStatusFilter: 'all',
  reputations: [],
  fleetMetrics: { total_agents: 0, total_claims: 0, quarantine_pending: 0 },
  triageHistory: [],
  editingItem: null,
  selectedTriageIndex: 0,
  keyboardBound: false,

  async render(container) {
    container.innerHTML = `
      <div class="trust-page-header">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <div>
            <h2 style="font-size: 22px; font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 10px;">
              <span>Provenance & Activity</span>
              <span class="badge" id="triage-status-pill">Loading</span>
            </h2>
            <p style="font-size: 13px; color: var(--text-secondary);">See what changed, who produced it, what was disputed, and what needs a decision.</p>
          </div>
          <div style="display:flex;gap:8px"><button class="btn-secondary open-memory-quality" style="font-size:12px">Memory Quality</button><button class="btn-secondary" id="btn-refresh-triage" style="font-size: 12px; padding: 6px 12px; display: flex; align-items: center; gap: 6px;">
            <span>↻</span> Refresh
          </button></div>
        </div>
      </div>

      <div class="trust-summary-strip" id="fleet-kpi-banner">
        <div class="fleet-kpi-card">
          <span class="fleet-kpi-lbl">Needs review</span>
          <span class="fleet-kpi-val" id="kpi-quarantine-count">-</span>
          <span class="fleet-kpi-sub" id="kpi-quarantine-sub">Checking queue</span>
        </div>
        <div class="fleet-kpi-card">
          <span class="fleet-kpi-lbl">Tracked agents</span>
          <span class="fleet-kpi-val" id="kpi-total-agents">-</span>
          <span class="fleet-kpi-sub">Test and system identities hidden</span>
        </div>
        <div class="fleet-kpi-card">
          <span class="fleet-kpi-lbl">Durable claims</span>
          <span class="fleet-kpi-val" id="kpi-total-claims">-</span>
          <span class="fleet-kpi-sub">Currently active in memory</span>
        </div>
        <div class="fleet-kpi-card">
          <span class="fleet-kpi-lbl">Latest activity</span>
          <span class="fleet-kpi-val compact" id="kpi-latest-activity">-</span>
          <span class="fleet-kpi-sub">Most recent agent contribution</span>
        </div>
      </div>

      <section class="trust-section" id="tab-content-harvest">
        <div class="trust-section-heading">
          <div>
            <h3 style="display: flex; align-items: center; gap: 8px;">
              <span>Harvest Review</span>
              <span class="badge" id="harvest-pending-pill" style="font-size: 11px; background: rgba(56,189,248,0.15); color: var(--accent-cyan);">0 pending</span>
            </h3>
            <p>The system admits source-backed context automatically. Inspect its rationale and contest any decision to restore prior truth.</p>
          </div>
          <div class="trust-controls" style="display: flex; gap: 8px;">
            <select id="harvest-type-filter" class="trust-select" aria-label="Filter by record type">
              <option value="">All record types</option>
              <option value="decision">Decisions</option>
              <option value="policy">Policies</option>
              <option value="project_state">Project state</option>
              <option value="fact">Facts</option>
              <option value="observation">Observations</option>
            </select>
            <select id="harvest-status-filter" class="trust-select" aria-label="Filter by review status">
              <option value="all">All decisions</option>
              <option value="proposed">Pending system decision</option>
              <option value="deferred">Deferred</option>
              <option value="accepted">Accepted</option>
              <option value="rejected">Rejected</option>
              <option value="contested">Contested by owner</option>
            </select>
            <select id="harvest-reviewer-select" class="trust-select" aria-label="Reviewer identity" title="Active reviewer identity">
              <option value="mihir">Reviewer: Mihir</option>
            </select>
          </div>
        </div>

        <div class="harvest-summary-bar" id="harvest-summary-bar" style="display: flex; align-items: center; justify-content: space-between; background: #131b26; border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 16px; margin-bottom: 14px; font-size: 12px;">
          <div style="display: flex; gap: 16px; align-items: center; flex-wrap: wrap;">
            <span>Decisions/Policies: <strong id="harvest-cnt-decisions" style="color: var(--accent-cyan);">-</strong></span>
            <span>Project State: <strong id="harvest-cnt-state" style="color: #a78bfa;">-</strong></span>
            <span>Merge Suggestions: <strong id="harvest-cnt-merges" style="color: #fbbf24;">-</strong></span>
            <span>Validation Failures: <strong id="harvest-cnt-failures" style="color: #f87171;">-</strong></span>
            <span>Deferred: <strong id="harvest-cnt-deferred" style="color: var(--text-muted);">-</strong></span>
          </div>
          <div style="font-size: 11px; color: var(--text-muted);" id="harvest-run-info">
            Last run: - · Next run: 03:10 AM
          </div>
        </div>

        <div id="harvest-candidates-deck" class="harvest-deck">
          <div class="trust-loading">Loading harvest queue…</div>
        </div>
      </section>

      <section class="trust-section" id="tab-content-triage">
        <div class="trust-section-heading"><div><h3>Needs attention</h3><p>Only claims that require a decision appear here.</p></div></div>
        <div id="triage-deck-container" class="triage-deck">
          <div class="trust-loading">Checking review queue…</div>
        </div>
      </section>

      <section class="trust-section" id="tab-content-fleet">
        <div class="trust-section-heading">
          <div>
            <h3>Agent activity</h3>
            <p>An attribution ledger of contributions, disputes, and review outcomes.</p>
          </div>
          <div class="trust-controls">
            <select id="agent-sort" class="trust-select" aria-label="Sort agents">
              <option value="recent">Recently active</option>
              <option value="evidence">Most evidence</option>
              <option value="attention">Most disputed</option>
              <option value="name">Name</option>
            </select>
            <label class="trust-toggle"><input type="checkbox" id="show-utility-agents"> Show test/system agents</label>
          </div>
        </div>
        <div id="fleet-grid-container" class="agent-health-grid"></div>
      </section>

      <section class="trust-section" id="tab-content-audit">
        <div class="trust-section-heading">
          <div><h3>Recent decisions</h3><p>Human and system resolutions, newest first.</p></div>
        </div>
        <div id="audit-list-container">
          <div style="text-align: center; color: var(--text-muted); padding: 30px;">Loading audit trail...</div>
        </div>
      </section>

      <!-- Inline Edit Modal Container -->
      <div id="triage-edit-modal-host"></div>
    `;

    this.bindEvents(container);
    this.bindGlobalKeyboard();
    await this.refreshAll();
  },

  bindEvents(container) {
    const mq=container.querySelector('.open-memory-quality'); if(mq) mq.addEventListener('click',()=>window.App.openMemoryQuality());
    const refreshBtn = container.querySelector('#btn-refresh-triage');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => this.refreshAll());
    }

    container.querySelector('#agent-sort')?.addEventListener('change', (e) => {
      this.agentSort = e.target.value;
      this.renderFleetCards();
    });
    container.querySelector('#show-utility-agents')?.addEventListener('change', (e) => {
      this.showUtilityAgents = e.target.checked;
      this.renderFleetCards();
      this.updateSummary();
    });
    container.querySelector('#harvest-type-filter')?.addEventListener('change', (e) => {
      this.harvestTypeFilter = e.target.value;
      this.loadHarvestQueue();
    });
    container.querySelector('#harvest-status-filter')?.addEventListener('change', (e) => {
      this.harvestStatusFilter = e.target.value;
      this.loadHarvestQueue();
    });
  },

  bindGlobalKeyboard() {
    if (this.keyboardBound) return;
    this.keyboardBound = true;

    window.addEventListener('keydown', (e) => {
      if (window.App && window.App.activeView !== 'steering') return;

      const activeEl = document.activeElement;
      if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) return;
      if (document.querySelector('.triage-edit-modal-backdrop')) return;

      const key = e.key.toLowerCase();

      // Navigation: J/Down and K/Up
      if (['j', 'arrowdown'].includes(key) && this.quarantineItems.length > 0) {
        e.preventDefault();
        this.selectedTriageIndex = Math.min(this.selectedTriageIndex + 1, this.quarantineItems.length - 1);
        this.updateTriageFocusVisuals(true);
        return;
      }
      if (['k', 'arrowup'].includes(key) && this.quarantineItems.length > 0) {
        e.preventDefault();
        this.selectedTriageIndex = Math.max(this.selectedTriageIndex - 1, 0);
        this.updateTriageFocusVisuals(true);
        return;
      }

      // Actions: A (Approve), R (Reject), E (Edit) operating on currently focused card
      if (['a', 'r', 'e'].includes(key) && this.quarantineItems.length > 0) {
        const activeIndex = (this.selectedTriageIndex >= 0 && this.selectedTriageIndex < this.quarantineItems.length)
          ? this.selectedTriageIndex
          : 0;
        const targetItem = this.quarantineItems[activeIndex];
        if (!targetItem) return;

        e.preventDefault();
        if (key === 'a') {
          this.executeResolve(targetItem.fact_key, targetItem.agent_id, 'accept');
        } else if (key === 'r') {
          this.executeResolve(targetItem.fact_key, targetItem.agent_id, 'reject');
        } else if (key === 'e') {
          this.openEditModal(targetItem);
        }
      }
    });
  },

  updateTriageFocusVisuals(shouldScroll = false) {
    const cards = document.querySelectorAll('.triage-card');
    cards.forEach((card) => {
      const idx = Number(card.dataset.index);
      const isFocused = idx === this.selectedTriageIndex;
      card.classList.toggle('focused', isFocused);
      if (isFocused && shouldScroll) {
        card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });
  },

  async refreshAll() {
    await Promise.all([
      this.loadSnapshotAndFleet(),
      this.loadQuarantine(),
      this.loadHarvestQueue(),
      this.loadAuditHistory(),
    ]);
  },

  async loadSnapshotAndFleet() {
    try {
      const snap = await window.gms.getSnapshot();
      this.reputations = snap.agent_reputations || [];
      this.fleetMetrics = snap.fleet_metrics || {
        total_agents: this.reputations.length,
        total_claims: 0,
        quarantine_pending: 0,
      };

      const kpiClaims = document.getElementById('kpi-total-claims');
      if (kpiClaims) kpiClaims.innerText = this.fleetMetrics.total_claims;
      this.updateSummary();
      this.renderFleetCards();
    } catch (err) {
      console.error('Error loading snapshot & fleet:', err);
    }
  },

  async loadQuarantine() {
    const container = document.getElementById('triage-deck-container');
    const kpiQuar = document.getElementById('kpi-quarantine-count');
    const kpiQuarSub = document.getElementById('kpi-quarantine-sub');
    const statusPill = document.getElementById('triage-status-pill');

    try {
      const items = await window.gms.getQuarantine();
      this.quarantineItems = items || [];
      const count = this.quarantineItems.length;

      if (kpiQuar) {
        kpiQuar.innerText = count;
        kpiQuar.style.color = count > 0 ? 'var(--accent-amber)' : 'var(--accent-green)';
      }
      if (kpiQuarSub) {
        kpiQuarSub.innerText = count > 0 ? `${count} awaiting triage` : 'Queue clear';
      }
      if (statusPill) {
        if (count > 0) {
          statusPill.innerText = `${count} Conflicts Pending`;
          statusPill.style.background = 'rgba(248, 81, 73, 0.15)';
          statusPill.style.color = 'var(--accent-red)';
        } else {
          statusPill.innerText = 'No pending decisions';
          statusPill.style.background = 'rgba(63, 185, 80, 0.15)';
          statusPill.style.color = 'var(--accent-green)';
        }
      }

      if (!container) return;

      if (count === 0) {
        this.selectedTriageIndex = -1;
        container.innerHTML = `
          <div class="trust-clear-state">
            <span class="trust-clear-icon">✓</span>
            <div><strong>Nothing needs review</strong><span>New conflicts and low-confidence claims will appear here.</span></div>
          </div>
        `;
        return;
      }

      this.selectedTriageIndex = Math.min(Math.max(0, this.selectedTriageIndex), count - 1);

      container.innerHTML = this.quarantineItems
        .map((item, idx) => {
          const isFocused = idx === this.selectedTriageIndex;
          const currentValStr = item.current_value !== null && item.current_value !== undefined
            ? (typeof item.current_value === 'object' ? JSON.stringify(item.current_value, null, 2) : String(item.current_value))
            : null;
          const proposedValStr = typeof item.value === 'object' ? JSON.stringify(item.value, null, 2) : String(item.value);

          const badgeClass = item.conflict_type === 'overwrite_conflict'
            ? 'overwrite'
            : item.conflict_type === 'schema_drift'
            ? 'drift'
            : item.conflict_type === 'insufficient_history'
            ? 'context'
            : 'unverified';

          const priorContributions = Number(item.agent_stats?.claim_count || 0);

          return `
            <div class="triage-card ${isFocused ? 'focused' : ''}" data-index="${idx}" data-key="${this.escapeHtml(item.fact_key)}" data-agent="${this.escapeHtml(item.agent_id)}">
              <div class="triage-card-header">
                <div>
                  <div class="triage-card-title">
                    <span>${this.escapeHtml(item.fact_key)}</span>
                    <span class="triage-conflict-badge ${badgeClass}">
                      ${this.escapeHtml(item.conflict_badge || 'Quarantined')}
                    </span>
                    <span class="triage-focused-indicator" style="font-size: 10px; font-weight: 700; color: var(--accent-cyan); background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 4px; padding: 1px 6px; ${isFocused ? 'display: inline-block;' : 'display: none;'}">FOCUSED</span>
                  </div>
                  <div style="display: flex; align-items: center; gap: 8px; margin-top: 6px;">
                    <span class="triage-agent-pill">
                      <span>🤖</span>
                      <span>Agent: <strong>${this.escapeHtml(item.agent_id)}</strong></span>
                      <span>•</span>
                      <span>${priorContributions} recorded contributions</span>
                    </span>
                    <span style="font-size: 11px; color: var(--text-muted);">${item.timestamp || ''}</span>
                  </div>
                </div>
                <span class="badge" style="font-size: 11px; font-family: 'SF Mono', monospace; background: rgba(255,255,255,0.06);">#${idx + 1}</span>
              </div>

              <div class="triage-rationale-note" style="margin-bottom: 12px;">
                <span>⚠️</span>
                <span>${this.escapeHtml(item.conflict_reason || 'Pending verification')}</span>
              </div>

              <div class="triage-diff-container">
                <div class="triage-diff-pane current">
                  <div class="triage-diff-header current">
                    <span>Current Truth in Memory</span>
                    <span>${item.current_owner ? `By: ${this.escapeHtml(item.current_owner)}` : 'No prior fact'}</span>
                  </div>
                  <div class="triage-diff-code">${currentValStr !== null ? this.escapeHtml(currentValStr) : '<span style="color: var(--text-muted); font-style: italic;">No prior active fact in store (New assertion)</span>'}</div>
                </div>
                <div class="triage-diff-pane proposed">
                  <div class="triage-diff-header proposed">
                    <span>Proposed Mutation (Incoming)</span>
                    <span>By: ${this.escapeHtml(item.agent_id)}</span>
                  </div>
                  <div class="triage-diff-code">${this.escapeHtml(proposedValStr)}</div>
                </div>
              </div>

              <div class="triage-actions-bar">
                <div style="font-size: 11.5px; color: var(--text-muted);">
                  This decision is retained as provenance for future audits.
                </div>
                <div class="triage-buttons-group">
                  <button class="btn-danger btn-triage-act" data-action="reject" data-key="${this.escapeHtml(item.fact_key)}" data-agent="${this.escapeHtml(item.agent_id)}">
                    Reject & Dismiss <span class="key-shortcut-hint">R</span>
                  </button>
                  <button class="btn-secondary btn-triage-edit" data-key="${this.escapeHtml(item.fact_key)}" data-agent="${this.escapeHtml(item.agent_id)}">
                    Edit & Merge <span class="key-shortcut-hint">E</span>
                  </button>
                  <button class="btn-primary btn-triage-act" data-action="accept" data-key="${this.escapeHtml(item.fact_key)}" data-agent="${this.escapeHtml(item.agent_id)}">
                    Approve & Ledger <span class="key-shortcut-hint">A</span>
                  </button>
                </div>
              </div>
            </div>
          `;
        })
        .join('');

      container.querySelectorAll('.triage-card').forEach((card) => {
        card.addEventListener('click', (e) => {
          if (e.target.closest('button')) return;
          const idx = Number(card.dataset.index);
          if (!isNaN(idx)) {
            this.selectedTriageIndex = idx;
            this.updateTriageFocusVisuals(false);
          }
        });
      });

      container.querySelectorAll('.btn-triage-act').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const key = e.currentTarget.dataset.key;
          const agent = e.currentTarget.dataset.agent;
          const action = e.currentTarget.dataset.action;
          this.executeResolve(key, agent, action);
        });
      });

      container.querySelectorAll('.btn-triage-edit').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const key = e.currentTarget.dataset.key;
          const agent = e.currentTarget.dataset.agent;
          const item = this.quarantineItems.find((i) => i.fact_key === key && i.agent_id === agent);
          if (item) this.openEditModal(item);
        });
      });
    } catch (err) {
      container.innerHTML = `<div style="color: var(--accent-red); padding: 20px;">Error loading quarantine items: ${err.message}</div>`;
    }
  },

  async executeResolve(key, agent, action, editedValue = null) {
    try {
      const payload = {
        fact_key: key,
        agent_id: agent,
        action: action,
        reviewer: 'mihir',
      };
      if (editedValue !== null) {
        payload.edited_value = editedValue;
      }

      const res = await window.gms.resolveQuarantine(payload);
      if (res.status === 'error') {
        window.App.showToast(`Resolution failed: ${res.message}`, 'error');
        return;
      }

      const actionVerb = action === 'accept' ? 'APPROVED & LEDGERED' : 'REJECTED';
      window.App.showToast(`Quarantine ${actionVerb}: '${key}'`, 'success');

      await this.refreshAll();
      if (window.App && window.App.refreshSnapshot) {
        window.App.refreshSnapshot();
      }
    } catch (err) {
      window.App.showToast(`Action failed: ${err.message}`, 'error');
    }
  },

  openEditModal(item) {
    this.editingItem = item;
    const host = document.getElementById('triage-edit-modal-host');
    if (!host) return;

    const initialValStr = typeof item.value === 'object' ? JSON.stringify(item.value, null, 2) : String(item.value);

    host.innerHTML = `
      <div class="triage-edit-modal-backdrop" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 9999; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(4px);">
        <div style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: var(--radius-md); width: 600px; max-width: 90vw; padding: 22px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px;">
            <div>
              <h3 style="font-size: 16px; font-weight: 700;">Edit & Ledger Quarantined Fact</h3>
              <p style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">
                Key: <strong style="font-family: 'SF Mono', monospace; color: var(--accent-amber);">${this.escapeHtml(item.fact_key)}</strong> • Agent: <strong>${this.escapeHtml(item.agent_id)}</strong>
              </p>
            </div>
            <button id="btn-close-edit-modal" style="background: transparent; border: none; font-size: 18px; color: var(--text-muted); cursor: pointer;">✕</button>
          </div>

          <div style="margin-bottom: 12px;">
            <label style="font-size: 11.5px; font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 6px;">
              Payload (JSON / Literal):
            </label>
            <textarea id="triage-edit-textarea" style="width: 100%; height: 220px; background: #090d13; border: 1px solid var(--border-subtle); border-radius: 6px; padding: 10px; font-family: 'SF Mono', monospace; font-size: 12px; color: #c9d1d9; resize: vertical;">${this.escapeHtml(initialValStr)}</textarea>
          </div>

          <div id="triage-edit-validation-status" style="font-size: 12px; margin-bottom: 16px; padding: 8px 12px; border-radius: 4px; background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.2); color: var(--accent-cyan);">
            Checking contract constraints...
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 10px;">
            <button class="btn-secondary" id="btn-cancel-edit-modal">Cancel</button>
            <button class="btn-primary" id="btn-commit-edit-modal">Approve Edited Value</button>
          </div>
        </div>
      </div>
    `;

    const closeBtn = host.querySelector('#btn-close-edit-modal');
    const cancelBtn = host.querySelector('#btn-cancel-edit-modal');
    const commitBtn = host.querySelector('#btn-commit-edit-modal');
    const textarea = host.querySelector('#triage-edit-textarea');
    const statusBox = host.querySelector('#triage-edit-validation-status');

    const closeModal = () => {
      host.innerHTML = '';
      this.editingItem = null;
    };

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

    let valTimeout = null;
    const runValidation = async () => {
      let parsed = textarea.value.trim();
      try {
        if (parsed.startsWith('{') || parsed.startsWith('[')) {
          parsed = JSON.parse(parsed);
        }
      } catch (e) {
        statusBox.style.background = 'rgba(248, 81, 73, 0.1)';
        statusBox.style.borderColor = 'rgba(248, 81, 73, 0.3)';
        statusBox.style.color = 'var(--accent-red)';
        statusBox.innerText = `Invalid JSON syntax: ${e.message}`;
        return false;
      }

      try {
        const report = await window.gms.validateFact({ key: item.fact_key, value: parsed });
        if (report.valid) {
          statusBox.style.background = 'rgba(63, 185, 80, 0.1)';
          statusBox.style.borderColor = 'rgba(63, 185, 80, 0.3)';
          statusBox.style.color = 'var(--accent-green)';
          statusBox.innerText = `✓ Schema Valid: Conforms to namespace contract (${report.namespace || 'standard'})`;
          return true;
        } else {
          statusBox.style.background = 'rgba(248, 81, 73, 0.1)';
          statusBox.style.borderColor = 'rgba(248, 81, 73, 0.3)';
          statusBox.style.color = 'var(--accent-red)';
          statusBox.innerText = `✕ Contract Violation: ${report.error}`;
          return false;
        }
      } catch (err) {
        statusBox.innerText = `Validation query error: ${err.message}`;
        return false;
      }
    };

    textarea.addEventListener('input', () => {
      clearTimeout(valTimeout);
      valTimeout = setTimeout(runValidation, 300);
    });

    runValidation();

    commitBtn.addEventListener('click', async () => {
      let parsedVal = textarea.value.trim();
      try {
        if (parsedVal.startsWith('{') || parsedVal.startsWith('[')) {
          parsedVal = JSON.parse(parsedVal);
        }
      } catch (e) {
        window.App.showToast(`Invalid JSON: ${e.message}`, 'error');
        return;
      }

      commitBtn.disabled = true;
      commitBtn.innerText = 'Committing...';
      closeModal();
      await this.executeResolve(item.fact_key, item.agent_id, 'accept', parsedVal);
    });
  },

  renderFleetCards() {
    const grid = document.getElementById('fleet-grid-container');
    if (!grid) return;

    const visible = this.getVisibleReputations();
    if (visible.length === 0) {
      grid.innerHTML = `<div style="color: var(--text-muted); padding: 20px;">No agent reputations recorded.</div>`;
      return;
    }

    const getAgentIcon = (id) => {
      const lower = id.toLowerCase();
      if (lower.includes('human')) return '👑';
      if (lower.includes('codex')) return '⚡';
      if (lower.includes('antigravity')) return '🌐';
      if (lower.includes('dream')) return '🌙';
      if (lower.includes('alphaos')) return '📈';
      return '🤖';
    };

    grid.innerHTML = visible
      .map((rep) => {
        const observations = Number(rep.claim_count || 0) + Number(rep.proposed_count || 0) + Number(rep.accepted_count || 0) + Number(rep.rejected_count || 0);
        const icon = getAgentIcon(rep.agent_id);
        const activityLabel = observations >= 15 ? 'Frequent contributor' : observations >= 5 ? 'Regular contributor' : 'Sparse history';
        const activityClass = observations >= 15 ? 'strong' : observations >= 5 ? 'medium' : 'limited';
        const lastActive = this.relativeTime(rep.last_updated);

        return `
          <div class="agent-health-card">
            <div class="agent-card-header">
              <div class="agent-card-identity">
                <div class="agent-card-avatar">${icon}</div>
                <div>
                  <div class="agent-card-name">${this.escapeHtml(rep.agent_id)}</div>
                  <div class="agent-card-specialty">${this.escapeHtml(rep.specialty || 'General')} · ${lastActive}</div>
                </div>
              </div>
              <span class="evidence-strength ${activityClass}">${activityLabel}</span>
            </div>

            <div class="agent-trust-meter-row useful">
              <div class="agent-score"><span>${observations}</span><small>review observations</small></div>
              <span class="agent-dispute-summary">${rep.proposed_count || 0} awaiting review</span>
            </div>

            <div class="agent-card-metrics-row">
              <span><b>${rep.claim_count || 0}</b> active claims</span>
              <span><b>${rep.accepted_count || 0}</b> accepted candidates</span>
              <span><b>${rep.rejected_count || 0}</b> rejected candidates</span>
            </div>
          </div>
        `;
      })
      .join('');
  },

  isUtilityAgent(agentId) {
    const id = String(agentId || '').toLowerCase();
    return id === 'unknown' || id === 'human-ui' || id === 'system_backfill' ||
      id.includes('test') || id.includes('mock') || id.includes('backfill');
  },

  getVisibleReputations() {
    const reps = this.reputations.filter((rep) => this.showUtilityAgents || !this.isUtilityAgent(rep.agent_id));
    return [...reps].sort((a, b) => {
      if (this.agentSort === 'name') return String(a.agent_id).localeCompare(String(b.agent_id));
      if (this.agentSort === 'evidence') return (Number(b.claim_count) + Number(b.accepted_count)) - (Number(a.claim_count) + Number(a.accepted_count));
      if (this.agentSort === 'attention') return Number(b.proposed_count) - Number(a.proposed_count) || this.timeValue(b.last_updated) - this.timeValue(a.last_updated);
      return this.timeValue(b.last_updated) - this.timeValue(a.last_updated);
    });
  },

  updateSummary() {
    const visible = this.getVisibleReputations();
    const agents = document.getElementById('kpi-total-agents');
    const latest = document.getElementById('kpi-latest-activity');
    if (agents) agents.innerText = visible.length;
    if (latest) {
      const newest = [...visible].sort((a, b) => this.timeValue(b.last_updated) - this.timeValue(a.last_updated))[0];
      latest.innerText = newest ? this.relativeTime(newest.last_updated) : '—';
    }
  },

  timeValue(value) {
    if (!value) return 0;
    const normalized = String(value).includes('T') ? String(value) : String(value).replace(' ', 'T');
    const parsed = new Date(normalized).getTime();
    return Number.isFinite(parsed) ? parsed : 0;
  },

  relativeTime(value) {
    const timestamp = this.timeValue(value);
    if (!timestamp) return 'No recent activity';
    const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return new Date(timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  },

  async loadAuditHistory() {
    const container = document.getElementById('audit-list-container');
    const tabBadge = document.getElementById('tab-badge-audit');
    if (!container) return;

    try {
      const history = await window.gms.getTriageHistory(25);
      this.triageHistory = history || [];

      if (tabBadge) {
        tabBadge.innerText = this.triageHistory.length;
      }

      if (this.triageHistory.length === 0) {
        container.innerHTML = `
          <div style="text-align: center; color: var(--text-muted); padding: 30px; background: var(--bg-surface); border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
            No past ledger resolutions or transition records found.
          </div>
        `;
        return;
      }

      container.innerHTML = this.triageHistory
        .map((item) => {
          const isPromoted = item.action === 'promoted' || item.action === 'active';
          const isDiscarded = item.action === 'discarded' || item.action === 'retracted';
          const badgeBg = isPromoted
            ? 'rgba(63, 185, 80, 0.15)'
            : isDiscarded
            ? 'rgba(248, 81, 73, 0.15)'
            : 'rgba(163, 113, 247, 0.15)';
          const badgeColor = isPromoted ? 'var(--accent-green)' : isDiscarded ? 'var(--accent-red)' : 'var(--accent-purple)';

          return `
            <div class="triage-history-item">
              <div class="triage-history-main">
                <span class="badge" style="background: ${badgeBg}; color: ${badgeColor}; font-size: 11px; font-weight: 700; text-transform: uppercase;">
                  ${this.escapeHtml(item.action || 'resolved')}
                </span>
                <div>
                  <div class="triage-history-key">${this.escapeHtml(item.fact_key || '')}</div>
                  <div class="triage-history-meta">
                    Agent: <strong>${this.escapeHtml(item.agent_id || '')}</strong> • Reviewer: ${this.escapeHtml(item.reviewer || 'system')} • Reason: ${this.escapeHtml(item.rationale || '')}
                  </div>
                </div>
              </div>
              <div style="font-size: 11px; color: var(--text-muted); font-family: 'SF Mono', monospace;">
                ${item.timestamp || ''}
              </div>
            </div>
          `;
        })
        .join('');
    } catch (err) {
      container.innerHTML = `<div style="color: var(--accent-red); padding: 20px;">Error loading audit history: ${err.message}</div>`;
    }
  },

  async loadHarvestQueue() {
    const deck = document.getElementById('harvest-candidates-deck');
    if (!deck) return;
    try {
      const [statusRes, candidatesRes, reviewersRes] = await Promise.all([
        window.gms.getHarvestStatus ? window.gms.getHarvestStatus() : null,
        window.gms.getHarvestCandidates ? window.gms.getHarvestCandidates({
          type: this.harvestTypeFilter || undefined,
          status: this.harvestStatusFilter || undefined,
          limit: 50
        }) : { candidates: [] },
        window.gms.getHarvestReviewers ? window.gms.getHarvestReviewers() : null,
      ]);

      if (reviewersRes && reviewersRes.reviewers) {
        this.registeredReviewers = reviewersRes.reviewers;
        const revSelect = document.getElementById('harvest-reviewer-select');
        if (revSelect) {
          const curVal = revSelect.value || 'mihir';
          revSelect.innerHTML = Object.entries(this.registeredReviewers).map(([k, v]) => `
            <option value="${this.escapeHtml(k)}" ${k === curVal ? 'selected' : ''}>
              Reviewer: ${this.escapeHtml(v.display_name || k)}
            </option>
          `).join('');
        }
      }

      if (statusRes) {
        this.harvestStatus = statusRes;
        const cntDec = document.getElementById('harvest-cnt-decisions');
        if (cntDec) cntDec.innerText = statusRes.decisions_policies_pending || 0;
        const cntState = document.getElementById('harvest-cnt-state');
        if (cntState) cntState.innerText = statusRes.project_state_pending || 0;
        const cntMerges = document.getElementById('harvest-cnt-merges');
        if (cntMerges) cntMerges.innerText = statusRes.merge_suggestions || 0;
        const cntFail = document.getElementById('harvest-cnt-failures');
        if (cntFail) cntFail.innerText = statusRes.validation_failures || 0;
        const cntDef = document.getElementById('harvest-cnt-deferred');
        if (cntDef) cntDef.innerText = statusRes.deferred_count || 0;

        const pill = document.getElementById('harvest-pending-pill');
        if (pill) {
          const total = statusRes.total_awaiting_review || 0;
          pill.innerText = `${total} pending`;
          pill.style.background = total > 0 ? 'rgba(56,189,248,0.2)' : 'rgba(255,255,255,0.06)';
        }

        const runInfo = document.getElementById('harvest-run-info');
        if (runInfo && statusRes.last_run) {
          const lr = statusRes.last_run;
          const ts = lr.timestamp ? this.formatTimeAgo(lr.timestamp) : 'never';
          runInfo.innerText = `Last run: ${ts} (${lr.provider || 'local'}) · Next: ${statusRes.next_scheduled_run || '03:10 AM'}`;
        }
      }

      this.harvestCandidates = candidatesRes?.candidates || [];
      this.renderHarvestDeck(statusRes?.next_scheduled_run);
    } catch (err) {
      console.error('Error loading harvest queue:', err);
      if (deck) deck.innerHTML = `<div class="harvest-empty-row" style="color: var(--text-muted); padding: 12px;">Could not load harvest queue: ${this.escapeHtml(err.message)}</div>`;
    }
  },

  renderHarvestDeck(nextRun) {
    const deck = document.getElementById('harvest-candidates-deck');
    if (!deck) return;

    if (!this.harvestCandidates.length) {
      deck.innerHTML = `
        <div class="harvest-empty-row" style="background: #111822; border: 1px solid var(--border-color); border-radius: 6px; padding: 12px 16px; font-size: 12px; color: var(--text-muted); display: flex; justify-content: space-between; align-items: center;">
          <span>No curation decisions in this view.</span>
          <span style="font-size: 11px;">Nightly Dream Cycle scheduled via launchd (${nextRun || '03:10 AM'})</span>
        </div>
      `;
      return;
    }

    deck.innerHTML = this.harvestCandidates.map((c) => {
      const payload = c.payload || {};
      const prov = payload.provenance || {};
      const sourceRef = (prov.source_refs || [])[0] || 'episodic history';
      const implications = payload.implications || [];
      const implList = Array.isArray(implications) ? implications : [implications];
      const diff = c.diff || {};

      return `
        <div class="harvest-card card" data-candidate-id="${this.escapeHtml(c.candidate_id)}" style="background: #131b26; border: 1px solid rgba(56,189,248,0.2); border-radius: 8px; padding: 14px; margin-bottom: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="badge" style="background: rgba(56,189,248,0.15); color: var(--accent-cyan); font-weight: 700; text-transform: uppercase; font-size: 10px; padding: 2px 6px; border-radius: 4px;">${this.escapeHtml(c.record_type)}</span>
              <code style="font-size: 12px; font-weight: 600; color: var(--text-primary);">${this.escapeHtml(c.canonical_key)}</code>
            </div>
            <div style="display: flex; gap: 6px; align-items: center; font-size: 11px; color: var(--text-muted);">
              <span>${this.escapeHtml(payload.scope?.project || 'global-memory')}</span>
              <span>·</span>
              <span>${this.formatTimeAgo(c.created_at)}</span>
            </div>
          </div>

          <div style="font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; line-height: 1.4;">
            ${this.escapeHtml(payload.statement || c.canonical_key)}
          </div>

          ${payload.rationale ? `
            <div style="margin-bottom: 8px; background: rgba(0,0,0,0.2); padding: 8px 10px; border-radius: 6px; border-left: 3px solid var(--accent-cyan);">
              <div style="font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--accent-cyan); margin-bottom: 2px;">Rationale</div>
              <div style="font-size: 12px; color: #c5d2e3; line-height: 1.4;">${this.escapeHtml(payload.rationale)}</div>
            </div>
          ` : ''}

          ${implList.length && implList[0] ? `
            <div style="margin-bottom: 8px;">
              <div style="font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--text-muted); margin-bottom: 4px;">Implications</div>
              <ul style="margin: 0 0 0 16px; padding: 0; font-size: 12px; color: #a0aec0;">
                ${implList.map((imp) => `<li>${this.escapeHtml(imp)}</li>`).join('')}
              </ul>
            </div>
          ` : ''}

          <div style="font-size: 11px; color: var(--text-muted); display: flex; gap: 12px; margin-bottom: 10px; flex-wrap: wrap;">
            <span>Provenance: <strong style="color: #94a3b8;">${this.escapeHtml(c.extractor_agent || 'DreamCycle')} (${this.escapeHtml(c.provider || 'local')})</strong></span>
            <span>Authority: <strong style="color: #94a3b8;">${this.escapeHtml(payload.authority || 'llm_inference')}</strong></span>
            <span>Source: <strong style="color: #94a3b8;">${this.escapeHtml(sourceRef)}</strong></span>
          </div>

          ${diff.has_existing ? `
            <div style="margin-bottom: 12px; background: rgba(251,191,36,0.06); border: 1px solid rgba(251,191,36,0.2); border-radius: 6px; padding: 8px 10px; font-size: 11px;">
              <span style="color: #fbbf24; font-weight: 600;">Existing record in memory (${this.escapeHtml(diff.suggested_action || 'update')}):</span>
              <div style="color: #cbd5e1; margin-top: 4px; font-family: monospace; white-space: pre-wrap; max-height: 80px; overflow: auto;">${this.escapeHtml(typeof diff.existing_record === 'object' ? JSON.stringify(diff.existing_record, null, 2) : String(diff.existing_record))}</div>
            </div>
          ` : ''}

          <div style="display: flex; gap: 8px; align-items: center; justify-content: flex-end; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 10px;">
            ${c.review_status === 'accepted' && c.reviewed_by === 'system' ? `
              <button class="btn-secondary btn-harvest-contest" data-id="${this.escapeHtml(c.candidate_id)}" style="font-size: 11px; padding: 4px 10px; color: #fbbf24;">Contest system decision</button>
            ` : c.review_status === 'proposed' ? `
            <button class="btn-secondary btn-harvest-act" data-action="defer" data-id="${this.escapeHtml(c.candidate_id)}" style="font-size: 11px; padding: 4px 10px;">Defer</button>
            <button class="btn-secondary btn-harvest-act" data-action="reject" data-id="${this.escapeHtml(c.candidate_id)}" style="font-size: 11px; padding: 4px 10px; color: #f87171;">Reject</button>
            <button class="btn-secondary btn-harvest-act" data-action="edit" data-id="${this.escapeHtml(c.candidate_id)}" style="font-size: 11px; padding: 4px 10px;">Edit & Accept</button>
            ${diff.has_existing ? `
              <button class="btn-secondary btn-harvest-act" data-action="merge" data-id="${this.escapeHtml(c.candidate_id)}" style="font-size: 11px; padding: 4px 10px; color: #fbbf24;">Merge</button>
            ` : ''}
            <button class="btn-primary btn-harvest-act" data-action="accept" data-id="${this.escapeHtml(c.candidate_id)}" style="font-size: 11px; padding: 4px 12px;">Accept</button>
            ` : `<span style="font-size:11px;color:var(--text-muted)">${this.escapeHtml(c.review_status || 'decided')} by ${this.escapeHtml(c.reviewed_by || 'system')}</span>`}
          </div>
        </div>
      `;
    }).join('');

    deck.querySelectorAll('.btn-harvest-act').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const action = e.currentTarget.dataset.action;
        const id = e.currentTarget.dataset.id;
        await this.handleHarvestAction(id, action);
      });
    });
    deck.querySelectorAll('.btn-harvest-contest').forEach((btn) => {
      btn.addEventListener('click', async (event) => {
        const candidateId = event.currentTarget.dataset.id;
        const rationale = await this.promptRationale({
          title: 'Contest System Decision',
          subtitle: 'Why is this system decision wrong? The prior value will be restored in canonical memory.',
          placeholder: 'Provide detailed context explaining why the decision should be contested...',
          minChars: 10,
          confirmText: 'Contest & Restore',
          confirmClass: 'btn-danger',
        });
        if (!rationale) return;

        try {
          const result = await window.gms.contestHarvestCandidate(candidateId, { rationale, apply: true });
          if (result && result.status === 'error') {
            window.App.showToast(result.error || 'Contest failed', 'error');
          } else {
            window.App.showToast('Decision successfully contested and prior value restored', 'success');
          }
        } catch (err) {
          window.App.showToast(`Contest failed: ${err.message}`, 'error');
        }
        await this.loadHarvestQueue();
      });
    });
  },

  promptRationale({
    title = 'Provide Decision Rationale',
    subtitle = 'Please describe the rationale for this action.',
    defaultValue = '',
    placeholder = 'Enter rationale here...',
    minChars = 10,
    confirmText = 'Submit',
    confirmClass = 'btn-primary',
  }) {
    return new Promise((resolve) => {
      const host = document.getElementById('triage-edit-modal-host');
      if (!host) {
        resolve(null);
        return;
      }

      const initialTrimmed = (defaultValue || '').trim();
      const initialValid = minChars === 0 || initialTrimmed.length >= minChars;

      host.innerHTML = `
        <div class="triage-edit-modal-backdrop rationale-modal-backdrop" style="position: fixed; inset: 0; background: rgba(0,0,0,0.75); z-index: 10000; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(4px);">
          <div class="modal-card" style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 10px; width: 560px; max-width: 90vw; padding: 22px; box-shadow: 0 16px 40px rgba(0,0,0,0.6);">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
              <div>
                <h3 style="margin: 0 0 4px 0; font-size: 16px; font-weight: 700; color: var(--text-primary);">${this.escapeHtml(title)}</h3>
                <p style="margin: 0; font-size: 12.5px; color: var(--text-secondary); line-height: 1.4;">${this.escapeHtml(subtitle)}</p>
              </div>
              <button id="btn-rationale-close" style="background: transparent; border: none; font-size: 18px; color: var(--text-muted); cursor: pointer; padding: 2px 6px;">✕</button>
            </div>

            <div style="margin-bottom: 14px;">
              <label style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); display: block; margin-bottom: 6px;">
                Rationale & Provenance Note (min ${minChars} chars)
              </label>
              <textarea id="modal-rationale-textarea" rows="4" style="width: 100%; box-sizing: border-box; background: #090d13; border: 1px solid var(--border-subtle); border-radius: 6px; padding: 10px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 13px; line-height: 1.5; color: var(--text-primary); resize: vertical;" placeholder="${this.escapeHtml(placeholder)}">${this.escapeHtml(defaultValue)}</textarea>
              <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                <span id="modal-rationale-counter" style="font-size: 11.5px; font-weight: 600; font-family: 'SF Mono', monospace; color: ${initialValid ? 'var(--accent-green)' : 'var(--accent-red)'};">
                  ${initialValid ? `✓ ${initialTrimmed.length} characters` : `${initialTrimmed.length} / ${minChars} characters minimum`}
                </span>
                <span style="font-size: 11px; color: var(--text-muted);">Press ⌘+Enter to submit • Esc to cancel</span>
              </div>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 10px;">
              <button class="btn-secondary" id="btn-rationale-cancel">Cancel</button>
              <button class="${confirmClass}" id="btn-rationale-submit" ${initialValid ? '' : 'disabled'} style="${initialValid ? '' : 'opacity: 0.5; cursor: not-allowed;'}">${this.escapeHtml(confirmText)}</button>
            </div>
          </div>
        </div>
      `;

      const textarea = host.querySelector('#modal-rationale-textarea');
      const counter = host.querySelector('#modal-rationale-counter');
      const submitBtn = host.querySelector('#btn-rationale-submit');
      const cancelBtn = host.querySelector('#btn-rationale-cancel');
      const closeBtn = host.querySelector('#btn-rationale-close');

      const cleanup = () => {
        host.innerHTML = '';
      };

      const doCancel = () => {
        cleanup();
        resolve(null);
      };

      const doSubmit = () => {
        const val = textarea.value.trim();
        if (minChars > 0 && val.length < minChars) return;
        cleanup();
        resolve(val);
      };

      textarea.addEventListener('input', () => {
        const val = textarea.value.trim();
        const len = val.length;
        if (minChars === 0 || len >= minChars) {
          counter.style.color = 'var(--accent-green)';
          counter.innerText = `✓ ${len} characters`;
          submitBtn.disabled = false;
          submitBtn.style.opacity = '1';
          submitBtn.style.cursor = 'pointer';
        } else {
          counter.style.color = 'var(--accent-red)';
          counter.innerText = `${len} / ${minChars} characters minimum`;
          submitBtn.disabled = true;
          submitBtn.style.opacity = '0.5';
          submitBtn.style.cursor = 'not-allowed';
        }
      });

      textarea.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
          e.preventDefault();
          doSubmit();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          doCancel();
        }
      });

      cancelBtn.addEventListener('click', doCancel);
      closeBtn.addEventListener('click', doCancel);
      submitBtn.addEventListener('click', doSubmit);

      setTimeout(() => {
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
      }, 50);
    });
  },

  async handleHarvestAction(candidateId, action) {
    const candidate = this.harvestCandidates.find((c) => c.candidate_id === candidateId);
    if (!candidate) return;

    if (action === 'edit') {
      this.openHarvestEditModal(candidate);
      return;
    }

    const revSelect = document.getElementById('harvest-reviewer-select');
    const reviewerId = revSelect ? revSelect.value : 'mihir';

    let rationale = '';
    if (action === 'reject') {
      rationale = await this.promptRationale({
        title: 'Reject Candidate Fact',
        subtitle: `Specify why "${candidate.canonical_key}" is being rejected from memory ledger.`,
        placeholder: 'Enter rejection rationale (>=10 characters)...',
        minChars: 10,
        confirmText: 'Reject Candidate',
        confirmClass: 'btn-danger',
      });
      if (!rationale) return;
    } else if (action === 'merge') {
      rationale = await this.promptRationale({
        title: 'Merge with Existing Record',
        subtitle: `Merge "${candidate.canonical_key}" with existing active claim.`,
        defaultValue: 'Merged with existing active claim',
        placeholder: 'Enter merge rationale (>=10 characters)...',
        minChars: 10,
        confirmText: 'Merge & Accept',
        confirmClass: 'btn-primary',
      });
      if (!rationale) return;
    } else if (action === 'defer') {
      rationale = await this.promptRationale({
        title: 'Defer Candidate Review',
        subtitle: `Defer review of "${candidate.canonical_key}" for future inspection.`,
        defaultValue: 'Deferred for future review',
        placeholder: 'Optional deferral note...',
        minChars: 0,
        confirmText: 'Defer Candidate',
        confirmClass: 'btn-secondary',
      });
      if (!rationale) return;
    } else if (action === 'accept') {
      rationale = await this.promptRationale({
        title: 'Accept Architectural Decision',
        subtitle: `Accept "${candidate.canonical_key}" into canonical memory ledger.`,
        defaultValue: 'Accepted architectural decision for production.',
        placeholder: 'Enter acceptance rationale (>=10 characters)...',
        minChars: 10,
        confirmText: 'Approve & Ledger',
        confirmClass: 'btn-primary',
      });
      if (!rationale) return;
    }

    try {
      const res = await window.gms.reviewHarvestCandidate(candidateId, {
        action: action,
        reviewer: reviewerId,
        rationale: rationale,
        expected_content_hash: candidate.content_hash,
      });
      if (res && res.error) {
        window.App.showToast('Review error: ' + res.error, 'error');
        return;
      }
      window.App.showToast(`Candidate ${action}ed successfully`, 'success');
      await this.loadHarvestQueue();
    } catch (err) {
      window.App.showToast('Error updating candidate: ' + err.message, 'error');
    }
  },

  openHarvestEditModal(candidate) {
    const host = document.getElementById('triage-edit-modal-host');
    if (!host) return;

    const payloadStr = JSON.stringify(candidate.payload || {}, null, 2);
    const revOptions = this.registeredReviewers ? Object.entries(this.registeredReviewers).map(([k, v]) => `
      <option value="${this.escapeHtml(k)}" ${k === 'mihir' ? 'selected' : ''}>
        ${this.escapeHtml(v.display_name || k)}
      </option>
    `).join('') : '<option value="mihir">Mihir (Local Operator)</option>';

    host.innerHTML = `
      <div class="triage-edit-modal-backdrop" style="position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 1000; display: flex; align-items: center; justify-content: center;">
        <div class="modal-card" style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: 10px; width: 640px; max-width: 90vw; padding: 20px;">
          <h3 style="margin: 0 0 8px 0; font-size: 16px;">Edit & Accept Context Candidate</h3>
          <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: 12px;">Edit candidate payload before acceptance into canonical memory.</p>
          <div style="display: flex; gap: 10px; margin-bottom: 10px;">
            <div style="flex: 2;">
              <label style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); display: block; margin-bottom: 4px;">Candidate Key</label>
              <input type="text" readonly value="${this.escapeHtml(candidate.canonical_key)}" style="width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 10px; font-size: 12px; color: var(--text-muted);">
            </div>
            <div style="flex: 1;">
              <label style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); display: block; margin-bottom: 4px;">Reviewer</label>
              <select id="harvest-modal-reviewer" style="width: 100%; box-sizing: border-box; background: #0e141c; border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 10px; font-size: 12px; color: var(--text-primary);">
                ${revOptions}
              </select>
            </div>
          </div>
          <label style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); display: block; margin-bottom: 4px;">Payload (JSON)</label>
          <textarea id="harvest-edit-json" style="width: 100%; box-sizing: border-box; height: 200px; background: #0e141c; border: 1px solid var(--border-color); border-radius: 6px; padding: 8px 10px; font-family: monospace; font-size: 11.5px; color: var(--text-primary); margin-bottom: 10px;">${this.escapeHtml(payloadStr)}</textarea>

          <label style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); display: block; margin-bottom: 4px;">Reviewer Rationale (>=10 characters required)</label>
          <textarea id="harvest-edit-rationale" rows="3" placeholder="Why were these edits made?" style="width: 100%; box-sizing: border-box; background: #090d13; border: 1px solid var(--border-subtle); border-radius: 6px; padding: 8px 10px; font-size: 12.5px; color: var(--text-primary); line-height: 1.4; resize: vertical;"></textarea>

          <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px; margin-bottom: 12px;">
            <span id="harvest-edit-char-counter" style="font-size: 11.5px; font-weight: 600; font-family: 'SF Mono', monospace; color: var(--accent-red);">
              0 / 10 characters required
            </span>
          </div>

          <div id="harvest-edit-error-box" style="display: none; padding: 8px 12px; margin-bottom: 12px; border-radius: 6px; font-size: 12px; background: rgba(248, 81, 73, 0.12); border: 1px solid rgba(248, 81, 73, 0.3); color: var(--accent-red);"></div>

          <div style="display: flex; justify-content: flex-end; gap: 8px;">
            <button class="btn-secondary" id="btn-harvest-edit-cancel">Cancel</button>
            <button class="btn-primary" id="btn-harvest-edit-save" disabled style="opacity: 0.5; cursor: not-allowed;">Save & Accept</button>
          </div>
        </div>
      </div>
    `;

    const rationaleInput = host.querySelector('#harvest-edit-rationale');
    const charCounter = host.querySelector('#harvest-edit-char-counter');
    const saveBtn = host.querySelector('#btn-harvest-edit-save');
    const errorBox = host.querySelector('#harvest-edit-error-box');

    const updateCounter = () => {
      const val = rationaleInput.value.trim();
      const len = val.length;
      if (len >= 10) {
        charCounter.style.color = 'var(--accent-green)';
        charCounter.innerText = `✓ ${len} characters`;
        saveBtn.disabled = false;
        saveBtn.style.opacity = '1';
        saveBtn.style.cursor = 'pointer';
      } else {
        charCounter.style.color = 'var(--accent-red)';
        charCounter.innerText = `${len} / 10 characters required`;
        saveBtn.disabled = true;
        saveBtn.style.opacity = '0.5';
        saveBtn.style.cursor = 'not-allowed';
      }
    };

    rationaleInput.addEventListener('input', () => {
      errorBox.style.display = 'none';
      updateCounter();
    });

    host.querySelector('#btn-harvest-edit-cancel').addEventListener('click', () => { host.innerHTML = ''; });
    saveBtn.addEventListener('click', async () => {
      const jsonText = host.querySelector('#harvest-edit-json').value;
      const rationale = rationaleInput.value.trim();
      const reviewer = host.querySelector('#harvest-modal-reviewer').value;

      if (rationale.length < 10) {
        errorBox.style.display = 'block';
        errorBox.innerText = 'Review rationale must be at least 10 non-whitespace characters.';
        return;
      }

      let editedObj;
      try {
        editedObj = JSON.parse(jsonText);
      } catch (err) {
        errorBox.style.display = 'block';
        errorBox.innerText = 'Invalid JSON in payload: ' + err.message;
        return;
      }

      try {
        saveBtn.disabled = true;
        saveBtn.innerText = 'Saving...';
        const res = await window.gms.reviewHarvestCandidate(candidate.candidate_id, {
          action: 'edit',
          reviewer: reviewer,
          rationale: rationale,
          edited_payload: editedObj,
          expected_content_hash: candidate.content_hash,
        });
        if (res && res.error) {
          saveBtn.disabled = false;
          saveBtn.innerText = 'Save & Accept';
          errorBox.style.display = 'block';
          errorBox.innerText = 'Review error: ' + res.error;
          return;
        }
        host.innerHTML = '';
        window.App.showToast('Candidate successfully edited and accepted into memory', 'success');
        await this.loadHarvestQueue();
      } catch (err) {
        saveBtn.disabled = false;
        saveBtn.innerText = 'Save & Accept';
        errorBox.style.display = 'block';
        errorBox.innerText = 'Error saving candidate: ' + err.message;
      }
    });
  },

  formatTimeAgo(dateStr) {
    if (!dateStr) return '';
    try {
      const now = new Date();
      const past = new Date(dateStr.replace(' ', 'T'));
      const diffMs = now - past;
      if (isNaN(diffMs)) return dateStr;
      const diffSec = Math.floor(diffMs / 1000);
      if (diffSec < 60) return 'just now';
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `${diffMin}m ago`;
      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return `${diffHr}h ago`;
      const diffDays = Math.floor(diffHr / 24);
      return `${diffDays}d ago`;
    } catch {
      return dateStr;
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
