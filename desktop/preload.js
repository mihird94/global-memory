const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('gms', {
  getSnapshot: () => ipcRenderer.invoke('gms:getSnapshot'),
  getMemories: (params) => ipcRenderer.invoke('gms:getMemories', params),
  saveFact: (payload) => ipcRenderer.invoke('gms:saveFact', payload),
  deleteFact: (payload) => ipcRenderer.invoke('gms:deleteFact', payload),
  validateFact: (payload) => ipcRenderer.invoke('gms:validateFact', payload),
  getQuarantine: () => ipcRenderer.invoke('gms:getQuarantine'),
  resolveQuarantine: (payload) => ipcRenderer.invoke('gms:resolveQuarantine', payload),
  getGraph: (params) => ipcRenderer.invoke('gms:getGraph', params),
  getConcepts: () => ipcRenderer.invoke('gms:getConcepts'),
  extractText: (payload) => ipcRenderer.invoke('gms:extractText', payload),
  getDailyNote: (date) => ipcRenderer.invoke('gms:getDailyNote', date),
  saveDailyNote: (payload) => ipcRenderer.invoke('gms:saveDailyNote', payload),
  harvestDailyNote: (payload) => ipcRenderer.invoke('gms:harvestDailyNote', payload),
  getReminders: () => ipcRenderer.invoke('gms:getReminders'),
  createReminder: (payload) => ipcRenderer.invoke('gms:createReminder', payload),
  getContracts: () => ipcRenderer.invoke('gms:getContracts'),
});
