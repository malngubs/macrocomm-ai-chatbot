// widget.js
// Standalone, brand-styled chat bubble that talks to your /chat endpoint
// and displays source citations. No blue used; Macrocomm orange & charcoal.

(function () {
  const BRAND = {
    // Macrocomm charcoal / near-black for headers
    primary: "#1f2937",          // header background (no blue)
    // Macrocomm orange for CTA + bubble button
    accent:  "#f46a00",
    // Body text (dark)
    text:    "#0f172a",
    // Light background for chat area
    surface: "#fafafa"
  };

  const Z = 2147483647;          // Max z-index so we always float on top
  const POS = { right: 20, bottom: 20 };

  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  };

  function css(strings) {
    const style = el('style');
    style.textContent = String.raw(strings);
    document.head.appendChild(style);
  }

  // ---------- Styles (Macrocomm brand, no blue) ----------
  css`
  .mc-btn{position:fixed;right:${POS.right}px;bottom:${POS.bottom}px;width:56px;height:56px;border-radius:9999px;background:${BRAND.accent};color:#fff;border:none;box-shadow:0 10px 25px rgba(0,0,0,.25);cursor:pointer;font-weight:800;font-family:ui-sans-serif,system-ui;-webkit-font-smoothing:antialiased;z-index:${Z}}
  .mc-panel{position:fixed;right:${POS.right}px;bottom:${POS.bottom+70}px;width:420px;max-height:70vh;background:#fff;border-radius:12px;box-shadow:0 24px 64px rgba(0,0,0,.35);display:none;overflow:hidden;border:1px solid #e5e7eb;font-family:ui-sans-serif,system-ui;-webkit-font-smoothing:antialiased;color:${BRAND.text};z-index:${Z}}
  .mc-panel.open{display:flex;flex-direction:column}
  .mc-head{background:${BRAND.primary};color:#fff;padding:12px 14px;display:flex;justify-content:space-between;align-items:center;font-weight:800}
  .mc-close{cursor:pointer;font-size:18px;opacity:.9}
  .mc-body{padding:10px 12px;overflow:auto;flex:1;background:${BRAND.surface}}
  .mc-msg{background:#fff;border-radius:8px;padding:8px 10px;margin:8px 0;box-shadow:0 1px 2px rgba(0,0,0,.06);white-space:pre-wrap}
  .mc-msg.user{background:#fff7ed;border:1px solid #fed7aa} /* faint orange tint for user */
  .mc-footer{display:flex;gap:8px;padding:10px;border-top:1px solid #eee;background:#fff}
  .mc-input{flex:1;padding:10px;border:1px solid #ddd;border-radius:8px}
  .mc-send{padding:10px 14px;background:${BRAND.accent};color:#fff;border:none;border-radius:8px;cursor:pointer}
  .mc-sources{margin-top:6px;font-size:12px;color:#374151}
  .mc-sources ul{margin:4px 0 0 16px;padding:0}
  .mc-sources a{color:${BRAND.accent};text-decoration:none}
  .mc-sources a:hover{text-decoration:underline}
  `;

  function createPanel(titleText) {
    const panel = el('div', 'mc-panel');
    const head = el('div', 'mc-head');
    head.appendChild(el('div', null, titleText || 'Macrocomm AI Assistant'));
    const close = el('div', 'mc-close', '×'); head.appendChild(close);
    const body = el('div', 'mc-body');
    const footer = el('div', 'mc-footer');
    const input = el('input', 'mc-input'); input.placeholder = 'Type your question...';
    const send = el('button', 'mc-send', 'Send');
    footer.appendChild(input); footer.appendChild(send);
    panel.appendChild(head); panel.appendChild(body); panel.appendChild(footer);
    return { panel, body, input, send, close };
  }

  function appendMessage(bodyEl, text, isUser, citations) {
    const wrap = el('div', 'mc-msg' + (isUser ? ' user' : ''));
    wrap.textContent = text || '';
    if (!isUser && Array.isArray(citations) && citations.length) {
      const d = el('div', 'mc-sources');
      const title = el('div', null, 'Sources:');
      const ul = el('ul');
      citations.slice(0, 6).forEach(src => {
        const li = el('li');
        try {
          const u = new URL(src);
          const a = el('a'); a.href = u.toString(); a.target = '_blank'; a.rel = 'noreferrer noopener';
          a.textContent = (u.hostname.replace(/^www\./, '') + u.pathname) || src;
          li.appendChild(a);
        } catch {
          const name = src.split(/[\\/]/).pop() || src;
          li.textContent = name;
        }
        ul.appendChild(li);
      });
      d.appendChild(title); d.appendChild(ul);
      wrap.appendChild(d);
    }
    bodyEl.appendChild(wrap); bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  async function sendToServer(apiBase, text) {
    const res = await fetch(`${apiBase}/chat`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ user_id: 'web', message: text })
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`HTTP ${res.status}: ${t}`);
    }
    return res.json(); // {answer, citations?}
  }

  function mount(root, opts = {}) {
    const apiBase = opts.apiBase || '';
    // Bubble button
    const btn = el('button', 'mc-btn', 'M-AI');
    btn.title = 'Macrocomm Assistant';
    document.body.appendChild(btn);

    // Panel
    const { panel, body, input, send, close } = createPanel('Macrocomm AI Assistant');
    document.body.appendChild(panel);

    const open = () => { panel.classList.add('open'); input.focus(); };
    const hide = () => panel.classList.remove('open');
    btn.addEventListener('click', open);
    close.addEventListener('click', hide);

    async function doSend() {
      const text = (input.value || '').trim(); if (!text) return;
      appendMessage(body, text, true);
      input.value = '';
      try {
        const out = await sendToServer(apiBase, text);
        appendMessage(body, (out.answer || 'No answer').trim(), false, out.citations);
      } catch (err) {
        console.error('chat error: ', err);
        appendMessage(body, `Sorry, I hit an error: ${err.message}`, false);
      }
    }
    send.addEventListener('click', doSend);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') doSend(); });
  }

  // Expose a small global for the injected content script
  window.MacrocommBubble = { mount };
})();
