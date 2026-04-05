(function() {
    'use strict';

    // ── Configuration ──
    var cfg = window.ChatGeniusConfig || {};
    var ADMIN_ID = cfg.adminId || '';
    var SERVER = cfg.server || '';
    var COLOR = cfg.color || '#0891b2';
    var TITLE = cfg.title || 'Chat with us';
    var WELCOME = cfg.welcome || 'Hello! How can I help you today?';
    var POSITION = cfg.position || 'right'; // 'right' or 'left'

    if (!ADMIN_ID || !SERVER) {
        console.warn('ChatGenius: adminId and server are required.');
        return;
    }

    // ── Session ──
    var SESSION_KEY = 'cg_session_' + ADMIN_ID;
    var sessionId = localStorage.getItem(SESSION_KEY);
    if (!sessionId) {
        sessionId = 'web_' + ADMIN_ID + '_' + Math.random().toString(36).substr(2, 12);
        localStorage.setItem(SESSION_KEY, sessionId);
    }

    // ── Styles ──
    var css = document.createElement('style');
    css.textContent = [
        '#cg-widget *{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}',
        '#cg-bubble{position:fixed;bottom:24px;' + POSITION + ':24px;width:60px;height:60px;border-radius:50%;background:' + COLOR + ';cursor:pointer;box-shadow:0 4px 20px rgba(0,0,0,0.25);display:flex;align-items:center;justify-content:center;z-index:999999;transition:transform .2s,box-shadow .2s}',
        '#cg-bubble:hover{transform:scale(1.08);box-shadow:0 6px 28px rgba(0,0,0,0.35)}',
        '#cg-bubble svg{width:28px;height:28px;fill:#fff}',
        '#cg-bubble .cg-close{display:none}',
        '#cg-bubble.open .cg-chat-icon{display:none}',
        '#cg-bubble.open .cg-close{display:block}',
        '#cg-badge{position:absolute;top:-2px;right:-2px;background:#ef4444;color:#fff;font-size:11px;font-weight:700;width:20px;height:20px;border-radius:50%;display:none;align-items:center;justify-content:center}',
        '#cg-window{position:fixed;bottom:100px;' + POSITION + ':24px;width:380px;max-width:calc(100vw - 32px);height:520px;max-height:calc(100vh - 140px);background:#0f1117;border:1px solid rgba(255,255,255,0.08);border-radius:16px;box-shadow:0 12px 48px rgba(0,0,0,0.5);z-index:999998;display:none;flex-direction:column;overflow:hidden}',
        '#cg-window.open{display:flex}',
        '#cg-header{background:' + COLOR + ';padding:16px 20px;display:flex;align-items:center;gap:12px;flex-shrink:0}',
        '#cg-header-avatar{width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:18px;color:#fff}',
        '#cg-header-info{flex:1}',
        '#cg-header-title{color:#fff;font-size:15px;font-weight:600}',
        '#cg-header-sub{color:rgba(255,255,255,0.75);font-size:12px}',
        '#cg-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.1) transparent}',
        '#cg-messages::-webkit-scrollbar{width:4px}',
        '#cg-messages::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:4px}',
        '.cg-msg{max-width:82%;padding:10px 14px;border-radius:14px;font-size:13.5px;line-height:1.5;word-wrap:break-word;animation:cgFadeIn .25s ease}',
        '.cg-msg a{color:' + COLOR + '}',
        '.cg-msg-bot{align-self:flex-start;background:#1a1d27;color:#e2e8f0;border-bottom-left-radius:4px}',
        '.cg-msg-user{align-self:flex-end;background:' + COLOR + ';color:#fff;border-bottom-right-radius:4px}',
        '.cg-typing{align-self:flex-start;background:#1a1d27;color:#94a3b8;padding:10px 14px;border-radius:14px;font-size:13px;border-bottom-left-radius:4px}',
        '.cg-typing span{display:inline-block;animation:cgDot 1.4s infinite both}',
        '.cg-typing span:nth-child(2){animation-delay:.2s}',
        '.cg-typing span:nth-child(3){animation-delay:.4s}',
        '@keyframes cgDot{0%,80%,100%{opacity:.3}40%{opacity:1}}',
        '@keyframes cgFadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}',
        '#cg-input-area{padding:12px 16px;border-top:1px solid rgba(255,255,255,0.06);display:flex;gap:8px;background:#0f1117;flex-shrink:0}',
        '#cg-input{flex:1;background:#1a1d27;border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:10px 14px;color:#e2e8f0;font-size:13.5px;outline:none;resize:none;min-height:20px;max-height:80px}',
        '#cg-input::placeholder{color:#64748b}',
        '#cg-input:focus{border-color:' + COLOR + '}',
        '#cg-send{background:' + COLOR + ';border:none;border-radius:10px;width:40px;height:40px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:opacity .15s;flex-shrink:0}',
        '#cg-send:hover{opacity:.85}',
        '#cg-send:disabled{opacity:.4;cursor:default}',
        '#cg-send svg{width:18px;height:18px;fill:#fff}',
        '#cg-powered{text-align:center;padding:6px;font-size:10px;color:#475569;background:#0f1117}',
        '#cg-powered a{color:#64748b;text-decoration:none}',
        '#cg-powered a:hover{color:' + COLOR + '}',
        /* Dropdown styles */
        '.cg-dropdown-wrap{margin:4px 0;max-width:90%;align-self:flex-start}',
        '.cg-dropdown-btn{background:#1a1d27;border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:8px 14px;color:#e2e8f0;font-size:13px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;width:100%;gap:8px}',
        '.cg-dropdown-btn:hover{border-color:' + COLOR + '}',
        '.cg-dropdown-list{display:none;margin-top:4px;border:1px solid rgba(255,255,255,0.08);border-radius:10px;overflow:hidden;background:#1a1d27}',
        '.cg-dropdown-list.open{display:block}',
        '.cg-dd-item{padding:10px 14px;cursor:pointer;font-size:13px;color:#e2e8f0;border-bottom:1px solid rgba(255,255,255,0.04);transition:background .15s}',
        '.cg-dd-item:hover{background:rgba(255,255,255,0.05)}',
        '.cg-dd-item:last-child{border-bottom:none}',
        '.cg-dd-item.selected{background:' + COLOR + '22}',
        /* Calendar styles */
        '.cg-calendar{background:#1a1d27;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:10px;max-width:280px;align-self:flex-start;margin:4px 0}',
        '.cg-cal-nav{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}',
        '.cg-cal-nav button{background:none;border:none;color:#e2e8f0;cursor:pointer;font-size:14px;padding:4px 8px;border-radius:6px}',
        '.cg-cal-nav button:hover{background:rgba(255,255,255,0.05)}',
        '.cg-cal-nav button:disabled{opacity:.3;cursor:default}',
        '.cg-cal-nav span{font-size:13px;font-weight:600;color:#e2e8f0}',
        '.cg-cal-weekdays{display:grid;grid-template-columns:repeat(7,1fr);text-align:center;font-size:11px;color:#64748b;margin-bottom:4px}',
        '.cg-cal-days{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}',
        '.cg-cal-day{background:none;border:none;color:#e2e8f0;font-size:12px;padding:6px;border-radius:8px;cursor:pointer;text-align:center}',
        '.cg-cal-day:hover{background:' + COLOR + '33}',
        '.cg-cal-day.today{border:1px solid ' + COLOR + '}',
        '.cg-cal-day.disabled{color:#334155;cursor:default}',
        '.cg-cal-day.disabled:hover{background:none}',
        '.cg-cal-day.selected{background:' + COLOR + ';color:#fff}',
        '.cg-cal-day.booked{background:#ef4444;color:#fff;font-weight:700}',
        '.cg-cal-day.empty{cursor:default}',
        '@media(max-width:480px){#cg-window{bottom:0;' + POSITION + ':0;width:100%;max-width:100%;height:100%;max-height:100%;border-radius:0}#cg-bubble{bottom:16px;' + POSITION + ':16px}}'
    ].join('\n');
    document.head.appendChild(css);

    // ── Build widget HTML ──
    var widget = document.createElement('div');
    widget.id = 'cg-widget';
    widget.innerHTML = [
        '<div id="cg-bubble">',
        '  <svg class="cg-chat-icon" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>',
        '  <svg class="cg-close" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>',
        '  <div id="cg-badge">1</div>',
        '</div>',
        '<div id="cg-window">',
        '  <div id="cg-header">',
        '    <div id="cg-header-avatar"><svg viewBox="0 0 24 24" width="22" height="22" fill="#fff"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg></div>',
        '    <div id="cg-header-info">',
        '      <div id="cg-header-title">' + escapeHtml(TITLE) + '</div>',
        '      <div id="cg-header-sub">Online — Typically replies instantly</div>',
        '    </div>',
        '  </div>',
        '  <div id="cg-messages"></div>',
        '  <div id="cg-input-area">',
        '    <input type="text" id="cg-input" placeholder="Type a message..." autocomplete="off">',
        '    <button id="cg-send"><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>',
        '  </div>',
        '  <div id="cg-powered">Powered by <a href="https://chatgenius.ai" target="_blank">ChatGenius</a></div>',
        '</div>'
    ].join('');
    document.body.appendChild(widget);

    // ── Elements ──
    var bubble = document.getElementById('cg-bubble');
    var win = document.getElementById('cg-window');
    var messages = document.getElementById('cg-messages');
    var input = document.getElementById('cg-input');
    var sendBtn = document.getElementById('cg-send');
    var badge = document.getElementById('cg-badge');
    var isOpen = false;
    var sending = false;

    // ── Show welcome message ──
    addMessage(WELCOME, false);

    // ── Toggle ──
    bubble.addEventListener('click', function() {
        isOpen = !isOpen;
        bubble.classList.toggle('open', isOpen);
        win.classList.toggle('open', isOpen);
        badge.style.display = 'none';
        if (isOpen) input.focus();
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
        typing.innerHTML = '<span>.</span><span>.</span><span>.</span>';
        messages.appendChild(typing);
        messages.scrollTop = messages.scrollHeight;

        fetch(SERVER + '/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: sessionId, admin_id: parseInt(ADMIN_ID) })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (typing.parentNode) typing.remove();
            addMessage(data.reply || 'Sorry, something went wrong.', false);
            if (data.options) renderOptions(data.options);
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
        div.innerHTML = isUser ? escapeHtml(text) : formatMarkdown(text);
        messages.appendChild(div);
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

        var label = isDoctor ? 'Select Doctor' : isTime ? 'Select Time' : isCancel ? 'Select Appointment' : isConfirm ? 'Confirm' : 'Select';

        var wrap = document.createElement('div');
        wrap.className = 'cg-dropdown-wrap';

        var btn = document.createElement('button');
        btn.className = 'cg-dropdown-btn';
        btn.innerHTML = '<span>' + label + '</span><span style="font-size:10px">&#9660;</span>';
        wrap.appendChild(btn);

        var list = document.createElement('div');
        list.className = 'cg-dropdown-list';

        items.forEach(function(item) {
            var row = document.createElement('div');
            row.className = 'cg-dd-item';
            var display = item.name;
            if (isDoctor) display = 'Dr. ' + item.name + (item.specialty ? ' — ' + item.specialty : '');
            if (isTime && item.booked) display = item.name + ' (Booked — Tap to join waitlist)';
            row.textContent = display;

            row.addEventListener('click', function() {
                list.querySelectorAll('.cg-dd-item').forEach(function(r) { r.classList.remove('selected'); });
                row.classList.add('selected');
                btn.querySelector('span').textContent = item.name;
                list.classList.remove('open');
                btn.classList.remove('open');
                setTimeout(function() {
                    input.value = isConfirm ? item.value : (isCancel ? String(item.index) : item.name);
                    send();
                }, 200);
            });
            list.appendChild(row);
        });

        wrap.appendChild(list);
        btn.addEventListener('click', function() {
            list.classList.toggle('open');
            btn.classList.toggle('open');
        });

        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;

        // Auto-open for small lists
        if (items.length <= 8) {
            list.classList.add('open');
            btn.classList.add('open');
        }
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
