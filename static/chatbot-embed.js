(function() {
    'use strict';

    // ── Configuration ──
    var cfg = window.ChatGeniusConfig || {};
    var ADMIN_ID = cfg.adminId || '';
    var SERVER = cfg.server || '';
    var COLOR = cfg.color || '#8b5cf6';
    var TITLE = cfg.title || 'Chat with us';
    var WELCOME = cfg.welcome || 'Hello! How can I help you today?';
    var POSITION = cfg.position || 'right'; // 'right' or 'left'
    var CUSTOMER_ID = cfg.customerId || '';
    var CUSTOMER_API_URL = cfg.customerApiUrl || '';

    if (!ADMIN_ID || !SERVER) {
        console.warn('ChatGenius: adminId and server are required.');
        return;
    }

    // ── Customization settings ──
    var cbCustom = {};

    // ── Session ──
    // Generate a fresh session on every page load so no old messages or flows persist
    var SESSION_KEY = 'cg_session_' + ADMIN_ID;
    var sessionId = 'web_' + ADMIN_ID + '_' + Math.random().toString(36).substr(2, 12);
    // Clear any stale session from localStorage
    try { localStorage.removeItem(SESSION_KEY); } catch(e) {}

    // ── Styles ──
    var css = document.createElement('style');
    css.textContent = [
        // Full reset inside Shadow DOM
        '*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;border:none;outline:none;text-decoration:none;line-height:normal;letter-spacing:normal;font-style:normal;font-weight:400;text-transform:none;vertical-align:baseline;list-style:none;-webkit-font-smoothing:antialiased}',

        // Bubble
        '#cg-bubble{pointer-events:auto;position:fixed;bottom:24px;' + POSITION + ':24px;width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,' + COLOR + ',#6366f1);cursor:pointer;box-shadow:0 4px 24px rgba(139,92,246,0.4),0 0 0 0 rgba(139,92,246,0.3);display:flex;align-items:center;justify-content:center;z-index:999999;transition:all .3s cubic-bezier(.4,0,.2,1);animation:cgPulseRing 2.5s ease infinite}',
        '#cg-bubble:hover{transform:scale(1.1);box-shadow:0 8px 32px rgba(139,92,246,0.5)}',
        '#cg-bubble:active{transform:scale(0.95)}',
        '#cg-bubble.open{animation:none;border-radius:16px;box-shadow:0 4px 24px rgba(139,92,246,0.3)}',
        '#cg-bubble svg{width:24px;height:24px;fill:#fff;transition:transform .3s cubic-bezier(.4,0,.2,1)}',
        '#cg-bubble .cg-close{display:none}',
        '#cg-bubble.open .cg-chat-icon{display:none}',
        '#cg-bubble.open .cg-close{display:block;animation:cgSpin .3s ease}',
        '@keyframes cgPulseRing{0%{box-shadow:0 4px 24px rgba(139,92,246,0.4),0 0 0 0 rgba(139,92,246,0.3)}70%{box-shadow:0 4px 24px rgba(139,92,246,0.4),0 0 0 12px rgba(139,92,246,0)}100%{box-shadow:0 4px 24px rgba(139,92,246,0.4),0 0 0 0 rgba(139,92,246,0)}}',
        '@keyframes cgSpin{from{transform:rotate(-90deg) scale(0.5);opacity:0}to{transform:rotate(0) scale(1);opacity:1}}',

        // Badge
        '#cg-badge{position:absolute;top:-4px;right:-4px;background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;font-size:10px;font-weight:700;width:20px;height:20px;border-radius:50%;display:none;align-items:center;justify-content:center;border:2px solid #fff;animation:cgBounceIn .4s cubic-bezier(.4,0,.2,1)}',
        '@keyframes cgBounceIn{0%{transform:scale(0)}60%{transform:scale(1.2)}100%{transform:scale(1)}}',

        // Window
        '#cg-window{pointer-events:auto;position:fixed;bottom:92px;' + POSITION + ':24px;width:360px;max-width:calc(100vw - 32px);height:480px;max-height:calc(100vh - 120px);background:#0c0c18;border:1px solid rgba(139,92,246,0.15);border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,0.5),0 0 40px rgba(139,92,246,0.08);z-index:999998;display:none;flex-direction:column;overflow:hidden;transform:translateY(16px) scale(0.96);opacity:0;transition:all .35s cubic-bezier(.4,0,.2,1)}',
        '#cg-window.open{display:flex;transform:translateY(0) scale(1);opacity:1}',
        '#cg-window.closing{transform:translateY(16px) scale(0.96);opacity:0}',

        // Header
        '#cg-header{background:linear-gradient(135deg,rgba(139,92,246,0.12),rgba(99,102,241,0.08));padding:16px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0;border-bottom:1px solid rgba(139,92,246,0.1);backdrop-filter:blur(20px)}',
        '#cg-header-avatar{width:36px;height:36px;border-radius:12px;background:linear-gradient(135deg,' + COLOR + ',#6366f1);display:flex;align-items:center;justify-content:center;box-shadow:0 2px 12px rgba(139,92,246,0.3)}',
        '#cg-header-avatar svg{width:18px;height:18px;fill:#fff}',
        '#cg-header-info{flex:1}',
        '#cg-header-title{color:#f1f5f9;font-size:14px;font-weight:600;letter-spacing:-0.01em}',
        '#cg-header-sub{color:rgba(148,163,184,0.8);font-size:11px;display:flex;align-items:center;gap:5px;margin-top:2px}',
        '#cg-reset{background:none;border:none;cursor:pointer;padding:4px;border-radius:6px;transition:background .2s;margin-left:auto}',
        '#cg-reset:hover{background:rgba(255,255,255,0.1)}',
        '#cg-reset svg{width:16px;height:16px;fill:rgba(148,163,184,0.7);transition:fill .2s}',
        '#cg-reset:hover svg{fill:#f1f5f9}',
        '#cg-header-dot{width:6px;height:6px;border-radius:50%;background:#22c55e;box-shadow:0 0 6px rgba(34,197,94,0.5);animation:cgGlow 2s ease infinite}',
        '@keyframes cgGlow{0%,100%{opacity:1}50%{opacity:0.5}}',

        // Messages
        '#cg-messages{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px;scrollbar-width:thin;scrollbar-color:rgba(139,92,246,0.15) transparent;scroll-behavior:smooth}',
        '#cg-messages::-webkit-scrollbar{width:3px}',
        '#cg-messages::-webkit-scrollbar-thumb{background:rgba(139,92,246,0.2);border-radius:3px}',
        '#cg-messages::-webkit-scrollbar-track{background:transparent}',

        // Messages
        '.cg-msg{max-width:84%;padding:10px 14px;font-size:13px;line-height:1.55;word-wrap:break-word;animation:cgSlideUp .35s cubic-bezier(.4,0,.2,1) both}',
        '.cg-msg a{color:' + COLOR + ';text-decoration:none;border-bottom:1px solid rgba(139,92,246,0.3);transition:border-color .2s}',
        '.cg-msg a:hover{border-color:' + COLOR + '}',
        '.cg-msg strong{color:#e2e8f0;font-weight:600}',
        '.cg-msg-bot{align-self:flex-start;background:rgba(255,255,255,0.04);color:#cbd5e1;border-radius:2px 14px 14px 14px;border:1px solid rgba(255,255,255,0.04)}',
        '.cg-msg-user{align-self:flex-end;background:linear-gradient(135deg,' + COLOR + ',#6366f1);color:#fff;border-radius:14px 14px 2px 14px;box-shadow:0 2px 12px rgba(139,92,246,0.25)}',
        '@keyframes cgSlideUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}',
        '@keyframes cgFadeIn{from{opacity:0}to{opacity:1}}',
        '@keyframes cgBounceIn{0%{transform:translateY(30px);opacity:0}60%{transform:translateY(-5px)}100%{transform:translateY(0);opacity:1}}',
        '@keyframes cgScaleIn{0%{transform:scale(0.3);opacity:0}80%{transform:scale(1.05)}100%{transform:scale(1);opacity:1}}',

        // Typing indicator
        '.cg-typing{align-self:flex-start;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.04);padding:12px 18px;border-radius:2px 14px 14px 14px;display:flex;gap:4px;align-items:center;animation:cgSlideUp .3s cubic-bezier(.4,0,.2,1) both}',
        '.cg-typing span{width:6px;height:6px;border-radius:50%;background:' + COLOR + ';animation:cgTypingDot 1.4s ease infinite both}',
        '.cg-typing span:nth-child(2){animation-delay:.15s}',
        '.cg-typing span:nth-child(3){animation-delay:.3s}',
        '@keyframes cgTypingDot{0%,60%,100%{transform:translateY(0);opacity:.3}30%{transform:translateY(-6px);opacity:1}}',

        // Input area
        '#cg-input-area{padding:12px 14px;border-top:1px solid rgba(139,92,246,0.08);display:flex;gap:8px;background:rgba(12,12,24,0.95);flex-shrink:0;backdrop-filter:blur(20px)}',
        '#cg-input{flex:1;background:rgba(255,255,255,0.04);border:1px solid rgba(139,92,246,0.12);border-radius:12px;padding:10px 14px;color:#e2e8f0;font-size:13px;outline:none;resize:none;min-height:20px;max-height:80px;transition:all .2s ease}',
        '#cg-input::placeholder{color:#475569}',
        '#cg-input:focus{border-color:rgba(139,92,246,0.4);background:rgba(255,255,255,0.06);box-shadow:0 0 0 3px rgba(139,92,246,0.08)}',
        '#cg-send{background:linear-gradient(135deg,' + COLOR + ',#6366f1);border:none;border-radius:12px;width:38px;height:38px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .2s cubic-bezier(.4,0,.2,1);flex-shrink:0;box-shadow:0 2px 8px rgba(139,92,246,0.25)}',
        '#cg-send:hover{transform:scale(1.06);box-shadow:0 4px 16px rgba(139,92,246,0.35)}',
        '#cg-send:active{transform:scale(0.95)}',
        '#cg-send:disabled{opacity:.35;cursor:default;transform:none;box-shadow:none}',
        '#cg-send svg{width:16px;height:16px;fill:#fff;transition:transform .15s}',

        // Powered by
        '#cg-powered{text-align:center;padding:6px;font-size:9px;color:#334155;background:#0c0c18;letter-spacing:0.02em}',
        '#cg-powered a{color:#475569;text-decoration:none;transition:color .2s}',
        '#cg-powered a:hover{color:' + COLOR + '}',

        // Option cards
        '.cg-options-wrap{margin:4px 0;max-width:92%;align-self:flex-start;display:flex;flex-direction:column;gap:5px;animation:cgSlideUp .35s cubic-bezier(.4,0,.2,1) both}',
        '.cg-options-label{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;font-weight:600;padding:0 2px;margin-bottom:2px}',
        '.cg-opt-card{position:relative;background:rgba(255,255,255,0.03);border:1px solid rgba(139,92,246,0.1);border-radius:10px;padding:8px 10px;color:#cbd5e1;font-size:11.5px;cursor:pointer;transition:all .2s cubic-bezier(.4,0,.2,1);display:flex;align-items:center;gap:8px;overflow:hidden}',
        '.cg-opt-card::before{content:"";position:absolute;inset:0;background:linear-gradient(135deg,rgba(139,92,246,0.06),transparent);opacity:0;transition:opacity .2s}',
        '.cg-opt-card:hover{border-color:rgba(139,92,246,0.35);transform:translateX(3px);background:rgba(139,92,246,0.05)}',
        '.cg-opt-card:hover::before{opacity:1}',
        '.cg-opt-card:active{transform:scale(0.98)}',
        '.cg-opt-card.selected{border-color:' + COLOR + ';background:rgba(139,92,246,0.1);color:#e2e8f0}',
        '.cg-opt-card.selected .cg-opt-check{opacity:1;transform:scale(1)}',
        '.cg-opt-icon{width:28px;height:28px;min-width:28px;min-height:28px;border-radius:8px;background:linear-gradient(135deg,rgba(139,92,246,0.15),rgba(99,102,241,0.1));display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:12px;line-height:1;color:' + COLOR + ';overflow:hidden}',
        '.cg-opt-text{flex:1;position:relative;z-index:1}',
        '.cg-opt-title{font-weight:500;color:#e2e8f0;font-size:11.5px;line-height:1.3}',
        '.cg-opt-sub{font-size:9.5px;color:#64748b;margin-top:1px}',
        '.cg-opt-check{position:absolute;right:8px;top:50%;transform:translateY(-50%) scale(0.5);width:16px;height:16px;border-radius:50%;background:linear-gradient(135deg,' + COLOR + ',#6366f1);display:flex;align-items:center;justify-content:center;opacity:0;transition:all .25s cubic-bezier(.4,0,.2,1)}',
        '.cg-opt-check svg{width:9px;height:9px;fill:#fff}',
        '.cg-opt-booked{opacity:0.45;cursor:default}',
        '.cg-opt-booked:hover{transform:none;border-color:rgba(239,68,68,0.2);background:rgba(239,68,68,0.04)}',
        '.cg-opt-booked .cg-opt-icon{background:rgba(239,68,68,0.1);color:#f87171}',

        // Confirm buttons
        '.cg-confirm-wrap{display:flex;gap:6px;margin:4px 0;align-self:flex-start;animation:cgSlideUp .35s cubic-bezier(.4,0,.2,1) both}',
        '.cg-confirm-btn{padding:7px 16px;border-radius:10px;border:1px solid rgba(139,92,246,0.15);font-size:11.5px;font-weight:500;cursor:pointer;transition:all .2s cubic-bezier(.4,0,.2,1)}',
        '.cg-confirm-yes{background:linear-gradient(135deg,rgba(34,197,94,0.12),rgba(34,197,94,0.06));color:#4ade80;border-color:rgba(34,197,94,0.2)}',
        '.cg-confirm-yes:hover{background:rgba(34,197,94,0.18);border-color:rgba(34,197,94,0.4);transform:translateY(-1px)}',
        '.cg-confirm-no{background:rgba(255,255,255,0.03);color:#94a3b8;border-color:rgba(255,255,255,0.06)}',
        '.cg-confirm-no:hover{background:rgba(239,68,68,0.08);color:#f87171;border-color:rgba(239,68,68,0.2);transform:translateY(-1px)}',

        // Calendar
        '.cg-calendar{background:rgba(255,255,255,0.03);border:1px solid rgba(139,92,246,0.1);border-radius:14px;padding:10px;max-width:260px;align-self:flex-start;margin:4px 0;animation:cgSlideUp .3s cubic-bezier(.4,0,.2,1) both;box-shadow:0 4px 16px rgba(0,0,0,0.2)}',
        '.cg-cal-nav{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 2px}',
        '.cg-cal-nav button{background:none;border:1px solid rgba(139,92,246,0.12);color:#cbd5e1;cursor:pointer;font-size:12px;padding:4px 8px;border-radius:8px;transition:all .2s}',
        '.cg-cal-nav button:hover{background:rgba(139,92,246,0.1);border-color:rgba(139,92,246,0.3)}',
        '.cg-cal-nav button:disabled{opacity:.2;cursor:default}',
        '.cg-cal-nav span{font-size:12px;font-weight:600;color:#e2e8f0}',
        '.cg-cal-weekdays{display:grid;grid-template-columns:repeat(7,1fr);text-align:center;font-size:10px;color:#475569;margin-bottom:4px;font-weight:500}',
        '.cg-cal-days{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}',
        '.cg-cal-day{background:none;border:none;color:#cbd5e1;font-size:11px;padding:5px;border-radius:8px;cursor:pointer;text-align:center;transition:all .15s ease}',
        '.cg-cal-day:hover:not(.disabled):not(.empty){background:rgba(139,92,246,0.15);color:#f1f5f9;transform:scale(1.1)}',
        '.cg-cal-day.today{border:1px solid rgba(139,92,246,0.4);color:' + COLOR + ';font-weight:600}',
        '.cg-cal-day.disabled{color:#1e293b;cursor:default}',
        '.cg-cal-day.disabled:hover{background:none;transform:none}',
        '.cg-cal-day.selected{background:linear-gradient(135deg,' + COLOR + ',#6366f1);color:#fff;font-weight:600;box-shadow:0 2px 8px rgba(139,92,246,0.3)}',
        '.cg-cal-day.booked{background:rgba(239,68,68,0.15);color:#f87171;font-weight:600}',
        '.cg-cal-day.empty{cursor:default}',

        // Mobile responsive
        '@media(max-width:480px){#cg-window{bottom:0;' + POSITION + ':0;width:100%;max-width:100%;height:100%;max-height:100%;border-radius:0;border:none}#cg-bubble{bottom:16px;' + POSITION + ':16px;width:52px;height:52px}}'
    ].join('\n');
    // ── Load Inter font (must be on main document for Shadow DOM to inherit) ──
    if (!document.querySelector('link[href*="fonts.googleapis.com/css2?family=Inter"]')) {
        var font = document.createElement('link');
        font.rel = 'stylesheet';
        font.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
        document.head.appendChild(font);
    }

    // ── Shadow DOM host ──
    var shadowHost = document.createElement('div');
    shadowHost.id = 'cg-shadow-host';
    shadowHost.style.cssText = 'all:initial !important;position:fixed !important;z-index:999999 !important;bottom:0 !important;' + POSITION + ':0 !important;width:0 !important;height:0 !important;overflow:visible !important;pointer-events:none !important;';
    document.body.appendChild(shadowHost);
    var shadow = shadowHost.attachShadow({ mode: 'open' });

    // Inject font into shadow DOM
    var shadowFont = document.createElement('link');
    shadowFont.rel = 'stylesheet';
    shadowFont.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
    shadow.appendChild(shadowFont);
    shadow.appendChild(css);

    // ── Build widget HTML ──
    var widget = document.createElement('div');
    widget.id = 'cg-widget';
    widget.style.cssText = 'all:initial !important;font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif !important;';
    widget.innerHTML = [
        '<div id="cg-bubble">',
        '  <svg class="cg-chat-icon" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>',
        '  <svg class="cg-close" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>',
        '  <div id="cg-badge">1</div>',
        '</div>',
        '<div id="cg-window">',
        '  <div id="cg-header">',
        '    <div id="cg-header-avatar"><svg viewBox="0 0 24 24" fill="#fff"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg></div>',
        '    <div id="cg-header-info">',
        '      <div id="cg-header-title">' + escapeHtml(TITLE) + '</div>',
        '      <div id="cg-header-sub"><span id="cg-header-dot"></span>Online now</div>',
        '    </div>',
        '    <button id="cg-reset" title="New Chat"><svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg></button>',
        '  </div>',
        '  <div id="cg-messages"></div>',
        '  <div id="cg-input-area">',
        '    <input type="text" id="cg-input" placeholder="Type a message..." autocomplete="off">',
        '    <button id="cg-send"><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>',
        '  </div>',
        '  <div id="cg-powered">Powered by <a href="https://chatgenius.ai" target="_blank">ChatGenius</a></div>',
        '</div>'
    ].join('');
    shadow.appendChild(widget);

    // ── Elements (query inside shadow root) ──
    var bubble = shadow.getElementById('cg-bubble');
    var win = shadow.getElementById('cg-window');
    var messages = shadow.getElementById('cg-messages');
    var input = shadow.getElementById('cg-input');
    var sendBtn = shadow.getElementById('cg-send');
    var badge = shadow.getElementById('cg-badge');
    var resetBtn = shadow.getElementById('cg-reset');
    var isOpen = false;
    var sending = false;

    // ── Fetch customization settings ──
    try {
        fetch(SERVER + '/api/chatbot-customization/public/' + ADMIN_ID)
            .then(function(resp) { if (resp.ok) return resp.json(); return {}; })
            .then(function(data) {
                cbCustom = data || {};
                applyCustomization();
            })
            .catch(function() {});
    } catch(e) {}

    // ── Apply customization styles ──
    function applyCustomization() {
        var css = '';
        if (cbCustom.chat_bg) css += '#cg-messages { background: ' + cbCustom.chat_bg + ' !important; }';
        if (cbCustom.header_bg) css += '#cg-header { background: ' + cbCustom.header_bg + ' !important; }';
        if (cbCustom.header_text) css += '#cg-header, #cg-header * { color: ' + cbCustom.header_text + ' !important; }';
        if (cbCustom.bot_msg_bg) css += '.cg-msg-bot { background: ' + cbCustom.bot_msg_bg + ' !important; }';
        if (cbCustom.bot_msg_text) css += '.cg-msg-bot { color: ' + cbCustom.bot_msg_text + ' !important; }';
        if (cbCustom.user_msg_bg) css += '.cg-msg-user { background: ' + cbCustom.user_msg_bg + ' !important; }';
        if (cbCustom.user_msg_text) css += '.cg-msg-user { color: ' + cbCustom.user_msg_text + ' !important; }';
        if (cbCustom.font_size) css += '.cg-msg { font-size: ' + cbCustom.font_size + 'px !important; }';
        if (cbCustom.input_bg) css += '#cg-input-area, #cg-input { background: ' + cbCustom.input_bg + ' !important; }';
        if (cbCustom.input_text) css += '#cg-input { color: ' + cbCustom.input_text + ' !important; }';
        if (cbCustom.send_btn) css += '#cg-send { background: ' + cbCustom.send_btn + ' !important; }';
        if (cbCustom.appt_marker) css += '.cg-cal-day.booked { background: ' + cbCustom.appt_marker + ' !important; }';
        // Dropdown styles
        if (cbCustom.dropdown_style === 'pill') {
            css += '.cg-opt-card { border-radius: 50px !important; border-left: 4px solid var(--cg-accent, #6366f1) !important; padding: 12px 20px !important; }';
        } else if (cbCustom.dropdown_style === 'glassmorphic') {
            css += '.cg-opt-card { backdrop-filter: blur(12px) !important; -webkit-backdrop-filter: blur(12px) !important; background: rgba(255,255,255,0.08) !important; border: 1px solid rgba(255,255,255,0.15) !important; border-radius: 16px !important; box-shadow: 0 4px 30px rgba(0,0,0,0.1) !important; }';
        }
        // Calendar styles
        if (cbCustom.calendar_style === 'rounded') {
            css += '.cg-cal-day { border-radius: 50% !important; width: 36px !important; height: 36px !important; display: flex !important; align-items: center !important; justify-content: center !important; margin: 2px auto !important; }';
        } else if (cbCustom.calendar_style === 'minimal') {
            css += '.cg-calendar { border: none !important; background: transparent !important; }';
            css += '.cg-cal-day { border: none !important; border-bottom: 2px solid transparent !important; border-radius: 0 !important; }';
            css += '.cg-cal-day:hover { border-bottom-color: var(--cg-accent, #6366f1) !important; }';
            css += '.cg-cal-day.selected { border-bottom-color: var(--cg-accent, #6366f1) !important; font-weight: bold !important; }';
        }
        // Launcher button
        if (cbCustom.launcher_bg) {
            css += '#cg-bubble { background: ' + cbCustom.launcher_bg + ' !important; }';
            css += '#cg-bubble:hover { box-shadow: 0 8px 32px ' + cbCustom.launcher_bg + '80 !important; }';
        }
        if (cbCustom.launcher_icon && cbCustom.launcher_icon !== 'chat') {
            var bubble = shadow.getElementById('cg-bubble');
            if (bubble) {
                var chatIcon = bubble.querySelector('.cg-chat-icon');
                if (chatIcon) {
                    if (cbCustom.launcher_icon === 'robot') {
                        chatIcon.setAttribute('viewBox', '0 0 24 24');
                        chatIcon.innerHTML = '<rect x="3" y="11" width="18" height="10" rx="2" fill="#fff"/><circle cx="12" cy="5" r="2" fill="none" stroke="#fff" stroke-width="2"/><line x1="12" y1="7" x2="12" y2="11" stroke="#fff" stroke-width="2"/><circle cx="8" cy="16" r="1.5" fill="#0c0c18"/><circle cx="16" cy="16" r="1.5" fill="#0c0c18"/><rect x="9" y="19" width="6" height="1" rx="0.5" fill="#0c0c18"/>';
                    } else if (cbCustom.launcher_icon === 'magic') {
                        chatIcon.setAttribute('viewBox', '0 0 24 24');
                        chatIcon.innerHTML = '<path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8L19 13M15 9h.01M17.8 6.2L19 5M11 6.2L9.7 5M11 11.8L9.7 13" stroke="#fff" stroke-width="2" stroke-linecap="round"/><path d="M2 21l9.5-9.5M9.5 13.5L11 12" stroke="#fff" stroke-width="2" stroke-linecap="round"/>';
                    }
                }
            }
        }
        // Hide watermark for agency plan
        if (cbCustom.hide_watermark) {
            var powered = shadow.getElementById('cg-powered');
            if (powered) powered.style.display = 'none';
        }
        // Chatbot title
        if (cbCustom.title) {
            var titleEl = shadow.getElementById('cg-header-title');
            if (titleEl) titleEl.textContent = cbCustom.title;
        }
        // Create/update style element
        var existingStyle = shadow.querySelector('#cg-custom-style');
        if (existingStyle) existingStyle.remove();
        if (css) {
            var styleEl = document.createElement('style');
            styleEl.id = 'cg-custom-style';
            styleEl.textContent = css;
            shadow.appendChild(styleEl);
        }
    }

    // ── Celebration animation (confetti) ──
    function showCelebration() {
        if (!cbCustom.confetti_enabled) return;
        var container = shadow.getElementById('cg-messages') || shadow.getElementById('cg-window');
        if (!container) return;
        var canvas = document.createElement('canvas');
        canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9999;';
        container.style.position = 'relative';
        container.appendChild(canvas);
        var ctx = canvas.getContext('2d');
        canvas.width = container.offsetWidth;
        canvas.height = container.offsetHeight;
        var particles = [];
        var colors = ['#f87171','#fbbf24','#34d399','#60a5fa','#a78bfa','#f472b6','#fb923c'];
        for (var i = 0; i < 80; i++) {
            particles.push({
                x: Math.random() * canvas.width,
                y: -10 - Math.random() * 50,
                w: 6 + Math.random() * 6,
                h: 4 + Math.random() * 4,
                color: colors[Math.floor(Math.random() * colors.length)],
                vy: 1.5 + Math.random() * 3,
                vx: (Math.random() - 0.5) * 2,
                rot: Math.random() * 360,
                rv: (Math.random() - 0.5) * 10
            });
        }
        var frame = 0;
        function animate() {
            if (frame++ > 180) { canvas.remove(); return; }
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            particles.forEach(function(p) {
                p.y += p.vy;
                p.x += p.vx;
                p.rot += p.rv;
                p.vy += 0.03;
                ctx.save();
                ctx.translate(p.x, p.y);
                ctx.rotate(p.rot * Math.PI / 180);
                ctx.fillStyle = p.color;
                ctx.fillRect(-p.w/2, -p.h/2, p.w, p.h);
                ctx.restore();
            });
            requestAnimationFrame(animate);
        }
        animate();
    }

    // ── Get animation name based on customization ──
    function getMsgAnimation() {
        var anim = cbCustom.message_animation || 'slide_up';
        var map = {
            'slide_up': 'cgSlideUp .35s cubic-bezier(.4,0,.2,1) both',
            'fade': 'cgFadeIn .35s ease both',
            'bounce': 'cgBounceIn .5s cubic-bezier(.4,0,.2,1) both',
            'scale': 'cgScaleIn .4s cubic-bezier(.4,0,.2,1) both',
            'typewriter': 'cgFadeIn .8s ease both'
        };
        return map[anim] || map['slide_up'];
    }

    // ── Reset chat (new session) ──
    resetBtn.addEventListener('click', function() {
        sessionId = 'web_' + ADMIN_ID + '_' + Math.random().toString(36).substr(2, 12);
        messages.innerHTML = '';
        addMessage(WELCOME, false);
    });

    // ── Show welcome message with delay for natural feel ──
    setTimeout(function() {
        addMessage(WELCOME, false);
    }, 400);

    // ── Toggle with animation ──
    bubble.addEventListener('click', function() {
        if (!isOpen) {
            isOpen = true;
            bubble.classList.add('open');
            win.style.display = 'flex';
            // Trigger reflow then animate
            void win.offsetWidth;
            win.classList.add('open');
            win.classList.remove('closing');
            badge.style.display = 'none';
            setTimeout(function() { input.focus(); }, 350);
        } else {
            isOpen = false;
            bubble.classList.remove('open');
            win.classList.add('closing');
            win.classList.remove('open');
            setTimeout(function() {
                if (!isOpen) win.style.display = 'none';
            }, 350);
        }
    });

    // ── Send ──
    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });

    function send() {
        var text = input.value.trim();
        if (!text || sending) return;
        input.value = '';
        addMessage(text, true);
        sending = true;
        sendBtn.disabled = true;

        // Typing indicator
        var typing = document.createElement('div');
        typing.className = 'cg-typing';
        typing.innerHTML = '<span></span><span></span><span></span>';
        messages.appendChild(typing);
        messages.scrollTop = messages.scrollHeight;

        fetch(SERVER + '/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: sessionId, admin_id: ADMIN_ID, customer_id: (window.ChatGeniusConfig || {}).customerId || CUSTOMER_ID, customer_api_url: (window.ChatGeniusConfig || {}).customerApiUrl || CUSTOMER_API_URL })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (typing.parentNode) typing.remove();
            addMessage(data.reply || 'Sorry, something went wrong.', false);
            if (data.options) renderOptions(data.options);
            if (data.booking_confirmed) {
                setTimeout(function() { showCelebration(); }, 500);
            }
            if (!isOpen) {
                badge.style.display = 'flex';
            }
        })
        .catch(function() {
            if (typing.parentNode) typing.remove();
            addMessage('Could not connect. Please try again.', false);
        })
        .finally(function() {
            sending = false;
            sendBtn.disabled = false;
        });
    }

    function addMessage(text, isUser) {
        var div = document.createElement('div');
        div.className = 'cg-msg ' + (isUser ? 'cg-msg-user' : 'cg-msg-bot');
        var anim = cbCustom.message_animation || 'slide_up';
        if (!isUser && anim === 'typewriter') {
            // Real typewriter: reveal characters one by one, max 20 seconds
            var html = formatMarkdown(text);
            div.innerHTML = '';
            div.style.opacity = '1';
            messages.appendChild(div);
            var temp = document.createElement('div');
            temp.innerHTML = html;
            var fullText = temp.textContent || temp.innerText || '';
            var len = fullText.length;
            // Speed: at most 20s total, minimum 5ms per char
            var perChar = Math.max(5, Math.min(30, Math.floor(20000 / Math.max(len, 1))));
            var idx = 0;
            var timer = setInterval(function() {
                idx += 1;
                // Show partial text by slicing the full HTML up to idx visible chars
                div.innerHTML = html;
                // Use a span to clip: show idx chars worth of content
                var shown = fullText.substring(0, idx);
                div.textContent = shown;
                // Re-apply markdown once fully revealed
                if (idx >= len) {
                    clearInterval(timer);
                    div.innerHTML = html;
                }
                messages.scrollTop = messages.scrollHeight;
            }, perChar);
        } else {
            div.style.animation = getMsgAnimation();
            div.innerHTML = isUser ? escapeHtml(text) : formatMarkdown(text);
            messages.appendChild(div);
        }
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Render UI options (dropdowns, calendar) ──
    function renderOptions(options) {
        if (!options || !options.type) return;

        if (options.type === 'calendar') {
            renderCalendar(options);
            return;
        }

        var type = options.type;
        var items = options.items || [];
        var isConfirm = type === 'confirm_yesno';
        var isCancel = type === 'cancel_bookings';
        var isDoctor = type === 'doctors';
        var isTime = type === 'timeslots';
        var isCat = type === 'categories';
        var isBookingType = type === 'booking_type';
        var isServices = type === 'services';

        // Confirm: render as two side-by-side buttons
        if (isConfirm) {
            var confirmWrap = document.createElement('div');
            confirmWrap.className = 'cg-confirm-wrap';
            items.forEach(function(item) {
                var btn = document.createElement('button');
                btn.className = 'cg-confirm-btn ' + (item.value === 'yes' ? 'cg-confirm-yes' : 'cg-confirm-no');
                btn.textContent = item.name;
                btn.addEventListener('click', function() {
                    confirmWrap.querySelectorAll('.cg-confirm-btn').forEach(function(b) { b.style.opacity = '0.4'; b.style.pointerEvents = 'none'; });
                    btn.style.opacity = '1';
                    setTimeout(function() { input.value = item.value; send(); }, 150);
                });
                confirmWrap.appendChild(btn);
            });
            messages.appendChild(confirmWrap);
            messages.scrollTop = messages.scrollHeight;
            return;
        }

        // Cards for doctors, timeslots, categories, cancel bookings
        var wrap = document.createElement('div');
        wrap.className = 'cg-options-wrap';

        items.forEach(function(item, idx) {
            var card = document.createElement('div');
            card.className = 'cg-opt-card';
            var isBooked = isTime && item.booked;
            if (isBooked) card.classList.add('cg-opt-booked');

            // Staggered animation
            card.style.animationDelay = (idx * 0.05) + 's';

            // Icon (SVG)
            var icon = document.createElement('div');
            icon.className = 'cg-opt-icon';
            if (isDoctor) icon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 11c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4z"/><path d="M6 21v-2a4 4 0 014-4h4a4 4 0 014 4v2"/></svg>';
            else if (isTime) icon.innerHTML = isBooked ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
            else if (isCat) icon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>';
            else if (isCancel) icon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>';
            else if (isBookingType) icon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>';
            else if (isServices) icon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>';
            else icon.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>';
            card.appendChild(icon);

            // Text
            var textWrap = document.createElement('div');
            textWrap.className = 'cg-opt-text';

            var title = document.createElement('div');
            title.className = 'cg-opt-title';
            if (isDoctor) title.textContent = 'Dr. ' + item.name;
            else title.textContent = item.name;
            textWrap.appendChild(title);

            var sub = document.createElement('div');
            sub.className = 'cg-opt-sub';
            if (isDoctor) {
                var parts = [];
                if (cbCustom.show_specialty && item.specialty) parts.push(item.specialty);
                if (item.availability) parts.push(item.availability);
                if (cbCustom.show_experience && item.years_of_experience) parts.push(item.years_of_experience + ' yrs exp');
                if (cbCustom.show_gender && item.gender) parts.push(item.gender);
                if (cbCustom.show_languages && item.languages) parts.push(item.languages);
                if (cbCustom.show_qualifications && item.qualifications) parts.push(item.qualifications);
                sub.textContent = parts.join(' \u2022 ');
            }
            else if (isBooked) sub.textContent = 'Fully booked \u2014 tap to join waitlist';
            else if (isTime) sub.textContent = 'Available';
            else if (isCancel) sub.textContent = 'Tap to select';
            else if (isBookingType) sub.textContent = item.value === 'service' ? 'Choose from available services' : 'Schedule a regular visit';
            else if (isServices) sub.textContent = 'Tap to select';
            if (sub.textContent) textWrap.appendChild(sub);

            card.appendChild(textWrap);

            // Checkmark
            var check = document.createElement('div');
            check.className = 'cg-opt-check';
            check.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';
            card.appendChild(check);

            card.addEventListener('click', function() {
                wrap.querySelectorAll('.cg-opt-card').forEach(function(c) { c.classList.remove('selected'); });
                card.classList.add('selected');
                setTimeout(function() {
                    input.value = isCancel ? String(item.index) : (isBookingType && item.value ? item.value : item.name);
                    send();
                }, 250);
            });

            wrap.appendChild(card);
        });

        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
    }

    function renderCalendar(options) {
        var offDates = {};
        (options.off_dates || []).forEach(function(d) { offDates[d] = true; });
        var bookedDates = {};
        (options.booked_dates || []).forEach(function(d) { bookedDates[d] = true; });
        var isCancelMode = options.mode === 'cancel';
        var today = new Date(); today.setHours(0,0,0,0);
        var MAX_MONTHS = 4;
        var WEEKDAYS = ['Su','Mo','Tu','We','Th','Fr','Sa'];
        var currentOffset = 0;

        var cal = document.createElement('div');
        cal.className = 'cg-calendar';

        var nav = document.createElement('div');
        nav.className = 'cg-cal-nav';
        var prevBtn = document.createElement('button'); prevBtn.innerHTML = '&#9664;';
        var monthLabel = document.createElement('span');
        var nextBtn = document.createElement('button'); nextBtn.innerHTML = '&#9654;';
        nav.appendChild(prevBtn); nav.appendChild(monthLabel); nav.appendChild(nextBtn);
        cal.appendChild(nav);

        var wkRow = document.createElement('div');
        wkRow.className = 'cg-cal-weekdays';
        WEEKDAYS.forEach(function(w) { var s = document.createElement('span'); s.textContent = w; wkRow.appendChild(s); });
        cal.appendChild(wkRow);

        var daysGrid = document.createElement('div');
        daysGrid.className = 'cg-cal-days';
        cal.appendChild(daysGrid);

        function renderMonth() {
            var d = new Date(today.getFullYear(), today.getMonth() + currentOffset, 1);
            monthLabel.textContent = d.toLocaleString('default', { month: 'long', year: 'numeric' });
            prevBtn.disabled = currentOffset === 0;
            nextBtn.disabled = currentOffset >= MAX_MONTHS - 1;
            daysGrid.innerHTML = '';

            var firstDay = d.getDay();
            for (var i = 0; i < firstDay; i++) {
                var empty = document.createElement('div');
                empty.className = 'cg-cal-day empty';
                daysGrid.appendChild(empty);
            }
            var daysInMonth = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
            for (var day = 1; day <= daysInMonth; day++) {
                var btn2 = document.createElement('button');
                btn2.className = 'cg-cal-day';
                btn2.textContent = day;
                var thisDate = new Date(d.getFullYear(), d.getMonth(), day);
                var iso = thisDate.getFullYear() + '-' + String(thisDate.getMonth()+1).padStart(2,'0') + '-' + String(day).padStart(2,'0');

                if (thisDate < today) { btn2.classList.add('disabled'); }
                else if (!isCancelMode && offDates[iso]) { btn2.classList.add('disabled'); btn2.title = 'Off day'; }
                else {
                    if (isCancelMode && bookedDates[iso]) { btn2.classList.add('booked'); }
                    (function(isoDate, b) {
                        b.addEventListener('click', function() {
                            daysGrid.querySelectorAll('.cg-cal-day.selected').forEach(function(x) { x.classList.remove('selected'); });
                            b.classList.add('selected');
                            setTimeout(function() { input.value = isoDate; send(); }, 200);
                        });
                    })(iso, btn2);
                }
                if (thisDate.getTime() === today.getTime()) btn2.classList.add('today');
                daysGrid.appendChild(btn2);
            }
        }

        prevBtn.addEventListener('click', function() { if (currentOffset > 0) { currentOffset--; renderMonth(); } });
        nextBtn.addEventListener('click', function() { if (currentOffset < MAX_MONTHS - 1) { currentOffset++; renderMonth(); } });
        renderMonth();

        messages.appendChild(cal);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Helpers ──
    function escapeHtml(str) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(str || ''));
        return d.innerHTML;
    }

    function formatMarkdown(text) {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
            .replace(/\n/g, '<br>');
    }

})();
