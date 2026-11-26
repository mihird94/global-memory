const assignmentStates = {
  assigned: 'Assigned', in_progress: 'In progress', blocked: 'Blocked', in_review: 'In review', done: 'Done',
  cancelled: 'Cancelled', open: 'Open', resolved: 'Resolved', declined: 'Declined', closed: 'Closed',
};
const threadKinds = {
  discussion: 'Discussion', request: 'Request', assignment: 'Assignment', broadcast: 'Broadcast',
};
const messageKinds = {
  message: 'Message', brief: 'Brief', question: 'Question', answer: 'Answer',
  proposal: 'Proposal', decision: 'Decision', handoff: 'Handoff', status: 'Status', ack: 'Ack',
};
const postTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const board = {
  revision: -1, listSignature: '', listRequest: 0, readRequest: 0, thread: null, author: '', loading: false, posting: false, agents: [],
};
let boardFilterTimer;

function statusPill(status) {
  return element('span', `pill board-state-${status}`, assignmentStates[status] || status);
}

function kindPill(kind) {
  return element('span', `pill board-kind-${kind}`, threadKinds[kind] || kind);
}

function participantSummary(task) {
  if (task.kind === 'assignment') return `${task.supervisor} → ${task.assignee}`;
  if (task.kind === 'broadcast') {
    const targets = (task.participants || []).filter((p) => p.toLowerCase() !== (task.created_by || '').toLowerCase());
    return `${task.created_by} → ${targets.length ? targets.join(', ') : '*'}`;
  }
  const parts = task.participants || [];
  return parts.length ? parts.join(', ') : task.created_by;
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
  meta.append(kindPill(task.kind || 'assignment'), statusPill(task.status));
  if (task.priority === 'high' || task.priority === 'urgent') {
    meta.append(element('span', `pill board-priority-${task.priority}`, task.priority));
  }
  if (task.unread_count > 0) {
    meta.append(element('span', 'pill board-unread-pill', `${task.unread_count} new`));
  }
  const tagBits = [`#${task.id}`, task.channel ? `#${task.channel}` : '', task.project].filter(Boolean);
  meta.append(element('span', 'row-project', tagBits.join(' · ')));
  body.append(element('span', 'row-title', task.title),
    element('span', 'board-assignees', participantSummary(task)), meta);
  button.append(glyph, body);
  button.addEventListener('click', () => openAssignment(task.id, true));
  row.append(button);
  return row;
}

function renderBoardAgents(agents) {
  const container = $('board-agents');
  if (!agents || !agents.length) {
    container.hidden = true;
    container.replaceChildren();
    return;
  }
  container.hidden = false;
  const chips = agents.map((ag) => {
    const chip = element('button', `agent-chip agent-status-${ag.status}`);
    chip.type = 'button';
    chip.title = ag.summary || `${ag.actor} (${ag.status})`;
    chip.append(element('span', 'agent-dot'), element('span', '', ag.actor));
    chip.addEventListener('click', () => {
      const input = $('board-actor-filter');
      input.value = input.value.trim().toLowerCase() === ag.actor.toLowerCase() ? '' : ag.actor;
      refreshBoard();
    });
    return chip;
  });
  container.replaceChildren(...chips);
}

function renderBoardRows(threads) {
  const container = $('board-list');
  const active = document.activeElement?.dataset.assignment;
  const offset = $('board-list-scroll').scrollTop;
  const noun = threads.length === 1 ? 'thread' : 'threads';
  $('board-subtitle').textContent = `${number.format(threads.length)} ${noun}`;
  if (threads.length) {
    container.replaceChildren(...threads.map(assignmentRow));
  } else {
    const msg = element('div', 'list-message');
    msg.append(element('strong', '', 'No threads here'), element('p', '',
      $('board-actor-filter').value || $('board-status-filter').value || $('board-kind-filter').value
        ? 'Try a different filter.' : 'Use New thread to start a discussion, request, or assignment.'));
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
    const actor = $('board-actor-filter').value.trim();
    const [data, agentsRes] = await Promise.all([
      bridge.request('board_list', {
        actor,
        status: $('board-status-filter').value,
        kind: $('board-kind-filter').value,
        include_broadcasts: Boolean(actor),
      }),
      bridge.request('board_agents', {}),
    ]);
    if (state.view !== 'board' || serial !== board.listRequest) return;
    board.agents = agentsRes.agents || [];
    renderBoardAgents(board.agents);
    const threads = data.threads || data.assignments || [];
    const listSig = threads.map((t) => `${t.id}:${t.revision}:${t.unread_count || 0}:${t.status}`).join('|');
    if (!quiet || data.revision !== board.revision || listSig !== board.listSignature) {
      board.revision = data.revision;
      board.listSignature = listSig;
      renderBoardRows(threads);
    }
    const opened = board.thread;
    if (preferred) await openAssignment(preferred, true);
    else if (opened) await openAssignment(opened.id);
    else if (threads.length && !narrow()) await openAssignment(threads[0].id);
  } catch (error) {
    if (!quiet && serial === board.listRequest) notify(error.message);
  } finally {
    if (serial === board.listRequest) board.loading = false;
  }
}

async function openAssignment(id, reveal = false) {
  const serial = ++board.readRequest;
  try {
    const actor = board.author || $('board-actor-filter').value.trim();
    const thread = await bridge.request('board_read', { id, actor, mark_read: false });
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

function setReplyTarget(post) {
  const form = $('board-reply-form');
  if (!post) {
    form.elements.reply_to.value = '';
    $('board-reply-to-bar').hidden = true;
    return;
  }
  form.elements.reply_to.value = String(post.id);
  $('board-reply-to-label').textContent = `Replying to #${post.id} (${post.author})`;
  $('board-reply-to-bar').hidden = false;
  form.elements.message.focus();
}

function _ackSignature(thread) {
  return (thread?.participant_roles || []).map((p) => `${p.actor}:${p.acked_id}:${p.last_read_id}`).join(',');
}

function renderAssignment(thread) {
  const sameThread = board.thread?.id === thread.id;
  if (sameThread && board.thread.revision === thread.revision && _ackSignature(board.thread) === _ackSignature(thread)) return;
  const reader = $('thread-scroll');
  const scrollTop = reader.scrollTop;
  board.thread = thread;
  const form = $('board-reply-form');
  if (!sameThread) {
    form.reset();
    form.elements.author.value = board.author;
    setReplyTarget(null);
    $('board-reply-error').hidden = true;
  }
  $('thread-id').textContent = `${threadKinds[thread.kind] || 'Thread'} #${thread.id}`;
  $('thread-title').textContent = thread.title;
  $('thread-state').replaceChildren(kindPill(thread.kind), statusPill(thread.status));
  $('board-ack-btn').hidden = !board.author && !$('board-actor-filter').value.trim();

  const roles = [];
  if (thread.kind === 'assignment') {
    roles.push(['Supervisor', thread.supervisor], ['Assignee', thread.assignee]);
  } else {
    roles.push(['Initiator', thread.created_by]);
    const others = (thread.participant_roles || []).filter((p) => p.actor.toLowerCase() !== thread.created_by.toLowerCase());
    if (others.length) {
      const formatted = others.map((p) => (p.acked_id >= thread.revision && thread.revision > 0 ? `${p.actor} ✓` : p.actor));
      roles.push(['Participants', formatted.join(', ')]);
    }
  }
  if (thread.channel) roles.push(['Channel', `#${thread.channel}`]);
  if (thread.project) roles.push(['Project', thread.project]);
  if (thread.priority && thread.priority !== 'normal') roles.push(['Priority', thread.priority]);
  $('thread-roles').replaceChildren(...roles.filter(([, value]) => value).flatMap(([role, value]) => [element('dt', '', role), element('dd', '', value)]));

  const identities = [...new Set([
    thread.created_by, thread.supervisor, thread.assignee,
    ...(thread.participants || []).filter((p) => p !== '*'),
    ...(board.agents || []).map((a) => a.actor),
  ].filter(Boolean))];
  $('board-identities').replaceChildren(...identities.map((value) => {
    const option = element('option');
    option.value = value;
    return option;
  }));

  const posts = thread.posts.map((post, i) => {
    const item = element('div', i === 0 ? 'thread-post thread-brief' : 'thread-post');
    const header = element('div', 'thread-post-header');
    header.append(element('strong', '', post.author));
    if (post.status) header.append(statusPill(post.status));
    else if (post.kind && post.kind !== 'message') {
      header.append(element('span', `pill board-msg-${post.kind}`, messageKinds[post.kind] || post.kind));
    }
    if (post.reply_to) {
      header.append(element('span', 'thread-reply-ref', `↪ #${post.reply_to}`));
    }
    if (post.to && post.to.length) {
      header.append(element('span', 'thread-to-ref', `→ ${post.to.join(', ')}`));
    }
    header.append(element('time', '', postTime.format(new Date(post.created_at))));
    const replyBtn = element('button', 'text-button thread-reply-btn', 'Reply');
    replyBtn.type = 'button';
    replyBtn.addEventListener('click', () => setReplyTarget(post));
    header.append(replyBtn);
    item.append(header);

    if (post.message) item.append(element('p', '', post.message));
    if (post.refs && post.refs.length) {
      const refsRow = element('div', 'thread-refs');
      for (const ref of post.refs) {
        const chip = element('span', 'tag-chip', ref);
        if (ref.startsWith('memory:')) {
          chip.classList.add('clickable');
          chip.title = 'Open memory in Library';
          chip.addEventListener('click', () => {
            const memId = ref.slice('memory:'.length);
            setWorkspace('library');
            openMemory(memId, true);
          });
        }
        refsRow.append(chip);
      }
      item.append(refsRow);
    }
    if (post.payload) {
      const details = element('details', 'thread-payload');
      details.append(element('summary', '', 'Structured payload'), element('pre', '', JSON.stringify(post.payload, null, 2)));
      item.append(details);
    }
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
  const actions = board.thread?.actions.filter((action) => {
    if (!actor) return false;
    if (action.actor === '*') return true;
    const actors = (action.actors || [action.actor]).map((a) => a.toLowerCase());
    if (actors.includes('*')) return actor !== board.thread.created_by.toLowerCase();
    return actors.includes(actor);
  }) ?? [];
  menu.replaceChildren(new Option('Reply', ''), ...actions.map((action) => new Option(action.label, action.status)));
  const chosen = actions.find((action) => action.status === former);
  menu.value = chosen?.status || '';
  const msgKind = form.elements.kind.value;
  form.elements.message.required = (!chosen && msgKind !== 'ack') || Boolean(chosen?.needs_message);
  $('board-post').textContent = chosen?.label || 'Post message';
  $('board-ack-btn').hidden = !(board.author || $('board-actor-filter').value.trim());
}

function syncThreadDialogFields() {
  const form = $('assignment-form');
  const kind = form.elements.kind.value;
  const isAssign = kind === 'assignment';
  const isBroadcast = kind === 'broadcast';
  $('thread-author-label').textContent = isAssign ? 'Supervisor' : 'From';
  $('thread-to-label').textContent = isAssign ? 'Assignee' : (isBroadcast ? 'Audience' : 'To');
  $('thread-body-label').textContent = isAssign ? 'Brief' : 'Message';
  form.elements.to.required = isAssign || kind === 'request';
  form.elements.body.required = isAssign || kind === 'request' || isBroadcast;
  if (isBroadcast && !form.elements.to.value.trim()) form.elements.to.value = '*';
  $('submit-assignment').textContent = isAssign ? 'Assign work' : 'Open thread';
}

$('board-nav').addEventListener('click', () => { setWorkspace('board'); refreshBoard(); });
$('board-status-filter').addEventListener('change', () => refreshBoard());
$('board-kind-filter').addEventListener('change', () => refreshBoard());
$('board-actor-filter').addEventListener('input', () => {
  clearTimeout(boardFilterTimer);
  boardFilterTimer = setTimeout(() => refreshBoard(), 250);
});
$('board-back').addEventListener('click', () => {
  $('board-view').classList.remove('show-reader');
  $('board-list').querySelector('[aria-pressed="true"]')?.focus();
});
$('board-clear-reply').addEventListener('click', () => setReplyTarget(null));

$('board-ack-btn').addEventListener('click', async () => {
  if (!board.thread) return;
  const actor = board.author || $('board-actor-filter').value.trim();
  if (!actor) return;
  try {
    await bridge.request('board_ack', { id: board.thread.id, actor, post_ack: false });
    notify(`Thread #${board.thread.id} acknowledged`);
    await refreshBoard();
  } catch (error) {
    notify(error.message);
  }
});

$('new-assignment').addEventListener('click', () => {
  const form = $('assignment-form');
  form.reset();
  form.elements.kind.value = 'discussion';
  form.elements.author.value = board.author;
  form.elements.project.value = state.project;
  syncThreadDialogFields();
  $('assignment-error').hidden = true;
  $('assignment-dialog').showModal();
  form.elements.title.focus();
});
$('thread-dialog-kind').addEventListener('change', syncThreadDialogFields);

$('assignment-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const fields = Object.fromEntries(new FormData(event.currentTarget));
  submitForm($('assignment-dialog'), $('submit-assignment'), $('assignment-error'), async () => {
    let created;
    if (fields.kind === 'assignment') {
      created = await bridge.request('board_assign', {
        title: fields.title,
        brief: fields.body,
        supervisor: fields.author,
        assignee: fields.to,
        project: fields.project,
        priority: fields.priority,
      });
    } else {
      created = await bridge.request('board_open', fields);
    }
    board.author = fields.author.trim();
    $('assignment-dialog').close();
    notify(`${threadKinds[fields.kind] || 'Thread'} #${created.id} opened`);
    await refreshBoard({ preferred: created.id });
  });
});

const replyForm = $('board-reply-form');
replyForm.elements.author.addEventListener('input', () => {
  board.author = replyForm.elements.author.value.trim();
  updateBoardActions();
});
replyForm.elements.status.addEventListener('change', updateBoardActions);
replyForm.elements.kind.addEventListener('change', updateBoardActions);
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
      replyForm.elements.kind.value = 'message';
      replyForm.elements.to.value = '';
      setReplyTarget(null);
      updateBoardActions();
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
