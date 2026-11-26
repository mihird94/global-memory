const { app, BrowserWindow, clipboard, ipcMain, shell } = require('electron');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { existsSync, mkdirSync } = require('node:fs');
const { homedir } = require('node:os');
const path = require('node:path');
const { createInterface } = require('node:readline');

const root = path.resolve(__dirname, '..');
const localPython = path.join(root, '.venv', 'bin', 'python');
const python = process.env.BRAIN_PYTHON || (existsSync(localPython) ? localPython : 'python3');
const actions = new Set([
  'browse', 'changes', 'search', 'read', 'create', 'edit', 'archive', 'context', 'status',
  'board_list', 'board_read', 'board_open', 'board_assign', 'board_post', 'board_inbox', 'board_ack', 'board_agents',
  'export_list', 'export_read', 'export_init', 'export_stage', 'export_approve', 'export_revoke',
  'export_wire', 'export_save_profile', 'export_inventory', 'export_update_config',
  'export_inbox_promote', 'export_inbox_discard', 'export_discover', 'export_add_candidates',
]);
const icon = path.join(__dirname, 'assets', 'brain.png');

let window;
let backend;
let nextId = 0;
const pending = new Map();

function startBackend() {
  const child = spawn(python, ['-u', '-m', 'gm.desktop'], {
    cwd: root,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  backend = child;
  child.stderr.pipe(process.stderr, { end: false });
  child.stdin.on('error', () => { /* The close event reports the backend failure. */ });
  const lines = createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    let reply;
    try {
      reply = JSON.parse(line);
    } catch {
      return;
    }
    const job = pending.get(reply.id);
    if (!job) return;
    pending.delete(reply.id);
    clearTimeout(job.timer);
    if (reply.error) job.reject(new Error(reply.error));
    else job.resolve(reply.result);
  });
  child.on('error', (error) => console.error('Brain backend:', error.message));
  child.on('close', () => {
    if (backend !== child) return;
    backend = undefined;
    for (const job of pending.values()) {
      clearTimeout(job.timer);
      job.reject(new Error('The Brain backend stopped. Confirm the Python environment is installed, then refresh.'));
    }
    pending.clear();
  });
  return child;
}

function request(action, params) {
  const child = backend || startBackend();
  const id = ++nextId;
  const timeoutMs = (action === 'export_discover' || action === 'export_stage') ? 180_000 : 90_000;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('Brain took too long to respond. Refresh to check the result.'));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    child.stdin.write(`${JSON.stringify({ id, action, params })}\n`);
  });
}

function fromWindow(event) {
  return window && event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame;
}

ipcMain.handle('brain:request', async (event, action, params) => {
  if (!fromWindow(event) || !actions.has(action)) return { error: 'Invalid Brain request.' };
  try {
    return { result: await request(action, params) };
  } catch (error) {
    return { error: error.message };
  }
});

ipcMain.handle('brain:copy', (event, value) => {
  if (fromWindow(event) && typeof value === 'string') clipboard.writeText(value);
});

ipcMain.handle('brain:link', async (event, value) => {
  if (!fromWindow(event)) return;
  let url;
  try { url = new URL(value); } catch { return; }
  if (url.protocol === 'https:' || url.protocol === 'http:') await shell.openExternal(url.href);
});

function createWindow() {
  window = new BrowserWindow({
    width: 1450,
    height: 930,
    minWidth: 830,
    minHeight: 610,
    show: false,
    title: 'Brain',
    icon,
    backgroundColor: '#f8f8f4',
    ...(process.platform === 'darwin' ? { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 17, y: 17 } } : {}),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, respond) => respond(false));
  window.on('closed', () => { window = undefined; });
  window.once('ready-to-show', () => window.show());
  window.loadFile(path.join(__dirname, 'index.html'));
}

app.setName('Brain');
const customRoot = process.env.GM_HOME && path.resolve(process.env.GM_HOME);
if (customRoot && customRoot !== path.join(homedir(), 'memories') && !app.commandLine.hasSwitch('user-data-dir')) {
  const storeKey = createHash('sha256').update(customRoot).digest('hex').slice(0, 16);
  const profile = path.join(app.getPath('userData'), 'stores', storeKey);
  mkdirSync(profile, { recursive: true, mode: 0o700 });
  app.setPath('userData', profile);
}
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window?.isMinimized()) window.restore();
    window?.focus();
  });
  app.whenReady().then(() => {
    app.dock?.setIcon(icon);
    createWindow();
  });
  app.on('activate', () => { if (!window) createWindow(); });
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
  app.on('before-quit', () => backend?.kill());
}
