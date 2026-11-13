const { contextBridge, ipcRenderer } = require("electron");

// Only the bundled miniature receives this preload; never a remote page.
contextBridge.exposeInMainWorld("CodexDesktop", Object.freeze({
  request: (endpoint) => ipcRenderer.invoke("mini:request", endpoint),
  openAdmin: () => ipcRenderer.invoke("mini:open-admin"),
  associate: (hubUrl, code) => ipcRenderer.invoke("mini:associate", hubUrl, code),
  configurationSize: (expanded) => ipcRenderer.invoke("mini:configuration-size", expanded),
}));
