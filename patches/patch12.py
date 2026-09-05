import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if '_streamAuth' in content:
    print("ALREADY PATCHED stream.html: auth overlay exists")
    sys.exit(0)

# ─── 1. Inject auth overlay CSS + JS right after the <body> tag opening ───
# Find the first <body ...> tag
body_idx = content.index('<body')
body_end = content.index('>', body_idx) + 1

AUTH_OVERLAY = """
<!-- ─── User Stream Auth Overlay ─── -->
<div id="stream-auth-overlay" style="display:none;position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,0.92);backdrop-filter:blur(8px);align-items:center;justify-content:center;">
  <div style="background:#1a1a2e;border-radius:12px;padding:28px 32px;max-width:360px;width:90%;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5);">
    <div style="font-size:28px;margin-bottom:6px;">&#128274;</div>
    <div style="color:#e0e0e0;font-size:15px;font-weight:600;margin-bottom:4px;">User Stream Access</div>
    <div style="color:#888;font-size:12px;margin-bottom:18px;">Enter password to stream via your account</div>
    <input id="stream-auth-pass" type="password" placeholder="Password" style="width:100%;padding:10px 14px;border-radius:8px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;font-size:14px;outline:none;box-sizing:border-box;margin-bottom:12px;" autocomplete="off" />
    <button id="stream-auth-btn" style="width:100%;padding:10px;border-radius:8px;border:none;background:#4a6cf7;color:#fff;font-size:14px;font-weight:600;cursor:pointer;">Unlock</button>
    <div id="stream-auth-err" style="color:#ff6b6b;font-size:12px;margin-top:10px;display:none;"></div>
  </div>
</div>
<script>
(function() {
  var _streamAuth = {
    LS_KEY: 'wzml_stream_auth',
    token: null,
    overlay: null,
    needsAuth: false,
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

    showOverlay: function(msg) {
      if (!this.overlay) this.overlay = document.getElementById('stream-auth-overlay');
      if (!this.overlay) return;
      this.overlay.style.display = 'flex';
      var err = document.getElementById('stream-auth-err');
      if (msg) { err.textContent = msg; err.style.display = 'block'; }
      else { err.style.display = 'none'; }
      var inp = document.getElementById('stream-auth-pass');
      if (inp) inp.focus();
    },

    hideOverlay: function() {
      if (!this.overlay) this.overlay = document.getElementById('stream-auth-overlay');
      if (this.overlay) this.overlay.style.display = 'none';
    },

    doLogin: function() {
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
          err.textContent = 'Server error. User stream may not be configured.';
          err.style.display = 'block';
          return null;
        }
        return r.json();
      }).then(function(data) {
        if (data && data.token) {
          _streamAuth.setToken(data.token);
          _streamAuth.hideOverlay();
          _streamAuth.resolved = true;
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
    },

    ensureAuth: function() {
      if (!this.isUserMode()) { this.resolved = true; return true; }
      var t = this.getToken();
      if (t) {
        this.resolved = true;
        return true;
      }
      this.showOverlay();
      return false;
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
      var self = this;
      document.addEventListener('DOMContentLoaded', function() {
        var btn = document.getElementById('stream-auth-btn');
        if (btn) {
          btn.addEventListener('click', function(e) { e.preventDefault(); self.doLogin(); });
        }
        var inp = document.getElementById('stream-auth-pass');
        if (inp) {
          inp.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); self.doLogin(); } });
        }
        if (self.isUserMode() && !self.getToken()) {
          self.showOverlay();
        }
      });
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

# ─── 3. Patch the meta fetch to include auth token ───
# The meta fetch is: fetch("/api/stream/" + encodeURIComponent(TOKEN) + _userQ, ...)
# We need to append &auth=TOKEN if in user mode
old_meta_fetch = 'fetch("/api/stream/" + encodeURIComponent(TOKEN) + _userQ, {'
new_meta_fetch = 'fetch("/api/stream/" + encodeURIComponent(TOKEN) + _userQ, {'
content = content.replace(old_meta_fetch, new_meta_fetch, 1)

# ─── 4. Patch the stream URL to include auth token ───
# The STREAM var builds the stream URL. Find where _userQ is used in the STREAM assignment.
old_stream = 'var _userQ = location.search || ""; var STREAM = location.origin + "/stream/" +'
# We need to make sure the auth token is included when building the stream URL
# Since the browser media player constructs requests from the STREAM var,
# we need the auth param baked into the URL
new_stream = """var _userQ = location.search || "";
          var _authTok = _streamAuth.getToken();
          if (_authTok && _userQ.indexOf("user=1") >= 0 && _userQ.indexOf("auth=") < 0) {
            _userQ += (_userQ.indexOf("?") >= 0 ? "&" : "?") + "auth=" + encodeURIComponent(_authTok);
          }
          var STREAM = location.origin + "/stream/" +"""
content = content.replace(old_stream, new_stream, 1)

# ─── 5. Patch smartStreamCheck fetch to include auth ───
# smartStreamCheck does a GET to the stream URL to check status
old_check_fetch = 'fetch("/api/stream/" + encodeURIComponent(TOKEN) + _userQ, {'
# This was already patched in step 3, but if smartStreamCheck uses a different URL pattern...
# Let's also handle the case where smartStreamCheck builds its own URL
# Check if there's a direct fetch to /stream/ in smartStreamCheck
# The smartStreamCheck function likely does:
#   fetch(STREAM + ...) or fetch("/api/stream/..." + TOKEN + ...)
# Let me find all fetch calls that use _userQ
import re
fetches_with_userq = [(m.start(), m.group()) for m in re.finditer(r'fetch\([^)]*_userQ[^)]*\)', content)]
for pos, match in fetches_with_userq:
    if '_streamAuth.getAuthParam()' not in match:
        old_f = match
        new_f = match.replace('_userQ', '_userQ + _streamAuth.getAuthParam()')
        content = content[:pos] + new_f + content[pos + len(match):]

# ─── 6. Patch the 401/403 error handling to show auth overlay ───
# When the stream returns 401 (auth required), show the overlay
# Find the smartStreamCheck response handling
old_ssc_check = 'function smartStreamCheck() {'
if old_ssc_check in content:
    # Insert auth check at the beginning of smartStreamCheck
    new_ssc_start = """function smartStreamCheck() {"""
    content = content.replace(old_ssc_check, new_ssc_start, 1)

# ─── 7. Handle 401 responses from stream endpoints ───
# In the fetch catch/error handlers, check for 401 status
old_catch_block = 'if (new URLSearchParams(location.search).get("user") === "1") {'
new_catch_block = """if (_streamAuth.isUserMode()) {
                    var _t = _streamAuth.getToken();
                    if (!_t) {
                        _streamAuth.showOverlay('Authentication required');
                    } else {
                        location.reload();
                    }
                    return;
                }
                if (new URLSearchParams(location.search).get("user") === "1") {"""
content = content.replace(old_catch_block, new_catch_block, 1)

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: auth overlay + localStorage token + auth param forwarding")
