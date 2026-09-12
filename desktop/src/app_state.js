/**
 * app_state.js — Central Application State & Navigation History Store
 *
 * Provides unified cross-view state, back/forward history tracking,
 * and stable ID preservation across Graph, Entities, and Exploration.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.AppState = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const listeners = new Set();

  const state = {
    activeView: 'exploration',
    history: [],
    historyIndex: -1,
    globalSearchQuery: '',
    selectedMemoryKey: '',
    selectedEntityId: null,
    selectedRelationshipId: null,
    selectedProjectId: null,
    graphFilterState: {
      minConnections: 2,
      temporalState: 'active',
      asOfDate: null,
      selectedTypes: [],
      selectedPredicates: [],
      hideIsolates: true,
      largestComponentOnly: false,
      neighborhoodDepth: 'all',
      textQuery: '',
      hideLiteralNodes: false,
    },
    graphPhysicsPreset: 'balanced',
    graphLabelMode: 'important', // 'important', 'all', 'none'
    graphClusterMode: 'none',     // 'none', 'type', 'namespace', 'component'
    graphFocus: null,
    graphViewport: null,
  };

  function subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function notify(changedKey, value) {
    listeners.forEach((fn) => {
      try {
        fn(changedKey, value, state);
      } catch (err) {
        console.error('AppState listener error:', err);
      }
    });
  }

  function pushHistory(entry) {
    if (state.historyIndex < state.history.length - 1) {
      state.history = state.history.slice(0, state.historyIndex + 1);
    }
    state.history.push({ ...entry, timestamp: Date.now() });
    if (state.history.length > 50) {
      state.history.shift();
    }
    state.historyIndex = state.history.length - 1;
    notify('history', state.history);
  }

  function canGoBack() {
    return state.historyIndex > 0;
  }

  function canGoForward() {
    return state.historyIndex < state.history.length - 1;
  }

  function goBack() {
    if (!canGoBack()) return null;
    state.historyIndex--;
    const entry = state.history[state.historyIndex];
    return entry;
  }

  function goForward() {
    if (!canGoForward()) return null;
    state.historyIndex++;
    const entry = state.history[state.historyIndex];
    return entry;
  }

  function setView(viewName, meta = {}) {
    state.activeView = viewName;
    pushHistory({ view: viewName, ...meta });
    notify('activeView', viewName);
  }

  function setGraphFilters(newFilters) {
    state.graphFilterState = { ...state.graphFilterState, ...newFilters };
    notify('graphFilterState', state.graphFilterState);
  }

  function setSelectedEntity(entityId) {
    state.selectedEntityId = entityId;
    notify('selectedEntityId', entityId);
  }

  function setSelectedRelationship(relId) {
    state.selectedRelationshipId = relId;
    notify('selectedRelationshipId', relId);
  }

  function setSelectedMemoryKey(key) {
    state.selectedMemoryKey = key;
    notify('selectedMemoryKey', key);
  }

  function setSelectedProjectId(projectId) {
    state.selectedProjectId = projectId;
    notify('selectedProjectId', projectId);
  }

  return {
    state,
    subscribe,
    pushHistory,
    canGoBack,
    canGoForward,
    goBack,
    goForward,
    setView,
    setGraphFilters,
    setSelectedEntity,
    setSelectedRelationship,
    setSelectedMemoryKey,
    setSelectedProjectId,
  };
});
