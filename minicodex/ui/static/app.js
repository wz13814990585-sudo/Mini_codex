const token = document.querySelector('meta[name="minicodex-token"]').content;

const ui = {
  tree: document.getElementById('file-tree'),
  filter: document.getElementById('file-filter'),
  code: document.getElementById('code-content'),
  codeView: document.getElementById('code-view'),
  empty: document.getElementById('editor-empty'),
  activePath: document.getElementById('active-path'),
  codeTab: document.getElementById('code-tab'),
  diffTab: document.getElementById('diff-tab'),
  terminal: document.getElementById('terminal-output'),
  chat: document.getElementById('chat-log'),
  badge: document.getElementById('task-badge'),
  review: document.getElementById('review-bar'),
  prompt: document.getElementById('task-prompt'),
  run: document.getElementById('run-task'),
  cancel: document.getElementById('cancel-task'),
  warning: document.getElementById('config-warning'),
  approval: document.getElementById('approval-bar'),
  approvalTool: document.getElementById('approval-tool'),
  approvalReason: document.getElementById('approval-reason'),
  approvalTarget: document.getElementById('approval-target'),
};

const translations = {
  zh: {
    workspace: 'WORKSPACE', files: '文件', searchFiles: '搜索文件', code: '代码', diff: '变更',
    selectFile: '选择一个文件开始查看', selectFileHint: '任务运行后可切换到 Diff 审查修改',
    activity: '运行活动', clear: '清空', ready: '等待任务…', agentChat: 'Agent 对话', idle: '空闲',
    inspect: '检查', act: '执行', validate: '验证', done: '完成', configNeeded: '需要配置模型',
    welcome: '描述你想完成的代码任务。我会先检查仓库，再编辑、测试并给出可审查的 Diff。',
    reviewTitle: '修改等待确认', reviewHint: 'Accept 保留修改，Reject 安全回滚本次任务',
    reject: 'Reject', accept: 'Accept', promptPlaceholder: '例如：为用户 API 添加分页，并补充测试',
    submitHint: '⌘/Ctrl + Enter 发送', stop: '停止', run: '运行任务', running: '运行中',
    pending: '待确认', accepted: '已接受', rejected: '已回滚', failed: '失败', cancelled: '已取消',
    noDiff: '当前文件没有未提交变更。', treeError: '无法读取文件树', requestFailed: '请求失败',
    approvalTitle: '操作需要批准', approvalWaiting: '等待批准', deny: '拒绝',
    allowTask: '本任务允许', allowOnce: '允许一次',
  },
  en: {
    workspace: 'WORKSPACE', files: 'Files', searchFiles: 'Search files', code: 'Code', diff: 'Changes',
    selectFile: 'Select a file to start', selectFileHint: 'Switch to Diff after a task to review changes',
    activity: 'Run activity', clear: 'Clear', ready: 'Waiting for a task…', agentChat: 'Agent chat', idle: 'Idle',
    inspect: 'Inspect', act: 'Act', validate: 'Validate', done: 'Done', configNeeded: 'Model setup required',
    welcome: 'Describe a coding task. I will inspect the repository, edit, test, and return a reviewable diff.',
    reviewTitle: 'Changes need your review', reviewHint: 'Accept keeps them; Reject safely rolls back this task',
    reject: 'Reject', accept: 'Accept', promptPlaceholder: 'Example: add pagination to the users API and test it',
    submitHint: '⌘/Ctrl + Enter to send', stop: 'Stop', run: 'Run task', running: 'Running',
    pending: 'Review', accepted: 'Accepted', rejected: 'Reverted', failed: 'Failed', cancelled: 'Cancelled',
    noDiff: 'This file has no uncommitted changes.', treeError: 'Unable to load file tree', requestFailed: 'Request failed',
    approvalTitle: 'Approval required', approvalWaiting: 'Approval', deny: 'Deny',
    allowTask: 'Allow for task', allowOnce: 'Allow once',
  },
};

const state = {
  locale: localStorage.getItem('minicodex-locale') || 'zh',
  tree: null,
  activePath: '',
  mode: 'code',
  lastSequence: 0,
  terminalEvents: [],
  messageSignature: '',
  taskSignature: '',
  pollTimer: null,
  modelReady: false,
  approval: null,
  pendingApprovalId: '',
};

function t(key) {
  return translations[state.locale][key] || key;
}

function applyLanguage() {
  document.documentElement.lang = state.locale === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((element) => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
  document.getElementById('language-toggle').textContent = state.locale === 'zh' ? 'EN' : '中文';
  renderApproval(state.approval);
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers['Content-Type'] = 'application/json';
  if ((options.method || 'GET') !== 'GET') headers['X-MiniCodex-Token'] = token;
  const response = await fetch(path, { ...options, headers });
  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  if (!response.ok) throw new Error(payload.error || `${t('requestFailed')} (${response.status})`);
  return payload;
}

function toast(message, kind = '') {
  const element = document.createElement('div');
  element.className = `toast ${kind}`.trim();
  element.textContent = message;
  document.getElementById('toast-region').append(element);
  window.setTimeout(() => element.remove(), 4200);
}

async function bootstrap() {
  try {
    const payload = await request('/api/bootstrap');
    document.getElementById('workspace-name').textContent = payload.workspace.name;
    document.getElementById('workspace-name').title = payload.workspace.path;
    document.getElementById('version').textContent = `v${payload.version}`;
    state.modelReady = payload.model.configured;
    document.getElementById('model-dot').classList.toggle('ready', state.modelReady);
    ui.warning.classList.toggle('hidden', state.modelReady);
    document.getElementById('config-problem').textContent = payload.model.problems.join(' · ');
    await loadTree();
    renderDynamicState(payload.state);
    schedulePoll(250);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function loadTree() {
  try {
    state.tree = await request('/api/tree');
    renderTree();
    if (!state.activePath) {
      const preferred = findFile(state.tree, 'README.md') || firstFile(state.tree);
      if (preferred) await openFile(preferred.path);
    }
  } catch (error) {
    ui.tree.textContent = t('treeError');
    toast(error.message, 'error');
  }
}

function findFile(node, path) {
  if (node.path === path && node.type === 'file') return node;
  for (const child of node.children || []) {
    const match = findFile(child, path);
    if (match) return match;
  }
  return null;
}

function firstFile(node) {
  if (node.type === 'file') return node;
  for (const child of node.children || []) {
    const match = firstFile(child);
    if (match) return match;
  }
  return null;
}

function renderTree() {
  ui.tree.replaceChildren();
  if (!state.tree) return;
  const query = ui.filter.value.trim().toLowerCase();
  if (query) {
    flattenFiles(state.tree).filter((item) => item.path.toLowerCase().includes(query)).forEach((item) => {
      ui.tree.append(treeRow(item, 0, false));
    });
    return;
  }
  for (const child of state.tree.children || []) ui.tree.append(treeNode(child, 0));
}

function flattenFiles(node, output = []) {
  if (node.type === 'file') output.push(node);
  for (const child of node.children || []) flattenFiles(child, output);
  return output;
}

function treeNode(node, depth) {
  const wrapper = document.createElement('div');
  wrapper.className = 'tree-node';
  const row = treeRow(node, depth, node.type === 'directory');
  wrapper.append(row);
  if (node.type === 'directory') {
    const children = document.createElement('div');
    children.className = 'tree-children collapsed';
    for (const child of node.children || []) children.append(treeNode(child, depth + 1));
    row.addEventListener('click', () => {
      children.classList.toggle('collapsed');
      row.querySelector('.tree-caret').textContent = children.classList.contains('collapsed') ? '›' : '⌄';
    });
    wrapper.append(children);
  }
  return wrapper;
}

function treeRow(node, depth, directory) {
  const row = document.createElement('div');
  row.className = `tree-row${node.path === state.activePath ? ' active' : ''}`;
  row.style.paddingLeft = `${8 + depth * 13}px`;
  row.title = node.path;
  const caret = document.createElement('span');
  caret.className = 'tree-caret';
  caret.textContent = directory ? '›' : '';
  const icon = document.createElement('span');
  icon.className = 'tree-icon';
  icon.textContent = directory ? '▰' : fileGlyph(node.name);
  const name = document.createElement('span');
  name.className = 'tree-name';
  name.textContent = node.name;
  row.append(caret, icon, name);
  if (!directory) row.addEventListener('click', () => openFile(node.path));
  return row;
}

function fileGlyph(name) {
  const extension = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
  return ({ py: 'py', js: 'js', ts: 'ts', html: '<>', css: '#', md: 'md', json: '{}', toml: 'tm' })[extension] || '·';
}

async function openFile(path) {
  state.activePath = path;
  state.mode = 'code';
  syncTabs();
  renderTree();
  try {
    const payload = await request(`/api/file?path=${encodeURIComponent(path)}`);
    renderCode(payload.content, false);
    ui.activePath.textContent = path;
    ui.activePath.title = path;
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function openDiff() {
  state.mode = 'diff';
  syncTabs();
  try {
    const suffix = state.activePath ? `?path=${encodeURIComponent(state.activePath)}` : '';
    const payload = await request(`/api/diff${suffix}`);
    renderCode(payload.text || t('noDiff'), true);
    ui.activePath.textContent = state.activePath ? `${state.activePath} · diff` : 'Workspace diff';
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderCode(content, isDiff) {
  ui.code.replaceChildren();
  const lines = String(content).replace(/\n$/, '').split('\n');
  lines.forEach((line, index) => {
    const span = document.createElement('span');
    span.className = 'code-line';
    if (isDiff) {
      if (line.startsWith('+') && !line.startsWith('+++')) span.classList.add('diff-add');
      else if (line.startsWith('-') && !line.startsWith('---')) span.classList.add('diff-remove');
      else if (line.startsWith('@@') || line.startsWith('diff ') || line.startsWith('index ')) span.classList.add('diff-meta');
    }
    span.dataset.line = String(index + 1);
    span.textContent = line || ' ';
    ui.code.append(span);
  });
  ui.empty.classList.add('hidden');
  ui.codeView.classList.remove('hidden');
  ui.codeView.scrollTop = 0;
  ui.codeView.scrollLeft = 0;
}

function syncTabs() {
  ui.codeTab.classList.toggle('active', state.mode === 'code');
  ui.diffTab.classList.toggle('active', state.mode === 'diff');
}

async function pollState() {
  try {
    const payload = await request(`/api/state?after=${state.lastSequence}`);
    renderDynamicState(payload);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    schedulePoll(700);
  }
}

function schedulePoll(delay) {
  window.clearTimeout(state.pollTimer);
  state.pollTimer = window.setTimeout(pollState, delay);
}

function renderDynamicState(payload) {
  const git = payload.git || {};
  document.getElementById('branch-name').textContent = git.branch || (git.is_repo ? 'detached' : 'no git');
  renderTask(payload.task, payload.runtime);
  renderApproval(payload.approval);
  renderMessages(payload.messages || []);
  appendEvents(payload.events || []);
  const summary = payload.trace_summary || {};
  document.getElementById('tool-count').textContent = `${summary.tool_calls || 0} tools`;
  document.getElementById('validation-count').textContent = `${summary.validation_runs || 0} checks`;
  const changed = payload.task_git && payload.task_git.agent_current_changed_files;
  const signature = JSON.stringify(changed || []);
  if (payload.task && payload.task.done && changed && changed.length && state.taskSignature !== `${payload.task.id}:${signature}`) {
    state.taskSignature = `${payload.task.id}:${signature}`;
    state.activePath = changed[0];
    openDiff();
    loadTree();
  }
}

function renderTask(task, runtime) {
  const status = task ? task.status : 'idle';
  const review = task ? task.review_status : 'not_required';
  let labelKey = 'idle';
  let badgeClass = 'idle';
  if (task && task.awaiting_approval) { labelKey = 'approvalWaiting'; badgeClass = 'pending'; }
  else if (task && !task.done) { labelKey = 'running'; badgeClass = 'running'; }
  else if (review === 'pending') { labelKey = 'pending'; badgeClass = 'pending'; }
  else if (review === 'accepted') { labelKey = 'accepted'; badgeClass = 'completed'; }
  else if (review === 'rejected') { labelKey = 'rejected'; badgeClass = 'completed'; }
  else if (status === 'failed') { labelKey = 'failed'; badgeClass = 'failed'; }
  else if (status === 'cancelled') { labelKey = 'cancelled'; badgeClass = 'failed'; }
  else if (status === 'completed') { labelKey = 'done'; badgeClass = 'completed'; }
  ui.badge.textContent = t(labelKey);
  ui.badge.className = `task-badge ${badgeClass}`;
  ui.review.classList.toggle('hidden', review !== 'pending');
  ui.cancel.classList.toggle('hidden', !(task && task.can_cancel));
  ui.run.disabled = Boolean(task && (!task.done || review === 'pending')) || !state.modelReady;
  ui.prompt.disabled = Boolean(task && (!task.done || review === 'pending'));
  renderPhases(runtime ? runtime.phase : null);
}

const approvalReasons = {
  zh: {
    dependency_install: '该操作会安装或修改项目依赖。',
    network_access: '该命令会访问外部网络。',
    preexisting_user_change: '目标文件在任务开始前已有未提交修改。',
    git_conflict: '目标文件当前存在 Git 冲突。',
  },
  en: {
    dependency_install: 'This operation installs or changes project dependencies.',
    network_access: 'This command accesses the external network.',
    preexisting_user_change: 'The target file already had uncommitted changes before this task.',
    git_conflict: 'The target file currently has a Git conflict.',
  },
};

function renderApproval(approval) {
  state.approval = approval || null;
  const pending = approval && approval.pending;
  state.pendingApprovalId = pending ? pending.request_id : '';
  ui.approval.classList.toggle('hidden', !pending);
  if (!pending) return;
  ui.approvalTool.textContent = `${pending.tool_name} · ${pending.rule}`;
  ui.approvalReason.textContent = approvalReasons[state.locale][pending.rule] || pending.reason;
  const details = [];
  if (pending.command) details.push(pending.command);
  if (pending.path) details.push(pending.path);
  for (const [key, value] of Object.entries(pending.arguments || {})) {
    if ((key === 'command' && pending.command) || (key === 'path' && pending.path)) continue;
    details.push(`${key}: ${Array.isArray(value) ? value.join(' ') : value}`);
  }
  ui.approvalTarget.textContent = details.join('\n') || pending.tool_name;
}

function renderPhases(phase) {
  const normalized = ({ fixing: 'acting', finalizing: 'validating', blocked: 'done' })[phase] || phase;
  const phases = ['inspecting', 'acting', 'validating', 'done'];
  const current = phases.indexOf(normalized);
  document.querySelectorAll('#phase-track [data-phase]').forEach((element, index) => {
    element.classList.toggle('active', index === current);
    element.classList.toggle('complete', current >= 0 && index < current);
  });
}

function renderMessages(messages) {
  const signature = messages.map((message) => message.id).join('|');
  if (signature === state.messageSignature) return;
  state.messageSignature = signature;
  ui.chat.querySelectorAll('.message:not(.welcome-message)').forEach((element) => element.remove());
  for (const message of messages) {
    const article = document.createElement('article');
    article.className = `message ${message.role}`;
    const body = document.createElement('div');
    body.className = 'message-body';
    const name = document.createElement('strong');
    name.textContent = message.role === 'user' ? 'You' : message.role === 'system' ? 'System' : 'MiniCodex';
    const text = document.createElement('p');
    text.textContent = message.content;
    body.append(name, text);
    if (message.role === 'assistant') {
      const avatar = document.createElement('div');
      avatar.className = 'message-avatar';
      avatar.textContent = 'M';
      article.append(avatar, body);
    } else {
      article.append(body);
    }
    ui.chat.append(article);
  }
  ui.chat.scrollTop = ui.chat.scrollHeight;
}

function appendEvents(events) {
  if (!events.length) return;
  if (ui.terminal.querySelector('.muted')) ui.terminal.replaceChildren();
  for (const event of events) {
    state.lastSequence = Math.max(state.lastSequence, event.sequence || 0);
    state.terminalEvents.push(event);
    const line = document.createElement('div');
    const success = event.data && event.data.success;
    line.className = `terminal-line${success === true ? ' success' : success === false ? ' failure' : ''}`;
    const time = document.createElement('span');
    time.className = 'time';
    time.textContent = formatTime(event.timestamp);
    const type = document.createElement('span');
    type.className = 'event';
    type.textContent = event.event_type;
    const detail = document.createElement('span');
    detail.textContent = eventDetail(event);
    line.append(time, type, detail);
    ui.terminal.append(line);
  }
  while (ui.terminal.children.length > 500) ui.terminal.firstElementChild.remove();
  ui.terminal.scrollTop = ui.terminal.scrollHeight;
}

function formatTime(timestamp) {
  if (!timestamp) return '--:--:--';
  const date = new Date(timestamp);
  return Number.isNaN(date.valueOf()) ? '--:--:--' : date.toLocaleTimeString([], { hour12: false });
}

function eventDetail(event) {
  const data = event.data || {};
  const parts = [data.tool_name, data.summary, data.path, data.phase, data.reason, data.error].filter(Boolean);
  if (data.duration_seconds != null) parts.push(`${Number(data.duration_seconds).toFixed(2)}s`);
  return parts.join(' · ') || '—';
}

async function submitTask(event) {
  event.preventDefault();
  const prompt = ui.prompt.value.trim();
  if (!prompt) return;
  try {
    await request('/api/tasks', { method: 'POST', body: JSON.stringify({ prompt }) });
    ui.prompt.value = '';
    state.lastSequence = 0;
    state.terminalEvents = [];
    ui.terminal.replaceChildren();
    await pollState();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function taskAction(action) {
  try {
    await request(`/api/tasks/${action}`, { method: 'POST', body: '{}' });
    await pollState();
    if (action === 'reject') {
      await loadTree();
      if (state.mode === 'diff') await openDiff();
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function approvalAction(decision) {
  if (!state.pendingApprovalId) return;
  try {
    await request('/api/approvals', {
      method: 'POST',
      body: JSON.stringify({ request_id: state.pendingApprovalId, decision }),
    });
    await pollState();
  } catch (error) {
    toast(error.message, 'error');
  }
}

document.getElementById('task-form').addEventListener('submit', submitTask);
ui.prompt.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submitTask(event);
});
document.getElementById('cancel-task').addEventListener('click', () => taskAction('cancel'));
document.getElementById('accept-task').addEventListener('click', () => taskAction('accept'));
document.getElementById('reject-task').addEventListener('click', () => taskAction('reject'));
document.getElementById('reject-approval').addEventListener('click', () => approvalAction('reject'));
document.getElementById('allow-task-approval').addEventListener('click', () => approvalAction('allow_task'));
document.getElementById('allow-once-approval').addEventListener('click', () => approvalAction('allow_once'));
document.getElementById('refresh-tree').addEventListener('click', loadTree);
document.getElementById('refresh-view').addEventListener('click', () => state.mode === 'diff' ? openDiff() : openFile(state.activePath));
ui.filter.addEventListener('input', renderTree);
ui.codeTab.addEventListener('click', () => state.activePath && openFile(state.activePath));
ui.diffTab.addEventListener('click', openDiff);
document.getElementById('clear-terminal').addEventListener('click', () => ui.terminal.replaceChildren());
document.getElementById('language-toggle').addEventListener('click', () => {
  state.locale = state.locale === 'zh' ? 'en' : 'zh';
  localStorage.setItem('minicodex-locale', state.locale);
  applyLanguage();
});

applyLanguage();
bootstrap();
