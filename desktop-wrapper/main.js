/**
 * Macrocomm Desktop Bubble (robust + server-hosted widget)
 * --------------------------------------------------------
 * Fixes:
 *  - Always finds a backend URL (env or config file fallback)
 *  - Shows the bubble even if the first page load fails
 *  - Tray "Show Chat" always creates/reveals the window
 *  - Single-instance lock (no multiple Electron apps)
 *  - Bottom-right positioning + always-on-top
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, globalShortcut, screen, shell } = require('electron');
const path = require('path');
const fs   = require('fs');
const url  = require('url');

// ---------------- 1) Resolve backend URL reliably ----------------
// Priority: ENV (MACROCOMM_URL) -> config/server_url.txt -> default
function readServerUrlFromConfig() {
  try {
    const cfg = path.join(__dirname, '..', 'config', 'server_url.txt');
    if (fs.existsSync(cfg)) {
      const val = fs.readFileSync(cfg, 'utf8').trim();
      if (val) return val;
    }
  } catch (_) {}
  return '';
}
const fromEnv   = (process.env.MACROCOMM_URL || '').trim();
const fromFile  = readServerUrlFromConfig();
const API_BASE  = (fromEnv || fromFile || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const WIDGET_URL = `${API_BASE}/static/host.html`; // server-hosted host page

// ---------------- 2) App identity + single instance ----------------
const APP_ID = 'com.macrocomm.assistant';
app.setAppUserModelId(APP_ID);
if (!app.requestSingleInstanceLock()) app.quit();

// ---------------- 3) Globals + helpers ----------------
let tray = null;
let bubble = null;

const BUBBLE_W = 420;
const BUBBLE_H = 560;
const MARGIN   = 16;

function bottomRightBounds(w, h) {
  const { workArea } = screen.getPrimaryDisplay();
  const x = Math.max(workArea.x, workArea.x + workArea.width  - w - MARGIN);
  const y = Math.max(workArea.y, workArea.y + workArea.height - h - MARGIN);
  return { x, y, width: w, height: h };
}

function ensureBubble() {
  if (bubble && !bubble.isDestroyed()) return bubble;

  const bounds = bottomRightBounds(BUBBLE_W, BUBBLE_H);

  // Optional preload
  const maybePreload = path.join(__dirname, 'preload.js');
  const webPrefs = {
    nodeIntegration: false,
    contextIsolation: true,
    sandbox: true,
    backgroundThrottling: false
  };
  if (fs.existsSync(maybePreload)) webPrefs.preload = maybePreload;

  bubble = new BrowserWindow({
    ...bounds,
    show: false,                 // we show explicitly
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    autoHideMenuBar: true,
    backgroundColor: '#00000000',
    webPreferences: webPrefs
  });

  // Strong on-top + visible across workspaces
  bubble.setAlwaysOnTop(true, 'screen-saver');
  bubble.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  // Open external links in default browser
  bubble.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // ----- Load the widget from the FastAPI server -----
  console.log('[Macrocomm] API_BASE =', API_BASE);
  console.log('[Macrocomm] Loading widget:', WIDGET_URL);
  bubble.loadURL(WIDGET_URL);

  // Show when ready, but also add a fallback in case load fails
  let shown = false;
  const tryShow = () => {
    if (!shown && bubble && !bubble.isDestroyed()) {
      bubble.show();
      bubble.focus();
      shown = true;
    }
  };

  bubble.once('ready-to-show', tryShow);

  // If load fails, show a tiny error HTML so users still see a window
  bubble.webContents.on('did-fail-load', (_e, code, desc, failingURL) => {
    console.error('[Macrocomm] did-fail-load', code, desc, failingURL);
    const html = `
      <html>
        <body style="margin:0;font-family:Segoe UI,Arial,sans-serif;background:#fff">
          <div style="padding:16px">
            <h3 style="margin:0 0 8px">Macrocomm Assistant</h3>
            <div style="color:#444">Could not load the chat UI.</div>
            <div style="margin-top:8px;font-size:12px;color:#666">
              Backend: ${API_BASE}<br/>
              Error: ${code} ${desc}
            </div>
          </div>
        </body>
      </html>`;
    bubble.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
    setTimeout(tryShow, 50);
  });

  // Keep positioned at bottom-right if display metrics change
  screen.on('display-metrics-changed', () => {
    if (!bubble || bubble.isDestroyed()) return;
    bubble.setBounds(bottomRightBounds(BUBBLE_W, BUBBLE_H));
  });

  bubble.on('closed', () => { bubble = null; });
  return bubble;
}

function showBubble() {
  const win = ensureBubble();
  if (!win) return;
  win.setBounds(bottomRightBounds(BUBBLE_W, BUBBLE_H));
  win.show();
  win.focus();
  win.setAlwaysOnTop(true, 'screen-saver'); // reinforce
}

function hideBubble() {
  if (!bubble || bubble.isDestroyed()) return;
  bubble.hide();
}

// ---------------- 4) Tray ----------------
function createTray() {
  // Prefer 32px icon; fall back to 16px if needed
  let trayImgPath = path.join(__dirname, '..', 'static', 'brand', 'icon32.png');
  if (!fs.existsSync(trayImgPath)) {
    trayImgPath = path.join(__dirname, '..', 'static', 'brand', 'icon16.png');
  }
  let icon = nativeImage.createFromPath(trayImgPath);
  icon = icon.isEmpty() ? nativeImage.createEmpty() : icon.resize({ width: 24, height: 24 });

  tray = new Tray(icon);
  tray.setToolTip('Macrocomm Assistant');

  const menu = Menu.buildFromTemplate([
    { label: 'Show Chat', click: () => showBubble() },
    { label: 'Hide Chat', click: () => hideBubble() },
    { type: 'separator' },
    { label: 'Reload',   click: () => { if (!bubble) ensureBubble(); bubble && bubble.reload(); } },
    { type: 'separator' },
    { label: 'Quit',     click: () => { globalShortcut.unregisterAll(); app.quit(); } }
  ]);
  tray.setContextMenu(menu);

  // Left-click toggles quickly
  tray.on('click', () => {
    if (!bubble || bubble.isDestroyed()) return showBubble();
    bubble.isVisible() ? hideBubble() : showBubble();
  });
}

// ---------------- 5) App lifecycle ----------------
app.whenReady().then(() => {
  console.log('[Macrocomm] Electron started');
  ensureBubble();     // create window immediately
  createTray();       // then tray

  // Global hotkey: toggle window
  globalShortcut.register('Control+Shift+Space', () => {
    if (!bubble || bubble.isDestroyed()) return showBubble();
    bubble.isVisible() ? hideBubble() : showBubble();
  });
});

// Keep process alive in tray even if all windows close
app.on('window-all-closed', (e) => e.preventDefault());

// On second launch, just bring the window up
app.on('second-instance', () => { showBubble(); });
