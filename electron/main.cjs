// Electron main process.
//
// Responsibilities:
//   1. Spawn the FastAPI sidecar — `python -m server.main` in dev, the frozen
//      `abg-sidecar.exe` in a packaged build.
//   2. Point the sidecar at bundled assets (prompts/workflows) and a per-user
//      data folder (projects/settings) via env vars, and put bundled ffmpeg on
//      PATH so audio mixing/mastering works without a system install.
//   3. Create the BrowserWindow and load the frontend (Vite dev server when
//      ABG_DEV=1, else the packaged dist bundle).
//   4. Provide native dialogs over IPC (open a book file, choose export folder).

const { app, BrowserWindow, Menu, ipcMain, dialog } = require("electron");
const { spawn, execFileSync } = require("node:child_process");
const path = require("node:path");
const http = require("node:http");
const fs = require("node:fs");

const APP_TITLE = "Audio Drama Builder";

const API_PORT = 8765;
const DEV = process.env.ABG_DEV === "1";
const REPO_ROOT = path.resolve(__dirname, "..");

let sidecar = null;
let win = null;

function pythonExe() {
  const conda = "C:/Users/Elin/miniconda3/python.exe";
  return process.env.ABG_PYTHON || conda;
}

function sidecarEnv() {
  // User-writable data lives under the OS user-data dir; bundled read-only
  // assets + ffmpeg live in the install's resources folder.
  const env = { ...process.env, PYTHONUTF8: "1" };
  const dataRoot = app.getPath("userData");
  fs.mkdirSync(dataRoot, { recursive: true });
  env.ABG_DATA_ROOT = dataRoot;

  if (!DEV) {
    const res = process.resourcesPath;
    env.ABG_ASSET_ROOT = path.join(res, "assets");
    const ffmpegDir = path.join(res, "ffmpeg");
    if (fs.existsSync(ffmpegDir)) env.PATH = `${ffmpegDir}${path.delimiter}${env.PATH}`;
  }
  return env;
}

function startSidecar() {
  const env = sidecarEnv();
  if (DEV) {
    sidecar = spawn(pythonExe(), ["-m", "server.main"], {
      cwd: REPO_ROOT,
      stdio: "inherit",
      env,
    });
  } else {
    // Packaged: the frozen exe is windowless (console=False), and we hide any
    // window + detach stdio so no console flashes up for the user.
    const exe = path.join(process.resourcesPath, "sidecar", "abg-sidecar.exe");
    sidecar = spawn(exe, [], { cwd: path.dirname(exe), stdio: "ignore", windowsHide: true, env });
  }
  sidecar.on("exit", (code) => console.log(`[sidecar] exited ${code}`));
}

// Stop the sidecar AND its children (the headless ComfyUI it spawned). A plain
// kill() only terminates the sidecar and orphans ComfyUI, so on Windows we kill
// the whole process tree.
function stopSidecar() {
  const proc = sidecar;
  if (!proc || proc.killed) return;
  sidecar = null;
  const pid = proc.pid;
  try {
    if (process.platform === "win32" && pid) {
      execFileSync("taskkill", ["/F", "/T", "/PID", String(pid)], { stdio: "ignore" });
    } else {
      proc.kill();
    }
  } catch {
    /* already gone */
  }
}

function waitForApi(timeoutMs = 40000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(`http://127.0.0.1:${API_PORT}/api/ping`, (res) => {
        res.destroy();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) reject(new Error("sidecar did not start"));
        else setTimeout(tick, 400);
      });
    };
    tick();
  });
}

async function createWindow() {
  win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: "#0b0e16",
    show: false,
    title: APP_TITLE,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Keep our title — don't let the page's <title> override the window title.
  win.on("page-title-updated", (e) => e.preventDefault());
  win.once("ready-to-show", () => win.show());

  if (DEV) {
    await win.loadURL("http://localhost:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    await win.loadFile(path.join(process.resourcesPath, "frontend", "index.html"));
  }
}

// --- native dialogs (IPC) ---------------------------------------------------
ipcMain.handle("dialog:openBook", async () => {
  const r = await dialog.showOpenDialog(win, {
    title: "Choose a book file",
    properties: ["openFile"],
    filters: [
      { name: "Books", extensions: ["pdf", "epub", "txt", "docx", "doc"] },
      { name: "All files", extensions: ["*"] },
    ],
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle("dialog:chooseFolder", async () => {
  const r = await dialog.showOpenDialog(win, {
    title: "Choose export folder",
    properties: ["openDirectory", "createDirectory"],
  });
  return r.canceled ? null : r.filePaths[0];
});

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null); // no File/Edit/View/Window/Help menu bar
  startSidecar();
  try {
    await waitForApi();
  } catch (e) {
    console.error(e);
  }
  await createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  stopSidecar();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  stopSidecar();
});
