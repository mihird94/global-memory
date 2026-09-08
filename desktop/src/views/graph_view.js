window.GraphView = {
  network: null,
  includeExpired: false,
  asOfDate: '',

  async render(container) {
    container.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
        <div>
          <h2 style="font-size: 20px; font-weight: 700; margin-bottom: 4px;">Bi-Temporal Knowledge Graph</h2>
          <p style="font-size: 13px; color: var(--text-secondary);">Visualize entity relationships across validity windows. Red/dashed edges show historical invalidations.</p>
        </div>
        <div style="display: flex; align-items: center; gap: 14px;">
          <label style="display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-secondary); cursor: pointer;">
            <input type="checkbox" id="toggle-include-expired" ${this.includeExpired ? 'checked' : ''}>
            <span>Show Expired Edges</span>
          </label>
          <div style="display: flex; align-items: center; gap: 6px;">
            <span style="font-size: 12px; color: var(--text-muted);">As Of:</span>
            <input type="date" class="form-control" id="graph-as-of-date" value="${this.asOfDate}" style="width: 140px; padding: 4px 8px; font-size: 12px;">
            <button class="btn-secondary" id="btn-reset-as-of" style="font-size: 11px; padding: 4px 8px;">Clear</button>
          </div>
          <button class="btn-primary" id="btn-refresh-graph" style="font-size: 12px; padding: 5px 10px;">Refresh</button>
        </div>
      </div>

      <!-- Graph Container Card -->
      <div style="display: flex; gap: 16px; height: calc(100vh - 210px); min-height: 480px;">
        <div id="vis-graph-container" style="flex: 1; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-md); position: relative; overflow: hidden;">
          <div id="graph-loading-indicator" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: var(--text-muted); font-size: 14px;">
            Rendering Knowledge Graph...
          </div>
        </div>

        <!-- Node Inspector Drawer -->
        <div id="node-inspector-drawer" style="width: 320px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 18px; display: flex; flex-direction: column;">
          <div style="font-size: 14px; font-weight: 700; margin-bottom: 12px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;">
            Node Inspector
          </div>
          <div id="node-details-content" style="flex: 1; overflow-y: auto; font-size: 12.5px; color: var(--text-secondary);">
            <div style="text-align: center; color: var(--text-muted); padding: 40px 10px;">
              Click any entity node to inspect its properties, validity history, and relationship edges.
            </div>
          </div>
        </div>
      </div>
    `;

    this.bindEvents(container);
    await this.loadGraph();
  },

  bindEvents(container) {
    const expiredToggle = container.querySelector('#toggle-include-expired');
    const asOfInput = container.querySelector('#graph-as-of-date');
    const resetAsOfBtn = container.querySelector('#btn-reset-as-of');
    const refreshBtn = container.querySelector('#btn-refresh-graph');

    expiredToggle.addEventListener('change', (e) => {
      this.includeExpired = e.target.checked;
      this.loadGraph();
    });

    asOfInput.addEventListener('change', (e) => {
      this.asOfDate = e.target.value;
      this.loadGraph();
    });

    resetAsOfBtn.addEventListener('click', () => {
      this.asOfDate = '';
      asOfInput.value = '';
      this.loadGraph();
    });

    refreshBtn.addEventListener('click', () => this.loadGraph());
  },

  async loadGraph() {
    const container = document.getElementById('vis-graph-container');
    const loading = document.getElementById('graph-loading-indicator');
    if (!container) return;

    if (loading) loading.style.display = 'block';

    try {
      const graphData = await window.gms.getGraph({
        include_expired: this.includeExpired,
        as_of: this.asOfDate ? `${this.asOfDate}T23:59:59Z` : '',
      });

      if (loading) loading.style.display = 'none';

      const typeColors = {
        INFRA: { background: '#134e4a', border: '#2dd4bf', highlight: '#5eead4' },
        TICKER: { background: '#14532d', border: '#4ade80', highlight: '#86efac' },
        AGENT: { background: '#713f12', border: '#facc15', highlight: '#fde047' },
        MODEL: { background: '#581c87', border: '#c084fc', highlight: '#d8b4fe' },
        POLICY: { background: '#7c2d12', border: '#fb923c', highlight: '#fdba74' },
        CONCEPT: { background: '#1e3a8a', border: '#60a5fa', highlight: '#93c5fd' },
      };

      const nodes = graphData.nodes.map((n) => {
        const color = typeColors[n.type] || typeColors.CONCEPT;
        return {
          id: n.id,
          label: n.label,
          title: `${n.label} (${n.type})`,
          color: {
            background: color.background,
            border: color.border,
            highlight: { background: color.highlight, border: '#ffffff' },
          },
          font: { color: '#f0f6fc', size: 12, face: 'system-ui' },
          shape: 'box',
          margin: 8,
          borderWidth: 1.5,
          raw: n,
        };
      });

      const edges = graphData.edges.map((e) => {
        return {
          id: e.id,
          from: e.from,
          to: e.to,
          label: e.label,
          arrows: 'to',
          color: e.active ? { color: 'rgba(88, 166, 255, 0.4)', highlight: '#58a6ff' } : { color: 'rgba(248, 81, 73, 0.35)', highlight: '#f85149' },
          dashes: !e.active,
          font: { color: e.active ? '#8b949e' : '#f85149', size: 10, align: 'middle' },
          raw: e,
        };
      });

      // Check if vis is loaded
      if (typeof vis !== 'undefined') {
        const data = {
          nodes: new vis.DataSet(nodes),
          edges: new vis.DataSet(edges),
        };

        const options = {
          physics: {
            solver: 'forceAtlas2Based',
            forceAtlas2Based: {
              gravitationalConstant: -40,
              centralGravity: 0.008,
              springLength: 90,
              springConstant: 0.12,
            },
            maxVelocity: 40,
            minVelocity: 0.5,
            stabilization: { iterations: 120 },
          },
          interaction: { hover: true, tooltipDelay: 200 },
        };

        this.network = new vis.Network(container, data, options);

        this.network.on('click', (params) => {
          if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const node = nodes.find((n) => n.id === nodeId);
            if (node) this.showNodeDetails(node.raw, edges);
          }
        });
      } else {
        container.innerHTML = `
          <div style="padding: 30px; text-align: center; color: var(--text-secondary);">
            <div style="font-size: 16px; font-weight: 600; margin-bottom: 8px;">Interactive Graph Substrate</div>
            <p>Loaded ${nodes.length} entities and ${edges.length} relationships.</p>
          </div>
        `;
      }
    } catch (err) {
      if (loading) loading.style.display = 'none';
      container.innerHTML = `<div style="color: var(--accent-red); padding: 20px;">Graph failed to load: ${err.message}</div>`;
    }
  },

  showNodeDetails(node, allEdges) {
    const drawer = document.getElementById('node-details-content');
    if (!drawer) return;

    const connectedEdges = allEdges.filter((e) => e.from === node.id || e.to === node.id);

    drawer.innerHTML = `
      <div style="margin-bottom: 14px;">
        <div style="font-size: 15px; font-weight: 700; color: var(--accent-blue); word-break: break-all;">${node.label}</div>
        <span class="badge" style="background: rgba(88, 166, 255, 0.15); color: var(--accent-blue); margin-top: 4px;">${node.type}</span>
      </div>

      ${node.summary ? `
        <div style="margin-bottom: 14px;">
          <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;">Summary</div>
          <div style="margin-top: 2px;">${node.summary}</div>
        </div>
      ` : ''}

      <div>
        <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">
          Connected Edges (${connectedEdges.length})
        </div>
        ${connectedEdges.length === 0 ? '<div style="color: var(--text-muted); font-size: 11.5px;">No edges connected.</div>' : ''}
        <ul style="list-style: none; padding: 0; display: flex; flex-direction: column; gap: 8px;">
          ${connectedEdges.map((e) => `
            <li style="background: var(--bg-surface); padding: 8px 10px; border-radius: var(--radius-sm); border-left: 3px solid ${e.raw.active ? 'var(--accent-blue)' : 'var(--accent-red)'}; font-size: 11.5px;">
              <div style="font-weight: 600; color: ${e.raw.active ? 'var(--text-primary)' : 'var(--accent-red)'};">
                ${e.from === node.id ? '→ ' + e.label : '← ' + e.label}
              </div>
              <div style="color: var(--text-muted); font-size: 10.5px; margin-top: 2px;">
                Valid From: ${e.raw.valid_from ? e.raw.valid_from.split('T')[0] : 'genesis'}
                ${e.raw.valid_to ? `<br>Valid To: <span style="color: var(--accent-red);">${e.raw.valid_to.split('T')[0]} (Expired)</span>` : ''}
              </div>
            </li>
          `).join('')}
        </ul>
      </div>
    `;
  },
};
