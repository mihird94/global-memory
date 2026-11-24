const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('brain', {
  platform: process.platform,
  request: async (action, params = {}) => {
    const response = await ipcRenderer.invoke('brain:request', action, params);
    if (response.error) throw new Error(response.error);
    return response.result;
  },
  copy: (value) => ipcRenderer.invoke('brain:copy', value),
  openLink: (value) => ipcRenderer.invoke('brain:link', value),
});
