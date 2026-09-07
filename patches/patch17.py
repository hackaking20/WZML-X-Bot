import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'wzml-theme-style' in content:
    print("ALREADY PATCHED: themes exist")
    sys.exit(0)

# ─── Theme CSS ───
# Inject before </head>
theme_css = '''<style id="wzml-theme-style">
/* ═══ Theme System: 4 Beautiful Themes ═══ */

/* ── Dark: Midnight Ocean (default) ── */
[data-theme="dark"] {
  --bg: #000003;
  --surface: #04040B;
  --surface-2: #07070F;
  --line: rgba(42, 95, 208, .28);
  --line-2: #2A5FD0;
  --text: #F5F7FF;
  --muted: #C3CBDF;
  --accent: #3D87FF;
  --accent-2: #5B9DFF;
  --accent-soft: #06153F;
  --t-glyph: #04081a;
  --t-veil-grid: rgba(42, 95, 208, .13);
  --t-veil-top: rgba(61, 135, 255, .1);
  --t-veil-bot: rgba(6, 21, 63, .55);
  --t-spot-grid: rgba(245, 247, 255, .16);
  --t-card-bg: linear-gradient(180deg, rgba(1,1,22,.92), rgba(0,0,12,.94));
  --t-card-border: rgba(42, 95, 208, .55);
}

/* ── Light: Soft Daylight ── */
[data-theme="light"] {
  --bg: #eef1f7;
  --surface: #ffffff;
  --surface-2: #f4f6fb;
  --line: rgba(42, 95, 208, .14);
  --line-2: #5B9DFF;
  --text: #1a1d2e;
  --muted: #5a6378;
  --accent: #3D87FF;
  --accent-2: #2563eb;
  --accent-soft: #dbeafe;
  --t-glyph: #c7d2fe;
  --t-veil-grid: rgba(42, 95, 208, .06);
  --t-veil-top: rgba(61, 135, 255, .08);
  --t-veil-bot: rgba(219, 234, 254, .4);
  --t-spot-grid: rgba(42, 95, 208, .10);
  --t-card-bg: linear-gradient(180deg, rgba(255,255,255,.95), rgba(244,246,251,.90));
  --t-card-border: rgba(42, 95, 208, .20);
}

/* ── Vibrant: Electric Aurora ── */
[data-theme="vibrant"] {
  --bg: #0f0c29;
  --surface: #1a1538;
  --surface-2: #221b48;
  --line: rgba(168, 85, 247, .22);
  --line-2: #a855f7;
  --text: #f0e7ff;
  --muted: #b8a6d9;
  --accent: #ec4899;
  --accent-2: #f472b6;
  --accent-soft: #4a1d6e;
  --t-glyph: #2a1a4a;
  --t-veil-grid: rgba(168, 85, 247, .12);
  --t-veil-top: rgba(236, 72, 153, .10);
  --t-veil-bot: rgba(79, 29, 110, .50);
  --t-spot-grid: rgba(244, 114, 182, .18);
  --t-card-bg: linear-gradient(180deg, rgba(26,21,56,.92), rgba(15,12,41,.94));
  --t-card-border: rgba(168, 85, 247, .35);
}

/* ── Ananya: Blossom Pastel ── (light vibrant aesthetic) */
[data-theme="ananya"] {
  --bg: #fdf2f8;
  --surface: #ffffff;
  --surface-2: #fdf4f9;
  --line: rgba(244, 114, 182, .16);
  --line-2: #f9a8d4;
  --text: #4a2040;
  --muted: #9d6b8a;
  --accent: #ec4899;
  --accent-2: #f472b6;
  --accent-soft: #fce7f3;
  --t-glyph: #fbcfe8;
  --t-veil-grid: rgba(244, 114, 182, .08);
  --t-veil-top: rgba(251, 207, 232, .25);
  --t-veil-bot: rgba(221, 214, 254, .30);
  --t-spot-grid: rgba(236, 72, 153, .10);
  --t-card-bg: linear-gradient(180deg, rgba(255,255,255,.92), rgba(253,244,249,.88));
  --t-card-border: rgba(244, 114, 182, .25);
}

/* ── Override backgrounds for each theme ── */
[data-theme="light"] .veil,
[data-theme="light"] body {
  background: var(--bg);
}
[data-theme="light"] .veil {
  background:
    linear-gradient(var(--t-veil-grid) 1px, transparent 1px) 50% / 13px 13px,
    linear-gradient(90deg, var(--t-veil-grid) 1px, transparent 1px) 50% / 13px 13px,
    radial-gradient(circle at 50% 12%, var(--t-veil-top), transparent 26%),
    radial-gradient(circle at 50% 94%, var(--t-veil-bot), transparent 44%);
}
[data-theme="light"] .glyph { color: var(--t-glyph); filter: drop-shadow(0 0 42px rgba(0,0,3,.15)); }

[data-theme="vibrant"] .veil {
  background:
    linear-gradient(var(--t-veil-grid) 1px, transparent 1px) 50% / 13px 13px,
    linear-gradient(90deg, var(--t-veil-grid) 1px, transparent 1px) 50% / 13px 13px,
    radial-gradient(circle at 30% 20%, rgba(236,72,153,.12), transparent 30%),
    radial-gradient(circle at 70% 80%, rgba(99,102,241,.12), transparent 30%),
    radial-gradient(circle at 50% 94%, var(--t-veil-bot), transparent 44%);
}
[data-theme="vibrant"] .glyph { color: var(--t-glyph); filter: drop-shadow(0 0 42px rgba(15,12,41,.95)); }
[data-theme="vibrant"] .glyph::before {
  background:
    radial-gradient(circle at 40% 25%, rgba(244,114,182,.3), transparent 34%),
    radial-gradient(circle at 60% 75%, rgba(168,85,247,.15), transparent 36%),
    linear-gradient(rgba(240,231,255,.13), rgba(240,231,255,.03));
}

[data-theme="ananya"] .veil,
[data-theme="ananya"] body {
  background: var(--bg);
}
[data-theme="ananya"] .veil {
  background:
    linear-gradient(var(--t-veil-grid) 1px, transparent 1px) 50% / 13px 13px,
    linear-gradient(90deg, var(--t-veil-grid) 1px, transparent 1px) 50% / 13px 13px,
    radial-gradient(circle at 20% 15%, rgba(251,207,232,.35), transparent 35%),
    radial-gradient(circle at 80% 85%, rgba(221,214,254,.35), transparent 35%),
    radial-gradient(circle at 50% 50%, rgba(254,240,232,.20), transparent 40%);
}
[data-theme="ananya"] .glyph { color: var(--t-glyph); filter: drop-shadow(0 0 42px rgba(252,231,243,.40)); opacity: .55; }
[data-theme="ananya"] .glyph::before {
  background:
    radial-gradient(circle at 40% 25%, rgba(244,114,182,.25), transparent 34%),
    radial-gradient(circle at 60% 75%, rgba(196,181,253,.20), transparent 36%),
    linear-gradient(rgba(253,242,248,.15), rgba(253,242,248,.05));
}
[data-theme="ananya"] .glyph::after {
  color: rgba(157,107,138,.15);
  text-shadow: 0 0 18px rgba(244,114,182,.15), 0 0 60px rgba(253,242,248,.60);
}

/* ── Theme Switcher UI ── */
.theme-switcher {
  position: fixed;
  bottom: 14px;
  right: 14px;
  z-index: 9999;
  font-family: 'Montserrat', system-ui, sans-serif;
}
.theme-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,.25);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: all .3s cubic-bezier(.16,1,.3,1);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 20px rgba(0,0,0,.2);
}
.theme-btn:hover { transform: scale(1.1); border-color: rgba(255,255,255,.5); }
.theme-panel {
  position: absolute;
  bottom: 54px;
  right: 0;
  background: var(--surface);
  border: 1px solid var(--line-2);
  border-radius: 16px;
  padding: 10px;
  display: none;
  flex-direction: column;
  gap: 6px;
  min-width: 180px;
  box-shadow: 0 12px 40px rgba(0,0,0,.3);
  backdrop-filter: blur(20px);
}
.theme-panel.open { display: flex; }
.theme-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  cursor: pointer;
  border: none;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  transition: background .2s;
  text-align: left;
  width: 100%;
}
.theme-option:hover { background: var(--accent-soft); }
.theme-option.active { background: var(--accent-soft); color: var(--accent); font-weight: 700; }
.theme-swatch {
  width: 22px;
  height: 22px;
  border-radius: 7px;
  flex: none;
  border: 1px solid rgba(255,255,255,.15);
}
.sw-dark { background: linear-gradient(135deg, #000003, #3D87FF); }
.sw-light { background: linear-gradient(135deg, #eef1f7, #3D87FF); }
.sw-vibrant { background: linear-gradient(135deg, #0f0c29, #ec4899, #a855f7); }
.sw-ananya { background: linear-gradient(135deg, #fdf2f8, #f9a8d4, #c4b5fd); }
</style>'''

# ─── Theme Switcher HTML + JS ───
# Inject before </body>
switcher_html = '''<div class="theme-switcher" id="themeSwitcher">
  <button class="theme-btn" id="themeBtn" title="Switch theme">🎨</button>
  <div class="theme-panel" id="themePanel">
    <button class="theme-option" data-t="dark">
      <span class="theme-swatch sw-dark"></span> Midnight Ocean
    </button>
    <button class="theme-option" data-t="light">
      <span class="theme-swatch sw-light"></span> Soft Daylight
    </button>
    <button class="theme-option" data-t="vibrant">
      <span class="theme-swatch sw-vibrant"></span> Electric Aurora
    </button>
    <button class="theme-option" data-t="ananya">
      <span class="theme-swatch sw-ananya"></span> Blossom (Ananya)
    </button>
  </div>
</div>
<script>
(function(){
  var saved = localStorage.getItem('wzml-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  function updateActive(){
    document.querySelectorAll('.theme-option').forEach(function(o){
      o.classList.toggle('active', o.dataset.t === saved);
    });
  }
  updateActive();
  var btn = document.getElementById('themeBtn');
  var panel = document.getElementById('themePanel');
  btn.addEventListener('click', function(e){
    e.stopPropagation();
    panel.classList.toggle('open');
  });
  document.addEventListener('click', function(){ panel.classList.remove('open'); });
  panel.addEventListener('click', function(e){ e.stopPropagation(); });
  document.querySelectorAll('.theme-option').forEach(function(o){
    o.addEventListener('click', function(){
      saved = o.dataset.t;
      document.documentElement.setAttribute('data-theme', saved);
      localStorage.setItem('wzml-theme', saved);
      updateActive();
      panel.classList.remove('open');
    });
  });
  // Set swatch button color to current theme
  function setBtnColor(){
    var t = saved;
    var colors = {
      dark: '#3D87FF', light: '#3D87FF', vibrant: '#ec4899', ananya: '#f9a8d4'
    };
    btn.style.background = colors[t] || '#3D87FF';
    btn.style.borderColor = colors[t] || '#3D87FF';
  }
  setBtnColor();
  var origSet = localStorage.setItem.bind(localStorage);
  localStorage.setItem = function(k,v){
    origSet(k,v);
    if(k==='wzml-theme'){ saved=v; setBtnColor(); updateActive(); }
  };
})();
</script>'''

# Inject CSS before </head>
if '</head>' in content:
    content = content.replace('</head>', theme_css + '\n</head>', 1)
    print("PATCHED: injected theme CSS into <head>")
else:
    content = theme_css + content
    print("PATCHED: prepended theme CSS (no </head> found)")

# Inject switcher before </body>
if '</body>' in content:
    content = content.replace('</body>', switcher_html + '\n</body>', 1)
    print("PATCHED: injected theme switcher before </body>")
else:
    content = content + switcher_html
    print("PATCHED: appended theme switcher (no </body> found)")

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: 4 themes added (Dark, Light, Vibrant, Ananya) + theme switcher")
