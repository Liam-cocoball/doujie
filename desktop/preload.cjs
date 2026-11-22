const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('doujieDesktop', {
  openStage: () => ipcRenderer.invoke('doujie:open-stage'),
});
