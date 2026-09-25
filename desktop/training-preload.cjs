const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('training', {
  profiles: () => ipcRenderer.invoke('training:profiles'),
  prepare: (model, name) => ipcRenderer.invoke('training:prepare', model, name),
  openFolder: () => ipcRenderer.invoke('training:open-folder')
});
