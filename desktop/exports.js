const exportsState = {
  bundles: [],
  harnesses: {},
  selectedName: '',
  detail: null,
  tab: 'all',
  loading: false,
  busy: false,
  dialogMode: 'create',
  sugFilter: 'recommended',
  sugBucket: '',
  sugIncludeReadonly: false,
  inboxDirty: false,
  profileDirty: false,
};

const ACTION_LABELS = {
  allow: 'Allow',
  redact_and_review: 'Redact & review',
  block: 'Blocked',
};

const TIER_LABELS = {
  recommended: 'Suggested: Clean',
  review: 'Suggested: Review',
  blocked: 'Suggested: Blocked',
};

const TIER_PILL_CLASSES = {
  recommended: 'export-action-allow',
  review: 'export-action-redact_and_review',
  blocked: 'export-action-block',
};

const HARNESS_LABELS = {
  pi: 'Pi (~/.pi/agent/mcp.json)',
  opencode: 'OpenCode (~/.config/opencode/opencode.jsonc)',
};

function harnessBadge(info) {
  const st = info?.state || 'disconnected';
  if (st === 'wired_this') return { text: 'Connected (this bundle)', cls: 'export-h-ok' };
  if (st === 'wired_other' || st === 'wired') return { text: 'Connected (other bundle)', cls: 'export-h-warn' };
  if (st === 'exposed_unrestricted') return { text: 'UNRESTRICTED brain-mcp!', cls: 'export-h-danger' };
  if (st === 'missing_config') return { text: 'Not installed', cls: 'export-h-muted' };
  return { text: 'Disconnected (safe)', cls: 'export-h-muted' };
}

function renderGlobalHarnesses(harnesses) {
  const box = $('export-global-status');
  const rows = Object.entries(HARNESS_LABELS).map(([key, label]) => {
    const info = harnesses?.[key];
    const b = harnessBadge(info);
    const row = element('div', 'export-global-row');
    row.append(element('span', '', label.split(' ')[0]), element('span', `pill ${b.cls}`, b.text));
    return row;
  });
  box.replaceChildren(...rows);
}

function bundleRow(b) {
  const row = element('div');
  row.setAttribute('role', 'listitem');
  const btn = element('button', 'memory-row');
  btn.dataset.bundle = b.name;
  btn.setAttribute('aria-pressed', String(b.name === exportsState.selectedName));
  const glyph = element('span', 'memory-icon export-icon');
  glyph.append(icon('shield'));
  const body = element('span', 'row-body');
  const meta = element('span', 'row-meta');
  const sc = b.staged_counts || {};
  const stagedTotal = (sc.allow || 0) + (sc.redact_and_review || 0) + (sc.block || 0);
  meta.append(
    element('span', `pill ${b.approved_count ? 'export-action-allow' : 'board-state-assigned'}`, `${b.approved_count} live`),
    element('span', 'row-project', `· ${(b.projects || []).join(', ') || 'custom'}`),
    element('span', 'row-date', `· ${stagedTotal} staged`),
  );
  if (b.inbox_pending_count) meta.append(element('span', 'pill export-action-block', `${b.inbox_pending_count} inbox`));
  body.append(element('span', 'row-title', b.name), meta);
  btn.append(glyph, body);
  btn.addEventListener('click', () => openBundle(b.name, true));
  row.append(btn);
  return row;
}

function renderBundleList() {
  const list = $('exports-list');
  const n = exportsState.bundles.length;
  $('exports-subtitle').textContent = `${n} ${n === 1 ? 'bundle' : 'bundles'}`;
  renderGlobalHarnesses(exportsState.harnesses);
  if (n) {
    list.replaceChildren(...exportsState.bundles.map(bundleRow));
  } else {
    const msg = element('div', 'list-message');
    msg.append(element('strong', '', 'No safe bundles yet'), element('p', '', 'Use New bundle to whitelist a project and screen notes locally.'));
    list.replaceChildren(msg);
  }
}

async function refreshExports({ quiet = false, preferred = '' } = {}) {
  const editingInbox = exportsState.tab === 'inbox' && (exportsState.inboxDirty || $('export-inbox-pane').contains(document.activeElement));
  const editingProfile = exportsState.tab === 'profile' && (exportsState.profileDirty || document.activeElement === $('export-profile-text'));
  if (quiet && (exportsState.loading || exportsState.busy || $('bundle-dialog').open || editingInbox || editingProfile)) return;
  exportsState.loading = true;
  try {
    const data = await bridge.request('export_list', {});
    if (state.view !== 'exports') return;
    exportsState.bundles = data.bundles || [];
    exportsState.harnesses = data.harnesses || {};
    renderBundleList();
    const target = preferred || exportsState.selectedName || (exportsState.bundles[0]?.name && !narrow() ? exportsState.bundles[0].name : '');
    if (target && exportsState.bundles.some((b) => b.name === target)) {
      await openBundle(target, Boolean(preferred));
    } else if (!target || !exportsState.bundles.some((b) => b.name === target)) {
      exportsState.selectedName = '';
      exportsState.detail = null;
      $('export-empty').hidden = false;
      $('export-content').hidden = true;
    }
  } catch (error) {
    if (!quiet) notify(error.message);
  } finally {
    exportsState.loading = false;
  }
}

async function openBundle(name, reveal = false) {
  try {
    const detail = await bridge.request('export_read', { bundle: name });
    if (state.view !== 'exports') return;
    if (exportsState.selectedName !== detail.name) {
      exportsState.inboxDirty = false;
      exportsState.profileDirty = false;
    }
    exportsState.selectedName = detail.name;
    exportsState.detail = detail;
    if (detail.suggestions) exportsState.sugIncludeReadonly = Boolean(detail.suggestions.include_readonly);
    renderBundleList();
    renderBundleDetail(detail);
    $('export-empty').hidden = true;
    $('export-content').hidden = false;
    if (reveal) {
      $('exports-view').classList.add('show-reader');
      if (narrow()) $('export-back').focus();
    }
  } catch (error) {
    notify(error.message);
  }
}

async function runBundleMutation(label, action, params, { switchToTab = '' } = {}) {
  if (exportsState.busy) return;
  exportsState.busy = true;
  const stageBtn = $('export-stage-btn');
  const prevStageText = stageBtn.querySelector('span')?.textContent || 'Scan & stage';
  if (action === 'export_stage' && stageBtn.querySelector('span')) {
    stageBtn.querySelector('span').textContent = 'Scanning…';
  }
  try {
    const res = await bridge.request(action, params);
    const detail = res.detail || res;
    if (action === 'export_inbox_discard' || action === 'export_inbox_promote') exportsState.inboxDirty = false;
    if (action === 'export_save_profile') exportsState.profileDirty = false;
    if (res.message) notify(res.message);
    else if (label) notify(label);
    exportsState.selectedName = detail.name;
    exportsState.detail = detail;
    if (switchToTab) exportsState.tab = switchToTab;
    await refreshExports({ preferred: detail.name });
  } catch (error) {
    notify(error.message);
  } finally {
    if (stageBtn.querySelector('span')) stageBtn.querySelector('span').textContent = prevStageText;
    exportsState.busy = false;
  }
}

function renderHarnessControls(detail) {
  const wrap = $('export-harnesses');
  const rows = Object.entries(HARNESS_LABELS).map(([harness, title]) => {
    const info = detail.harnesses?.[harness] || { state: 'disconnected', bundle: '' };
    const badge = harnessBadge(info);
    const card = element('div', 'export-harness-card');
    const left = element('div', 'export-harness-meta');
    left.append(element('strong', '', title), element('span', `pill ${badge.cls}`, badge.text));
    const btns = element('div', 'export-harness-actions');

    const connectBtn = element('button', 'button secondary', info.state === 'wired_this' ? 'Rewire' : 'Connect');
    connectBtn.type = 'button';
    connectBtn.addEventListener('click', () => runBundleMutation(`Connected ${harness} to brain-safe-mcp`, 'export_wire', { bundle: detail.name, harness, disconnect: false }));

    const discBtn = element('button', 'button secondary', 'Disconnect');
    discBtn.type = 'button';
    discBtn.disabled = info.state === 'disconnected' || info.state === 'missing_config';
    discBtn.addEventListener('click', () => runBundleMutation(`Disconnected ${harness}`, 'export_wire', { bundle: detail.name, harness, disconnect: true }));

    btns.append(connectBtn, discBtn);
    card.append(left, btns);
    return card;
  });
  wrap.replaceChildren(...rows);
}

function renderCoverageBanner(detail) {
  const banner = $('export-coverage-banner');
  const cov = detail.inventory?.coverage || detail.skipped_breakdown || {};
  const sk = detail.skipped_breakdown || cov;
  const totalNotes = detail.total_store_notes ?? detail.inventory?.total_notes ?? 0;
  const sc = detail.staged_counts || {};
  const stagedTotal = (sc.allow || 0) + (sc.redact_and_review || 0) + (sc.block || 0);
  const eligibleNow = cov.eligible_in_scope ?? stagedTotal;

  const summaryText = `Scope matches ${number.format(eligibleNow)} of ${number.format(totalNotes)} memories in Brain (${number.format(stagedTotal)} staged) · Skipped: ${number.format(sk.other_projects || 0)} other projects, ${number.format(sk.unprojected || 0)} unprojected, ${number.format(sk.private_kinds || 0)} journals/profile, ${number.format(sk.readonly_roots || 0)} read-only wiki`;

  const actions = element('div', 'export-coverage-actions');
  const scopeBtn = element('button', 'button secondary', 'Edit scope');
  scopeBtn.type = 'button';
  scopeBtn.addEventListener('click', () => openBundleDialog('edit', detail));

  const sugBtn = element('button', 'button secondary', 'Suggest classifications');
  sugBtn.type = 'button';
  sugBtn.addEventListener('click', () => {
    exportsState.tab = 'suggestions';
    renderBundleDetail(detail);
  });

  actions.append(scopeBtn, sugBtn);
  banner.replaceChildren(element('span', '', summaryText), actions);
}

function renderBundleDetail(detail) {
  $('export-bundle-path').textContent = detail.bundle_dir;
  $('export-bundle-name').textContent = detail.name;
  const cfg = detail.config || {};
  const scopeParts = [(cfg.projects || []).join(', ') || 'none'];
  if (cfg.include_unprojected) scopeParts.push('+ unprojected');
  if (cfg.include_readonly_roots) scopeParts.push('+ wiki');
  if (cfg.manual_include_ids?.length) scopeParts.push(`+ ${cfg.manual_include_ids.length} picked`);
  const stagedStamp = detail.staged_at ? ` · last scan ${formatDay(detail.staged_at)}` : ' · not scanned yet';
  $('export-bundle-meta').textContent = `Scope: ${scopeParts.join(' ')} · Kinds: ${(cfg.allow_kinds || []).join(', ')} · MiniLM threshold ${cfg.threshold ?? 0.50}${stagedStamp}`;
  $('export-manifest-pill').textContent = `Manifest v${detail.manifest_version} · ${detail.approved_count} live`;
  $('export-manifest-pill').className = `pill ${detail.approved_count ? 'export-action-allow' : 'board-state-assigned'}`;

  renderCoverageBanner(detail);
  renderHarnessControls(detail);

  const sc = detail.staged_counts || {};
  const cardsData = [
    ['Approved live', detail.approved_count || 0],
    ['Allow (clean)', sc.allow || 0],
    ['Redact & review', sc.redact_and_review || 0],
    ['Blocked', sc.block || 0],
  ];
  $('export-cards').replaceChildren(...cardsData.map(([lbl, val]) => {
    const box = element('div');
    box.append(element('strong', '', number.format(val)), element('span', '', lbl));
    return box;
  }));

  const sugTab = $('export-tab-suggestions');
  const recCount = detail.suggestions?.tier_counts?.recommended;
  sugTab.textContent = recCount !== undefined ? `Suggestions (${number.format(recCount)} clean)` : 'Suggestions';

  for (const btn of $('export-tabs').querySelectorAll('button')) {
    btn.classList.toggle('active', btn.dataset.etab === exportsState.tab);
  }

  const showInbox = exportsState.tab === 'inbox';
  $('export-tab-inbox').textContent = detail.inbox_pending_count ? `Inbox (${detail.inbox_pending_count})` : 'Inbox';
  $('export-inbox-pane').hidden = !showInbox;
  const showProfile = exportsState.tab === 'profile';
  const showAudit = exportsState.tab === 'audit';
  const showSuggestions = exportsState.tab === 'suggestions';
  $('export-items').hidden = showProfile || showAudit || showSuggestions || showInbox;
  $('export-suggestions-pane').hidden = !showSuggestions;
  $('export-profile-pane').hidden = !showProfile;
  $('export-audit-pane').hidden = !showAudit;

  $('export-approve-clean-btn').disabled = !(sc.allow > 0);
  $('export-revoke-all-btn').disabled = !(detail.approved_count > 0);

  if (showInbox) {
    renderInboxPane(detail);
  } else if (showProfile) {
    $('export-profile-text').value = detail.safe_profile || '';
  } else if (showAudit) {
    renderAuditPane(detail.recent_audit || []);
  } else if (showSuggestions) {
    renderSuggestionsPane(detail);
  } else {
    renderItemsList(detail);
  }
}

function buildPreviewDetails(it) {
  if (!it.diff_preview && !it.scrubbed_body) return null;
  const details = document.createElement('details');
  details.className = 'export-preview-details';
  details.append(element('summary', '', it.diff_preview ? 'Inspect redaction diff & sanitized body' : 'Inspect sanitized body'));
  if (it.diff_preview) details.append(element('pre', 'export-diff', it.diff_preview));
  if (it.scrubbed_body) details.append(element('pre', 'export-scrubbed-body', it.scrubbed_body));
  return details;
}

function renderItemsList(detail) {
  const container = $('export-items');
  const items = (detail.items || []).filter((it) => {
    if (exportsState.tab === 'approved') return it.approved;
    if (exportsState.tab === 'all') return true;
    return it.action === exportsState.tab;
  });

  if (!items.length) {
    const msg = element('div', 'list-message');
    const headline = (detail.items || []).length ? 'No notes in this filter' : 'No staged scan results yet';
    const sub = (detail.items || []).length ? 'Switch tabs, edit scope, or open Suggestions.' : 'Click Scan & stage above or open Suggestions to pick from all Brain memories.';
    msg.append(element('strong', '', headline), element('p', '', sub));
    container.replaceChildren(msg);
    return;
  }

  const cards = items.map((it) => {
    const card = element('div', `export-card export-card-${it.action}`);
    const top = element('div', 'export-card-top');
    const titleBox = element('div');
    titleBox.append(
      element('div', 'export-card-title', it.title),
      element('div', 'export-card-id', `${it.id} · ${it.kind}/${it.project || 'unprojected'}`),
    );
    const pills = element('div', 'export-card-pills');
    pills.append(element('span', `pill export-action-${it.action}`, ACTION_LABELS[it.action] || it.action));
    if (it.approved) {
      const okState = it.source_state === 'ok' && it.export_state === 'ok';
      pills.append(element('span', `pill ${okState ? 'export-live-pill' : 'export-drift-pill'}`, okState ? 'Approved · Live' : `${it.source_state} / ${it.export_state}`));
    }
    if (it.staged) pills.append(element('span', 'pill board-state-assigned', `p=${Number(it.p_post_scrub).toFixed(2)}`));
    if (it.entity_types?.length) pills.append(element('span', 'pill board-state-blocked', it.entity_types.join(', ')));
    top.append(titleBox, pills);
    card.append(top);

    const preview = buildPreviewDetails(it);
    if (preview) card.append(preview);

    const actions = element('div', 'export-card-actions');
    if (it.staged) {
      if (it.action === 'allow') {
        const b = element('button', 'button secondary', it.approved ? 'Re-approve' : 'Approve clean');
        b.type = 'button';
        b.addEventListener('click', () => runBundleMutation(`Approved ${it.id}`, 'export_approve', { bundle: detail.name, doc_ids: [it.id] }));
        actions.append(b);
      } else if (it.action === 'redact_and_review') {
        const b = element('button', 'button secondary', it.approved ? 'Re-approve redacted' : 'Approve redacted');
        b.type = 'button';
        b.addEventListener('click', () => runBundleMutation(`Approved redacted ${it.id}`, 'export_approve', { bundle: detail.name, doc_ids: [it.id], allow_redacted: true }));
        actions.append(b);
      } else if (it.action === 'block') {
        const b = element('button', 'button secondary danger-ghost', 'Override & approve…');
        b.type = 'button';
        b.addEventListener('click', () => {
          if (window.confirm(`"${it.title}" was BLOCKED (${(it.hard_block_rules || []).join(', ') || `p=${it.p_post_scrub}`}). Override and export to external bundle "${detail.name}"?`)) {
            runBundleMutation(`Override-approved ${it.id}`, 'export_approve', { bundle: detail.name, doc_ids: [it.id], allow_redacted: true, force_blocked: true });
          }
        });
        actions.append(b);
      }
    }
    if (it.approved) {
      const r = element('button', 'button secondary danger-ghost', 'Revoke');
      r.type = 'button';
      r.addEventListener('click', () => runBundleMutation(`Revoked ${it.id}`, 'export_revoke', { bundle: detail.name, doc_ids: [it.id] }));
      actions.append(r);
    }
    card.append(actions);
    return card;
  });
  container.replaceChildren(...cards);
}

function addBucketToScope(detail, bucket) {
  const cfg = detail.config || {};
  const payload = { bundle: detail.name, restage: true };
  if (bucket.type === 'readonly') {
    payload.include_readonly_roots = true;
  } else if (bucket.type === 'unprojected') {
    payload.include_unprojected = true;
  } else {
    if (bucket.sensitive && !window.confirm(`"${bucket.label}" is marked sensitive by default policy. Add this project to "${detail.name}" scope and scan it locally?`)) {
      return;
    }
    payload.projects = Array.from(new Set([...(cfg.projects || []), bucket.slug]));
    if (bucket.sensitive) payload.allow_sensitive_project = true;
  }
  runBundleMutation(`Added "${bucket.label}" to scope`, 'export_update_config', payload);
}

function renderSuggestionsPane(detail) {
  const pane = $('export-suggestions-pane');
  const sug = detail.suggestions;
  const inv = detail.inventory || {};

  const toolbar = element('div', 'export-sug-toolbar');
  const controls = element('div', 'export-sug-controls');

  const scanBtn = element('button', 'button primary', sug ? 'Re-scan all memories' : 'Scan & classify all memories');
  scanBtn.type = 'button';
  scanBtn.addEventListener('click', () => {
    scanBtn.textContent = 'Classifying…';
    scanBtn.disabled = true;
    runBundleMutation('Store-wide classification updated', 'export_discover', {
      bundle: detail.name,
      include_readonly: exportsState.sugIncludeReadonly,
    });
  });

  const roLabel = element('label', 'inline-check');
  const roCheck = document.createElement('input');
  roCheck.type = 'checkbox';
  roCheck.checked = exportsState.sugIncludeReadonly;
  roCheck.addEventListener('change', () => {
    exportsState.sugIncludeReadonly = roCheck.checked;
  });
  roLabel.append(roCheck, element('span', '', `Include read-only wiki (${number.format(inv.readonly_count || 0)})`));

  controls.append(scanBtn, roLabel);
  toolbar.append(controls);

  if (!sug) {
    const empty = element('div', 'list-message');
    empty.append(
      element('strong', '', 'Discover & classify notes across your whole Brain store'),
      element('p', '', `Click "Scan & classify all memories" to run local ONNX screening across ${number.format(inv.total_notes || 0)} notes, group clean vs. redacted vs. blocked projects, and cherry-pick any note into "${detail.name}".`),
    );
    pane.replaceChildren(toolbar, empty);
    return;
  }

  const unaddedClean = (sug.items || []).filter((it) => it.suggested_tier === 'recommended' && !it.in_scope);
  const bulkBtn = element('button', 'button secondary', `Add ${number.format(unaddedClean.length)} recommended clean`);
  bulkBtn.type = 'button';
  bulkBtn.disabled = unaddedClean.length === 0;
  bulkBtn.addEventListener('click', () => {
    runBundleMutation(
      `Added ${unaddedClean.length} clean notes to "${detail.name}"`,
      'export_add_candidates',
      { bundle: detail.name, doc_ids: unaddedClean.map((i) => i.id), approve_if_clean: false },
    );
  });
  toolbar.append(bulkBtn);

  const bucketsWrap = element('div', 'export-sug-buckets');
  for (const b of sug.project_summaries || []) {
    const card = element('div', `export-sug-bucket-card${exportsState.sugBucket === b.key ? ' active' : ''}`);
    card.addEventListener('click', () => {
      exportsState.sugBucket = exportsState.sugBucket === b.key ? '' : b.key;
      renderSuggestionsPane(detail);
    });
    const top = element('div', 'export-sug-bucket-top');
    const titleSpan = element('strong', '', b.label);
    const tierPill = element('span', `pill ${TIER_PILL_CLASSES[b.suggested_tier] || 'board-state-assigned'}`, `${b.allow} clean`);
    top.append(titleSpan, tierPill);

    const stats = element('div', 'export-sug-bucket-stats', `${b.total} total · ${b.redact_and_review} redact · ${b.block} blocked${b.sensitive ? ' · Sensitive project' : ''}`);
    const actRow = element('div', 'export-sug-bucket-actions');
    if (b.in_scope) {
      actRow.append(element('span', 'pill export-live-pill', 'In scope'));
    } else {
      const addScopeBtn = element('button', 'button secondary', '+ Add to scope');
      addScopeBtn.type = 'button';
      addScopeBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        addBucketToScope(detail, b);
      });
      actRow.append(addScopeBtn);
    }
    card.append(top, stats, actRow);
    bucketsWrap.append(card);
  }

  const tc = sug.tier_counts || {};
  const filterRow = element('div', 'export-sug-filters');
  const pillsBox = element('div', 'export-sug-pills');
  for (const [tierKey, label] of [
    ['recommended', `Recommended clean (${number.format(tc.recommended || 0)})`],
    ['review', `Needs review (${number.format(tc.review || 0)})`],
    ['blocked', `Blocked (${number.format(tc.blocked || 0)})`],
    ['all', `All scanned (${number.format(sug.total_scanned || 0)})`],
  ]) {
    const btn = element('button', `button ${exportsState.sugFilter === tierKey ? 'primary' : 'secondary'}`, label);
    btn.type = 'button';
    btn.addEventListener('click', () => {
      exportsState.sugFilter = tierKey;
      renderSuggestionsPane(detail);
    });
    pillsBox.append(btn);
  }
  filterRow.append(pillsBox);
  if (exportsState.sugBucket) {
    const clearBtn = element('button', 'button secondary', `Filter: ${exportsState.sugBucket} ✕`);
    clearBtn.type = 'button';
    clearBtn.addEventListener('click', () => {
      exportsState.sugBucket = '';
      renderSuggestionsPane(detail);
    });
    filterRow.append(clearBtn);
  }

  const filtered = (sug.items || []).filter((it) => {
    if (exportsState.sugFilter !== 'all' && it.suggested_tier !== exportsState.sugFilter) return false;
    if (exportsState.sugBucket && it.bucket_key !== exportsState.sugBucket) return false;
    return true;
  });

  const listWrap = element('div', 'export-items');
  if (!filtered.length) {
    const msg = element('div', 'list-message');
    msg.append(element('strong', '', 'No matching suggestions'), element('p', '', 'Switch tier filters or clear the selected source card above.'));
    listWrap.append(msg);
  } else {
    for (const it of filtered) {
      const card = element('div', `export-card export-card-${it.action}`);
      const top = element('div', 'export-card-top');
      const titleBox = element('div');
      titleBox.append(
        element('div', 'export-card-title', it.title),
        element('div', 'export-card-id', `${it.id} · ${it.kind}/${it.project || (it.readonly ? 'wiki' : 'unprojected')}`),
      );
      const pills = element('div', 'export-card-pills');
      pills.append(
        element('span', `pill ${TIER_PILL_CLASSES[it.suggested_tier] || 'board-state-assigned'}`, TIER_LABELS[it.suggested_tier] || it.suggested_tier),
        element('span', 'pill board-state-assigned', `p=${Number(it.p_post_scrub).toFixed(2)}`),
      );
      if (it.sensitive_project) pills.append(element('span', 'pill export-h-warn', 'Sensitive project'));
      if (it.entity_types?.length) pills.append(element('span', 'pill board-state-blocked', it.entity_types.join(', ')));
      top.append(titleBox, pills);
      card.append(top);

      const preview = buildPreviewDetails(it);
      if (preview) card.append(preview);

      const actions = element('div', 'export-card-actions');
      if (it.approved) {
        actions.append(element('span', 'pill export-live-pill', 'Approved · Live'));
      } else if (it.in_scope) {
        actions.append(element('span', 'pill board-state-assigned', 'In scope (staged)'));
        const jumpBtn = element('button', 'button secondary', 'Open in staged');
        jumpBtn.type = 'button';
        jumpBtn.addEventListener('click', () => {
          exportsState.tab = it.action === 'allow' ? 'allow' : it.action === 'redact_and_review' ? 'redact_and_review' : 'block';
          renderBundleDetail(detail);
        });
        actions.append(jumpBtn);
      } else {
        const addBtn = element('button', 'button secondary', '+ Add to bundle');
        addBtn.type = 'button';
        addBtn.addEventListener('click', () => {
          if (it.sensitive_project && !window.confirm(`"${it.title}" belongs to sensitive project "${it.project}". Stage it into "${detail.name}"?`)) return;
          runBundleMutation(`Added ${it.id} to "${detail.name}"`, 'export_add_candidates', {
            bundle: detail.name,
            doc_ids: [it.id],
            approve_if_clean: false,
          });
        });
        actions.append(addBtn);

        if (it.action === 'allow') {
          const addAppBtn = element('button', 'button primary', '+ Add & approve');
          addAppBtn.type = 'button';
          addAppBtn.addEventListener('click', () => {
            if (it.sensitive_project && !window.confirm(`"${it.title}" belongs to sensitive project "${it.project}". Add and immediately approve it for Pi/OpenCode?`)) return;
            runBundleMutation(`Added & approved ${it.id}`, 'export_add_candidates', {
              bundle: detail.name,
              doc_ids: [it.id],
              approve_if_clean: true,
            });
          });
          actions.append(addAppBtn);
        }
      }
      card.append(actions);
      listWrap.append(card);
    }
  }

  pane.replaceChildren(toolbar, bucketsWrap, filterRow, listWrap);
}

function renderAuditPane(rows) {
  const box = $('export-audit-pane');
  if (!rows.length) {
    const msg = element('div', 'list-message');
    msg.append(element('strong', '', 'No MCP reads logged yet'), element('p', '', 'Every safe_context, safe_search, and safe_read call appends a verified SHA-256 audit row here.'));
    box.replaceChildren(msg);
    return;
  }
  const list = element('div', 'export-audit-list');
  for (const r of rows) {
    const item = element('div', 'export-audit-row');
    item.append(
      element('span', 'export-audit-ts', r.ts || ''),
      element('span', 'pill board-state-assigned', r.tool || ''),
      element('span', `pill ${r.status === 'ok' ? 'export-action-allow' : 'export-action-block'}`, r.status || ''),
      element('span', 'export-audit-target', [r.doc_id, r.sha256 ? `sha:${r.sha256}` : '', r.ms !== undefined ? `${r.ms}ms` : ''].filter(Boolean).join(' · ')),
    );
    list.append(item);
  }
  box.replaceChildren(list);
}

function updateSensitiveWarningVisibility() {
  const list = $('bundle-projects-list');
  const anySensitive = Array.from(list.querySelectorAll('input[name="project_pick"]:checked')).some(
    (cb) => cb.dataset.sensitive === '1',
  );
  $('bundle-sensitive-wrap').hidden = !anySensitive;
  if (!anySensitive) $('bundle-allow-sensitive').checked = false;
}

async function openBundleDialog(mode, detail = null) {
  exportsState.dialogMode = mode;
  const form = $('bundle-form');
  form.reset();
  $('bundle-error').hidden = true;

  let inv = detail?.inventory;
  if (!inv) {
    try {
      inv = await bridge.request('export_inventory', {});
    } catch (error) {
      notify(error.message);
      return;
    }
  }

  const cfg = detail?.config || {};
  const selectedProjects = new Set(
    mode === 'edit' ? (cfg.projects || []) : (state.project ? [state.project] : []),
  );
  const allowKinds = new Set(cfg.allow_kinds || ['project', 'decision', 'lesson', 'fact']);

  $('bundle-dialog-title').textContent = mode === 'edit' ? `Edit scope · ${detail.name}` : 'New safe bundle';
  $('submit-bundle').textContent = mode === 'edit' ? 'Save scope & restage' : 'Create bundle';
  form.elements.name.value = mode === 'edit' ? detail.name : '';
  form.elements.name.readOnly = mode === 'edit';
  form.elements.threshold.value = String(cfg.threshold ?? 0.50);
  form.elements.denylist.value = (cfg.extra_denylist || []).join(', ');
  $('bundle-allow-proposals').checked = cfg.allow_proposals !== false;
  $('bundle-include-unprojected').checked = Boolean(cfg.include_unprojected);
  $('bundle-include-readonly').checked = Boolean(cfg.include_readonly_roots);
  $('bundle-allow-sensitive').checked = Boolean(cfg.allow_sensitive_project);
  $('bundle-unprojected-label').textContent = `Include unprojected facts/decisions/lessons (${number.format(inv.unprojected_count || 0)})`;
  $('bundle-readonly-label').textContent = `Include read-only external wiki (${number.format(inv.readonly_count || 0)})`;

  for (const kindCb of form.querySelectorAll('input[name="kind"]')) {
    kindCb.checked = mode === 'edit' ? allowKinds.has(kindCb.value) : true;
  }

  const projRows = (inv.projects || []).map((p) => {
    const lbl = element('label', 'bundle-project-item');
    const left = element('span', 'bundle-project-left');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.name = 'project_pick';
    cb.value = p.slug;
    cb.dataset.sensitive = p.sensitive ? '1' : '0';
    cb.checked = selectedProjects.has(p.slug);
    cb.addEventListener('change', updateSensitiveWarningVisibility);
    left.append(cb, element('span', '', `${p.slug} (${p.count})`));
    lbl.append(left);
    if (p.sensitive) lbl.append(element('span', 'pill export-h-warn', 'Sensitive'));
    return lbl;
  });
  $('bundle-projects-list').replaceChildren(
    ...(projRows.length ? projRows : [element('span', 'field-hint', 'No tagged projects found yet.')]),
  );
  updateSensitiveWarningVisibility();
  $('bundle-dialog').showModal();
  if (mode === 'create') form.elements.name.focus();
}

$('exports-nav').addEventListener('click', () => {
  setWorkspace('exports');
  refreshExports();
});

$('export-back').addEventListener('click', () => {
  $('exports-view').classList.remove('show-reader');
  $('exports-list').querySelector('[aria-pressed="true"]')?.focus();
});

$('export-tabs').addEventListener('click', (event) => {
  const btn = event.target.closest('button[data-etab]');
  if (!btn) return;
  exportsState.tab = btn.dataset.etab;
  if (exportsState.detail) renderBundleDetail(exportsState.detail);
});

$('export-edit-scope-btn').addEventListener('click', () => {
  if (!exportsState.detail) return;
  openBundleDialog('edit', exportsState.detail);
});

$('export-stage-btn').addEventListener('click', () => {
  if (!exportsState.selectedName) return;
  runBundleMutation('Scan & stage complete', 'export_stage', { bundle: exportsState.selectedName });
});

$('export-approve-clean-btn').addEventListener('click', () => {
  if (!exportsState.selectedName) return;
  runBundleMutation('Approved all clean notes', 'export_approve', { bundle: exportsState.selectedName, all_clean: true });
});

$('export-revoke-all-btn').addEventListener('click', () => {
  if (!exportsState.selectedName) return;
  if (!window.confirm(`Revoke all exported notes from "${exportsState.selectedName}" immediately?`)) return;
  runBundleMutation('Revoked all notes', 'export_revoke', { bundle: exportsState.selectedName, revoke_all: true });
});

$('export-profile-text').addEventListener('input', () => {
  exportsState.profileDirty = true;
});

$('export-save-profile-btn').addEventListener('click', () => {
  if (!exportsState.selectedName) return;
  runBundleMutation('Saved sanitized profile', 'export_save_profile', {
    bundle: exportsState.selectedName,
    content: $('export-profile-text').value,
  });
});

$('new-bundle').addEventListener('click', () => openBundleDialog('create'));

$('bundle-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const formEl = event.currentTarget;
  const fd = new FormData(formEl);
  const projects = Array.from(formEl.querySelectorAll('input[name="project_pick"]:checked')).map((c) => c.value);
  const allow_kinds = fd.getAll('kind').map(String);
  const common = {
    projects,
    threshold: Number(fd.get('threshold') || 0.50),
    denylist: String(fd.get('denylist') || '').trim(),
    allow_kinds,
    allow_proposals: $('bundle-allow-proposals').checked,
    include_unprojected: $('bundle-include-unprojected').checked,
    include_readonly_roots: $('bundle-include-readonly').checked,
    allow_sensitive_project: $('bundle-allow-sensitive').checked,
  };
  const action = exportsState.dialogMode === 'edit' ? 'export_update_config' : 'export_init';
  const payload = exportsState.dialogMode === 'edit'
    ? { ...common, bundle: exportsState.selectedName, restage: true }
    : { ...common, name: String(fd.get('name') || '').trim() };

  submitForm($('bundle-dialog'), $('submit-bundle'), $('bundle-error'), async () => {
    const detail = await bridge.request(action, payload);
    $('bundle-dialog').close();
    notify(exportsState.dialogMode === 'edit' ? `Updated scope & restaged "${detail.name}"` : `Created bundle "${detail.name}"`);
    await refreshExports({ preferred: detail.name });
  });
});


async function promoteProposal(detail, proposal, inputs, alsoExport, scrubbed) {
  if (exportsState.busy) return;
  exportsState.busy = true;
  const params = {
    bundle: detail.name,
    proposal_id: proposal.id,
    use_scrubbed: scrubbed,
    also_export: alsoExport,
    force_blocked: false,
  };
  for (const key of Object.keys(inputs)) params[key] = inputs[key].value;
  try {
    let nextDetail;
    try {
      nextDetail = await bridge.request('export_inbox_promote', params);
    } catch (error) {
      if (!scrubbed && /\bblocked\b/i.test(error.message || '')) {
        if (!window.confirm('This proposal is blocked by privacy screening. Force promotion into Brain?')) return;
        nextDetail = await bridge.request('export_inbox_promote', { ...params, force_blocked: true });
      } else {
        throw error;
      }
    }
    exportsState.inboxDirty = false;
    notify('Proposal promoted');
    exportsState.selectedName = nextDetail.name;
    exportsState.detail = nextDetail;
    await refreshExports({ preferred: nextDetail.name });
  } catch (error) {
    notify(error.message);
  } finally {
    exportsState.busy = false;
  }
}

function renderInboxPane(detail) {
  const pane = $('export-inbox-pane');
  const enabled = detail.config?.allow_proposals !== false;
  const children = [element('p', 'export-inbox-notice', `Quarantined proposals: ${enabled ? 'enabled' : 'disabled'}. Review carefully before promotion. Change this in Edit scope.`)];
  if (!detail.inbox?.length) children.push(element('p', 'field-hint', 'Pi and OpenCode can submit proposals using safe_propose. Nothing enters Brain until you promote it here.'));
  for (const proposal of detail.inbox || []) {
    const screen = proposal.full_screen || {};
    const card = element('section', 'export-inbox-card');
    card.append(element('strong', '', 'Untrusted external proposal'), element('p', 'field-hint', `${proposal.id} · ${proposal.harness} · ${proposal.created_at} · ${proposal.kind}`));
    card.append(element('p', `pill export-action-${screen.action || 'block'}`, `${screen.action || 'unknown'} · p=${Number(screen.p_post_scrub || 0).toFixed(2)}`));
    const findings = [...(proposal.l1_screen?.entity_types || []), ...(proposal.l1_screen?.hard_block_rules || []), ...(screen.entity_types || []), ...(screen.hard_block_rules || [])];
    if (findings.length) card.append(element('p', 'field-hint', `Findings: ${[...new Set(findings)].join(', ')}`));
    const fields = element('div', 'export-inbox-fields');
    const inputs = {};
    for (const [key, label] of [['title', 'Title'], ['headline', 'Headline'], ['project', 'Project'], ['content', 'Content']]) {
      const wrap = element('label', '', label);
      const input = document.createElement(key === 'content' ? 'textarea' : 'input');
      input.value = proposal[key] || '';
      if (key === 'content') input.rows = 8;
      input.addEventListener('input', () => { exportsState.inboxDirty = true; });
      wrap.append(input); fields.append(wrap); inputs[key] = input;
    }
    card.append(fields);
    if (screen.diff_preview || (screen.scrubbed_body && screen.scrubbed_body !== proposal.content)) {
      const preview = buildPreviewDetails(screen);
      if (preview) card.append(preview);
    }
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
    const checkLabel = element('label', 'inline-check', `Also stage & approve into "${detail.name}"`); checkLabel.prepend(checkbox); card.append(checkLabel);
    const actions = element('div', 'export-profile-actions');
    const primary = element('button', 'button primary', screen.action === 'block' ? 'Force promote…' : 'Promote to Brain');
    primary.type = 'button';
    primary.addEventListener('click', () => promoteProposal(detail, proposal, inputs, checkbox.checked, false));
    actions.append(primary);
    if (screen.scrubbed_body && screen.scrubbed_body !== proposal.content) {
      const scrub = element('button', 'button secondary', 'Promote scrubbed');
      scrub.type = 'button';
      scrub.addEventListener('click', () => promoteProposal(detail, proposal, inputs, checkbox.checked, true));
      actions.append(scrub);
    }
    const discard = element('button', 'button secondary danger-ghost', 'Discard'); discard.type = 'button'; discard.addEventListener('click', () => runBundleMutation('Proposal discarded', 'export_inbox_discard', {bundle: detail.name, proposal_id: proposal.id})); actions.append(discard);
    card.append(actions); children.push(card);
  }
  pane.replaceChildren(...children);
}
