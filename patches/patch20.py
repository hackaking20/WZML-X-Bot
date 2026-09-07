import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'wzml-x-extras-v2' in content:
    print("ALREADY PATCHED: extras-v2 exist")
    sys.exit(0)

# ─── CSS for v2 features ───
v2_css = '''<style id="wzml-x-extras-v2">
/* ═══ WZML-X Extra Features v2 ═══ */

/* ── PiP Button ── */
.pip-btn {
  background: rgba(0,0,0,.45);
  border: 1px solid rgba(255,255,255,.18);
  color: #fff;
  font-size: 14px;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  transition: all .2s;
}
.pip-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }

/* ── Volume Slider ── */
.vol-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(0,0,0,.45);
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 6px;
  padding: 3px 10px;
}
.vol-wrap span { font-size: 12px; color: #fff; min-width: 36px; text-align: center; }
.vol-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 80px;
  height: 4px;
  border-radius: 4px;
  background: rgba(255,255,255,.25);
  outline: none;
  cursor: pointer;
}
.vol-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #3D87FF;
  cursor: pointer;
}
.vol-slider::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #3D87FF;
  cursor: pointer;
  border: none;
}

/* ── Info Panel ── */
.info-btn {
  background: rgba(0,0,0,.45);
  border: 1px solid rgba(255,255,255,.18);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  transition: all .2s;
}
.info-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }
.info-panel {
  display: none;
  margin-top: 10px;
  background: rgba(0,0,0,.55);
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 12px;
  padding: 16px 20px;
  backdrop-filter: blur(12px);
  font-family: 'Montserrat', sans-serif;
  animation: fadeIn .25s ease;
}
.info-panel.open { display: block; }
.info-panel h4 { color: #fff; font-size: 14px; margin-bottom: 10px; }
.info-panel .info-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 13px;
  color: #ccc;
  border-bottom: 1px solid rgba(255,255,255,.06);
}
.info-panel .info-row:last-child { border-bottom: none; }
.info-panel .info-row .label { color: #999; }
.info-panel .info-row .value { color: #fff; font-weight: 500; }

/* ── Glassmorphism video frame ── */
.wzml-glass-frame {
  position: relative;
}
.wzml-glass-frame::before {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: inherit;
  background: linear-gradient(135deg, rgba(61,135,255,.15), rgba(255,107,157,.10), rgba(0,223,162,.10));
  z-index: -1;
  filter: blur(8px);
  opacity: .8;
  pointer-events: none;
  transition: opacity .3s;
}
.wzml-glass-frame:hover::before { opacity: 1; }

/* ── Animated gradient mesh background ── */
.wzml-mesh-bg {
  position: fixed;
  inset: 0;
  z-index: -2;
  pointer-events: none;
  opacity: .4;
  background:
    radial-gradient(ellipse at 20% 30%, rgba(61,135,255,.12), transparent 50%),
    radial-gradient(ellipse at 80% 70%, rgba(255,107,157,.08), transparent 50%),
    radial-gradient(ellipse at 50% 90%, rgba(0,223,162,.08), transparent 50%);
  animation: meshFloat 20s ease-in-out infinite alternate;
}
[data-theme="light"] ~ .wzml-mesh-bg,
[data-theme="light"] .wzml-mesh-bg {
  opacity: .6;
}
[data-theme="blossom"] ~ .wzml-mesh-bg,
[data-theme="blossom"] .wzml-mesh-bg {
  opacity: .5;
  background:
    radial-gradient(ellipse at 20% 30%, rgba(255,153,204,.15), transparent 50%),
    radial-gradient(ellipse at 80% 70%, rgba(255,200,224,.10), transparent 50%),
    radial-gradient(ellipse at 50% 90%, rgba(200,162,255,.08), transparent 50%);
}
[data-theme="vibrant"] ~ .wzml-mesh-bg,
[data-theme="vibrant"] .wzml-mesh-bg {
  opacity: .7;
  background:
    radial-gradient(ellipse at 20% 30%, rgba(255,0,128,.12), transparent 50%),
    radial-gradient(ellipse at 80% 70%, rgba(0,255,224,.10), transparent 50%),
    radial-gradient(ellipse at 50% 90%, rgba(255,235,59,.08), transparent 50%);
}
@keyframes meshFloat {
  0% { transform: scale(1) rotate(0deg); }
  50% { transform: scale(1.05) rotate(2deg); }
  100% { transform: scale(1) rotate(-2deg); }
}
</style>'''

# ─── HTML for info panel ───
v2_html = '''<div class="info-panel" id="infoPanel">
  <h4>File Info</h4>
  <div class="info-row"><span class="label">Resolution</span><span class="value" id="info-res">-</span></div>
  <div class="info-row"><span class="label">Duration</span><span class="value" id="info-dur">-</span></div>
  <div class="info-row"><span class="label">Current Time</span><span class="value" id="info-cur">-</span></div>
  <div class="info-row"><span class="label">Volume</span><span class="value" id="info-vol">-</span></div>
  <div class="info-row"><span class="label">Playback Rate</span><span class="value" id="info-rate">-</span></div>
  <div class="info-row"><span class="label">Network State</span><span class="value" id="info-net">-</span></div>
</div>'''

# ─── JavaScript for v2 features ───
v2_js = '''<script id="wzml-x-extras-v2-js">
(function(){
  function ready(fn){
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function(){
    var vid = document.getElementById('player');
    if (!vid) { console.warn('[v2] no player found'); return; }

    // ── Toast helper (reuse from v1 if available) ──
    var toastEl = document.getElementById('toast');
    var toastTimer = null;
    function toast(msg){
      if (!toastEl) return;
      toastEl.textContent = msg;
      toastEl.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function(){ toastEl.classList.remove('show'); }, 2000);
    }

    // ── Glassmorphism frame on video ──
    if (vid.parentNode) {
      vid.parentNode.classList.add('wzml-glass-frame');
    }

    // ── Animated mesh background ──
    var mesh = document.createElement('div');
    mesh.className = 'wzml-mesh-bg';
    document.body.insertBefore(mesh, document.body.firstChild);

    // ── Get or create extras bar ──
    var bar = document.getElementById('extrasBar');
    if (!bar) { bar = document.createElement('div'); bar.className = 'extras-bar'; bar.id = 'extrasBar'; vid.parentNode.appendChild(bar); }

    // ── PiP button ──
    var pipBtn = document.createElement('button');
    pipBtn.className = 'pip-btn';
    pipBtn.innerHTML = '\\u{1F4AC}';
    pipBtn.title = 'Picture-in-Picture (press P)';
    pipBtn.onclick = function(){ togglePiP(); };
    bar.appendChild(pipBtn);

    function togglePiP(){
      if (!document.pictureInPictureEnabled) {
        toast('PiP not supported');
        return;
      }
      if (document.pictureInPictureElement) {
        document.exitPictureInPicture().then(function(){ toast('Exited PiP'); }).catch(function(){ toast('PiP exit failed'); });
      } else {
        vid.requestPictureInPicture().then(function(){ toast('PiP on'); }).catch(function(){ toast('PiP failed'); });
      }
    }

    // ── Volume slider ──
    var volWrap = document.createElement('div');
    volWrap.className = 'vol-wrap';
    volWrap.innerHTML = '<span id="volLabel">' + Math.round(vid.volume * 100) + '%</span><input type="range" class="vol-slider" id="volSlider" min="0" max="100" value="' + Math.round(vid.volume * 100) + '">';
    bar.appendChild(volWrap);

    var volSlider = document.getElementById('volSlider');
    var volLabel = document.getElementById('volLabel');
    volSlider.addEventListener('input', function(){
      vid.volume = volSlider.value / 100;
      volLabel.textContent = volSlider.value + '%';
    });
    vid.addEventListener('volumechange', function(){
      var v = Math.round(vid.volume * 100);
      volSlider.value = v;
      volLabel.textContent = v + '%';
    });

    // ── Info button + panel ──
    var infoBtn = document.createElement('button');
    infoBtn.className = 'info-btn';
    infoBtn.textContent = 'Info';
    infoBtn.title = 'Show file info (press I)';
    infoBtn.onclick = function(){ toggleInfo(); };
    bar.appendChild(infoBtn);

    // Insert info panel after the bar
    var infoPanel = document.createElement('div');
    infoPanel.className = 'info-panel';
    infoPanel.id = 'infoPanel';
    infoPanel.innerHTML = '<h4>File Info</h4>' +
      '<div class="info-row"><span class="label">Resolution</span><span class="value" id="info-res">-</span></div>' +
      '<div class="info-row"><span class="label">Duration</span><span class="value" id="info-dur">-</span></div>' +
      '<div class="info-row"><span class="label">Current Time</span><span class="value" id="info-cur">-</span></div>' +
      '<div class="info-row"><span class="label">Volume</span><span class="value" id="info-vol">-</span></div>' +
      '<div class="info-row"><span class="label">Playback Rate</span><span class="value" id="info-rate">-</span></div>' +
      '<div class="info-row"><span class="label">Network State</span><span class="value" id="info-net">-</span></div>';
    bar.parentNode.insertBefore(infoPanel, bar.nextSibling);

    function toggleInfo(){
      if (infoPanel.classList.contains('open')) {
        infoPanel.classList.remove('open');
      } else {
        infoPanel.classList.add('open');
        updateInfo();
      }
    }

    function updateInfo(){
      var resEl = document.getElementById('info-res');
      var durEl = document.getElementById('info-dur');
      var curEl = document.getElementById('info-cur');
      var volEl = document.getElementById('info-vol');
      var rateEl = document.getElementById('info-rate');
      var netEl = document.getElementById('info-net');
      if (resEl) resEl.textContent = (vid.videoWidth && vid.videoHeight) ? vid.videoWidth + 'x' + vid.videoHeight : 'Loading...';
      if (durEl) durEl.textContent = vid.duration ? formatTime(vid.duration) : '-';
      if (curEl) curEl.textContent = formatTime(vid.currentTime);
      if (volEl) volEl.textContent = Math.round(vid.volume * 100) + '%' + (vid.muted ? ' (muted)' : '');
      if (rateEl) rateEl.textContent = vid.playbackRate + 'x';
      if (netEl) {
        var ns = vid.networkState;
        var states = {0: 'Empty', 1: 'Idle', 2: 'Loading', 3: 'No source'};
        netEl.textContent = states[ns] || ns;
      }
    }

    function formatTime(s){
      if (!s || isNaN(s)) return '-';
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      var sec = Math.floor(s % 60);
      if (h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
      return m + ':' + String(sec).padStart(2,'0');
    }

    // Update info periodically when open
    setInterval(function(){
      if (infoPanel.classList.contains('open')) updateInfo();
    }, 1000);

    // ── Keyboard shortcuts for v2 features ──
    document.addEventListener('keydown', function(e){
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      switch(e.key){
        case 'p':
          e.preventDefault();
          togglePiP();
          break;
        case 'i':
          e.preventDefault();
          toggleInfo();
          break;
      }
    });

    console.log('[v2] PiP + volume slider + info panel + glassmorphism + mesh background ready');
  });
})();
</script>'''

# Inject CSS before </head>
if '</head>' in content:
    content = content.replace('</head>', v2_css + '\n</head>', 1)
    print("PATCHED: injected v2 CSS into <head>")
else:
    content = v2_css + content
    print("PATCHED: prepended v2 CSS")

# Inject JS before </body>
if '</body>' in content:
    content = content.replace('</body>', v2_js + '\n</body>', 1)
    print("PATCHED: injected v2 JS before </body>")
else:
    content = content + v2_js
    print("PATCHED: appended v2 JS")

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: PiP + volume slider + info panel + glassmorphism + mesh background")
