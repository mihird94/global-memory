window.RemindersView = {
  async render(container) {
    container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <div>
          <h2 style="font-size: 20px; font-weight: 700; margin-bottom: 4px;">Apple Reminders Integration</h2>
          <p style="font-size: 13px; color: var(--text-secondary);">Manage system reminders and convert actionable items directly into GMS memory claims.</p>
        </div>
        <button class="btn-secondary" id="btn-refresh-reminders">Refresh Reminders</button>
      </div>

      <!-- Quick Add Reminder Card -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title">
          <span>＋ Add Apple Reminder</span>
        </div>
        <form id="form-create-reminder" style="display: grid; grid-template-columns: 1fr 1fr auto; gap: 12px; align-items: flex-end;">
          <div class="form-group" style="margin-bottom: 0;">
            <label>Reminder Title</label>
            <input type="text" class="form-control" id="rem-title" placeholder="e.g. Audit GMS drift logs on Monday" required>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label>Notes / Context</label>
            <input type="text" class="form-control" id="rem-notes" placeholder="Optional context...">
          </div>
          <button type="submit" class="btn-primary" style="height: 34px;">Add to Reminders</button>
        </form>
      </div>

      <!-- Reminders List Card -->
      <div class="card" style="padding: 0; overflow: hidden;">
        <div style="padding: 14px 18px; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
          <h3 style="font-size: 14px; font-weight: 600;">Active Tasks & Incomplete Reminders</h3>
          <span class="badge badge-general" id="reminders-count-badge">Checking...</span>
        </div>
        <div id="reminders-list-container">
          <div style="text-align: center; color: var(--text-muted); padding: 30px;">Loading Reminders...</div>
        </div>
      </div>
    `;

    this.bindEvents(container);
    await this.loadReminders();
  },

  bindEvents(container) {
    const refreshBtn = container.querySelector('#btn-refresh-reminders');
    const form = container.querySelector('#form-create-reminder');

    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => this.loadReminders());
    }

    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const titleInput = document.getElementById('rem-title');
        const notesInput = document.getElementById('rem-notes');
        const title = titleInput.value.trim();
        const notes = notesInput.value.trim();

        if (!title) return;

        try {
          const res = await window.gms.createReminder({ title, notes });
          if (res.status === 'success') {
            window.App.showToast(`Reminder created: "${title}"`, 'success');
            titleInput.value = '';
            notesInput.value = '';
            this.loadReminders();
          } else {
            window.App.showToast(`Failed: ${res.message}`, 'error');
          }
        } catch (err) {
          window.App.showToast(`Error: ${err.message}`, 'error');
        }
      });
    }
  },

  async loadReminders() {
    const container = document.getElementById('reminders-list-container');
    const badge = document.getElementById('reminders-count-badge');
    if (!container) return;

    try {
      const res = await window.gms.getReminders();

      if (!res.supported) {
        if (badge) badge.innerText = 'Disabled';
        container.innerHTML = `
          <div style="padding: 30px; text-align: center; color: var(--text-muted);">
            <div style="font-size: 14px; font-weight: 600; margin-bottom: 4px;">macOS Only Feature</div>
            <div>Apple Reminders integration is only supported on macOS systems. On Mini PC / Linux, this module gracefully stays inactive.</div>
          </div>
        `;
        return;
      }

      const reminders = res.reminders || [];
      if (badge) badge.innerText = `${reminders.length} Incomplete`;

      if (reminders.length === 0) {
        container.innerHTML = `
          <div style="padding: 30px; text-align: center; color: var(--accent-green);">
            <div style="font-size: 20px; margin-bottom: 6px;">✓</div>
            <div style="font-size: 14px; font-weight: 600;">No incomplete reminders found in Apple Reminders</div>
          </div>
        `;
        return;
      }

      container.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Task / Title</th>
              <th style="width: 180px; text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody>
            ${reminders.map((r) => `
              <tr>
                <td>
                  <div style="font-weight: 600; font-size: 13px; color: var(--text-primary);">${this.escapeHtml(r.title)}</div>
                </td>
                <td style="text-align: right;">
                  <button class="btn-secondary btn-convert-memory" data-title="${this.escapeHtml(r.title)}" style="font-size: 11.5px; padding: 4px 8px;">
                    Convert to GMS Memory
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;

      // Bind convert buttons
      container.querySelectorAll('.btn-convert-memory').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const title = e.target.dataset.title;
          window.App.openAddMemoryModal({
            key: `task.${title.toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 30)}`,
            value: JSON.stringify({ task: title, source: 'apple_reminders', status: 'pending' }, null, 2),
            tier: 'procedural',
          });
        });
      });
    } catch (err) {
      container.innerHTML = `<div style="color: var(--accent-red); padding: 20px;">Error loading reminders: ${err.message}</div>`;
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
