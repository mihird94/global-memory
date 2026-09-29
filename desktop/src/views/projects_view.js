window.ProjectsView = {
  selectedProjectId: null,
  projects: [],
  currentProject: null,
  activeTab: 'overview', // 'overview', 'decisions', 'work', 'activity', 'knowledge'
  searchQuery: '',
  sortBy: 'recent', // 'recent', 'name', 'attention'
  inspectorItem: null,
  masterColCollapsed: false,
  inspectorColCollapsed: false,

  asOfTimestamp: null,

  // Resume Modal State
  resumeModal: {
    isOpen: false,
    format: 'antigravity',
    bundle: null,
    loading: false
  },

  // Context Packet Modal state
  packetModal: {
    isOpen: false,
    profile: 'standard', // 'small', 'standard', 'deep'
    format: 'markdown',   // 'markdown', 'json'
    sections: {
      brief: true,
      focus: true,
      tasks: true,
      decisions: true,
      activity: true,
      knowledge: true
    },
    preview: null,
    loading: false
  },

  async render(container) {
    container.innerHTML = `
      <div class="projects-workspace-layout">
        <!-- Column 1: Projects Master List -->
        <aside class="projects-master-col card" id="projects-master-col">
          <div class="projects-master-header">
            <div class="projects-col-title-row">
              <div class="panel-label">Projects Workspace</div>
              <button class="btn-icon btn-collapse-col" id="btn-toggle-master-col" title="Collapse Sidebar">◀</button>
            </div>
            <div class="collapsed-rail-text">Projects</div>
            <button class="btn-secondary open-memory-quality" style="width:100%;margin:8px 0">Memory Quality</button>
            <div class="projects-search-bar">
              <input type="text" id="projects-search-input" class="search-input" placeholder="Filter projects..." value="${this.escapeHtml(this.searchQuery)}">
            </div>
            <div class="projects-sort-row">
              <label for="projects-sort-select">Sort:</label>
              <select id="projects-sort-select" class="sort-select">
                <option value="recent" ${this.sortBy === 'recent' ? 'selected' : ''}>Recent activity</option>
                <option value="name" ${this.sortBy === 'name' ? 'selected' : ''}>Name (A–Z)</option>
                <option value="attention" ${this.sortBy === 'attention' ? 'selected' : ''}>Attention needed</option>
                <option value="stale" ${this.sortBy === 'stale' ? 'selected' : ''}>Stale</option>
              </select>
            </div>
          </div>
          <div id="projects-list" class="projects-list-container">
            <div class="loading-state">Loading projects...</div>
          </div>
        </aside>

        <!-- Column 2: Project Detail & Context Workspace -->
        <section class="projects-detail-col card" id="projects-detail-container">
          <div class="empty-project-selection">
            <div class="empty-icon">📁</div>
            <strong>Select a project</strong>
            <span>Choose a project from the left or initialize one in ~/memories/projects/</span>
          </div>
        </section>

        <!-- Column 3: Inspector Drawer -->
        <aside class="projects-inspector-col card" id="projects-inspector">
          <div class="projects-col-title-row" style="margin-bottom: 8px;">
            <div class="panel-label">Project Inspector</div>
            <button class="btn-icon btn-collapse-col" id="btn-toggle-inspector-col" title="Collapse Inspector">▶</button>
          </div>
          <div class="collapsed-rail-text">Inspector</div>
          <div id="projects-inspector-body">
            <div class="empty-inspector">
              <div class="empty-icon">⌁</div>
              <strong>Project Inspector</strong>
              <span>Select any decision, task, handoff, or knowledge record to inspect provenance and actions.</span>
            </div>
          </div>
        </aside>
      </div>

      <!-- Context Packet Modal -->
      <div class="modal-overlay" id="modal-context-packet" style="display: none;">
        <div class="modal-card context-packet-modal">
          <div class="modal-header">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 20px;">📦</span>
              <div>
                <h3 style="margin: 0; font-size: 16px;">Context Packet Generator</h3>
                <span class="muted" id="packet-project-subtitle" style="font-size: 11px;">Generating deterministic handoff packet</span>
              </div>
            </div>
            <button class="btn-close" id="btn-close-packet-modal">×</button>
          </div>

          <div class="packet-modal-body">
            <!-- Profile Selector & Stats Strip -->
            <div class="packet-controls-strip">
              <div class="segmented-control" id="packet-profile-selector">
                <button class="segment" data-profile="small">Small (~2k tok)</button>
                <button class="segment active" data-profile="standard">Standard (~6k tok)</button>
                <button class="segment" data-profile="deep">Deep (~15k tok)</button>
              </div>
              <div class="packet-budget-stats" id="packet-budget-stats">
                <span class="stat-badge" id="packet-stat-chars">- chars</span>
                <span class="stat-badge" id="packet-stat-tokens">~- tokens</span>
                <span class="stat-badge hash" id="packet-stat-hash">sha256:...</span>
              </div>
            </div>

            <!-- Redaction & Sections Filter -->
            <div class="packet-options-bar">
              <div class="packet-section-toggles">
                <label><input type="checkbox" id="pkt-sec-brief" checked> Brief</label>
                <label><input type="checkbox" id="pkt-sec-focus" checked> Focus & Constraints</label>
                <label><input type="checkbox" id="pkt-sec-tasks" checked> Work & Handoffs</label>
                <label><input type="checkbox" id="pkt-sec-decisions" checked> Decisions</label>
                <label><input type="checkbox" id="pkt-sec-activity" checked> Activity</label>
                <label><input type="checkbox" id="pkt-sec-knowledge" checked> Knowledge</label>
              </div>
              <div class="packet-redaction-status" id="packet-redaction-status">
                <span class="shield-icon">🛡️</span> <span id="packet-redaction-text">Secrets masked</span>
              </div>
            </div>

            <!-- Content View Switcher & Preview Area -->
            <div class="packet-preview-header">
              <div class="tab-pills" id="packet-format-tabs">
                <button class="tab-pill active" data-format="markdown">Markdown Preview</button>
                <button class="tab-pill" data-format="json">Canonical JSON</button>
              </div>
            </div>

            <div class="packet-preview-container">
              <pre class="packet-preview-content" id="packet-preview-text">Generating packet...</pre>
            </div>
          </div>

          <div class="modal-footer packet-modal-footer">
            <div id="packet-export-feedback" style="font-size: 11px; color: var(--accent-green);"></div>
            <div style="display: flex; gap: 10px;">
              <button class="btn-secondary" id="btn-copy-packet">📋 Copy to Clipboard</button>
              <button class="btn-primary" id="btn-export-packet">💾 Export to File</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Resume with Context Modal -->
      <div class="modal-overlay" id="modal-resume-context" style="display: none;">
        <div class="modal-card context-packet-modal" style="max-width: 820px;">
          <div class="modal-header">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 20px;">🚀</span>
              <div>
                <h3 style="margin: 0; font-size: 16px;">Agent Resumption Bundle</h3>
                <span class="muted" id="resume-project-subtitle" style="font-size: 11px;">Generate agent prompt for immediate continuation without repo rereading</span>
              </div>
            </div>
            <button class="btn-close" id="btn-close-resume-modal">×</button>
          </div>

          <div class="packet-modal-body">
            <!-- Format selector & telemetry strip -->
            <div class="packet-controls-strip">
              <div class="segmented-control" id="resume-format-selector">
                <button class="segment active" data-fmt="antigravity">Antigravity</button>
                <button class="segment" data-fmt="codex">Codex</button>
                <button class="segment" data-fmt="gemini">Gemini CLI</button>
                <button class="segment" data-fmt="json">Canonical JSON</button>
              </div>
              <div class="packet-budget-stats">
                <span class="stat-badge hash" id="resume-stat-hash">sha256:...</span>
                <span class="stat-badge" style="background: rgba(210, 153, 34, 0.15); color: var(--accent-amber);">🔒 No Auto-Dispatch</span>
              </div>
            </div>

            <div class="packet-preview-container" style="margin-top: 12px; height: 380px;">
              <pre class="packet-preview-content" id="resume-preview-text" style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 1.45;">Generating resumption bundle...</pre>
            </div>
          </div>

          <div class="modal-footer packet-modal-footer">
            <div style="font-size: 11px; color: var(--text-muted);">Paste directly into your agent chat or terminal session to resume with complete context.</div>
            <button class="btn-primary" id="btn-copy-resume">📋 Copy Prompt to Clipboard</button>
          </div>
        </div>
      </div>
    `;

    this.bindEvents(container);
    await this.loadProjects();
  },

  bindEvents(container) {
    // Column collapse toggles
    const btnToggleMaster = container.querySelector('#btn-toggle-master-col');
    const masterCol = container.querySelector('#projects-master-col');
    if (btnToggleMaster && masterCol) {
      const toggleMaster = () => {
        this.masterColCollapsed = !this.masterColCollapsed;
        masterCol.classList.toggle('collapsed', this.masterColCollapsed);
        btnToggleMaster.innerText = this.masterColCollapsed ? '▶' : '◀';
        btnToggleMaster.title = this.masterColCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar';
      };
      btnToggleMaster.addEventListener('click', toggleMaster);
      masterCol.querySelector('.collapsed-rail-text')?.addEventListener('click', toggleMaster);
    }

    const btnToggleInspector = container.querySelector('#btn-toggle-inspector-col');
    const inspectorCol = container.querySelector('#projects-inspector');
    if (btnToggleInspector && inspectorCol) {
      const toggleInspector = () => {
        this.inspectorColCollapsed = !this.inspectorColCollapsed;
        inspectorCol.classList.toggle('collapsed', this.inspectorColCollapsed);
        btnToggleInspector.innerText = this.inspectorColCollapsed ? '◀' : '▶';
        btnToggleInspector.title = this.inspectorColCollapsed ? 'Expand Inspector' : 'Collapse Inspector';
      };
      btnToggleInspector.addEventListener('click', toggleInspector);
      inspectorCol.querySelector('.collapsed-rail-text')?.addEventListener('click', toggleInspector);
    }

    const mq=container.querySelector('.open-memory-quality'); if(mq) mq.addEventListener('click',()=>window.App.openMemoryQuality());
    // Search input with debounce
    const searchInput = container.querySelector('#projects-search-input');
    let searchDebounce = null;
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(() => {
          this.searchQuery = e.target.value;
          this.loadProjects();
        }, 200);
      });
    }

    // Sort select
    const sortSelect = container.querySelector('#projects-sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', (e) => {
        this.sortBy = e.target.value;
        this.loadProjects();
      });
    }

    // Packet modal close
    const btnCloseModal = container.querySelector('#btn-close-packet-modal');
    if (btnCloseModal) {
      btnCloseModal.addEventListener('click', () => this.closePacketModal());
    }

    // Profile selector
    container.querySelectorAll('#packet-profile-selector .segment').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        container.querySelectorAll('#packet-profile-selector .segment').forEach((b) => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
        this.packetModal.profile = e.currentTarget.dataset.profile;
        this.refreshPacketPreview();
      });
    });

    // Format tabs (Markdown vs JSON)
    container.querySelectorAll('#packet-format-tabs .tab-pill').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        container.querySelectorAll('#packet-format-tabs .tab-pill').forEach((b) => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
        this.packetModal.format = e.currentTarget.dataset.format;
        this.updatePacketDisplay();
      });
    });

    // Section checkboxes
    const toggleMap = {
      'pkt-sec-brief': 'brief',
      'pkt-sec-focus': 'focus',
      'pkt-sec-tasks': 'tasks',
      'pkt-sec-decisions': 'decisions',
      'pkt-sec-activity': 'activity',
      'pkt-sec-knowledge': 'knowledge'
    };
    Object.entries(toggleMap).forEach(([elemId, key]) => {
      const el = container.querySelector(`#${elemId}`);
      if (el) {
        el.checked = this.packetModal.sections[key];
        el.addEventListener('change', (e) => {
          this.packetModal.sections[key] = e.target.checked;
          this.refreshPacketPreview();
        });
      }
    });

    // Copy Packet button
    const btnCopy = container.querySelector('#btn-copy-packet');
    if (btnCopy) {
      btnCopy.addEventListener('click', async () => {
        if (!this.packetModal.preview) return;
        const text = this.packetModal.format === 'json'
          ? JSON.stringify(this.packetModal.preview.raw_payload || {}, null, 2)
          : (this.packetModal.preview.markdown || '');
        try {
          await navigator.clipboard.writeText(text);
          btnCopy.innerText = '✓ Copied!';
          setTimeout(() => { btnCopy.innerText = '📋 Copy to Clipboard'; }, 2000);
        } catch (e) {
          console.error('Clipboard copy failed:', e);
        }
      });
    }

    // Export Packet button
    const btnExport = container.querySelector('#btn-export-packet');
    if (btnExport) {
      btnExport.addEventListener('click', async () => {
        await this.exportPacketToFile();
      });
    }

    // Resume Modal Events
    const btnCloseResume = container.querySelector('#btn-close-resume-modal');
    if (btnCloseResume) {
      btnCloseResume.addEventListener('click', () => {
        const modal = document.getElementById('modal-resume-context');
        if (modal) modal.style.display = 'none';
        this.resumeModal.isOpen = false;
      });
    }

    container.querySelectorAll('#resume-format-selector .segment').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        container.querySelectorAll('#resume-format-selector .segment').forEach((b) => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
        this.resumeModal.format = e.currentTarget.dataset.fmt;
        this.refreshResumePreview();
      });
    });

    const btnCopyResume = container.querySelector('#btn-copy-resume');
    if (btnCopyResume) {
      btnCopyResume.addEventListener('click', async () => {
        if (!this.resumeModal.bundle) return;
        const text = this.resumeModal.format === 'json'
          ? JSON.stringify(this.resumeModal.bundle, null, 2)
          : (this.resumeModal.bundle.prompt || '');
        try {
          await navigator.clipboard.writeText(text);
          btnCopyResume.innerText = '✓ Copied Resumption Prompt!';
          setTimeout(() => { btnCopyResume.innerText = '📋 Copy Prompt to Clipboard'; }, 2000);
        } catch (e) {
          console.error('Clipboard copy failed:', e);
        }
      });
    }
  },

  async loadProjects() {
    const listEl = document.getElementById('projects-list');
    if (!listEl) return;

    try {
      const res = await window.gms.getProjects({
        sort: this.sortBy,
        q: this.searchQuery
      });
      this.projects = res.projects || [];
      this.renderProjectsList();

      // If we have projects and none is selected, select the first or the one from AppState
      const targetId = window.AppState?.state?.selectedProjectId || this.selectedProjectId || (this.projects[0]?.project_id);
      if (targetId && this.projects.some(p => p.project_id === targetId)) {
        await this.selectProject(targetId);
      } else if (this.projects.length > 0) {
        await this.selectProject(this.projects[0].project_id);
      } else {
        this.renderEmptyWorkspace();
      }
    } catch (err) {
      listEl.innerHTML = `<div class="error-state">Failed to load projects<br><small>${this.escapeHtml(err.message)}</small></div>`;
    }
  },

  renderProjectsList() {
    const listEl = document.getElementById('projects-list');
    if (!listEl) return;

    if (!this.projects.length) {
      listEl.innerHTML = `
        <div class="empty-list">
          <strong>No projects found</strong>
          <span>Projects in ~/memories/projects/ or gms_tasks will appear here.</span>
        </div>`;
      return;
    }

    listEl.innerHTML = this.projects.map((p) => {
      const isSelected = p.project_id === this.selectedProjectId;
      const attentionCount = p.attention_count || 0;
      const timeAgo = this.formatTimeAgo(p.last_activity);
      const purpose = p.purpose || 'No purpose recorded';
      const completeness = p.bank_completeness || {};
      const completionPercent = Math.round((completeness.completion_ratio || 0) * 100);

      return `
        <div class="project-list-card ${isSelected ? 'selected' : ''}" data-project-id="${this.escapeHtml(p.project_id)}">
          <div class="project-card-top">
            <span class="project-card-title">${this.escapeHtml(p.name || p.project_id)}</span>
            ${attentionCount > 0 ? `<span class="attention-dot" title="${attentionCount} attention items"></span>` : ''}
          </div>
          <div class="project-card-purpose">${this.escapeHtml(purpose)}</div>
          <div class="project-card-footer">
            <span class="project-card-time">${this.escapeHtml(timeAgo || 'Idle')}</span>
            <div class="project-card-badges">
              <span class="badge ${completionPercent === 100 ? 'badge-complete' : 'badge-attention'}" title="${this.escapeHtml((completeness.missing_files || []).join(', ') || 'All five project context files are populated')}">${completionPercent}% context</span>
              ${p.pending_handoffs > 0 ? `<span class="badge badge-handoff" title="${p.pending_handoffs} pending handoff(s)">${p.pending_handoffs} handoff</span>` : ''}
              ${p.open_tasks > 0 ? `<span class="badge badge-task">${p.open_tasks} tasks</span>` : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');

    listEl.querySelectorAll('.project-list-card').forEach((card) => {
      card.addEventListener('click', () => {
        const pid = card.dataset.projectId;
        if (pid) this.selectProject(pid);
      });
    });
  },

  async selectProject(projectId) {
    this.selectedProjectId = projectId;
    if (window.AppState) {
      window.AppState.setSelectedProjectId(projectId);
    }

    // Highlight row
    document.querySelectorAll('.project-list-card').forEach((c) => {
      c.classList.toggle('selected', c.dataset.projectId === projectId);
    });

    const detailEl = document.getElementById('projects-detail-container');
    if (!detailEl) return;
    detailEl.innerHTML = '<div class="loading-state">Loading project context workspace...</div>';

    try {
      const detail = await window.gms.getProject(projectId);
      this.currentProject = detail;
      this.renderProjectDetail(detail);
    } catch (err) {
      detailEl.innerHTML = `<div class="error-state">Failed to load project details<br><small>${this.escapeHtml(err.message)}</small></div>`;
    }
  },

  renderEmptyWorkspace() {
    const detailEl = document.getElementById('projects-detail-container');
    if (detailEl) {
      detailEl.innerHTML = `
        <div class="empty-project-selection">
          <div class="empty-icon">📁</div>
          <strong>No Projects Available</strong>
          <span>Create a project folder under <code>~/memories/projects/{name}/</code> or add tasks with <code>--project</code>.</span>
        </div>`;
    }
  },

  renderProjectDetail(detail) {
    const container = document.getElementById('projects-detail-container');
    if (!container) return;

    const attentionItems = detail.attention_items || [];
    const brief = detail.brief || {};
    const act = detail.active_context || {};
    const tasks = detail.tasks || { in_progress: [], needs_review: [], open: [], completed: [] };
    const decisions = detail.decisions || [];
    const completeness = detail.bank_completeness || {};
    const completionPercent = Math.round((completeness.completion_ratio || 0) * 100);

    const totalOpen = (tasks.in_progress?.length || 0) + (tasks.needs_review?.length || 0) + (tasks.open?.length || 0);

    container.innerHTML = `
      <!-- Workspace Header -->
      <header class="project-ws-header">
        <div class="project-ws-title-group">
          <div style="display: flex; align-items: center; gap: 8px;">
            <h2>${this.escapeHtml(detail.name || detail.project_id)}</h2>
            <span class="project-id-pill">${this.escapeHtml(detail.project_id)}</span>
            <span class="freshness-pill">${detail.last_activity ? `Active ${this.escapeHtml(this.formatTimeAgo(detail.last_activity))}` : 'Idle'}</span>
            <span class="freshness-pill" title="${this.escapeHtml((completeness.missing_files || []).join(', ') || 'All standard context files populated')}">${completionPercent}% context complete</span>
          </div>
          <div class="project-repo-meta">
            <span>📁 ${this.escapeHtml(detail.repo_path || detail.bank_path || 'No repository root')}</span>
            ${detail.host_info ? `<span>· 💻 ${this.escapeHtml(detail.host_info)}</span>` : ''}
          </div>
        </div>

        <div class="project-ws-actions">
          <button class="btn-primary" id="btn-resume-context" style="background: linear-gradient(135deg, #238636, #2ea043); border: none; font-weight: 600; display: flex; align-items: center; gap: 6px;">
            <span>🚀</span>
            <span>Resume with Context</span>
          </button>
          <button class="btn-secondary" id="btn-open-packet-modal">
            <span>📦</span>
            <span>Context Packet</span>
          </button>
          <button class="btn-secondary" id="btn-refresh-project" title="Refresh Project">
            <span>🔄</span>
          </button>
        </div>
      </header>

      <!-- Attention Banner (if any attention items) -->
      ${attentionItems.length > 0 ? `
        <div class="project-attention-banner">
          <div class="attention-banner-header">
            <span class="attention-icon">⚠️</span>
            <strong>Attention Needed (${attentionItems.length})</strong>
          </div>
          <div class="attention-items-list">
            ${attentionItems.map(item => `
              <div class="attention-pill-item">
                <span class="attention-tag">${this.escapeHtml(item.type)}</span>
                <span class="attention-msg">${this.escapeHtml(item.message)}</span>
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}

      <!-- Navigation Tabs for Context Workspace -->
      <nav class="project-ws-nav">
        <button class="ws-nav-tab ${this.activeTab === 'overview' ? 'active' : ''}" data-tab="overview">
          Overview
        </button>
        <button class="ws-nav-tab ${this.activeTab === 'decisions' ? 'active' : ''}" data-tab="decisions">
          Decisions <span class="tab-count">${decisions.length}</span>
        </button>
        <button class="ws-nav-tab ${this.activeTab === 'work' ? 'active' : ''}" data-tab="work">
          Active Work <span class="tab-count">${totalOpen}</span>
        </button>
        <button class="ws-nav-tab ${this.activeTab === 'activity' ? 'active' : ''}" data-tab="activity">
          Timeline
        </button>
        <button class="ws-nav-tab ${this.activeTab === 'knowledge' ? 'active' : ''}" data-tab="knowledge">
          Knowledge
        </button>
        <button class="ws-nav-tab ${this.activeTab === 'handoffs' ? 'active' : ''}" data-tab="handoffs">
          Handoffs <span class="tab-count">${(detail.tasks?.needs_review || []).length}</span>
        </button>
      </nav>

      <!-- Tab Content Area -->
      <div class="project-ws-content" id="project-tab-content">
        <!-- Rendered by active tab handler -->
      </div>
    `;

    // Bind header actions
    container.querySelector('#btn-resume-context')?.addEventListener('click', () => {
      this.openResumeModal();
    });
    container.querySelector('#btn-open-packet-modal')?.addEventListener('click', () => {
      this.openPacketModal();
    });
    container.querySelector('#btn-refresh-project')?.addEventListener('click', () => {
      this.selectProject(detail.project_id);
    });

    // Bind tabs
    container.querySelectorAll('.ws-nav-tab').forEach((tab) => {
      tab.addEventListener('click', (e) => {
        container.querySelectorAll('.ws-nav-tab').forEach((t) => t.classList.remove('active'));
        e.currentTarget.classList.add('active');
        this.activeTab = e.currentTarget.dataset.tab;
        this.renderActiveTabContent();
      });
    });

    this.renderActiveTabContent();
  },

  renderActiveTabContent() {
    const tabContainer = document.getElementById('project-tab-content');
    if (!tabContainer || !this.currentProject) return;

    if (this.activeTab === 'overview') {
      this.renderOverviewTab(tabContainer);
    } else if (this.activeTab === 'decisions') {
      this.renderDecisionsTab(tabContainer);
    } else if (this.activeTab === 'work') {
      this.renderWorkTab(tabContainer);
    } else if (this.activeTab === 'activity') {
      this.renderActivityTab(tabContainer);
    } else if (this.activeTab === 'knowledge') {
      this.renderKnowledgeTab(tabContainer);
    } else if (this.activeTab === 'handoffs') {
      this.renderHandoffsTab(tabContainer);
    }
  },

  // ---------------------------------------------------------------------------
  // Tab 1: Operational Project Briefing (gms-project-briefing-v1)
  // ---------------------------------------------------------------------------
  async renderOverviewTab(container) {
    const p = this.currentProject;
    container.innerHTML = '<div class="loading-state">Loading operational project briefing...</div>';

    let briefing = null;
    try {
      briefing = await window.gms.getProjectBriefing({
        id: p.project_id,
        as_of: this.asOfTimestamp || null,
        profile: 'standard'
      });
    } catch (e) {
      console.warn('Failed to load project briefing via API, using fallback:', e);
    }

    const nextAction = briefing?.next_action || { statement: 'Verify active project tasks', rationale: 'Maintain task momentum' };
    const blockers = briefing?.blocking_issues || [];
    const bindingDecisions = briefing?.binding_decisions || (p.decisions || []);
    const constraints = briefing?.constraints || (p.active_context?.constraints || []);
    const currentTruth = briefing?.current_truth || [];
    const activeTasks = briefing?.active_work || (p.tasks?.in_progress || []);
    const packetHash = briefing?.packet_hash || 'sha256:...';
    const goalStatement = briefing?.goal?.statement || (p.brief?.overview || p.brief?.purpose || 'No goal stated.');

    container.innerHTML = `
      <div class="briefing-control-bar card" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; margin-bottom: 12px; background: rgba(22, 27, 34, 0.7); border: 1px solid var(--border-color); border-radius: var(--radius-sm);">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 13px; font-weight: 600; color: var(--text-secondary);">Temporal View:</span>
          <span class="badge ${this.asOfTimestamp ? 'badge-warning' : 'badge-active'}">${this.asOfTimestamp ? `As of: ${this.asOfTimestamp}` : 'Live (Current Truth)'}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <input type="datetime-local" id="input-as-of-time" class="search-input" style="font-size: 11px; padding: 4px 8px; width: 190px;" value="${this.asOfTimestamp ? this.asOfTimestamp.slice(0, 16) : ''}">
          <button class="btn-tiny" id="btn-apply-as-of">Apply</button>
          ${this.asOfTimestamp ? '<button class="btn-tiny" id="btn-reset-as-of">Reset to Live</button>' : ''}
          <span class="stat-badge hash" style="font-size: 10px;" title="Deterministic Packet Hash">${this.escapeHtml(packetHash.slice(0, 24))}...</span>
        </div>
      </div>

      <!-- Top Primary Action Box -->
      <div class="context-card next-action-card" style="border: 1px solid rgba(63, 185, 80, 0.4); background: rgba(63, 185, 80, 0.04); margin-bottom: 14px;">
        <div class="context-card-header" style="border-bottom: 1px solid rgba(63, 185, 80, 0.2);">
          <span class="card-icon" style="color: var(--accent-green);">⚡</span>
          <strong style="color: var(--text-primary); font-size: 14px;">Next Action Required (START HERE)</strong>
          <span class="badge" style="background: rgba(63, 185, 80, 0.15); color: var(--accent-green);">Priority 1</span>
        </div>
        <div class="context-card-body">
          <h4 style="margin: 0 0 6px 0; font-size: 15px; color: var(--text-primary); font-weight: 600;">${this.escapeHtml(nextAction.statement || 'No immediate action')}</h4>
          <p style="margin: 0 0 10px 0; font-size: 12px; color: var(--text-secondary);"><b>Rationale:</b> ${this.escapeHtml(nextAction.rationale || 'Operational continuity')}</p>
          ${nextAction.acceptance_criteria && nextAction.acceptance_criteria.length > 0 ? `
            <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); margin-bottom: 4px;">Acceptance Criteria</div>
            <ul class="bullet-list" style="margin-left: 14px; font-size: 12.5px;">
              ${nextAction.acceptance_criteria.map(c => `<li><span style="color: var(--accent-green); margin-right: 4px;">✓</span> ${this.escapeHtml(c)}</li>`).join('')}
            </ul>
          ` : ''}
        </div>
      </div>

      <!-- Blocking Issues Box (if any blockers) -->
      ${blockers.length > 0 ? `
        <div class="context-card blocker-alert-card" style="border: 1px solid rgba(248, 81, 73, 0.4); background: rgba(248, 81, 73, 0.05); margin-bottom: 14px;">
          <div class="context-card-header" style="border-bottom: 1px solid rgba(248, 81, 73, 0.2);">
            <span class="card-icon" style="color: var(--accent-red);">⚠️</span>
            <strong style="color: var(--accent-red); font-size: 14px;">Blocking Contradictions & Collisions (${blockers.length})</strong>
          </div>
          <div class="context-card-body" style="display: flex; flex-direction: column; gap: 8px;">
            ${blockers.map(b => `
              <div class="blocker-item-row" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; background: rgba(0,0,0,0.2); border-radius: var(--radius-sm);">
                <div>
                  <strong style="font-size: 13px; color: var(--text-primary);">${this.escapeHtml(b.title || b.key)}</strong>
                  <div style="font-size: 11.5px; color: var(--accent-red); margin-top: 2px;">${this.escapeHtml(b.statement)}</div>
                </div>
                <button class="btn-tiny open-inbox-btn" style="border-color: var(--accent-red); color: var(--accent-red);">Resolve in Inbox</button>
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}

      <div class="overview-grid">
        <!-- Goal & Mission Card -->
        <div class="context-card full-width">
          <div class="context-card-header">
            <span class="card-icon">🎯</span>
            <strong>Project Mission & Core Truth</strong>
          </div>
          <div class="context-card-body">
            <p class="mission-statement" style="font-size: 13.5px; line-height: 1.5;">${this.escapeHtml(goalStatement)}</p>
          </div>
        </div>

        <!-- Binding Decisions Card -->
        <div class="context-card">
          <div class="context-card-header">
            <span class="card-icon">⚖️</span>
            <strong>Binding Decisions (${bindingDecisions.length})</strong>
          </div>
          <div class="context-card-body">
            ${bindingDecisions.length > 0 ? `
              <div style="display: flex; flex-direction: column; gap: 8px;">
                ${bindingDecisions.slice(0, 5).map(d => `
                  <div class="decision-preview-item" data-decision-id="${this.escapeHtml(d.decision_id || d.key || '')}" style="cursor: pointer; padding: 6px 8px; background: var(--bg-surface); border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
                    <div style="font-size: 12.5px; font-weight: 600; color: var(--accent-blue);">${this.escapeHtml(d.statement || d.decision || d.key)}</div>
                    <div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">${this.escapeHtml(d.rationale || 'Preserve architectural bounds')}</div>
                  </div>
                `).join('')}
              </div>
            ` : '<span class="muted">No binding decisions recorded.</span>'}
          </div>
        </div>

        <!-- Constraints Card -->
        <div class="context-card">
          <div class="context-card-header">
            <span class="card-icon">⛔</span>
            <strong>Active Constraints & Boundaries (${constraints.length})</strong>
          </div>
          <div class="context-card-body">
            ${constraints.length > 0 ? `
              <ul class="bullet-list">
                ${constraints.map(c => `<li>${this.escapeHtml(typeof c === 'object' ? c.statement : c)}</li>`).join('')}
              </ul>
            ` : '<span class="muted">No explicit constraints recorded.</span>'}
          </div>
        </div>

        <!-- Active Workstream -->
        <div class="context-card">
          <div class="context-card-header">
            <span class="card-icon">🔨</span>
            <strong>Active Tasks (${activeTasks.length})</strong>
          </div>
          <div class="context-card-body">
            ${activeTasks.length > 0 ? `
              <div style="display: flex; flex-direction: column; gap: 6px;">
                ${activeTasks.slice(0, 4).map(t => `
                  <div style="display: flex; justify-content: space-between; align-items: center; padding: 4px 6px; background: var(--bg-surface); border-radius: var(--radius-sm);">
                    <span style="font-size: 12px; font-weight: 500;">${this.escapeHtml(t.title || t.task_id)}</span>
                    <span class="badge badge-task" style="font-size: 10px;">${this.escapeHtml(t.status || 'open')}</span>
                  </div>
                `).join('')}
              </div>
            ` : '<span class="muted">No tasks currently in progress.</span>'}
          </div>
        </div>

        <!-- Verified Current Truth -->
        <div class="context-card">
          <div class="context-card-header">
            <span class="card-icon">🛡️</span>
            <strong>Verified Current Truth (${currentTruth.length})</strong>
          </div>
          <div class="context-card-body">
            ${currentTruth.length > 0 ? `
              <div style="display: flex; flex-direction: column; gap: 6px;">
                ${currentTruth.slice(0, 4).map(tr => `
                  <div style="padding: 4px 6px; font-size: 12px;">
                    <b>${this.escapeHtml(tr.key)}</b>: ${this.escapeHtml(tr.statement ? tr.statement.slice(0, 80) + '...' : '')}
                  </div>
                `).join('')}
              </div>
            ` : '<span class="muted">See Knowledge tab for scoped facts.</span>'}
          </div>
        </div>
      </div>
    `;

    // Bind As-Of controls
    const asOfInput = container.querySelector('#input-as-of-time');
    container.querySelector('#btn-apply-as-of')?.addEventListener('click', () => {
      if (asOfInput && asOfInput.value) {
        this.asOfTimestamp = new Date(asOfInput.value).toISOString();
        this.renderOverviewTab(container);
      }
    });
    container.querySelector('#btn-reset-as-of')?.addEventListener('click', () => {
      this.asOfTimestamp = null;
      this.renderOverviewTab(container);
    });
    container.querySelectorAll('.open-inbox-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (window.App && window.App.switchView) {
          window.App.switchView('action_inbox');
        }
      });
    });
    container.querySelectorAll('.decision-preview-item').forEach(item => {
      item.addEventListener('click', async () => {
        const did = item.dataset.decisionId;
        if (did && window.gms.getDecisionImpact) {
          const impact = await window.gms.getDecisionImpact(did);
          this.inspectItem('decision', impact);
        }
      });
    });
  },

  // ---------------------------------------------------------------------------
  // Tab 2: Rationale-First Decisions
  // ---------------------------------------------------------------------------
  renderDecisionsTab(container) {
    const decisions = this.currentProject?.decisions || [];

    if (!decisions.length) {
      container.innerHTML = `
        <div class="empty-section-state">
          <div class="empty-icon">⚖️</div>
          <strong>No Decisions Recorded</strong>
          <span>Decisions recorded in <code>activeContext.md</code> or semantic facts under <code>${this.escapeHtml(this.currentProject.project_id)}.*</code> will appear here with rationale and implications.</span>
        </div>`;
      return;
    }

    container.innerHTML = `
      <div class="decisions-list">
        ${decisions.map((d, index) => {
          const provClass = `prov-${d.provenance || 'explicit'}`;
          return `
            <div class="decision-card" data-decision-index="${index}">
              <div class="decision-card-top">
                <div class="decision-title-row">
                  <span class="decision-bullet">◆</span>
                  <strong class="decision-heading">${this.escapeHtml(d.decision)}</strong>
                </div>
                <div class="decision-pills">
                  <span class="scope-pill">${this.escapeHtml(d.scope || 'project')}</span>
                  <span class="provenance-pill ${provClass}">${this.escapeHtml(d.provenance || 'explicit')}</span>
                </div>
              </div>

              <div class="decision-rationale-row">
                <div class="label-heading">Rationale</div>
                <div class="rationale-text">${this.escapeHtml(d.rationale || 'No explicit rationale recorded.')}</div>
              </div>

              ${d.implications && (Array.isArray(d.implications) ? d.implications.length : String(d.implications).trim()) ? `
                <div class="decision-implications-row">
                  <div class="label-heading">Implications & Next Steps</div>
                  <div class="implications-text">
                    ${Array.isArray(d.implications) ? `<ul style="margin: 4px 0 0 16px; padding: 0; font-size: 12px; color: #a0aec0;">${d.implications.map(i => `<li>${this.escapeHtml(i)}</li>`).join('')}</ul>` : this.escapeHtml(d.implications)}
                  </div>
                </div>
              ` : ''}

              <div class="decision-footer">
                <span class="decision-author">${d.author ? `Decided by <b>${this.escapeHtml(d.author)}</b>` : 'Project Policy'}</span>
                ${d.date ? `<span class="decision-date">${this.escapeHtml(d.date)}</span>` : ''}
              </div>

              ${(d.raw || d.raw_payload) ? `
                <details class="raw-disclosure">
                  <summary>Raw Structure</summary>
                  <pre class="code-preview">${this.escapeHtml(JSON.stringify(d.raw || d.raw_payload, null, 2))}</pre>
                </details>
              ` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;

    container.querySelectorAll('.decision-card').forEach((card) => {
      card.addEventListener('click', (e) => {
        // don't inspect if clicking details toggle
        if (e.target.closest('details')) return;
        const idx = parseInt(card.dataset.decisionIndex, 10);
        if (!isNaN(idx) && decisions[idx]) {
          this.inspectItem('decision', decisions[idx]);
        }
      });
    });
  },

  // ---------------------------------------------------------------------------
  // Tab 3: Work & Handoffs
  // ---------------------------------------------------------------------------
  renderWorkTab(container) {
    const p = this.currentProject;
    const tasks = p.tasks || {};
    const inProgress = tasks.in_progress || [];
    const needsReview = tasks.needs_review || [];
    const openTasks = tasks.open || [];
    const completed = tasks.completed || [];

    const totalTasks = inProgress.length + needsReview.length + openTasks.length + completed.length;

    if (totalTasks === 0) {
      container.innerHTML = `
        <div class="empty-section-state">
          <div class="empty-icon">📋</div>
          <strong>No SQLite Tasks Tracked</strong>
          <span>No active tasks in <code>gms_tasks</code> for project <code>${this.escapeHtml(p.project_id)}</code>. Active context from markdown files remains visible in the Truth & State tab.</span>
        </div>`;
      return;
    }

    container.innerHTML = `
      <div class="work-columns">
        <!-- Needs Review / Pending Handoffs -->
        ${needsReview.length > 0 ? `
          <div class="task-lane alert-lane">
            <div class="lane-header">
              <span class="lane-icon">📬</span>
              <strong>Pending Review & Handoffs (${needsReview.length})</strong>
            </div>
            <div class="lane-tasks">
              ${needsReview.map(t => this.renderTaskCard(t, 'needs_review')).join('')}
            </div>
          </div>
        ` : ''}

        <!-- Active / In Progress -->
        <div class="task-lane">
          <div class="lane-header">
            <span class="lane-icon">🏃</span>
            <strong>Active / In Progress (${inProgress.length})</strong>
          </div>
          <div class="lane-tasks">
            ${inProgress.length > 0
              ? inProgress.map(t => this.renderTaskCard(t, 'in_progress')).join('')
              : '<div class="empty-lane">No tasks currently claimed or in progress.</div>'}
          </div>
        </div>

        <!-- Open / Backlog -->
        <div class="task-lane">
          <div class="lane-header">
            <span class="lane-icon">📌</span>
            <strong>Open Tasks (${openTasks.length})</strong>
          </div>
          <div class="lane-tasks">
            ${openTasks.length > 0
              ? openTasks.map(t => this.renderTaskCard(t, 'open')).join('')
              : '<div class="empty-lane">No unassigned open tasks.</div>'}
          </div>
        </div>

        <!-- Completed Tasks (collapsible) -->
        ${completed.length > 0 ? `
          <details class="completed-tasks-disclosure">
            <summary>Completed Tasks (${completed.length})</summary>
            <div class="lane-tasks" style="margin-top: 10px;">
              ${completed.map(t => this.renderTaskCard(t, 'completed')).join('')}
            </div>
          </details>
        ` : ''}
      </div>
    `;

    container.querySelectorAll('.task-item-card').forEach((card) => {
      card.addEventListener('click', async (e) => {
        const taskId = card.dataset.taskId;
        if (!taskId) return;
        try {
          const resume = await window.gms.getTaskResume(taskId);
          this.inspectItem('task', resume);
        } catch (err) {
          console.error('Failed to get task resume:', err);
        }
      });
    });
  },

  renderTaskCard(t, statusGroup) {
    const hasCheckpoint = !!t.latest_checkpoint;
    const hasHandoff = !!t.latest_handoff;

    return `
      <div class="task-item-card status-${statusGroup}" data-task-id="${this.escapeHtml(t.task_id)}">
        <div class="task-item-top">
          <strong class="task-title">${this.escapeHtml(t.title || t.task_id)}</strong>
          <span class="task-id-pill">${this.escapeHtml(t.task_id)}</span>
        </div>
        <div class="task-meta-row">
          <span>Agent: <b>${this.escapeHtml(t.claimed_by || t.owner || 'unassigned')}</b></span>
          <span>Priority: <b>${this.escapeHtml(t.priority || 'normal')}</b></span>
        </div>
        ${hasCheckpoint ? `
          <div class="task-checkpoint-snippet">
            <span class="chk-icon">📍</span>
            <span>Checkpoint: ${this.escapeHtml(t.latest_checkpoint.notes || 'Progress checkpoint')}</span>
          </div>
        ` : ''}
        ${hasHandoff ? `
          <div class="task-handoff-snippet">
            <span class="chk-icon">📦</span>
            <span>Handoff: ${this.escapeHtml(t.latest_handoff.summary || 'Context handoff pending')}</span>
          </div>
        ` : ''}
      </div>
    `;
  },

  // ---------------------------------------------------------------------------
  // Tab 4: Unified Project Timeline (gms-timeline-stream-v1)
  // ---------------------------------------------------------------------------
  async renderActivityTab(container) {
    container.innerHTML = '<div class="loading-state">Loading unified project timeline...</div>';

    try {
      let timeline = [];
      if (window.gms.getProjectTimeline) {
        const res = await window.gms.getProjectTimeline({
          projectId: this.currentProject.project_id,
          limit: 50
        });
        timeline = res.events || [];
      } else {
        const res = await window.gms.getProjectActivity({
          projectId: this.currentProject.project_id,
          limit: 50
        });
        timeline = res.activity || [];
      }

      if (!timeline.length) {
        container.innerHTML = `
          <div class="empty-section-state">
            <div class="empty-icon">🕒</div>
            <strong>No Timeline Events Logged</strong>
            <span>Bank changes, decisions, contradictions, or task lifecycle transitions will appear here.</span>
          </div>`;
        return;
      }

      container.innerHTML = `
        <div class="timeline-container">
          ${timeline.map((entry) => {
            const kindClass = `kind-${entry.event_type || entry.source_type || 'task'}`;
            const timeAgo = this.formatTimeAgo(entry.event_time || entry.timestamp);

            return `
              <div class="timeline-entry" data-event-id="${this.escapeHtml(entry.event_id || '')}">
                <div class="timeline-left">
                  <span class="timeline-dot ${kindClass}"></span>
                  <div class="timeline-line"></div>
                </div>
                <div class="timeline-body card" style="padding: 10px 14px; margin-bottom: 8px; border: 1px solid var(--border-color); background: var(--bg-surface);">
                  <div class="timeline-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <span class="badge ${kindClass}" style="font-size: 10.5px;">${this.escapeHtml(entry.event_type || entry.source_type || 'event')}</span>
                      <strong class="timeline-title" style="font-size: 13px;">${this.escapeHtml(entry.title || entry.event_id || 'Event')}</strong>
                    </div>
                    <span class="timeline-time muted" style="font-size: 11px;">${this.escapeHtml(timeAgo || '')}</span>
                  </div>
                  <div class="timeline-content" style="font-size: 12px; color: var(--text-secondary); margin: 4px 0;">${this.escapeHtml(entry.statement || entry.content || '')}</div>
                  <div class="timeline-footer" style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-top: 6px; padding-top: 4px; border-top: 1px solid var(--border-subtle);">
                    <span>Actor: <b>${this.escapeHtml(entry.actor || entry.author || 'system')}</b></span>
                    ${entry.source_ref ? `<span>Ref: <code>${this.escapeHtml(entry.source_ref)}</code></span>` : ''}
                    ${entry.event_id ? `<span>ID: <code>${this.escapeHtml(entry.event_id)}</code></span>` : ''}
                  </div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    } catch (err) {
      container.innerHTML = `<div class="error-state">Failed to load project timeline<br><small>${this.escapeHtml(err.message)}</small></div>`;
    }
  },

  // ---------------------------------------------------------------------------
  // Tab 5: Scoped Knowledge
  // ---------------------------------------------------------------------------
  async renderKnowledgeTab(container) {
    container.innerHTML = '<div class="loading-state">Loading scoped facts, entities, and artifacts...</div>';

    try {
      const res = await window.gms.getProjectKnowledge({
        projectId: this.currentProject.project_id,
        limit: 50
      });
      const memories = res.memories || [];
      const entities = res.entities || [];
      const artifacts = res.artifacts || [];

      const totalItems = memories.length + entities.length + artifacts.length;

      if (totalItems === 0) {
        container.innerHTML = `
          <div class="empty-section-state">
            <div class="empty-icon">💡</div>
            <strong>No Scoped Knowledge</strong>
            <span>Memories in namespace <code>${this.escapeHtml(this.currentProject.project_id)}.*</code> or entities referenced in project docs will appear here.</span>
          </div>`;
        return;
      }

      container.innerHTML = `
        <div class="knowledge-sections">
          <!-- Memories & Facts -->
          ${memories.length > 0 ? `
            <div class="knowledge-group">
              <div class="knowledge-group-title">
                <span>🧠 Scoped Memories (${memories.length})</span>
              </div>
              <div class="knowledge-grid">
                ${memories.map(m => `
                  <div class="knowledge-card" data-knowledge-key="${this.escapeHtml(m.key)}">
                    <div class="knowledge-card-top">
                      <strong class="knowledge-key">${this.escapeHtml(m.key)}</strong>
                      <span class="why-badge">${this.escapeHtml(m.why_here || 'scoped')}</span>
                    </div>
                    <div class="knowledge-preview">${this.escapeHtml(typeof m.value === 'object' ? JSON.stringify(m.value) : String(m.value))}</div>
                    <div class="knowledge-card-actions">
                      <button class="btn-tiny" data-open-explore="${this.escapeHtml(m.key)}">🔍 Open in Explore</button>
                    </div>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : ''}

          <!-- Entities -->
          ${entities.length > 0 ? `
            <div class="knowledge-group">
              <div class="knowledge-group-title">
                <span>💡 Linked Entities (${entities.length})</span>
              </div>
              <div class="knowledge-grid">
                ${entities.map(e => `
                  <div class="knowledge-card" data-entity-id="${this.escapeHtml(e.id || '')}">
                    <div class="knowledge-card-top">
                      <strong class="knowledge-key">${this.escapeHtml(e.name || e.id)}</strong>
                      <span class="why-badge">${this.escapeHtml(e.why_here || 'entity')}</span>
                    </div>
                    <div class="knowledge-preview">${this.escapeHtml(e.summary || e.description || e.entity_type || '')}</div>
                    <div class="knowledge-card-actions">
                      <button class="btn-tiny" data-open-concept="${this.escapeHtml(e.id || '')}">💡 Concepts View</button>
                      <button class="btn-tiny" data-open-graph="${this.escapeHtml(e.id || '')}">🕸️ Graph</button>
                    </div>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : ''}

          <!-- Artifacts & Files -->
          ${artifacts.length > 0 ? `
            <div class="knowledge-group">
              <div class="knowledge-group-title">
                <span>📄 Project Bank Files (${artifacts.length})</span>
              </div>
              <div class="knowledge-grid">
                ${artifacts.map(a => `
                  <div class="knowledge-card">
                    <div class="knowledge-card-top">
                      <strong class="knowledge-key">${this.escapeHtml(a.filename)}</strong>
                      <span class="why-badge">${this.escapeHtml(a.why_here || 'bank file')}</span>
                    </div>
                    <div class="knowledge-preview">${this.escapeHtml(a.path || '')}</div>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : ''}
        </div>
      `;

      // Bind actions
      container.querySelectorAll('[data-open-explore]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const key = btn.dataset.openExplore;
          window.App.exploreRelated(key);
        });
      });

      container.querySelectorAll('[data-open-concept]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const eid = btn.dataset.openConcept;
          window.App.openEntity({ id: eid });
        });
      });

      container.querySelectorAll('[data-open-graph]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const eid = btn.dataset.openGraph;
          window.App.openInGraph(eid, eid);
        });
      });
    } catch (err) {
      container.innerHTML = `<div class="error-state">Failed to load scoped knowledge<br><small>${this.escapeHtml(err.message)}</small></div>`;
    }
  },

  // ---------------------------------------------------------------------------
  // Tab 6: Handoffs & Resume Bundles
  // ---------------------------------------------------------------------------
  renderHandoffsTab(container) {
    const p = this.currentProject;
    const tasks = p.tasks || {};
    const needsReview = tasks.needs_review || [];
    const inProgress = tasks.in_progress || [];
    const handoffTasks = [...needsReview, ...inProgress.filter(t => t.latest_handoff)];

    if (handoffTasks.length === 0) {
      container.innerHTML = `
        <div class="empty-section-state">
          <div class="empty-icon">🤝</div>
          <strong>No Active Handoff Packages</strong>
          <span>No unacknowledged task handoffs or active checkpoints requiring takeover in project <code>${this.escapeHtml(p.project_id)}</code>.</span>
        </div>`;
      return;
    }

    container.innerHTML = `
      <div class="handoffs-container" style="display: flex; flex-direction: column; gap: 14px; padding: 12px 0;">
        <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;">
          Review structured cross-agent handoff bundles and checkpoints. Use <strong>Copy Launch Prompt</strong> to resume any task in Gemini, Antigravity, or Codex.
        </div>
        ${handoffTasks.map(t => {
          const hnd = t.latest_handoff || {};
          const chk = t.latest_checkpoint || {};
          return `
            <div class="card handoff-bundle-card" style="background: #111822; border: 1px solid rgba(56,189,248,0.25); border-radius: 8px; padding: 14px;">
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                <div>
                  <span class="badge badge-task" style="font-size: 10px;">${this.escapeHtml(t.status)}</span>
                  <h4 style="margin: 4px 0 0 0; font-size: 14px;">${this.escapeHtml(t.title || t.task_id)}</h4>
                </div>
                <div style="display: flex; gap: 8px;">
                  <button class="btn-primary btn-copy-launch-prompt" data-task-id="${this.escapeHtml(t.task_id)}" style="font-size: 11px; padding: 4px 10px;">
                    📋 Copy Launch Prompt
                  </button>
                  <button class="btn-secondary btn-inspect-handoff" data-task-id="${this.escapeHtml(t.task_id)}" style="font-size: 11px; padding: 4px 8px;">
                    Inspect
                  </button>
                </div>
              </div>
              <div style="font-size: 12px; color: #cbd5e1; margin-bottom: 8px;">
                <strong>Summary:</strong> ${this.escapeHtml(hnd.summary || chk.notes || 'Work in progress')}
              </div>
              ${hnd.blockers ? `
                <div style="font-size: 11px; color: #f87171; margin-bottom: 6px;">
                  <strong>Obstacles / Blockers:</strong> ${this.escapeHtml(hnd.blockers)}
                </div>
              ` : ''}
              <div style="font-size: 11px; color: var(--text-muted); display: flex; gap: 14px; flex-wrap: wrap;">
                <span>Owner: <strong>${this.escapeHtml(t.claimed_by || t.owner || 'unassigned')}</strong></span>
                <span>Last Updated: <strong>${this.escapeHtml(this.formatTimeAgo(t.updated_at || t.created_at))}</strong></span>
                ${chk.status ? `<span>Checkpoint Status: <strong>${this.escapeHtml(chk.status)}</strong></span>` : ''}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;

    container.querySelectorAll('.btn-copy-launch-prompt').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const taskId = e.currentTarget.dataset.taskId;
        const task = handoffTasks.find(t => t.task_id === taskId);
        if (!task) return;
        const hnd = task.latest_handoff || {};
        const chk = task.latest_checkpoint || {};
        const launchPrompt = [
          `# Task Resume Instructions: ${task.title || task.task_id}`,
          `Project: ${p.project_id}`,
          `Task ID: ${task.task_id}`,
          `Current Status: ${task.status}`,
          '',
          '## Handoff Summary',
          hnd.summary || chk.notes || 'Proceed with task implementation.',
          '',
          hnd.blockers ? `## Known Blockers\n${hnd.blockers}\n` : '',
          hnd.uncommitted_files && hnd.uncommitted_files.length ? `## Files in Flight\n${hnd.uncommitted_files.join('\n')}\n` : '',
          '## Next Steps',
          'Review the project brief, verify working tree integrity, and continue execution.'
        ].filter(Boolean).join('\n');

        try {
          await navigator.clipboard.writeText(launchPrompt);
          const orig = btn.textContent;
          btn.textContent = '✓ Copied!';
          setTimeout(() => { btn.textContent = orig; }, 2000);
        } catch (err) {
          alert('Could not copy to clipboard: ' + err.message);
        }
      });
    });

    container.querySelectorAll('.btn-inspect-handoff').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const taskId = e.currentTarget.dataset.taskId;
        if (!taskId) return;
        try {
          const resume = await window.gms.getTaskResume(taskId);
          this.inspectItem('task', resume);
        } catch (err) {
          console.error('Failed to get task resume:', err);
        }
      });
    });
  },

  // ---------------------------------------------------------------------------
  // Column 3: Inspector Drawer
  // ---------------------------------------------------------------------------
  inspectItem(type, item) {
    this.inspectorItem = { type, item };
    const inspectorEl = document.getElementById('projects-inspector-body') || document.getElementById('projects-inspector');
    const inspectorCol = document.getElementById('projects-inspector');
    const btnToggleInspector = document.getElementById('btn-toggle-inspector-col');
    if (!inspectorEl) return;

    if (this.inspectorColCollapsed && inspectorCol) {
      this.inspectorColCollapsed = false;
      inspectorCol.classList.remove('collapsed');
      if (btnToggleInspector) {
        btnToggleInspector.innerText = '▶';
        btnToggleInspector.title = 'Collapse Inspector';
      }
    }

    if (type === 'decision') {
      inspectorEl.innerHTML = `
        <div class="inspector-header">
          <div>
            <span class="badge badge-general">Decision</span>
            <h3 style="margin-top: 4px; font-size: 14px;">${this.escapeHtml(item.decision)}</h3>
          </div>
          <button class="icon-button" id="btn-close-proj-inspector">×</button>
        </div>
        <div class="inspector-meta">
          <div><span>Scope</span><strong>${this.escapeHtml(item.scope || 'project')}</strong></div>
          <div><span>Provenance</span><strong>${this.escapeHtml(item.provenance || 'explicit')}</strong></div>
          <div><span>Author</span><strong>${this.escapeHtml(item.author || 'system')}</strong></div>
          ${item.date ? `<div><span>Decided Date</span><strong>${this.escapeHtml(item.date)}</strong></div>` : ''}
        </div>
        <div class="panel-label">Rationale</div>
        <div class="inspector-text-block">${this.escapeHtml(item.rationale || 'No rationale recorded.')}</div>
        ${item.implications && (Array.isArray(item.implications) ? item.implications.length : String(item.implications).trim()) ? `
          <div class="panel-label" style="margin-top: 12px;">Implications & Next Steps</div>
          <div class="inspector-text-block">
            ${Array.isArray(item.implications) ? `<ul style="margin: 4px 0 0 16px; padding: 0; font-size: 12px; color: #a0aec0;">${item.implications.map((i) => `<li>${this.escapeHtml(i)}</li>`).join('')}</ul>` : this.escapeHtml(item.implications)}
          </div>
        ` : ''}
        ${(item.raw || item.raw_payload) ? `
          <div class="panel-label" style="margin-top: 12px;">Raw Structure</div>
          <pre class="memory-value">${this.escapeHtml(JSON.stringify(item.raw || item.raw_payload, null, 2))}</pre>
        ` : ''}
      `;
    } else if (type === 'task') {
      const t = item.task || {};
      const chk = item.latest_checkpoint;
      const hnd = item.latest_handoff;

      inspectorEl.innerHTML = `
        <div class="inspector-header">
          <div>
            <span class="badge badge-task">${this.escapeHtml(t.status || 'task')}</span>
            <h3 style="margin-top: 4px; font-size: 14px;">${this.escapeHtml(t.title || t.task_id)}</h3>
          </div>
          <button class="icon-button" id="btn-close-proj-inspector">×</button>
        </div>
        <div class="inspector-meta">
          <div><span>Task ID</span><code>${this.escapeHtml(t.task_id)}</code></div>
          <div><span>Agent</span><strong>${this.escapeHtml(t.claimed_by || t.owner || 'unassigned')}</strong></div>
          <div><span>Priority</span><strong>${this.escapeHtml(t.priority || 'normal')}</strong></div>
          ${t.created_at ? `<div><span>Created</span><strong>${this.escapeHtml(this.formatTimeAgo(t.created_at))}</strong></div>` : ''}
        </div>
        ${t.description ? `
          <div class="panel-label">Task Description</div>
          <div class="inspector-text-block">${this.escapeHtml(t.description)}</div>
        ` : ''}
        ${chk ? `
          <div class="panel-label" style="margin-top: 12px;">Latest Checkpoint</div>
          <div class="inspector-checkpoint-card">
            <div><b>Notes:</b> ${this.escapeHtml(chk.notes || '')}</div>
            ${chk.status ? `<div><b>Status:</b> ${this.escapeHtml(chk.status)}</div>` : ''}
            <div class="muted" style="font-size: 10px; margin-top: 4px;">${this.escapeHtml(chk.timestamp || '')}</div>
          </div>
        ` : ''}
        ${hnd ? `
          <div class="panel-label" style="margin-top: 12px;">Latest Handoff Bundle</div>
          <div class="inspector-handoff-card">
            <div><b>Summary:</b> ${this.escapeHtml(hnd.summary || '')}</div>
            ${hnd.blockers ? `<div><b>Blockers:</b> ${this.escapeHtml(hnd.blockers)}</div>` : ''}
            ${hnd.uncommitted_files ? `<div><b>Uncommitted:</b> <code>${this.escapeHtml(JSON.stringify(hnd.uncommitted_files))}</code></div>` : ''}
          </div>
        ` : ''}
      `;
    }

    inspectorEl.querySelector('#btn-close-proj-inspector')?.addEventListener('click', () => {
      this.inspectorItem = null;
      inspectorEl.innerHTML = `
        <div class="empty-inspector">
          <div class="empty-icon">⌁</div>
          <strong>Project Inspector</strong>
          <span>Select any decision, task, handoff, or knowledge record to inspect provenance and actions.</span>
        </div>`;
    });
  },

  // ---------------------------------------------------------------------------
  // Agent Resumption Bundle Modal
  // ---------------------------------------------------------------------------
  async openResumeModal() {
    if (!this.currentProject) return;
    const modal = document.getElementById('modal-resume-context');
    if (!modal) return;

    modal.style.display = 'flex';
    this.resumeModal.isOpen = true;

    const subtitle = document.getElementById('resume-project-subtitle');
    if (subtitle) {
      subtitle.innerText = `Continuation prompt for ${this.currentProject.name || this.currentProject.project_id}`;
    }

    await this.refreshResumePreview();
  },

  async refreshResumePreview() {
    const previewEl = document.getElementById('resume-preview-text');
    const hashEl = document.getElementById('resume-stat-hash');
    if (!previewEl || !this.currentProject) return;
    previewEl.innerText = 'Generating fresh resumption bundle...';
    try {
      const res = await window.gms.getResumeBundle({
        id: this.currentProject.project_id,
        target_format: this.resumeModal.format,
        as_of: this.asOfTimestamp || null,
      });
      this.resumeModal.bundle = res;
      if (hashEl) hashEl.innerText = res.packet_hash ? res.packet_hash.slice(0, 24) + '...' : 'sha256:...';
      if (this.resumeModal.format === 'json') {
        previewEl.innerText = JSON.stringify(res, null, 2);
      } else {
        previewEl.innerText = res.prompt || 'No prompt generated.';
      }
    } catch (err) {
      previewEl.innerText = `Error generating resumption bundle: ${err.message}`;
    }
  },

  // ---------------------------------------------------------------------------
  // Context Packet Modal & Generation
  // ---------------------------------------------------------------------------
  openPacketModal() {
    if (!this.currentProject) return;
    const modal = document.getElementById('modal-context-packet');
    if (!modal) return;

    modal.style.display = 'flex';
    this.packetModal.isOpen = true;

    const subtitle = document.getElementById('packet-project-subtitle');
    if (subtitle) {
      subtitle.innerText = `Deterministic packet for ${this.currentProject.name || this.currentProject.project_id}`;
    }

    this.refreshPacketPreview();
  },

  closePacketModal() {
    const modal = document.getElementById('modal-context-packet');
    if (modal) modal.style.display = 'none';
    this.packetModal.isOpen = false;
  },

  async refreshPacketPreview() {
    if (!this.currentProject) return;
    const previewEl = document.getElementById('packet-preview-text');
    if (previewEl) previewEl.innerText = 'Assembling deterministic context packet...';

    try {
      const res = await window.gms.previewContextPacket({
        project_id: this.currentProject.project_id,
        profile: this.packetModal.profile,
        sections: this.packetModal.sections
      });
      this.packetModal.preview = res;

      // Update stats
      document.getElementById('packet-stat-chars').innerText = `${(res.character_count || 0).toLocaleString()} chars`;
      document.getElementById('packet-stat-tokens').innerText = `~${(res.estimated_tokens || 0).toLocaleString()} tokens`;
      document.getElementById('packet-stat-hash').innerText = res.content_hash ? res.content_hash.slice(0, 18) + '…' : 'hash';
      document.getElementById('packet-stat-hash').title = res.content_hash || '';

      const redactText = document.getElementById('packet-redaction-text');
      if (redactText) {
        const count = res.secrets_redacted_count || 0;
        redactText.innerText = count > 0 ? `${count} secret(s) redacted` : 'Zero secrets detected';
      }

      this.updatePacketDisplay();
    } catch (err) {
      if (previewEl) previewEl.innerText = `Error generating packet: ${err.message}`;
    }
  },

  updatePacketDisplay() {
    const previewEl = document.getElementById('packet-preview-text');
    if (!previewEl || !this.packetModal.preview) return;

    if (this.packetModal.format === 'json') {
      previewEl.innerText = JSON.stringify(this.packetModal.preview.raw_payload || {}, null, 2);
    } else {
      previewEl.innerText = this.packetModal.preview.markdown || 'No markdown output generated.';
    }
  },

  async exportPacketToFile() {
    if (!this.currentProject) return;
    const feedback = document.getElementById('packet-export-feedback');
    if (feedback) feedback.innerText = 'Exporting packet to disk...';

    try {
      const res = await window.gms.exportContextPacket({
        project_id: this.currentProject.project_id,
        profile: this.packetModal.profile,
        sections: this.packetModal.sections
      });

      if (feedback) {
        feedback.innerText = `✓ Exported: ${res.filename} (${(res.character_count || 0).toLocaleString()} chars)`;
        setTimeout(() => { if (feedback) feedback.innerText = ''; }, 5000);
      }
    } catch (err) {
      if (feedback) {
        feedback.innerText = `Export error: ${err.message}`;
        feedback.style.color = 'var(--accent-red)';
      }
    }
  },

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------
  formatTimeAgo(dateStr) {
    if (!dateStr) return '';
    try {
      const d = new Date(String(dateStr).replace(' ', 'T'));
      if (isNaN(d.getTime())) return String(dateStr).slice(0, 10);
      const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
      if (diffSec <= 60) return 'Just now';
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      if (diffSec < 86400 * 7) return `${Math.floor(diffSec / 86400)}d ago`;
      return d.toISOString().slice(0, 10);
    } catch (e) {
      return String(dateStr).slice(0, 10);
    }
  },

  escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
};
