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
  const iconPath = path.join(__dirname, 'assets', 'icon.png');

  mainWindow = new BrowserWindow({
    width: 1320,
    height: 880,
    minWidth: 1020,
    minHeight: 680,
    title: 'Mbrain',
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#0d1117',
    icon: iconPath,
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
ipcMain.handle('gms:getTriageHistory', (event, limit) => requestAPI(`/api/triage/history?limit=${limit || 25}`));
ipcMain.handle('gms:getGraph', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/graph?${query}`);
});
ipcMain.handle('gms:getConcepts', () => requestAPI('/api/concepts'));
ipcMain.handle('gms:getEntityEvidence', (event, id) => requestAPI(`/api/entities/evidence?id=${encodeURIComponent(id || '')}`));
ipcMain.handle('gms:getRelationshipEvidence', (event, id) => requestAPI(`/api/relationships/evidence?id=${encodeURIComponent(id || '')}`));
ipcMain.handle('gms:getEntityDuplicates', (event, id) => requestAPI(`/api/entities/duplicates${id ? `?id=${encodeURIComponent(id)}` : ''}`));
ipcMain.handle('gms:getMemoryQuality', () => requestAPI('/api/v1/memory-quality'));
ipcMain.handle('gms:getMigrationInventory', () => requestAPI('/api/v1/migration/inventory'));
ipcMain.handle('gms:getAliases', (event, key) => requestAPI(`/api/v1/aliases${key ? `?key=${encodeURIComponent(key)}` : ''}`));
ipcMain.handle('gms:inspectRetrievalPlan', (event, payload) => requestAPI('/api/v1/retrieval/plan', 'POST', payload));
ipcMain.handle('gms:buildContextPacketV1', (event, payload) => requestAPI('/api/v1/context-packet', 'POST', payload));
ipcMain.handle('gms:extractText', (event, payload) => requestAPI('/api/concepts/extract', 'POST', payload));
ipcMain.handle('gms:getDailyNote', (event, date) => requestAPI(`/api/daily_note?date=${date || ''}`));
ipcMain.handle('gms:saveDailyNote', (event, payload) => requestAPI('/api/daily_note', 'POST', payload));
ipcMain.handle('gms:harvestDailyNote', (event, payload) => requestAPI('/api/daily_note/harvest', 'POST', payload));
ipcMain.handle('gms:getReminders', () => requestAPI('/api/reminders'));
ipcMain.handle('gms:createReminder', (event, payload) => requestAPI('/api/reminders', 'POST', payload));
ipcMain.handle('gms:getContracts', () => requestAPI('/api/contracts'));
ipcMain.handle('gms:getProjects', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/projects?${query}`);
});
ipcMain.handle('gms:getProject', (event, id) => requestAPI(`/api/projects/${encodeURIComponent(id || '')}`));
ipcMain.handle('gms:getProjectActivity', (event, params) => {
  const pid = params?.id || params?.projectId || '';
  const query = new URLSearchParams({
    limit: params?.limit || 50,
    ...(params?.before ? { before: params.before } : {})
  }).toString();
  return requestAPI(`/api/projects/${encodeURIComponent(pid)}/activity?${query}`);
});
ipcMain.handle('gms:getProjectKnowledge', (event, params) => {
  const pid = params?.id || params?.projectId || '';
  const query = new URLSearchParams({
    kind: params?.kind || 'all',
    limit: params?.limit || 50
  }).toString();
  return requestAPI(`/api/projects/${encodeURIComponent(pid)}/knowledge?${query}`);
});
ipcMain.handle('gms:getTaskResume', (event, id) => requestAPI(`/api/tasks/${encodeURIComponent(id || '')}/resume`));
ipcMain.handle('gms:previewContextPacket', (event, payload) => requestAPI('/api/context-packets/preview', 'POST', payload));
ipcMain.handle('gms:exportContextPacket', (event, payload) => requestAPI('/api/context-packets/export', 'POST', payload));
ipcMain.handle('gms:hybridSearch', (event, params) => {
  const query = new URLSearchParams({
    q: params?.query || params?.q || '',
    limit: params?.limit || 15
  }).toString();
  return requestAPI(`/api/search?${query}`);
});
ipcMain.handle('gms:mergeEntities', (event, payload) => requestAPI('/api/entities/merge', 'POST', payload));
ipcMain.handle('gms:getDreamCycleStatus', () => requestAPI('/api/dream-cycle/status'));
ipcMain.handle('gms:triggerDreamCycle', () => requestAPI('/api/dream-cycle/trigger', 'POST', {}));
ipcMain.handle('gms:getHarvestStatus', () => requestAPI('/api/harvest/status'));
ipcMain.handle('gms:getHarvestCandidates', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/harvest/candidates?${query}`);
});
ipcMain.handle('gms:getHarvestCandidate', (event, id) => requestAPI(`/api/harvest/candidates/${encodeURIComponent(id || '')}`));
ipcMain.handle('gms:reviewHarvestCandidate', (event, id, payload) => requestAPI(`/api/harvest/candidates/${encodeURIComponent(id || '')}/review`, 'POST', payload));
ipcMain.handle('gms:curateHarvestCandidates', (event, payload) => requestAPI('/api/harvest/curate', 'POST', payload));
ipcMain.handle('gms:contestHarvestCandidate', (event, id, payload) => requestAPI(`/api/harvest/candidates/${encodeURIComponent(id || '')}/contest`, 'POST', payload));
ipcMain.handle('gms:previewMigrateFlat', (event, payload) => requestAPI('/api/harvest/migrate-flat/preview', 'POST', payload));
ipcMain.handle('gms:getHarvestReviewers', () => requestAPI('/api/harvest/reviewers'));
ipcMain.handle('gms:getReviewAudit', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/harvest/audit?${query}`);
});
ipcMain.handle('gms:getPollutionAudit', () => requestAPI('/api/harvest/pollution/audit'));
ipcMain.handle('gms:runPollutionCleanup', (event, payload) => requestAPI('/api/harvest/pollution/cleanup', 'POST', payload));

// Pass 8: Project Intelligence & Agent Continuity
ipcMain.handle('gms:getProjectBriefing', (event, params) => {
  const pid = params?.id || params?.projectId || params?.project || '';
  const query = new URLSearchParams({
    ...(params?.as_of ? { as_of: params.as_of } : {}),
    ...(params?.profile ? { profile: params.profile } : {}),
  }).toString();
  return requestAPI(`/api/projects/${encodeURIComponent(pid)}/briefing?${query}`);
});
ipcMain.handle('gms:explainProjectBriefing', (event, params) => {
  const pid = params?.id || params?.projectId || params?.project || '';
  const query = new URLSearchParams({
    ...(params?.as_of ? { as_of: params.as_of } : {}),
    ...(params?.profile ? { profile: params.profile } : {}),
  }).toString();
  return requestAPI(`/api/projects/${encodeURIComponent(pid)}/briefing/explain?${query}`);
});
ipcMain.handle('gms:getProjectTimeline', (event, params) => {
  const pid = params?.id || params?.projectId || params?.project || '';
  const query = new URLSearchParams({
    ...(params?.type ? { type: params.type } : {}),
    ...(params?.agent ? { agent: params.agent } : {}),
    limit: params?.limit || 50,
  }).toString();
  return requestAPI(`/api/projects/${encodeURIComponent(pid)}/timeline?${query}`);
});
ipcMain.handle('gms:getResumeBundle', (event, params) => {
  const pid = params?.id || params?.projectId || params?.project || '';
  return requestAPI(`/api/projects/${encodeURIComponent(pid)}/resume`, 'POST', params);
});
ipcMain.handle('gms:getDecisions', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/decisions?${query}`);
});
ipcMain.handle('gms:getDecision', (event, id) => requestAPI(`/api/decisions/${encodeURIComponent(id || '')}`));
ipcMain.handle('gms:getDecisionImpact', (event, id) => requestAPI(`/api/decisions/${encodeURIComponent(id || '')}/impact`));
ipcMain.handle('gms:getActionInbox', (event, params) => {
  const query = new URLSearchParams(params || {}).toString();
  return requestAPI(`/api/inbox?${query}`);
});
ipcMain.handle('gms:previewInboxAction', (event, payload) => requestAPI('/api/inbox/preview', 'POST', payload));
ipcMain.handle('gms:applyInboxAction', (event, payload) => requestAPI('/api/inbox/apply', 'POST', payload));
ipcMain.handle('gms:getRepairEvidence', (event, key) => requestAPI(`/api/repair/${encodeURIComponent(key || '')}/evidence`));
ipcMain.handle('gms:analyzeRepairRecord', (event, key) => requestAPI(`/api/repair/${encodeURIComponent(key || '')}/analyze`));
ipcMain.handle('gms:stageRepairRecord', (event, payload) => requestAPI(`/api/repair/${encodeURIComponent(payload?.key || '')}/stage`, 'POST', payload));
ipcMain.handle('gms:getMorningBriefing', (event, params) => {
  const pid = params?.id || params?.projectId || params?.project || '';
  const query = new URLSearchParams({
    ...(params?.as_of ? { as_of: params.as_of } : {}),
  }).toString();
  return requestAPI(`/api/projects/${encodeURIComponent(pid)}/morning-briefing?${query}`);
});
ipcMain.handle('gms:getResumptionEvaluation', () => requestAPI('/api/eval/resumption'));

app.whenReady().then(() => {
  const iconPath = path.join(__dirname, 'assets', 'icon.png');
  if (process.platform === 'darwin' && app.dock) {
    try {
      app.dock.setIcon(iconPath);
    } catch (e) {}
  }
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
