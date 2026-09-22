import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { WorkspaceEditor } from './workspace_editor.js';

const token = document.querySelector('meta[name="minicodex-token"]').content;

const ui = {
  tree: document.getElementById('file-tree'),
  filter: document.getElementById('file-filter'),
  code: document.getElementById('code-content'),
  codeView: document.getElementById('code-view'),
  editorHost: document.getElementById('code-editor'),
  openTabs: document.getElementById('open-file-tabs'),
  workbench: document.querySelector('.workbench'),
  findFile: document.getElementById('find-file'),
  renameFile: document.getElementById('rename-file'),
  trashFile: document.getElementById('trash-file'),
  saveFile: document.getElementById('save-file'),
  newFile: document.getElementById('new-file'),
  newFolder: document.getElementById('new-folder'),
  empty: document.getElementById('editor-empty'),
  activePath: document.getElementById('active-path'),
  codeTab: document.getElementById('code-tab'),
  diffTab: document.getElementById('diff-tab'),
  terminal: document.getElementById('terminal-output'),
  terminalShell: document.getElementById('terminal-shell'),
  terminalNotice: document.getElementById('terminal-notice'),
  terminalContainer: document.getElementById('xterm-container'),
  startTerminal: document.getElementById('start-terminal'),
  stopTerminal: document.getElementById('stop-terminal'),
  shellTab: document.getElementById('shell-tab'),
  activityTab: document.getElementById('activity-tab'),
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
  diffFiles: document.getElementById('diff-file-bar'),
  modeHelp: document.getElementById('permission-mode-help'),
  modeButtons: Array.from(document.querySelectorAll('[data-mode]')),
  reviewHint: document.getElementById('review-hint'),
  dialog: document.getElementById('workspace-dialog'),
  dialogForm: document.getElementById('workspace-dialog-form'),
  dialogTitle: document.getElementById('workspace-dialog-title'),
  dialogMessage: document.getElementById('workspace-dialog-message'),
  dialogInput: document.getElementById('workspace-dialog-input'),
  dialogCancel: document.getElementById('workspace-dialog-cancel'),
  dialogConfirm: document.getElementById('workspace-dialog-confirm'),
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
    noDiff: '当前文件没有可显示的变更。', treeError: '无法读取文件树', requestFailed: '请求失败',
    approvalTitle: '操作需要批准', approvalWaiting: '等待批准', deny: '拒绝',
    allowTask: '本任务允许', allowOnce: '允许一次',
    modeReview: '审查', modeAuto: '自动', modeReadOnly: '只读',
    modeReviewHelp: '警示操作执行前询问，任务结束后审查全部修改',
    modeAutoHelp: '安全策略允许的操作自动执行，任务结束后仍可审查修改',
    modeReadOnlyHelp: 'Agent 仅开放读取、搜索和 Git 检查，不允许修改或运行进程',
    allChanges: '全部变更', changedFiles: '个文件等待审查',
    findFile: '查找', renameFile: '重命名', trashFile: '删除', saveFile: '保存', savedFile: '文件已保存',
    newFile: '新建文件', newFolder: '新建文件夹', namePrompt: '输入工作区内的相对路径：',
    renamePrompt: '输入新路径：', deleteConfirm: '移到可恢复的本地回收区？',
    unsavedTab: '该文件有未保存修改，确定关闭标签吗？', unsavedTask: '请先保存所有已修改文件，再启动 Agent 任务。',
    terminal: '终端', startTerminal: '启动终端', stopTerminal: '关闭终端',
    terminalNotice: '终端以当前系统用户权限执行命令，可访问工作区外的文件和网络。点击“启动终端”后连接到当前工作区。运行 Agent 前请先关闭终端。',
    terminalClosed: '终端已关闭。', terminalStartError: '终端启动失败',
    dialogCancel: '取消', dialogConfirm: '确认',
    movedToTrash: '文件已移到 .minicodex/trash/，可通过终端恢复。',
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
    noDiff: 'No reviewable changes for this file.', treeError: 'Unable to load file tree', requestFailed: 'Request failed',
    approvalTitle: 'Approval required', approvalWaiting: 'Approval', deny: 'Deny',
    allowTask: 'Allow for task', allowOnce: 'Allow once',
    modeReview: 'Review', modeAuto: 'Auto', modeReadOnly: 'Read-only',
    modeReviewHelp: 'Ask before caution operations, then review the complete task diff',
    modeAutoHelp: 'Run safety-allowed operations automatically; final changes remain reviewable',
    modeReadOnlyHelp: 'Agent may only read, search, and inspect Git; block its edits and processes',
    allChanges: 'All changes', changedFiles: 'files awaiting review',
    findFile: 'Find', renameFile: 'Rename', trashFile: 'Delete', saveFile: 'Save', savedFile: 'File saved',
    newFile: 'New file', newFolder: 'New folder', namePrompt: 'Enter a path relative to the workspace:',
    renamePrompt: 'Enter the new path:', deleteConfirm: 'Move this item to the recoverable local trash?',
    unsavedTab: 'This file has unsaved changes. Close its tab?', unsavedTask: 'Save all edited files before starting an Agent task.',
    terminal: 'Terminal', startTerminal: 'Start terminal', stopTerminal: 'Close terminal',
    terminalNotice: 'This shell runs with your OS user permissions and can access files and the network outside the workspace. Click Start terminal to connect. Close it before running an Agent task.',
    terminalClosed: 'Terminal closed.', terminalStartError: 'Could not start terminal',
    dialogCancel: 'Cancel', dialogConfirm: 'Confirm',
    movedToTrash: 'File moved to .minicodex/trash/; it can be restored from the terminal.',
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
  permissionMode: ['review', 'auto', 'read_only'].includes(localStorage.getItem('minicodex-permission-mode'))
    ? localStorage.getItem('minicodex-permission-mode') : 'review',
  changedPaths: [],
  diffPath: '',
  canEditNow: true,
  agentBusy: false,
  terminalRunning: false,
  terminalSession: '',
  terminalSequence: 0,
  terminalTimer: null,
  bottomMode: 'shell',
};

const editor = new WorkspaceEditor(ui.editorHost, {
  onChange: () => { renderFileTabs(); renderEditorActions(); },
  onSave: () => saveFile(),
  styleNonce: token,
});
const terminalFit = new FitAddon();
const shell = new Terminal({
  cursorBlink: true, fontFamily: 'SFMono-Regular, Consolas, Menlo, monospace',
  fontSize: 12, theme: { background: '#0b0e10', foreground: '#e5eee9', cursor: '#9fffc9' },
  scrollback: 3000, allowProposedApi: false,
});
shell.loadAddon(terminalFit);
shell.open(ui.terminalContainer);
let terminalWrites = Promise.resolve();
let lastTerminalSize = '';

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
  document.querySelectorAll('[data-i18n-title]').forEach((element) => {
    element.title = t(element.dataset.i18nTitle);
  });
  document.getElementById('language-toggle').textContent = state.locale === 'zh' ? 'EN' : '中文';
  renderApproval(state.approval);
  renderPermissionMode();
  renderDiffFiles();
  renderReviewHint();
  renderEditorActions();
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers['Content-Type'] = 'application/json';
  if ((options.method || 'GET') !== 'GET') headers['X-MiniCodex-Token'] = token;
  if (path.startsWith('/api/terminal')) headers['X-MiniCodex-Token'] = token;
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
    scheduleTerminalPoll(0);
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
  if (!path) return;
  try {
    const payload = await request(`/api/file?path=${encodeURIComponent(path)}`);
    const existing = editor.tabs.get(path);
    if (existing && editor.dirty(path) && existing.revision !== payload.revision) {
      toast('File changed on disk; your unsaved draft was kept.', 'error');
    }
    editor.open(path, payload);
    state.activePath = path;
    state.diffPath = '';
    state.mode = 'code';
    ui.activePath.textContent = path;
    ui.activePath.title = path;
    ui.empty.classList.add('hidden');
    ui.codeView.classList.add('hidden');
    ui.editorHost.classList.remove('hidden');
    syncTabs();
    renderFileTabs();
    renderDiffFiles();
    renderTree();
    editor.requestMeasure();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function openDiff(path) {
  const target = path === undefined ? (state.diffPath || state.activePath || '') : path;
  state.mode = 'diff';
  state.diffPath = target || '';
  syncTabs();
  renderDiffFiles();
  try {
    const suffix = state.diffPath ? `?path=${encodeURIComponent(state.diffPath)}` : '';
    const payload = await request(`/api/diff${suffix}`);
    renderCode(payload.text || t('noDiff'), true);
    ui.activePath.textContent = state.diffPath ? `${state.diffPath} · diff` : t('allChanges');
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderCode(content, isDiff) {
  ui.editorHost.classList.add('hidden');
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
  renderEditorActions();
}

function renderEditorActions() {
  const current = editor.current();
  const inCode = state.mode === 'code' && current;
  ui.findFile.disabled = !inCode;
  ui.renameFile.disabled = !inCode || !state.canEditNow || current.dirty;
  ui.trashFile.disabled = !inCode || !state.canEditNow || current.dirty;
  ui.saveFile.disabled = !inCode || !state.canEditNow || !current.editable || !current.dirty;
  ui.newFile.disabled = !state.canEditNow;
  ui.newFolder.disabled = !state.canEditNow;
}

function renderFileTabs() {
  ui.openTabs.replaceChildren();
  for (const [path] of editor.tabs) {
    const button = document.createElement('div');
    button.className = `file-tab${path === editor.activePath && state.mode === 'code' ? ' active' : ''}`;
    button.setAttribute('role', 'tab');
    button.tabIndex = 0;
    button.title = path;
    const name = document.createElement('span');
    name.className = 'file-tab-name';
    name.textContent = path.split('/').at(-1);
    const dirty = document.createElement('span');
    dirty.className = 'file-tab-dirty';
    dirty.textContent = editor.dirty(path) ? '●' : '';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'file-tab-close';
    close.textContent = '×';
    close.setAttribute('aria-label', `Close ${path}`);
    close.addEventListener('click', (event) => { event.stopPropagation(); closeFileTab(path); });
    button.append(name, dirty, close);
    button.addEventListener('click', () => activateFileTab(path));
    button.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activateFileTab(path); }
    });
    ui.openTabs.append(button);
  }
}

function activateFileTab(path) {
  const tab = editor.activate(path);
  if (!tab) return;
  state.activePath = path;
  state.mode = 'code';
  state.diffPath = '';
  ui.activePath.textContent = path;
  ui.activePath.title = path;
  ui.empty.classList.add('hidden');
  ui.codeView.classList.add('hidden');
  ui.editorHost.classList.remove('hidden');
  syncTabs();
  renderDiffFiles();
  renderFileTabs();
  renderTree();
  editor.requestMeasure();
}

function closeFileTab(path) {
  if (editor.dirty(path) && !window.confirm(t('unsavedTab'))) return;
  editor.close(path);
  if (editor.activePath) activateFileTab(editor.activePath);
  else {
    state.activePath = '';
    ui.activePath.textContent = '—';
    ui.editorHost.classList.add('hidden');
    ui.codeView.classList.add('hidden');
    ui.empty.classList.remove('hidden');
    renderEditorActions();
    renderTree();
  }
  renderFileTabs();
}

async function saveFile() {
  const current = editor.current();
  if (!current || !current.dirty || !state.canEditNow || !current.editable) return;
  try {
    const payload = await request('/api/file', {
      method: 'POST',
      body: JSON.stringify({
        path: current.path,
        content: current.content,
        expected_revision: current.revision,
      }),
    });
    editor.markSaved(current.path, payload);
    renderFileTabs();
    renderEditorActions();
    toast(t('savedFile'));
  } catch (error) {
    toast(error.message, 'error');
  }
}

function defaultNewPath() {
  const path = state.activePath;
  return path.includes('/') ? `${path.slice(0, path.lastIndexOf('/') + 1)}` : '';
}

function workspaceDialog({ title, message, value = null, dangerous = false }) {
  return new Promise((resolve) => {
    ui.dialogTitle.textContent = title;
    ui.dialogMessage.textContent = message;
    ui.dialogInput.classList.toggle('hidden', value === null);
    ui.dialogInput.required = value !== null;
    ui.dialogInput.value = value || '';
    ui.dialogCancel.textContent = t('dialogCancel');
    ui.dialogConfirm.textContent = dangerous ? t('trashFile') : t('dialogConfirm');
    ui.dialogConfirm.classList.toggle('danger', dangerous);
    function finish(result) {
      ui.dialogForm.removeEventListener('submit', submit);
      ui.dialogCancel.removeEventListener('click', cancel);
      ui.dialog.removeEventListener('cancel', cancel);
      ui.dialog.close();
      resolve(result);
    }
    function submit(event) {
      event.preventDefault();
      finish(value === null ? true : ui.dialogInput.value.trim());
    }
    function cancel(event) { event.preventDefault(); finish(null); }
    ui.dialogForm.addEventListener('submit', submit);
    ui.dialogCancel.addEventListener('click', cancel);
    ui.dialog.addEventListener('cancel', cancel);
    ui.dialog.showModal();
    if (value !== null) { ui.dialogInput.focus(); ui.dialogInput.select(); }
    else ui.dialogConfirm.focus();
  });
}

async function createItem(kind) {
  const path = await workspaceDialog({
    title: t(kind === 'file' ? 'newFile' : 'newFolder'),
    message: t('namePrompt'), value: defaultNewPath(),
  });
  if (!path || !path.trim()) return;
  try {
    const payload = await request('/api/items/create', {
      method: 'POST', body: JSON.stringify({ path: path.trim(), kind }),
    });
    await loadTree();
    if (kind === 'file') await openFile(payload.path);
  } catch (error) { toast(error.message, 'error'); }
}

async function renameFile() {
  const current = editor.current();
  if (!current || current.dirty || !state.canEditNow) return;
  const newPath = await workspaceDialog({
    title: t('renameFile'), message: t('renamePrompt'), value: current.path,
  });
  if (!newPath || newPath === current.path) return;
  try {
    const payload = await request('/api/items/rename', {
      method: 'POST', body: JSON.stringify({
        path: current.path, new_path: newPath.trim(), expected_revision: current.revision,
      }),
    });
    editor.rename(current.path, payload.path);
    await loadTree();
    activateFileTab(payload.path);
  } catch (error) { toast(error.message, 'error'); }
}

async function trashFile() {
  const current = editor.current();
  if (!current || current.dirty || !state.canEditNow) return;
  const confirmed = await workspaceDialog({
    title: t('trashFile'), message: t('deleteConfirm'), dangerous: true,
  });
  if (!confirmed) return;
  try {
    await request('/api/items/trash', {
      method: 'POST', body: JSON.stringify({ path: current.path, expected_revision: current.revision }),
    });
    closeFileTab(current.path);
    await loadTree();
    toast(t('movedToTrash'));
  } catch (error) { toast(error.message, 'error'); }
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
  const events = payload.events || [];
  document.getElementById('branch-name').textContent = git.branch || (git.is_repo ? 'detached' : 'no git');
  const changed = payload.task_git && payload.task_git.agent_current_changed_files;
  state.changedPaths = changed || [];
  renderTask(payload.task, payload.runtime);
  renderApproval(payload.approval);
  renderMessages(payload.messages || []);
  appendEvents(events);
  // New files should become visible while the Agent is still working, not
  // only after the task finishes and opens a reviewable diff.
  if (events.some((event) => event.event_type === 'edit_applied')) loadTree();
  const summary = payload.trace_summary || {};
  document.getElementById('tool-count').textContent = `${summary.tool_calls || 0} tools`;
  document.getElementById('validation-count').textContent = `${summary.validation_runs || 0} checks`;
  renderDiffFiles();
  const signature = JSON.stringify(changed || []);
  if (payload.task && payload.task.done && changed && changed.length && state.taskSignature !== `${payload.task.id}:${signature}`) {
    state.taskSignature = `${payload.task.id}:${signature}`;
    state.activePath = changed[0];
    state.diffPath = changed[0];
    openDiff(changed[0]);
    loadTree();
  }
}

function renderTask(task, runtime) {
  const status = task ? task.status : 'idle';
  const review = task ? task.review_status : 'not_required';
  if (task && task.permission_mode && (!task.done || review === 'pending')) {
    state.permissionMode = task.permission_mode;
    localStorage.setItem('minicodex-permission-mode', state.permissionMode);
  }
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
  state.agentBusy = Boolean(task && (!task.done || review === 'pending'));
  ui.run.disabled = state.agentBusy || !state.modelReady || state.terminalRunning;
  state.canEditNow = !(task && (!task.done || review === 'pending'));
  editor.setCanEdit(state.canEditNow);
  renderEditorActions();
  ui.startTerminal.disabled = !state.canEditNow;
  ui.prompt.disabled = Boolean(task && (!task.done || review === 'pending'));
  ui.modeButtons.forEach((button) => {
    button.disabled = Boolean(task && (!task.done || review === 'pending'));
  });
  renderReviewHint();
  renderPermissionMode();
  renderPhases(runtime ? runtime.phase : null);
}

function renderPermissionMode() {
  for (const button of ui.modeButtons) {
    const active = button.dataset.mode === state.permissionMode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  }
  const helpKey = ({ review: 'modeReviewHelp', auto: 'modeAutoHelp', read_only: 'modeReadOnlyHelp' })[state.permissionMode];
  ui.modeHelp.textContent = t(helpKey || 'modeReviewHelp');
}

function renderReviewHint() {
  const pending = !ui.review.classList.contains('hidden');
  ui.reviewHint.textContent = pending && state.changedPaths.length
    ? `${state.changedPaths.length} ${t('changedFiles')} · ${t('reviewHint')}`
    : t('reviewHint');
}

function renderDiffFiles() {
  const hasDiffFiles = state.mode === 'diff' && state.changedPaths.length > 0;
  ui.diffFiles.classList.toggle('hidden', !hasDiffFiles);
  ui.workbench.classList.toggle('has-diff-files', hasDiffFiles);
  ui.diffFiles.replaceChildren();
  if (!hasDiffFiles) return;
  const entries = [['', t('allChanges')], ...state.changedPaths.map((path) => [path, path])];
  for (const [path, label] of entries) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `diff-file${state.diffPath === path ? ' active' : ''}`;
    button.textContent = label;
    button.title = label;
    button.addEventListener('click', () => {
      if (path) state.activePath = path;
      openDiff(path);
    });
    ui.diffFiles.append(button);
  }
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
  const parts = [data.tool_name, data.rule, data.decision, data.resolution, data.summary, data.path, data.phase, data.reason, data.error].filter(Boolean);
  if (data.duration_seconds != null) parts.push(`${Number(data.duration_seconds).toFixed(2)}s`);
  return parts.join(' · ') || '—';
}

async function submitTask(event) {
  event.preventDefault();
  const prompt = ui.prompt.value.trim();
  if (!prompt) return;
  if ([...editor.tabs.keys()].some((path) => editor.dirty(path))) {
    toast(t('unsavedTask'), 'error');
    return;
  }
  try {
    await request('/api/tasks', {
      method: 'POST',
      body: JSON.stringify({ prompt, permission_mode: state.permissionMode }),
    });
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

function renderBottomTabs() {
  const shellMode = state.bottomMode === 'shell';
  ui.shellTab.classList.toggle('active', shellMode);
  ui.activityTab.classList.toggle('active', !shellMode);
  ui.terminalShell.classList.toggle('hidden', !shellMode);
  ui.terminal.classList.toggle('hidden', shellMode);
  ui.startTerminal.classList.toggle('hidden', !shellMode || state.terminalRunning);
  ui.stopTerminal.classList.toggle('hidden', !shellMode || !state.terminalRunning);
  document.getElementById('tool-count').classList.toggle('hidden', shellMode);
  document.getElementById('validation-count').classList.toggle('hidden', shellMode);
  if (shellMode) {
    requestAnimationFrame(() => { terminalFit.fit(); if (state.terminalRunning) resizeTerminal(); });
  }
}

async function pollTerminal() {
  try {
    const payload = await request(`/api/terminal?after=${state.terminalSequence}`);
    ui.terminalContainer.classList.toggle('hidden', !payload.session_id);
    ui.terminalNotice.classList.toggle('hidden', Boolean(payload.session_id));
    if (payload.session_id && state.bottomMode === 'shell') terminalFit.fit();
    if (payload.session_id !== state.terminalSession) {
      state.terminalSession = payload.session_id;
      state.terminalSequence = 0;
      shell.reset();
      if (payload.session_id && !payload.chunks.length) return;
    }
    if (payload.reset) shell.reset();
    for (const chunk of payload.chunks || []) {
      shell.write(chunk.data);
      state.terminalSequence = Math.max(state.terminalSequence, chunk.sequence);
    }
    state.terminalRunning = Boolean(payload.running);
    ui.run.disabled = state.agentBusy || !state.modelReady || state.terminalRunning;
    renderBottomTabs();
    if (payload.session_id && !payload.running) {
      ui.terminalNotice.textContent = t('terminalClosed');
      ui.terminalNotice.classList.remove('hidden');
    }
  } catch (error) {
    // A temporary polling failure should not erase a running shell's output.
  } finally {
    scheduleTerminalPoll(state.terminalRunning ? 180 : 1000);
  }
}

function scheduleTerminalPoll(delay) {
  window.clearTimeout(state.terminalTimer);
  state.terminalTimer = window.setTimeout(pollTerminal, delay);
}

async function startTerminal() {
  state.bottomMode = 'shell';
  ui.terminalContainer.classList.remove('hidden');
  renderBottomTabs();
  terminalFit.fit();
  try {
    const payload = await request('/api/terminal/start', {
      method: 'POST', body: JSON.stringify({ cols: Math.max(shell.cols, 20), rows: Math.max(shell.rows, 5) }),
    });
    state.terminalSession = payload.session_id;
    state.terminalSequence = 0;
    state.terminalRunning = true;
    lastTerminalSize = '';
    shell.reset();
    ui.terminalNotice.classList.add('hidden');
    renderBottomTabs();
    shell.focus();
    scheduleTerminalPoll(0);
  } catch (error) {
    toast(`${t('terminalStartError')}: ${error.message}`, 'error');
    scheduleTerminalPoll(0);
  }
}

async function stopTerminal() {
  try {
    await request('/api/terminal/stop', { method: 'POST', body: '{}' });
    scheduleTerminalPoll(0);
  } catch (error) { toast(error.message, 'error'); }
}

let terminalResizeTimer;
function resizeTerminal() {
  if (state.bottomMode !== 'shell' || ui.terminalContainer.classList.contains('hidden')) return;
  terminalFit.fit();
  if (!state.terminalRunning) return;
  const dimensions = `${shell.cols}x${shell.rows}`;
  if (dimensions === lastTerminalSize) return;
  lastTerminalSize = dimensions;
  window.clearTimeout(terminalResizeTimer);
  terminalResizeTimer = window.setTimeout(() => {
    request('/api/terminal/resize', {
      method: 'POST', body: JSON.stringify({ cols: shell.cols, rows: shell.rows }),
    }).catch(() => {});
  }, 120);
}

shell.onData((data) => {
  if (!state.terminalRunning) return;
  terminalWrites = terminalWrites.then(() => request('/api/terminal/input', {
    method: 'POST', body: JSON.stringify({ data }),
  })).catch((error) => toast(error.message, 'error'));
});

function setupResizers() {
  const saved = {
    left: Number(localStorage.getItem('minicodex-left-width')) || 250,
    right: Number(localStorage.getItem('minicodex-right-width')) || 370,
    bottom: Number(localStorage.getItem('minicodex-bottom-height')) || 240,
  };
  const apply = (which, value) => {
    const grid = document.querySelector('.workspace-grid').getBoundingClientRect();
    const bench = ui.workbench.getBoundingClientRect();
    if (which === 'left') saved.left = Math.max(170, Math.min(value, Math.min(500, grid.width - saved.right - 400)));
    else if (which === 'right') saved.right = Math.max(290, Math.min(value, Math.min(600, grid.width - saved.left - 400)));
    else {
      const diffHeight = ui.diffFiles.classList.contains('hidden') ? 0 : ui.diffFiles.getBoundingClientRect().height;
      saved.bottom = Math.max(120, Math.min(value, Math.min(600, bench.height - 286 - diffHeight)));
    }
    document.documentElement.style.setProperty(`--${which === 'bottom' ? 'bottom-height' : `${which}-width`}`, `${Math.round(saved[which])}px`);
    editor.requestMeasure();
    resizeTerminal();
  };
  for (const which of ['left', 'right', 'bottom']) apply(which, saved[which]);
  const config = [
    ['left-resizer', 'left'], ['right-resizer', 'right'], ['bottom-resizer', 'bottom'],
  ];
  for (const [id, which] of config) {
    const handle = document.getElementById(id);
    handle.addEventListener('pointerdown', (event) => {
      if (window.matchMedia('(max-width: 820px)').matches) return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      handle.classList.add('dragging');
      document.body.classList.add('resizing');
      document.body.classList.toggle('resizing-vertical', which === 'bottom');
    });
    handle.addEventListener('pointermove', (event) => {
      if (!handle.hasPointerCapture(event.pointerId)) return;
      const rect = document.querySelector('.workspace-grid').getBoundingClientRect();
      const bench = ui.workbench.getBoundingClientRect();
      const value = which === 'left' ? event.clientX - rect.left
        : which === 'right' ? rect.right - event.clientX : bench.bottom - event.clientY;
      apply(which, value);
    });
    const finishResize = (event) => {
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      handle.classList.remove('dragging');
      document.body.classList.remove('resizing', 'resizing-vertical');
      localStorage.setItem(`minicodex-${which}-${which === 'bottom' ? 'height' : 'width'}`, String(Math.round(saved[which])));
    };
    handle.addEventListener('pointerup', finishResize);
    handle.addEventListener('pointercancel', finishResize);
    handle.addEventListener('lostpointercapture', finishResize);
    handle.addEventListener('keydown', (event) => {
      const direction = (event.key === 'ArrowRight' || event.key === 'ArrowDown') ? 1
        : (event.key === 'ArrowLeft' || event.key === 'ArrowUp') ? -1 : 0;
      if (!direction) return;
      event.preventDefault();
      apply(which, saved[which] + (which === 'right' || which === 'bottom' ? -direction : direction) * 16);
      localStorage.setItem(`minicodex-${which}-${which === 'bottom' ? 'height' : 'width'}`, String(Math.round(saved[which])));
    });
  }
  new ResizeObserver(() => { editor.requestMeasure(); resizeTerminal(); }).observe(ui.workbench);
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
document.getElementById('refresh-view').addEventListener('click', () => state.mode === 'diff' ? openDiff(state.diffPath) : openFile(state.activePath));
ui.newFile.addEventListener('click', () => createItem('file'));
ui.newFolder.addEventListener('click', () => createItem('directory'));
ui.findFile.addEventListener('click', () => editor.find());
ui.renameFile.addEventListener('click', renameFile);
ui.trashFile.addEventListener('click', trashFile);
ui.saveFile.addEventListener('click', saveFile);
ui.filter.addEventListener('input', renderTree);
ui.codeTab.addEventListener('click', () => state.activePath && activateFileTab(state.activePath));
ui.diffTab.addEventListener('click', () => openDiff(state.activePath || ''));
ui.shellTab.addEventListener('click', () => { state.bottomMode = 'shell'; renderBottomTabs(); });
ui.activityTab.addEventListener('click', () => { state.bottomMode = 'activity'; renderBottomTabs(); });
ui.startTerminal.addEventListener('click', startTerminal);
ui.stopTerminal.addEventListener('click', stopTerminal);
ui.terminalShell.addEventListener('click', () => { if (state.terminalRunning) shell.focus(); });
ui.modeButtons.forEach((button) => button.addEventListener('click', () => {
  if (button.disabled) return;
  state.permissionMode = button.dataset.mode;
  localStorage.setItem('minicodex-permission-mode', state.permissionMode);
  renderPermissionMode();
}));
document.getElementById('clear-terminal').addEventListener('click', () => {
  if (state.bottomMode === 'shell') shell.clear();
  else ui.terminal.replaceChildren();
});
document.getElementById('language-toggle').addEventListener('click', () => {
  state.locale = state.locale === 'zh' ? 'en' : 'zh';
  localStorage.setItem('minicodex-locale', state.locale);
  applyLanguage();
});

document.addEventListener('keydown', (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's' && state.mode === 'code') {
    event.preventDefault();
    saveFile();
  }
});
window.addEventListener('beforeunload', (event) => {
  if ([...editor.tabs.keys()].some((path) => editor.dirty(path))) {
    event.preventDefault();
    event.returnValue = '';
  }
});

applyLanguage();
setupResizers();
renderBottomTabs();
bootstrap();
