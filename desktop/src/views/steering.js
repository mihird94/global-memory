window.SteeringView = {
  async render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin-bottom: 4px;">Steer & Verify</h2>
        <p style="font-size: 13px; color: var(--text-secondary);">Review quarantined claims, resolve conflicts, and calibrate agent Bayesian trust reputations.</p>
      </div>

      <!-- Quarantine Review Inbox -->
      <div class="card">
        <div class="card-title">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span>🛡️ Quarantined Claims Inbox</span>
            <span class="badge" id="quarantine-count-badge" style="background: rgba(248, 81, 73, 0.2); color: var(--accent-red);">0 Pending</span>
          </div>
          <button class="btn-secondary" id="btn-refresh-quarantine" style="font-size: 12px; padding: 4px 8px;">Refresh</button>
        </div>
        <div id="quarantine-list-container" style="margin-top: 14px;">
          <div style="text-align: center; color: var(--text-muted); padding: 24px;">Checking quarantine status...</div>
        </div>
      </div>

      <!-- Agent Reputation & Trust Table -->
      <div class="card" style="margin-top: 24px; padding: 0; overflow: hidden;">
        <div style="padding: 16px 18px 12px 18px; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
          <h3 style="font-size: 15px; font-weight: 600;">Agent Bayesian Trust Reputations</h3>
          <span style="font-size: 12px; color: var(--text-muted);">Formula: Trust = α / (α + β)</span>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Agent ID</th>
              <th style="width: 90px;">Alpha (α)</th>
              <th style="width: 90px;">Beta (β)</th>
              <th style="width: 200px;">Trust Score</th>
              <th style="width: 140px;">Last Activity</th>
            </tr>
          </thead>
          <tbody id="reputations-list">
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 24px;">Loading reputation scores...</td></tr>
          </tbody>
        </table>
      </div>
    `;

    this.bindEvents(container);
    await Promise.all([this.loadQuarantine(), this.loadReputations()]);
  },

  bindEvents(container) {
    const refreshBtn = container.querySelector('#btn-refresh-quarantine');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        this.loadQuarantine();
        this.loadReputations();
      });
    }
  },

  async loadQuarantine() {
    const container = document.getElementById('quarantine-list-container');
    const badge = document.getElementById('quarantine-count-badge');
    if (!container) return;

    try {
      const items = await window.gms.getQuarantine();
      const count = items ? items.length : 0;
      if (badge) badge.innerText = `${count} Pending`;

      if (count === 0) {
        container.innerHTML = `
          <div style="text-align: center; color: var(--accent-green); padding: 30px; background: rgba(63, 185, 80, 0.05); border-radius: var(--radius-sm); border: 1px dashed rgba(63, 185, 80, 0.2);">
            <div style="font-size: 24px; margin-bottom: 6px;">✓</div>
            <div style="font-weight: 600; font-size: 14px;">Quarantine Inbox Clean</div>
            <div style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">No unverified or conflicting claims awaiting manual review.</div>
          </div>
        `;
        return;
      }

      container.innerHTML = items
        .map((item) => {
          const valStr = typeof item.value === 'object' ? JSON.stringify(item.value, null, 2) : String(item.value);
          return `
            <div style="background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 14px; margin-bottom: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                <div>
                  <span style="font-weight: 600; font-family: 'SF Mono', monospace; font-size: 13px; color: var(--accent-amber);">${item.fact_key}</span>
                  <span style="font-size: 11.5px; color: var(--text-muted); margin-left: 10px;">Agent: <strong>${item.agent_id}</strong> (${item.branch || 'main'})</span>
                </div>
                <div style="font-size: 11px; color: var(--text-muted);">${item.timestamp || ''}</div>
              </div>
              <pre style="background: var(--bg-primary); padding: 10px; border-radius: 4px; font-size: 12px; font-family: 'SF Mono', monospace; color: var(--text-secondary); overflow-x: auto; margin-bottom: 12px;">${this.escapeHtml(valStr)}</pre>
              <div style="display: flex; justify-content: flex-end; gap: 8px;">
                <button class="btn-danger btn-resolve-quarantine" data-key="${this.escapeHtml(item.fact_key)}" data-agent="${this.escapeHtml(item.agent_id)}" data-action="reject">
                  Reject & Penalize
                </button>
                <button class="btn-primary btn-resolve-quarantine" data-key="${this.escapeHtml(item.fact_key)}" data-agent="${this.escapeHtml(item.agent_id)}" data-action="accept">
                  Accept & Boost Trust
                </button>
              </div>
            </div>
          `;
        })
        .join('');

      // Bind resolve buttons
      container.querySelectorAll('.btn-resolve-quarantine').forEach((btn) => {
        btn.addEventListener('click', async (e) => {
          const key = e.target.dataset.key;
          const agent = e.target.dataset.agent;
          const action = e.target.dataset.action;

          try {
            e.target.disabled = true;
            await window.gms.resolveQuarantine({
              fact_key: key,
              agent_id: agent,
              action: action,
              reviewer: 'human-ui',
            });
            window.App.showToast(`Quarantine resolved: ${action.toUpperCase()} '${key}'`, 'success');
            this.loadQuarantine();
            this.loadReputations();
            window.App.refreshSnapshot();
          } catch (err) {
            window.App.showToast(`Failed to resolve: ${err.message}`, 'error');
            e.target.disabled = false;
          }
        });
      });
    } catch (err) {
      container.innerHTML = `<div style="color: var(--accent-red); padding: 20px;">Error loading quarantine: ${err.message}</div>`;
    }
  },

  async loadReputations() {
    const listEl = document.getElementById('reputations-list');
    if (!listEl) return;

    try {
      const snap = await window.gms.getSnapshot();
      const reputations = snap.agent_reputations || [];

      if (reputations.length === 0) {
        listEl.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 20px;">No agent reputations recorded yet.</td></tr>`;
        return;
      }

      listEl.innerHTML = reputations
        .map((rep) => {
          const pct = Math.round(rep.trust * 100);
          const barColor = pct >= 80 ? 'var(--accent-green)' : pct >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)';
          return `
            <tr>
              <td>
                <span style="font-weight: 600; font-size: 13px;">${rep.agent_id}</span>
              </td>
              <td style="font-family: 'SF Mono', monospace; color: var(--accent-green);">+${rep.alpha}</td>
              <td style="font-family: 'SF Mono', monospace; color: var(--accent-red);">${rep.beta}</td>
              <td>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <div style="flex: 1; height: 6px; background: var(--bg-surface); border-radius: 3px; overflow: hidden;">
                    <div style="width: ${pct}%; height: 100%; background: ${barColor};"></div>
                  </div>
                  <span style="font-size: 12px; font-weight: 600; font-family: 'SF Mono', monospace; width: 42px; text-align: right;">${pct}%</span>
                </div>
              </td>
              <td style="font-size: 12px; color: var(--text-muted);">${rep.last_updated || 'Active'}</td>
            </tr>
          `;
        })
        .join('');
    } catch (err) {
      listEl.innerHTML = `<tr><td colspan="5" style="color: var(--accent-red); padding: 20px;">Error loading reputations: ${err.message}</td></tr>`;
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
