/* ── State ─────────────────────────────────────────────────────── */
const state = {
  encode: { inputPath: null, outputPath: null, running: false, cancelFlag: false },
  decode: { inputPath: null, outputPath: null, running: false },
  compare: { origPath: null, dvdbcPath: null, running: false },
};

/* ── Tabs ──────────────────────────────────────────────────────── */
function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  document.querySelector(`.nav-item[data-tab="${name}"]`).classList.add('active');
}

/* ── Toast ──────────────────────────────────────────────────────── */
function toast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; }, 3000);
  setTimeout(() => el.remove(), 3300);
}

/* ── Quality ────────────────────────────────────────────────────── */
function updateQuality(v) {
  document.getElementById('quality-value').textContent = v;
  document.querySelectorAll('.preset-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.q) === parseInt(v));
  });
}
function setQuality(v) {
  document.getElementById('quality-slider').value = v;
  updateQuality(v);
}

/* ── Helper: show image in preview ──────────────────────────────── */
function showPreview(containerId, dataUrl) {
  const box = document.getElementById(containerId);
  if (!dataUrl) {
    box.innerHTML = `<div class="preview-placeholder"><span>Preview</span></div>`;
    return;
  }
  box.innerHTML = `<img src="${dataUrl}" alt="preview">`;
}

function showPreviewBox(containerId, dataUrl) {
  const box = document.getElementById(containerId);
  if (!dataUrl) {
    box.innerHTML = `<div class="preview-placeholder"><span>Preview</span></div>`;
    return;
  }
  box.innerHTML = `<img src="${dataUrl}" alt="preview">`;
}

/* ── Encode Tab ────────────────────────────────────────────────── */
async function browseEncode() {
  const path = await window.electronAPI.openFile([
    { name: 'Video', extensions: ['mp4', 'avi', 'mov', 'mkv', 'webm'] },
    { name: 'All Files', extensions: ['*'] }
  ]);
  if (!path) return;
  state.encode.inputPath = path;
  document.getElementById('encode-file-name').textContent = path.split(/[\\/]/).pop();
  const info = await window.electronAPI.getVideoInfo(path);
  if (info.error) {
    document.getElementById('encode-file-info').textContent = 'Could not read video info';
    return;
  }
  const size = await window.electronAPI.getFileSize(path);
  document.getElementById('encode-file-info').textContent =
    `${info.width}x${info.height}  •  ${info.fps.toFixed(0)} fps  •  ${info.frames} frames  •  ${fmtSize(size)}`;
}

async function startEncode() {
  if (!state.encode.inputPath) { toast('Select a video file first', 'error'); return; }
  if (state.encode.running) return;

  const outPath = await window.electronAPI.saveFile({
    defaultPath: 'output.dvdbc',
    filters: [{ name: 'DVDBC Video', extensions: ['dvdbc'] }]
  });
  if (!outPath) return;

  state.encode.running = true;
  state.encode.cancelFlag = false;
  state.encode.outputPath = outPath;

  document.getElementById('encode-btn').style.display = 'none';
  document.getElementById('cancel-btn').style.display = 'block';
  document.getElementById('output-card').style.display = 'none';
  document.getElementById('encode-status').textContent = 'Starting...';
  document.getElementById('stat-frames').textContent = '0';

  const quality = parseInt(document.getElementById('quality-slider').value);
  const keyframe = parseInt(document.getElementById('kf-interval').value);

  window.electronAPI.sendToPython({
    cmd: 'encode',
    input: state.encode.inputPath,
    output: outPath,
    quality: quality,
    keyframe: keyframe,
    taskId: 'encode'
  });
}

function cancelEncode() {
  state.encode.cancelFlag = true;
  window.electronAPI.sendToPython({ cmd: 'cancel', taskId: 'encode' });
  document.getElementById('cancel-btn').style.display = 'none';
  document.getElementById('encode-status').textContent = 'Cancelling...';
}

function openOutputFolder() {
  const path = state.encode.outputPath;
  if (path) {
    const dir = path.substring(0, path.lastIndexOf(/[\\/]/.test(path) ? path.match(/[\\/]/)[0] : '/'));
    // Use shell
    window.electronAPI.sendToPython({ cmd: 'open-folder', path: dir });
  }
}

/* ── Decode Tab ────────────────────────────────────────────────── */
async function browseDecode() {
  const path = await window.electronAPI.openFile([
    { name: 'DVDBC Video', extensions: ['dvdbc'] },
    { name: 'All Files', extensions: ['*'] }
  ]);
  if (!path) return;
  state.decode.inputPath = path;
  document.getElementById('decode-file-name').textContent = path.split(/[\\/]/).pop();
  const size = await window.electronAPI.getFileSize(path);
  document.getElementById('decode-file-info').textContent = fmtSize(size);

  // Try to get header info via Python
  window.electronAPI.sendToPython({ cmd: 'probe', input: path, taskId: 'decode-probe' });
}

async function startDecode() {
  if (!state.decode.inputPath) { toast('Select a DVDBC file first', 'error'); return; }
  if (state.decode.running) return;

  const outPath = await window.electronAPI.saveFile({
    defaultPath: 'decoded.mp4',
    filters: [{ name: 'MP4 Video', extensions: ['mp4'] }]
  });
  if (!outPath) return;

  state.decode.running = true;
  state.decode.outputPath = outPath;
  document.getElementById('decode-progress').style.display = 'block';
  document.getElementById('decode-status').textContent = 'Decoding...';

  window.electronAPI.sendToPython({
    cmd: 'decode',
    input: state.decode.inputPath,
    output: outPath,
    taskId: 'decode'
  });
}

/* ── Compare Tab ──────────────────────────────────────────────── */
async function browseCompareOrig() {
  const path = await window.electronAPI.openFile([
    { name: 'Video', extensions: ['mp4', 'avi', 'mov'] },
    { name: 'All Files', extensions: ['*'] }
  ]);
  if (!path) return;
  state.compare.origPath = path;
  document.getElementById('comp-orig-name').textContent = path.split(/[\\/]/).pop();
  const info = await window.electronAPI.getVideoInfo(path);
  const size = await window.electronAPI.getFileSize(path);
  document.getElementById('comp-orig-size').textContent = fmtSize(size) + (info.width ? `  •  ${info.width}x${info.height}` : '');
}

async function browseCompareDvdbc() {
  const path = await window.electronAPI.openFile([
    { name: 'DVDBC Video', extensions: ['dvdbc'] },
    { name: 'All Files', extensions: ['*'] }
  ]);
  if (!path) return;
  state.compare.dvdbcPath = path;
  document.getElementById('comp-dvdbc-name').textContent = path.split(/[\\/]/).pop();
  const size = await window.electronAPI.getFileSize(path);
  document.getElementById('comp-dvdbc-size').textContent = fmtSize(size);
}

function startCompare() {
  if (!state.compare.origPath || !state.compare.dvdbcPath) {
    toast('Select both original and DVDBC files', 'error');
    return;
  }
  state.compare.running = true;
  document.getElementById('compare-results').style.display = 'none';
  document.getElementById('compare-status').textContent = 'Comparing...';
  window.electronAPI.sendToPython({
    cmd: 'compare',
    original: state.compare.origPath,
    compressed: state.compare.dvdbcPath,
    taskId: 'compare'
  });
}

/* ── Settings ──────────────────────────────────────────────────── */
function setTheme(name) {
  // Simple theme switching via CSS
  const root = document.documentElement;
  const themes = {
    dark: { bg: '#0a0a1a', card: '#181840', border: '#2a2a5a' },
    deep: { bg: '#0a0a2e', card: '#101050', border: '#202070' },
    midnight: { bg: '#0d0d1a', card: '#14142a', border: '#2a2a4a' },
    light: { bg: '#f0f0f8', card: '#ffffff', border: '#dddde8', text: '#1a1a2e' },
  };
  const t = themes[name] || themes.dark;
  root.style.setProperty('--bg-primary', t.bg);
  root.style.setProperty('--bg-card', t.card);
  root.style.setProperty('--border', t.border);
  if (t.text) root.style.setProperty('--text', t.text);
  localStorage.setItem('dvdba-theme', name);
}

function saveSettings() {
  toast('Settings saved', 'success');
}

/* ── Python IPC ────────────────────────────────────────────────── */
window.electronAPI.onPythonMessage((msg) => {
  const { taskId, status } = msg;

  if (taskId === 'encode') {
    handleEncodeMessage(msg);
  } else if (taskId === 'decode' || taskId === 'decode-probe') {
    handleDecodeMessage(msg);
  } else if (taskId === 'compare') {
    handleCompareMessage(msg);
  }
});

function handleEncodeMessage(msg) {
  const { status, percent, message, frames, size, time, error } = msg;

  if (status === 'progress') {
    document.getElementById('encode-progress-fill').style.width = (percent || 0) + '%';
    document.getElementById('encode-status').textContent = message || '';
    document.getElementById('encode-detail').textContent = `${percent || 0}%`;
    document.getElementById('stat-progress').textContent = (percent || 0) + '%';
  }

  if (status === 'done') {
    state.encode.running = false;
    document.getElementById('encode-btn').style.display = 'block';
    document.getElementById('cancel-btn').style.display = 'none';
    document.getElementById('encode-progress-fill').style.width = '100%';
    document.getElementById('encode-status').textContent = 'Complete!';
    document.getElementById('encode-detail').textContent = `${frames} frames • ${fmtTime(time)}`;
    document.getElementById('stat-frames').textContent = frames || '—';
    document.getElementById('stat-output').textContent = fmtSize(size || 0);
    document.getElementById('stat-speed').textContent = time ? (frames / time).toFixed(1) + ' fps' : '—';
    document.getElementById('output-name').textContent = '✅ ' + (state.encode.outputPath || '').split(/[\\/]/).pop();
    document.getElementById('output-info').textContent = `${fmtSize(size || 0)}  •  ${frames} frames  •  ${fmtTime(time)}`;
    document.getElementById('output-card').style.display = 'block';
    toast('Encoding complete!', 'success');
  }

  if (status === 'error') {
    state.encode.running = false;
    document.getElementById('encode-btn').style.display = 'block';
    document.getElementById('cancel-btn').style.display = 'none';
    document.getElementById('encode-status').textContent = 'Error: ' + (error || 'Unknown');
    toast(error || 'Encoding failed', 'error');
  }

  if (status === 'cancelled') {
    state.encode.running = false;
    document.getElementById('encode-btn').style.display = 'block';
    document.getElementById('cancel-btn').style.display = 'none';
    document.getElementById('encode-status').textContent = 'Cancelled';
  }
}

function handleDecodeMessage(msg) {
  const { status, message, info, percent, error } = msg;

  if (status === 'info' && info) {
    document.getElementById('decode-meta').textContent =
      `Resolution: ${info.width}x${info.height}\nFPS: ${info.fps}  •  Frames: ${info.frames}\nQuality: ${info.quality}`;
  }

  if (status === 'progress') {
    document.getElementById('decode-progress').style.display = 'block';
    document.getElementById('decode-progress-fill').style.width = (percent || 0) + '%';
    document.getElementById('decode-status').textContent = message || '';
  }

  if (status === 'done') {
    state.decode.running = false;
    document.getElementById('decode-progress-fill').style.width = '100%';
    document.getElementById('decode-status').textContent = '✅ Complete!';
    toast('Decoding complete!', 'success');
  }

  if (status === 'error') {
    state.decode.running = false;
    document.getElementById('decode-status').textContent = 'Error: ' + (error || '');
    toast(error || 'Decoding failed', 'error');
  }
}

function handleCompareMessage(msg) {
  const { status, psnr: psnrVal, ssim: ssimVal, ratio, frames, origSize, compSize, error } = msg;

  if (status === 'done') {
    state.compare.running = false;
    document.getElementById('compare-results').style.display = 'block';

    const psnrEl = document.getElementById('result-psnr');
    psnrEl.textContent = psnrVal ? psnrVal.toFixed(2) : '—';
    psnrEl.style.color = psnrVal > 35 ? '#00e676' : psnrVal > 25 ? '#ffab00' : '#ff1744';

    document.getElementById('result-ssim').textContent = ssimVal ? ssimVal.toFixed(4) : '—';
    document.getElementById('result-ratio').textContent = ratio ? ratio.toFixed(2) : '—';
    document.getElementById('result-frames').textContent = frames || '—';
    document.getElementById('compare-status').textContent =
      `Original: ${fmtSize(origSize)}  →  DVDBC: ${fmtSize(compSize)}`;
    toast('Comparison complete', 'success');
  }

  if (status === 'error') {
    state.compare.running = false;
    document.getElementById('compare-status').textContent = 'Error: ' + (error || '');
  }

  if (status === 'progress') {
    document.getElementById('compare-status').textContent = message || 'Comparing...';
  }
}

/* ── Utils ──────────────────────────────────────────────────────── */
function fmtSize(bytes) {
  if (!bytes || bytes === 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return bytes.toFixed(1) + ' ' + units[i];
}

function fmtTime(seconds) {
  if (!seconds) return '—';
  if (seconds < 60) return seconds.toFixed(1) + 's';
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(0);
  return m + 'm ' + s + 's';
}

/* ── Init ──────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // Load saved theme
  const saved = localStorage.getItem('dvdba-theme');
  if (saved) setTheme(saved);
});
