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
  var authToken = "";
  try { authToken = localStorage.getItem("token") || ""; } catch (e) {}

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

      /* ── Quick action chips ── */
      .sb-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        padding: 0 18px 12px;
        animation: fadeIn 0.4s ease;
      }
      .sb-chip {
        padding: 7px 14px;
        border-radius: 20px;
        border: 1px solid rgba(210,213,220,0.5);
        background: #ffffff;
        color: #555b6e;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        font-family: inherit;
        line-height: 1.3;
      }
      .sb-chip:hover {
        background: linear-gradient(135deg, #e8e9ee, #dddfe5);
        border-color: rgba(160,165,180,0.5);
        color: #2d3142;
      }
      .sb-chip:active { transform: scale(0.96); }

      /* ── Nav action buttons (rendered from bot messages) ── */
      .sb-nav-btn {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 6px 14px;
        margin: 4px 4px 4px 0;
        border-radius: 8px;
        border: 1px solid rgba(139,92,246,0.25);
        background: rgba(139,92,246,0.06);
        color: #7c3aed;
        font-size: 12.5px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
        font-family: inherit;
        line-height: 1.3;
      }
      .sb-nav-btn:hover {
        background: rgba(139,92,246,0.14);
        border-color: rgba(139,92,246,0.4);
        transform: translateY(-1px);
      }
      .sb-nav-btn:active { transform: scale(0.97); }
      .sb-nav-btn::before {
        content: '\\2192';
        font-size: 13px;
      }

      /* ── Status badge ── */
      .sb-status {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 10.5px;
        font-weight: 600;
        margin-top: 3px;
        letter-spacing: 0.02em;
      }
      .sb-status-dot {
        width: 7px; height: 7px; border-radius: 50%;
        display: inline-block;
      }
      .sb-status-dot.online { background: #34d399; box-shadow: 0 0 6px rgba(52,211,153,0.5); }
      .sb-status-dot.offline { background: #9ca0b0; }
      .sb-status-text { color: #9ca0b0; }
      .sb-status-name { color: #555b6e; }
      .sb-plan-badge {
        display: inline-block;
        padding: 1px 7px;
        border-radius: 4px;
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-left: 4px;
        vertical-align: middle;
      }
      .sb-plan-badge.free { background: #F3F4F6; color: #6B7280; }
      .sb-plan-badge.basic { background: #DBEAFE; color: #2563EB; }
      .sb-plan-badge.growth { background: #EDE9FE; color: #7C3AED; }
      .sb-plan-badge.pro { background: #FEF3C7; color: #D97706; }
      .sb-plan-badge.enterprise { background: #FEE2E2; color: #DC2626; }

      /* ── Feedback buttons ── */
      .sb-feedback {
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px solid rgba(210,213,220,0.2);
      }
      .sb-feedback-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border-radius: 6px;
        border: 1px solid rgba(210,213,220,0.4);
        background: transparent;
        cursor: pointer;
        transition: all 0.2s;
        color: #9ca0b0;
        font-size: 13px;
      }
      .sb-feedback-btn:hover { background: rgba(210,213,220,0.15); color: #555b6e; }
      .sb-feedback-btn.selected { border-color: rgba(139,92,246,0.4); color: #7c3aed; background: rgba(139,92,246,0.06); }
      .sb-feedback-label { font-size: 10.5px; color: #b0b4c3; margin-right: 4px; }
      .sb-feedback-thanks { font-size: 10.5px; color: #34d399; font-weight: 500; }

      /* ── Follow-up chips (below a message) ── */
      .sb-follow-ups {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px solid rgba(210,213,220,0.15);
      }
      .sb-follow-up {
        padding: 5px 12px;
        border-radius: 16px;
        border: 1px solid rgba(139,92,246,0.2);
        background: rgba(139,92,246,0.04);
        color: #7c3aed;
        font-size: 11.5px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
        font-family: inherit;
        line-height: 1.3;
      }
      .sb-follow-up:hover {
        background: rgba(139,92,246,0.1);
        border-color: rgba(139,92,246,0.35);
      }
      .sb-follow-up:active { transform: scale(0.97); }

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
          <div class="sb-status" id="sbStatus">
            <span class="sb-status-dot offline"></span>
            <span class="sb-status-text">Platform help & account assistant</span>
          </div>
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
  var statusEl = shadow.getElementById("sbStatus");
  var quickActions = [];
  var initDone = false;

  var currentPlan = "";

  function updateStatus(loggedIn, name, role, plan) {
    if (!statusEl) return;
    var dot = statusEl.querySelector(".sb-status-dot");
    var txt = statusEl.querySelector(".sb-status-text");
    if (loggedIn) {
      dot.className = "sb-status-dot online";
      var rLabel = role === "doctor" ? "Doctor" : "Admin";
      var planBadge = plan ? ' <span class="sb-plan-badge ' + (plan || "free") + '">' + (plan || "free").toUpperCase() + '</span>' : '';
      txt.innerHTML = '<span class="sb-status-name">' + (name || "User") + '</span> \u00B7 ' + rLabel + planBadge;
      currentPlan = plan || "free";
    } else {
      dot.className = "sb-status-dot offline";
      txt.textContent = "Platform help & account assistant";
      currentPlan = "";
    }
  }

  function renderChips(actions) {
    // Remove existing chips
    var old = shadow.querySelector(".sb-chips");
    if (old) old.remove();
    if (!actions || !actions.length) return;
    var wrap = document.createElement("div");
    wrap.className = "sb-chips";
    actions.forEach(function (a) {
      var chip = document.createElement("button");
      chip.className = "sb-chip";
      chip.textContent = a.label;
      chip.addEventListener("click", function () {
        input.value = a.msg;
        sendMessage();
        // Remove chips after click
        var c = shadow.querySelector(".sb-chips");
        if (c) c.remove();
      });
      wrap.appendChild(chip);
    });
    messagesEl.after(wrap);
  }

  function fetchInit() {
    try { authToken = localStorage.getItem("token") || ""; } catch (e) {}
    var h = { "Content-Type": "application/json" };
    if (authToken) h["Authorization"] = "Bearer " + authToken;
    fetch(ENDPOINT, {
      method: "POST",
      headers: h,
      body: JSON.stringify({ init: true })
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      updateStatus(data.logged_in, data.user_name, data.role, data.plan);
      quickActions = data.quick_actions || [];
      // Update placeholder based on login state
      if (data.logged_in) {
        input.placeholder = "Ask about your bookings, leads, setup, or get help...";
      }
      if (conversationHistory.length > 0) {
        // Restore conversation history (skip greeting since we have history)
        conversationHistory.forEach(function (msg) {
          if (msg.role === "user") addUserMessage(msg.content);
          else addBotMessage(msg.content);
        });
      } else {
        // Show greeting
        if (data.logged_in && data.greeting) {
          addBotMessage(data.greeting);
        } else if (data.logged_in) {
          addBotMessage("Hi" + (data.user_name ? ", **" + data.user_name + "**" : "") + "! I\u2019m your ChatGenius assistant. I have access to your account data \u2014 ask me about bookings, doctors, patients, leads, stats, or anything about the platform. How can I help?");
        } else {
          addBotMessage("Hi! I\u2019m the ChatGenius Support Assistant. Ask me anything about our platform \u2014 features, pricing, setup, integrations, and more. How can I help you today?");
        }
        renderChips(quickActions);
      }
      initDone = true;
    })
    .catch(function () {
      addBotMessage("Hi! I\u2019m the ChatGenius Support Assistant. Ask me anything about our platform. How can I help you today?");
      initDone = true;
    });
  }

  refreshBtn.addEventListener("click", function () {
    conversationHistory = [];
    sessionStorage.removeItem(SESSION_KEY);
    messagesEl.innerHTML = "";
    initDone = false;
    fetchInit();
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
      if (!initDone && messagesEl.children.length === 0) {
        fetchInit();
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

  // Keyboard shortcut: Ctrl+/ or Cmd+/ to toggle bot
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
      e.preventDefault();
      toggle.click();
    }
    // Escape to close
    if (e.key === "Escape" && isOpen) {
      toggle.click();
    }
  });

  function sendMessage() {
    var text = input.value.trim();
    if (!text) return;

    // Remove chips when sending
    var chips = shadow.querySelector(".sb-chips");
    if (chips) chips.remove();

    addUserMessage(text);
    input.value = "";
    input.style.height = "44px";
    sendBtn.disabled = true;

    var typing = addTypingIndicator();

    var fetchHeaders = { "Content-Type": "application/json" };
    if (authToken) fetchHeaders["Authorization"] = "Bearer " + authToken;

    fetch(ENDPOINT, {
      method: "POST",
      headers: fetchHeaders,
      body: JSON.stringify({ message: text, history: conversationHistory.slice(-20) }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        removeEl(typing);
        if (data.error) {
          addErrorMessage(data.error);
        } else {
          var msgEl = addBotMessage(data.answer, true);
          conversationHistory.push({ role: "assistant", content: data.answer });
          saveSession();
          // Render follow-up suggestions inside the message bubble
          if (data.follow_ups && data.follow_ups.length > 0) {
            renderFollowUps(msgEl, data.follow_ups);
          }
          // Add feedback buttons
          addFeedbackButtons(msgEl);
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

  function addBotMessage(text, returnEl) {
    var d = document.createElement("div");
    d.className = "msg bot";
    d.innerHTML = fmt(text);
    // Attach click handlers to nav buttons
    var navBtns = d.querySelectorAll(".sb-nav-btn");
    navBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var page = btn.getAttribute("data-page");
        if (page) {
          if (typeof window.showPage === "function") {
            window.showPage(page);
          } else {
            window.location.href = "/user-dashboard#" + page;
          }
        }
      });
    });
    messagesEl.appendChild(d);
    scroll();
    return returnEl ? d : undefined;
  }

  function renderFollowUps(msgEl, followUps) {
    var wrap = document.createElement("div");
    wrap.className = "sb-follow-ups";
    followUps.forEach(function (fu) {
      var btn = document.createElement("button");
      btn.className = "sb-follow-up";
      btn.textContent = fu.label;
      btn.addEventListener("click", function () {
        input.value = fu.msg;
        sendMessage();
        // Remove this follow-up row
        wrap.remove();
      });
      wrap.appendChild(btn);
    });
    msgEl.appendChild(wrap);
    scroll();
  }

  function addFeedbackButtons(msgEl) {
    var wrap = document.createElement("div");
    wrap.className = "sb-feedback";
    wrap.innerHTML = '<span class="sb-feedback-label">Helpful?</span>';
    var thumbUp = document.createElement("button");
    thumbUp.className = "sb-feedback-btn";
    thumbUp.innerHTML = "\u{1F44D}";
    thumbUp.title = "Helpful";
    var thumbDown = document.createElement("button");
    thumbDown.className = "sb-feedback-btn";
    thumbDown.innerHTML = "\u{1F44E}";
    thumbDown.title = "Not helpful";

    function handleFeedback(selected, btn) {
      thumbUp.disabled = true;
      thumbDown.disabled = true;
      btn.classList.add("selected");
      var label = wrap.querySelector(".sb-feedback-label");
      if (label) {
        label.className = "sb-feedback-thanks";
        label.textContent = "Thanks for the feedback!";
      }
    }

    thumbUp.addEventListener("click", function () { handleFeedback("up", thumbUp); });
    thumbDown.addEventListener("click", function () { handleFeedback("down", thumbDown); });

    wrap.appendChild(thumbUp);
    wrap.appendChild(thumbDown);
    msgEl.appendChild(wrap);
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
    // Nav links: [[nav:page-name|Button Label]] → clickable button
    s = s.replace(/\[\[nav:([a-z0-9\-]+)\|(.+?)\]\]/g, '<button class="sb-nav-btn" data-page="$1">$2</button>');
    // Markdown links: [text](url) → anchor tag (only for http/https URLs)
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:#7c3aed;text-decoration:underline;font-weight:500">$1</a>');
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
