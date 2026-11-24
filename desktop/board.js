const assignmentStates = {
  assigned: 'Assigned', in_progress: 'In progress', blocked: 'Blocked', in_review: 'In review', done: 'Done',
};
const postTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const board = { revision: -1, listRequest: 0, readRequest: 0, thread: null, author: '', loading: false, posting: false };
let boardFilterTimer;

function statusPill(status) {
  return element('span', `pill board-state-${status}`, assignmentStates[status]);
}

function assignmentRow(task) {
  const row = element('div');
  row.setAttribute('role', 'listitem');
  const button = element('button', 'memory-row');
  button.dataset.assignment = task.id;
  button.setAttribute('aria-pressed', String(task.id === board.thread?.id));
  const glyph = element('span', `memory-icon board-state-${task.status}`);
  glyph.append(icon('board'));
  const body = element('span', 'row-body');
  const meta = element('span', 'row-meta');
  meta.append(statusPill(task.status), element('span', 'row-project', [`#${task.id}`, task.project].filter(Boolean).join(' · ')));
  body.append(element('span', 'row-title', task.title),
    element('span', 'board-assignees', `${task.supervisor} → ${task.assignee}`), meta);
  button.append(glyph, body);
  button.addEventListener('click', () => openAssignment(task.id, true));
  row.append(button);
  return row;
}

function renderBoardRows(assignments) {
  const container = $('board-list');
  const active = document.activeElement?.dataset.assignment;
  const offset = $('board-list-scroll').scrollTop;
  const noun = assignments.length === 1 ? 'assignment' : 'assignments';
  $('board-subtitle').textContent = `${number.format(assignments.length)} ${noun}`;
  if (assignments.length) {
    container.replaceChildren(...assignments.map(assignmentRow));
  } else {
    const msg = element('div', 'list-message');
    msg.append(element('strong', '', 'No assignments here'), element('p', '',
      $('board-actor-filter').value || $('board-status-filter').value ? 'Try a different filter.' : 'Use New assignment to delegate work.'));
    container.replaceChildren(msg);
  }
  if (active) [...container.querySelectorAll('button')].find((row) => row.dataset.assignment === active)?.focus({ preventScroll: true });
  $('board-list-scroll').scrollTop = offset;
}

async function refreshBoard({ quiet = false, preferred = 0 } = {}) {
  if (quiet && (board.loading || board.posting)) return;
  const serial = ++board.listRequest;
  board.loading = true;
  try {
    const data = await bridge.request('board_list', { actor: $('board-actor-filter').value, status: $('board-status-filter').value });
    if (state.view !== 'board' || serial !== board.listRequest) return;
    if (quiet && data.revision === board.revision) return;
    board.revision = data.revision;
    renderBoardRows(data.assignments);
    const opened = board.thread;
    const selected = data.assignments.find(({ id }) => id === opened?.id);
    if (preferred) await openAssignment(preferred, true);
    else if (opened && (!quiet || selected?.revision !== opened.revision)) await openAssignment(opened.id);
    else if (!opened && data.assignments.length && !narrow()) await openAssignment(data.assignments[0].id);
  } catch (error) {
    if (!quiet && serial === board.listRequest) notify(error.message);
  } finally {
    if (serial === board.listRequest) board.loading = false;
  }
}

async function openAssignment(id, reveal = false) {
  const serial = ++board.readRequest;
  try {
    const thread = await bridge.request('board_read', { id });
    if (state.view !== 'board' || serial !== board.readRequest) return;
    renderAssignment(thread);
    if (reveal) {
      $('board-view').classList.add('show-reader');
      if (narrow()) $('board-back').focus();
    }
  } catch (error) {
    if (serial === board.readRequest) notify(error.message);
  }
}

function renderAssignment(thread) {
  const sameThread = board.thread?.id === thread.id;
  if (sameThread && board.thread.revision === thread.revision) return;
  const reader = $('thread-scroll');
  const scrollTop = reader.scrollTop;
  board.thread = thread;
  const form = $('board-reply-form');
  if (!sameThread) {
    form.reset();
    form.elements.author.value = board.author;
    $('board-reply-error').hidden = true;
  }
  $('thread-id').textContent = `Assignment #${thread.id}`;
  $('thread-title').textContent = thread.title;
  $('thread-state').replaceChildren(statusPill(thread.status));
  const roles = [['Supervisor', thread.supervisor], ['Assignee', thread.assignee], ['Project', thread.project]];
  $('thread-roles').replaceChildren(...roles.filter(([, value]) => value).flatMap(([role, value]) => [element('dt', '', role), element('dd', '', value)]));
  const identities = [...new Set([thread.supervisor, thread.assignee])];
  $('board-identities').replaceChildren(...identities.map((value) => {
    const option = element('option');
    option.value = value;
    return option;
  }));
  const posts = thread.posts.map((post, i) => {
    const item = element('div', i === 0 ? 'thread-post thread-brief' : 'thread-post');
    const header = element('div', 'thread-post-header');
    header.append(element('strong', '', post.author));
    if (i === 0) header.append(element('span', 'pill board-state-assigned', 'Brief'));
    else if (post.status) header.append(statusPill(post.status));
    header.append(element('time', '', postTime.format(new Date(post.created_at))));
    item.append(header);
    if (post.message) item.append(element('p', '', post.message));
    return item;
  });
  $('thread-posts').replaceChildren(...posts);
  for (const button of $('board-list').querySelectorAll('button[data-assignment]')) {
    button.setAttribute('aria-pressed', String(Number(button.dataset.assignment) === thread.id));
  }
  $('thread-empty').hidden = true;
  $('thread-content').hidden = false;
  updateBoardActions();
  reader.scrollTop = sameThread ? scrollTop : 0;
}

function updateBoardActions() {
  const form = $('board-reply-form');
  const menu = form.elements.status;
  const former = menu.value;
  const actor = form.elements.author.value.trim().toLowerCase();
  const actions = board.thread?.actions.filter((action) => action.actor.toLowerCase() === actor) ?? [];
  menu.replaceChildren(new Option('Reply', ''), ...actions.map((action) => new Option(action.label, action.status)));
  const chosen = actions.find((action) => action.status === former);
  menu.value = chosen?.status || '';
  form.elements.message.required = !chosen || chosen.needs_message;
  $('board-post').textContent = chosen?.label || 'Post update';
}

$('board-nav').addEventListener('click', () => { setWorkspace('board'); refreshBoard(); });
$('board-status-filter').addEventListener('change', () => refreshBoard());
$('board-actor-filter').addEventListener('input', () => {
  clearTimeout(boardFilterTimer);
  boardFilterTimer = setTimeout(() => refreshBoard(), 250);
});
$('board-back').addEventListener('click', () => {
  $('board-view').classList.remove('show-reader');
  $('board-list').querySelector('[aria-pressed="true"]')?.focus();
});

$('new-assignment').addEventListener('click', () => {
  const form = $('assignment-form');
  form.reset();
  form.elements.supervisor.value = board.author;
  form.elements.project.value = state.project;
  $('assignment-error').hidden = true;
  $('assignment-dialog').showModal();
  form.elements.title.focus();
});

$('assignment-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const fields = Object.fromEntries(new FormData(event.currentTarget));
  submitForm($('assignment-dialog'), $('submit-assignment'), $('assignment-error'), async () => {
    const assignment = await bridge.request('board_assign', fields);
    board.author = fields.supervisor.trim();
    $('assignment-dialog').close();
    notify(`Assignment #${assignment.id} opened`);
    await refreshBoard({ preferred: assignment.id });
  });
});

const replyForm = $('board-reply-form');
replyForm.elements.author.addEventListener('input', () => {
  board.author = replyForm.elements.author.value.trim();
  updateBoardActions();
});
replyForm.elements.status.addEventListener('change', updateBoardActions);
replyForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (board.posting || !board.thread) return;
  const thread = board.thread.id;
  const fields = Object.fromEntries(new FormData(event.currentTarget));
  board.posting = true;
  $('board-post').disabled = true;
  $('board-reply-error').hidden = true;
  try {
    await bridge.request('board_post', { id: thread, ...fields });
    if (thread === board.thread?.id && replyForm.elements.message.value === fields.message) {
      replyForm.elements.message.value = '';
      replyForm.elements.status.value = '';
    }
    await refreshBoard();
  } catch (error) {
    $('board-reply-error').textContent = error.message;
    $('board-reply-error').hidden = false;
  } finally {
    board.posting = false;
    $('board-post').disabled = false;
  }
});
