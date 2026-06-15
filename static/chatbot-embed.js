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
    var CUSTOMER_API_URL = cfg.customerApiUrl || '';
    // Returning customer recognition: use configured customerId, or fall back to stored patient_id
    var PATIENT_KEY = 'cg_patient_' + ADMIN_ID;
    var CUSTOMER_ID = cfg.customerId || '';
    if (!CUSTOMER_ID) {
        try { CUSTOMER_ID = localStorage.getItem(PATIENT_KEY) || ''; } catch(e) {}
    }

    if (!ADMIN_ID || !SERVER) {
        console.warn('ChatGenius: adminId and server are required.');
        return;
    }

    // ── Customization settings ──
    var cbCustom = {};

    // ── Live chat handoff state ──
    var _handoffActive = false;
    var _handoffStaffName = '';
    var _handoffPollTimer = null;
    var _handoffLastMsgId = 0;
    var _handoffWaitingEl = null;
    var _defaultSubText = 'The team can also help';
    var _ambientPollTimer = null;  // slow poll to detect admin takeover
    var _chatStarted = false;      // true after first message sent
    var _shownStaffMsgIds = {};    // track displayed staff msg IDs to prevent duplicates

    // ── Session ──
    // Reuse session within 30 min so live chat handoff survives page refresh
    var SESSION_KEY = 'cg_session_' + ADMIN_ID;
    var SESSION_TS_KEY = 'cg_session_ts_' + ADMIN_ID;
    var sessionId = '';
    try {
        var _storedSid = localStorage.getItem(SESSION_KEY);
        var _storedTs = parseInt(localStorage.getItem(SESSION_TS_KEY) || '0');
        if (_storedSid && (Date.now() - _storedTs) < 30 * 60 * 1000) {
            sessionId = _storedSid;
        }
    } catch(e) {}
    if (!sessionId) {
        sessionId = 'web_' + ADMIN_ID + '_' + Math.random().toString(36).substr(2, 12);
    }
    try { localStorage.setItem(SESSION_KEY, sessionId); localStorage.setItem(SESSION_TS_KEY, String(Date.now())); } catch(e) {}

    // ── Website Visitor Tracking ──
    // Fires once per page load to record a visit for the admin's website
    (function trackPageVisit() {
        var VID_KEY = 'cg_visitor_id';
        var visitorId = '';
        try { visitorId = localStorage.getItem(VID_KEY) || ''; } catch(e) {}
        if (!visitorId) {
            visitorId = 'v_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 8);
            try { localStorage.setItem(VID_KEY, visitorId); } catch(e) {}
        }
        try {
            var payload = JSON.stringify({
                admin_id: ADMIN_ID,
                visitor_id: visitorId,
                page_url: window.location.href,
                page_path: window.location.pathname,
                referrer: document.referrer || ''
            });
            if (navigator.sendBeacon) {
                navigator.sendBeacon(SERVER + '/api/track-visit', new Blob([payload], {type: 'application/json'}));
            } else {
                var xhr = new XMLHttpRequest();
                xhr.open('POST', SERVER + '/api/track-visit', true);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.send(payload);
            }
        } catch(e) {}
    })();

    // ── Styles ──
    var css = document.createElement('style');
    css.textContent = [
        // Full reset inside Shadow DOM
        '*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;border:none;outline:none;text-decoration:none;line-height:normal;letter-spacing:normal;font-style:normal;font-weight:400;text-transform:none;vertical-align:baseline;list-style:none;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}',

        // Bubble — elevated floating pill
        '#cg-bubble{pointer-events:auto;position:fixed;bottom:28px;' + POSITION + ':28px;width:62px;height:62px;border-radius:50%;background:' + COLOR + ';cursor:pointer;box-shadow:0 8px 32px rgba(0,0,0,0.12),0 2px 8px rgba(0,0,0,0.06);display:flex;align-items:center;justify-content:center;z-index:999999;transition:all .4s cubic-bezier(.16,1,.3,1)}',
        '#cg-bubble:hover{transform:translateY(-3px) scale(1.05);box-shadow:0 12px 40px rgba(0,0,0,0.16),0 4px 12px rgba(0,0,0,0.08)}',
        '#cg-bubble:active{transform:translateY(0) scale(0.96);transition-duration:.15s}',
        '#cg-bubble.open{box-shadow:0 8px 32px rgba(0,0,0,0.12)}',
        '#cg-bubble svg{width:24px;height:24px;fill:#fff;transition:all .4s cubic-bezier(.16,1,.3,1)}',
        '#cg-bubble .cg-close{display:none}',
        '#cg-bubble.open .cg-chat-icon{display:none}',
        '#cg-bubble.open .cg-close{display:block;animation:cgSpin .4s cubic-bezier(.16,1,.3,1)}',
        '@keyframes cgSpin{from{transform:rotate(-90deg) scale(0.5);opacity:0}to{transform:rotate(0) scale(1);opacity:1}}',

        // Badge
        '#cg-badge{position:absolute;top:-3px;right:-3px;background:#ef4444;color:#fff;font-size:10px;font-weight:700;width:20px;height:20px;border-radius:50%;display:none;align-items:center;justify-content:center;border:2.5px solid #fff;animation:cgBounceIn .5s cubic-bezier(.16,1,.3,1)}',
        '@keyframes cgBounceIn{0%{transform:scale(0)}50%{transform:scale(1.25)}100%{transform:scale(1)}}',

        // Window — clean white panel (Intercom Fin style)
        '#cg-window{pointer-events:auto;position:fixed;bottom:102px;' + POSITION + ':28px;width:440px;max-width:calc(100vw - 40px);height:640px;max-height:calc(100vh - 130px);background:#FFFFFF;border:1px solid #E5E7EB;border-radius:16px;box-shadow:0 8px 40px rgba(0,0,0,0.12);z-index:999998;display:none;flex-direction:column;overflow:hidden;transform:translateY(16px) scale(0.95);opacity:0;transition:all .4s cubic-bezier(.16,1,.3,1)}',
        '#cg-window.open{display:flex;transform:translateY(0) scale(1);opacity:1}',
        '#cg-window.closing{transform:translateY(16px) scale(0.95);opacity:0}',

        // Header — clean white (Intercom Fin style)
        '#cg-header{background:#FFFFFF;padding:16px 20px;display:flex;align-items:center;gap:14px;flex-shrink:0;border-bottom:1px solid #E8E8E8}',
        '#cg-header-avatar{width:36px;height:36px;border-radius:50%;background:#1F2937;display:flex;align-items:center;justify-content:center}',
        '#cg-header-avatar svg{width:18px;height:18px;fill:#fff}',
        '#cg-header-info{flex:1}',
        '#cg-header-title{color:#1a1a2e;font-size:15px;font-weight:600;letter-spacing:-0.02em}',
        '#cg-header-sub{color:#6B7280;font-size:12px;display:flex;align-items:center;gap:6px;margin-top:3px;letter-spacing:-0.01em}',
        '#cg-header-actions{display:flex;align-items:center;gap:4px;margin-left:auto}',
        '#cg-reset{background:none;border:none;cursor:pointer;padding:8px;border-radius:10px;transition:all .3s cubic-bezier(.16,1,.3,1)}',
        '#cg-reset:hover{background:rgba(0,0,0,0.04);transform:rotate(45deg)}',
        '#cg-reset svg{width:16px;height:16px;fill:#8b8fa3;transition:fill .3s}',
        '#cg-reset:hover svg{fill:#1a1a2e}',
        '#cg-close-btn{background:none;border:none;cursor:pointer;padding:8px;border-radius:10px;transition:all .3s cubic-bezier(.16,1,.3,1)}',
        '#cg-close-btn:hover{background:rgba(0,0,0,0.04)}',
        '#cg-close-btn svg{width:16px;height:16px;fill:#8b8fa3;transition:fill .3s}',
        '#cg-close-btn:hover svg{fill:#1a1a2e}',
        '#cg-header-dot{width:7px;height:7px;border-radius:50%;background:#34d399;box-shadow:0 0 0 2px rgba(52,211,153,0.2);animation:cgGlow 3s ease infinite}',
        '@keyframes cgGlow{0%,100%{box-shadow:0 0 0 2px rgba(52,211,153,0.2)}50%{box-shadow:0 0 0 4px rgba(52,211,153,0.1)}}',

        // Language selector — modern pill style
        '#cg-lang-wrap{position:relative;display:flex;align-items:center}',
        '#cg-lang-btn{background:#F3F4F6;border:1px solid #E5E7EB;cursor:pointer;padding:5px 10px;border-radius:20px;transition:all .3s cubic-bezier(.16,1,.3,1);display:flex;align-items:center;gap:5px;font-family:inherit;font-size:11px;font-weight:500;color:#6B7280}',
        '#cg-lang-btn:hover{background:#E5E7EB;border-color:#D1D5DB;color:#374151}',
        '#cg-lang-btn svg{width:13px;height:13px;fill:currentColor;flex-shrink:0}',
        '#cg-lang-btn .cg-lang-current{max-width:50px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
        '#cg-lang-menu{display:none;position:absolute;top:calc(100% + 6px);right:0;background:#FFFFFF;border:1px solid #E5E7EB;border-radius:12px;box-shadow:0 12px 32px rgba(0,0,0,0.12),0 2px 6px rgba(0,0,0,0.04);min-width:160px;padding:6px;z-index:10}',
        '#cg-lang-menu.open{display:block;animation:cgSlideUp .25s cubic-bezier(.16,1,.3,1) both}',
        '.cg-lang-opt{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;cursor:pointer;font-size:13px;color:#374151;transition:all .15s;white-space:nowrap;font-weight:450}',
        '.cg-lang-opt:hover{background:#F3F4F6}',
        '.cg-lang-opt.active{background:' + COLOR + '0c;color:' + COLOR + ';font-weight:600}',
        '.cg-lang-opt.active::after{content:"✓";margin-left:auto;font-size:12px;font-weight:700}',
        '.cg-lang-flag{font-size:17px;line-height:1}',

        // Messages area — light gray (Intercom Fin style)
        '#cg-messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px;scrollbar-width:none;scroll-behavior:smooth;background:#F5F5F5}',
        '#cg-messages::-webkit-scrollbar{width:0;display:none}',

        // Message bubbles
        '.cg-msg{max-width:80%;padding:12px 16px;font-size:13.5px;line-height:1.55;word-wrap:break-word;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;letter-spacing:-0.01em}',
        '.cg-msg a{color:' + COLOR + ';text-decoration:none;font-weight:500;transition:all .3s}',
        '.cg-msg a:hover{opacity:0.75}',
        '.cg-msg strong{font-weight:600}',
        '.cg-msg-bot{align-self:flex-start;background:#FFFFFF;color:#2d3142;border-radius:16px;box-shadow:0 1px 3px rgba(0,0,0,0.06)}',
        '.cg-msg-bot strong{color:#1a1a2e}',
        '.cg-msg-user{align-self:flex-end;background:#1F2937;color:#FFFFFF;border-radius:16px}',
        '@keyframes cgSlideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}',
        '@keyframes cgFadeIn{from{opacity:0}to{opacity:1}}',
        '@keyframes cgBounceIn{0%{transform:translateY(30px);opacity:0}60%{transform:translateY(-5px)}100%{transform:translateY(0);opacity:1}}',
        '@keyframes cgScaleIn{0%{transform:scale(0.3);opacity:0}80%{transform:scale(1.05)}100%{transform:scale(1);opacity:1}}',

        // Staff messages (live chat handoff)
        '.cg-msg-staff{align-self:flex-start;background:#EFF6FF;color:#1e3a5f;border-radius:16px;box-shadow:0 1px 3px rgba(0,0,0,0.06)}',
        '.cg-staff-badge{display:flex;align-items:center;gap:5px;margin-bottom:4px;font-size:11px;font-weight:600;color:#3B82F6}',
        '.cg-staff-badge svg{width:12px;height:12px;fill:#3B82F6}',
        // Handoff waiting indicator
        '.cg-handoff-waiting{align-self:flex-start;background:#FFFBEB;color:#92400E;border-radius:16px;padding:12px 16px;font-size:13px;display:flex;align-items:center;gap:8px;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;box-shadow:0 1px 3px rgba(0,0,0,0.06)}',
        '.cg-handoff-waiting .cg-hw-dots{display:flex;gap:3px}',
        '.cg-handoff-waiting .cg-hw-dots span{width:5px;height:5px;border-radius:50%;background:#D97706;animation:cgTypingDot 1.4s ease infinite both}',
        '.cg-handoff-waiting .cg-hw-dots span:nth-child(2){animation-delay:.2s}',
        '.cg-handoff-waiting .cg-hw-dots span:nth-child(3){animation-delay:.4s}',

        // Typing indicator
        '.cg-typing{align-self:flex-start;background:#FFFFFF;padding:14px 20px;border-radius:16px;display:flex;gap:5px;align-items:center;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;box-shadow:0 1px 3px rgba(0,0,0,0.06)}',
        '.cg-typing span{width:7px;height:7px;border-radius:50%;background:#b4b8c8;animation:cgTypingDot 1.4s ease infinite both}',
        '.cg-typing span:nth-child(2){animation-delay:.2s}',
        '.cg-typing span:nth-child(3){animation-delay:.4s}',
        '@keyframes cgTypingDot{0%,60%,100%{transform:translateY(0);opacity:.3}30%{transform:translateY(-6px);opacity:1}}',

        // Input area — rounded container
        '#cg-input-area{padding:10px 12px;background:#FFFFFF;flex-shrink:0;border-top:none}',
        '#cg-input-container{background:#F5F5F5;border-radius:20px;padding:0;display:flex;flex-direction:column;border:1px solid #E5E7EB;transition:border-color .3s}',
        '#cg-input-container.focused{border-color:#D1D5DB}',
        '#cg-input{width:100%;background:transparent;border:none;border-radius:20px 20px 0 0;padding:14px 18px 6px;color:#1a1a2e;font-size:14px;outline:none;resize:none;min-height:40px;max-height:84px;overflow-y:auto;line-height:1.4;letter-spacing:-0.01em}',
        '#cg-input::placeholder{color:#9CA3AF}',
        '#cg-input:focus{box-shadow:none}',
        '#cg-input-bottom{display:flex;align-items:center;padding:4px 10px 10px 14px}',
        '.cg-input-actions{display:flex;gap:4px;flex:1;position:relative}',
        '.cg-input-action{background:none;border:none;cursor:pointer;padding:6px;border-radius:8px;font-size:16px;line-height:1;color:#9CA3AF;transition:all .2s}',
        '.cg-input-action:hover{color:#4B5563;background:rgba(0,0,0,0.04)}',
        '#cg-send{background:#E5E7EB;border:none;border-radius:50%;width:36px;height:36px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .3s cubic-bezier(.16,1,.3,1);flex-shrink:0;margin-left:auto}',
        '#cg-send:hover{background:#D1D5DB;transform:scale(1.05)}',
        '#cg-send:active{transform:scale(0.95);transition-duration:.15s}',
        '#cg-send:disabled{opacity:.3;cursor:default;transform:none}',
        '#cg-send svg{width:16px;height:16px;fill:#374151}',

        // Mic button (inline in action bar)
        '#cg-mic{display:none}',
        '#cg-mic.recording{background:rgba(239,68,68,0.1);color:#ef4444;animation:cgMicPulse 1.5s ease infinite}',
        '#cg-mic.recording svg{fill:#ef4444}',
        '@keyframes cgMicPulse{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,0.15)}50%{box-shadow:0 0 0 6px rgba(239,68,68,0)}}',
        '#cg-mic-status{display:none;font-size:10px;color:#6b7280;text-align:center;padding:2px 14px;background:transparent;flex-shrink:0}',

        // Voice inline input (replaces input area)
        '#cg-voice-inline{display:none;flex-direction:column;align-items:center;gap:6px;padding:12px 16px;background:#ffffff;border-top:1px solid #e5e7eb;animation:cgFadeIn .25s ease}',
        '#cg-voice-inline.active{display:flex}',
        '#cg-voice-inline .cg-vi-stop{width:48px;height:48px;border-radius:12px;border:none;background:transparent;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .2s}',
        '#cg-voice-inline .cg-vi-stop:hover{background:rgba(0,0,0,0.05)}',
        '#cg-voice-inline .cg-vi-stop .cg-vi-square{width:18px;height:18px;border-radius:4px;background:#374151;animation:cgViSpin 3s linear infinite}',
        '@keyframes cgViSpin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}',
        '#cg-voice-inline .cg-vi-timer{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;color:rgba(55,65,81,0.7);transition:opacity .3s}',
        '#cg-voice-inline .cg-vi-bars{height:16px;width:220px;display:flex;align-items:center;justify-content:center;gap:1.5px}',
        '#cg-voice-inline .cg-vi-bar{width:2px;border-radius:2px;background:rgba(55,65,81,0.15);min-height:3px;transition:height 80ms ease}',
        '#cg-voice-inline .cg-vi-bar.active{background:rgba(55,65,81,0.45);animation:cgViPulse 1.2s ease infinite}',
        '@keyframes cgViPulse{0%,100%{opacity:.5}50%{opacity:1}}',
        '#cg-voice-inline .cg-vi-hint{font-size:11px;color:rgba(55,65,81,0.7)}',
        '@keyframes cgFadeIn{from{opacity:0}to{opacity:1}}',

        // Emoji picker
        '#cg-emoji-picker{display:none;position:absolute;bottom:44px;left:0;width:260px;max-height:200px;overflow-y:auto;background:#fff;border:1px solid #e5e7eb;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.12);padding:8px;z-index:10;animation:cgFadeIn .15s ease}',
        '#cg-emoji-picker.open{display:block}',
        '.cg-emoji-grid{display:grid;grid-template-columns:repeat(8,1fr);gap:2px}',
        '.cg-emoji-item{background:none;border:none;cursor:pointer;font-size:18px;padding:4px;border-radius:6px;transition:background .15s;text-align:center;line-height:1.2}',
        '.cg-emoji-item:hover{background:rgba(0,0,0,0.06)}',

        // Image in chat
        '.cg-msg-img{max-width:200px;max-height:200px;border-radius:10px;margin-bottom:4px;display:block;object-fit:cover}',

        // Image preview strip inside input container
        '#cg-img-preview{display:none;padding:8px 12px 0;position:relative}',
        '#cg-img-preview.active{display:flex;align-items:center;gap:8px}',
        '#cg-img-preview img{width:48px;height:48px;object-fit:cover;border-radius:8px;border:1px solid #e5e7eb}',
        '#cg-img-preview .cg-img-name{flex:1;font-size:11px;color:#6B7280;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
        '#cg-img-preview .cg-img-remove{background:none;border:none;cursor:pointer;color:#9CA3AF;padding:4px;border-radius:6px;transition:all .2s;display:flex;align-items:center;justify-content:center}',
        '#cg-img-preview .cg-img-remove:hover{color:#ef4444;background:rgba(239,68,68,0.08)}',

        // Powered by (Intercom privacy text style)
        '#cg-powered{text-align:center;padding:6px 16px;font-size:10px;color:#9CA3AF;background:#FFFFFF;letter-spacing:0.01em;border-top:none}',
        '#cg-powered a{color:#6B7280;text-decoration:underline;font-weight:400;transition:color .3s}',
        '#cg-powered a:hover{color:#1F2937}',

        // Option cards — glass morphism
        '.cg-options-wrap{margin:6px 0;max-width:92%;align-self:flex-start;display:flex;flex-direction:column;gap:8px;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both}',
        '.cg-options-label{font-size:10px;color:#8b8fa3;text-transform:uppercase;letter-spacing:0.06em;font-weight:600;padding:0 4px;margin-bottom:2px}',
        '.cg-opt-card{position:relative;background:rgba(255,255,255,0.8);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.05);border-radius:14px;padding:12px 14px;color:#2d3142;font-size:12.5px;cursor:pointer;transition:all .3s cubic-bezier(.16,1,.3,1);display:flex;align-items:center;gap:12px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,0.03)}',
        '.cg-opt-card::before{content:"";position:absolute;inset:0;background:transparent;opacity:0;transition:opacity .3s}',
        '.cg-opt-card:hover{border-color:' + COLOR + '30;transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,0.06)}',
        '.cg-opt-card:hover::before{opacity:0}',
        '.cg-opt-card:active{transform:translateY(0) scale(0.98);transition-duration:.15s}',
        '.cg-opt-card.selected{border-color:' + COLOR + '50;background:' + COLOR + '06;box-shadow:0 4px 16px ' + COLOR + '10}',
        '.cg-opt-card.selected .cg-opt-check{opacity:1;transform:scale(1)}',
        '.cg-opt-icon{width:34px;height:34px;min-width:34px;min-height:34px;border-radius:11px;background:' + COLOR + '0c;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:14px;line-height:1;color:' + COLOR + ';overflow:hidden}',
        '.cg-opt-text{flex:1;position:relative;z-index:1}',
        '.cg-opt-title{font-weight:500;color:#1a1a2e;font-size:12.5px;line-height:1.35;letter-spacing:-0.01em}',
        '.cg-opt-sub{font-size:10.5px;color:#8b8fa3;margin-top:2px}',
        '.cg-opt-check{position:absolute;right:12px;top:50%;transform:translateY(-50%) scale(0.5);width:20px;height:20px;border-radius:50%;background:' + COLOR + ';display:flex;align-items:center;justify-content:center;opacity:0;transition:all .3s cubic-bezier(.16,1,.3,1)}',
        '.cg-opt-check svg{width:10px;height:10px;fill:#fff}',
        '.cg-opt-booked{opacity:0.5;cursor:default}',
        '.cg-opt-booked:hover{transform:none;border-color:rgba(239,68,68,0.15);background:rgba(254,242,242,0.6)}',
        '.cg-opt-booked .cg-opt-icon{background:rgba(254,242,242,0.8);color:#ef4444}',

        // Confirm buttons
        '.cg-confirm-wrap{display:flex;gap:8px;margin:6px 0;align-self:flex-start;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both}',
        '.cg-confirm-btn{padding:9px 20px;border-radius:22px;border:1px solid rgba(0,0,0,0.06);font-size:12px;font-weight:500;cursor:pointer;transition:all .3s cubic-bezier(.16,1,.3,1);letter-spacing:-0.01em}',
        '.cg-confirm-yes{background:rgba(240,253,244,0.8);color:#16a34a;border-color:rgba(34,197,94,0.2)}',
        '.cg-confirm-yes:hover{background:#dcfce7;transform:translateY(-2px);box-shadow:0 4px 12px rgba(34,197,94,0.1)}',
        '.cg-confirm-no{background:rgba(255,255,255,0.8);color:#6b7280;border-color:rgba(0,0,0,0.06)}',
        '.cg-confirm-no:hover{background:rgba(254,242,242,0.8);color:#ef4444;border-color:rgba(239,68,68,0.15);transform:translateY(-2px)}',

        // Calendar — glass card
        '.cg-calendar{background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.05);border-radius:18px;padding:14px;max-width:270px;align-self:flex-start;margin:6px 0;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;box-shadow:0 4px 16px rgba(0,0,0,0.04)}',
        '.cg-cal-nav{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding:0 2px}',
        '.cg-cal-nav button{background:rgba(0,0,0,0.03);border:none;color:#374151;cursor:pointer;font-size:12px;padding:5px 10px;border-radius:10px;transition:all .3s cubic-bezier(.16,1,.3,1)}',
        '.cg-cal-nav button:hover{background:rgba(0,0,0,0.06);transform:translateY(-1px)}',
        '.cg-cal-nav button:disabled{opacity:.25;cursor:default;transform:none}',
        '.cg-cal-nav span{font-size:13px;font-weight:600;color:#1a1a2e;letter-spacing:-0.02em}',
        '.cg-cal-weekdays{display:grid;grid-template-columns:repeat(7,1fr);text-align:center;font-size:10px;color:#8b8fa3;margin-bottom:6px;font-weight:600;letter-spacing:0.02em}',
        '.cg-cal-days{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}',
        '.cg-cal-day{background:none;border:none;color:#374151;font-size:11.5px;padding:7px;border-radius:10px;cursor:pointer;text-align:center;transition:all .25s cubic-bezier(.16,1,.3,1);font-weight:450}',
        '.cg-cal-day:hover:not(.disabled):not(.empty){background:' + COLOR + '0c;color:' + COLOR + ';transform:scale(1.15)}',
        '.cg-cal-day.today{background:' + COLOR + '08;color:' + COLOR + ';font-weight:600}',
        '.cg-cal-day.disabled{color:#d1d5db;cursor:default}',
        '.cg-cal-day.disabled:hover{background:none;transform:none}',
        '.cg-cal-day.selected{background:' + COLOR + ';color:#fff;font-weight:600;box-shadow:0 3px 10px ' + COLOR + '30}',
        '.cg-cal-day.booked{background:rgba(254,242,242,0.8);color:#ef4444;font-weight:600}',
        '.cg-cal-day.empty{cursor:default}',

        // Quick reply buttons — floating pills
        '.cg-quick-replies{display:flex;flex-wrap:wrap;gap:7px;max-width:92%;align-self:flex-start;margin:6px 0;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both}',
        '.cg-quick-btn{padding:8px 16px;border-radius:22px;border:1px solid rgba(0,0,0,0.06);background:rgba(255,255,255,0.85);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);color:#374151;font-size:12px;font-weight:500;cursor:pointer;transition:all .3s cubic-bezier(.16,1,.3,1);white-space:nowrap;box-shadow:0 2px 6px rgba(0,0,0,0.03);letter-spacing:-0.01em}',
        '.cg-quick-btn:hover{border-color:' + COLOR + '30;color:' + COLOR + ';transform:translateY(-2px);box-shadow:0 4px 14px rgba(0,0,0,0.06)}',
        '.cg-quick-btn:active{transform:translateY(0) scale(0.96);transition-duration:.15s}',
        '.cg-quick-btn.selected{background:' + COLOR + ';color:#fff;border-color:' + COLOR + ';box-shadow:0 4px 14px ' + COLOR + '25}',

        // Product cards — elevated glass
        '.cg-product-cards{display:flex;flex-direction:column;gap:10px;max-width:92%;align-self:flex-start;margin:6px 0;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both}',
        '.cg-product-card{background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.05);border-radius:16px;overflow:hidden;cursor:pointer;transition:all .35s cubic-bezier(.16,1,.3,1);box-shadow:0 2px 8px rgba(0,0,0,0.04)}',
        '.cg-product-card:hover{transform:translateY(-3px);box-shadow:0 8px 28px rgba(0,0,0,0.08);border-color:rgba(0,0,0,0.08)}',
        '.cg-product-img{width:100%;height:130px;object-fit:cover;background:rgba(248,250,252,0.8);display:flex;align-items:center;justify-content:center;overflow:hidden}',
        '.cg-product-img img{width:100%;height:100%;object-fit:cover;transition:transform .5s cubic-bezier(.16,1,.3,1)}',
        '.cg-product-card:hover .cg-product-img img{transform:scale(1.04)}',
        '.cg-product-img svg{width:32px;height:32px;fill:#d1d5db}',
        '.cg-product-body{padding:14px}',
        '.cg-product-name{color:#1a1a2e;font-size:13.5px;font-weight:600;line-height:1.35;margin-bottom:5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;letter-spacing:-0.02em}',
        '.cg-product-price-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}',
        '.cg-product-price{color:#1a1a2e;font-size:16px;font-weight:700;letter-spacing:-0.02em}',
        '.cg-product-compare{color:#9ca3af;font-size:11.5px;text-decoration:line-through}',
        '.cg-product-badge{font-size:9px;padding:3px 8px;border-radius:8px;font-weight:600;background:rgba(240,253,244,0.8);color:#16a34a;letter-spacing:0.02em}',
        '.cg-product-rating{display:flex;align-items:center;gap:5px;margin-bottom:10px}',
        '.cg-product-stars{color:#f59e0b;font-size:11px;letter-spacing:1px}',
        '.cg-product-reviews{color:#9ca3af;font-size:10.5px}',
        '.cg-product-stock{font-size:10.5px;color:#f59e0b;margin-bottom:8px}',
        '.cg-product-actions{display:flex;gap:8px}',
        '.cg-product-btn{flex:1;padding:9px 0;border-radius:12px;font-size:11.5px;font-weight:600;cursor:pointer;text-align:center;transition:all .3s cubic-bezier(.16,1,.3,1);letter-spacing:-0.01em}',
        '.cg-product-btn-primary{background:' + COLOR + ';color:#fff;border:none;box-shadow:0 3px 10px ' + COLOR + '20}',
        '.cg-product-btn-primary:hover{transform:translateY(-2px);box-shadow:0 6px 18px ' + COLOR + '28}',
        '.cg-product-btn-secondary{background:rgba(0,0,0,0.03);color:#374151;border:1px solid rgba(0,0,0,0.06)}',
        '.cg-product-btn-secondary:hover{background:rgba(0,0,0,0.06);transform:translateY(-1px)}',

        // Property cards
        '.cg-property-cards{display:flex;flex-direction:column;gap:10px;max-width:92%;align-self:flex-start;margin:6px 0;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both}',
        '.cg-property-card{background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.05);border-radius:16px;overflow:hidden;cursor:pointer;transition:all .35s cubic-bezier(.16,1,.3,1);box-shadow:0 2px 8px rgba(0,0,0,0.04)}',
        '.cg-property-card:hover{transform:translateY(-3px);box-shadow:0 8px 28px rgba(0,0,0,0.08)}',
        '.cg-property-img{width:100%;height:140px;object-fit:cover;background:rgba(248,250,252,0.8);display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden}',
        '.cg-property-img img{width:100%;height:100%;object-fit:cover;transition:transform .5s cubic-bezier(.16,1,.3,1)}',
        '.cg-property-card:hover .cg-property-img img{transform:scale(1.04)}',
        '.cg-property-img svg{width:32px;height:32px;fill:#d1d5db}',
        '.cg-property-status{position:absolute;top:10px;left:10px;padding:4px 10px;border-radius:8px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}',
        '.cg-property-status.active{background:rgba(22,163,74,0.9);color:#fff}',
        '.cg-property-status.pending{background:rgba(245,158,11,0.9);color:#fff}',
        '.cg-property-body{padding:14px}',
        '.cg-property-price{color:#1a1a2e;font-size:17px;font-weight:700;margin-bottom:3px;letter-spacing:-0.02em}',
        '.cg-property-addr{color:#4b5563;font-size:12px;font-weight:500;margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
        '.cg-property-details{display:flex;gap:12px;margin-bottom:8px}',
        '.cg-property-detail{display:flex;align-items:center;gap:4px;color:#6b7280;font-size:11px}',
        '.cg-property-detail svg{width:12px;height:12px;fill:#9ca3af}',
        '.cg-property-detail strong{color:#1a1a2e;font-weight:600}',
        '.cg-property-features{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px}',
        '.cg-property-feat{padding:3px 8px;border-radius:8px;font-size:9.5px;background:' + COLOR + '08;color:' + COLOR + ';font-weight:500}',
        '.cg-property-scores{display:flex;gap:10px;margin-bottom:10px}',
        '.cg-property-score{font-size:10px;color:#9ca3af}',
        '.cg-property-score strong{color:#1a1a2e}',
        '.cg-property-actions{display:flex;gap:8px}',
        '.cg-property-btn{flex:1;padding:9px 0;border-radius:12px;font-size:11.5px;font-weight:600;cursor:pointer;text-align:center;transition:all .3s cubic-bezier(.16,1,.3,1)}',
        '.cg-property-btn-primary{background:' + COLOR + ';color:#fff;border:none;box-shadow:0 3px 10px ' + COLOR + '20}',
        '.cg-property-btn-primary:hover{transform:translateY(-2px);box-shadow:0 6px 18px ' + COLOR + '28}',
        '.cg-property-btn-secondary{background:rgba(0,0,0,0.03);color:#374151;border:1px solid rgba(0,0,0,0.06)}',
        '.cg-property-btn-secondary:hover{background:rgba(0,0,0,0.06);transform:translateY(-1px)}',

        // Cart summary
        '.cg-cart-summary{background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.05);border-radius:16px;padding:16px;max-width:92%;align-self:flex-start;margin:6px 0;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;box-shadow:0 2px 8px rgba(0,0,0,0.04)}',
        '.cg-cart-title{color:#1a1a2e;font-size:13.5px;font-weight:600;margin-bottom:10px;display:flex;align-items:center;gap:8px;letter-spacing:-0.02em}',
        '.cg-cart-item{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(0,0,0,0.04)}',
        '.cg-cart-item:last-child{border-bottom:none}',
        '.cg-cart-item-name{color:#4b5563;font-size:12px;flex:1}',
        '.cg-cart-item-qty{color:#9ca3af;font-size:10.5px;margin:0 8px}',
        '.cg-cart-item-price{color:#1a1a2e;font-size:12.5px;font-weight:600}',
        '.cg-cart-total{display:flex;justify-content:space-between;padding-top:10px;border-top:1px solid rgba(0,0,0,0.06);margin-top:4px}',
        '.cg-cart-total-label{color:#1a1a2e;font-size:13.5px;font-weight:600}',
        '.cg-cart-total-price{color:#1a1a2e;font-size:16px;font-weight:700;letter-spacing:-0.02em}',
        '.cg-cart-actions{display:flex;gap:8px;margin-top:10px}',

        // Order tracking
        '.cg-order-track{background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.05);border-radius:16px;padding:16px;max-width:92%;align-self:flex-start;margin:6px 0;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;box-shadow:0 2px 8px rgba(0,0,0,0.04)}',
        '.cg-order-header{display:flex;justify-content:space-between;margin-bottom:12px}',
        '.cg-order-number{color:#1a1a2e;font-size:12.5px;font-weight:600;letter-spacing:-0.01em}',
        '.cg-order-status-badge{padding:4px 10px;border-radius:8px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.02em}',
        '.cg-order-status-badge.shipped{background:rgba(243,232,255,0.8);color:#7c3aed}',
        '.cg-order-status-badge.delivered{background:rgba(240,253,244,0.8);color:#16a34a}',
        '.cg-order-status-badge.processing{background:rgba(255,251,235,0.8);color:#d97706}',
        '.cg-order-status-badge.confirmed{background:rgba(219,234,254,0.8);color:#2563eb}',
        '.cg-order-status-badge.pending{background:rgba(254,249,195,0.8);color:#a16207}',
        '.cg-order-status-badge.cancelled{background:rgba(254,226,226,0.8);color:#dc2626}',
        '.cg-order-status-badge.refunded{background:rgba(254,226,226,0.8);color:#dc2626}',
        '.cg-order-steps{display:flex;justify-content:space-between;position:relative;margin:14px 0}',
        '.cg-order-step{display:flex;flex-direction:column;align-items:center;gap:5px;z-index:1}',
        '.cg-order-dot{width:18px;height:18px;border-radius:50%;border:2px solid #e5e7eb;background:#fff;transition:all .4s cubic-bezier(.16,1,.3,1)}',
        '.cg-order-dot.done{background:' + COLOR + ';border-color:' + COLOR + ';box-shadow:0 2px 6px ' + COLOR + '30}',
        '.cg-order-dot.current{border-color:' + COLOR + ';box-shadow:0 0 0 4px ' + COLOR + '12}',
        '.cg-order-step-label{font-size:9px;color:#8b8fa3;text-align:center;font-weight:500}',
        '.cg-order-line{position:absolute;top:9px;left:20px;right:20px;height:2px;background:#e5e7eb;border-radius:2px}',
        '.cg-order-line-fill{height:100%;background:' + COLOR + ';border-radius:2px;transition:width .6s cubic-bezier(.16,1,.3,1)}',

        // Agent card
        '.cg-agent-card{background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(0,0,0,0.05);border-radius:16px;padding:16px;max-width:92%;align-self:flex-start;margin:6px 0;display:flex;gap:14px;align-items:center;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;box-shadow:0 2px 8px rgba(0,0,0,0.04)}',
        '.cg-agent-photo{width:50px;height:50px;border-radius:14px;background:rgba(0,0,0,0.03);display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0}',
        '.cg-agent-photo img{width:100%;height:100%;object-fit:cover}',
        '.cg-agent-photo svg{width:20px;height:20px;fill:#9ca3af}',
        '.cg-agent-info{flex:1}',
        '.cg-agent-name{color:#1a1a2e;font-size:13.5px;font-weight:600;letter-spacing:-0.02em}',
        '.cg-agent-title{color:#8b8fa3;font-size:10.5px;margin-top:2px}',
        '.cg-agent-spec{color:#6b7280;font-size:10.5px;margin-top:2px}',
        '.cg-agent-contact{display:flex;gap:6px;margin-top:8px}',
        '.cg-agent-contact-btn{padding:5px 12px;border-radius:8px;font-size:10.5px;font-weight:500;cursor:pointer;transition:all .3s cubic-bezier(.16,1,.3,1)}',

        // Cart recovery / urgency timer
        '.cg-recovery-banner{background:linear-gradient(135deg,#ef4444,#dc2626);border-radius:16px;padding:16px;max-width:92%;align-self:flex-start;margin:6px 0;animation:cgSlideUp .4s cubic-bezier(.16,1,.3,1) both;box-shadow:0 4px 16px rgba(239,68,68,0.2)}',
        '.cg-recovery-text{color:#fff;font-size:12.5px;line-height:1.5;margin-bottom:10px;letter-spacing:-0.01em}',
        '.cg-recovery-discount{background:rgba(255,255,255,0.15);border:1px dashed rgba(255,255,255,0.4);border-radius:12px;padding:10px 12px;text-align:center;margin:10px 0;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}',
        '.cg-recovery-code{color:#fbbf24;font-size:16px;font-weight:700;letter-spacing:1.5px}',
        '.cg-recovery-desc{color:rgba(255,255,255,0.85);font-size:10.5px;margin-top:3px}',
        '.cg-urgency-timer{display:flex;align-items:center;justify-content:center;gap:8px;margin-top:10px;color:#fff}',
        '.cg-urgency-icon{font-size:14px}',
        '.cg-urgency-time{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}',
        '.cg-urgency-label{font-size:10px;color:rgba(255,255,255,0.75)}',
        '.cg-recovery-actions{display:flex;gap:8px;margin-top:10px}',
        '.cg-recovery-btn{flex:1;padding:9px 12px;border-radius:12px;font-size:11.5px;font-weight:600;cursor:pointer;text-align:center;transition:all .3s cubic-bezier(.16,1,.3,1);border:none}',
        '.cg-recovery-btn-primary{background:#fff;color:#dc2626;box-shadow:0 2px 8px rgba(0,0,0,0.1)}',
        '.cg-recovery-btn-primary:hover{transform:translateY(-2px);box-shadow:0 4px 14px rgba(0,0,0,0.15)}',
        '.cg-recovery-btn-secondary{background:rgba(255,255,255,0.15);color:#fff;border:1px solid rgba(255,255,255,0.3);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}',
        '.cg-recovery-btn-secondary:hover{background:rgba(255,255,255,0.25);transform:translateY(-1px)}',

        // Mobile responsive
        '@media(max-width:480px){#cg-window{bottom:0;' + POSITION + ':0;width:100%;max-width:100%;height:100%;max-height:100%;border-radius:0;border:none}#cg-bubble{bottom:20px;' + POSITION + ':20px;width:56px;height:56px}}'
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
        '    <div id="cg-header-avatar"><span style="font-size:18px;color:#fff">&#10022;</span></div>',
        '    <div id="cg-header-info">',
        '      <div id="cg-header-title">' + escapeHtml(TITLE) + '</div>',
        '      <div id="cg-header-sub">The team can also help</div>',
        '    </div>',
        '    <div id="cg-header-actions">',
        '      <div id="cg-lang-wrap">',
        '        <button id="cg-lang-btn" title="Change Language"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg><span class="cg-lang-current">EN</span></button>',
        '        <div id="cg-lang-menu">',
        '          <div class="cg-lang-opt active" data-lang="en"><span class="cg-lang-flag">&#127468;&#127463;</span> English</div>',
        '          <div class="cg-lang-opt" data-lang="ar"><span class="cg-lang-flag">&#127480;&#127462;</span> العربية</div>',
        '          <div class="cg-lang-opt" data-lang="es"><span class="cg-lang-flag">&#127466;&#127480;</span> Español</div>',
        '          <div class="cg-lang-opt" data-lang="fr"><span class="cg-lang-flag">&#127467;&#127479;</span> Français</div>',
        '          <div class="cg-lang-opt" data-lang="zh"><span class="cg-lang-flag">&#127464;&#127475;</span> 中文</div>',
        '          <div class="cg-lang-opt" data-lang="ur"><span class="cg-lang-flag">&#127477;&#127472;</span> اردو</div>',
        '          <div class="cg-lang-opt" data-lang="tl"><span class="cg-lang-flag">&#127477;&#127469;</span> Tagalog</div>',
        '        </div>',
        '      </div>',
        '      <button id="cg-reset" title="New Chat"><svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg></button>',
        '      <button id="cg-close-btn" title="Close"><svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg></button>',
        '    </div>',
        '  </div>',
        '  <div id="cg-messages"></div>',
        '  <div id="cg-input-area">',
        '    <div id="cg-input-container">',
        '      <div id="cg-img-preview"><img id="cg-img-thumb" src="" alt=""><span class="cg-img-name" id="cg-img-name"></span><button class="cg-img-remove" id="cg-img-remove" title="Remove photo"><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg></button></div>',
        '      <textarea id="cg-input" placeholder="Ask a question..." autocomplete="off" rows="1"></textarea>',
        '      <div id="cg-input-bottom">',
        '        <div class="cg-input-actions">',
        '          <button class="cg-input-action" id="cg-attach" title="Send photo"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg></button>',
        '          <input type="file" id="cg-file-input" accept="image/*" style="display:none">',
        '          <button class="cg-input-action" id="cg-emoji-btn" title="Emoji"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-3.5-9c.83 0 1.5-.67 1.5-1.5S9.33 8 8.5 8 7 8.67 7 9.5 7.67 11 8.5 11zm7 0c.83 0 1.5-.67 1.5-1.5S16.33 8 15.5 8 14 8.67 14 9.5s.67 1.5 1.5 1.5zm-3.5 6.5c2.33 0 4.31-1.46 5.11-3.5H6.89c.8 2.04 2.78 3.5 5.11 3.5z"/></svg></button>',
        '          <div id="cg-emoji-picker"></div>',
        '          <button class="cg-input-action" id="cg-mic" title="Voice input" style="display:none"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg></button>',
        '        </div>',
        '        <button id="cg-send"><svg viewBox="0 0 24 24"><path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z" transform="rotate(-90 12 12)"/></svg></button>',
        '      </div>',
        '    </div>',
        '  </div>',
        '  <div id="cg-voice-inline">',
        '    <button class="cg-vi-stop" id="cg-voice-stop" title="Stop recording"><div class="cg-vi-square"></div></button>',
        '    <span class="cg-vi-timer" id="cg-voice-timer">00:00</span>',
        '    <div class="cg-vi-bars" id="cg-voice-bars"></div>',
        '    <p class="cg-vi-hint" id="cg-voice-hint">Listening...</p>',
        '  </div>',
        '  <div id="cg-mic-status"></div>',
        '  <div id="cg-powered">By chatting, you agree to our <a href="https://chatgenius.ai/privacy" target="_blank">Privacy Policy</a></div>',
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
    var closeBtn = shadow.getElementById('cg-close-btn');
    var micBtn = shadow.getElementById('cg-mic');
    var micStatus = shadow.getElementById('cg-mic-status');
    var voiceInline = shadow.getElementById('cg-voice-inline');
    var voiceTimer = shadow.getElementById('cg-voice-timer');
    var voiceBarsContainer = shadow.getElementById('cg-voice-bars');
    var voiceStopBtn = shadow.getElementById('cg-voice-stop');
    var voiceHint = shadow.getElementById('cg-voice-hint');
    var inputArea = shadow.getElementById('cg-input-area');
    var isOpen = false;
    var sending = false;
    var _cgCart = [];  // Track cart items for exit-intent recovery
    var _micRecording = false;
    var _micRecorder = null;
    var _micChunks = [];
    var _micStream = null;
    var _micMimeType = 'audio/webm';
    var _lastInputWasVoice = false;
    var _voiceSession = false; // stays true while booking flow continues from voice
    var _typewriterTimer = null;
    var _voiceTimerInterval = null;
    var _voiceAnalyser = null;
    var _voiceAnimFrame = null;
    var _voiceBars = [];

    // Create visualizer bars
    if (voiceBarsContainer) {
        for (var b = 0; b < 48; b++) {
            var bar = document.createElement('div');
            bar.className = 'cg-vi-bar';
            bar.style.height = '3px';
            voiceBarsContainer.appendChild(bar);
            _voiceBars.push(bar);
        }
    }

    // Voice stop button
    if (voiceStopBtn) {
        voiceStopBtn.addEventListener('click', function() { if (_micRecording) stopMicRecording(); });
    }

    // ── Emoji Picker ──
    var emojiBtn = shadow.getElementById('cg-emoji-btn');
    var emojiPicker = shadow.getElementById('cg-emoji-picker');
    var _emojiPopulated = false;
    var _emojis = ['😀','😂','🥰','😍','😊','😎','🤔','😅','😢','😭','🥺','😤','🔥','❤️','💙','💜','🩷','💛','👍','👎','👏','🙏','💪','✅','❌','⭐','🎉','🎊','📸','🦷','😁','😬','🤗','🥳','😇','🤩','🫡','👀','💯','🙌','✨','💖','🫶','🤝','📞','📅','💊','🏥','🩺','💉','🪥','😷','🤒','🤕','💆','🧑‍⚕️','👨‍⚕️','👩‍⚕️','🏨','💬','📝','🕐','📍'];

    function populateEmojis() {
        if (_emojiPopulated || !emojiPicker) return;
        var grid = document.createElement('div');
        grid.className = 'cg-emoji-grid';
        _emojis.forEach(function(em) {
            var btn = document.createElement('button');
            btn.className = 'cg-emoji-item';
            btn.textContent = em;
            btn.type = 'button';
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                if (input) {
                    var start = input.selectionStart || input.value.length;
                    var end = input.selectionEnd || input.value.length;
                    input.value = input.value.substring(0, start) + em + input.value.substring(end);
                    input.focus();
                    input.selectionStart = input.selectionEnd = start + em.length;
                }
                emojiPicker.classList.remove('open');
            });
            grid.appendChild(btn);
        });
        emojiPicker.appendChild(grid);
        _emojiPopulated = true;
    }

    if (emojiBtn && emojiPicker) {
        emojiBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            populateEmojis();
            emojiPicker.classList.toggle('open');
        });
        // Close emoji picker when clicking elsewhere in shadow DOM
        shadow.addEventListener('click', function(e) {
            if (e.target !== emojiBtn && !emojiPicker.contains(e.target)) {
                emojiPicker.classList.remove('open');
            }
        });
    }

    // ── Photo Attachment ──
    var attachBtn = shadow.getElementById('cg-attach');
    var fileInput = shadow.getElementById('cg-file-input');
    var imgPreview = shadow.getElementById('cg-img-preview');
    var imgThumb = shadow.getElementById('cg-img-thumb');
    var imgName = shadow.getElementById('cg-img-name');
    var imgRemove = shadow.getElementById('cg-img-remove');
    var _pendingFile = null; // the File object waiting to be sent
    var _pendingObjUrl = null;

    function clearImagePreview() {
        _pendingFile = null;
        if (_pendingObjUrl) { URL.revokeObjectURL(_pendingObjUrl); _pendingObjUrl = null; }
        if (imgPreview) imgPreview.classList.remove('active');
        if (imgThumb) imgThumb.src = '';
        if (imgName) imgName.textContent = '';
        if (fileInput) fileInput.value = '';
    }

    if (attachBtn && fileInput) {
        attachBtn.addEventListener('click', function() { fileInput.click(); });
        fileInput.addEventListener('change', function() {
            var file = fileInput.files && fileInput.files[0];
            if (!file) return;
            if (file.size > 5 * 1024 * 1024) {
                addMessage('Image too large (max 5MB). Please choose a smaller photo.', false);
                fileInput.value = '';
                return;
            }
            // Show preview strip in input area
            _pendingFile = file;
            _pendingObjUrl = URL.createObjectURL(file);
            if (imgThumb) imgThumb.src = _pendingObjUrl;
            if (imgName) imgName.textContent = file.name;
            if (imgPreview) imgPreview.classList.add('active');
            if (input) { input.placeholder = 'Add a message about this photo...'; input.focus(); }
        });
    }

    if (imgRemove) {
        imgRemove.addEventListener('click', function() {
            clearImagePreview();
            if (input) input.placeholder = 'Ask a question...';
        });
    }

    // ── Return Visit Tracking ──
    var VISIT_COUNT_KEY = 'cg_visit_count_' + ADMIN_ID;
    var VISIT_LAST_KEY = 'cg_last_visit_' + ADMIN_ID;
    var _visitCount = 1;
    try {
        _visitCount = parseInt(localStorage.getItem(VISIT_COUNT_KEY) || '0', 10) + 1;
        localStorage.setItem(VISIT_COUNT_KEY, String(_visitCount));
        localStorage.setItem(VISIT_LAST_KEY, String(Date.now()));
    } catch(e) {}

    // ── Multi-Language Auto-Detection ──
    var _detectedLang = (navigator.language || navigator.userLanguage || 'en').split('-')[0];

    // ── Sound Notification ──
    var _notifSound = null;
    try {
        // Tiny beep using Web Audio API (no external file needed)
        var _audioCtx = null;
        function playNotifSound() {
            try {
                if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                var osc = _audioCtx.createOscillator();
                var gain = _audioCtx.createGain();
                osc.connect(gain);
                gain.connect(_audioCtx.destination);
                osc.frequency.value = 880;
                osc.type = 'sine';
                gain.gain.value = 0.08;
                gain.gain.exponentialRampToValueAtTime(0.001, _audioCtx.currentTime + 0.3);
                osc.start(_audioCtx.currentTime);
                osc.stop(_audioCtx.currentTime + 0.3);
            } catch(e) {}
        }
    } catch(e) { function playNotifSound(){} }

    // ── Conversation Analytics Tracking ──
    var _chatStartTime = null;
    var _messageCount = 0;
    var _maxScrollDepth = 0;
    var _pageLoadTime = Date.now();

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
        // Voice input button (enterprise/agency only)
        if (cbCustom.voice_enabled && micBtn) {
            micBtn.style.display = 'inline-flex';
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
        var colors = ['#f87171','#fbbf24','#34d399','#a78bfa','#c084fc','#f472b6','#fb923c'];
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
    // Bug fix #4: Null check before adding event listener
    if (resetBtn) {
        resetBtn.addEventListener('click', function() {
            stopHandoffPolling();
            stopAmbientPoll();
            _chatStarted = false;
            _shownStaffMsgIds = {};
            sessionId = 'web_' + ADMIN_ID + '_' + Math.random().toString(36).substr(2, 12);
            try { localStorage.setItem(SESSION_KEY, sessionId); localStorage.setItem(SESSION_TS_KEY, String(Date.now())); } catch(e) {}
            if (messages) messages.innerHTML = '';
            _voiceSession = false; _lastInputWasVoice = false;
            if (_micRecording) stopMicRecording();
            resetMicUI();
            if (window.speechSynthesis) try { window.speechSynthesis.cancel(); } catch(e) {}
            if (_typewriterTimer) { clearInterval(_typewriterTimer); _typewriterTimer = null; }
            addMessage(WELCOME, false);
        });
    }

    // ── Restore session or show welcome ──
    var _isRestoredSession = false;
    try { _isRestoredSession = localStorage.getItem(SESSION_KEY) === sessionId && !!localStorage.getItem(SESSION_TS_KEY); } catch(e) {}

    if (_isRestoredSession) {
        // Fetch chat history and restore messages
        fetch(SERVER + '/api/chat/history?session_id=' + encodeURIComponent(sessionId) + '&admin_id=' + encodeURIComponent(ADMIN_ID))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(function(m) {
                    if (m.sender === 'user') addMessage(m.text, true);
                    else if (m.sender === 'staff') addStaffMessage(m.text, '');
                    else addMessage(m.text, false);
                });
                _chatStarted = true;
                startAmbientPoll();
            } else {
                addMessage(WELCOME, false);
            }
        })
        .catch(function() { addMessage(WELCOME, false); });
    } else {
        setTimeout(function() { addMessage(WELCOME, false); }, 400);
    }

    // ── Toggle with animation ──
    // Bug fix #4: Null check before adding event listener
    if (!bubble) return;
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

    // ── Close button inside header ──
    function closeWidget() {
        isOpen = false;
        bubble.classList.remove('open');
        win.classList.add('closing');
        win.classList.remove('open');
        setTimeout(function() {
            if (!isOpen) win.style.display = 'none';
        }, 350);
    }
    if (closeBtn) closeBtn.addEventListener('click', closeWidget);

    // ── Language selector ──
    var langBtn = shadow.getElementById('cg-lang-btn');
    var langMenu = shadow.getElementById('cg-lang-menu');
    var currentLang = 'en';
    if (langBtn && langMenu) {
        langBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            langMenu.classList.toggle('open');
        });
        var langOpts = langMenu.querySelectorAll('.cg-lang-opt');
        langOpts.forEach(function(opt) {
            opt.addEventListener('click', function(e) {
                e.stopPropagation();
                var lang = opt.getAttribute('data-lang');
                currentLang = lang;
                langOpts.forEach(function(o) { o.classList.remove('active'); });
                opt.classList.add('active');
                langMenu.classList.remove('open');
                // Update pill label
                var langLabel = langBtn.querySelector('.cg-lang-current');
                if (langLabel) langLabel.textContent = lang.toUpperCase();
                // Tell backend to switch language for this session
                fetch(SERVER + '/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({session_id: sessionId, admin_id: ADMIN_ID, message: '__set_language__' + lang})
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.reply) addMessage(data.reply, false);
                }).catch(function() {});
            });
        });
        // Close menu when clicking elsewhere
        shadow.addEventListener('click', function() { langMenu.classList.remove('open'); });
    }

    // ── Send ──
    // Bug fix #4: Null checks before adding event listeners
    if (sendBtn) sendBtn.addEventListener('click', function() { _voiceSession = false; send(); });
    if (input) {
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _voiceSession = false; send(); }
        });
        // Auto-resize textarea as user types
        input.addEventListener('input', function() {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 80) + 'px';
        });
        // Focus styling for container
        var inputContainer = shadow.getElementById('cg-input-container');
        if (inputContainer) {
            input.addEventListener('focus', function() { inputContainer.classList.add('focused'); });
            input.addEventListener('blur', function() { inputContainer.classList.remove('focused'); });
        }
    }

    var _pendingDisplayText = null; // translated label to show in chat bubble
    function send(fromVoice) {
        var text = input.value.trim();
        var hasImage = !!_pendingFile;
        if ((!text && !hasImage) || sending) return;
        input.value = '';
        input.style.height = 'auto';
        var wasVoice = fromVoice || _lastInputWasVoice || _voiceSession;
        if (fromVoice || _lastInputWasVoice) _voiceSession = true;
        _lastInputWasVoice = false;

        // Show user message with optional image
        if (hasImage && _pendingObjUrl) {
            var imgMsg = document.createElement('div');
            imgMsg.className = 'cg-msg cg-msg-user';
            imgMsg.style.animation = getMsgAnimation();
            var imgEl = document.createElement('img');
            imgEl.className = 'cg-msg-img';
            imgEl.src = _pendingObjUrl;
            imgEl.alt = 'Photo';
            imgMsg.appendChild(imgEl);
            if (text) {
                var textSpan = document.createElement('span');
                textSpan.textContent = text;
                imgMsg.appendChild(textSpan);
            }
            if (messages) { messages.appendChild(imgMsg); requestAnimationFrame(function() { messages.scrollTop = messages.scrollHeight; }); }
        } else {
            addMessage(_pendingDisplayText || text, true);
        }
        _pendingDisplayText = null;
        _messageCount++;
        if (!_chatStartTime) _chatStartTime = Date.now();
        if (!_chatStarted) { _chatStarted = true; startAmbientPoll(); }
        try { localStorage.setItem(SESSION_TS_KEY, String(Date.now())); } catch(e) {}
        sending = true;
        sendBtn.disabled = true;

        // Typing indicator
        var typing = document.createElement('div');
        typing.className = 'cg-typing';
        typing.innerHTML = '<span></span><span></span><span></span>';
        messages.appendChild(typing);
        messages.scrollTop = messages.scrollHeight;

        // If image is attached, upload it first, then send chat message
        var chatText = text || 'What do you see in this photo?';
        var imageFile = _pendingFile;
        clearImagePreview();
        if (input) input.placeholder = 'Ask a question...';

        var uploadPromise;
        if (imageFile) {
            var fd = new FormData();
            fd.append('image', imageFile);
            fd.append('session_id', sessionId);
            fd.append('admin_id', ADMIN_ID);
            fd.append('description', imageFile.name);
            uploadPromise = fetch(SERVER + '/api/chat/upload-image', { method: 'POST', body: fd })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data.ok) { console.warn('Image upload failed:', data.error); }
                });
        } else {
            uploadPromise = Promise.resolve();
        }

        uploadPromise.then(function() {
            return fetch(SERVER + '/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: chatText, session_id: sessionId, admin_id: ADMIN_ID, customer_id: (window.ChatGeniusConfig || {}).customerId || CUSTOMER_ID, customer_api_url: (window.ChatGeniusConfig || {}).customerApiUrl || CUSTOMER_API_URL, language: _detectedLang, visit_count: _visitCount })
            });
        })
        .then(function(r) {
            // Bug fix #6: Handle non-OK responses gracefully
            if (!r.ok) throw new Error('Server error: ' + r.status);
            return r.json();
        })
        .then(function(data) {
            if (typing && typing.parentNode) typing.remove();
            var reply = data.reply || '';
            // If handoff is active, bot stays silent — don't show bot reply
            if (data.handoff_silent) {
                // Skip bot bubble entirely
            } else {
                addMessage(reply || 'Sorry, something went wrong.', false);
            }
            _messageCount++;
            // Sound notification when widget is closed
            if (!isOpen) { try { playNotifSound(); } catch(e) {} }
            // Handle lead capture form from server
            if (data.lead_form) { renderLeadForm(data.lead_form); }
            // Sync cart state from server (always accurate)
            if (data.cart && data.cart.length > 0) {
                // Detect newly added items and notify parent window for native cart sync
                var prevIds = _cgCart.map(function(c){ return c.id; });
                _cgCart = data.cart.slice();
                data.cart.forEach(function(item) {
                    if (prevIds.indexOf(item.id) === -1 && item.external_id) {
                        // New item added — tell the parent website to add to its native cart
                        try {
                            window.parent.postMessage({
                                type: 'chatgenius:add_to_cart',
                                product_id: item.external_id,
                                product_name: item.name,
                                quantity: item.qty || 1,
                                price: item.price,
                                url: item.url || '',
                                variant_options: item.variant_options || null
                            }, '*');
                        } catch(e) {}
                    }
                });
            } else if (data.cart && data.cart.length === 0) {
                _cgCart = [];
            }
            if (data.options) {
                renderOptions(data.options);
                // If input was voice and there are dropdown options, speak response + tell user to select
                if (wasVoice && cbCustom.voice_enabled) {
                    var speakMsg = reply.replace(/\*\*/g, '');
                    if (data.options.type !== 'calendar') speakMsg += '. Please select an option on screen.';
                    else speakMsg += '. Please pick a date on the calendar.';
                    cgSpeak(speakMsg);
                }
            } else if (wasVoice && cbCustom.voice_enabled) {
                // Speak the AI response
                cgSpeak(reply.replace(/\*\*/g, ''));
            }
            // Store patient_id for returning customer recognition
            if (data.patient_id) {
                try { localStorage.setItem(PATIENT_KEY, String(data.patient_id)); } catch(e) {}
                if (!CUSTOMER_ID) CUSTOMER_ID = String(data.patient_id);
            }
            if (data.booking_confirmed) {
                _voiceSession = false;
                setTimeout(function() { showCelebration(); }, 500);
            }
            // Live chat handoff state
            handleHandoffState(data);
            if (!isOpen && badge) {
                badge.style.display = 'flex';
            }
        })
        .catch(function(err) {
            if (typing && typing.parentNode) typing.remove();
            // Bug fix #6: User-visible error message on fetch failure
            addMessage('Could not connect. Please try again.', false);
            console.warn('ChatGenius: chat request failed:', err);
        })
        .finally(function() {
            sending = false;
            if (sendBtn) sendBtn.disabled = false;
        });
    }

    // ── TTS for voice responses ──
    var _cgVoice = null;
    function _pickVoice() {
        if (_cgVoice) return _cgVoice;
        var voices = window.speechSynthesis.getVoices();
        // Prefer natural-sounding voices
        var preferred = ['Samantha', 'Google US English', 'Karen', 'Moira', 'Tessa', 'Alex'];
        for (var p = 0; p < preferred.length; p++) {
            for (var v = 0; v < voices.length; v++) {
                if (voices[v].name.indexOf(preferred[p]) >= 0 && voices[v].lang.indexOf('en') === 0) { _cgVoice = voices[v]; return _cgVoice; }
            }
        }
        // Fallback: first English voice
        for (var v = 0; v < voices.length; v++) {
            if (voices[v].lang.indexOf('en') === 0) { _cgVoice = voices[v]; return _cgVoice; }
        }
        return null;
    }
    if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = function() { _cgVoice = null; _pickVoice(); };

    function cgSpeak(text) {
        if (!window.speechSynthesis) return;
        window.speechSynthesis.cancel();
        var utt = new SpeechSynthesisUtterance(text);
        utt.rate = 1.05; utt.pitch = 1.0; utt.volume = 1.0; utt.lang = 'en-US';
        var voice = _pickVoice();
        if (voice) utt.voice = voice;
        try { window.speechSynthesis.speak(utt); } catch(e) {}
    }

    // ── Voice recording (enterprise only) ──
    if (micBtn) {
        micBtn.addEventListener('click', function() {
            if (_micRecording) {
                stopMicRecording();
            } else {
                startMicRecording();
            }
        });
    }

    function startMicRecording() {
        if (_micRecording || sending) return;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
            if (micStatus) { micStatus.style.display = 'block'; micStatus.textContent = 'Voice not supported in this browser.'; setTimeout(function() { micStatus.style.display = 'none'; }, 3000); }
            return;
        }
        navigator.mediaDevices.getUserMedia({ audio: true }).then(function(stream) {
            _micStream = stream;
            _micChunks = [];
            _micRecording = true;
            if (micBtn) micBtn.classList.add('recording');

            // Show inline voice UI, hide normal input
            if (inputArea) inputArea.style.display = 'none';
            if (voiceInline) voiceInline.classList.add('active');
            if (voiceHint) voiceHint.textContent = 'Listening...';

            // Start timer
            var startTime = Date.now();
            if (voiceTimer) voiceTimer.textContent = '00:00';
            _voiceTimerInterval = setInterval(function() {
                var elapsed = Math.floor((Date.now() - startTime) / 1000);
                var m = Math.floor(elapsed / 60);
                var s = elapsed % 60;
                if (voiceTimer) voiceTimer.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
            }, 200);

            // Mark bars as active
            for (var bi = 0; bi < _voiceBars.length; bi++) { _voiceBars[bi].classList.add('active'); }

            // Set up audio analyser for visualizer bars
            try {
                var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                var source = audioCtx.createMediaStreamSource(stream);
                _voiceAnalyser = audioCtx.createAnalyser();
                _voiceAnalyser.fftSize = 128;
                source.connect(_voiceAnalyser);
                var bufLen = _voiceAnalyser.frequencyBinCount;
                var dataArr = new Uint8Array(bufLen);
                function drawBars() {
                    _voiceAnimFrame = requestAnimationFrame(drawBars);
                    _voiceAnalyser.getByteFrequencyData(dataArr);
                    for (var i = 0; i < _voiceBars.length; i++) {
                        var idx = Math.floor(i * bufLen / _voiceBars.length);
                        var val = dataArr[idx] || 0;
                        var h = Math.max(3, (val / 255) * 14);
                        _voiceBars[i].style.height = h + 'px';
                    }
                }
                drawBars();
            } catch(e) { /* analyser not critical */ }

            var mimeType = 'audio/webm;codecs=opus';
            if (typeof MediaRecorder !== 'undefined' && !MediaRecorder.isTypeSupported(mimeType)) mimeType = 'audio/webm';
            if (typeof MediaRecorder !== 'undefined' && !MediaRecorder.isTypeSupported(mimeType)) mimeType = 'audio/mp4';
            _micMimeType = mimeType;
            _micRecorder = new MediaRecorder(stream, MediaRecorder.isTypeSupported(mimeType) ? { mimeType: mimeType } : {});
            _micRecorder.ondataavailable = function(e) { if (e.data.size > 0) _micChunks.push(e.data); };
            _micRecorder.onstop = function() {
                if (_micStream) { _micStream.getTracks().forEach(function(t) { t.stop(); }); _micStream = null; }
                if (_micChunks.length === 0) { resetMicUI(); return; }
                var blob = new Blob(_micChunks, { type: _micMimeType });
                if (blob.size < 500) { resetMicUI(); return; }
                transcribeAndSend(blob);
            };
            _micRecorder.start(250);

            // Auto-stop after 30 seconds
            setTimeout(function() { if (_micRecording) stopMicRecording(); }, 30000);
        }).catch(function(err) {
            console.warn('ChatGenius: mic access denied:', err);
            _micRecording = false;
            resetMicUI();
            if (micStatus) { micStatus.style.display = 'block'; micStatus.textContent = 'Mic access denied'; setTimeout(function() { micStatus.style.display = 'none'; }, 3000); }
        });
    }

    function stopMicRecording() {
        _micRecording = false;
        if (micBtn) micBtn.classList.remove('recording');
        if (_micRecorder && _micRecorder.state !== 'inactive') _micRecorder.stop();
        // Clean up voice inline visuals
        if (_voiceTimerInterval) { clearInterval(_voiceTimerInterval); _voiceTimerInterval = null; }
        if (_voiceAnimFrame) { cancelAnimationFrame(_voiceAnimFrame); _voiceAnimFrame = null; }
        _voiceAnalyser = null;
        for (var i = 0; i < _voiceBars.length; i++) { _voiceBars[i].style.height = '3px'; _voiceBars[i].classList.remove('active'); }
    }

    function resetMicUI() {
        _micRecording = false;
        if (micBtn) micBtn.classList.remove('recording');
        if (micStatus) { micStatus.style.display = 'none'; micStatus.textContent = ''; }
        // Hide inline voice UI, restore input area
        if (voiceInline) voiceInline.classList.remove('active');
        if (inputArea) inputArea.style.display = '';
        if (_voiceTimerInterval) { clearInterval(_voiceTimerInterval); _voiceTimerInterval = null; }
        if (_voiceAnimFrame) { cancelAnimationFrame(_voiceAnimFrame); _voiceAnimFrame = null; }
        _voiceAnalyser = null;
        if (voiceTimer) voiceTimer.textContent = '00:00';
        for (var i = 0; i < _voiceBars.length; i++) { _voiceBars[i].style.height = '3px'; _voiceBars[i].classList.remove('active'); }
    }

    function transcribeAndSend(audioBlob) {
        // Show transcribing state in the inline voice UI
        if (voiceHint) voiceHint.textContent = 'Transcribing...';

        var formData = new FormData();
        formData.append('audio', audioBlob, 'voice.webm');
        formData.append('lang', 'en');

        fetch(SERVER + '/api/voice/transcribe', {
            method: 'POST',
            body: formData
        })
        .then(function(r) {
            if (!r.ok) throw new Error('Transcription failed: ' + r.status);
            return r.json();
        })
        .then(function(data) {
            resetMicUI();
            var text = (data.corrected || data.text || '').trim();
            if (!text) {
                if (micStatus) { micStatus.style.display = 'block'; micStatus.textContent = 'Could not hear you. Try again.'; setTimeout(function() { micStatus.style.display = 'none'; }, 3000); }
                return;
            }
            // Put text in input and send it through the normal chat flow
            input.value = text;
            _lastInputWasVoice = true;
            send(true);
        })
        .catch(function(err) {
            resetMicUI();
            console.warn('ChatGenius: transcription failed:', err);
            if (micStatus) { micStatus.style.display = 'block'; micStatus.textContent = 'Voice failed. Try typing instead.'; setTimeout(function() { micStatus.style.display = 'none'; }, 3000); }
        });
    }

    function addMessage(text, isUser) {
        // Bug fix #4: Null check on messages container
        if (!messages) return;
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
                    _typewriterTimer = null;
                    div.innerHTML = html;
                }
                // Bug fix #5: Reliable scroll-to-bottom using requestAnimationFrame
                requestAnimationFrame(function() { messages.scrollTop = messages.scrollHeight; });
            }, perChar);
            _typewriterTimer = timer;
        } else {
            div.style.animation = getMsgAnimation();
            div.innerHTML = isUser ? escapeHtml(text) : formatMarkdown(text);
            messages.appendChild(div);
        }
        // Bug fix #5: Reliable scroll-to-bottom using requestAnimationFrame
        requestAnimationFrame(function() { messages.scrollTop = messages.scrollHeight; });
    }

    // ── Render UI options (dropdowns, calendar) ──
    function renderOptions(options) {
        if (!options || !options.type || !messages) return;

        if (options.type === 'calendar') { renderCalendar(options); return; }
        if (options.type === 'quick_replies') { renderQuickReplies(options); return; }
        if (options.type === 'product_cards') { renderProductCards(options); return; }
        if (options.type === 'property_cards') { renderPropertyCards(options); return; }
        if (options.type === 'cart_summary') { renderCartSummary(options); return; }
        if (options.type === 'order_tracking') { renderOrderTracking(options); return; }
        if (options.type === 'agent_card') { renderAgentCard(options); return; }

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
                    _pendingDisplayText = item.name;
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
            else if (isBooked) sub.textContent = item.subtitle || 'Fully booked \u2014 tap to join waitlist';
            else if (isTime) sub.textContent = item.subtitle || 'Available';
            else if (isCancel) sub.textContent = item.subtitle || 'Tap to select';
            else if (isBookingType) sub.textContent = item.subtitle || (item.value === 'service' ? 'Choose from available services' : 'Schedule a regular visit');
            else if (isServices) sub.textContent = item.subtitle || 'Tap to select';
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
                    var sendValue = isCancel ? String(item.index) : (item.value || item.name);
                    _pendingDisplayText = item.name || sendValue;
                    input.value = sendValue;
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

    // ── Render quick reply buttons ──
    function renderQuickReplies(options) {
        var items = options.items || [];
        var wrap = document.createElement('div');
        wrap.className = 'cg-quick-replies';
        items.forEach(function(item) {
            // If item has a url property, render as a link button that opens in new tab
            if (item.url) {
                var link = document.createElement('a');
                link.className = 'cg-quick-btn';
                link.textContent = item.label || item.name || item;
                link.href = item.url;
                link.target = '_blank';
                link.rel = 'noopener';
                link.style.textDecoration = 'none';
                link.style.display = 'inline-flex';
                link.style.alignItems = 'center';
                link.style.gap = '4px';
                link.innerHTML = (item.label || item.name || '') + ' <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';
                wrap.appendChild(link);
            } else {
                var btn = document.createElement('button');
                btn.className = 'cg-quick-btn';
                btn.textContent = item.label || item.name || item;
                btn.addEventListener('click', function() {
                    wrap.querySelectorAll('.cg-quick-btn').forEach(function(b) { b.style.opacity = '0.4'; b.style.pointerEvents = 'none'; });
                    btn.classList.add('selected');
                    btn.style.opacity = '1';
                    _pendingDisplayText = item.label || item.name || item;
                    setTimeout(function() { input.value = item.value || item.label || item.name || item; send(); }, 150);
                });
                wrap.appendChild(btn);
            }
        });
        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Render product cards (e-commerce) ──
    function renderProductCards(options) {
        var items = options.items || [];
        var currency = options.currency || '$';
        var wrap = document.createElement('div');
        wrap.className = 'cg-product-cards';
        items.forEach(function(item, idx) {
            var card = document.createElement('div');
            card.className = 'cg-product-card';
            card.style.animationDelay = (idx * 0.08) + 's';

            // Image
            var imgWrap = document.createElement('div');
            imgWrap.className = 'cg-product-img';
            if (item.image) {
                var img = document.createElement('img');
                img.src = item.image;
                img.alt = item.name || '';
                img.loading = 'lazy';
                imgWrap.appendChild(img);
            } else {
                imgWrap.innerHTML = '<svg viewBox="0 0 24 24"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>';
            }
            card.appendChild(imgWrap);

            // Body
            var body = document.createElement('div');
            body.className = 'cg-product-body';

            var name = document.createElement('div');
            name.className = 'cg-product-name';
            name.textContent = item.name || '';
            body.appendChild(name);

            // Price row
            var priceRow = document.createElement('div');
            priceRow.className = 'cg-product-price-row';
            var price = document.createElement('span');
            price.className = 'cg-product-price';
            price.textContent = currency + parseFloat(item.price || 0).toFixed(2);
            priceRow.appendChild(price);
            if (item.compare_price && parseFloat(item.compare_price) > parseFloat(item.price)) {
                var compare = document.createElement('span');
                compare.className = 'cg-product-compare';
                compare.textContent = currency + parseFloat(item.compare_price).toFixed(2);
                priceRow.appendChild(compare);
                var badge = document.createElement('span');
                badge.className = 'cg-product-badge';
                var pct = Math.round((1 - parseFloat(item.price) / parseFloat(item.compare_price)) * 100);
                badge.textContent = '-' + pct + '%';
                priceRow.appendChild(badge);
            }
            body.appendChild(priceRow);

            // Rating
            if (item.rating && parseFloat(item.rating) > 0) {
                var ratingWrap = document.createElement('div');
                ratingWrap.className = 'cg-product-rating';
                var stars = document.createElement('span');
                stars.className = 'cg-product-stars';
                var fullStars = Math.floor(parseFloat(item.rating));
                stars.textContent = '\u2605'.repeat(fullStars) + '\u2606'.repeat(5 - fullStars);
                ratingWrap.appendChild(stars);
                if (item.review_count) {
                    var reviews = document.createElement('span');
                    reviews.className = 'cg-product-reviews';
                    reviews.textContent = '(' + item.review_count + ')';
                    ratingWrap.appendChild(reviews);
                }
                body.appendChild(ratingWrap);
            }

            // Stock warning
            if (item.stock && item.stock > 0 && item.stock <= 5) {
                var stock = document.createElement('div');
                stock.className = 'cg-product-stock';
                stock.textContent = 'Only ' + item.stock + ' left in stock!';
                body.appendChild(stock);
            }

            // Action buttons
            var actions = document.createElement('div');
            actions.className = 'cg-product-actions';
            var addBtn = document.createElement('button');
            addBtn.className = 'cg-product-btn cg-product-btn-primary';
            addBtn.textContent = 'Add to Cart';
            addBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                var cartMode = (cbCustom && cbCustom.cart_integration_mode) || 'product_link';
                // If native_cart but integration not done, fall back to product_link
                if (cartMode === 'native_cart' && cbCustom && cbCustom.cart_integration_pending) {
                    cartMode = 'product_link';
                }
                if (cartMode === 'native_cart') {
                    // Enterprise: add via chatbot (triggers postMessage to store)
                    input.value = 'Add ' + (item.name || 'this product') + ' to cart';
                    send();
                } else if (item.url) {
                    window.open(item.url, '_blank');
                } else {
                    input.value = 'Add ' + (item.name || 'this product') + ' to cart';
                    send();
                }
            });
            actions.appendChild(addBtn);
            var detailBtn = document.createElement('button');
            detailBtn.className = 'cg-product-btn cg-product-btn-secondary';
            detailBtn.textContent = 'Details';
            detailBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                input.value = 'Tell me more about ' + (item.name || 'this product');
                send();
            });
            actions.appendChild(detailBtn);
            body.appendChild(actions);

            card.appendChild(body);
            wrap.appendChild(card);
        });
        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Render property cards (real estate) ──
    function renderPropertyCards(options) {
        var items = options.items || [];
        var wrap = document.createElement('div');
        wrap.className = 'cg-property-cards';
        items.forEach(function(item, idx) {
            var card = document.createElement('div');
            card.className = 'cg-property-card';
            card.style.animationDelay = (idx * 0.08) + 's';

            // Image
            var imgWrap = document.createElement('div');
            imgWrap.className = 'cg-property-img';
            if (item.image) {
                var img = document.createElement('img');
                img.src = item.image;
                img.alt = item.address || '';
                img.loading = 'lazy';
                imgWrap.appendChild(img);
            } else {
                imgWrap.innerHTML = '<svg viewBox="0 0 24 24"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>';
            }
            // Status badge
            if (item.status) {
                var statusBadge = document.createElement('div');
                statusBadge.className = 'cg-property-status ' + (item.status || 'active');
                statusBadge.textContent = item.status;
                imgWrap.appendChild(statusBadge);
            }
            card.appendChild(imgWrap);

            // Body
            var body = document.createElement('div');
            body.className = 'cg-property-body';

            var price = document.createElement('div');
            price.className = 'cg-property-price';
            price.textContent = '$' + Number(item.price || 0).toLocaleString();
            if (item.price_per_sqft) {
                price.textContent += ' \u2022 $' + item.price_per_sqft + '/sqft';
            }
            body.appendChild(price);

            var addr = document.createElement('div');
            addr.className = 'cg-property-addr';
            addr.textContent = item.address || '';
            body.appendChild(addr);

            // Details row: beds, baths, sqft
            var details = document.createElement('div');
            details.className = 'cg-property-details';
            if (item.beds) {
                var bedEl = document.createElement('span');
                bedEl.className = 'cg-property-detail';
                bedEl.innerHTML = '<svg viewBox="0 0 24 24"><path d="M7 13c1.66 0 3-1.34 3-3S8.66 7 7 7s-3 1.34-3 3 1.34 3 3 3zm12-6h-8v7H3V5H1v15h2v-3h18v3h2v-9c0-2.21-1.79-4-4-4z"/></svg> <strong>' + item.beds + '</strong> bd';
                details.appendChild(bedEl);
            }
            if (item.baths) {
                var bathEl = document.createElement('span');
                bathEl.className = 'cg-property-detail';
                bathEl.innerHTML = '<svg viewBox="0 0 24 24"><path d="M7 13c1.66 0 3-1.34 3-3S8.66 7 7 7s-3 1.34-3 3 1.34 3 3 3zm0 0"/></svg> <strong>' + item.baths + '</strong> ba';
                details.appendChild(bathEl);
            }
            if (item.sqft) {
                var sqftEl = document.createElement('span');
                sqftEl.className = 'cg-property-detail';
                sqftEl.textContent = Number(item.sqft).toLocaleString() + ' sqft';
                details.appendChild(sqftEl);
            }
            body.appendChild(details);

            // Features
            if (item.features && item.features.length > 0) {
                var feats = document.createElement('div');
                feats.className = 'cg-property-features';
                item.features.slice(0, 5).forEach(function(f) {
                    var feat = document.createElement('span');
                    feat.className = 'cg-property-feat';
                    feat.textContent = f;
                    feats.appendChild(feat);
                });
                body.appendChild(feats);
            }

            // Scores
            if (item.walk_score || item.school_rating) {
                var scores = document.createElement('div');
                scores.className = 'cg-property-scores';
                if (item.walk_score) {
                    var ws = document.createElement('span');
                    ws.className = 'cg-property-score';
                    ws.innerHTML = 'Walk: <strong>' + item.walk_score + '</strong>';
                    scores.appendChild(ws);
                }
                if (item.school_rating) {
                    var sr = document.createElement('span');
                    sr.className = 'cg-property-score';
                    sr.innerHTML = 'School: <strong>' + item.school_rating + '/10</strong>';
                    scores.appendChild(sr);
                }
                body.appendChild(scores);
            }

            // Action buttons
            var actions = document.createElement('div');
            actions.className = 'cg-property-actions';
            var viewBtn = document.createElement('button');
            viewBtn.className = 'cg-property-btn cg-property-btn-primary';
            viewBtn.textContent = 'Schedule Viewing';
            viewBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                input.value = 'I want to schedule a viewing for ' + (item.address || 'this property');
                send();
            });
            actions.appendChild(viewBtn);
            var moreBtn = document.createElement('button');
            moreBtn.className = 'cg-property-btn cg-property-btn-secondary';
            moreBtn.textContent = 'More Info';
            moreBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                input.value = 'Tell me more about ' + (item.address || 'this property');
                send();
            });
            actions.appendChild(moreBtn);
            body.appendChild(actions);

            card.appendChild(body);
            wrap.appendChild(card);
        });
        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Render cart summary ──
    function renderCartSummary(options) {
        var items = options.items || [];
        var currency = options.currency || '$';
        var wrap = document.createElement('div');
        wrap.className = 'cg-cart-summary';

        var title = document.createElement('div');
        title.className = 'cg-cart-title';
        title.innerHTML = '\uD83D\uDED2 Your Cart (' + items.length + ' items)';
        wrap.appendChild(title);

        var total = 0;
        items.forEach(function(item) {
            var row = document.createElement('div');
            row.className = 'cg-cart-item';
            var name = document.createElement('span');
            name.className = 'cg-cart-item-name';
            name.textContent = item.name || '';
            row.appendChild(name);
            var qty = document.createElement('span');
            qty.className = 'cg-cart-item-qty';
            qty.textContent = 'x' + (item.qty || 1);
            row.appendChild(qty);
            var price = document.createElement('span');
            price.className = 'cg-cart-item-price';
            var itemTotal = parseFloat(item.price || 0) * (item.qty || 1);
            price.textContent = currency + itemTotal.toFixed(2);
            row.appendChild(price);
            wrap.appendChild(row);
            total += itemTotal;
        });

        if (options.discount) {
            total -= parseFloat(options.discount);
        }

        var totalRow = document.createElement('div');
        totalRow.className = 'cg-cart-total';
        var label = document.createElement('span');
        label.className = 'cg-cart-total-label';
        label.textContent = 'Total:';
        totalRow.appendChild(label);
        var totalPrice = document.createElement('span');
        totalPrice.className = 'cg-cart-total-price';
        totalPrice.textContent = currency + total.toFixed(2);
        totalRow.appendChild(totalPrice);
        wrap.appendChild(totalRow);

        // Cart actions
        var actions = document.createElement('div');
        actions.className = 'cg-cart-actions';
        var checkoutBtn = document.createElement('button');
        checkoutBtn.className = 'cg-product-btn cg-product-btn-primary';
        checkoutBtn.textContent = 'Checkout';
        checkoutBtn.addEventListener('click', function() {
            input.value = 'I want to checkout';
            send();
        });
        actions.appendChild(checkoutBtn);
        var continueBtn = document.createElement('button');
        continueBtn.className = 'cg-product-btn cg-product-btn-secondary';
        continueBtn.textContent = 'Continue Shopping';
        continueBtn.addEventListener('click', function() {
            input.value = 'Show me more products';
            send();
        });
        actions.appendChild(continueBtn);
        wrap.appendChild(actions);

        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Render order tracking ──
    function renderOrderTracking(options) {
        var wrap = document.createElement('div');
        wrap.className = 'cg-order-track';

        var header = document.createElement('div');
        header.className = 'cg-order-header';
        var orderNum = document.createElement('span');
        orderNum.className = 'cg-order-number';
        orderNum.textContent = 'Order ' + (options.order_number || '');
        header.appendChild(orderNum);
        var statusBadge = document.createElement('span');
        var st = (options.status || 'processing').toLowerCase();
        statusBadge.className = 'cg-order-status-badge ' + st;
        statusBadge.textContent = options.status || 'Processing';
        header.appendChild(statusBadge);
        wrap.appendChild(header);

        // Progress steps — handle special statuses
        var isCancelled = st === 'cancelled' || st === 'refunded';
        var isPending = st === 'pending';
        var steps = ['Confirmed', 'Processing', 'Shipped', 'Delivered'];
        var currentStep;
        if (isCancelled) {
            currentStep = -1;
        } else if (isPending) {
            currentStep = -1;
        } else {
            currentStep = steps.indexOf(options.status || 'Processing');
            if (currentStep < 0) currentStep = 0;
        }

        if (isCancelled) {
            // Show cancelled/refunded banner instead of progress steps
            var cancelWrap = document.createElement('div');
            cancelWrap.style.cssText = 'margin-top:10px;padding:8px 12px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);border-radius:8px;text-align:center;font-size:11px;color:#f87171;font-weight:600';
            cancelWrap.textContent = st === 'cancelled' ? 'This order has been cancelled' : 'This order has been refunded';
            wrap.appendChild(cancelWrap);
        } else {
            var stepsWrap = document.createElement('div');
            stepsWrap.className = 'cg-order-steps';
            var line = document.createElement('div');
            line.className = 'cg-order-line';
            var lineFill = document.createElement('div');
            lineFill.className = 'cg-order-line-fill';
            if (isPending) {
                lineFill.style.width = '0%';
            } else {
                lineFill.style.width = Math.max(0, (currentStep / (steps.length - 1)) * 100) + '%';
            }
            line.appendChild(lineFill);
            stepsWrap.appendChild(line);

            steps.forEach(function(step, i) {
                var stepEl = document.createElement('div');
                stepEl.className = 'cg-order-step';
                var dot = document.createElement('div');
                dot.className = 'cg-order-dot';
                if (!isPending) {
                    if (i < currentStep) dot.classList.add('done');
                    else if (i === currentStep) dot.classList.add('done', 'current');
                }
                stepEl.appendChild(dot);
                var label = document.createElement('span');
                label.className = 'cg-order-step-label';
                label.textContent = step;
                stepEl.appendChild(label);
                stepsWrap.appendChild(stepEl);
            });

            if (isPending) {
                var pendingNote = document.createElement('div');
                pendingNote.style.cssText = 'text-align:center;font-size:10.5px;color:#fbbf24;margin-top:4px';
                pendingNote.textContent = 'Order received — awaiting confirmation';
                stepsWrap.appendChild(pendingNote);
            }

            wrap.appendChild(stepsWrap);
        }

        // Tracking info
        if (options.tracking_number) {
            var trackInfo = document.createElement('div');
            trackInfo.style.cssText = 'margin-top:10px;font-size:10.5px;color:#94a3b8';
            trackInfo.textContent = (options.carrier || 'Carrier') + ': ' + options.tracking_number;
            wrap.appendChild(trackInfo);
        }
        if (options.estimated_delivery) {
            var eta = document.createElement('div');
            eta.style.cssText = 'font-size:10.5px;color:#4ade80;margin-top:2px';
            eta.textContent = 'Estimated delivery: ' + options.estimated_delivery;
            wrap.appendChild(eta);
        }

        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Render agent card (real estate) ──
    function renderAgentCard(options) {
        var agent = options.agent || options;
        var card = document.createElement('div');
        card.className = 'cg-agent-card';

        var photo = document.createElement('div');
        photo.className = 'cg-agent-photo';
        if (agent.photo) {
            var img = document.createElement('img');
            img.src = agent.photo;
            img.alt = agent.name || '';
            photo.appendChild(img);
        } else {
            photo.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>';
        }
        card.appendChild(photo);

        var info = document.createElement('div');
        info.className = 'cg-agent-info';
        var name = document.createElement('div');
        name.className = 'cg-agent-name';
        name.textContent = agent.name || '';
        info.appendChild(name);
        if (agent.title) {
            var titleEl = document.createElement('div');
            titleEl.className = 'cg-agent-title';
            titleEl.textContent = agent.title;
            info.appendChild(titleEl);
        }
        if (agent.specializations) {
            var spec = document.createElement('div');
            spec.className = 'cg-agent-spec';
            spec.textContent = agent.specializations;
            info.appendChild(spec);
        }

        var contact = document.createElement('div');
        contact.className = 'cg-agent-contact';
        if (agent.phone) {
            var callBtn = document.createElement('button');
            callBtn.className = 'cg-agent-contact-btn cg-product-btn-primary';
            callBtn.textContent = 'Call';
            callBtn.addEventListener('click', function() {
                window.open('tel:' + agent.phone);
            });
            contact.appendChild(callBtn);
        }
        var chatBtn = document.createElement('button');
        chatBtn.className = 'cg-agent-contact-btn cg-product-btn-secondary';
        chatBtn.textContent = 'Message';
        chatBtn.addEventListener('click', function() {
            input.value = 'I want to talk to ' + (agent.name || 'an agent');
            send();
        });
        contact.appendChild(chatBtn);
        info.appendChild(contact);

        card.appendChild(info);
        messages.appendChild(card);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Cart Recovery Banner ──
    function renderCartRecovery(opts) {
        if (!messages) return;
        var banner = document.createElement('div');
        banner.className = 'cg-recovery-banner';

        var text = document.createElement('div');
        text.className = 'cg-recovery-text';
        text.innerHTML = formatMarkdown(opts.message || 'You have items in your cart!');
        banner.appendChild(text);

        // Discount code block
        if (opts.discount_code) {
            var disc = document.createElement('div');
            disc.className = 'cg-recovery-discount';
            var code = document.createElement('div');
            code.className = 'cg-recovery-code';
            code.textContent = opts.discount_code;
            disc.appendChild(code);
            var desc = document.createElement('div');
            desc.className = 'cg-recovery-desc';
            if (opts.discount_type === 'percentage') {
                desc.textContent = opts.discount_value + '% off your order!';
            } else {
                desc.textContent = (opts.currency || '$') + opts.discount_value + ' off your order!';
            }
            disc.appendChild(desc);
            banner.appendChild(disc);
        }

        // Urgency timer countdown
        if (opts.urgency_minutes && opts.urgency_minutes > 0) {
            var timer = document.createElement('div');
            timer.className = 'cg-urgency-timer';
            timer.innerHTML = '<span class="cg-urgency-icon">&#9200;</span><span class="cg-urgency-time"></span><span class="cg-urgency-label">before offer expires</span>';
            banner.appendChild(timer);
            var timeEl = timer.querySelector('.cg-urgency-time');
            var totalSec = opts.urgency_minutes * 60;
            function tick() {
                if (totalSec <= 0) { timeEl.textContent = 'Expired!'; return; }
                var m = Math.floor(totalSec / 60);
                var s = totalSec % 60;
                timeEl.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
                totalSec--;
                setTimeout(tick, 1000);
            }
            tick();
        }

        // Action buttons
        var actions = document.createElement('div');
        actions.className = 'cg-recovery-actions';
        var checkoutBtn = document.createElement('button');
        checkoutBtn.className = 'cg-recovery-btn cg-recovery-btn-primary';
        checkoutBtn.textContent = 'Complete Purchase';
        checkoutBtn.addEventListener('click', function() {
            input.value = 'I want to checkout';
            send();
        });
        actions.appendChild(checkoutBtn);
        var browseBtn = document.createElement('button');
        browseBtn.className = 'cg-recovery-btn cg-recovery-btn-secondary';
        browseBtn.textContent = 'View Cart';
        browseBtn.addEventListener('click', function() {
            input.value = 'View my cart';
            send();
        });
        actions.appendChild(browseBtn);
        banner.appendChild(actions);

        messages.appendChild(banner);
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
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/\*([^*]+)\*/g, '<em>$1</em>')
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(m, text, url) { var safeUrl = /^https?:\/\//i.test(url) ? url : '#'; return '<a href="' + safeUrl + '" target="_blank" rel="noopener">' + text + '</a>'; })
            .replace(/\n/g, '<br>');
    }

    // ── Proactive Engagement Engine ──
    // Bug fix #2: Track cleanup functions for memory leak prevention
    var _proactiveCleanups = [];

    (function initProactive() {
        var PROACTIVE_KEY = 'cg_proactive_triggered_' + ADMIN_ID;
        // Only trigger once per session
        // Bug fix #3: Wrap sessionStorage in try/catch for private browsing
        try { if (sessionStorage.getItem(PROACTIVE_KEY)) return; } catch(e) { /* private browsing - proceed anyway */ }

        fetch(SERVER + '/api/proactive-config/public/' + ADMIN_ID)
            .then(function(resp) { if (resp.ok) return resp.json(); return null; })
            .then(function(cfg) {
                if (!cfg || !cfg.enabled) return;

                var triggered = false;
                var dwellMs = (cfg.dwell_time_seconds || 30) * 1000;
                var scrollPct = cfg.scroll_depth_percent || 60;
                var exitEnabled = cfg.exit_intent_enabled !== false;
                var triggerMsg = cfg.trigger_message || 'Need help? I can assist with booking appointments!';

                function doTrigger() {
                    // Bug fix #1: Check isOpen to avoid race condition with already-open widget
                    if (triggered || isOpen) return;
                    triggered = true;
                    // Bug fix #3: Wrap sessionStorage in try/catch for private browsing
                    try { sessionStorage.setItem(PROACTIVE_KEY, '1'); } catch(e) {}
                    // Bug fix #1: Clean up remaining timers/listeners once triggered
                    cleanupProactive();
                    // Bug fix #4: Null checks on DOM queries within shadow DOM
                    if (!bubble || !win || !badge) return;
                    // Bug fix #3 (race): Re-check isOpen after a short delay before showing message
                    setTimeout(function() {
                        if (isOpen) return;
                        // Open widget
                        isOpen = true;
                        bubble.classList.add('open');
                        win.style.display = 'flex';
                        void win.offsetWidth;
                        win.classList.add('open');
                        win.classList.remove('closing');
                        badge.style.display = 'none';
                        // Show proactive message
                        addMessage(triggerMsg, false);
                    }, 50);
                }

                // Dwell time trigger
                var dwellTimer = setTimeout(function() {
                    doTrigger();
                }, dwellMs);

                // Scroll depth trigger
                function onScroll() {
                    if (triggered) return;
                    var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                    var docHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) - window.innerHeight;
                    if (docHeight <= 0) return;
                    var pct = (scrollTop / docHeight) * 100;
                    if (pct >= scrollPct) {
                        doTrigger();
                    }
                }
                window.addEventListener('scroll', onScroll);

                // Return visit trigger (3+ visits)
                if (_visitCount >= 3 && !triggered) {
                    setTimeout(function() {
                        if (!triggered && !isOpen) {
                            // Override trigger message for return visitors
                            triggerMsg = cfg.return_visit_message || 'Welcome back! Can I help you find something today?';
                            doTrigger();
                        }
                    }, 2000); // Short delay for return visitors
                }

                // Exit intent trigger (desktop only - mouse leaves viewport top)
                var onMouseLeave = null;
                if (exitEnabled) {
                    onMouseLeave = function(e) {
                        if (e.clientY <= 0 && !triggered) {
                            doTrigger();
                        }
                    };
                    document.addEventListener('mouseleave', onMouseLeave);
                }

                // Bug fix #2: Centralized cleanup to prevent memory leaks
                function cleanupProactive() {
                    clearTimeout(dwellTimer);
                    window.removeEventListener('scroll', onScroll);
                    if (onMouseLeave) document.removeEventListener('mouseleave', onMouseLeave);
                }
                _proactiveCleanups.push(cleanupProactive);
            })
            .catch(function() {});
    })();

    // Bug fix #2: Expose proactive cleanup on the widget element for external teardown
    if(shadowHost) shadowHost._cleanupProactive = function() { _proactiveCleanups.forEach(function(fn) { fn(); }); };

    // ── A/B Testing for Greetings ──
    (function initABGreeting() {
        try {
            fetch(SERVER + '/api/ab-greeting/' + ADMIN_ID + '?session=' + sessionId)
                .then(function(r) { if (r.ok) return r.json(); return null; })
                .then(function(data) {
                    if (data && data.message && messages) {
                        // Replace the welcome message with A/B variant
                        var firstMsg = messages.querySelector('.cg-msg-bot');
                        if (firstMsg) {
                            firstMsg.innerHTML = formatMarkdown(data.message);
                        }
                    }
                })
                .catch(function() {});
        } catch(e) {}
    })();

    // ── Lead Capture Form Renderer ──
    function renderLeadForm(formConfig) {
        var container = document.createElement('div');
        container.className = 'cg-lead-form';
        container.style.cssText = 'padding:12px 16px;background:rgba(255,255,255,0.95);backdrop-filter:blur(8px);border-radius:16px;margin:8px 12px;border:1px solid rgba(0,0,0,0.06);';

        var title = formConfig.title || 'Stay in touch';
        var subtitle = formConfig.subtitle || 'Get personalized recommendations sent to you';

        var html = '<div style="font-weight:600;font-size:14px;margin-bottom:4px;color:#1a1a2e;">' + escapeHtml(title) + '</div>';
        html += '<div style="font-size:12px;color:#666;margin-bottom:12px;">' + escapeHtml(subtitle) + '</div>';

        var fields = formConfig.fields || ['email'];
        fields.forEach(function(field) {
            var ph = field === 'email' ? 'Email address' : field === 'phone' ? 'Phone number' : field === 'name' ? 'Your name' : field === 'budget' ? 'Your budget (e.g. $500)' : field;
            var type = field === 'email' ? 'email' : field === 'phone' ? 'tel' : 'text';
            html += '<input class="cg-lead-input" data-field="' + escapeHtml(field) + '" type="' + type + '" placeholder="' + escapeHtml(ph) + '" style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid rgba(0,0,0,0.1);border-radius:10px;font-size:13px;margin-bottom:8px;outline:none;font-family:inherit;background:rgba(255,255,255,0.9);transition:border .2s;" />';
        });

        html += '<button class="cg-lead-submit" style="width:100%;padding:10px;border:none;border-radius:10px;background:' + COLOR + ';color:#fff;font-weight:600;font-size:13px;cursor:pointer;font-family:inherit;transition:opacity .2s;">' + escapeHtml(formConfig.button_text || 'Submit') + '</button>';

        if (formConfig.skip_text !== false) {
            html += '<div class="cg-lead-skip" style="text-align:center;font-size:11px;color:#999;margin-top:6px;cursor:pointer;">No thanks, just browsing</div>';
        }

        container.innerHTML = html;
        messages.appendChild(container);
        messages.scrollTop = messages.scrollHeight;

        // Submit handler
        var submitBtn = container.querySelector('.cg-lead-submit');
        submitBtn.addEventListener('click', function() {
            var data = {};
            var inputs = container.querySelectorAll('.cg-lead-input');
            var valid = true;
            inputs.forEach(function(inp) {
                var val = inp.value.trim();
                if (!val) { valid = false; inp.style.borderColor = '#ef4444'; }
                else { inp.style.borderColor = 'rgba(0,0,0,0.1)'; }
                data[inp.getAttribute('data-field')] = val;
            });
            if (!valid) return;

            submitBtn.textContent = 'Saving...';
            submitBtn.disabled = true;

            fetch(SERVER + '/api/lead-capture', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    admin_id: ADMIN_ID,
                    session_id: sessionId,
                    fields: data
                })
            })
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                container.innerHTML = '<div style="text-align:center;padding:12px;color:#22c55e;font-weight:600;font-size:13px;">Thanks! We\'ll keep you updated.</div>';
                // Send the collected info as a chat message so the AI knows
                var msg = '';
                if (data.name) msg += 'My name is ' + data.name + '. ';
                if (data.email) msg += 'My email is ' + data.email + '. ';
                if (data.phone) msg += 'My phone is ' + data.phone + '. ';
                if (data.budget) msg += 'My budget is ' + data.budget + '.';
                if (msg) {
                    fetch(SERVER + '/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ message: msg.trim(), session_id: sessionId, admin_id: ADMIN_ID, customer_id: CUSTOMER_ID, language: _detectedLang, visit_count: _visitCount, _silent: true })
                    }).catch(function() {});
                }
            })
            .catch(function() {
                submitBtn.textContent = 'Try again';
                submitBtn.disabled = false;
            });
        });

        // Skip handler
        var skipBtn = container.querySelector('.cg-lead-skip');
        if (skipBtn) {
            skipBtn.addEventListener('click', function() {
                container.style.opacity = '0';
                container.style.transition = 'opacity .3s';
                setTimeout(function() { if (container.parentNode) container.remove(); }, 300);
            });
        }
    }

    // ── Scroll Depth Tracking (for analytics) ──
    (function trackScrollDepth() {
        window.addEventListener('scroll', function() {
            var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            var docHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) - window.innerHeight;
            if (docHeight <= 0) return;
            var pct = Math.round((scrollTop / docHeight) * 100);
            if (pct > _maxScrollDepth) _maxScrollDepth = pct;
        });
    })();

    // ── Conversation Drop-off Tracking ──
    // Tracks when user closes widget or leaves page mid-conversation
    (function initDropoffTracking() {
        // Track widget close as potential drop-off
        if (bubble) {
            var origClick = bubble.onclick;
            bubble.addEventListener('click', function() {
                // After the toggle runs, check if widget was just closed
                setTimeout(function() {
                    if (!isOpen && _messageCount > 0) {
                        // User closed widget mid-conversation
                        try {
                            var blob = new Blob([JSON.stringify({
                                admin_id: ADMIN_ID,
                                session_id: sessionId,
                                event: 'widget_closed',
                                message_count: _messageCount,
                                duration_seconds: _chatStartTime ? Math.round((Date.now() - _chatStartTime) / 1000) : 0,
                                scroll_depth: _maxScrollDepth,
                                page_time_seconds: Math.round((Date.now() - _pageLoadTime) / 1000),
                                visit_count: _visitCount,
                                language: _detectedLang
                            })], {type: 'application/json'});
                            navigator.sendBeacon(SERVER + '/api/chat-analytics/event', blob);
                        } catch(e) {}
                    }
                }, 400);
            });
        }

        // Track page unload with conversation data
        window.addEventListener('beforeunload', function() {
            if (_messageCount > 0) {
                try {
                    var blob = new Blob([JSON.stringify({
                        admin_id: ADMIN_ID,
                        session_id: sessionId,
                        event: 'page_leave',
                        message_count: _messageCount,
                        duration_seconds: _chatStartTime ? Math.round((Date.now() - _chatStartTime) / 1000) : 0,
                        scroll_depth: _maxScrollDepth,
                        page_time_seconds: Math.round((Date.now() - _pageLoadTime) / 1000),
                        visit_count: _visitCount,
                        language: _detectedLang,
                        cart_items: _cgCart.length
                    })], {type: 'application/json'});
                    navigator.sendBeacon(SERVER + '/api/chat-analytics/event', blob);
                } catch(e) {}
            }
        });
    })();

    // ── Cart Recovery Exit-Intent Engine ──
    (function initCartRecovery() {
        var CR_KEY = 'cg_cart_recovery_stage_' + ADMIN_ID;
        var _crConfig = null;
        var _crStage = 0;  // 0=not triggered, 1=gentle nudge, 2=discount, 3=last chance
        var _crDiscountCode = null;
        var _crDiscountType = null;
        var _crDiscountValue = 0;
        var _crCurrency = '$';
        var _crCooldown = false;

        try { _crStage = parseInt(sessionStorage.getItem(CR_KEY) || '0', 10); } catch(e) {}

        // Fetch cart recovery config from proactive config
        fetch(SERVER + '/api/proactive-config/public/' + ADMIN_ID)
            .then(function(resp) { if (resp.ok) return resp.json(); return null; })
            .then(function(cfg) {
                if (!cfg || !cfg.cart_recovery || !cfg.cart_recovery.enabled) return;
                _crConfig = cfg.cart_recovery;

                function openWidgetIfNeeded() {
                    if (isOpen) return;
                    if (!bubble || !win || !badge) return;
                    isOpen = true;
                    bubble.classList.add('open');
                    win.style.display = 'flex';
                    void win.offsetWidth;
                    win.classList.add('open');
                    win.classList.remove('closing');
                    badge.style.display = 'none';
                }

                function triggerRecovery() {
                    if (_cgCart.length === 0 || _crCooldown || _crStage >= 3) return;
                    _crCooldown = true;
                    // Cooldown: prevent spam (30 seconds between triggers)
                    setTimeout(function() { _crCooldown = false; }, 30000);

                    _crStage++;
                    try { sessionStorage.setItem(CR_KEY, String(_crStage)); } catch(e) {}

                    openWidgetIfNeeded();

                    setTimeout(function() {
                        if (_crStage === 1) {
                            // Stage 1: Gentle nudge
                            addMessage(_crConfig.recovery_message_1 || 'Wait! You have items in your cart. Don\'t miss out!', false);
                            renderCartRecovery({
                                message: _crConfig.recovery_message_1 || 'You still have items waiting in your cart!',
                            });
                        } else if (_crStage === 2) {
                            // Stage 2: Discount offer — fetch unique code from server
                            if (_crConfig.discount_enabled && !_crDiscountCode) {
                                fetch(SERVER + '/api/cart-recovery/abandon', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({
                                        admin_id: ADMIN_ID,
                                        session_id: sessionId,
                                        cart_items: _cgCart
                                    })
                                })
                                .then(function(r) { return r.json(); })
                                .then(function(d) {
                                    _crDiscountCode = d.discount_code || null;
                                    _crDiscountType = d.discount_type || 'percentage';
                                    _crDiscountValue = d.discount_value || 0;
                                    _crCurrency = d.currency || '$';
                                    renderCartRecovery({
                                        message: _crConfig.recovery_message_2 || 'Still thinking? Here\'s a special discount just for you!',
                                        discount_code: _crDiscountCode,
                                        discount_type: _crDiscountType,
                                        discount_value: _crDiscountValue,
                                        currency: _crCurrency,
                                        urgency_minutes: _crConfig.urgency_timer_enabled ? _crConfig.urgency_timer_duration : 0
                                    });
                                })
                                .catch(function() {
                                    addMessage(_crConfig.recovery_message_2 || 'Still thinking? Complete your purchase now!', false);
                                });
                            } else {
                                renderCartRecovery({
                                    message: _crConfig.recovery_message_2 || 'Still thinking? Complete your purchase now!',
                                    discount_code: _crDiscountCode,
                                    discount_type: _crDiscountType,
                                    discount_value: _crDiscountValue,
                                    currency: _crCurrency || '$',
                                    urgency_minutes: _crConfig.urgency_timer_enabled ? _crConfig.urgency_timer_duration : 0
                                });
                            }
                        } else if (_crStage >= 3) {
                            // Stage 3: Last chance
                            renderCartRecovery({
                                message: _crConfig.recovery_message_3 || 'Last chance! Your cart is about to expire.',
                                discount_code: _crDiscountCode,
                                discount_type: _crDiscountType,
                                discount_value: _crDiscountValue,
                                currency: _crCurrency || '$',
                                urgency_minutes: _crConfig.urgency_timer_enabled ? Math.max(5, Math.floor(_crConfig.urgency_timer_duration / 3)) : 0
                            });
                        }
                    }, 100);
                }

                // Exit intent: mouse leaves viewport top (desktop)
                if (_crConfig.exit_intent_trigger) {
                    document.addEventListener('mouseleave', function(e) {
                        if (e.clientY <= 0) triggerRecovery();
                    });
                }

                // Tab switch trigger (visibilitychange)
                if (_crConfig.tab_switch_trigger) {
                    document.addEventListener('visibilitychange', function() {
                        if (document.hidden) triggerRecovery();
                    });
                }

                // Mobile: back button / beforeunload
                window.addEventListener('beforeunload', function() {
                    if (_cgCart.length > 0 && _crStage === 0) {
                        // Save abandoned cart silently
                        var blob = new Blob([JSON.stringify({
                            admin_id: ADMIN_ID,
                            session_id: sessionId,
                            cart_items: _cgCart
                        })], {type: 'application/json'});
                        navigator.sendBeacon(SERVER + '/api/cart-recovery/abandon', blob);
                    }
                });
            })
            .catch(function() {});
    })();

    // ── Native Cart Integration ──
    // Listen for chatgenius:add_to_cart messages and add to the store's real cart
    window.addEventListener('message', function(e) {
        if (!e.data || e.data.type !== 'chatgenius:add_to_cart') return;
        // Only accept messages from our own widget iframe (same origin or chatgenius host)
        if (e.origin && e.origin !== window.location.origin && e.origin.indexOf('chatgenius') === -1 && e.origin.indexOf(_cgBase.replace(/^https?:\/\//, '').split('/')[0]) === -1) return;
        var productId = e.data.product_id;
        var productName = e.data.product_name || '';
        var qty = e.data.quantity || 1;
        var price = e.data.price || 0;
        var productUrl = e.data.url || '';
        var variantOptions = e.data.variant_options || null;
        if (!productId) return;

        // ── 1. Custom cart URL (configured by store owner) — always takes priority ──
        var _cartAddUrl = (cbCustom && cbCustom.cart_add_url) || '';
        if (_cartAddUrl) {
            try {
                var _finalUrl = _cartAddUrl
                    .replace(/\{product_id\}/g, encodeURIComponent(productId))
                    .replace(/\{quantity\}/g, encodeURIComponent(qty))
                    .replace(/\{price\}/g, encodeURIComponent(price))
                    .replace(/\{product_name\}/g, encodeURIComponent(productName));
                // POST with form-urlencoded content type for broadest platform compatibility
                fetch(_finalUrl, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest'}
                })
                    .then(function(r) {
                        if (r.ok) {
                            try { document.dispatchEvent(new CustomEvent('chatgenius:cart:added', {detail: {product_id: productId, quantity: qty}})); } catch(ex) {}
                        }
                    })
                    .catch(function(){});
            } catch(ex) {}
            return;
        }

        // ── Helper: notify the page via DOM event + onAddToCart callback ──
        var _cartDetail = {product_id: productId, product_name: productName, quantity: qty, price: price, url: productUrl, variant_options: variantOptions};
        function _notifyPage() {
            try { document.dispatchEvent(new CustomEvent('chatgenius:cart:add', {detail: _cartDetail})); } catch(ex) {}
            if (window.ChatGeniusConfig && typeof window.ChatGeniusConfig.onAddToCart === 'function') {
                try { window.ChatGeniusConfig.onAddToCart(_cartDetail); } catch(ex) {}
            }
            if (typeof window.chatGeniusAddToCart === 'function') {
                try { window.chatGeniusAddToCart(_cartDetail); } catch(ex) {}
            }
        }

        // ── 2. Platform-specific fallback (only when store_url is configured) ──
        var _ecomPlatform = (cbCustom && cbCustom.ecom_platform) || '';
        var _storeUrl = (cbCustom && cbCustom.store_url) || '';
        var _cartBase = _storeUrl ? _storeUrl.replace(/\/$/, '') : '';

        if (_cartBase) {
            // Shopify
            if (_ecomPlatform === 'shopify' || window.Shopify) {
                var _handle = '';
                if (productUrl) {
                    var _parts = productUrl.split('/products/');
                    if (_parts.length > 1) _handle = _parts[1].split('?')[0].split('#')[0].replace(/\/$/, '');
                }
                var _fetchUrl = _handle ? (_cartBase + '/products/' + _handle + '.json') : (_cartBase + '/products/' + productId + '.json');
                fetch(_fetchUrl)
                    .then(function(r) { return r.ok ? r.json() : null; })
                    .then(function(d) {
                        if (!d || !d.product || !d.product.variants || !d.product.variants.length) return;
                        return fetch(_cartBase + '/cart/add.js', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({items: [{id: d.product.variants[0].id, quantity: qty}]})
                        });
                    })
                    .then(function(r) {
                        if (r && r.ok) { try { document.dispatchEvent(new CustomEvent('cart:refresh')); } catch(ex) {} }
                    })
                    .catch(function() {
                        fetch(_cartBase + '/cart/add.js', {
                            method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({items: [{id: parseInt(productId), quantity: qty}]})
                        }).catch(function(){});
                    });
                _notifyPage();
                return;
            }

            // WooCommerce
            if (_ecomPlatform === 'woocommerce' || window.wc_add_to_cart_params) {
                fetch(_cartBase + '/?add-to-cart=' + productId + '&quantity=' + qty, {method: 'POST', credentials: 'same-origin'})
                    .then(function() {
                        try { jQuery(document.body).trigger('wc_fragment_refresh'); } catch(ex) {}
                        try { jQuery(document.body).trigger('added_to_cart'); } catch(ex) {}
                    })
                    .catch(function(){});
                _notifyPage();
                return;
            }

            // Magento
            if (_ecomPlatform === 'magento') {
                fetch(_cartBase + '/checkout/cart/add/product/' + productId + '/qty/' + qty + '/', {
                    method: 'POST', credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}
                }).then(function() {
                    try { require(['Magento_Customer/js/customer-data'], function(cd) { cd.reload(['cart'], true); }); } catch(ex) {}
                }).catch(function(){});
                _notifyPage();
                return;
            }

            // BigCommerce
            if (_ecomPlatform === 'bigcommerce' || window.BCData) {
                fetch(_cartBase + '/cart.php', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: 'action=add&product_id=' + productId + '&qty[]=' + qty
                }).catch(function(){});
                _notifyPage();
                return;
            }
        }

        // ── 3. No platform match or no store_url — notify page via callbacks + DOM event ──
        _notifyPage();
    });

    // ── Live Chat Handoff: polling & staff messages ──

    // Ambient poll: slow (8s) background check so widget detects when admin takes over
    function startAmbientPoll() {
        if (_ambientPollTimer || _handoffPollTimer) return;
        _ambientPollTimer = setInterval(pollHandoff, 8000);
    }

    function stopAmbientPoll() {
        if (_ambientPollTimer) { clearInterval(_ambientPollTimer); _ambientPollTimer = null; }
    }

    // Fast poll: 3s when handoff is active
    function startHandoffPolling() {
        stopAmbientPoll(); // switch from slow to fast
        if (_handoffPollTimer) return;
        _handoffPollTimer = setInterval(pollHandoff, 3000);
        pollHandoff(); // immediate first poll
    }

    function stopHandoffPolling() {
        if (_handoffPollTimer) { clearInterval(_handoffPollTimer); _handoffPollTimer = null; }
        _handoffActive = false;
        _handoffStaffName = '';
        _handoffLastMsgId = 0;
        // Reset header subtitle
        var sub = shadow.querySelector('#cg-header-sub');
        if (sub) { sub.innerHTML = '<div id="cg-header-dot"></div> ' + _defaultSubText; }
        // Remove waiting indicator if present
        if (_handoffWaitingEl && _handoffWaitingEl.parentNode) { _handoffWaitingEl.remove(); _handoffWaitingEl = null; }
        // Go back to ambient polling so we detect if admin takes over again
        if (_chatStarted) startAmbientPoll();
    }

    function pollHandoff() {
        fetch(SERVER + '/api/chat/poll?session_id=' + encodeURIComponent(sessionId) + '&admin_id=' + encodeURIComponent(ADMIN_ID) + '&after_id=' + _handoffLastMsgId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            // If handoff ended and no messages
            if (!data.active && !data.messages.length) {
                if (_handoffActive) stopHandoffPolling();
                return;
            }

            // Admin took over — switch to fast polling if not already
            if (data.active && !_handoffActive) {
                _handoffActive = true;
                startHandoffPolling();
            }

            // Update staff name in header
            if (data.staff_name && data.staff_name !== _handoffStaffName) {
                _handoffStaffName = data.staff_name;
                var sub = shadow.querySelector('#cg-header-sub');
                if (sub) {
                    sub.innerHTML = '<div id="cg-header-dot" style="background:#3B82F6;box-shadow:0 0 0 2px rgba(59,130,246,0.2)"></div> ' + escapeHtml(_handoffStaffName) + ' is assisting you';
                }
                // Remove waiting indicator when agent assigned
                if (_handoffWaitingEl && _handoffWaitingEl.parentNode) { _handoffWaitingEl.remove(); _handoffWaitingEl = null; }
            }

            // Display new staff messages (deduplicated)
            if (data.messages && data.messages.length > 0) {
                var hasNew = false;
                data.messages.forEach(function(m) {
                    if (!_shownStaffMsgIds[m.id]) {
                        _shownStaffMsgIds[m.id] = true;
                        // Remove waiting indicator on first staff message
                        if (_handoffWaitingEl && _handoffWaitingEl.parentNode) { _handoffWaitingEl.remove(); _handoffWaitingEl = null; }
                        addStaffMessage(m.text, data.staff_name || 'Support');
                        hasNew = true;
                    }
                    if (m.id > _handoffLastMsgId) _handoffLastMsgId = m.id;
                });
                // Sound notification when widget is closed and new messages arrived
                if (hasNew && !isOpen) { try { playNotifSound(); } catch(e) {} }
            }
        })
        .catch(function() {});
    }

    function addStaffMessage(text, staffName) {
        if (!messages) return;
        var div = document.createElement('div');
        div.className = 'cg-msg cg-msg-staff';
        div.style.animation = getMsgAnimation();
        div.innerHTML = '<div class="cg-staff-badge"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/></svg> ' + escapeHtml(staffName) + '</div>' + formatMarkdown(text);
        messages.appendChild(div);
        requestAnimationFrame(function() { messages.scrollTop = messages.scrollHeight; });
    }

    function showHandoffWaiting() {
        if (!messages) return;
        // Don't duplicate
        if (_handoffWaitingEl && _handoffWaitingEl.parentNode) return;
        var div = document.createElement('div');
        div.className = 'cg-handoff-waiting';
        div.innerHTML = '<div class="cg-hw-dots"><span></span><span></span><span></span></div> Waiting for our team to respond...';
        messages.appendChild(div);
        requestAnimationFrame(function() { messages.scrollTop = messages.scrollHeight; });
        _handoffWaitingEl = div;
    }

    function handleHandoffState(data) {
        if (!data.handoff) {
            if (_handoffActive) stopHandoffPolling();
            return;
        }

        _handoffActive = true;

        if (data.handoff_status === 'queued') {
            showHandoffWaiting();
            startHandoffPolling();
        } else if (data.handoff_status === 'assigned') {
            if (data.staff_name && data.staff_name !== _handoffStaffName) {
                _handoffStaffName = data.staff_name;
                var sub = shadow.querySelector('#cg-header-sub');
                if (sub) {
                    sub.innerHTML = '<div id="cg-header-dot" style="background:#3B82F6;box-shadow:0 0 0 2px rgba(59,130,246,0.2)"></div> ' + escapeHtml(_handoffStaffName) + ' is assisting you';
                }
                if (_handoffWaitingEl && _handoffWaitingEl.parentNode) { _handoffWaitingEl.remove(); _handoffWaitingEl = null; }
            }
            startHandoffPolling();
        }
    }

})();
