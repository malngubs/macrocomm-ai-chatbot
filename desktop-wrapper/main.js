/**
 * Macrocomm Desktop Wrapper — SAFE main process (Bubble Mode)
 * - No 'window' usage in main (Node context only)
 * - Serves local UI from /static on 127.0.0.1:8000
 * - Passes backend API base to the renderer via ?api_base=...
 * - Bubble window: bottom-right, frameless, transparent, hidden from taskbar
 * - Tray icon toggles visibility
 */

const { app, BrowserWindow, Menu, Tray, nativeImage, screen } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const url = require("url");

// ---------- resolve API base (ENV -> config -> default) ----------
function readServerUrlFromConfig() {
  try {
    const p = path.join(__dirname, "..", "static", "server-url.txt");
    return (fs.readFileSync(p, "utf8") || "").trim();
  } catch { return ""; }
}
const normalizeBase = (u) => (u || "").trim().replace(/\/+$/, "");
function resolveApiBase() {
  // Example: MACROCOMM_URL=http://bot.macrocomm.local:8000
  const fromEnv  = normalizeBase(process.env.MACROCOMM_URL);
  if (fromEnv) return fromEnv;

  const fromFile = normalizeBase(readServerUrlFromConfig());
  if (fromFile) return fromFile;

  // Dev fallback
  return "http://127.0.0.1:8000";
}

// ---------- tiny static file server for /static/* ----------
function startStaticServer(rootDir, port = 8000) {
  const mime = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".woff2": "font/woff2",
    ".woff": "font/woff", ".ttf": "font/ttf",
  };

  const server = http.createServer((req, res) => {
    try {
      const parsed = url.parse(req.url || "/");

      // Only serve /static/*
      if (!parsed.pathname.startsWith("/static/")) {
        res.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ detail: "Not Found" }));
        return;
      }

      // Map /static/... → <rootDir>/...
      const rel = parsed.pathname.replace(/^\/static\//, "").replace(/\.\.[/\\]/g, "");
      const filePath = path.join(rootDir, rel);

      if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
        res.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ detail: "Not Found" }));
        return;
      }

      const ext = path.extname(filePath).toLowerCase();
      res.writeHead(200, { "Content-Type": mime[ext] || "application/octet-stream", "Cache-Control": "no-cache" });
      fs.createReadStream(filePath).pipe(res);
    } catch (e) {
      res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ detail: "Static server error", error: String(e) }));
    }
  });

  server.listen(port, "127.0.0.1", () => {
    console.log(`[Macrocomm] Static UI server on http://127.0.0.1:${port}/static/`);
  });

  return server;
}

// ---------- window/tray (still main process — no 'window' global) ----------
let staticServer = null;
let tray = null;
let win = null;

function getBottomRightPosition(width, height) {
  const d = screen.getPrimaryDisplay().workArea;   // respects taskbar
  const margin = 16;
  return {
    x: Math.max(d.x, d.x + d.width  - width  - margin),
    y: Math.max(d.y, d.y + d.height - height - margin),
  };
}

function createWindow() {
  const apiBase = resolveApiBase();   // e.g., http://bot.macrocomm.local:8000
  console.log(`[Macrocomm] RESOLVED API_BASE = ${apiBase}`);

  // start the tiny server that serves /static/*
  staticServer ||= startStaticServer(path.join(__dirname, "..", "static"), 8000);

  // ---- Option A: bubble-like window (frameless, transparent, bottom-right) ----
  const WIDTH = 420, HEIGHT = 640;
  const pos = getBottomRightPosition(WIDTH, HEIGHT);

  Menu.setApplicationMenu(null); // remove menu bar

  win = new BrowserWindow({
    width: WIDTH,
    height: HEIGHT,
    x: pos.x,
    y: pos.y,
    frame: false,           // bubble look (no OS chrome)
    transparent: true,      // allows rounded/overlay styled UI
    resizable: false,       // avoid accidental resize
    movable: true,
    alwaysOnTop: false,     // set to true if you want it above all windows
    skipTaskbar: true,      // hide from taskbar
    show: false,            // show only when ready (avoid flash)
    backgroundColor: "#00000000",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true
    }
  });

  // Pass api_base in query string for the renderer (host.html) to read
  const hostUrl = `http://127.0.0.1:8000/static/host.html?api_base=${encodeURIComponent(apiBase)}`;
  console.log(`[Macrocomm] Loading widget: ${hostUrl}`);
  win.loadURL(hostUrl);

  // Smooth first paint
  win.once("ready-to-show", () => win.show());
}

function toggleWindow() {
  if (!win) return createWindow();
  if (win.isVisible()) {
    win.hide();
  } else {
    const WIDTH = 420, HEIGHT = 640;
    const pos = getBottomRightPosition(WIDTH, HEIGHT);
    win.setBounds({ x: pos.x, y: pos.y, width: WIDTH, height: HEIGHT });
    win.show();
  }
}

function createTray() {
  try {
    const iconPath = path.join(__dirname, "..", "static", "brand", "tray.png");
    const image = nativeImage.createFromPath(iconPath);
    tray = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image);
  } catch {
    tray = new Tray(nativeImage.createEmpty());
  }
  tray.setToolTip("Macrocomm Assistant");
  tray.on("click", toggleWindow);
}

app.whenReady().then(() => {
  createWindow();
  createTray();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("quit", () => {
  try { staticServer && staticServer.close(); } catch {}
});
