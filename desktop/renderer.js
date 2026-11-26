const $ = (id) => document.getElementById(id);
const bridge = window.brain;
const markdown = window.markdownit({ html: false, linkify: false });
markdown.validateLink = (href) => /^https?:\/\//i.test(href);
markdown.renderer.rules.image = (tokens, i) => {
  const alt = markdown.utils.escapeHtml(tokens[i].content || 'Image');
  return `<span class="markdown-image">${alt}</span>`;
};

const labels = { fact: 'Fact', decision: 'Decision', lesson: 'Lesson', journal: 'Journal', episode: 'Episode', project: 'Project', profile: 'Profile' };
const modes = { hybrid: 'Hybrid', fts: 'Keyword', 'hybrid+rerank': 'Hybrid · reranked', 'fts+rerank': 'Keyword · reranked' };
const number = new Intl.NumberFormat();
const day = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
const state = {
  bucket: '', project: '', query: '', items: [], selected: null, selection: '',
  listRequest: 0, readRequest: 0, headlineThreshold: 400, catalogRevision: '', listing: false, view: 'library',
};
const LIVE_REFRESH_MS = 5000;
let toastTimer;
let editing;
let busyDialog;
let contextText;
let checkingForUpdates = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const namespace = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(namespace, 'svg');
  const use = document.createElementNS(namespace, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.setAttribute('aria-hidden', 'true');
  svg.append(use);
  return svg;
}

function formatDay(value) {
  const date = new Date(`${value?.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.valueOf()) ? '' : day.format(date);
}

function excerpt(note) {
  return (note.snippet || note.excerpt || '')
    .replace(/^# [^\n]+\n*/, '')
    .replace(/^#{1,6} +/gm, '')
    .replace(/\*\*|`/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function notify(message) {
  const toast = $('toast');
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3200);
}

function libraryMessage(title, text) {
  const message = element('div', 'list-message');
  message.append(element('strong', '', title), element('p', '', text));
  $('results').replaceChildren(message);
}

function showScope() {
  const scope = state.bucket || 'all';
  const selections = document.querySelectorAll('.nav-item[data-scope], .nav-item[data-project]');
  for (const button of selections) {
    const active = state.view === 'library' && (state.project ? button.dataset.project === state.project : button.dataset.scope === scope);
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  $('library-title').textContent = state.project || { all: 'All memories', fact: 'Facts', episode: 'Episodes' }[scope];
  $('query').placeholder = state.project ? `Search ${state.project}…` : 'Search memories…';
  for (const option of $('kind').options) {
    const journal = option.value === 'journal';
    option.disabled = Boolean(option.value && state.bucket && (state.bucket === 'episode') !== journal);
    option.hidden = option.disabled;
  }
}

function renderNav(data) {
  state.headlineThreshold = data.fact_headline_threshold ?? state.headlineThreshold;
  for (const bucket of ['all', 'fact', 'episode']) {
    $(`count-${bucket}`).textContent = number.format(data.counts[bucket] || 0);
  }
  const projects = $('projects');
  const restoreFocus = projects.contains(document.activeElement);
  const buttons = data.projects.map(({ name, total }) => {
    const button = element('button', 'nav-item');
    button.dataset.project = name;
    button.title = name;
    button.append(icon('project'), element('span', '', name), element('span', 'nav-count', number.format(total)));
    button.addEventListener('click', () => chooseScope('', name));
    return button;
  });
  projects.replaceChildren(...(buttons.length ? buttons : [element('p', 'empty-projects', 'No projects yet')]));
  $('project-options').replaceChildren(...data.projects.map(({ name }) => {
    const option = element('option');
    option.value = name;
    return option;
  }));
  showScope();
  if (restoreFocus) buttons.find((button) => button.dataset.project === state.project)?.focus();
}

function memoryRow(item) {
  const row = element('div', '');
  row.setAttribute('role', 'listitem');
  const button = element('button', 'memory-row');
  button.dataset.id = item.id;
  button.setAttribute('aria-pressed', String(item.id === state.selection));
  const type = element('span', `memory-icon kind-${item.kind}`);
  type.append(icon(item.kind === 'episode' ? 'journal' : item.kind));
  const body = element('span', 'row-body');
  const meta = element('span', 'row-meta');
  meta.append(element('span', '', labels[item.kind] || item.kind));
  if (item.project && item.project !== state.project) meta.append(element('span', 'row-project', `· ${item.project}`));
  const formatted = formatDay(item.updated_at);
  if (formatted) meta.append(element('span', 'row-date', `· ${formatted}`));
  if (item.mode?.includes('rerank')) meta.append(element('span', `confidence confidence-${item.confidence}`, `${item.confidence[0].toUpperCase()}${item.confidence.slice(1)}`));
  const preview = item.mode ? excerpt(item) : item.headline || excerpt(item);
  body.append(element('span', 'row-title', item.title), element('span', 'row-excerpt', preview), meta);
  button.append(type, body);
  button.addEventListener('click', () => openMemory(item.id, true));
  row.append(button);
  return row;
}

function listFilters() {
  return { bucket: state.bucket, project: state.project, kind: $('kind').value, since: $('since').value, until: $('until').value };
}

function updateFilterUi() {
  $('clear-filters').hidden = !($('kind').value || $('since').value || $('until').value);
  $('dates-button').classList.toggle('secondary', Boolean($('since').value || $('until').value));
}

async function loadList({ refresh = false, append = false, preferred = '', reveal = false, live = false } = {}) {
  const serial = ++state.listRequest;
  const scope = listFilters();
  const searching = Boolean(state.query);
  const offset = append ? state.items.length : 0;
  const limit = live && state.items.length > 30 ? state.items.length : 30;
  state.listing = true;
  $('results').setAttribute('aria-busy', 'true');
  $('load-more').disabled = true;
  if (!append && !live) {
    $('library-subtitle').textContent = searching ? 'Searching…' : 'Loading memories…';
    $('search-warning').hidden = true;
  }
  updateFilterUi();
  try {
    let data;
    if (searching) data = await bridge.request('search', { ...scope, query: state.query, refresh });
    else data = await bridge.request('browse', { ...scope, refresh, offset, limit });
    if (serial !== state.listRequest) return;
    if (!append) state.catalogRevision = data.catalog_revision;
    const count = searching ? data.items.length : data.total;
    const noun = searching ? (count === 1 ? 'match' : 'matches') : (count === 1 ? 'memory' : 'memories');
    const prefix = searching && count === 30 ? 'Top ' : '';
    $('library-subtitle').replaceChildren(element('span', '', `${prefix}${number.format(count)} ${noun}`));
    if (data.mode) $('library-subtitle').append(element('span', 'mode', modes[data.mode] || data.mode));
    if (data.counts) renderNav(data);
    $('search-warning').hidden = !data.verify;
    state.items = append ? [...state.items, ...data.items] : data.items;
    $('pagination').hidden = searching || state.items.length >= (data.total || 0);
    if (append) $('results').append(...data.items.map(memoryRow));
    else {
      const scrollTop = live ? $('list-scroll').scrollTop : 0;
      const focusedId = live ? document.activeElement?.closest('.memory-row')?.dataset.id : '';
      if (state.items.length) $('results').replaceChildren(...state.items.map(memoryRow));
      else if (searching) libraryMessage('No matches in this scope', 'Try a different query or broaden your filters.');
      else libraryMessage('No memories here', $('clear-filters').hidden ? 'Use New memory to save something.' : 'Clear or change the filters.');
      if (focusedId) {
        const focused = [...$('results').querySelectorAll('.memory-row')].find((row) => row.dataset.id === focusedId);
        focused?.focus({ preventScroll: true });
      }
      $('list-scroll').scrollTop = scrollTop;
    }
    if (preferred) await openMemory(preferred, reveal);
    else if (live && state.selection) await refreshReader(serial);
    else if (!append && state.items.some(({ id }) => id === state.selection)) renderMatch();
    else if (!append && state.items.length && !narrow()) await openMemory(state.items[0].id);
    else if (!append) clearReader();
  } catch (error) {
    if (serial !== state.listRequest || live) return;
    if (append) notify(error.message);
    else {
      $('library-subtitle').textContent = searching ? 'Search unavailable' : 'Library unavailable';
      libraryMessage('Couldn’t load memories', error.message);
      $('pagination').hidden = true;
    }
  } finally {
    if (serial === state.listRequest) {
      state.listing = false;
      $('results').setAttribute('aria-busy', 'false');
      $('load-more').disabled = false;
    }
  }
}

async function refreshReader(serial) {
  const previous = state.selected;
  if (!previous) return;
  try {
    const note = await bridge.request('read', { id: previous.id, if_revision: previous.revision });
    if (serial !== state.listRequest || state.selected !== previous) return;
    if (note.missing) {
      clearReader();
    } else if (note.unchanged) {
      renderMatch();
    } else {
      const raw = !$('source').hidden;
      const scrollTop = $('reader-scroll').scrollTop;
      state.selected = note;
      renderMemory(note);
      setView(raw);
      $('reader-scroll').scrollTop = scrollTop;
    }
  } catch {
    // A failed update keeps the last readable source on screen.
  }
}

async function checkForUpdates() {
  if (document.hidden || document.querySelector('dialog[open]')) return;
  if (state.view === 'board') {
    await refreshBoard({ quiet: true });
    return;
  }
  if (state.view === 'exports') {
    if (typeof refreshExports === 'function') await refreshExports({ quiet: true });
    return;
  }
  if (checkingForUpdates || state.listing) return;
  checkingForUpdates = true;
  const serial = state.listRequest;
  try {
    const { catalog_revision: revision } = await bridge.request('changes');
    if (state.view === 'library' && serial === state.listRequest && revision !== state.catalogRevision && !document.querySelector('dialog[open]')) {
      await loadList({ live: true });
    }
  } catch {
    // A later poll retries. Refresh library reports any persistent error.
  } finally {
    checkingForUpdates = false;
  }
}

function setWorkspace(view) {
  state.view = view;
  const board = view === 'board';
  const exportsMode = view === 'exports';
  const library = view === 'library';
  $('panes').hidden = !library;
  $('search-form').hidden = !library;
  $('new-memory').hidden = !library;
  $('board-view').hidden = !board;
  $('board-filter').hidden = !board;
  $('new-assignment').hidden = !board;
  $('exports-view').hidden = !exportsMode;
  $('new-bundle').hidden = !exportsMode;

  $('board-nav').classList.toggle('active', board);
  if (board) $('board-nav').setAttribute('aria-current', 'page');
  else $('board-nav').removeAttribute('aria-current');

  $('exports-nav').classList.toggle('active', exportsMode);
  if (exportsMode) $('exports-nav').setAttribute('aria-current', 'page');
  else $('exports-nav').removeAttribute('aria-current');

  const label = board ? 'Refresh board' : (exportsMode ? 'Refresh exports' : 'Refresh library');
  $('refresh').setAttribute('aria-label', label);
  $('refresh').title = `${label} now`;
  showScope();
}

function chooseScope(bucket, project = '') {
  setWorkspace('library');
  state.bucket = bucket;
  state.project = project;
  $('kind').value = '';
  closeNarrowReader();
  showScope();
  loadList({ refresh: !state.query });
}

function narrow() {
  return window.matchMedia('(max-width: 930px)').matches;
}

function markSelection() {
  for (const row of document.querySelectorAll('.memory-row')) {
    row.setAttribute('aria-pressed', String(row.dataset.id === state.selection));
  }
}

function clearReader() {
  ++state.readRequest;
  state.selection = '';
  state.selected = null;
  markSelection();
  closeNarrowReader();
  $('reader-content').hidden = true;
  $('reader-empty').hidden = false;
  $('reader-empty-title').textContent = 'Open a memory';
  $('reader-empty-copy').textContent = 'Choose a memory to read its source.';
}

function closeNarrowReader(restoreFocus = false) {
  $('panes').classList.remove('show-reader');
  if (restoreFocus) {
    const row = [...document.querySelectorAll('.memory-row')].find((button) => button.dataset.id === state.selection);
    (row || $('query')).focus();
  }
}

async function openMemory(id, reveal = false) {
  const serial = ++state.readRequest;
  state.selection = id;
  state.selected = null;
  markSelection();
  if (reveal) $('panes').classList.add('show-reader');
  $('reader-content').hidden = true;
  $('reader-empty').hidden = false;
  $('reader-empty-title').textContent = 'Reading memory…';
  $('reader-empty-copy').textContent = '';
  try {
    const note = await bridge.request('read', { id });
    if (serial !== state.readRequest) return;
    state.selected = note;
    renderMemory(note);
    if (reveal && narrow()) $('back').focus();
  } catch (error) {
    if (serial !== state.readRequest) return;
    $('reader-empty-title').textContent = 'Couldn’t open this memory';
    $('reader-empty-copy').textContent = error.message;
    if (reveal && narrow()) {
      closeNarrowReader(true);
      notify(error.message);
    }
  }
}

function renderMemory(note) {
  $('source-path').textContent = note.rel_path;
  $('copy-id').setAttribute('aria-label', `Copy memory ID ${note.id}`);
  $('copy-id').title = `Copy memory ID · ${note.id}`;
  $('memory-title').textContent = note.title;
  $('memory-headline').textContent = note.headline || '';
  $('memory-headline').hidden = !note.headline || note.headline === note.title;
  const kind = element('span', `pill kind-${note.kind}`);
  kind.append(icon(note.kind === 'episode' ? 'journal' : note.kind), document.createTextNode(labels[note.kind] || note.kind));
  const details = $('memory-details');
  details.replaceChildren(kind);
  for (const value of [note.project, formatDay(note.updated_at), note.epistemic, note.author, note.provenance]) {
    if (value) details.append(element('span', '', `· ${value}`));
  }
  if (note.readonly) details.append(element('span', 'pill readonly-tag', 'Read-only source'));
  $('tags').replaceChildren(...note.tags.map((tag) => element('span', 'tag', tag)));
  $('tags').hidden = note.tags.length === 0;
  $('edit').hidden = note.readonly || note.kind === 'episode';
  $('archive').hidden = note.readonly;
  const journal = note.kind === 'journal';
  $('edit').querySelector('span').textContent = journal ? 'New journal entry' : note.subject && note.predicate ? 'Update value' : 'Edit';
  const lines = note.markdown.split('\n');
  if (lines[0]?.startsWith('# ') && lines[0].slice(2).trim() === note.title) lines.shift();
  $('markdown').innerHTML = markdown.render(lines.join('\n'));
  $('source').textContent = note.raw;
  $('reader-empty').hidden = true;
  $('reader-content').hidden = false;
  setView(false);
  $('reader-scroll').scrollTop = 0;
}

function renderMatch() {
  const item = state.items.find(({ id }) => id === state.selection);
  const match = $('matched-section');
  const hasConflict = Boolean(item?.conflicts_with?.length);
  match.hidden = (!item?.snippet && !hasConflict) || !$('source').hidden;
  if (!match.hidden) {
    const nodes = [];
    if (item.snippet) {
      const heading = item.heading && item.heading !== item.title ? `Matched in ${item.heading}` : 'Matched excerpt';
      nodes.push(element('strong', '', heading), element('p', '', excerpt(item)));
    }
    if (hasConflict) {
      const peers = item.conflicts_with.slice(0, 2).map((c) => `${c.id} (${c.updated_at})`).join(', ');
      nodes.push(element('strong', '', 'Potential conflict'), element('p', '', `Differs from ${peers} — verify newer/scoped truth.`));
    }
    match.replaceChildren(...nodes);
  }
}

function setView(raw) {
  $('source').hidden = !raw;
  $('markdown').hidden = raw;
  $('read-view').classList.toggle('active', !raw);
  $('markdown-view').classList.toggle('active', raw);
  $('read-view').setAttribute('aria-pressed', String(!raw));
  $('markdown-view').setAttribute('aria-pressed', String(raw));
  renderMatch();
}

function updateCompose() {
  const form = $('compose-form');
  const kind = editing?.kind || $('note-kind').value;
  const atomic = kind === 'atomic' || Boolean(editing?.subject && editing?.predicate);
  const journal = kind === 'journal';
  const project = kind === 'project';
  $('capture-kind').hidden = Boolean(editing);
  $('capture-title').hidden = Boolean(editing);
  $('capture-meta').hidden = Boolean(editing) || journal || project;
  $('capture-atomic').hidden = Boolean(editing) || !atomic;
  form.elements.title.required = !editing && !journal && !atomic;
  form.elements.subject.required = !editing && atomic;
  form.elements.predicate.required = !editing && atomic;
  $('title-label').textContent = project ? 'Project name' : atomic || journal ? 'Title (optional)' : 'Title';
  $('content-label').textContent = atomic ? 'Value' : 'Markdown';
  const hint = atomic ? (editing ? 'Saving records the previous value as superseded.' : 'A subject and predicate identify one fact. Open that fact to change its value.')
    : journal ? 'Appends to today’s journal.' : '';
  $('compose-hint').textContent = hint;
  $('compose-hint').hidden = !hint;
  $('save-memory').textContent = editing ? 'Save changes' : journal ? 'Add entry' : project ? 'Create project' : 'Save memory';
  updateHeadlineField();
}

function updateHeadlineField() {
  const form = $('compose-form');
  const kind = editing?.kind || $('note-kind').value;
  const fact = kind === 'fact' || kind === 'atomic';
  const durable = kind !== 'journal' && kind !== 'episode';
  const required = fact && [...form.elements.content.value.trim()].length > state.headlineThreshold;
  $('capture-headline').hidden = !durable;
  form.elements.headline.required = required;
  $('headline-label').textContent = required ? 'Headline (required)' : 'Headline (optional)';
  $('headline-hint').textContent = required
    ? `Add a one-line headline for facts over ${state.headlineThreshold} characters.`
    : 'Brain can derive a headline when this field is blank.';
}

function showCompose(kind, note = null) {
  const form = $('compose-form');
  form.reset();
  editing = note;
  $('note-kind').value = kind;
  form.elements.project.value = state.project;
  $('compose-error').hidden = true;
  const atomic = Boolean(note?.subject && note?.predicate);
  $('compose-title').textContent = note ? (atomic ? 'Update fact value' : 'Edit memory') : kind === 'project' ? 'New project' : kind === 'journal' ? 'New journal entry' : 'New memory';
  if (note) {
    form.elements.content.value = atomic ? note.value : note.markdown;
    form.elements.headline.value = note.headline || '';
  }
  updateCompose();
  $('compose-dialog').showModal();
  (note ? form.elements.content : form.elements.title).focus();
}

async function submitForm(dialog, button, errorNode, action) {
  if (busyDialog) return;
  busyDialog = dialog;
  button.disabled = true;
  errorNode.hidden = true;
  try {
    await action();
  } catch (error) {
    errorNode.textContent = error.message;
    errorNode.hidden = false;
  } finally {
    busyDialog = undefined;
    button.disabled = false;
  }
}

function renderStatus(details) {
  const cards = element('div', 'status-cards');
  for (const [label, value] of [['Memories', details.index.docs], ['Search chunks', details.index.chunks], ['Embedded chunks', details.index.embedded]]) {
    const card = element('div');
    card.append(element('strong', '', number.format(value)), element('span', '', label));
    cards.append(card);
  }
  const usage = element('dl', 'status-list');
  for (const [tool, count] of Object.entries(details.usage)) {
    usage.append(element('dt', '', tool), element('dd', '', number.format(count)));
  }
  const version = element('p', 'field-hint', `Brain ${details.version} · ${details.root}`);
  $('info-body').replaceChildren(version, cards, element('strong', '', 'MCP calls'), usage);
  if (details.last_call) $('info-body').append(element('p', 'field-hint', `Last call ${formatDay(details.last_call)}`));
}

async function showInfo(action, title) {
  $('info-title').textContent = title;
  $('info-body').textContent = 'Loading…';
  $('copy-context').hidden = true;
  contextText = '';
  const dialog = $('info-dialog');
  const token = Symbol();
  dialog.request = token;
  dialog.showModal();
  try {
    const data = await bridge.request(action, { project: state.project });
    if (!dialog.open || dialog.request !== token) return;
    if (action === 'status') renderStatus(data);
    else {
      contextText = data.markdown;
      const context = element('article', 'markdown');
      context.innerHTML = markdown.render(contextText);
      $('info-body').replaceChildren(context);
      $('copy-context').hidden = false;
    }
  } catch (error) {
    if (dialog.open && dialog.request === token) $('info-body').textContent = error.message;
  }
}

async function copy(value, message) {
  try {
    await bridge.copy(value);
    notify(message);
  } catch (error) {
    notify(error.message);
  }
}

function updateSearchInput() {
  $('clear-search').hidden = !$('query').value && !state.query;
  $('search-shortcut').hidden = !$('clear-search').hidden;
}

function resetSearch() {
  $('query').value = '';
  state.query = '';
  updateSearchInput();
  closeNarrowReader();
  loadList({ refresh: true });
}

for (const button of document.querySelectorAll('[data-scope]')) {
  button.addEventListener('click', () => chooseScope(button.dataset.scope === 'all' ? '' : button.dataset.scope));
}
for (const field of ['kind', 'since', 'until']) $(field).addEventListener('change', () => loadList());
$('dates-button').addEventListener('click', () => {
  const open = $('date-filters').hidden;
  $('date-filters').hidden = !open;
  $('dates-button').setAttribute('aria-expanded', String(open));
});
$('clear-filters').addEventListener('click', () => {
  for (const field of ['kind', 'since', 'until']) $(field).value = '';
  loadList();
});
$('search-form').addEventListener('submit', (event) => {
  event.preventDefault();
  state.query = $('query').value.trim();
  updateSearchInput();
  closeNarrowReader();
  loadList({ refresh: !state.query });
});
$('query').addEventListener('input', updateSearchInput);
$('clear-search').addEventListener('click', () => { resetSearch(); $('query').focus(); });
$('refresh').addEventListener('click', () => {
  if (state.view === 'board') refreshBoard();
  else if (state.view === 'exports' && typeof refreshExports === 'function') refreshExports();
  else loadList({ refresh: true, preferred: state.selection });
});
$('load-more').addEventListener('click', () => loadList({ append: true }));
$('new-memory').addEventListener('click', () => showCompose(state.bucket === 'episode' ? 'journal' : 'fact'));
$('new-project').addEventListener('click', () => { setWorkspace('library'); showCompose('project'); });
$('note-kind').addEventListener('change', updateCompose);
$('compose-form').elements.content.addEventListener('input', updateHeadlineField);
$('back').addEventListener('click', () => closeNarrowReader(true));
$('read-view').addEventListener('click', () => setView(false));
$('markdown-view').addEventListener('click', () => setView(true));
$('copy-id').addEventListener('click', () => copy(state.selected.id, 'Memory ID copied'));
$('copy-markdown').addEventListener('click', () => copy(state.selected.raw, 'Markdown copied'));
$('context').addEventListener('click', () => showInfo('context', 'Session context'));
$('status').addEventListener('click', () => showInfo('status', 'Index & usage'));
$('copy-context').addEventListener('click', () => copy(contextText, 'Session context copied'));
$('edit').addEventListener('click', () => {
  const note = state.selected;
  if (note.kind === 'journal') showCompose('journal');
  else showCompose(note.kind, note);
});
$('archive').addEventListener('click', () => {
  $('archive-error').hidden = true;
  $('archive-copy').textContent = `Archive “${state.selected.title}” from the shared library?`;
  $('archive-dialog').showModal();
});

$('compose-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = Object.fromEntries(new FormData(event.currentTarget));
  submitForm($('compose-dialog'), $('save-memory'), $('compose-error'), async () => {
    const result = editing
      ? await bridge.request('edit', { id: editing.id, revision: editing.revision, content: form.content, headline: form.headline })
      : await bridge.request('create', form);
    $('compose-dialog').close();
    notify(editing ? 'Changes saved' : form.kind === 'journal' ? 'Journal entry added' : 'Memory saved');
    loadList({ preferred: result.id, reveal: true });
  });
});

$('archive-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const { id, revision } = state.selected;
  submitForm($('archive-dialog'), $('confirm-archive'), $('archive-error'), async () => {
    await bridge.request('archive', { id, revision });
    $('archive-dialog').close();
    clearReader();
    notify('Memory archived');
    loadList();
  });
});

for (const dialog of document.querySelectorAll('dialog')) {
  for (const button of dialog.querySelectorAll('.close-dialog')) {
    button.addEventListener('click', () => { if (busyDialog !== dialog) dialog.close(); });
  }
  dialog.addEventListener('cancel', (event) => { if (busyDialog === dialog) event.preventDefault(); });
}

for (const article of [$('markdown'), $('info-body')]) {
  article.addEventListener('click', (event) => {
    const anchor = event.target.closest('a[href]');
    if (!anchor) return;
    event.preventDefault();
    bridge.openLink(anchor.href).catch((error) => notify(error.message));
  });
}

$('results').addEventListener('keydown', (event) => {
  if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
  const row = event.target.closest('[role="listitem"]');
  const next = event.key === 'ArrowDown' ? row?.nextElementSibling : row?.previousElementSibling;
  if (next) { event.preventDefault(); next.querySelector('button')?.focus(); }
});

document.addEventListener('keydown', (event) => {
  const modifier = bridge.platform === 'darwin' ? event.metaKey : event.ctrlKey;
  if (modifier && event.key.toLowerCase() === 'k' && !document.querySelector('dialog[open]')) {
    event.preventDefault();
    const input = $(state.view === 'board' ? 'board-actor-filter' : 'query');
    input.focus();
    input.select();
  } else if (modifier && event.key === 'Enter' && $('compose-dialog').open) {
    event.preventDefault();
    $('compose-form').requestSubmit();
  } else if (event.key === 'Escape' && event.target === $('query') && state.query) {
    resetSearch();
  }
});

if (bridge.platform !== 'darwin') $('search-shortcut').textContent = 'Ctrl K';
loadList({ refresh: true });
window.setInterval(checkForUpdates, LIVE_REFRESH_MS);
window.addEventListener('focus', checkForUpdates);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) checkForUpdates();
});
