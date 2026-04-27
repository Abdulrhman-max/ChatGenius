/**
 * ChatGenius Support Bot Widget
 * Luxury silver/white support chatbot for the ChatGenius website.
 * Completely separate from the AI chatbot installed on users' websites.
 */
(function () {
  if (window.__cg_support_bot_loaded) return;
  window.__cg_support_bot_loaded = true;

  var ENDPOINT = "/api/support-chat";
  var SESSION_KEY = "cg_support_bot_session";
  var isOpen = false;
  var conversationHistory = [];

  try {
    var saved = sessionStorage.getItem(SESSION_KEY);
    if (saved) conversationHistory = JSON.parse(saved);
  } catch (e) {}

  function saveSession() {
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(conversationHistory)); } catch (e) {}
  }

  // ── Build widget ──
  var root = document.createElement("div");
  root.id = "cg-support-bot";
  root.attachShadow({ mode: "open" });

  root.shadowRoot.innerHTML = `
    <style>
      :host { all: initial; }
      *, *::before, *::after {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        white-space: normal;
        word-wrap: break-word;
        overflow-wrap: break-word;
        line-height: 1.5;
      }

      /* ── Toggle ── */
      .sb-toggle {
        position: fixed;
        bottom: 28px;
        right: 28px;
        width: 62px;
        height: 62px;
        border-radius: 50%;
        border: 1px solid rgba(210,213,220,0.6);
        background: linear-gradient(145deg, #ffffff, #eef0f5);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        box-shadow: 0 4px 20px rgba(0,0,0,0.06), 0 1px 4px rgba(0,0,0,0.04), inset 0 1px 0 rgba(255,255,255,1);
        cursor: pointer;
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
      }
      .sb-toggle:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(0,0,0,0.1), 0 2px 8px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,1);
      }
      .sb-toggle:active { transform: translateY(0) scale(0.96); }
      .sb-toggle svg { width: 26px; height: 26px; color: #8b8fa3; transition: color 0.25s; }
      .sb-toggle:hover svg { color: #555b6e; }
      .sb-toggle.open .icon-chat { display: none; }
      .sb-toggle.open .icon-close { display: block; }
      .sb-toggle:not(.open) .icon-chat { display: block; }
      .sb-toggle:not(.open) .icon-close { display: none; }

      /* ── Window ── */
      .sb-window {
        position: fixed;
        bottom: 102px;
        right: 28px;
        width: 460px;
        max-width: calc(100vw - 24px);
        height: 640px;
        max-height: calc(100vh - 120px);
        border-radius: 24px;
        border: 1px solid rgba(210,213,220,0.45);
        background: #f8f9fb;
        box-shadow: 0 30px 80px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.04);
        display: none;
        flex-direction: column;
        overflow: hidden;
        z-index: 99998;
        opacity: 0;
        transform: translateY(16px) scale(0.97);
        transition: opacity 0.3s cubic-bezier(0.4,0,0.2,1), transform 0.3s cubic-bezier(0.4,0,0.2,1);
      }
      .sb-window.visible {
        display: flex;
        opacity: 1;
        transform: translateY(0) scale(1);
      }

      /* ── Header ── */
      .sb-header {
        padding: 22px 24px;
        background: linear-gradient(180deg, #ffffff, #f5f6f9);
        border-bottom: 1px solid rgba(210,213,220,0.35);
        display: flex;
        align-items: center;
        gap: 16px;
        flex-shrink: 0;
      }
      .sb-refresh {
        margin-left: auto;
        width: 34px;
        height: 34px;
        min-width: 34px;
        border: 1px solid rgba(210,213,220,0.4);
        border-radius: 10px;
        background: linear-gradient(145deg, #f0f1f5, #e4e6ec);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.25s cubic-bezier(0.4,0,0.2,1);
        flex-shrink: 0;
      }
      .sb-refresh:hover {
        background: linear-gradient(145deg, #e4e6ec, #d8dae2);
        transform: rotate(45deg);
      }
      .sb-refresh:active { transform: rotate(90deg) scale(0.92); }
      .sb-refresh svg { width: 16px; height: 16px; color: #8b8fa3; }
      .sb-header-icon {
        width: 44px;
        height: 44px;
        min-width: 44px;
        border-radius: 14px;
        background: linear-gradient(145deg, #f0f1f5, #e4e6ec);
        border: 1px solid rgba(210,213,220,0.4);
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 2px 6px rgba(0,0,0,0.04), inset 0 1px 0 rgba(255,255,255,0.8);
        flex-shrink: 0;
      }
      .sb-header-icon svg { width: 22px; height: 22px; color: #8b8fa3; }
      .sb-header-text h3 {
        font-size: 15px;
        font-weight: 650;
        color: #1a1d2b;
        letter-spacing: -0.02em;
        line-height: 1.3;
      }
      .sb-header-text p {
        font-size: 12.5px;
        color: #9ca0b0;
        margin-top: 3px;
        letter-spacing: 0.01em;
        line-height: 1.3;
      }

      /* ── Messages ── */
      .sb-messages {
        flex: 1;
        overflow-y: auto;
        overflow-x: hidden;
        padding: 20px 18px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        background: #f2f3f7;
        scrollbar-width: thin;
        scrollbar-color: rgba(180,183,195,0.25) transparent;
      }
      .sb-messages::-webkit-scrollbar { width: 4px; }
      .sb-messages::-webkit-scrollbar-track { background: transparent; }
      .sb-messages::-webkit-scrollbar-thumb { background: rgba(180,183,195,0.3); border-radius: 10px; }

      /* ── Bubble base ── */
      .msg {
        max-width: 92%;
        padding: 14px 18px;
        font-size: 13.5px;
        line-height: 1.7;
        animation: fadeIn 0.35s ease;
        word-wrap: break-word;
        overflow-wrap: break-word;
        word-break: break-word;
        white-space: normal;
        overflow: visible;
      }
      @keyframes fadeIn {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
      }

      /* ── Bot bubble ── */
      .msg.bot {
        align-self: flex-start;
        background: #ffffff;
        border: 1px solid rgba(210,213,220,0.4);
        border-radius: 4px 20px 20px 20px;
        color: #2d3142;
        box-shadow: 0 1px 4px rgba(0,0,0,0.025);
      }
      .msg.bot strong, .msg.bot b { color: #1a1d2b; font-weight: 650; }
      .msg.bot ul, .msg.bot ol {
        padding-left: 20px;
        margin: 8px 0 4px 0;
        list-style-position: outside;
      }
      .msg.bot li {
        margin: 5px 0;
        padding-left: 2px;
        line-height: 1.6;
        display: list-item;
      }
      .msg.bot li::marker { color: #9ca0b0; }
      .msg.bot code {
        background: rgba(210,213,220,0.25);
        padding: 2px 7px;
        border-radius: 5px;
        font-size: 12.5px;
        font-family: 'SF Mono', 'Fira Code', Consolas, monospace;
        color: #555b6e;
      }
      .msg.bot p {
        margin: 0 0 6px 0;
        word-wrap: break-word;
        overflow-wrap: break-word;
      }
      .msg.bot p:last-child { margin-bottom: 0; }

      /* ── User bubble ── */
      .msg.user {
        align-self: flex-end;
        background: linear-gradient(135deg, #c0c4d0, #a8adb8);
        color: #1a1d2b;
        border-radius: 20px 4px 20px 20px;
        border: none;
        box-shadow: 0 2px 10px rgba(160,165,180,0.25);
        font-weight: 450;
        white-space: pre-wrap;
      }

      /* ── Error ── */
      .msg.error {
        align-self: center;
        max-width: 90%;
        background: #fff5f5;
        border: 1px solid rgba(220,160,160,0.3);
        border-radius: 14px;
        color: #a04040;
        font-size: 12.5px;
        text-align: center;
        padding: 10px 16px;
      }

      /* ── Typing ── */
      .sb-typing {
        align-self: flex-start;
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 16px 20px;
        background: #ffffff;
        border: 1px solid rgba(210,213,220,0.4);
        border-radius: 4px 20px 20px 20px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.025);
        animation: fadeIn 0.3s ease;
      }
      .sb-typing span {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #c0c4d0;
        display: block;
        animation: bounce 1.4s infinite ease-in-out;
      }
      .sb-typing span:nth-child(2) { animation-delay: 0.16s; }
      .sb-typing span:nth-child(3) { animation-delay: 0.32s; }
      @keyframes bounce {
        0%, 60%, 100% { transform: translateY(0); opacity: 0.35; }
        30% { transform: translateY(-7px); opacity: 1; }
      }

      /* ── Input ── */
      .sb-input-area {
        padding: 16px 18px;
        border-top: 1px solid rgba(210,213,220,0.35);
        background: #ffffff;
        display: flex;
        gap: 10px;
        align-items: flex-end;
        flex-shrink: 0;
      }
      .sb-input {
        flex: 1;
        min-width: 0;
        border: 1.5px solid rgba(210,213,220,0.5);
        border-radius: 14px;
        padding: 11px 16px;
        font-size: 13.5px;
        color: #2d3142;
        background: #f8f9fb;
        outline: none;
        transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
        resize: none;
        height: 44px;
        max-height: 100px;
        line-height: 1.45;
        font-family: inherit;
        white-space: pre-wrap;
      }
      .sb-input::placeholder { color: #b0b4c3; }
      .sb-input:focus {
        border-color: rgba(160,165,180,0.6);
        background: #ffffff;
        box-shadow: 0 0 0 4px rgba(160,165,180,0.08);
      }
      .sb-send {
        width: 44px;
        height: 44px;
        min-width: 44px;
        border: none;
        border-radius: 14px;
        background: linear-gradient(145deg, #c5c9d6, #a8adb8);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s cubic-bezier(0.4,0,0.2,1);
        flex-shrink: 0;
        box-shadow: 0 2px 8px rgba(160,165,180,0.2);
      }
      .sb-send:hover {
        background: linear-gradient(145deg, #b0b5c2, #969baa);
        transform: translateY(-1px);
        box-shadow: 0 4px 14px rgba(160,165,180,0.3);
      }
      .sb-send:active { transform: translateY(0) scale(0.96); }
      .sb-send:disabled { opacity: 0.35; cursor: not-allowed; transform: none; box-shadow: none; }
      .sb-send svg { width: 18px; height: 18px; color: #ffffff; }

      /* ── Footer ── */
      .sb-powered {
        text-align: center;
        padding: 10px 16px;
        font-size: 10.5px;
        color: #b0b4c3;
        letter-spacing: 0.03em;
        background: #ffffff;
        flex-shrink: 0;
      }

      /* ── Mobile ── */
      @media (max-width: 480px) {
        .sb-window {
          bottom: 0; right: 0; left: 0;
          width: 100%; height: 100%;
          max-width: 100vw; max-height: 100vh;
          border-radius: 0;
        }
        .sb-toggle { bottom: 20px; right: 20px; width: 56px; height: 56px; }
        .sb-toggle svg { width: 24px; height: 24px; }
        .msg { max-width: 95%; }
      }
    </style>

    <button class="sb-toggle" aria-label="Open support chat">
      <svg class="icon-chat" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
        <path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 20.105V4.5A1.5 1.5 0 015.25 3h13.5a1.5 1.5 0 011.5 1.5v10.5a1.5 1.5 0 01-1.5 1.5H7.682l-3.932 3.105z"/>
      </svg>
      <svg class="icon-close" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
      </svg>
    </button>

    <div class="sb-window">
      <div class="sb-header">
        <div class="sb-header-icon">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"/>
          </svg>
        </div>
        <div class="sb-header-text">
          <h3>ChatGenius Support</h3>
          <p>Ask anything about our platform</p>
        </div>
        <button class="sb-refresh" aria-label="New conversation" title="New conversation">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.992 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182"/>
          </svg>
        </button>
      </div>
      <div class="sb-messages"></div>
      <div class="sb-input-area">
        <textarea class="sb-input" placeholder="Ask about features, pricing, setup..." rows="1"></textarea>
        <button class="sb-send" aria-label="Send message">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"/>
          </svg>
        </button>
      </div>
      <div class="sb-powered">Powered by ChatGenius</div>
    </div>
  `;

  document.body.appendChild(root);

  var shadow = root.shadowRoot;
  var toggle = shadow.querySelector(".sb-toggle");
  var chatWindow = shadow.querySelector(".sb-window");
  var messagesEl = shadow.querySelector(".sb-messages");
  var input = shadow.querySelector(".sb-input");
  var sendBtn = shadow.querySelector(".sb-send");
  var refreshBtn = shadow.querySelector(".sb-refresh");

  refreshBtn.addEventListener("click", function () {
    conversationHistory = [];
    sessionStorage.removeItem(SESSION_KEY);
    messagesEl.innerHTML = "";
    addBotMessage("Hi! I\u2019m the ChatGenius Support Assistant. Ask me anything about our platform \u2014 features, pricing, setup, integrations, and more. How can I help you today?");
  });

  toggle.addEventListener("click", function () {
    isOpen = !isOpen;
    toggle.classList.toggle("open", isOpen);
    if (isOpen) {
      chatWindow.style.display = "flex";
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          chatWindow.classList.add("visible");
        });
      });
      input.focus();
      if (messagesEl.children.length === 0) {
        addBotMessage("Hi! I\u2019m the ChatGenius Support Assistant. Ask me anything about our platform \u2014 features, pricing, setup, integrations, and more. How can I help you today?");
        conversationHistory.forEach(function (msg) {
          if (msg.role === "user") addUserMessage(msg.content);
          else addBotMessage(msg.content);
        });
      }
    } else {
      chatWindow.classList.remove("visible");
      setTimeout(function () {
        if (!isOpen) chatWindow.style.display = "none";
      }, 350);
    }
  });

  input.addEventListener("input", function () {
    this.style.height = "44px";
    this.style.height = Math.min(this.scrollHeight, 100) + "px";
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);

  function sendMessage() {
    var text = input.value.trim();
    if (!text) return;

    addUserMessage(text);
    input.value = "";
    input.style.height = "44px";
    sendBtn.disabled = true;

    var typing = addTypingIndicator();

    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: conversationHistory.slice(-20) }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        removeEl(typing);
        if (data.error) {
          addErrorMessage(data.error);
        } else {
          addBotMessage(data.answer);
          conversationHistory.push({ role: "assistant", content: data.answer });
          saveSession();
        }
        sendBtn.disabled = false;
        input.focus();
      })
      .catch(function () {
        removeEl(typing);
        addErrorMessage("Connection error. Please try again.");
        sendBtn.disabled = false;
      });

    conversationHistory.push({ role: "user", content: text });
    saveSession();
  }

  function addUserMessage(text) {
    var d = document.createElement("div");
    d.className = "msg user";
    d.textContent = text;
    messagesEl.appendChild(d);
    scroll();
  }

  function addBotMessage(text) {
    var d = document.createElement("div");
    d.className = "msg bot";
    d.innerHTML = fmt(text);
    messagesEl.appendChild(d);
    scroll();
  }

  function addErrorMessage(text) {
    var d = document.createElement("div");
    d.className = "msg error";
    d.textContent = text;
    messagesEl.appendChild(d);
    scroll();
  }

  function addTypingIndicator() {
    var d = document.createElement("div");
    d.className = "sb-typing";
    d.innerHTML = "<span></span><span></span><span></span>";
    messagesEl.appendChild(d);
    scroll();
    return d;
  }

  function removeEl(el) { if (el && el.parentNode) el.parentNode.removeChild(el); }

  function scroll() {
    requestAnimationFrame(function () { messagesEl.scrollTop = messagesEl.scrollHeight; });
  }

  function inlineFmt(s) {
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/`([^`]+?)`/g, "<code>$1</code>");
    return s;
  }

  function fmt(text) {
    var h = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    var lines = h.split("\n");
    var out = [];
    var inList = false;

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var bm = line.match(/^(\s*)[-\u2022\*]\s+(.+)$/);
      var nm = line.match(/^(\s*)\d+\.\s+(.+)$/);

      if (bm) {
        if (!inList) { out.push("<ul>"); inList = "ul"; }
        out.push("<li>" + inlineFmt(bm[2]) + "</li>");
      } else if (nm) {
        if (!inList) { out.push("<ol>"); inList = "ol"; }
        out.push("<li>" + inlineFmt(nm[2]) + "</li>");
      } else {
        if (inList) { out.push("</" + inList + ">"); inList = false; }
        var trimmed = line.trim();
        if (trimmed === "") {
          out.push("<br>");
        } else {
          out.push("<p>" + inlineFmt(trimmed) + "</p>");
        }
      }
    }
    if (inList) out.push("</" + inList + ">");
    return out.join("");
  }
})();
