'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// Expose only fixed window actions, never a general-purpose IPC or filesystem API.
contextBridge.exposeInMainWorld('subtitleDesktop', Object.freeze({
  getState: () => ipcRenderer.invoke('desktop:state'),
  saveDisplayPreferences: (values) => ipcRenderer.invoke('desktop:display-save', values),
  setAlwaysOnTop: (enabled) => ipcRenderer.invoke('desktop:pin', Boolean(enabled)),
  minimize: () => ipcRenderer.invoke('desktop:minimize'),
  close: () => ipcRenderer.invoke('desktop:close'),
  beginResize: (edge) => ipcRenderer.invoke('desktop:resize-start', String(edge)),
  endResize: () => ipcRenderer.invoke('desktop:resize-stop'),
  openDataFolder: () => ipcRenderer.invoke('desktop:data-folder'),
  getCloudConfig: () => ipcRenderer.invoke('desktop:cloud-config'),
  saveCloudConfig: (region, key) => ipcRenderer.invoke('desktop:cloud-save', { region, key }),
}));
