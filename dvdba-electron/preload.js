const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // Window controls
  minimize: () => ipcRenderer.invoke('minimize'),
  maximize: () => ipcRenderer.invoke('maximize'),
  close: () => ipcRenderer.invoke('close'),

  // File dialogs
  openFile: (filters) => ipcRenderer.invoke('open-file-dialog', filters),
  saveFile: (options) => ipcRenderer.invoke('save-file-dialog', options),

  // Python backend
  sendToPython: (msg) => ipcRenderer.invoke('send-to-python', msg),
  onPythonMessage: (callback) => {
    ipcRenderer.on('python-message', (event, msg) => callback(msg));
  },

  // File utils
  getFileSize: (path) => ipcRenderer.invoke('get-file-size', path),
  getVideoInfo: (path) => ipcRenderer.invoke('get-video-info', path),
});
