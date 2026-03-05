/**
 * AIMPACT+ Widget Loader
 * Embed: <script src="https://lk.navilet.ru/widget-loader.js" data-assistant-id="UUID"></script>
 */
(function() {
  'use strict';
  var script = document.currentScript || document.querySelector('script[data-assistant-id]');
  if (!script) return;
  var assistantId = script.getAttribute('data-assistant-id');
  if (!assistantId) { console.error('AIMPACT: data-assistant-id is required'); return; }

  var origin;
  try { origin = new URL(script.src).origin; } catch(e) { origin = 'https://lk.navilet.ru'; }

  var configUrl = origin + '/api/widget/config?assistant_id=' + assistantId;
  var embedUrl = origin + '/widget/embed/' + assistantId;

  var cfg = { primary_color: '#6366f1', position: 'bottom-right' };
  var isOpen = false;
  var isReady = false;
  var launcher, iframe, overlay;

  function darken(hex, amt) {
    hex = hex.replace('#','');
    var r = Math.max(0, parseInt(hex.substring(0,2),16) - amt);
    var g = Math.max(0, parseInt(hex.substring(2,4),16) - amt);
    var b = Math.max(0, parseInt(hex.substring(4,6),16) - amt);
    return '#' + [r,g,b].map(function(c){return c.toString(16).padStart(2,'0')}).join('');
  }

  function isMobile() { return window.innerWidth <= 480; }

  function injectStyles() {
    var style = document.createElement('style');
    style.textContent = [
      '.aimpact-launcher{position:fixed;bottom:24px;z-index:2147483646;width:60px;height:60px;border-radius:50%;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#fff;box-shadow:0 4px 20px rgba(0,0,0,0.25);transition:all .3s cubic-bezier(.4,0,.2,1);animation:aimpact-pulse 2s infinite}',
      '.aimpact-launcher:hover{transform:scale(1.08)}',
      '.aimpact-launcher.active{animation:none}',
      '.aimpact-launcher svg{width:26px;height:26px;transition:all .3s}',
      '.aimpact-launcher .ai-icon-open{opacity:1;transform:scale(1)}',
      '.aimpact-launcher .ai-icon-close{position:absolute;opacity:0;transform:scale(.5) rotate(-90deg)}',
      '.aimpact-launcher.active .ai-icon-open{opacity:0;transform:scale(.5) rotate(90deg)}',
      '.aimpact-launcher.active .ai-icon-close{opacity:1;transform:scale(1) rotate(0)}',
      '@keyframes aimpact-pulse{0%,100%{box-shadow:0 0 0 0 rgba(99,102,241,.5)}50%{box-shadow:0 0 0 14px rgba(99,102,241,0)}}',
      '.aimpact-frame{position:fixed;bottom:100px;z-index:2147483645;width:400px;height:620px;max-height:calc(100vh - 120px);border:none;border-radius:16px;box-shadow:0 8px 40px rgba(0,0,0,0.2);opacity:0;visibility:hidden;transform:translateY(20px) scale(.95);transition:all .3s cubic-bezier(.4,0,.2,1);background:#fff}',
      '.aimpact-frame.open{opacity:1;visibility:visible;transform:translateY(0) scale(1)}',
      '.aimpact-overlay{display:none;position:fixed;inset:0;z-index:2147483644;background:rgba(0,0,0,.4)}',
      '@media(max-width:480px){',
      '  .aimpact-frame.open{bottom:0!important;left:0!important;right:0!important;width:100%!important;height:100%!important;max-height:100vh!important;border-radius:0}',
      '  .aimpact-launcher.active{display:none}',
      '  .aimpact-overlay.show{display:block}',
      '}'
    ].join('\n');
    document.head.appendChild(style);
  }

  function createLauncher() {
    launcher = document.createElement('button');
    launcher.className = 'aimpact-launcher';
    launcher.setAttribute('aria-label', 'Открыть чат');
    launcher.innerHTML = '<svg class="ai-icon-open" viewBox="0 0 24 24" fill="none"><path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2ZM20 16H5.17L4 17.17V4H20V16Z" fill="currentColor"/><path d="M7 9H17V11H7V9ZM7 6H17V8H7V6ZM7 12H14V14H7V12Z" fill="currentColor"/></svg><svg class="ai-icon-close" viewBox="0 0 24 24" fill="none"><path d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12L19 6.41Z" fill="currentColor"/></svg>';
    applyPosition(launcher, 'launcher');
    applyColor();
    document.body.appendChild(launcher);
    launcher.addEventListener('click', toggle);
  }

  function createIframe() {
    iframe = document.createElement('iframe');
    iframe.className = 'aimpact-frame';
    iframe.src = embedUrl;
    iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox');
    iframe.setAttribute('allow', 'clipboard-write');
    applyPosition(iframe, 'iframe');
    document.body.appendChild(iframe);

    overlay = document.createElement('div');
    overlay.className = 'aimpact-overlay';
    overlay.addEventListener('click', close);
    document.body.appendChild(overlay);
  }

  function applyPosition(el, type) {
    var isLeft = cfg.position === 'bottom-left';
    if (type === 'launcher') {
      el.style.right = isLeft ? 'auto' : '24px';
      el.style.left = isLeft ? '24px' : 'auto';
    } else {
      el.style.right = isLeft ? 'auto' : '24px';
      el.style.left = isLeft ? '24px' : 'auto';
    }
  }

  function applyColor() {
    var c = cfg.primary_color;
    launcher.style.background = 'linear-gradient(135deg, '+c+' 0%, '+darken(c,30)+' 100%)';
    var shadow = hexToRgba(c, 0.5);
    var style = document.querySelector('.aimpact-launcher');
    if (style) {
      var sheets = document.styleSheets;
      for (var i = 0; i < sheets.length; i++) {
        try {
          var rules = sheets[i].cssRules;
          for (var j = 0; j < rules.length; j++) {
            if (rules[j].name === 'aimpact-pulse') {
              rules[j].deleteRule(0); rules[j].deleteRule(0);
              rules[j].appendRule('0%,100%{box-shadow:0 0 0 0 '+shadow+'}');
              rules[j].appendRule('50%{box-shadow:0 0 0 14px '+hexToRgba(c,0)+'}');
            }
          }
        } catch(e) {}
      }
    }
  }

  function hexToRgba(hex, alpha) {
    hex = hex.replace('#','');
    var r = parseInt(hex.substring(0,2),16);
    var g = parseInt(hex.substring(2,4),16);
    var b = parseInt(hex.substring(4,6),16);
    return 'rgba('+r+','+g+','+b+','+alpha+')';
  }

  function open() {
    if (isOpen) return;
    isOpen = true;
    if (!iframe) createIframe();
    iframe.classList.add('open');
    launcher.classList.add('active');
    if (isMobile()) overlay.classList.add('show');
    if (isReady) iframe.contentWindow.postMessage({type:'aimpact:open'}, '*');
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    if (iframe) iframe.classList.remove('open');
    launcher.classList.remove('active');
    if (overlay) overlay.classList.remove('show');
  }

  function toggle() { isOpen ? close() : open(); }

  function destroy() {
    if (iframe) { iframe.remove(); iframe = null; }
    if (launcher) { launcher.remove(); launcher = null; }
    if (overlay) { overlay.remove(); overlay = null; }
    window.removeEventListener('message', onMessage);
    delete window.AimpactWidget;
  }

  function onMessage(e) {
    if (!e.data || typeof e.data.type !== 'string') return;
    if (e.data.type === 'aimpact:ready') { isReady = true; }
    else if (e.data.type === 'aimpact:close') { close(); }
  }

  window.addEventListener('message', onMessage);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && isOpen) close();
  });

  window.AimpactWidget = { open: open, close: close, toggle: toggle, destroy: destroy };

  async function loadAndInit() {
    try {
      var resp = await fetch(configUrl);
      if (resp.ok) {
        var data = await resp.json();
        if (data.primary_color) cfg.primary_color = data.primary_color;
        if (data.position) cfg.position = data.position;
      }
    } catch(e) {
      console.warn('AIMPACT: config load failed, using defaults');
    }
    injectStyles();
    createLauncher();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadAndInit);
  } else {
    loadAndInit();
  }
})();
