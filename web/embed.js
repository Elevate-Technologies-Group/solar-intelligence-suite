/**
 * Solar Intelligence Suite — Embeddable Lead Capture Widget
 * Version 1.0.0
 *
 * Drop ONE script tag on any website to add a Solar Savings Calculator:
 *   <script src="https://your-server/api/widget/embed.js?company=Elevate+Solar&primary=%23FF6B35"></script>
 *
 * URL params (all optional):
 *   company      Company name shown in widget header (default: "Solar Intelligence")
 *   tagline      Subtitle text (default: "Find out how much you could save")
 *   primary      Primary accent color hex, URL-encoded (default: #16a34a)
 *   mode         floating | inline | button (default: floating)
 *   target       CSS selector for inline mount (only used in inline mode)
 *   phone        Rep phone number shown after lead capture
 *   rep          Rep name shown after lead capture
 *   utm_source   UTM tracking (passed through to lead data)
 *   utm_campaign UTM campaign (passed through to lead data)
 */

(function () {
  'use strict';

  // ─── Config from script tag URL params ───────────────────────────────────
  var scriptEl = document.currentScript ||
    (function () {
      var s = document.getElementsByTagName('script');
      return s[s.length - 1];
    })();

  var src = scriptEl ? scriptEl.src : '';
  var baseUrl = src.replace(/\/api\/widget\/embed\.js.*$/, '').replace(/\/web\/embed\.js.*$/, '');
  if (!baseUrl) baseUrl = window.location.origin;

  function urlParam(name, def) {
    try {
      var m = new URL(src).searchParams.get(name);
      return m !== null ? m : def;
    } catch (e) {
      return def;
    }
  }

  var CFG = {
    company:      urlParam('company',      'Solar Intelligence'),
    tagline:      urlParam('tagline',      'Find out how much you could save'),
    primary:      urlParam('primary',      '#16a34a'),
    mode:         urlParam('mode',         'floating'),   // floating | inline | button
    target:       urlParam('target',       ''),
    phone:        urlParam('phone',        ''),
    rep:          urlParam('rep',          ''),
    utm_source:   urlParam('utm_source',   'embed_widget'),
    utm_campaign: urlParam('utm_campaign', ''),
  };

  var API = baseUrl + '/api';

  // ─── Inject styles ────────────────────────────────────────────────────────
  var style = document.createElement('style');
  style.textContent = [
    '#si-widget-root *{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}',
    '#si-fab{position:fixed;bottom:24px;right:24px;z-index:999998;background:' + CFG.primary + ';color:#fff;border:none;border-radius:30px;padding:14px 20px;font-size:15px;font-weight:700;cursor:pointer;box-shadow:0 4px 20px rgba(0,0,0,.25);display:flex;align-items:center;gap:8px;transition:transform .15s,box-shadow .15s}',
    '#si-fab:hover{transform:translateY(-2px);box-shadow:0 6px 28px rgba(0,0,0,.35)}',
    '#si-fab svg{flex-shrink:0}',
    '#si-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:999999;display:flex;align-items:center;justify-content:center;padding:16px;opacity:0;transition:opacity .2s}',
    '#si-overlay.si-show{opacity:1}',
    '#si-modal{background:#111827;color:#f3f4f6;border-radius:16px;width:100%;max-width:480px;padding:28px;position:relative;transform:translateY(20px);transition:transform .25s;box-shadow:0 20px 60px rgba(0,0,0,.6)}',
    '#si-overlay.si-show #si-modal{transform:translateY(0)}',
    '.si-close{position:absolute;top:14px;right:16px;background:none;border:none;color:#9ca3af;font-size:22px;cursor:pointer;line-height:1;padding:4px}',
    '.si-close:hover{color:#fff}',
    '.si-logo{display:flex;align-items:center;gap:10px;margin-bottom:18px}',
    '.si-logo-icon{width:36px;height:36px;background:' + CFG.primary + ';border-radius:8px;display:flex;align-items:center;justify-content:center}',
    '.si-co{font-size:18px;font-weight:700;color:#fff}',
    '.si-tag{font-size:12px;color:#9ca3af;margin-top:2px}',
    '.si-step{display:none}.si-step.si-active{display:block}',
    '.si-label{font-size:13px;color:#9ca3af;margin-bottom:6px;font-weight:500;display:block}',
    '.si-input{width:100%;background:#1f2937;border:1.5px solid #374151;border-radius:8px;color:#f3f4f6;font-size:15px;padding:11px 14px;outline:none;transition:border-color .15s;margin-bottom:12px}',
    '.si-input:focus{border-color:' + CFG.primary + '}',
    '.si-btn{display:inline-block;background:' + CFG.primary + ';color:#fff;border:none;border-radius:8px;padding:12px 20px;font-size:15px;font-weight:700;cursor:pointer;width:100%;margin-top:4px;transition:filter .15s}',
    '.si-btn:hover{filter:brightness(1.12)}',
    '.si-btn:disabled{opacity:.55;cursor:not-allowed}',
    '.si-row{display:flex;gap:10px}.si-row .si-input{margin:0}.si-row .si-label{margin-bottom:6px}',
    '.si-row-wrap{display:flex;gap:10px;margin-bottom:12px}.si-row-wrap>div{flex:1}',
    '.si-spinner{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px 0;gap:16px;color:#9ca3af;font-size:14px}',
    '.si-ring{width:48px;height:48px;border:4px solid #374151;border-top-color:' + CFG.primary + ';border-radius:50%;animation:si-spin 1s linear infinite}',
    '@keyframes si-spin{to{transform:rotate(360deg)}}',
    '.si-score-bar-wrap{background:#374151;border-radius:99px;height:10px;margin:6px 0 14px;overflow:hidden}',
    '.si-score-bar{height:100%;border-radius:99px;transition:width .8s ease;background:' + CFG.primary + '}',
    '.si-stats{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}',
    '.si-stat{background:#1f2937;border-radius:10px;padding:12px 14px}',
    '.si-stat-val{font-size:22px;font-weight:800;color:' + CFG.primary + '}',
    '.si-stat-lbl{font-size:11px;color:#9ca3af;margin-top:2px}',
    '.si-grade{display:inline-flex;align-items:center;gap:6px;background:#1f2937;border-radius:8px;padding:6px 12px;font-size:13px;font-weight:700;color:#fff;margin-bottom:14px}',
    '.si-grade-badge{background:' + CFG.primary + ';border-radius:5px;padding:2px 7px;font-size:12px}',
    '.si-pts{background:#1f2937;border-radius:8px;padding:10px 14px;font-size:12px;color:#d1d5db;margin-bottom:14px}',
    '.si-pts ul{margin:6px 0 0;padding-left:18px}.si-pts ul li{margin-bottom:4px}',
    '.si-pts b{color:#fff}',
    '.si-success{text-align:center;padding:16px 0}',
    '.si-success-icon{font-size:48px;margin-bottom:10px}',
    '.si-success h3{color:#fff;font-size:20px;margin:0 0 8px}',
    '.si-success p{color:#9ca3af;font-size:14px;margin:0 0 16px}',
    '.si-success a{color:' + CFG.primary + ';text-decoration:none;font-weight:700}',
    '.si-err{color:#f87171;font-size:13px;margin-top:4px;display:none}',
    '.si-inline-wrap{background:#111827;border:1.5px solid #374151;border-radius:16px;padding:24px;max-width:480px}',
    '.si-inline-btn{background:' + CFG.primary + ';color:#fff;border:none;border-radius:8px;padding:12px 22px;font-size:15px;font-weight:700;cursor:pointer;transition:filter .15s}',
    '.si-inline-btn:hover{filter:brightness(1.12)}',
    '.si-powered{text-align:center;font-size:11px;color:#4b5563;margin-top:16px}',
    '.si-powered a{color:#4b5563;text-decoration:none}',
  ].join('\n');
  document.head.appendChild(style);

  // ─── Root container ───────────────────────────────────────────────────────
  var root = document.createElement('div');
  root.id = 'si-widget-root';
  document.body.appendChild(root);

  // ─── Solar icon SVG ───────────────────────────────────────────────────────
  var sunSvg = '<svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/><line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/></svg>';
  var sunSvgSmall = '<svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#fff" stroke-width="2.5"><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/><line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/></svg>';

  // ─── Modal HTML ───────────────────────────────────────────────────────────
  function buildModalHTML() {
    return [
      '<button class="si-close" id="si-close-btn" aria-label="Close">&times;</button>',
      '<div class="si-logo">',
        '<div class="si-logo-icon">' + sunSvgSmall + '</div>',
        '<div><div class="si-co">' + escH(CFG.company) + '</div><div class="si-tag">' + escH(CFG.tagline) + '</div></div>',
      '</div>',

      // Step 1 — Address input
      '<div class="si-step si-active" id="si-step-1">',
        '<label class="si-label">Home address</label>',
        '<input class="si-input" id="si-addr" type="text" placeholder="1234 W Main St, Phoenix, AZ 85001" autocomplete="street-address">',
        '<div class="si-row-wrap">',
          '<div><label class="si-label">Monthly electric bill</label>',
          '<input class="si-input" id="si-bill" type="number" placeholder="175" min="50" max="999" value="175"></div>',
        '</div>',
        '<div id="si-step1-err" class="si-err">Please enter a valid address.</div>',
        '<button class="si-btn" id="si-analyze-btn">☀️ Analyze My Home</button>',
        '<div class="si-powered">Powered by <a href="https://github.com/Elevate-Technologies-Group/solar-intelligence-suite" target="_blank">Solar Intelligence Suite</a></div>',
      '</div>',

      // Step 2 — Loading
      '<div class="si-step" id="si-step-2">',
        '<div class="si-spinner">',
          '<div class="si-ring"></div>',
          '<span id="si-loading-msg">Analyzing satellite imagery...</span>',
        '</div>',
      '</div>',

      // Step 3 — Results + lead capture
      '<div class="si-step" id="si-step-3">',
        '<div id="si-results"></div>',
        '<div id="si-capture">',
          '<label class="si-label">Get your personalized savings report</label>',
          '<input class="si-input" id="si-name" type="text" placeholder="Your name">',
          '<div class="si-row-wrap">',
            '<div><input class="si-input" id="si-phone" type="tel" placeholder="Phone number" style="margin:0"></div>',
            '<div><input class="si-input" id="si-email" type="email" placeholder="Email (optional)" style="margin:0"></div>',
          '</div>',
          '<div id="si-cap-err" class="si-err">Please enter your name and phone number.</div>',
          '<button class="si-btn" id="si-submit-btn">📋 Send My Report</button>',
          '<div class="si-powered" style="margin-top:10px">Powered by <a href="https://github.com/Elevate-Technologies-Group/solar-intelligence-suite" target="_blank">Solar Intelligence Suite</a></div>',
        '</div>',
      '</div>',

      // Step 4 — Thank you
      '<div class="si-step" id="si-step-4">',
        '<div class="si-success">',
          '<div class="si-success-icon">🎉</div>',
          '<h3>Your report is on its way!</h3>',
          '<p id="si-ty-msg">One of our solar advisors will follow up shortly with your personalized savings estimate.</p>',
          '<div id="si-rep-info"></div>',
        '</div>',
        '<div class="si-powered">Powered by <a href="https://github.com/Elevate-Technologies-Group/solar-intelligence-suite" target="_blank">Solar Intelligence Suite</a></div>',
      '</div>',
    ].join('');
  }

  // ─── Floating mode ────────────────────────────────────────────────────────
  function mountFloating() {
    // FAB button
    var fab = document.createElement('button');
    fab.id = 'si-fab';
    fab.innerHTML = sunSvg + '<span>☀️ Solar Savings Estimate</span>';
    root.appendChild(fab);

    // Overlay + modal
    var overlay = document.createElement('div');
    overlay.id = 'si-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Solar savings calculator');

    var modal = document.createElement('div');
    modal.id = 'si-modal';
    modal.innerHTML = buildModalHTML();
    overlay.appendChild(modal);
    root.appendChild(overlay);

    // Open/close
    fab.addEventListener('click', function () { openModal(overlay); });
    document.getElementById('si-close-btn').addEventListener('click', function () { closeModal(overlay); });
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(overlay); });

    wireSteps();
  }

  // ─── Inline mode ─────────────────────────────────────────────────────────
  function mountInline() {
    var targetEl = CFG.target ? document.querySelector(CFG.target) : null;
    if (!targetEl) {
      console.warn('[SolarWidget] Inline mode: target "' + CFG.target + '" not found. Falling back to floating.');
      mountFloating();
      return;
    }
    var wrap = document.createElement('div');
    wrap.className = 'si-inline-wrap';
    wrap.innerHTML = buildModalHTML();
    // remove close button in inline mode
    var cb = wrap.querySelector('#si-close-btn');
    if (cb) cb.style.display = 'none';
    targetEl.appendChild(wrap);
    wireSteps();
  }

  // ─── Button mode (replaces a button with modal trigger) ───────────────────
  function mountButton() {
    var overlay = document.createElement('div');
    overlay.id = 'si-overlay';
    var modal = document.createElement('div');
    modal.id = 'si-modal';
    modal.innerHTML = buildModalHTML();
    overlay.appendChild(modal);
    root.appendChild(overlay);

    document.getElementById('si-close-btn').addEventListener('click', function () { closeModal(overlay); });
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(overlay); });

    // Expose global trigger
    window.SolarWidget = { open: function () { openModal(overlay); } };

    wireSteps();
  }

  // ─── Open / Close ─────────────────────────────────────────────────────────
  function openModal(overlay) {
    overlay.style.display = 'flex';
    requestAnimationFrame(function () { overlay.classList.add('si-show'); });
    document.body.style.overflow = 'hidden';
    var addr = document.getElementById('si-addr');
    if (addr) setTimeout(function () { addr.focus(); }, 300);
  }

  function closeModal(overlay) {
    overlay.classList.remove('si-show');
    setTimeout(function () {
      overlay.style.display = 'none';
      document.body.style.overflow = '';
    }, 200);
  }

  // ─── Step wiring ─────────────────────────────────────────────────────────
  var _leadData = null;

  function showStep(n) {
    for (var i = 1; i <= 4; i++) {
      var el = document.getElementById('si-step-' + i);
      if (el) el.classList.toggle('si-active', i === n);
    }
  }

  function wireSteps() {
    // Step 1 → 2 (analyze)
    var analyzeBtn = document.getElementById('si-analyze-btn');
    var addrInput  = document.getElementById('si-addr');
    var billInput  = document.getElementById('si-bill');

    if (addrInput) {
      addrInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { analyzeBtn && analyzeBtn.click(); }
      });
    }

    if (analyzeBtn) {
      analyzeBtn.addEventListener('click', function () {
        var addr = (addrInput && addrInput.value.trim()) || '';
        var errEl = document.getElementById('si-step1-err');
        if (!addr || addr.length < 10) {
          if (errEl) errEl.style.display = 'block';
          return;
        }
        if (errEl) errEl.style.display = 'none';
        analyzeBtn.disabled = true;
        showStep(2);
        doAnalyze(addr, parseFloat(billInput && billInput.value) || 175);
      });
    }

    // Step 3 → 4 (submit lead)
    var submitBtn = document.getElementById('si-submit-btn');
    if (submitBtn) {
      submitBtn.addEventListener('click', function () {
        var name    = (document.getElementById('si-name')  && document.getElementById('si-name').value.trim())  || '';
        var phone   = (document.getElementById('si-phone') && document.getElementById('si-phone').value.trim()) || '';
        var email   = (document.getElementById('si-email') && document.getElementById('si-email').value.trim()) || '';
        var capErr  = document.getElementById('si-cap-err');

        if (!name || !phone) {
          if (capErr) capErr.style.display = 'block';
          return;
        }
        if (capErr) capErr.style.display = 'none';
        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending…';
        doSubmitLead(name, phone, email);
      });
    }
  }

  // ─── Analyze (call API) ───────────────────────────────────────────────────
  var loadingMsgs = [
    'Analyzing satellite imagery...',
    'Computing roof solar potential...',
    'Calculating your savings estimate...',
    'Scoring lead quality...',
  ];
  var _msgTimer = null;
  var _msgIdx = 0;

  function doAnalyze(addr, bill) {
    _msgIdx = 0;
    var msgEl = document.getElementById('si-loading-msg');
    _msgTimer = setInterval(function () {
      _msgIdx = (_msgIdx + 1) % loadingMsgs.length;
      if (msgEl) msgEl.textContent = loadingMsgs[_msgIdx];
    }, 1500);

    var url = API + '/lead/enrich?address=' + encodeURIComponent(addr) + '&monthly_bill=' + bill;

    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        clearInterval(_msgTimer);
        _leadData = data;
        _leadData._address = addr;
        _leadData._bill = bill;
        renderResults(data);
        showStep(3);
      })
      .catch(function (err) {
        clearInterval(_msgTimer);
        // Fall back to estimated results so widget doesn't fail completely
        renderEstimated(addr, bill);
        showStep(3);
      });
  }

  function renderResults(d) {
    var score = d.lead_score || 0;
    var grade = d.lead_grade || '—';
    var priority = d.priority || 'UNKNOWN';
    var savings = d.annual_savings_yr1_usd || 0;
    var payback = d.payback_years || 0;
    var netCost = d.net_cost_usd || 0;
    var kw = d.system_size_kw || 0;
    var pts = d.talking_points || [];
    var scoreColor = score >= 70 ? CFG.primary : (score >= 50 ? '#d97706' : '#dc2626');

    var html = [
      '<div class="si-grade">',
        '<span>Score</span>',
        '<span class="si-grade-badge">' + grade + '</span>',
        '<span style="color:' + scoreColor + ';font-size:20px;font-weight:800">' + score + '/100</span>',
        '<span style="color:#9ca3af">·</span>',
        '<span style="color:' + scoreColor + '">' + priority + '</span>',
      '</div>',
      '<div class="si-score-bar-wrap"><div class="si-score-bar" style="width:0%;background:' + scoreColor + '" id="si-bar"></div></div>',
      '<div class="si-stats">',
        '<div class="si-stat"><div class="si-stat-val">$' + fmt(savings) + '</div><div class="si-stat-lbl">Year 1 savings</div></div>',
        '<div class="si-stat"><div class="si-stat-val">' + (payback ? payback.toFixed(1) + ' yr' : '—') + '</div><div class="si-stat-lbl">Payback period</div></div>',
        '<div class="si-stat"><div class="si-stat-val">$' + fmt(netCost) + '</div><div class="si-stat-lbl">Net cost (after ITC)</div></div>',
        '<div class="si-stat"><div class="si-stat-val">' + (kw ? kw.toFixed(1) + ' kW' : '—') + '</div><div class="si-stat-lbl">System size</div></div>',
      '</div>',
    ];

    if (pts && pts.length) {
      html.push('<div class="si-pts"><b>☀️ Key insights for your home:</b><ul>');
      var shown = pts.slice(0, 3);
      shown.forEach(function (pt) { html.push('<li>' + escH(pt.replace(/^[•\-]\s*/, '')) + '</li>'); });
      html.push('</ul></div>');
    }

    document.getElementById('si-results').innerHTML = html.join('');

    // Animate score bar
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var bar = document.getElementById('si-bar');
        if (bar) bar.style.width = score + '%';
      });
    });
  }

  function renderEstimated(addr, bill) {
    // Generic estimate when API fails (privacy / network issue)
    var estSavings = Math.round(bill * 0.85 * 12);
    var estCost = Math.round(bill * 12 * 6.2);
    var itc = Math.round(estCost * 0.3);
    var net = estCost - itc;
    var payback = parseFloat((net / estSavings).toFixed(1));

    _leadData = { _address: addr, _bill: bill, _estimated: true,
      annual_savings_yr1_usd: estSavings, net_cost_usd: net, payback_years: payback,
      lead_score: 72, lead_grade: 'B', priority: 'WARM', system_size_kw: parseFloat((estCost / 3000).toFixed(1)) };

    var html = [
      '<div class="si-grade"><span>Estimated</span><span class="si-grade-badge">B</span><span style="color:' + CFG.primary + ';font-size:20px;font-weight:800">72/100</span></div>',
      '<div class="si-score-bar-wrap"><div class="si-score-bar" style="width:0%;background:' + CFG.primary + '" id="si-bar"></div></div>',
      '<div class="si-stats">',
        '<div class="si-stat"><div class="si-stat-val">~$' + fmt(estSavings) + '</div><div class="si-stat-lbl">Est. Year 1 savings</div></div>',
        '<div class="si-stat"><div class="si-stat-val">~' + payback + ' yr</div><div class="si-stat-lbl">Est. payback period</div></div>',
        '<div class="si-stat"><div class="si-stat-val">~$' + fmt(net) + '</div><div class="si-stat-lbl">Est. net cost (after ITC)</div></div>',
        '<div class="si-stat"><div class="si-stat-val">30%</div><div class="si-stat-lbl">Federal tax credit</div></div>',
      '</div>',
      '<div class="si-pts"><b>☀️ Based on your $' + bill + '/mo bill:</b><ul>',
        '<li>Most AZ homeowners save 80–95% of their electric bill with solar</li>',
        '<li>The federal ITC gives you 30% off ($' + fmt(itc) + ' on your taxes)</li>',
        '<li>Lock in today\'s rate before utility prices increase further</li>',
      '</ul></div>',
    ].join('');
    document.getElementById('si-results').innerHTML = html;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var bar = document.getElementById('si-bar');
        if (bar) bar.style.width = '72%';
      });
    });
  }

  // ─── Submit lead ──────────────────────────────────────────────────────────
  function doSubmitLead(name, phone, email) {
    var payload = {
      address:      (_leadData && _leadData._address) || '',
      name:         name,
      phone:        phone,
      email:        email,
      monthly_bill: (_leadData && _leadData._bill) || 175,
      lead_score:   (_leadData && _leadData.lead_score) || null,
      lead_grade:   (_leadData && _leadData.lead_grade) || null,
      priority:     (_leadData && _leadData.priority)   || null,
      annual_savings: (_leadData && _leadData.annual_savings_yr1_usd) || null,
      utm_source:   CFG.utm_source,
      utm_campaign: CFG.utm_campaign,
      widget_company: CFG.company,
      estimated:    !!(_leadData && _leadData._estimated),
    };

    fetch(API + '/widget/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        showThankYou(name, data);
      })
      .catch(function () {
        // Still show thank-you even if API fails
        showThankYou(name, {});
      });
  }

  function showThankYou(name, data) {
    var tyMsg = document.getElementById('si-ty-msg');
    if (tyMsg && name) {
      tyMsg.textContent = 'Thanks ' + escH(name.split(' ')[0]) + '! One of our solar advisors will reach out shortly with your personalized savings report.';
    }

    var repInfo = document.getElementById('si-rep-info');
    if (repInfo) {
      var parts = [];
      if (CFG.rep)   parts.push('<strong>' + escH(CFG.rep) + '</strong>');
      if (CFG.phone) parts.push('<a href="tel:' + escH(CFG.phone) + '" style="color:' + CFG.primary + ';text-decoration:none;font-weight:700">' + escH(CFG.phone) + '</a>');
      if (parts.length) {
        repInfo.innerHTML = '<p style="color:#9ca3af;font-size:13px;margin:0">Your advisor: ' + parts.join(' · ') + '</p>';
      }
    }

    showStep(4);
  }

  // ─── Utilities ────────────────────────────────────────────────────────────
  function escH(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function fmt(n) {
    return Math.round(n || 0).toLocaleString();
  }

  // ─── Mount ────────────────────────────────────────────────────────────────
  function mount() {
    if (CFG.mode === 'inline') { mountInline(); }
    else if (CFG.mode === 'button') { mountButton(); }
    else { mountFloating(); }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

})();
