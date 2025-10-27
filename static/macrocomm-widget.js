// static/macrocomm-widget.js  (v3 stable)
// Minimal, robust widget with fixed-height header, full-rounded card,
// and start-of-message scrolling so answers are readable from the top.

(() => {
  const BRAND_URL = "/brand.json";
  const VERSION = "v3"; // cache buster

  /* ------------- utils ------------- */
  const qs = (s, r = document) => r.querySelector(s);
  const ce = (t, c) => { const n = document.createElement(t); if (c) n.className = c; return n; };

  // Format LLM text so users never see markdown asterisks or odd list dashes.
  function sanitiseAndFormatLLM(text) {
    // Basic HTML escape (safety)
    const escape = (s) => s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    let t = escape(text);

    // 1) Convert **bold** → <strong>bold</strong>
    t = t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

    // 2) Convert ATX headings (## Heading) → <strong>Heading</strong>
    t = t.replace(/^\s*#{1,6}\s+(.+?)\s*$/gm, "<strong>$1</strong>");

    // 3) Replace list-leading dashes with bullets
    t = t.replace(/^\s*-\s+/gm, "• ");

    // 4) Change spaced hyphens used as commas into commas
    t = t.replace(/\s-\s/g, ", ");

    // 5) Collapse excess blank lines
    t = t.replace(/\n{3,}/g, "\n\n");

    // 6) Convert single newlines to <br>, keep paragraphs
    t = t.split("\n\n").map(p => p.replace(/\n/g, "<br>")).join("</p><p>");
    return `<p>${t}</p>`;
  }

  async function getBrand() {
    const r = await fetch(`${BRAND_URL}?${VERSION}`);
    if (!r.ok) throw new Error(`brand.json ${r.status}`);
    return await r.json();
  }

  /* ------------- transport ------------- */
  async function sendMessage(apiChatPath, message, history) {
    const payload = {
      message: typeof message === "string" ? message : String(message ?? ""),
      history: Array.isArray(history) ? history : []
    };
    if (!payload.message.trim()) return { answer: "" };

    const r = await fetch(apiChatPath || "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!r.ok) {
      const t = await r.text().catch(() => "");
      throw new Error(`${r.status} ${r.statusText}${t ? ` — ${t}` : ""}`);
    }
    return await r.json();
  }

  /* ------------- styles (injected quickly to avoid FOUC) ------------- */
  function injectStyles(brand) {
    const colors = brand?.colors || brand;
    const css = `
:root{
  --mcw-primary: ${colors?.primary || "#ffffff"};
  --mcw-accent:  ${colors?.accent  || "#ff6a00"};
  --mc-font: "Open Sans", system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu,
             "Helvetica Neue", Arial, "Noto Sans", sans-serif;
}
.mc-root{position:fixed;right:24px;bottom:24px;z-index:2147483647;font-family:var(--mc-font)}
.mc-card{width:480px;max-width:calc(100vw - 48px);background:#fff;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.18);overflow:hidden;display:flex;flex-direction:column}
.mc-header{display:flex;align-items:center;justify-content:center;background:var(--mcw-primary);height:64px;min-height:64px;padding:0 16px;border-top-left-radius:16px;border-top-right-radius:16px;position:relative}
.mc-header-logo{height:42px;max-height:42px;width:auto;object-fit:contain;display:block;margin:0 auto}
.mc-close{appearance:none;border:0;background:transparent;color:#000;opacity:.6;cursor:pointer;font-size:18px;line-height:1;position:absolute;right:10px;top:10px}
.mc-body{padding:12px 12px 8px;overflow:auto;max-height:72vh;scroll-behavior:smooth}
.mc-msg{display:inline-block;background:#f6f7f9;border-left:4px solid var(--mcw-accent);padding:10px 12px;border-radius:10px;margin:8px 0;white-space:normal}
.mc-user{align-self:flex-end;background:#eef7ff;border-left-color:#9ecbff}
.mc-inputbar{display:flex;gap:10px;padding:12px;border-top:1px solid #eee;background:#fff}
.mc-input{flex:1;border:1px solid #e0e0e0;border-radius:10px;padding:12px 14px;font-size:14px}
.mc-send{background:var(--mcw-accent);color:#fff;border:0;border-radius:10px;padding:0 16px;min-width:68px;cursor:pointer}
.mc-launcher{position:fixed;right:24px;bottom:24px;display:flex;align-items:center;gap:10px;background:var(--mcw-accent);color:#fff;border-radius:28px;box-shadow:0 10px 30px rgba(0,0,0,.2);padding:10px 16px;font-weight:600;cursor:pointer}
.hidden{display:none}
@media (max-width:520px){ .mc-card{width:calc(100vw - 24px)} }
`;
    const style = ce("style");
    style.textContent = css;
    document.head.appendChild(style);
  }

  function buildHeader(brand){
    const header = ce("div", "mc-header");
    const logo = ce("img", "mc-header-logo");
    logo.alt = (brand?.name || "Macrocomm") + " logo";
    logo.src = brand?.logo_url || "/static/brand/logo.png";
    header.appendChild(logo);
    const closeBtn = ce("button", "mc-close");
    closeBtn.textContent = "✕";
    header.appendChild(closeBtn);   // kept for keyboard a11y; host.css can hide if needed
    return { header, closeBtn };
  }

  function buildUI(brand){
    injectStyles(brand);

    const root     = ce("div", "mc-root hidden");
    const card     = ce("div", "mc-card");
    const body     = ce("div", "mc-body");
    const inputBar = ce("div", "mc-inputbar");
    const input    = ce("input", "mc-input");
    const sendBtn  = ce("button","mc-send");
    input.placeholder = "Type your question…";
    sendBtn.textContent = "Send";

    const { header, closeBtn } = buildHeader(brand);

    inputBar.appendChild(input);
    inputBar.appendChild(sendBtn);
    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(inputBar);
    root.appendChild(card);

    const launcher = ce("button", "mc-launcher");
    const lbl = ce("div", "mc-launcher-label");
    lbl.textContent = brand?.launcherText || "Ask Macro-Bot";
    launcher.appendChild(lbl);

    document.body.appendChild(root);
    document.body.appendChild(launcher);

    return { root, body, input, sendBtn, closeBtn, launcher };
  }

  /* ------------- behaviour ------------- */
  function appendMsg(container, text, isUser=false){
    if (!text) return;
    const m = ce("div", `mc-msg${isUser ? " mc-user" : ""}`);

    // Format bot messages with HTML, keep user messages as plain text
    if (isUser) {
      m.textContent = text;
    } else {
      m.innerHTML = sanitiseAndFormatLLM(text);
    }

    container.appendChild(m);

    // If it's a bot message: show from the start of the new bubble
    if (!isUser) {
      const last = m;
      last.scrollIntoView({ block: 'start', inline: 'nearest' });
      // Gentle nudge so the bubble isn’t glued to the header
      container.scrollTop = Math.max(0, last.offsetTop - 8);
    } else {
      // For user messages: normal bottom scroll
      container.scrollTop = container.scrollHeight;
    }
  }

  function showWelcome(container, welcome){
    const title = welcome?.title || "";
    const sub   = welcome?.subtitle || "";
    const t = [title, sub].filter(Boolean).join("\n");
    if (t) appendMsg(container, t, false);
  }

  /* ------------- init ------------- */
  (async function init(){
    let brand;
    try { brand = await getBrand(); }
    catch {
      brand = {
        colors: { primary: "#ffffff", accent: "#ff6a00" },
        launcherText: "Ask Macro-Bot",
        api: { chat: "/chat" },
        welcome: {
          title: "Hi! 👋 I’m Macro-Bot.",
          subtitle: "Ask me about company policies, procedures, HR or benefits — I’ll keep it smart and simple."
        }
      };
    }

    const apiChat = brand?.api?.chat || "/chat";
    const { root, body, input, sendBtn, closeBtn, launcher } = buildUI(brand);

    // open/close
    launcher.addEventListener("click", () => {
      root.classList.toggle("hidden");
      if (!root.classList.contains("hidden")) input.focus();
    });
    closeBtn.addEventListener("click", () => root.classList.add("hidden"));

    // welcome
    showWelcome(body, brand?.welcome);

    // message history pairs
    const history = [];

    async function doSend(){
      const q = input.value.trim();
      if (!q) return;
      appendMsg(body, q, true);
      input.value = "";
      try {
        const data = await sendMessage(apiChat, q, history);
        const answer =
          data?.answer ?? data?.text ?? data?.output ??
          (typeof data === "string" ? data : JSON.stringify(data));
        appendMsg(body, answer, false);
        history.push([q, answer]);
      } catch (err) {
        appendMsg(body, `Sorry, I hit an error: ${err.message}`, false);
      }
    }
    sendBtn.addEventListener("click", doSend);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); }
    });

    // auto-open on first load (host also calls this, safe to double-call)
    setTimeout(() => launcher.click(), 0);
  })();
})();
