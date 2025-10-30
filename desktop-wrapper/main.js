/**
 * Macrocomm Desktop Bubble (robust local test build)
 * --------------------------------------------------
 * Fixes:
 *  - Load the widget from the running FastAPI server (http URL) not file://
 *  - Auto-show the bubble on first run so you SEE it without using the tray
 *  - Create a Tray with a safe fallback icon so it always exists
 *  - Keep a single frameless, always-on-top window (no big black host window)
 *  - Add a global hotkey (Ctrl+Shift+Space) to toggle show/hide
 *
 * When you switch to the server, just change MACROCOMM_URL (via cross-env or BAT).
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, globalShortcut, screen, shell } = require('electron');
const path = require('path');
const fs = require('fs');

// ---------- 1) Config ----------
// Where to load the widget host page from.
// For local dev we hit the FastAPI server directly.
const API_BASE = (process.env.MACROCOMM_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const WIDGET_URL = `${API_BASE}/static/host.html`;   // <-- your host page on the server

const BUBBLE_W = 420;
const BUBBLE_H = 560;
const MARGIN   = 16;
const APP_ID   = 'com.macrocomm.assistant';

// ---------- 2) Globals ----------
let tray = null;
let bubble = null;

// Make single instance
if (!app.requestSingleInstanceLock()) app.quit();
app.setAppUserModelId(APP_ID);

// Compute bottom-right window bounds on the primary display
function bottomRightBounds(w, h) {
  const { workArea } = screen.getPrimaryDisplay();
  const x = Math.max(workArea.x, workArea.x + workArea.width  - w - MARGIN);
  const y = Math.max(workArea.y, workArea.y + workArea.height - h - MARGIN);
  return { x, y, width: w, height: h };
}

function createBubble() {
  const bounds = bottomRightBounds(BUBBLE_W, BUBBLE_H);

  // Guarded preload (optional file)
  const maybePreload = path.join(__dirname, 'preload.js');
  const webPrefs = {
    nodeIntegration: false,
    contextIsolation: true,
    sandbox: true,
    backgroundThrottling: false
  };
  if (fs.existsSync(maybePreload)) webPrefs.preload = maybePreload;

  // Frameless, transparent bubble (no black rectangle)
  bubble = new BrowserWindow({
    ...bounds,
    show: false,                 // we'll show explicitly when ready
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

  // Strongest on-top level on Windows, and visible across workspaces
  bubble.setAlwaysOnTop(true, 'screen-saver');
  bubble.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  // Open external links in default browser
  bubble.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Load the widget host from the running FastAPI server
  bubble.loadURL(WIDGET_URL);

  // AUTO-SHOW so you see it immediately on first run;
  // later, you can comment this and rely purely on tray/hotkey.
  bubble.once('ready-to-show', () => {
    bubble.show();
    bubble.focus();
  });

  // Esc hides
  bubble.webContents.on('before-input-event', (_e, input) => {
    if (input.type === 'keyDown' && input.key === 'Escape') hideBubble();
  });

  // Keep positioned at bottom-right if display geometry changes
  screen.on('display-metrics-changed', () => {
    if (!bubble) return;
    bubble.setBounds(bottomRightBounds(BUBBLE_W, BUBBLE_H));
  });

  bubble.on('closed', () => { bubble = null; });
}

function createTray() {
  // --- Tray icon handling (scales for clarity) ---
  let trayImgPath = path.join(__dirname, '..', 'static', 'brand', 'icon32.png'); // 32x32 or larger image
  if (!fs.existsSync(trayImgPath)) {
    // Fallback if you only have icon16.png
    trayImgPath = path.join(__dirname, '..', 'static', 'brand', 'icon16.png');
  }
  let icon = nativeImage.createFromPath(trayImgPath);
  // Optional: explicitly resize for visibility (Windows ignores oversize but scales crisp)
  icon = icon.resize({ width: 24, height: 24 });   // try 20–28 for best results
  // Optional: mark as template for dark/light modes on macOS (ignored on Windows)
  // icon.setTemplateImage(true);
  tray = new Tray(icon);
  tray.setToolTip('Macrocomm Assistant');

  const menu = Menu.buildFromTemplate([
    { label: 'Show Chat', click: showBubble },
    { label: 'Hide Chat', click: hideBubble },
    { type: 'separator' },
    { label: 'Reload', click: () => bubble && bubble.reload() },
    { type: 'separator' },
    { label: 'Quit', click: () => { globalShortcut.unregisterAll(); app.quit(); } }
  ]);
  tray.setContextMenu(menu);

  // Left-click toggles quickly
  tray.on('click', () => {
    if (!bubble) return;
    bubble.isVisible() ? hideBubble() : showBubble();
  });
}

function showBubble() {
  if (!bubble) return;
  bubble.setBounds(bottomRightBounds(BUBBLE_W, BUBBLE_H)); // re-place
  bubble.show();
  bubble.focus();
  bubble.setAlwaysOnTop(true, 'screen-saver'); // reinforce
}

function hideBubble() {
  if (!bubble) return;
  bubble.hide();
}

// ---------- 3) App lifecycle ----------
app.whenReady().then(() => {
  // Helpful console line so you can see Electron actually started
  // (Run with $env:ELECTRON_ENABLE_LOGGING="1" if you want verbose logs)
  console.log('[Macrocomm] Electron started. API_BASE =', API_BASE);
  console.log('[Macrocomm] Loading widget from', WIDGET_URL);

  createBubble();
  createTray();

  // Global hotkey to toggle
  globalShortcut.register('Control+Shift+Space', () => {
    if (!bubble) return;
    bubble.isVisible() ? hideBubble() : showBubble();
  });
});

// Keep process alive in tray even if no windows
app.on('window-all-closed', (e) => e.preventDefault());

// On re-activate (macOS), recreate bubble if needed
app.on('activate', () => { if (!bubble) createBubble(); });

// If a second instance is launched, just show the existing bubble
app.on('second-instance', () => { showBubble(); });