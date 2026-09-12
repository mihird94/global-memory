/**
 * graph_view.js — Mbrain Local-First Knowledge Graph Control Center
 *
 * Implements Mbrain UX Pass 2 (Stages B, C, D):
 * - Collapsible filter panel with deterministic filtering via GraphFilter
 * - Minimum connections threshold (0, 1+, 2+ default, 3+, 5+, 10+)
 * - Search reveal for filtered nodes without resetting user filters
 * - ForceAtlas2 physics presets (Balanced, Loose, Compact, Hierarchical, Manual)
 * - Auto-stabilization stop to prevent perpetual motion and high CPU
 * - Saved graph views stored in localStorage
 * - Node Evidence Inspector and Relationship Evidence Inspector
 * - Zero external CDN / cloud dependencies
 */

window.GraphView = {
  network: null,
  rawGraph: null,
  filteredGraph: null,
  visNodes: null,
  visEdges: null,
  filterPanelOpen: false,
  pendingFocus: null,
  activeLabelMode: 'important', // 'important', 'all', 'none'
  activeClusterMode: 'none',

  filterState: {
    minConnections: 2,
    temporalState: 'active',
    asOfDate: null,
    selectedTypes: [],
    selectedPredicates: [],
    hideIsolates: true,
    largestComponentOnly: false,
    neighborhoodDepth: 'all',
    focusNodeId: null,
    revealedNodeIds: [],
    textQuery: '',
    hideLiteralNodes: false,
  },

  physicsPresets: {
    balanced: {
      gravitationalConstant: -72,
      centralGravity: 0.012,
      springLength: 128,
      springConstant: 0.045,
      damping: 0.55,
      avoidOverlap: 0.65,
      maxVelocity: 28,
      stabilizationIterations: 280,
    },
    loose: {
      gravitationalConstant: -110,
      centralGravity: 0.008,
      springLength: 190,
      springConstant: 0.035,
      damping: 0.60,
      avoidOverlap: 0.85,
      maxVelocity: 35,
      stabilizationIterations: 320,
    },
    compact: {
      gravitationalConstant: -45,
      centralGravity: 0.025,
      springLength: 85,
      springConstant: 0.065,
      damping: 0.50,
      avoidOverlap: 0.50,
      maxVelocity: 22,
      stabilizationIterations: 240,
    },
    hierarchical: {
      gravitationalConstant: -60,
      centralGravity: 0.01,
      springLength: 120,
      springConstant: 0.04,
      damping: 0.5,
      avoidOverlap: 0.7,
      maxVelocity: 25,
      stabilizationIterations: 200,
    },
  },

  currentPhysicsPreset: 'balanced',
  physicsConfig: null,

  async render(container) {
    this.container = container;
    this.loadPersistedSettings();

    container.innerHTML = `
      <div class="graph-shell">
        <!-- Top Toolbar -->
        <header class="graph-toolbar">
          <div style="display:flex; align-items:center; gap:10px;">
            <button class="icon-button" id="btn-toggle-filters" title="Toggle Graph Filters" style="font-size:13px; font-weight:600; display:flex; align-items:center; gap:5px;">
              <span>☰</span> <span>Filters</span>
            </button>
            <div>
              <div class="eyebrow" style="margin:0;">Knowledge Map</div>
              <h2 style="font-size:17px; margin:0;">Graph</h2>
            </div>
          </div>

          <div class="graph-search">
            <span>⌕</span>
            <input id="graph-search-input" placeholder="Search and reveal any entity…" autocomplete="off">
            <div id="graph-search-results" class="graph-search-results"></div>
          </div>

          <div class="graph-controls">
            <!-- Saved Views -->
            <select class="compact-date" id="select-saved-views" title="Saved graph views" style="cursor:pointer;">
              <option value="default">Default View</option>
            </select>
            <button class="icon-button" id="btn-save-current-view" title="Save current view">💾</button>

            <!-- Clusters -->
            <select class="compact-date" id="select-cluster-mode" title="Cluster mode" style="cursor:pointer;">
              <option value="none">Clusters: None</option>
              <option value="type">By Type</option>
              <option value="component">By Component</option>
            </select>

            <!-- Label Mode -->
            <button class="icon-button ${this.activeLabelMode === 'important' ? 'active' : ''}" id="btn-label-mode" title="Label Mode: Important / All / None">
              Aa
            </button>

            <!-- Viewport Fit -->
            <button class="icon-button" id="btn-fit-graph" title="Fit visible graph to screen">⊙</button>

            <!-- Physics Simulation Toggle -->
            <button class="icon-button" id="btn-toggle-physics" title="Pause / Resume Physics Simulation">⏸️</button>

            <!-- Reset Layout -->
            <button class="icon-button" id="btn-reset-layout" title="Reset Graph Layout & Stabilize">↺</button>
          </div>
        </header>

        <!-- Canvas Stage -->
        <div class="graph-stage">
          <!-- Network Canvas -->
          <div id="vis-graph-container">
            <div id="graph-loading-indicator" class="graph-loading">
              <span></span> Resolving entity relationships…
            </div>
          </div>

          <!-- Dynamic HUD Summary -->
          <div id="graph-hud" class="graph-hud">
            <span>Mapping knowledge…</span>
          </div>

          <!-- Stabilizing Indicator -->
          <div id="graph-stabilizing-pill" class="graph-stabilizing-pill">
            <span style="width:6px; height:6px; border-radius:50%; background:#6b9fff; animation:spin 1s linear infinite;"></span>
            <span>Stabilizing layout…</span>
          </div>

          <!-- Collapsible Left Filters Panel -->
          <aside id="graph-filters-panel" class="graph-filters-panel ${this.filterPanelOpen ? '' : 'collapsed'}">
            <div class="filters-header">
              <h3>Graph Filters</h3>
              <button class="btn-close" id="btn-close-filters">×</button>
            </div>

            <!-- Minimum Connections -->
            <div class="filter-section">
              <div class="filter-header-row">
                <span class="panel-label" style="margin:0;">Min Connections</span>
                <span class="filter-badge-pill" id="badge-min-connections">2+ connections</span>
              </div>
              <div class="min-conn-buttons" id="min-conn-buttons">
                <button class="conn-btn" data-val="0">0</button>
                <button class="conn-btn" data-val="1">1+</button>
                <button class="conn-btn active" data-val="2">2+</button>
                <button class="conn-btn" data-val="3">3+</button>
                <button class="conn-btn" data-val="5">5+</button>
                <button class="conn-btn" data-val="10">10+</button>
              </div>
            </div>

            <!-- Text Filter -->
            <div class="filter-section">
              <span class="panel-label" style="margin:0;">Text Filter</span>
              <input type="text" class="form-control" id="graph-text-filter" placeholder="Filter names / summaries…" style="font-size:11.5px; padding:5px 8px;">
            </div>

            <!-- Temporal State -->
            <div class="filter-section">
              <span class="panel-label" style="margin:0;">Temporal Validity</span>
              <div class="segmented-control" id="temporal-segmented-control" style="font-size:11px;">
                <button class="segment active" data-state="active">Active</button>
                <button class="segment" data-state="historical">Historical</button>
                <button class="segment" data-state="all">All</button>
              </div>
              <div style="display:flex; align-items:center; gap:6px; margin-top:4px;">
                <span style="font-size:10px; color:var(--text-muted);">As Of:</span>
                <input type="date" class="compact-date" id="graph-as-of-date" style="flex:1;">
              </div>
            </div>

            <!-- Connectivity Toggles -->
            <div class="filter-section">
              <span class="panel-label" style="margin:0;">Connectivity</span>
              <label class="filter-checkbox-item">
                <label><input type="checkbox" id="toggle-hide-isolates" checked> Hide isolated entities</label>
              </label>
              <label class="filter-checkbox-item">
                <label><input type="checkbox" id="toggle-largest-component"> Largest component only</label>
              </label>
              <label class="filter-checkbox-item">
                <label><input type="checkbox" id="toggle-hide-literals"> Suppress literal nodes</label>
              </label>
              <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 6px;">
                <span style="font-size:11px; color:#8da0b8;">Focus Neighborhood:</span>
                <select class="compact-date" id="select-neighborhood-depth" style="font-size:10px;">
                  <option value="all">All</option>
                  <option value="1">1-hop</option>
                  <option value="2">2-hop</option>
                </select>
              </div>
            </div>

            <!-- Entity Types Multi-Select -->
            <div class="filter-section">
              <div class="filter-header-row">
                <span class="panel-label" style="margin:0;">Entity Types</span>
                <div style="display:flex; gap:6px;">
                  <button class="text-link" id="btn-select-all-types" style="font-size:10px;">All</button>
                  <span style="color:#4a596f;">·</span>
                  <button class="text-link" id="btn-clear-types" style="font-size:10px;">Clear</button>
                </div>
              </div>
              <div class="filter-checkbox-list" id="filter-type-list"></div>
            </div>

            <!-- Predicates Multi-Select -->
            <div class="filter-section">
              <div class="filter-header-row">
                <span class="panel-label" style="margin:0;">Predicates</span>
                <div style="display:flex; gap:6px;">
                  <button class="text-link" id="btn-select-all-predicates" style="font-size:10px;">All</button>
                  <span style="color:#4a596f;">·</span>
                  <button class="text-link" id="btn-clear-predicates" style="font-size:10px;">Clear</button>
                </div>
              </div>
              <div class="filter-checkbox-list" id="filter-predicate-list"></div>
            </div>

            <!-- Advanced Physics Collapsible -->
            <div class="filter-section" style="border-top:1px solid var(--border-subtle); padding-top:10px;">
              <div class="filter-header-row">
                <span class="panel-label" style="margin:0;">Force Physics</span>
                <select class="compact-date" id="select-physics-preset" style="font-size:10px;">
                  <option value="balanced">Balanced</option>
                  <option value="loose">Loose</option>
                  <option value="compact">Compact</option>
                  <option value="hierarchical">Hierarchical</option>
                  <option value="manual">Manual</option>
                </select>
              </div>
              <div class="physics-controls" id="physics-controls-body">
                <div class="physics-slider-row">
                  <label>Repulsion <span id="val-grav-const">-72</span></label>
                  <input type="range" id="slider-grav-const" min="-180" max="-20" value="-72">
                </div>
                <div class="physics-slider-row">
                  <label>Spring Length <span id="val-spring-length">128</span></label>
                  <input type="range" id="slider-spring-length" min="50" max="260" value="128">
                </div>
                <div class="physics-slider-row">
                  <label>Avoid Overlap <span id="val-avoid-overlap">0.65</span></label>
                  <input type="range" id="slider-avoid-overlap" min="0" max="1" step="0.05" value="0.65">
                </div>
                <div style="display:flex; justify-content:space-between; margin-top:4px;">
                  <button class="text-link" id="btn-reset-physics" style="font-size:10px;">Reset Defaults</button>
                  <button class="text-link" id="btn-rerun-physics" style="font-size:10px; color:#6b9fff;">Re-run Physics</button>
                </div>
              </div>
            </div>
          </aside>

          <!-- Type Legend -->
          <div class="graph-legend">
            <span><i class="legend-infra"></i>INFRA</span>
            <span><i class="legend-model"></i>MODEL</span>
            <span><i class="legend-agent"></i>AGENT</span>
            <span><i class="legend-concept"></i>CONCEPT</span>
          </div>

          <!-- Stats / Metadata -->
          <div class="graph-stats" id="graph-stats"></div>

          <!-- Node Evidence Inspector Drawer -->
          <aside id="node-inspector-drawer" class="graph-inspector collapsed">
            <button class="icon-button graph-inspector-close" id="close-node-inspector">×</button>
            <div id="node-details-content"></div>
          </aside>

          <!-- Relationship Evidence Inspector Drawer -->
          <aside id="relationship-inspector-drawer" class="graph-inspector collapsed">
            <button class="icon-button graph-inspector-close" id="close-relationship-inspector">×</button>
            <div id="relationship-details-content"></div>
          </aside>
        </div>
      </div>
    `;

    this.bindEvents(container);
    await this.loadGraphData();
  },

  loadPersistedSettings() {
    try {
      const savedPhys = localStorage.getItem('mbrain_graph_physics_config');
      if (savedPhys) {
        this.physicsConfig = JSON.parse(savedPhys);
      } else {
        this.physicsConfig = { ...this.physicsPresets.balanced };
      }
      const savedPreset = localStorage.getItem('mbrain_graph_physics_preset');
      if (savedPreset && this.physicsPresets[savedPreset]) {
        this.currentPhysicsPreset = savedPreset;
      }
    } catch (e) {
      this.physicsConfig = { ...this.physicsPresets.balanced };
    }
  },

  savePersistedSettings() {
    try {
      localStorage.setItem('mbrain_graph_physics_config', JSON.stringify(this.physicsConfig));
      localStorage.setItem('mbrain_graph_physics_preset', this.currentPhysicsPreset);
    } catch (e) {}
  },

  bindEvents(container) {
    // Toggle filter drawer
    const toggleFiltersBtn = container.querySelector('#btn-toggle-filters');
    const closeFiltersBtn = container.querySelector('#btn-close-filters');
    const filterPanel = container.querySelector('#graph-filters-panel');

    const togglePanel = () => {
      this.filterPanelOpen = !this.filterPanelOpen;
      filterPanel.classList.toggle('collapsed', !this.filterPanelOpen);
      toggleFiltersBtn.classList.toggle('active', this.filterPanelOpen);
    };
    toggleFiltersBtn.addEventListener('click', togglePanel);
    closeFiltersBtn.addEventListener('click', togglePanel);

    // Min connections buttons
    container.querySelectorAll('.conn-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        container.querySelectorAll('.conn-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        const val = parseInt(btn.dataset.val, 10);
        this.filterState.minConnections = val;
        container.querySelector('#badge-min-connections').textContent = `${val}+ connections`;
        this.applyFilterAndRefresh();
      });
    });

    // Text filter
    let textTimeout = null;
    const textInput = container.querySelector('#graph-text-filter');
    textInput.addEventListener('input', (e) => {
      clearTimeout(textTimeout);
      textTimeout = setTimeout(() => {
        this.filterState.textQuery = e.target.value.trim();
        this.applyFilterAndRefresh();
      }, 180);
    });

    // Temporal segmented control
    container.querySelectorAll('#temporal-segmented-control .segment').forEach((btn) => {
      btn.addEventListener('click', () => {
        container.querySelectorAll('#temporal-segmented-control .segment').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        this.filterState.temporalState = btn.dataset.state;
        this.applyFilterAndRefresh();
      });
    });

    // As of date
    container.querySelector('#graph-as-of-date').addEventListener('change', (e) => {
      this.filterState.asOfDate = e.target.value || null;
      this.applyFilterAndRefresh();
    });

    // Connectivity toggles
    container.querySelector('#toggle-hide-isolates').addEventListener('change', (e) => {
      this.filterState.hideIsolates = e.target.checked;
      this.applyFilterAndRefresh();
    });
    container.querySelector('#toggle-largest-component').addEventListener('change', (e) => {
      this.filterState.largestComponentOnly = e.target.checked;
      this.applyFilterAndRefresh();
    });
    container.querySelector('#toggle-hide-literals').addEventListener('change', (e) => {
      this.filterState.hideLiteralNodes = e.target.checked;
      this.applyFilterAndRefresh();
    });
    container.querySelector('#select-neighborhood-depth').addEventListener('change', (e) => {
      this.filterState.neighborhoodDepth = e.target.value;
      this.applyFilterAndRefresh();
    });

    // Entity types actions
    container.querySelector('#btn-select-all-types').addEventListener('click', () => {
      container.querySelectorAll('#filter-type-list input').forEach((chk) => { chk.checked = true; });
      this.filterState.selectedTypes = [];
      this.applyFilterAndRefresh();
    });
    container.querySelector('#btn-clear-types').addEventListener('click', () => {
      container.querySelectorAll('#filter-type-list input').forEach((chk) => { chk.checked = false; });
      this.filterState.selectedTypes = ['__NONE__'];
      this.applyFilterAndRefresh();
    });

    // Predicates actions
    container.querySelector('#btn-select-all-predicates').addEventListener('click', () => {
      container.querySelectorAll('#filter-predicate-list input').forEach((chk) => { chk.checked = true; });
      this.filterState.selectedPredicates = [];
      this.applyFilterAndRefresh();
    });
    container.querySelector('#btn-clear-predicates').addEventListener('click', () => {
      container.querySelectorAll('#filter-predicate-list input').forEach((chk) => { chk.checked = false; });
      this.filterState.selectedPredicates = ['__NONE__'];
      this.applyFilterAndRefresh();
    });

    // Physics Presets
    const presetSelect = container.querySelector('#select-physics-preset');
    presetSelect.value = this.currentPhysicsPreset;
    presetSelect.addEventListener('change', (e) => {
      const p = e.target.value;
      this.currentPhysicsPreset = p;
      if (this.physicsPresets[p]) {
        this.physicsConfig = { ...this.physicsPresets[p] };
        this.syncPhysicsSliders();
        this.updateNetworkPhysics();
        this.savePersistedSettings();
      }
    });

    // Physics sliders
    const gravSlider = container.querySelector('#slider-grav-const');
    const springSlider = container.querySelector('#slider-spring-length');
    const overlapSlider = container.querySelector('#slider-avoid-overlap');

    const onPhysicsChange = () => {
      presetSelect.value = 'manual';
      this.currentPhysicsPreset = 'manual';
      this.physicsConfig.gravitationalConstant = parseFloat(gravSlider.value);
      this.physicsConfig.springLength = parseFloat(springSlider.value);
      this.physicsConfig.avoidOverlap = parseFloat(overlapSlider.value);

      container.querySelector('#val-grav-const').textContent = gravSlider.value;
      container.querySelector('#val-spring-length').textContent = springSlider.value;
      container.querySelector('#val-avoid-overlap').textContent = overlapSlider.value;

      this.updateNetworkPhysics();
      this.savePersistedSettings();
    };

    gravSlider.addEventListener('input', onPhysicsChange);
    springSlider.addEventListener('input', onPhysicsChange);
    overlapSlider.addEventListener('input', onPhysicsChange);

    container.querySelector('#btn-reset-physics').addEventListener('click', () => {
      this.currentPhysicsPreset = 'balanced';
      presetSelect.value = 'balanced';
      this.physicsConfig = { ...this.physicsPresets.balanced };
      this.syncPhysicsSliders();
      this.updateNetworkPhysics();
      this.savePersistedSettings();
    });

    container.querySelector('#btn-rerun-physics').addEventListener('click', () => {
      if (this.network) {
        this.showStabilizing(true);
        this.physicsRunning = true;
        const toggleBtn = container.querySelector('#btn-toggle-physics');
        if (toggleBtn) {
          toggleBtn.textContent = '⏸️';
          toggleBtn.title = 'Pause Physics Simulation';
        }
        this.network.setOptions({ physics: { enabled: true } });
      }
    });

    // Toolbar controls
    container.querySelector('#btn-fit-graph').addEventListener('click', () => {
      if (this.network) this.network.fit({ animation: { duration: 450, easingFunction: 'easeInOutQuad' } });
    });

    const togglePhysicsBtn = container.querySelector('#btn-toggle-physics');
    if (togglePhysicsBtn) {
      togglePhysicsBtn.addEventListener('click', () => {
        if (!this.network) return;
        this.physicsRunning = !(this.physicsRunning ?? false);
        this.network.setOptions({ physics: { enabled: this.physicsRunning } });
        togglePhysicsBtn.textContent = this.physicsRunning ? '⏸️' : '▶️';
        togglePhysicsBtn.title = this.physicsRunning ? 'Pause Physics Simulation' : 'Resume Physics Simulation';
      });
    }

    const resetLayoutBtn = container.querySelector('#btn-reset-layout');
    if (resetLayoutBtn) {
      resetLayoutBtn.addEventListener('click', () => {
        if (!this.network) return;
        this.showStabilizing(true);
        this.physicsRunning = true;
        if (togglePhysicsBtn) {
          togglePhysicsBtn.textContent = '⏸️';
          togglePhysicsBtn.title = 'Pause Physics Simulation';
        }
        this.network.setOptions({ physics: { enabled: true } });
        this.network.stabilize();
        this.network.fit({ animation: { duration: 450, easingFunction: 'easeInOutQuad' } });
      });
    }

    const labelBtn = container.querySelector('#btn-label-mode');
    labelBtn.addEventListener('click', () => {
      const modes = ['important', 'all', 'none'];
      const nextIdx = (modes.indexOf(this.activeLabelMode) + 1) % modes.length;
      this.activeLabelMode = modes[nextIdx];
      labelBtn.textContent = this.activeLabelMode === 'important' ? 'Aa' : this.activeLabelMode === 'all' ? 'AA' : '—';
      labelBtn.title = `Label Mode: ${this.activeLabelMode.toUpperCase()}`;
      this.updateLabelVisibility();
    });

    // Saved views
    this.renderSavedViewsDropdown();
    container.querySelector('#btn-save-current-view').addEventListener('click', () => this.promptSaveView());
    container.querySelector('#select-saved-views').addEventListener('change', (e) => this.applySavedView(e.target.value));

    // Clustering
    container.querySelector('#select-cluster-mode').addEventListener('change', (e) => {
      this.activeClusterMode = e.target.value;
      this.applyClustering();
    });

    // Close inspectors
    container.querySelector('#close-node-inspector').addEventListener('click', () => this.closeInspectors());
    container.querySelector('#close-relationship-inspector').addEventListener('click', () => this.closeInspectors());

    // Search input
    const searchInput = container.querySelector('#graph-search-input');
    searchInput.addEventListener('input', () => this.renderSearchResults(searchInput.value));
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        searchInput.value = '';
        this.renderSearchResults('');
        this.closeInspectors();
      }
    });
  },

  syncPhysicsSliders() {
    const c = this.physicsConfig || this.physicsPresets.balanced;
    const g = document.getElementById('slider-grav-const');
    const s = document.getElementById('slider-spring-length');
    const o = document.getElementById('slider-avoid-overlap');
    if (g && s && o) {
      g.value = c.gravitationalConstant;
      s.value = c.springLength;
      o.value = c.avoidOverlap;
      document.getElementById('val-grav-const').textContent = c.gravitationalConstant;
      document.getElementById('val-spring-length').textContent = c.springLength;
      document.getElementById('val-avoid-overlap').textContent = c.avoidOverlap;
    }
  },

  async loadGraphData() {
    const stage = document.getElementById('vis-graph-container');
    const loading = document.getElementById('graph-loading-indicator');
    if (!stage) return;
    if (loading) loading.style.display = 'flex';

    try {
      this.rawGraph = await window.gms.getGraph({ include_expired: true });
      this.populateFacets();
      this.syncPhysicsSliders();
      this.applyFilterAndRefresh(true);
    } catch (err) {
      stage.innerHTML = `<div class="error-state">Failed to load graph data<br><small>${this.escapeHtml(err.message)}</small></div>`;
    } finally {
      if (loading) loading.style.display = 'none';
    }
  },

  populateFacets() {
    const typeList = document.getElementById('filter-type-list');
    const predList = document.getElementById('filter-predicate-list');
    if (!this.rawGraph || !typeList || !predList) return;

    const types = this.rawGraph.facets?.types || {};
    const preds = this.rawGraph.facets?.predicates || {};

    // Entity types
    typeList.innerHTML = Object.entries(types)
      .sort((a, b) => b[1] - a[1])
      .map(([t, count]) => `
        <div class="filter-checkbox-item">
          <label><input type="checkbox" class="chk-type" value="${this.escapeHtml(t)}" checked> ${this.escapeHtml(t)}</label>
          <b>${count}</b>
        </div>
      `).join('');

    typeList.querySelectorAll('.chk-type').forEach((chk) => {
      chk.addEventListener('change', () => {
        const checked = Array.from(typeList.querySelectorAll('.chk-type:checked')).map((c) => c.value);
        this.filterState.selectedTypes = checked.length === Object.keys(types).length ? [] : checked;
        this.applyFilterAndRefresh();
      });
    });

    // Predicates
    predList.innerHTML = Object.entries(preds)
      .sort((a, b) => b[1] - a[1])
      .map(([p, count]) => `
        <div class="filter-checkbox-item">
          <label><input type="checkbox" class="chk-pred" value="${this.escapeHtml(p)}" checked> ${this.escapeHtml(p)}</label>
          <b>${count}</b>
        </div>
      `).join('');

    predList.querySelectorAll('.chk-pred').forEach((chk) => {
      chk.addEventListener('change', () => {
        const checked = Array.from(predList.querySelectorAll('.chk-pred:checked')).map((c) => c.value);
        this.filterState.selectedPredicates = checked.length === Object.keys(preds).length ? [] : checked;
        this.applyFilterAndRefresh();
      });
    });
  },

  applyFilterAndRefresh(initial = false) {
    if (!this.rawGraph || typeof window.GraphFilter === 'undefined') return;

    // Run pure deterministic filtering pipeline
    this.filteredGraph = window.GraphFilter.filterGraph(this.rawGraph, this.filterState);
    this.updateHUD(this.filteredGraph.metadata);

    const colors = {
      INFRA: ['#44c7b6', '#163e3c'],
      TICKER: ['#64d37c', '#193d27'],
      AGENT: ['#f0b85a', '#493617'],
      MODEL: ['#b38cff', '#35234e'],
      POLICY: ['#f08362', '#4b271f'],
      CONCEPT: ['#6b9fff', '#1d3156'],
    };

    // Find maximum visible degree for nonlinear scaling
    const maxDegree = Math.max(1, ...this.filteredGraph.nodes.map((n) => n.visibleDegree || 0));

    const visNodeList = this.filteredGraph.nodes.map((node) => {
      const normType = String(node.type || 'CONCEPT').toUpperCase();
      const colorPair = colors[normType] || colors.CONCEPT;
      const deg = node.visibleDegree || 0;

      // Nonlinear radius scaling: R = 9 + 18 * sqrt(deg / maxDegree)
      const radius = Math.min(32, Math.max(9, Math.round(9 + 18 * Math.sqrt(deg / maxDegree))));
      const displayLabel = node.label.length > 30 ? `${node.label.slice(0, 27)}…` : node.label;

      return {
        id: node.id,
        label: displayLabel,
        fullLabel: node.label,
        type: normType,
        size: radius,
        shape: 'dot',
        borderWidth: node.revealed ? 2.5 : 1,
        color: {
          background: node.revealed ? '#ffffff' : colorPair[0],
          border: node.revealed ? '#6b9fff' : colorPair[0],
          highlight: { background: '#ffffff', border: colorPair[0] },
          hover: { background: '#dfe8ff', border: colorPair[0] },
        },
        font: {
          color: '#d9e2f1',
          size: deg >= 2 ? 11 : 9,
          face: 'system-ui, -apple-system, BlinkMacSystemFont',
          vadjust: radius + 7,
          strokeWidth: 3,
          strokeColor: '#0a0e15',
        },
        raw: node,
      };
    });

    const visEdgeList = this.filteredGraph.edges.map((edge) => {
      const isActive = Boolean(edge.active);
      return {
        id: edge.id,
        from: edge.from,
        to: edge.to,
        label: edge.label,
        title: `${edge.label} · ${isActive ? 'Active' : 'Historical'}`,
        width: isActive ? 1.0 : 0.7,
        dashes: !isActive,
        color: isActive
          ? { color: 'rgba(123, 145, 178, 0.4)', highlight: '#8eb9ff', hover: '#719de0' }
          : { color: 'rgba(240, 112, 98, 0.35)', highlight: '#f07062', hover: '#f07062' },
        smooth: { enabled: true, type: 'continuous', roundness: 0.2 },
        arrows: { to: { enabled: true, scaleFactor: 0.35 } },
        font: {
          color: '#8190a8',
          size: 9,
          strokeWidth: 3,
          strokeColor: '#0a0e15',
          align: 'middle',
        },
        raw: edge,
      };
    });

    if (initial || !this.network) {
      this.initVisNetwork(visNodeList, visEdgeList);
    } else {
      this.visNodes.clear();
      this.visNodes.add(visNodeList);
      this.visEdges.clear();
      this.visEdges.add(visEdgeList);
      this.updateLabelVisibility();
      this.showStabilizing(true);
      this.network.setOptions({ physics: { enabled: true } });
    }

    if (this.pendingFocus) {
      const target = visNodeList.find((n) => n.id === this.pendingFocus.id || n.fullLabel.toLowerCase() === String(this.pendingFocus.label).toLowerCase());
      this.pendingFocus = null;
      if (target) {
        setTimeout(() => this.focusNode(target.id, true), 250);
      }
    }
  },

  initVisNetwork(nodeList, edgeList) {
    const stage = document.getElementById('vis-graph-container');
    if (!stage || typeof vis === 'undefined') return;

    this.visNodes = new vis.DataSet(nodeList);
    this.visEdges = new vis.DataSet(edgeList);

    const phys = this.physicsConfig || this.physicsPresets.balanced;

    const options = {
      autoResize: true,
      nodes: { scaling: { min: 9, max: 32, label: { enabled: false } } },
      edges: { selectionWidth: 2.5, hoverWidth: 1.5 },
      physics: {
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: phys.gravitationalConstant,
          centralGravity: phys.centralGravity,
          springLength: phys.springLength,
          springConstant: phys.springConstant,
          damping: phys.damping,
          avoidOverlap: phys.avoidOverlap,
        },
        stabilization: {
          enabled: true,
          iterations: phys.stabilizationIterations || 280,
          updateInterval: 25,
          fit: true,
        },
        maxVelocity: phys.maxVelocity || 28,
        minVelocity: 0.35,
      },
      interaction: {
        hover: true,
        tooltipDelay: 160,
        navigationButtons: false,
        keyboard: { enabled: true },
        multiselect: true,
        zoomView: true,
        dragView: true,
      },
      layout: { improvedLayout: true, randomSeed: 19 },
    };

    this.showStabilizing(true);
    this.network = new vis.Network(stage, { nodes: this.visNodes, edges: this.visEdges }, options);

    // Stop physics automatically upon stabilization
    const onStabilized = () => {
      this.network.setOptions({ physics: { enabled: false } });
      this.showStabilizing(false);
      this.physicsRunning = false;
      const toggleBtn = this.container?.querySelector('#btn-toggle-physics');
      if (toggleBtn) {
        toggleBtn.textContent = '▶️';
        toggleBtn.title = 'Resume Physics Simulation';
      }
    };
    this.network.on('stabilizationIterationsDone', onStabilized);
    this.network.on('stabilized', onStabilized);

    // Click handler for nodes & edges
    this.network.on('click', (params) => {
      if (params.nodes && params.nodes.length > 0) {
        this.focusNode(params.nodes[0]);
      } else if (params.edges && params.edges.length > 0) {
        this.focusEdge(params.edges[0]);
      } else {
        this.closeInspectors();
      }
    });

    this.network.on('doubleClick', (params) => {
      if (params.nodes && params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        if (this.network.isCluster && this.network.isCluster(nodeId)) {
          this.network.openCluster(nodeId);
        } else {
          this.focusNode(nodeId, true);
        }
      }
    });

    setTimeout(() => this.showStabilizing(false), 2000);
  },

  updateNetworkPhysics() {
    if (!this.network) return;
    const phys = this.physicsConfig || this.physicsPresets.balanced;
    this.showStabilizing(true);
    this.physicsRunning = true;
    const toggleBtn = this.container?.querySelector('#btn-toggle-physics');
    if (toggleBtn) {
      toggleBtn.textContent = '⏸️';
      toggleBtn.title = 'Pause Physics Simulation';
    }
    this.network.setOptions({
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: phys.gravitationalConstant,
          centralGravity: phys.centralGravity,
          springLength: phys.springLength,
          springConstant: phys.springConstant,
          damping: phys.damping,
          avoidOverlap: phys.avoidOverlap,
        },
      },
    });
  },

  showStabilizing(show) {
    const pill = document.getElementById('graph-stabilizing-pill');
    if (pill) pill.classList.toggle('active', Boolean(show));
  },

  updateHUD(meta) {
    const hud = document.getElementById('graph-hud');
    const stats = document.getElementById('graph-stats');
    if (!hud || !meta) return;

    const hiddenTotal = (meta.totalNodes - meta.visibleNodes);
    hud.innerHTML = `
      <span>Showing <strong>${meta.visibleNodes}</strong> of ${meta.totalNodes} entities</span>
      <span style="color:#425269;">·</span>
      <span><strong>${meta.visibleEdges}</strong> of ${meta.totalEdges} relationships</span>
      ${hiddenTotal > 0 ? `<span style="color:#e6aa55; margin-left:4px;">(${hiddenTotal} hidden)</span>` : ''}
    `;

    if (stats) {
      stats.textContent = `${meta.visibleNodes} visible · ${meta.visibleEdges} relationships · Min connections: ${this.filterState.minConnections}+`;
    }
  },

  updateLabelVisibility() {
    if (!this.network || !this.visNodes || !this.visEdges) return;
    const mode = this.activeLabelMode;

    const updates = this.visNodes.get().map((node) => {
      let show = true;
      if (mode === 'none') show = false;
      else if (mode === 'important') show = (node.raw?.visibleDegree >= 2) || Boolean(node.raw?.revealed);
      return { id: node.id, font: { size: show ? (node.size > 18 ? 11 : 9) : 0 } };
    });
    this.visNodes.update(updates);

    this.visEdges.update(
      this.visEdges.get().map((e) => ({
        id: e.id,
        font: { size: mode === 'all' ? 9 : 0 },
      }))
    );
  },

  renderSearchResults(query) {
    const box = document.getElementById('graph-search-results');
    if (!box) return;
    const q = query.trim().toLowerCase();
    if (!q) {
      box.classList.remove('visible');
      box.innerHTML = '';
      return;
    }

    const allNodes = this.rawGraph?.nodes || [];
    const matches = allNodes
      .filter((n) => n.label.toLowerCase().includes(q) || String(n.summary || '').toLowerCase().includes(q))
      .slice(0, 8);

    box.innerHTML = matches.length
      ? matches.map((n) => `
        <button data-id="${this.escapeHtml(n.id)}">
          <i style="background:#6b9fff"></i>
          <span>${this.escapeHtml(n.label)} <small>${this.escapeHtml(n.type)} · ${n.active_degree || 0} active</small></span>
        </button>
      `).join('')
      : '<div class="no-search-results">No matching entities</div>';

    box.classList.add('visible');
    box.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.getElementById('graph-search-input').value = '';
        box.classList.remove('visible');
        this.revealAndFocusNode(btn.dataset.id);
      });
    });
  },

  revealAndFocusNode(nodeId) {
    const idStr = String(nodeId);
    if (!this.filterState.revealedNodeIds.includes(idStr)) {
      this.filterState.revealedNodeIds.push(idStr);
    }
    this.filterState.focusNodeId = idStr;
    this.applyFilterAndRefresh();
    setTimeout(() => this.focusNode(idStr, true), 150);
  },

  async focusNode(nodeId, isolate = false) {
    if (!this.network || !this.visNodes) return;
    const node = this.visNodes.get(nodeId);
    if (!node) return;

    this.closeInspectors();
    const connected = this.network.getConnectedNodes(node.id);
    this.network.selectNodes([node.id]);

    this.network.focus(node.id, {
      scale: isolate ? 1.35 : 1.1,
      animation: { duration: 500, easingFunction: 'easeInOutQuad' },
    });

    if (isolate) {
      this.network.setSelection(
        { nodes: [node.id, ...connected], edges: this.network.getConnectedEdges(node.id) },
        { unselectAll: true, highlightEdges: true }
      );
    }

    await this.showNodeInspector(node.raw);
  },

  async focusEdge(edgeId) {
    if (!this.network || !this.visEdges) return;
    const edge = this.visEdges.get(edgeId);
    if (!edge) return;

    this.closeInspectors();
    this.network.selectEdges([edge.id]);
    await this.showRelationshipInspector(edge.raw);
  },

  async showNodeInspector(node) {
    const drawer = document.getElementById('node-inspector-drawer');
    const content = document.getElementById('node-details-content');
    if (!drawer || !content) return;

    drawer.classList.remove('collapsed');
    content.innerHTML = `
      <div class="entity-kicker">${this.escapeHtml(node.type)}</div>
      <h3>${this.escapeHtml(node.label)}</h3>
      <p class="entity-summary">${this.escapeHtml(node.summary || 'No summary recorded.')}</p>
      <div class="entity-metrics">
        <div><strong>${node.visibleDegree || 0}</strong><span>visible links</span></div>
        <div><strong>${node.active_degree || 0}</strong><span>active</span></div>
      </div>
      <div style="font-size:11px; color:var(--text-muted); padding:10px 0;">Loading supporting evidence…</div>
    `;

    try {
      const evidence = await window.gms.getEntityEvidence(node.id);
      const claims = evidence.claims || [];
      const rels = evidence.relationships || [];

      content.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <div>
            <div class="entity-kicker">${this.escapeHtml(evidence.type || node.type)}</div>
            <h3>${this.escapeHtml(evidence.name || node.label)}</h3>
          </div>
          <span class="badge ${evidence.quality_status === 'well_supported' ? 'quality-good' : 'quality-warn'}" style="background:#172232; font-size:10px;">
            ${this.escapeHtml(evidence.quality_status || 'Active')}
          </span>
        </div>

        <p class="entity-summary">${this.escapeHtml(evidence.summary || node.summary || 'No summary recorded.')}</p>

        <div class="entity-metrics">
          <div><strong>${evidence.evidence_count || 0}</strong><span>evidence refs</span></div>
          <div><strong>${evidence.active_relationships_count || 0}</strong><span>active rels</span></div>
        </div>

        <!-- Relationships -->
        <div class="panel-label">Relationships (${rels.length})</div>
        <div class="connection-list">
          ${rels.length ? rels.slice(0, 10).map((r) => `
            <button data-id="${this.escapeHtml(r.other_entity.id)}" data-rel="${this.escapeHtml(r.relationship_id)}">
              <span>${r.direction === 'outgoing' ? '→' : '←'} ${this.escapeHtml(r.predicate)}</span>
              <strong>${this.escapeHtml(r.other_entity.name)}</strong>
            </button>
          `).join('') : '<span class="muted" style="font-size:11px;">No relationships recorded.</span>'}
        </div>

        <!-- Supporting Claims -->
        <div class="panel-label" style="margin-top:16px;">Supporting Claims (${claims.length})</div>
        ${claims.length ? claims.slice(0, 4).map((c) => `
          <div class="evidence-claim-box">
            <header>
              <strong>${this.escapeHtml(c.key)}</strong>
              <span>${this.escapeHtml(c.agent || 'system')}</span>
            </header>
            <code>${this.escapeHtml(typeof c.value === 'object' ? JSON.stringify(c.value) : String(c.value))}</code>
          </div>
        `).join('') : '<span class="muted" style="font-size:11px;">No direct claims linked.</span>'}

        <!-- Actions -->
        <div class="inspector-actions stacked" style="margin-top:18px;">
          <button class="btn-primary" id="btn-inspect-memories">Find related memories</button>
          <button class="btn-secondary" id="btn-inspect-entity">Open in Entities</button>
          <button class="btn-secondary" id="btn-focus-1hop">Focus 1-hop neighbors</button>
        </div>
      `;

      content.querySelectorAll('.connection-list button').forEach((btn) => {
        btn.addEventListener('click', () => this.revealAndFocusNode(btn.dataset.id));
      });

      content.querySelector('#btn-inspect-memories')?.addEventListener('click', () => {
        window.App.exploreRelated(node.label);
      });
      content.querySelector('#btn-inspect-entity')?.addEventListener('click', () => {
        window.App.openEntity({ id: node.id, name: node.label });
      });
      content.querySelector('#btn-focus-1hop')?.addEventListener('click', () => {
        this.filterState.focusNodeId = String(node.id);
        this.filterState.neighborhoodDepth = 1;
        document.getElementById('select-neighborhood-depth').value = '1';
        this.applyFilterAndRefresh();
      });
    } catch (e) {}
  },

  async showRelationshipInspector(edge) {
    const drawer = document.getElementById('relationship-inspector-drawer');
    const content = document.getElementById('relationship-details-content');
    if (!drawer || !content) return;

    drawer.classList.remove('collapsed');
    content.innerHTML = `
      <div class="entity-kicker">Relationship</div>
      <div class="relationship-hero">
        <div class="rel-node-chip">
          <strong>#${this.escapeHtml(edge.from)}</strong>
          <span>Subject</span>
        </div>
        <div class="rel-pred-badge">${this.escapeHtml(edge.label)}</div>
        <div class="rel-node-chip">
          <strong>#${this.escapeHtml(edge.to)}</strong>
          <span>Object</span>
        </div>
      </div>
      <div style="font-size:11px; color:var(--text-muted); padding:10px 0;">Loading relationship evidence…</div>
    `;

    try {
      const relEv = await window.gms.getRelationshipEvidence(edge.id);
      const timeline = relEv.timeline || [];
      const claim = relEv.claim;

      content.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <div class="entity-kicker">Relationship Evidence</div>
          <span class="badge ${relEv.active ? 'quality-good' : 'quality-warn'}" style="background:#172232; font-size:10px;">
            ${relEv.active ? 'Active' : 'Historical'}
          </span>
        </div>

        <div class="relationship-hero">
          <div class="rel-node-chip">
            <strong>${this.escapeHtml(relEv.subject?.name || edge.from)}</strong>
            <span>${this.escapeHtml(relEv.subject?.type || 'Subject')}</span>
          </div>
          <div class="rel-pred-badge">${this.escapeHtml(relEv.predicate || edge.label)}</div>
          <div class="rel-node-chip">
            <strong>${this.escapeHtml(relEv.object?.name || edge.to)}</strong>
            <span>${this.escapeHtml(relEv.object?.type || 'Object')}</span>
          </div>
        </div>

        <div class="inspector-meta" style="margin-bottom:14px;">
          <div>
            <span>Valid From</span>
            <strong>${this.escapeHtml(relEv.valid_from ? relEv.valid_from.split('T')[0] : 'genesis')}</strong>
          </div>
          <div>
            <span>Valid To</span>
            <strong>${this.escapeHtml(relEv.valid_to ? relEv.valid_to.split('T')[0] : 'Current (Active)')}</strong>
          </div>
        </div>

        <!-- Supporting Claim -->
        <div class="panel-label">Supporting Claim & Provenance</div>
        ${claim ? `
          <div class="evidence-claim-box">
            <header>
              <strong>${this.escapeHtml(claim.key)}</strong>
              <span>Agent: ${this.escapeHtml(claim.agent || 'system')}</span>
            </header>
            <code>${this.escapeHtml(typeof claim.value === 'object' ? JSON.stringify(claim.value) : String(claim.value))}</code>
          </div>
        ` : '<span class="muted" style="font-size:11px;">No direct source claim linked.</span>'}

        <!-- Supersession Timeline -->
        <div class="panel-label" style="margin-top:16px;">Supersession Timeline (${timeline.length})</div>
        <div style="margin-top:6px;">
          ${timeline.length ? timeline.map((t) => `
            <div class="timeline-item ${t.active ? 'active' : 'historical'}">
              <div style="display:flex; justify-content:space-between; font-weight:600;">
                <span>${this.escapeHtml(t.predicate)} → ${this.escapeHtml(t.target)}</span>
                <span style="font-size:9.5px; color:${t.active ? 'var(--accent-green)' : 'var(--accent-amber)'};">${t.active ? 'ACTIVE' : 'SUPERSEDED'}</span>
              </div>
              <div style="font-size:9.5px; color:var(--text-muted);">
                ${this.escapeHtml(t.valid_from ? t.valid_from.split('T')[0] : '')} – ${this.escapeHtml(t.valid_to ? t.valid_to.split('T')[0] : 'present')}
              </div>
            </div>
          `).join('') : '<span class="muted" style="font-size:11px;">No prior revisions found.</span>'}
        </div>

        <div class="inspector-actions stacked" style="margin-top:18px;">
          <button class="btn-primary" id="btn-rel-jump-subject">Focus ${this.escapeHtml(relEv.subject?.name || 'Subject')}</button>
          <button class="btn-secondary" id="btn-rel-jump-object">Focus ${this.escapeHtml(relEv.object?.name || 'Object')}</button>
        </div>
      `;

      content.querySelector('#btn-rel-jump-subject')?.addEventListener('click', () => {
        if (relEv.subject?.id) this.revealAndFocusNode(relEv.subject.id);
      });
      content.querySelector('#btn-rel-jump-object')?.addEventListener('click', () => {
        if (relEv.object?.id) this.revealAndFocusNode(relEv.object.id);
      });
    } catch (e) {}
  },

  closeInspectors() {
    document.getElementById('node-inspector-drawer')?.classList.add('collapsed');
    document.getElementById('relationship-inspector-drawer')?.classList.add('collapsed');
    if (this.network) this.network.unselectAll();
  },

  // Saved Views implementation
  renderSavedViewsDropdown() {
    const sel = document.getElementById('select-saved-views');
    if (!sel) return;
    let saved = [];
    try {
      saved = JSON.parse(localStorage.getItem('mbrain_saved_graph_views') || '[]');
    } catch (e) {}

    sel.innerHTML = '<option value="default">Default View</option>' +
      saved.map((v, i) => `<option value="${i}">${this.escapeHtml(v.name)}</option>`).join('');
  },

  promptSaveView() {
    const name = prompt('Name for this saved graph view:');
    if (!name || !name.trim()) return;

    let saved = [];
    try {
      saved = JSON.parse(localStorage.getItem('mbrain_saved_graph_views') || '[]');
    } catch (e) {}

    saved.push({
      name: name.trim(),
      filterState: { ...this.filterState },
      physicsPreset: this.currentPhysicsPreset,
      labelMode: this.activeLabelMode,
      clusterMode: this.activeClusterMode,
    });

    localStorage.setItem('mbrain_saved_graph_views', JSON.stringify(saved));
    this.renderSavedViewsDropdown();
    window.App?.showToast(`Saved view "${name.trim()}"`, 'success');
  },

  applySavedView(val) {
    if (val === 'default') {
      this.filterState = {
        minConnections: 2,
        temporalState: 'active',
        asOfDate: null,
        selectedTypes: [],
        selectedPredicates: [],
        hideIsolates: true,
        largestComponentOnly: false,
        neighborhoodDepth: 'all',
        focusNodeId: null,
        revealedNodeIds: [],
        textQuery: '',
        hideLiteralNodes: false,
      };
      this.currentPhysicsPreset = 'balanced';
      this.activeLabelMode = 'important';
      this.activeClusterMode = 'none';
    } else {
      let saved = [];
      try {
        saved = JSON.parse(localStorage.getItem('mbrain_saved_graph_views') || '[]');
      } catch (e) {}
      const v = saved[parseInt(val, 10)];
      if (v) {
        this.filterState = { ...v.filterState };
        this.currentPhysicsPreset = v.physicsPreset || 'balanced';
        this.activeLabelMode = v.labelMode || 'important';
        this.activeClusterMode = v.clusterMode || 'none';
      }
    }
    this.applyFilterAndRefresh();
  },

  applyClustering() {
    if (!this.network || !this.visNodes || !this.visEdges) return;

    if (this.activeClusterMode === 'type') {
      const types = ['INFRA', 'AGENT', 'MODEL', 'CONCEPT', 'TICKER', 'POLICY'];
      types.forEach((type) => {
        const count = this.visNodes.get({ filter: (n) => n.type === type }).length;
        if (count > 1) {
          this.network.cluster({
            joinCondition: (nodeOptions) => nodeOptions.type === type,
            clusterNodeProperties: {
              id: `cluster-type-${type}`,
              label: `${type} (${count})`,
              shape: 'dot',
              size: Math.min(42, 20 + Math.round(count * 1.5)),
              color: '#6b9fff',
            },
          });
        }
      });
    } else if (this.activeClusterMode === 'component') {
      const edges = this.visEdges.get();
      const nodes = this.visNodes.get();
      const adj = {};
      nodes.forEach((n) => { adj[n.id] = []; });
      edges.forEach((e) => {
        if (adj[e.from] && adj[e.to]) {
          adj[e.from].push(e.to);
          adj[e.to].push(e.from);
        }
      });

      const visited = new Set();
      let compIndex = 0;
      nodes.forEach((n) => {
        if (!visited.has(n.id)) {
          const comp = [];
          const q = [n.id];
          visited.add(n.id);
          while (q.length > 0) {
            const curr = q.shift();
            comp.push(curr);
            (adj[curr] || []).forEach((nxt) => {
              if (!visited.has(nxt)) {
                visited.add(nxt);
                q.push(nxt);
              }
            });
          }
          if (comp.length >= 3) {
            compIndex++;
            const compSet = new Set(comp);
            const leader = nodes.find((node) => node.id === comp[0]);
            const label = leader ? `${leader.label} Group (${comp.length})` : `Component ${compIndex} (${comp.length})`;
            this.network.cluster({
              joinCondition: (nodeOptions) => compSet.has(nodeOptions.id),
              clusterNodeProperties: {
                id: `cluster-comp-${compIndex}`,
                label: label,
                shape: 'dot',
                size: Math.min(45, 22 + comp.length),
                color: '#38bdf8',
              },
            });
          }
        }
      });
    } else {
      this.applyFilterAndRefresh();
    }
  },

  escapeHtml(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },
};
