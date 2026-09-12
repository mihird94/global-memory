window.App = {
  activeView: 'projects_view',
  views: {
    exploration: window.ExplorationView,
    projects_view: window.ProjectsView,
    action_inbox: window.ActionInboxView,
    steering: window.SteeringView,
    daily_notes: window.DailyNotesView,
    graph_view: window.GraphView,
    concepts_view: window.ConceptsView,
    reminders_view: window.RemindersView,
    memory_quality: window.MemoryQualityView,
  },

  async init() {
    this.bindNavigation();
    this.bindGlobalSearch();
    this.bindKeyboardShortcuts();
    this.bindModals();
    if (window.SearchPalette) {
      window.SearchPalette.init();
    }
    await this.refreshSnapshot();
    this.switchView('projects_view');
  },

  bindNavigation() {
    document.querySelectorAll('.nav-item').forEach((item) => {
      item.addEventListener('click', () => {
        const viewName = item.dataset.view;
        this.switchView(viewName);
      });
    });
  },

  bindKeyboardShortcuts() {
    const viewMap = {
      '1': 'exploration',
      '2': 'projects_view',
      '3': 'action_inbox',
      '4': 'steering',
      '5': 'daily_notes',
      '6': 'graph_view',
      '7': 'concepts_view',
      '8': 'reminders_view',
      '9': 'memory_quality',
    };

    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

      if ((e.metaKey || e.ctrlKey) && viewMap[e.key]) {
        e.preventDefault();
        this.switchView(viewMap[e.key]);
      } else if ((e.metaKey || e.ctrlKey) && e.key === 'r') {
        e.preventDefault();
        this.refreshSnapshot();
        const container = document.getElementById('main-view');
        if (container && this.views[this.activeView]?.render) {
          this.views[this.activeView].render(container);
        }
      }
    });

    const dreamInd = document.getElementById('dream-cycle-indicator');
    if (dreamInd) {
      dreamInd.addEventListener('click', async () => {
        if (window.gms.getDreamCycleStatus) {
          const st = await window.gms.getDreamCycleStatus();
          const info = `Last Run: ${st.timestamp || 'Never'}\nStatus: ${st.status || 'idle'}\nProvider: ${st.provider || 'none'}\nFacts Promoted: ${st.facts_promoted || 0}\nDuration: ${st.duration_seconds || 0}s\n\nTrigger a new consolidation now?`;
          if (confirm(info)) {
            if (window.gms.triggerDreamCycle) {
              await window.gms.triggerDreamCycle();
              alert('Dream Cycle triggered in background. Changes will consolidate automatically.');
              this.refreshSnapshot();
            }
          }
        }
      });
    }
  },

  switchView(viewName, meta = {}) {
    if (!this.views[viewName]) return;

    this.activeView = viewName;
    if (window.AppState) {
      window.AppState.setView(viewName, meta);
    }
    document.querySelectorAll('.nav-item').forEach((item) => {
      item.classList.toggle('active', item.dataset.view === viewName);
    });

    const container = document.getElementById('main-view');
    if (container) {
      this.views[viewName].render(container);
    }
  },

  openInGraph(entityId = '', entityLabel = '') {
    if (window.AppState) {
      window.AppState.setSelectedEntity(entityId);
    }
    window.GraphView.pendingFocus = { id: entityId, label: entityLabel };
    this.switchView('graph_view', { entityId, entityLabel });
  },

  openEntity(entity) {
    if (!entity) return;
    if (window.AppState) {
      window.AppState.setSelectedEntity(entity.id);
    }
    window.ConceptsView.pendingEntityId = entity.id;
    this.switchView('concepts_view', { entityId: entity.id });
  },

  openProject(projectId) {
    if (!projectId) return;
    if (window.AppState) {
      window.AppState.setSelectedProjectId(projectId);
    }
    if (window.ProjectsView) {
      window.ProjectsView.selectedProjectId = projectId;
    }
    this.switchView('projects_view', { projectId });
  },

  openMemoryQuality() { this.switchView('memory_quality'); },

  exploreRelated(query) {
    const searchInput = document.getElementById('global-search');
    if (searchInput) searchInput.value = query || '';
    if (window.AppState) {
      window.AppState.setSelectedMemoryKey(query || '');
    }
    window.ExplorationView.searchQuery = query || '';
    this.switchView('exploration', { query });
  },

  async refreshSnapshot() {
    try {
      const snap = await window.gms.getSnapshot();

      const totalMemories = (snap.facts.semantic || 0) + (snap.facts.operational || 0) + (snap.facts.procedural || 0) + (snap.episodes.count || 0);
      document.getElementById('badge-total-memories').innerText = totalMemories;
      document.getElementById('badge-quarantine').innerText = snap.db.quarantined_facts || 0;
      document.getElementById('badge-relationships').innerText = snap.db.relationships || 0;
      document.getElementById('badge-entities').innerText = snap.db.entities || 0;

      const badgeProjects = document.getElementById('badge-projects');
      if (badgeProjects && window.gms.getProjects) {
        window.gms.getProjects().then((res) => {
          if (res && res.projects) {
            badgeProjects.innerText = res.projects.length;
          }
        }).catch(() => {});
      }

      const badgeInbox = document.getElementById('badge-inbox');
      if (badgeInbox && window.gms.getActionInbox) {
        window.gms.getActionInbox({}).then((res) => {
          if (res && typeof res.total_items === 'number') {
            badgeInbox.innerText = res.total_items;
            badgeInbox.style.display = res.total_items > 0 ? 'inline-block' : 'none';
          }
        }).catch(() => {});
      }

      if (window.gms.getDreamCycleStatus) {
        window.gms.getDreamCycleStatus().then((st) => {
          const el = document.getElementById('dream-cycle-status-text');
          if (el && st) {
            if (st.status === 'completed') {
              el.innerText = `Consolidated (${st.provider || 'auto'})`;
              el.parentElement.title = `Last Run: ${st.timestamp}\nProvider: ${st.provider}\nFacts: ${st.facts_promoted}\nDuration: ${st.duration_seconds}s\nClick to inspect or run now`;
            } else if (st.status === 'running') {
              el.innerText = `Consolidating...`;
            } else {
              el.innerText = `Dream Cycle: Idle`;
            }
          }
        }).catch(() => {});
      }

      const activeClaims = snap.db.claims_by_status ? (snap.db.claims_by_status.active || 0) : 0;
      document.getElementById('stat-active-claims').innerText = activeClaims;

      const dbSizeMb = (snap.db_size_bytes / (1024 * 1024)).toFixed(2);
      document.getElementById('stat-db-size').innerText = `${dbSizeMb} MB`;

      const memRootLabel = document.getElementById('memory-root-label');
      if (memRootLabel) memRootLabel.innerText = snap.memory_root;
    } catch (err) {
      console.error('Failed to refresh snapshot:', err);
    }
  },

  bindGlobalSearch() {
    const searchInput = document.getElementById('global-search');
    if (!searchInput) return;

    searchInput.addEventListener('click', (e) => {
      e.preventDefault();
      if (window.SearchPalette) {
        window.SearchPalette.open();
      }
    });

    searchInput.addEventListener('focus', (e) => {
      e.preventDefault();
      searchInput.blur();
      if (window.SearchPalette) {
        window.SearchPalette.open();
      }
    });
  },

  bindModals() {
    const addModal = document.getElementById('modal-add-memory');
    const editModal = document.getElementById('modal-edit-fact');
    const openAddBtn = document.getElementById('btn-open-add-modal');
    const closeAddBtn = document.getElementById('btn-close-add-modal');
    const closeEditBtn = document.getElementById('btn-close-edit-modal');
    const formAdd = document.getElementById('form-add-memory');
    const formEdit = document.getElementById('form-edit-fact');
    const validateAddBtn = document.getElementById('btn-validate-preview');
    const validateEditBtn = document.getElementById('btn-edit-validate');
    const deleteFactBtn = document.getElementById('btn-delete-fact');

    openAddBtn.addEventListener('click', () => {
      this.openAddMemoryModal();
    });

    closeAddBtn.addEventListener('click', () => addModal.classList.remove('active'));
    closeEditBtn.addEventListener('click', () => editModal.classList.remove('active'));

    // Validate preview on Add
    validateAddBtn.addEventListener('click', async () => {
      const key = document.getElementById('add-memory-key').value.trim();
      const val = document.getElementById('add-memory-val').value.trim();
      const feedback = document.getElementById('add-validation-feedback');

      if (!key) {
        feedback.innerHTML = '<span style="color: var(--accent-red);">Please provide a fact key.</span>';
        return;
      }

      try {
        const res = await window.gms.validateFact({ key, value: val });
        if (res.valid) {
          feedback.innerHTML = '<span style="color: var(--accent-green);">✓ Schema contract valid! Ready to save.</span>';
        } else {
          feedback.innerHTML = `<span style="color: var(--accent-red);">✕ Schema Violation: ${res.error}</span>`;
        }
      } catch (err) {
        feedback.innerHTML = `<span style="color: var(--accent-red);">Validation error: ${err.message}</span>`;
      }
    });

    // Submit Add
    formAdd.addEventListener('submit', async (e) => {
      e.preventDefault();
      const key = document.getElementById('add-memory-key').value.trim();
      const val = document.getElementById('add-memory-val').value.trim();
      const tier = document.getElementById('add-memory-tier').value;

      try {
        const res = await window.gms.saveFact({ key, value: val, kind: tier });
        if (res.status === 'error') {
          this.showToast(`Error: ${res.message}`, 'error');
        } else {
          this.showToast(`Saved memory '${key}'`, 'success');
          addModal.classList.remove('active');
          formAdd.reset();
          document.getElementById('add-validation-feedback').innerHTML = '';
          this.refreshSnapshot();
          if (this.activeView === 'exploration') window.ExplorationView.loadMemories();
        }
      } catch (err) {
        this.showToast(`Failed: ${err.message}`, 'error');
      }
    });

    // Validate on Edit
    validateEditBtn.addEventListener('click', async () => {
      const key = document.getElementById('edit-fact-key').value.trim();
      const val = document.getElementById('edit-fact-val').value.trim();
      const feedback = document.getElementById('edit-validation-feedback');

      try {
        const res = await window.gms.validateFact({ key, value: val });
        if (res.valid) {
          feedback.innerHTML = '<span style="color: var(--accent-green);">✓ Schema contract valid!</span>';
        } else {
          feedback.innerHTML = `<span style="color: var(--accent-red);">✕ Schema Violation: ${res.error}</span>`;
        }
      } catch (err) {
        feedback.innerHTML = `<span style="color: var(--accent-red);">${err.message}</span>`;
      }
    });

    // Submit Edit
    formEdit.addEventListener('submit', async (e) => {
      e.preventDefault();
      const key = document.getElementById('edit-fact-key').value.trim();
      const val = document.getElementById('edit-fact-val').value.trim();

      try {
        const res = await window.gms.saveFact({ key, value: val, agent: 'human-ui' });
        if (res.status === 'error') {
          this.showToast(`Error: ${res.message}`, 'error');
        } else {
          this.showToast(`Updated fact '${key}'`, 'success');
          editModal.classList.remove('active');
          this.refreshSnapshot();
          if (this.activeView === 'exploration') window.ExplorationView.loadMemories();
        }
      } catch (err) {
        this.showToast(`Failed: ${err.message}`, 'error');
      }
    });

    // Delete Fact
    deleteFactBtn.addEventListener('click', async () => {
      const key = document.getElementById('edit-fact-key').value.trim();
      if (!confirm(`Are you sure you want to delete / retract fact '${key}'?`)) return;

      try {
        await window.gms.deleteFact({ key, agent: 'human-ui' });
        this.showToast(`Deleted fact '${key}'`, 'warning');
        editModal.classList.remove('active');
        this.refreshSnapshot();
        if (this.activeView === 'exploration') window.ExplorationView.loadMemories();
      } catch (err) {
        this.showToast(`Error: ${err.message}`, 'error');
      }
    });
  },

  openAddMemoryModal(defaults = {}) {
    const modal = document.getElementById('modal-add-memory');
    if (!modal) return;
    if (defaults.key) document.getElementById('add-memory-key').value = defaults.key;
    if (defaults.value) document.getElementById('add-memory-val').value = defaults.value;
    if (defaults.tier) document.getElementById('add-memory-tier').value = defaults.tier;
    document.getElementById('add-validation-feedback').innerHTML = '';
    modal.classList.add('active');
  },

  openEditFactModal(memory) {
    const modal = document.getElementById('modal-edit-fact');
    if (!modal) return;
    document.getElementById('edit-fact-key').value = memory.key;
    const valStr = typeof memory.value === 'object' ? JSON.stringify(memory.value, null, 2) : String(memory.value);
    document.getElementById('edit-fact-val').value = valStr;
    document.getElementById('edit-validation-feedback').innerHTML = '';
    modal.classList.add('active');
  },

  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : type === 'warning' ? '⚠' : 'ℹ';
    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  },
};

window.addEventListener('DOMContentLoaded', () => {
  window.App.init();
});
