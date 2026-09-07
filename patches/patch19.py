import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'wzml-x-extras' in content:
    print("ALREADY PATCHED: extras exist")
    sys.exit(0)

# ─── CSS for extra features ───
extra_css = '''<style id="wzml-x-extras">
/* ═══ WZML-X Extra Features ═══ */

/* ── Speed Control ── */
.speed-btn {
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
.speed-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }

/* ── Snapshot Button ── */
.snap-btn {
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
.snap-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }

/* ── Copy Link Button ── */
.copy-btn {
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
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.copy-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }

/* ── Extra Controls Bar ── */
.extras-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  margin-top: 8px;
  flex-wrap: wrap;
}

/* ── QR Code Modal ── */
.qr-modal {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0,0,0,.75);
  backdrop-filter: blur(8px);
  align-items: center;
  justify-content: center;
}
.qr-modal.open { display: flex; }
.qr-box {
  background: #fff;
  border-radius: 16px;
  padding: 24px;
  text-align: center;
  box-shadow: 0 24px 80px rgba(0,0,0,.5);
}
.qr-box img, .qr-box canvas {
  border-radius: 8px;
  margin: 0 auto 12px;
  display: block;
}
.qr-box p {
  color: #333;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 16px;
  font-family: 'Montserrat', sans-serif;
}
.qr-close {
  background: #3D87FF;
  color: #fff;
  border: none;
  padding: 8px 20px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
  font-family: 'Montserrat', sans-serif;
}
.qr-close:hover { background: #2a5fd0; }

/* ── Toast Notification ── */
.toast {
  position: fixed;
  bottom: 70px;
  left: 50%;
  transform: translateX(-50%) translateY(20px);
  background: rgba(0,0,0,.85);
  color: #fff;
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  font-family: 'Montserrat', sans-serif;
  z-index: 10001;
  opacity: 0;
  transition: all .3s cubic-bezier(.16,1,.3,1);
  pointer-events: none;
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255,255,255,.12);
}
.toast.show {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

/* ── Shortcut Hint Overlay ── */
.shortcut-hint {
  display: none;
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 10002;
  background: rgba(0,0,0,.88);
  border: 1px solid rgba(255,255,255,.15);
  border-radius: 16px;
  padding: 24px 28px;
  backdrop-filter: blur(16px);
  font-family: 'Montserrat', sans-serif;
  animation: fadeIn .3s ease;
}
.shortcut-hint.open { display: block; }
.shortcut-hint h3 {
  color: #fff;
  font-size: 16px;
  margin-bottom: 14px;
  text-align: center;
}
.shortcut-hint .row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 5px 0;
  color: #ccc;
  font-size: 13px;
}
.shortcut-hint .key {
  background: rgba(255,255,255,.1);
  border: 1px solid rgba(255,255,255,.2);
  border-radius: 5px;
  padding: 2px 8px;
  font-family: monospace;
  font-size: 12px;
  color: #fff;
  min-width: 28px;
  text-align: center;
}
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>'''

# ─── HTML for extra controls ───
extra_html = '''<div class="extras-bar" id="extrasBar"></div>
<div class="qr-modal" id="qrModal">
  <div class="qr-box">
    <div id="qrCanvas"></div>
    <p>Scan to open on another device</p>
    <button class="qr-close" id="qrClose">Close</button>
  </div>
</div>
<div class="shortcut-hint" id="shortcutHint">
  <h3>Keyboard Shortcuts</h3>
  <div class="row"><span>Play / Pause</span><span class="key">Space</span></div>
  <div class="row"><span>Seek 10s back / forward</span><span class="key">&larr; &rarr;</span></div>
  <div class="row"><span>Volume up / down</span><span class="key">&uarr; &darr;</span></div>
  <div class="row"><span>Fullscreen</span><span class="key">F</span></div>
  <div class="row"><span>Mute</span><span class="key">M</span></div>
  <div class="row"><span>Playback speed</span><span class="key">S</span></div>
  <div class="row"><span>Snapshot</span><span class="key">D</span></div>
  <div class="row"><span>Copy link</span><span class="key">C</span></div>
  <div class="row"><span>Show / hide shortcuts</span><span class="key">?</span></div>
</div>
<div class="toast" id="toast"></div>'''

# ─── JavaScript for all features ───
extra_js = '''<script id="wzml-x-extras-js">
(function(){
  function ready(fn){
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function(){
    var vid = document.getElementById('player');
    if (!vid) { console.warn('[extras] no player found'); return; }

    // ── Toast helper ──
    var toastEl = document.getElementById('toast');
    var toastTimer = null;
    function toast(msg){
      if (!toastEl) return;
      toastEl.textContent = msg;
      toastEl.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function(){ toastEl.classList.remove('show'); }, 2000);
    }

    // ── Build extra controls bar ──
    var bar = document.getElementById('extrasBar');
    if (!bar) { bar = document.createElement('div'); bar.className = 'extras-bar'; bar.id = 'extrasBar'; vid.parentNode.appendChild(bar); }

    // Speed button
    var speeds = [0.5, 1, 1.5, 2];
    var speedIdx = 1;
    var speedBtn = document.createElement('button');
    speedBtn.className = 'speed-btn';
    speedBtn.textContent = '1x';
    speedBtn.title = 'Playback speed (press S)';
    speedBtn.onclick = function(){ cycleSpeed(); };
    bar.appendChild(speedBtn);

    function cycleSpeed(){
      speedIdx = (speedIdx + 1) % speeds.length;
      vid.playbackRate = speeds[speedIdx];
      speedBtn.textContent = speeds[speedIdx] + 'x';
      toast('Speed: ' + speeds[speedIdx] + 'x');
    }

    // Snapshot button
    var snapBtn = document.createElement('button');
    snapBtn.className = 'snap-btn';
    snapBtn.innerHTML = '\\u{1F4F7}';
    snapBtn.title = 'Snapshot (press D)';
    snapBtn.onclick = function(){ takeSnapshot(); };
    bar.appendChild(snapBtn);

    function takeSnapshot(){
      try {
        var c = document.createElement('canvas');
        c.width = vid.videoWidth || 640;
        c.height = vid.videoHeight || 360;
        var ctx = c.getContext('2d');
        ctx.drawImage(vid, 0, 0, c.width, c.height);
        c.toBlob(function(blob){
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'snapshot-' + Date.now() + '.png';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
          toast('Snapshot saved');
        }, 'image/png');
      } catch(e) {
        toast('Snapshot failed');
      }
    }

    // Copy link button
    var copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.innerHTML = '\\u{1F517} Copy';
    copyBtn.title = 'Copy stream link (press C)';
    copyBtn.onclick = function(){ copyLink(); };
    bar.appendChild(copyBtn);

    function copyLink(){
      var url = window.location.href;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function(){ toast('Link copied!'); }).catch(function(){ fallbackCopy(url); });
      } else {
        fallbackCopy(url);
      }
    }
    function fallbackCopy(url){
      var ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); toast('Link copied!'); }
      catch(e) { toast('Copy failed'); }
      document.body.removeChild(ta);
    }

    // QR code button (uses online API, cached)
    var qrBtn = document.createElement('button');
    qrBtn.className = 'copy-btn';
    qrBtn.innerHTML = '\\u{1F4F1} QR';
    qrBtn.title = 'Show QR code';
    qrBtn.onclick = function(){ showQR(); };
    bar.appendChild(qrBtn);

    var qrModal = document.getElementById('qrModal');
    var qrCanvas = document.getElementById('qrCanvas');
    var qrClose = document.getElementById('qrClose');
    if (qrClose) qrClose.onclick = function(){ qrModal.classList.remove('open'); };
    if (qrModal) qrModal.addEventListener('click', function(e){ if (e.target === qrModal) qrModal.classList.remove('open'); });

    function showQR(){
      if (!qrModal || !qrCanvas) return;
      qrCanvas.innerHTML = '';
      var img = document.createElement('img');
      img.width = 200;
      img.height = 200;
      var url = 'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=' + encodeURIComponent(window.location.href);
      img.src = url;
      img.onerror = function(){ qrCanvas.innerHTML = '<p style="color:#999;font-size:12px">QR failed to load</p>'; };
      qrCanvas.appendChild(img);
      qrModal.classList.add('open');
    }

    // ── Keyboard shortcuts ──
    var hintEl = document.getElementById('shortcutHint');
    var hintTimer = null;

    function showHint(){
      if (!hintEl) return;
      hintEl.classList.add('open');
      clearTimeout(hintTimer);
      hintTimer = setTimeout(function(){ hintEl.classList.remove('open'); }, 4000);
    }

    // Close hint on click
    if (hintEl) hintEl.addEventListener('click', function(){ hintEl.classList.remove('open'); });

    document.addEventListener('keydown', function(e){
      // Don't intercept if typing in an input
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      switch(e.key){
        case ' ':
        case 'k':
          e.preventDefault();
          if (vid.paused) { vid.play(); toast('Playing'); }
          else { vid.pause(); toast('Paused'); }
          break;
        case 'ArrowLeft':
          e.preventDefault();
          vid.currentTime = Math.max(0, vid.currentTime - 10);
          toast('-10s');
          break;
        case 'ArrowRight':
          e.preventDefault();
          vid.currentTime = Math.min(vid.duration || 0, vid.currentTime + 10);
          toast('+10s');
          break;
        case 'ArrowUp':
          e.preventDefault();
          vid.volume = Math.min(1, vid.volume + 0.1);
          toast('Volume: ' + Math.round(vid.volume * 100) + '%');
          break;
        case 'ArrowDown':
          e.preventDefault();
          vid.volume = Math.max(0, vid.volume - 0.1);
          toast('Volume: ' + Math.round(vid.volume * 100) + '%');
          break;
        case 'f':
          e.preventDefault();
          if (document.fullscreenElement) document.exitFullscreen();
          else if (vid.requestFullscreen) vid.requestFullscreen();
          else if (vid.webkitRequestFullscreen) vid.webkitRequestFullscreen();
          break;
        case 'm':
          e.preventDefault();
          vid.muted = !vid.muted;
          toast(vid.muted ? 'Muted' : 'Unmuted');
          break;
        case 's':
          e.preventDefault();
          cycleSpeed();
          break;
        case 'd':
          e.preventDefault();
          takeSnapshot();
          break;
        case 'c':
          e.preventDefault();
          copyLink();
          break;
        case '?':
          e.preventDefault();
          showHint();
          break;
      }
    });

    // Show hint briefly on first load
    setTimeout(function(){ showHint(); }, 1500);

    console.log('[extras] keyboard shortcuts + speed + snapshot + copy + QR ready');
  });
})();
</script>'''

# Inject CSS before </head>
if '</head>' in content:
    content = content.replace('</head>', extra_css + '\n</head>', 1)
    print("PATCHED: injected extras CSS into <head>")
else:
    content = extra_css + content
    print("PATCHED: prepended extras CSS")

# Inject HTML and JS before </body>
extras_block = extra_html + '\n' + extra_js
if '</body>' in content:
    content = content.replace('</body>', extras_block + '\n</body>', 1)
    print("PATCHED: injected extras HTML+JS before </body>")
else:
    content = content + extras_block
    print("PATCHED: appended extras HTML+JS")

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: keyboard shortcuts + speed control + snapshot + copy link + QR code")
