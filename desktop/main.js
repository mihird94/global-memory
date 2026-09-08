const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn, execFile } = require('child_process');
const http = require('http');
const fs = require('fs');

let mainWindow = null;
let apiProcess = null;
const API_PORT = 28765;
const REPO_ROOT = path.resolve(__dirname, '..');

// Discover Python binary
function getPythonPath() {
  const venvPython = path.join(REPO_ROOT, '.venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) return venvPython;
  if (fs.existsSync('/usr/bin/python3')) return '/usr/bin/python3';
  return 'python3';
}

function startBackendServer() {
  const pythonPath = getPythonPath();
  const scriptPath = path.join(REPO_ROOT, 'tools', 'gms_desktop_api.py');

  apiProcess = spawn(pythonPath, [scriptPath, '--serve', '--port', API_PORT.toString()], {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: 'pipe',
  });

  apiProcess.stdout.on('data', (data) => {
    console.log(`[GMS API]: ${data.toString().trim()}`);
  });

  apiProcess.stderr.on('data', (data) => {
    console.error(`[GMS API ERR]: ${data.toString().trim()}`);
  });

  apiProcess.on('close', (code) => {
    console.log(`[GMS API] exited with code ${code}`);
  });
}

// Fallback CLI invoke if needed
function callCLI(action, args = {}) {
  return new Promise((resolve, reject) => {
    const pythonPath = getPythonPath();
    const scriptPath = path.join(REPO_ROOT, 'tools', 'gms_desktop_api.py');
    execFile(
      pythonPath,
      [scriptPath, '--action', action, '--args', JSON.stringify(args)],
      { cwd: REPO_ROOT, maxBuffer: 10 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          return reject(new Error(stderr || error.message));
        }
        try {
          const parsed = JSON.parse(stdout);
          resolve(parsed);
        } catch (e) {
          resolve({ raw: stdout });
        }
      }
    );
  });
}

// HTTP request helper to local API
function requestAPI(endpoint, method = 'GET', body = null) {
  return new Promise((resolve, reject) => {
    const postData = body ? JSON.stringify(body) : null;
    const options = {
      hostname: '127.0.0.1',
      port: API_PORT,
      path: endpoint,
      method: method,
      headers: {
        'Content-Type': 'application/json',
        ...(postData ? { 'Content-Length': Buffer.byteLength(postData) } : {}),
      },
      timeout: 10000,
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => {
        data += chunk;
      });
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (err) {
          resolve({ raw: data });
        }
      });
    });

    req.on('error', (err) => {
      // Fallback to CLI execution if HTTP server is not yet ready
      const action = endpoint.replace('/api/', '').split('?')[0].replace('/', '_');
      callCLI(action, body || {})
        .then(resolve)
        .catch(reject);
    });

    if (postData) {
      req.write(postData);
    }
    req.end();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 880,
    minWidth: 1020,
    minHeight: 680,
    title: 'Global Memory System',
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#0d1117',
    trafficLightPosition: { x: 18, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'src', 'index.html'));

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// IPC Handlers
ipcMain.handle('gms:getSnapshot', () => requestAPI('/api/snapshot'));
ipcMain.handle('gms:getMemories', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/memories?${query}`);
});
ipcMain.handle('gms:saveFact', (event, payload) => requestAPI('/api/memories/fact', 'POST', payload));
ipcMain.handle('gms:deleteFact', (event, payload) => requestAPI('/api/memories/delete', 'POST', payload));
ipcMain.handle('gms:validateFact', (event, payload) => requestAPI('/api/validate', 'POST', payload));
ipcMain.handle('gms:getQuarantine', () => requestAPI('/api/quarantine'));
ipcMain.handle('gms:resolveQuarantine', (event, payload) => requestAPI('/api/quarantine/resolve', 'POST', payload));
ipcMain.handle('gms:getGraph', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/graph?${query}`);
});
ipcMain.handle('gms:getConcepts', () => requestAPI('/api/concepts'));
ipcMain.handle('gms:extractText', (event, payload) => requestAPI('/api/concepts/extract', 'POST', payload));
ipcMain.handle('gms:getDailyNote', (event, date) => requestAPI(`/api/daily_note?date=${date || ''}`));
ipcMain.handle('gms:saveDailyNote', (event, payload) => requestAPI('/api/daily_note', 'POST', payload));
ipcMain.handle('gms:harvestDailyNote', (event, payload) => requestAPI('/api/daily_note/harvest', 'POST', payload));
ipcMain.handle('gms:getReminders', () => requestAPI('/api/reminders'));
ipcMain.handle('gms:createReminder', (event, payload) => requestAPI('/api/reminders', 'POST', payload));
ipcMain.handle('gms:getContracts', () => requestAPI('/api/contracts'));

app.whenReady().then(() => {
  startBackendServer();
  // Small delay to ensure API server starts before window loads
  setTimeout(createWindow, 300);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  if (apiProcess) {
    try {
      apiProcess.kill();
    } catch (e) {}
  }
});
