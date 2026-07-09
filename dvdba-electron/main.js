const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');

let mainWindow;
let pythonProcess = null;

function getPythonBackendPath() {
  const isDev = !app.isPackaged;
  if (isDev) {
    return path.join(__dirname, 'python-backend', 'backend.py');
  }
  return path.join(process.resourcesPath, 'python-backend', 'backend.py');
}

function startPythonBackend() {
  const backendPath = getPythonBackendPath();
  pythonProcess = spawn('python', [backendPath], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  });

  let buffer = '';
  pythonProcess.stdout.on('data', (data) => {
    buffer += data.toString();
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (line.trim()) {
        try {
          const msg = JSON.parse(line);
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('python-message', msg);
          }
        } catch (e) {
          console.error('Parse error:', line);
        }
      }
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error('Python err:', data.toString());
  });

  pythonProcess.on('close', (code) => {
    console.log('Python exited:', code);
    pythonProcess = null;
  });
}

function sendToPython(msg) {
  if (pythonProcess && pythonProcess.stdin.writable) {
    pythonProcess.stdin.write(JSON.stringify(msg) + '\n');
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    backgroundColor: '#0d0d1a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'src', 'index.html'));
}

// ── IPC Handlers ────────────────────────────────────────────────────

ipcMain.handle('minimize', () => mainWindow?.minimize());
ipcMain.handle('maximize', () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow?.maximize();
  }
});
ipcMain.handle('close', () => mainWindow?.close());

ipcMain.handle('open-file-dialog', async (event, filters) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: filters || [{ name: 'All Files', extensions: ['*'] }]
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('save-file-dialog', async (event, options) => {
  const result = await dialog.showSaveDialog(mainWindow, options);
  return result.canceled ? null : result.filePath;
});

ipcMain.handle('send-to-python', (event, msg) => {
  sendToPython(msg);
});

ipcMain.handle('get-file-size', (event, filePath) => {
  try {
    return fs.statSync(filePath).size;
  } catch {
    return 0;
  }
});

ipcMain.handle('get-video-info', async (event, filePath) => {
  return new Promise((resolve) => {
    const proc = spawn('python', ['-c', `
import json, sys
try:
    import cv2
    cap = cv2.VideoCapture('${filePath.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}')
    w = int(cap.get(3)); h = int(cap.get(4))
    fps = cap.get(5); nf = int(cap.get(7))
    cap.release()
    print(json.dumps({"width":w,"height":h,"fps":fps,"frames":nf}))
except Exception as e:
    print(json.dumps({"error":str(e)}))
    `]);
    let out = '';
    proc.stdout.on('data', d => out += d);
    proc.on('close', () => {
      try { resolve(JSON.parse(out)); }
      catch { resolve({ error: 'Failed to parse' }); }
    });
  });
});

// ── App Lifecycle ───────────────────────────────────────────────────

app.whenReady().then(() => {
  startPythonBackend();
  createWindow();
});

app.on('window-all-closed', () => {
  if (pythonProcess) {
    sendToPython({ cmd: 'shutdown' });
    setTimeout(() => pythonProcess?.kill(), 1000);
  }
  app.quit();
});

app.on('before-quit', () => {
  if (pythonProcess) {
    sendToPython({ cmd: 'shutdown' });
    pythonProcess.kill();
  }
});
