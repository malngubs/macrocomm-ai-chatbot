// Macrocomm Desktop Wrapper — Final popup build
// - Tray icon with left-click toggle
// - Frameless, transparent window anchored bottom-right
// - Loads the widget host URL
// - Auto-opens the chat (fallback clicks launcher if needed)
// - Minimal logging to help future debugging

const { app, BrowserWindow, Tray, Menu, nativeImage, screen, globalShortcut } = require('electron');
const path = require('path');
const fs = require('fs');

// ---------------------------- CONFIG ---------------------------------
const WIDGET_URL = 'http://127.0.0.1:8000/static/host.html';  // <— change to central HTTPS URL after rollout
const POPUP_W = 420;
const POPUP_H = 380;
const APP_ID   = 'com.macrocomm.assistant';
// ---------------------------------------------------------------------

// --------------- Logging (kept lightweight & persistent) --------------
const LOG_DIR  = path.join(process.env.LOCALAPPDATA || app.getPath('userData'), 'MacrocommAssistant');
const LOG_FILE = path.join(LOG_DIR, 'electron-startup.log');
if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
function log(...a){ fs.appendFileSync(LOG_FILE, `[${new Date().toISOString()}] ${a.join(' ')}\n`); }
// ---------------------------------------------------------------------

let win, tray;

function trayIcon() {
  // Use a real icon — Windows will hide empty/transparent images
  const dev = path.join(__dirname, 'assets', 'tray.ico');
  const devPng = path.join(__dirname, 'assets', 'tray.png');
  const prod = path.join(process.resourcesPath || __dirname, 'assets', 'tray.ico');
  for (const p of [dev, devPng, prod]) {
    if (fs.existsSync(p)) {
      const img = nativeImage.createFromPath(p);
      if (!img.isEmpty()) return img;
    }
  }
  // fallback: small opaque square
  const buf = Buffer.alloc(16*16*4, 0xff);
  return nativeImage.createFromBuffer(buf, { width:16, height:16, scaleFactor:1 });
}

function anchorBR() {
  const wa = screen.getPrimaryDisplay().workArea;
  return { x: Math.round(wa.x + wa.width - POPUP_W - 8), y: Math.round(wa.y + wa.height - POPUP_H - 8) };
}

function createWindow() {
  log('createWindow');
  win = new BrowserWindow({
    width: POPUP_W,
    height: POPUP_H,
    show: false,            // show after ready-to-show
    frame: false,           // no native frame (true popup look)
    resizable: false,
    movable: false,
    skipTaskbar: true,
    alwaysOnTop: true,

    // Transparent popup (just the chat UI)
    transparent: true,
    backgroundColor: '#00000000',

    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  // Keep the window pinned bottom-right
  const pos = anchorBR();
  win.setPosition(pos.x, pos.y, false);

  // Load host page
  win.loadURL(WIDGET_URL).catch(err => log('loadURL error:', err?.message));

  // Show quickly when ready
  win.once('ready-to-show', () => { log('ready-to-show'); win.show(); });

  // After load, try to auto-open bubble and hide only close/dismiss controls.
  win.webContents.on('did-finish-load', () => {
    log('did-finish-load');

    // Keep page edges clean; do NOT hide the launcher
    win.webContents.insertCSS(`
      html, body { margin:0!important; padding:0!important; overflow:hidden!important; background:transparent!important; }
    `).catch(()=>{});

    // Inject a small <script> before </body> so Chrome/host pages run the auto-open logic in page context
    const autoOpenScript = `
      (function () {
        function clickLauncher(doc) {
          let el = doc.querySelector('[aria-label*="open" i],[aria-label*="toggle" i],[aria-label*="launcher" i]');
          if (el) { el.click(); return true; }
          el = doc.querySelector('.mc-launcher,.macrocomm-launcher,.widget-launcher');
          if (el) { el.click(); return true; }
          const wants = [/ask macro-?bot/i, /open chat/i, /open bot/i, /ask macrocomm/i];
          for (const b of doc.querySelectorAll('button,[role="button"]')) {
            const t = (b.innerText || b.textContent || '').trim();
            if (wants.some(rx => rx.test(t))) { b.click(); return true; }
          }
          return false;
        }
        function tryOpen() {
          if (clickLauncher(document)) return;
          setTimeout(() => clickLauncher(document), 600);
          setTimeout(() => clickLauncher(document), 1200);
        }
        if (document.readyState === 'loading') {
          document.addEventListener('DOMContentLoaded', tryOpen);
        } else {
          tryOpen();
        }
      })();
    `;
    // Append script element into the page so it runs in page context (better compatibility with some hosts)
    win.webContents.executeJavaScript(`(function(){ const s = document.createElement('script'); s.type = 'text/javascript'; s.textContent = ${JSON.stringify(autoOpenScript)}; (document.body || document.head || document.documentElement).appendChild(s); })();`).catch(()=>{});

    // Backstop click to open the bubble if the page didn't already auto-open it
    win.webContents.executeJavaScript(`
      (function(){
        function clickLauncher(doc){
          let el = doc.querySelector('[aria-label*="open" i],[aria-label*="toggle" i],[aria-label*="launcher" i]');
          if (el) { el.click(); return true; }
          el = doc.querySelector('.mc-launcher,.macrocomm-launcher,.widget-launcher');
          if (el) { el.click(); return true; }
          const wants = [/ask macro-?bot/i, /open chat/i, /open bot/i, /ask macrocomm/i];
          for (const b of doc.querySelectorAll('button,[role="button"]')) {
            const t=(b.innerText||b.textContent||'').trim();
            if (wants.some(rx=>rx.test(t))) { b.click(); return true; }
          }
          return false;
        }
        let tries = 0;
        (function retry(){
          if (clickLauncher(document) || ++tries > 4) return;
          setTimeout(retry, 500);
        })();
      })();
    `).catch(()=>{});
  });

  // Hide on close (keep process alive for tray)
  win.on('close', (e) => { e.preventDefault(); win.hide(); });
}

function createTray() {
  log('createTray');
  tray = new Tray(trayIcon());
  tray.setToolTip('Macrocomm Assistant');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open', click: () => { const p=anchorBR(); win.setPosition(p.x,p.y,false); win.show(); win.focus(); } },
    { label: 'Hide', click: () => win.hide() },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() }
  ]));
  // Left-click toggles
  tray.on('click', () => {
    if (win.isVisible()) win.hide();
    else { const p=anchorBR(); win.setPosition(p.x,p.y,false); win.show(); win.focus(); }
  });
}

if (!app.requestSingleInstanceLock()) app.quit();
app.setAppUserModelId(APP_ID);

app.whenReady().then(() => {
  createWindow();
  createTray();

  // Optional: hotkey Ctrl+Shift+M toggles popup
  globalShortcut.register('Control+Shift+M', () => {
    if (win.isVisible()) win.hide();
    else { const p=anchorBR(); win.setPosition(p.x,p.y,false); win.show(); win.focus(); }
  });
});

app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => { /* keep running for tray */ });
