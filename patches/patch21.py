import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'wzml-x-extras-v3' in content:
    print("ALREADY PATCHED: extras-v3 exist")
    sys.exit(0)

# ─── CSS for v3 features ───
v3_css = '''<style id="wzml-x-extras-v3">
/* ═══ WZML-X Extra Features v3 ═══ */

/* ── Theater Mode ── */
body.wzml-theater {
  background: #000 !important;
}
body.wzml-theater .wzml-mesh-bg {
  opacity: 0 !important;
}
body.wzml-theater #player {
  max-width: 90vw !important;
  max-height: 85vh !important;
  box-shadow: 0 0 60px rgba(61,135,255,.3) !important;
}
body.wzml-theater .extras-bar,
body.wzml-theater .info-panel {
  position: relative;
  z-index: 10;
}
body.wzml-theater::after {
  content: '';
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.6);
  z-index: -1;
  pointer-events: none;
}

/* ── Loop Button ── */
.loop-btn {
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
.loop-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }
.loop-btn.active {
  background: rgba(61,135,255,.35);
  border-color: rgba(61,135,255,.6);
  color: #3D87FF;
}

/* ── Theater Button ── */
.theater-btn {
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
.theater-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }
.theater-btn.active {
  background: rgba(61,135,255,.35);
  border-color: rgba(61,135,255,.6);
}

/* ── Share Button ── */
.share-btn {
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
.share-btn:hover { background: rgba(0,0,0,.65); border-color: rgba(255,255,255,.35); }

/* ── Resume Position Banner ── */
.resume-banner {
  display: none;
  position: fixed;
  bottom: 20px;
  right: 20px;
  background: rgba(0,0,0,.85);
  border: 1px solid rgba(61,135,255,.4);
  border-radius: 12px;
  padding: 14px 20px;
  backdrop-filter: blur(12px);
  z-index: 10003;
  font-family: 'Montserrat', sans-serif;
  animation: fadeInUp .3s ease;
}
.resume-banner.show { display: block; }
.resume-banner p { color: #ccc; font-size: 13px; margin-bottom: 10px; }
.resume-banner p b { color: #fff; }
.resume-banner .resume-actions { display: flex; gap: 8px; }
.resume-banner .resume-yes {
  background: #3D87FF; color: #fff; border: none;
  padding: 6px 16px; border-radius: 8px; cursor: pointer;
  font-weight: 600; font-size: 12px; font-family: inherit;
}
.resume-banner .resume-yes:hover { background: #2a5fd0; }
.resume-banner .resume-no {
  background: rgba(255,255,255,.1); color: #ccc; border: 1px solid rgba(255,255,255,.15);
  padding: 6px 16px; border-radius: 8px; cursor: pointer;
  font-size: 12px; font-family: inherit;
}
.resume-banner .resume-no:hover { background: rgba(255,255,255,.15); }

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>'''

# ─── JavaScript for v3 features ───
v3_js = '''<script id="wzml-x-extras-v3-js">
(function(){
  function ready(fn){
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function(){
    var vid = document.getElementById('player');
    if (!vid) { console.warn('[v3] no player found'); return; }

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

    // ── Get or create extras bar ──
    var bar = document.getElementById('extrasBar');
    if (!bar) { bar = document.createElement('div'); bar.className = 'extras-bar'; bar.id = 'extrasBar'; vid.parentNode.appendChild(bar); }

    // ── Theater Mode ──
    var theaterBtn = document.createElement('button');
    theaterBtn.className = 'theater-btn';
    theaterBtn.innerHTML = '\\u{1F4FA}';
    theaterBtn.title = 'Theater mode (press T)';
    theaterBtn.onclick = function(){ toggleTheater(); };
    bar.appendChild(theaterBtn);

    function toggleTheater(){
      document.body.classList.toggle('wzml-theater');
      var isOn = document.body.classList.contains('wzml-theater');
      theaterBtn.classList.toggle('active', isOn);
      toast(isOn ? 'Theater mode on' : 'Theater mode off');
    }

    // ── Loop / Repeat ──
    var loopBtn = document.createElement('button');
    loopBtn.className = 'loop-btn';
    loopBtn.innerHTML = '\\u{1F501}';
    loopBtn.title = 'Loop video (press R)';
    loopBtn.onclick = function(){ toggleLoop(); };
    bar.appendChild(loopBtn);

    function toggleLoop(){
      vid.loop = !vid.loop;
      loopBtn.classList.toggle('active', vid.loop);
      toast(vid.loop ? 'Loop on' : 'Loop off');
    }

    // ── Share Button ──
    var shareBtn = document.createElement('button');
    shareBtn.className = 'share-btn';
    shareBtn.textContent = 'Share';
    shareBtn.title = 'Share link (press E)';
    shareBtn.onclick = function(){ shareLink(); };
    bar.appendChild(shareBtn);

    function shareLink(){
      var url = window.location.href;
      var title = document.title || 'Stream';
      if (navigator.share) {
        navigator.share({ title: title, url: url }).then(function(){
          toast('Shared!');
        }).catch(function(){
          // User cancelled, do nothing
        });
      } else if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function(){
          toast('Link copied!');
        }).catch(function(){
          fallbackCopy(url);
        });
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

    // ── Resume Playback Position ──
    var resumeKey = 'wzml-resume:' + window.location.pathname;
    var savedTime = null;
    try {
      savedTime = parseFloat(localStorage.getItem(resumeKey));
    } catch(e) {}

    // Save position periodically and on pause
    var saveTimer = setInterval(function(){
      try {
        if (vid.currentTime > 5 && !vid.ended) {
          localStorage.setItem(resumeKey, String(vid.currentTime));
        }
      } catch(e) {}
    }, 5000);

    vid.addEventListener('pause', function(){
      try {
        if (vid.currentTime > 5) {
          localStorage.setItem(resumeKey, String(vid.currentTime));
        }
      } catch(e) {}
    });

    // Show resume banner if we have a saved position
    if (savedTime && savedTime > 10 && !isNaN(savedTime)) {
      var banner = document.createElement('div');
      banner.className = 'resume-banner';
      var mins = Math.floor(savedTime / 60);
      var secs = Math.floor(savedTime % 60);
      var timeStr = mins > 0 ? mins + 'm ' + secs + 's' : secs + 's';
      banner.innerHTML = '<p>Resume from <b>' + timeStr + '</b>?</p>' +
        '<div class="resume-actions">' +
        '<button class="resume-yes" id="resumeYes">Resume</button>' +
        '<button class="resume-no" id="resumeNo">Start over</button>' +
        '</div>';
      document.body.appendChild(banner);

      setTimeout(function(){ banner.classList.add('show'); }, 800);

      document.getElementById('resumeYes').onclick = function(){
        vid.currentTime = savedTime;
        banner.classList.remove('show');
        setTimeout(function(){ banner.remove(); }, 300);
        toast('Resumed from ' + timeStr);
      };
      document.getElementById('resumeNo').onclick = function(){
        try { localStorage.removeItem(resumeKey); } catch(e) {}
        banner.classList.remove('show');
        setTimeout(function(){ banner.remove(); }, 300);
      };
    }

    // Clear saved position when video ends (unless looping)
    vid.addEventListener('ended', function(){
      if (!vid.loop) {
        try { localStorage.removeItem(resumeKey); } catch(e) {}
      }
    });

    // ── Keyboard shortcuts for v3 ──
    document.addEventListener('keydown', function(e){
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      switch(e.key){
        case 't':
          e.preventDefault();
          toggleTheater();
          break;
        case 'r':
          e.preventDefault();
          toggleLoop();
          break;
        case 'e':
          e.preventDefault();
          shareLink();
          break;
        case 'n':
          e.preventDefault();
          vid.currentTime = Math.max(0, vid.currentTime - 30);
          toast('-30s');
          break;
        case 'l':
          e.preventDefault();
          vid.currentTime = Math.min(vid.duration || 0, vid.currentTime + 30);
          toast('+30s');
          break;
      }
    });

    // Add shortcuts to the hint overlay (if it exists from patch19)
    var hintEl = document.getElementById('shortcutHint');
    if (hintEl) {
      var newRows = [
        '<div class="row"><span>Theater mode</span><span class="key">T</span></div>',
        '<div class="row"><span>Loop / repeat</span><span class="key">R</span></div>',
        '<div class="row"><span>Share link</span><span class="key">E</span></div>',
        '<div class="row"><span>Skip 30s back</span><span class="key">N</span></div>',
        '<div class="row"><span>Skip 30s forward</span><span class="key">L</span></div>'
      ];
      var closeRow = hintEl.querySelector('.row:last-child');
      if (closeRow) {
        for (var i = newRows.length - 1; i >= 0; i--) {
          closeRow.insertAdjacentHTML('beforebegin', newRows[i]);
        }
      }
    }

    console.log('[v3] theater mode + loop + share + resume playback + skip 30s ready');
  });
})();
</script>'''

# Inject CSS before </head>
if '</head>' in content:
    content = content.replace('</head>', v3_css + '\n</head>', 1)
    print("PATCHED: injected v3 CSS into <head>")
else:
    content = v3_css + content
    print("PATCHED: prepended v3 CSS")

# Inject JS before </body>
if '</body>' in content:
    content = content.replace('</body>', v3_js + '\n</body>', 1)
    print("PATCHED: injected v3 JS before </body>")
else:
    content = content + v3_js
    print("PATCHED: appended v3 JS")

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: theater mode + loop + share + resume playback + skip 30s")
