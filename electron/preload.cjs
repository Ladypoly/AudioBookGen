// Preload: expose a minimal, safe bridge to the renderer.
//   - window.__API_BASE__  : absolute URL of the FastAPI sidecar.
//   - window.electronAPI   : native dialogs (open book file, choose folder).
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("__API_BASE__", "http://127.0.0.1:8765");

contextBridge.exposeInMainWorld("electronAPI", {
  openBook: () => ipcRenderer.invoke("dialog:openBook"),
  chooseFolder: () => ipcRenderer.invoke("dialog:chooseFolder"),
});
