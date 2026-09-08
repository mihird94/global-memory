window.ExplorationView = {
  currentTier: 'all',
  currentNamespace: '',
  searchQuery: '',

  async render(container) {
    container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <div>
          <h2 style="font-size: 20px; font-weight: 700; margin-bottom: 4px;">Memory Exploration</h2>
          <p style="font-size: 13px; color: var(--text-secondary);">Browse, inspect, and filter across semantic, episodic, operational, and procedural memory stores.</p>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn-secondary filter-tier active" data-tier="all">All Tiers</button>
          <button class="btn-secondary filter-tier" data-tier="semantic">Semantic</button>
          <button class="btn-secondary filter-tier" data-tier="episodic">Episodic</button>
          <button class="btn-secondary filter-tier" data-tier="operational">Operational</button>
          <button class="btn-secondary filter-tier" data-tier="procedural">Procedural</button>
        </div>
      </div>

      <!-- Namespace Chips -->
      <div style="display: flex; gap: 8px; margin-bottom: 18px; flex-wrap: wrap;">
        <span style="font-size: 12px; color: var(--text-muted); align-self: center;">Namespace:</span>
        <button class="badge filter-ns active" data-ns="" style="cursor: pointer; border: 1px solid var(--border-color); background: var(--bg-surface); color: var(--text-primary);">All</button>
        <button class="badge badge-infra filter-ns" data-ns="infra" style="cursor: pointer; border: 1px solid transparent;">infra.*</button>
        <button class="badge badge-trading filter-ns" data-ns="trading" style="cursor: pointer; border: 1px solid transparent;">trading.*</button>
        <button class="badge badge-trading filter-ns" data-ns="alphaos" style="cursor: pointer; border: 1px solid transparent;">alphaos.*</button>
        <button class="badge badge-models filter-ns" data-ns="models" style="cursor: pointer; border: 1px solid transparent;">models.*</button>
        <button class="badge badge-policies filter-ns" data-ns="policies" style="cursor: pointer; border: 1px solid transparent;">policies.*</button>
      </div>

      <!-- Memory Table Card -->
      <div class="card" style="padding: 0; overflow: hidden;">
        <table class="data-table" id="memories-table">
          <thead>
            <tr>
              <th style="width: 250px;">Key / Identifier</th>
              <th style="width: 110px;">Tier</th>
              <th>Content / Value Preview</th>
              <th style="width: 100px; text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody id="memories-list">
            <tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 30px;">Loading memories...</td></tr>
          </tbody>
        </table>
      </div>
    `;

    this.bindEvents(container);
    await this.loadMemories();
  },

  bindEvents(container) {
    container.querySelectorAll('.filter-tier').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        container.querySelectorAll('.filter-tier').forEach((b) => b.classList.remove('active'));
        e.target.classList.add('active');
        this.currentTier = e.target.dataset.tier;
        this.loadMemories();
      });
    });

    container.querySelectorAll('.filter-ns').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        container.querySelectorAll('.filter-ns').forEach((b) => b.style.borderColor = 'transparent');
        e.target.style.borderColor = 'var(--accent-blue)';
        this.currentNamespace = e.target.dataset.ns;
        this.loadMemories();
      });
    });
  },

  async loadMemories() {
    const listEl = document.getElementById('memories-list');
    if (!listEl) return;

    try {
      const res = await window.gms.getMemories({
        tier: this.currentTier,
        namespace: this.currentNamespace,
        q: this.searchQuery,
        limit: 150,
      });

      if (!res.memories || res.memories.length === 0) {
        listEl.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 40px;">No memories found matching criteria.</td></tr>`;
        return;
      }

      listEl.innerHTML = res.memories
        .map((m) => {
          const valStr = typeof m.value === 'object' ? JSON.stringify(m.value) : String(m.value);
          const safeVal = valStr.length > 180 ? valStr.slice(0, 180) + '...' : valStr;
          const badgeClass = m.namespace ? `badge-${m.namespace}` : 'badge-general';

          return `
            <tr>
              <td>
                <div style="font-weight: 600; font-family: 'SF Mono', monospace; font-size: 12.5px; color: var(--accent-blue);">${m.key}</div>
                <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">${m.source}</div>
              </td>
              <td>
                <span class="badge ${badgeClass}">${m.namespace || m.tier}</span>
              </td>
              <td>
                <div style="font-size: 12.5px; font-family: 'SF Mono', monospace; color: var(--text-secondary); word-break: break-all;">
                  ${this.escapeHtml(safeVal)}
                </div>
              </td>
              <td style="text-align: right;">
                <button class="btn-secondary btn-edit-fact" data-key="${this.escapeHtml(m.key)}" style="padding: 4px 8px; font-size: 11.5px;">Edit</button>
              </td>
            </tr>
          `;
        })
        .join('');

      // Bind Edit buttons
      listEl.querySelectorAll('.btn-edit-fact').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const key = e.target.dataset.key;
          const memory = res.memories.find((m) => m.key === key);
          if (memory) {
            window.App.openEditFactModal(memory);
          }
        });
      });
    } catch (err) {
      listEl.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--accent-red); padding: 30px;">Error loading memories: ${err.message}</td></tr>`;
    }
  },

  setSearchQuery(q) {
    this.searchQuery = q;
    this.loadMemories();
  },

  escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};
