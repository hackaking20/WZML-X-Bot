import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'wzml-theme-style' in content:
    print("ALREADY PATCHED: themes exist")
    sys.exit(0)

# ─── Theme CSS for landing.html ───
# landing.html uses different variables: --bg, --line, --line-strong, --deep, --mid, --light, --pale, --text, --muted
theme_css = '''<style id="wzml-theme-style">
/* ═══ Theme System for WZML-X Landing ═══ */

/* ── Dark: Midnight Ocean (default) ── */
[data-theme="dark"] {
  color-scheme: dark;
  --bg: #00000C;
  --line: rgba(93, 157, 255, 0.10);
  --line-strong: rgba(42, 95, 208, 0.55);
  --deep: #16409E;
  --mid: #1A4AB0;
  --light: #3D87FF;
  --pale: #5B9DFF;
  --text: #F5F7FF;
  --muted: #CBD2E5;
  --t-body-before-top: rgba(61, 135, 255, 0.18);
  --t-body-before-bot: rgba(26, 74, 176, 0.35);
  --t-card-bg: linear-gradient(180deg, rgba(1,1,22,.92), rgba(0,0,12,.94));
  --t-card-border: rgba(42, 95, 208, 0.55);
}

/* ── Light: Soft Daylight ── */
[data-theme="light"] {
  color-scheme: light;
  --bg: #eef1f7;
  --line: rgba(42, 95, 208, .08);
  --line-strong: rgba(42, 95, 208, .20);
  --deep: #2563eb;
  --mid: #3b82f6;
  --light: #3D87FF;
  --pale: #60a5fa;
  --text: #1a1d2e;
  --muted: #5a6378;
  --t-body-before-top: rgba(61, 135, 255, .10);
  --t-body-before-bot: rgba(219, 234, 254, .30);
  --t-card-bg: linear-gradient(180deg, rgba(255,255,255,.95), rgba(244,246,251,.90));
  --t-card-border: rgba(42, 95, 208, .20);
}

/* ── Vibrant: Electric Aurora ── */
[data-theme="vibrant"] {
  color-scheme: dark;
  --bg: #0f0c29;
  --line: rgba(168, 85, 247, .12);
  --line-strong: rgba(168, 85, 247, .35);
  --deep: #6d28d9;
  --mid: #7c3aed;
  --light: #a855f7;
  --pale: #c084fc;
  --text: #f0e7ff;
  --muted: #b8a6d9;
  --t-body-before-top: rgba(236, 72, 153, .15);
  --t-body-before-bot: rgba(79, 29, 110, .40);
  --t-card-bg: linear-gradient(180deg, rgba(26,21,56,.92), rgba(15,12,41,.94));
  --t-card-border: rgba(168, 85, 247, .35);
}

/* ── Blossom Pastel ── (light vibrant aesthetic) */
[data-theme="blossom"] {
  color-scheme: light;
  --bg: #fdf2f8;
  --line: rgba(244, 114, 182, .10);
  --line-strong: rgba(244, 114, 182, .25);
  --deep: #db2777;
  --mid: #ec4899;
  --light: #f472b6;
  --pale: #f9a8d4;
  --text: #4a2040;
  --muted: #9d6b8a;
  --t-body-before-top: rgba(251, 207, 232, .30);
  --t-body-before-bot: rgba(221, 214, 254, .30);
  --t-card-bg: linear-gradient(180deg, rgba(255,255,255,.92), rgba(253,244,249,.88));
  --t-card-border: rgba(244, 114, 182, .25);
}

/* Override body backgrounds per theme */
[data-theme="light"] body::before {
  background:
    radial-gradient(55rem 34rem at 50% -12%, var(--t-body-before-top) 0%, transparent 70%),
    radial-gradient(38rem 28rem at 8% 104%, var(--t-body-before-bot) 0%, transparent 70%);
}
[data-theme="light"] .card {
  background: var(--t-card-bg);
  border: 1px solid var(--t-card-border);
  box-shadow: 0 32px 80px -24px rgba(0,0,12,.15);
}
[data-theme="light"] h1 {
  background: linear-gradient(180deg, #1a1d2e 30%, var(--pale) 130%);
  -webkit-background-clip: text;
  background-clip: text;
}

[data-theme="vibrant"] body::before {
  background:
    radial-gradient(55rem 34rem at 50% -12%, var(--t-body-before-top) 0%, transparent 70%),
    radial-gradient(38rem 28rem at 8% 104%, var(--t-body-before-bot) 0%, transparent 70%),
    radial-gradient(40rem 28rem at 90% 20%, rgba(99,102,241,.12) 0%, transparent 70%);
}
[data-theme="vibrant"] .card {
  background: var(--t-card-bg);
  border: 1px solid var(--t-card-border);
  box-shadow: 0 32px 80px -24px rgba(15,12,41,.95);
}
[data-theme="vibrant"] h1 {
  background: linear-gradient(180deg, #f0e7ff 30%, var(--pale) 130%);
  -webkit-background-clip: text;
  background-clip: text;
}
[data-theme="vibrant"] .button .ico {
  color: var(--pale);
  background: rgba(168, 85, 247, .14);
}

[data-theme="blossom"] body::before {
  background:
    radial-gradient(55rem 34rem at 20% -12%, rgba(251,207,232,.30) 0%, transparent 70%),
    radial-gradient(38rem 28rem at 80% 104%, rgba(221,214,254,.30) 0%, transparent 70%),
    radial-gradient(40rem 28rem at 50% 50%, rgba(254,240,232,.15) 0%, transparent 70%);
}
[data-theme="blossom"] .card {
  background: var(--t-card-bg);
  border: 1px solid var(--t-card-border);
  box-shadow: 0 32px 80px -24px rgba(244,114,182,.20);
}
[data-theme="blossom"] h1 {
  background: linear-gradient(180deg, #4a2040 20%, var(--pale) 130%);
  -webkit-background-clip: text;
  background-clip: text;
}
[data-theme="blossom"] .logo {
  box-shadow: 0 18px 44px -14px rgba(244,114,182,.40);
}
[data-theme="blossom"] .button .ico {
  color: var(--pale);
  background: rgba(244,114,182,.12);
}
[data-theme="blossom"] .button:hover {
  border-color: rgba(244,114,182,.30);
  background: rgba(244,114,182,.05);
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
  background: var(--bg);
  border: 1px solid var(--line-strong);
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
.theme-option:hover { background: var(--line); }
.theme-option.active { color: var(--light); font-weight: 700; }
.theme-swatch {
  width: 22px;
  height: 22px;
  border-radius: 7px;
  flex: none;
  border: 1px solid rgba(255,255,255,.15);
}
.sw-dark { background: linear-gradient(135deg, #00000C, #3D87FF); }
.sw-light { background: linear-gradient(135deg, #eef1f7, #3D87FF); }
.sw-vibrant { background: linear-gradient(135deg, #0f0c29, #ec4899, #a855f7); }
.sw-blossom { background: linear-gradient(135deg, #fdf2f8, #f9a8d4, #c4b5fd); }
</style>'''

switcher_html = '''<div class="theme-switcher" id="themeSwitcher">
  <button class="theme-btn" id="themeBtn" title="Switch theme">&#127912;</button>
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
    <button class="theme-option" data-t="blossom">
      <span class="theme-swatch sw-blossom"></span> Blossom
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
  function setBtnColor(){
    var colors = { dark:'#3D87FF', light:'#3D87FF', vibrant:'#ec4899', blossom:'#f9a8d4' };
    btn.style.background = colors[saved] || '#3D87FF';
    btn.style.borderColor = colors[saved] || '#3D87FF';
  }
  setBtnColor();
})();
</script>'''

if '</head>' in content:
    content = content.replace('</head>', theme_css + '\n</head>', 1)
    print("PATCHED: injected theme CSS into <head>")
else:
    content = theme_css + content
    print("PATCHED: prepended theme CSS")

if '</body>' in content:
    content = content.replace('</body>', switcher_html + '\n</body>', 1)
    print("PATCHED: injected theme switcher before </body>")
else:
    content = content + switcher_html
    print("PATCHED: appended theme switcher")

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED landing.html: 4 themes + theme switcher added")
