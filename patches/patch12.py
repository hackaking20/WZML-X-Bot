import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if '_streamAuth' in content:
    print("ALREADY PATCHED stream.html: auth overlay exists")
    sys.exit(0)

# ─── 1. Inject auth overlay + blocking script right after <body> ───
body_idx = content.index('<body')
body_end = content.index('>', body_idx) + 1

AUTH_OVERLAY = """
<!-- ─── User Stream Auth Overlay ─── -->
<div id="stream-auth-overlay" style="display:none;position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.92);backdrop-filter:blur(8px);align-items:center;justify-content:center;">
  <div style="background:#1a1a2e;border-radius:12px;padding:28px 32px;max-width:360px;width:90%;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
    <div style="font-size:28px;margin-bottom:6px;">&#128274;</div>
    <div style="color:#e0e0e0;font-size:15px;font-weight:600;margin-bottom:4px;">User Stream Access</div>
    <div id="auth-subtext" style="color:#888;font-size:12px;margin-bottom:18px;">Checking authorization...</div>
    <input id="stream-auth-pass" type="password" placeholder="Password" style="display:none;width:100%;padding:10px 14px;border-radius:8px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;font-size:14px;outline:none;box-sizing:border-box;margin-bottom:12px;" autocomplete="off" />
    <button id="stream-auth-btn" style="display:none;width:100%;padding:10px;border-radius:8px;border:none;background:#4a6cf7;color:#fff;font-size:14px;font-weight:600;cursor:pointer;">Unlock</button>
    <div id="stream-auth-err" style="color:#ff6b6b;font-size:12px;margin-top:10px;display:none;"></div>
  </div>
</div>
<script>
(function() {
  var isUser = false;
  try { isUser = new URLSearchParams(location.search).get('user') === '1'; }
  catch(e) { isUser = location.search.indexOf('user=1') >= 0; }
  var tok = null;
  try { tok = localStorage.getItem('wzml_stream_auth'); } catch(e) {}
  var noauth = false;
  try { noauth = new URLSearchParams(location.search).get('noauth') === '1'; }
  catch(e) { noauth = location.search.indexOf('noauth=1') >= 0; }

  if (isUser && !tok && !noauth) {
    // Halt all page loading — prevents stream player from initializing
    try { window.stop(); } catch(e) {}
    // Show overlay
    var el = document.getElementById('stream-auth-overlay');
    if (el) el.style.display = 'flex';
    // Async check: is STREAM_PASS configured?
    fetch('/api/stream_auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: 'check' })
    }).then(function(r) {
      if (r.status === 401) {
        // STREAM_PASS is set — show password form
        var sub = document.getElementById('auth-subtext');
        if (sub) sub.textContent = 'Enter password to stream via your account';
        var inp = document.getElementById('stream-auth-pass');
        if (inp) { inp.style.display = 'block'; inp.focus(); }
        var btn = document.getElementById('stream-auth-btn');
        if (btn) btn.style.display = 'block';
      } else {
        // STREAM_PASS not set — reload with noauth flag, page will load normally
        var u = new URL(location.href);
        u.searchParams.set('noauth', '1');
        location.replace(u.toString());
      }
    }).catch(function() {
      var sub = document.getElementById('auth-subtext');
      if (sub) sub.textContent = 'Network error. Please refresh the page.';
    });
    // Wire up button + enter key
    function doLogin() {
      var pass = document.getElementById('stream-auth-pass').value;
      if (!pass) return;
      var btn = document.getElementById('stream-auth-btn');
      btn.textContent = 'Verifying...';
      btn.disabled = true;
      fetch('/api/stream_auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pass })
      }).then(function(r) {
        if (r.status === 401) {
          btn.textContent = 'Unlock';
          btn.disabled = false;
          var err = document.getElementById('stream-auth-err');
          err.textContent = 'Wrong password. Try again.';
          err.style.display = 'block';
          return null;
        }
        if (!r.ok) {
          btn.textContent = 'Unlock';
          btn.disabled = false;
          var err = document.getElementById('stream-auth-err');
          err.textContent = 'Server error.';
          err.style.display = 'block';
          return null;
        }
        return r.json();
      }).then(function(data) {
        if (data && data.token) {
          try { localStorage.setItem('wzml_stream_auth', data.token); } catch(e) {}
          location.reload();
        } else {
          btn.textContent = 'Unlock';
          btn.disabled = false;
        }
      }).catch(function(e) {
        btn.textContent = 'Unlock';
        btn.disabled = false;
        var err = document.getElementById('stream-auth-err');
        err.textContent = 'Network error: ' + e.message;
        err.style.display = 'block';
      });
    }
    document.addEventListener('DOMContentLoaded', function() {
      var btn = document.getElementById('stream-auth-btn');
      if (btn) btn.addEventListener('click', function(e) { e.preventDefault(); doLogin(); });
      var inp = document.getElementById('stream-auth-pass');
      if (inp) inp.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); doLogin(); } });
    });
  } else {
    // Not user mode, has token, or noauth — hide overlay, let page load
    var el = document.getElementById('stream-auth-overlay');
    if (el) el.style.display = 'none';
    if (noauth) {
      try {
        var u = new URL(location.href);
        u.searchParams.delete('noauth');
        history.replaceState({}, '', u.toString());
      } catch(e) {}
    }
  }
})();
</script>
<script>
(function() {
  var _streamAuth = {
    LS_KEY: 'wzml_stream_auth',
    token: null,
    resolved: false,

    getToken: function() {
      if (this.token) return this.token;
      try { this.token = localStorage.getItem(this.LS_KEY); } catch(e) {}
      return this.token;
    },

    setToken: function(t) {
      this.token = t;
      try { localStorage.setItem(this.LS_KEY, t); } catch(e) {}
    },

    clearToken: function() {
      this.token = null;
      try { localStorage.removeItem(this.LS_KEY); } catch(e) {}
    },

    isUserMode: function() {
      try { return new URLSearchParams(location.search).get('user') === '1'; }
      catch(e) { return location.search.indexOf('user=1') >= 0; }
    },

    getAuthParam: function() {
      var t = this.getToken();
      if (!t || !this.isUserMode()) return '';
      return '&auth=' + encodeURIComponent(t);
    },

    getAuthQs: function() {
      var t = this.getToken();
      if (!t || !this.isUserMode()) return '';
      return '?auth=' + encodeURIComponent(t);
    },

    init: function() {
      this.resolved = true;
    }
  };
  window._streamAuth = _streamAuth;
  _streamAuth.init();
})();
</script>
"""

content = content[:body_end] + AUTH_OVERLAY + content[body_end:]

# ─── 2. Patch _switchToUser to include auth token ───
old_switch = """function _switchToUser() {
                var sp = new URLSearchParams(location.search);
                if (sp.get("user") === "1") {
                    location.reload();
                } else {
                    sp.set("user", "1");
                    location.href = location.pathname + "?" + sp.toString();
                }
            }"""
new_switch = """function _switchToUser() {
                var sp = new URLSearchParams(location.search);
                if (sp.get("user") === "1") {
                    location.reload();
                } else {
                    sp.set("user", "1");
                    var t = _streamAuth.getToken();
                    if (t) sp.set("auth", t);
                    location.href = location.pathname + "?" + sp.toString();
                }
            }"""
content = content.replace(old_switch, new_switch, 1)

# ─── 3. Patch the stream URL to include auth token ───
old_stream = 'var _userQ = location.search || ""; var STREAM = location.origin + "/stream/" +'
new_stream = """var _userQ = location.search || "";
          var _authTok = _streamAuth.getToken();
          if (_authTok && _userQ.indexOf("user=1") >= 0 && _userQ.indexOf("auth=") < 0) {
            _userQ += (_userQ.indexOf("?") >= 0 ? "&" : "?") + "auth=" + encodeURIComponent(_authTok);
          }
          var STREAM = location.origin + "/stream/" +"""
content = content.replace(old_stream, new_stream, 1)

# ─── 4. Patch all fetch calls that use _userQ to include auth param ───
import re
fetches_with_userq = [(m.start(), m.group()) for m in re.finditer(r'fetch\([^)]*_userQ[^)]*\)', content)]
for pos, match in fetches_with_userq:
    if '_streamAuth.getAuthParam()' not in match:
        old_f = match
        new_f = match.replace('_userQ', '_userQ + _streamAuth.getAuthParam()')
        content = content[:pos] + new_f + content[pos + len(match):]

# ─── 5. Handle 401 responses from stream endpoints ───
old_catch_block = 'if (new URLSearchParams(location.search).get("user") === "1") {'
new_catch_block = """if (_streamAuth.isUserMode()) {
                    _streamAuth.clearToken();
                    var u = new URL(location.href);
                    u.searchParams.delete('noauth');
                    u.searchParams.delete('auth');
                    location.replace(u.toString());
                    return;
                }
                if (new URLSearchParams(location.search).get("user") === "1") {"""
content = content.replace(old_catch_block, new_catch_block, 1)

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: window.stop + overlay + async auth check + token forwarding")
