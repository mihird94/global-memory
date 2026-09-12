/**
 * graph_filter.js — Pure Deterministic Graph Filtering Pipeline
 *
 * Implements the 10-step graph filtering pipeline from Mbrain UX Pass 2 specification (Section 5.3).
 * Zero DOM dependencies. Safe to run in browser, Electron, or Node.js tests.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.GraphFilter = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /**
   * Default filter configuration.
   */
  const DEFAULT_FILTER_STATE = {
    minConnections: 2,         // 0, 1, 2, 3, 5, 10
    temporalState: 'active',   // 'active', 'historical', 'all'
    asOfDate: null,            // ISO date string 'YYYY-MM-DD' or null
    selectedTypes: [],         // Empty array means all types allowed
    selectedPredicates: [],    // Empty array means all predicates allowed
    hideIsolates: true,        // Hide 0-degree nodes by default
    largestComponentOnly: false,
    neighborhoodDepth: 'all',  // 1, 2, or 'all'
    focusNodeId: null,         // Entity ID to anchor neighborhood
    revealedNodeIds: [],       // Explicitly searched/revealed node IDs
    textQuery: '',             // Text filter across label & summary
    hideLiteralNodes: false,   // Optional filter to suppress long literal-like nodes
  };

  /**
   * Normalize an entity type to uppercase string.
   */
  function normalizeType(t) {
    return String(t || 'CONCEPT').trim().toUpperCase();
  }

  /**
   * Pure deterministic filter function.
   *
   * @param {Object} rawGraph - { nodes: Array, edges: Array }
   * @param {Object} filterState - Partial or complete filter state
   * @returns {Object} { nodes: Array, edges: Array, metadata: Object }
   */
  function filterGraph(rawGraph, filterState = {}) {
    const state = { ...DEFAULT_FILTER_STATE, ...filterState };
    const rawNodes = Array.isArray(rawGraph?.nodes) ? rawGraph.nodes : [];
    const rawEdges = Array.isArray(rawGraph?.edges) ? rawGraph.edges : [];

    const totalNodes = rawNodes.length;
    const totalEdges = rawEdges.length;

    const hiddenReasons = {
      temporal: 0,
      predicate: 0,
      type: 0,
      degree: 0,
      isolate: 0,
      component: 0,
      text: 0,
      literal: 0,
    };

    // Node lookup map by ID
    const nodeMap = new Map();
    rawNodes.forEach((node) => {
      nodeMap.set(String(node.id), { ...node, type: normalizeType(node.type) });
    });

    // Step 1: Temporal / as-of edge filtering
    let asOfDt = null;
    if (state.asOfDate) {
      try {
        asOfDt = new Date(state.asOfDate.includes('T') ? state.asOfDate : `${state.asOfDate}T23:59:59Z`);
      } catch (e) {
        asOfDt = null;
      }
    }

    const temporarilyValidEdges = [];
    rawEdges.forEach((edge) => {
      const isActive = edge.active !== undefined ? Boolean(edge.active) : !edge.valid_to;
      let valid = true;

      if (asOfDt) {
        const fromDt = edge.valid_from ? new Date(edge.valid_from) : null;
        const toDt = edge.valid_to ? new Date(edge.valid_to) : null;
        if (fromDt && fromDt > asOfDt) valid = false;
        if (toDt && toDt <= asOfDt) valid = false;
      } else if (state.temporalState === 'active') {
        valid = isActive;
      } else if (state.temporalState === 'historical') {
        valid = !isActive;
      } // 'all' allows both

      if (valid) {
        temporarilyValidEdges.push(edge);
      } else {
        hiddenReasons.temporal++;
      }
    });

    // Step 2: Predicate filter
    const allowedPredicates = new Set(
      Array.isArray(state.selectedPredicates) ? state.selectedPredicates.map((p) => String(p).trim().toLowerCase()) : []
    );
    const predicateValidEdges = [];
    temporarilyValidEdges.forEach((edge) => {
      const pred = String(edge.label || edge.predicate || '').trim().toLowerCase();
      if (allowedPredicates.size === 0 || allowedPredicates.has(pred)) {
        predicateValidEdges.push(edge);
      } else {
        hiddenReasons.predicate++;
      }
    });

    // Step 3 & 4: Type filter & Literal filter
    const allowedTypes = new Set(
      Array.isArray(state.selectedTypes) ? state.selectedTypes.map((t) => normalizeType(t)) : []
    );
    const candidateNodes = new Map();

    nodeMap.forEach((node, idStr) => {
      const typeAllowed = allowedTypes.size === 0 || allowedTypes.has(node.type);
      const literalAllowed = !state.hideLiteralNodes || !node.literal_like;

      if (!typeAllowed) {
        hiddenReasons.type++;
      } else if (!literalAllowed) {
        hiddenReasons.literal++;
      } else {
        candidateNodes.set(idStr, { ...node });
      }
    });

    // Step 5: Recompute visible degree after temporal, predicate, and type filtering
    const visibleEdgesStep5 = [];
    const degreeMap = new Map();
    candidateNodes.forEach((_, id) => degreeMap.set(id, 0));

    predicateValidEdges.forEach((edge) => {
      const fromStr = String(edge.from);
      const toStr = String(edge.to);
      if (candidateNodes.has(fromStr) && candidateNodes.has(toStr)) {
        visibleEdgesStep5.push(edge);
        degreeMap.set(fromStr, (degreeMap.get(fromStr) || 0) + 1);
        degreeMap.set(toStr, (degreeMap.get(toStr) || 0) + 1);
      }
    });

    // Step 6: Minimum connections threshold
    const minDeg = Math.max(0, parseInt(state.minConnections, 10) || 0);
    const degreePassedNodes = new Map();
    candidateNodes.forEach((node, id) => {
      const deg = degreeMap.get(id) || 0;
      node.visibleDegree = deg;
      if (deg >= minDeg) {
        degreePassedNodes.set(id, node);
      } else {
        hiddenReasons.degree++;
      }
    });

    // Step 7: Edge pruning where endpoints did not meet minimum degree
    const degreePassedEdges = [];
    const degreePassedNodesRefined = new Map(degreePassedNodes);

    visibleEdgesStep5.forEach((edge) => {
      const fromStr = String(edge.from);
      const toStr = String(edge.to);
      if (degreePassedNodesRefined.has(fromStr) && degreePassedNodesRefined.has(toStr)) {
        degreePassedEdges.push(edge);
      }
    });

    // Step 8: Connectivity constraints (Hide isolates, Largest component, Neighborhood depth, Text filter)
    let currentNodes = new Map(degreePassedNodesRefined);

    // 8a: Text filter
    if (state.textQuery && state.textQuery.trim()) {
      const q = state.textQuery.trim().toLowerCase();
      const textPassed = new Map();
      currentNodes.forEach((node, id) => {
        const nameMatch = String(node.label || '').toLowerCase().includes(q);
        const summaryMatch = String(node.summary || '').toLowerCase().includes(q);
        if (nameMatch || summaryMatch) {
          textPassed.set(id, node);
        } else {
          hiddenReasons.text++;
        }
      });
      currentNodes = textPassed;
    }

    // 8b: Hide isolates (nodes with 0 edges in degreePassedEdges)
    const connectedNodeIds = new Set();
    degreePassedEdges.forEach((e) => {
      connectedNodeIds.add(String(e.from));
      connectedNodeIds.add(String(e.to));
    });

    if (state.hideIsolates) {
      const nonIsolates = new Map();
      currentNodes.forEach((node, id) => {
        if (connectedNodeIds.has(id)) {
          nonIsolates.set(id, node);
        } else {
          hiddenReasons.isolate++;
        }
      });
      currentNodes = nonIsolates;
    }

    // 8c: Neighborhood depth (around focusNodeId)
    if (state.focusNodeId && (state.neighborhoodDepth === 1 || state.neighborhoodDepth === 2 || state.neighborhoodDepth === '1' || state.neighborhoodDepth === '2')) {
      const depthLimit = parseInt(state.neighborhoodDepth, 10);
      const targetId = String(state.focusNodeId);

      // Adjacency graph
      const adj = new Map();
      degreePassedEdges.forEach((e) => {
        const u = String(e.from);
        const v = String(e.to);
        if (!adj.has(u)) adj.set(u, []);
        if (!adj.has(v)) adj.set(v, []);
        adj.get(u).push(v);
        adj.get(v).push(u);
      });

      // BFS to find nodes within depthLimit
      const visitedDepth = new Map();
      const queue = [{ id: targetId, d: 0 }];
      visitedDepth.set(targetId, 0);

      while (queue.length > 0) {
        const { id, d } = queue.shift();
        if (d >= depthLimit) continue;
        const neighbors = adj.get(id) || [];
        neighbors.forEach((nbr) => {
          if (!visitedDepth.has(nbr)) {
            visitedDepth.set(nbr, d + 1);
            queue.push({ id: nbr, d: d + 1 });
          }
        });
      }

      const neighborhoodNodes = new Map();
      currentNodes.forEach((node, id) => {
        if (visitedDepth.has(id)) {
          neighborhoodNodes.set(id, node);
        } else {
          hiddenReasons.component++;
        }
      });
      currentNodes = neighborhoodNodes;
    }

    // 8d: Largest connected component only
    if (state.largestComponentOnly && currentNodes.size > 0) {
      const activeNodeIds = new Set(currentNodes.keys());
      const adj = new Map();
      activeNodeIds.forEach((id) => adj.set(id, []));

      degreePassedEdges.forEach((e) => {
        const u = String(e.from);
        const v = String(e.to);
        if (activeNodeIds.has(u) && activeNodeIds.has(v)) {
          adj.get(u).push(v);
          adj.get(v).push(u);
        }
      });

      const visited = new Set();
      const components = [];

      activeNodeIds.forEach((startId) => {
        if (!visited.has(startId)) {
          const comp = [];
          const queue = [startId];
          visited.add(startId);

          while (queue.length > 0) {
            const curr = queue.shift();
            comp.push(curr);
            (adj.get(curr) || []).forEach((nbr) => {
              if (!visited.has(nbr)) {
                visited.add(nbr);
                queue.push(nbr);
              }
            });
          }
          components.push(comp);
        }
      });

      // Find largest component
      components.sort((a, b) => b.length - a.length);
      const largestSet = new Set(components[0] || []);

      const compNodes = new Map();
      currentNodes.forEach((node, id) => {
        if (largestSet.has(id)) {
          compNodes.set(id, node);
        } else {
          hiddenReasons.component++;
        }
      });
      currentNodes = compNodes;
    }

    // Step 9: Re-add explicitly searched/revealed nodes with a `revealed` marker
    const revealedSet = new Set(
      (Array.isArray(state.revealedNodeIds) ? state.revealedNodeIds : []).map(String)
    );
    if (state.focusNodeId && state.forceRevealFocus) {
      revealedSet.add(String(state.focusNodeId));
    }

    revealedSet.forEach((revId) => {
      if (!currentNodes.has(revId) && nodeMap.has(revId)) {
        const orig = nodeMap.get(revId);
        currentNodes.set(revId, {
          ...orig,
          revealed: true,
          visibleDegree: degreeMap.get(revId) || 0,
        });
      }
    });

    // Final edge filter based on survivor nodes
    const finalNodes = Array.from(currentNodes.values());
    const survivorNodeIds = new Set(currentNodes.keys());

    const finalEdges = [];
    visibleEdgesStep5.forEach((edge) => {
      const fromStr = String(edge.from);
      const toStr = String(edge.to);
      if (survivorNodeIds.has(fromStr) && survivorNodeIds.has(toStr)) {
        finalEdges.push(edge);
      }
    });

    // Facet counts based on current raw graph
    const typeFacetCounts = {};
    rawNodes.forEach((n) => {
      const t = normalizeType(n.type);
      typeFacetCounts[t] = (typeFacetCounts[t] || 0) + 1;
    });

    const predicateFacetCounts = {};
    rawEdges.forEach((e) => {
      const p = String(e.label || e.predicate || '').trim();
      if (p) {
        predicateFacetCounts[p] = (predicateFacetCounts[p] || 0) + 1;
      }
    });

    return {
      nodes: finalNodes,
      edges: finalEdges,
      metadata: {
        totalNodes,
        totalEdges,
        visibleNodes: finalNodes.length,
        visibleEdges: finalEdges.length,
        hiddenReasons,
        facets: {
          types: typeFacetCounts,
          predicates: predicateFacetCounts,
        },
        activeFilterState: state,
      },
    };
  }

  return {
    DEFAULT_FILTER_STATE,
    normalizeType,
    filterGraph,
  };
});
