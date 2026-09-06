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
<!-- ─── User Stream Auth Overlay (hidden by default) ─── -->
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
// ─── Synchronous page blocker: prevent stream player from loading when auth needed ───
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
    // Replace entire page with auth form — stream player never loads
    document.open();
    document.write('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>User Stream Access</title><style>*{box-sizing:border-box}body{margin:0;background:#0d0d1a;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:system-ui,-apple-system,sans-serif}.box{background:#1a1a2e;border-radius:12px;padding:28px 32px;max-width:360px;width:90%;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.5)}.icon{font-size:28px;margin-bottom:6px}.title{color:#e0e0e0;font-size:15px;font-weight:600;margin-bottom:4px}.sub{color:#888;font-size:12px;margin-bottom:18px}input{width:100%;padding:10px 14px;border-radius:8px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;font-size:14px;outline:none;box-sizing:border-box;margin-bottom:12px}button{width:100%;padding:10px;border-radius:8px;border:none;background:#4a6cf7;color:#fff;font-size:14px;font-weight:600;cursor:pointer}button:disabled{opacity:0.6;cursor:wait}.err{color:#ff6b6b;font-size:12px;margin-top:10px;display:none}</style></head><body><div class="box"><div class="icon">&#128274;</div><div class="title">User Stream Access</div><div class="sub" id="sub-text">Checking...</div><input id="pass" type="password" placeholder="Password" style="display:none" autocomplete="off"><button id="btn" style="display:none">Unlock</button><div class="err" id="err"></div></div><scr'+'ipt>(function(){var sub=document.getElementById("sub-text");var pass=document.getElementById("pass");var btn=document.getElementById("btn");var err=document.getElementById("err");fetch("/api/stream_auth",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:"check"})}).then(function(r){if(r.status===401){sub.textContent="Enter password to stream via your account";pass.style.display="block";btn.style.display="block";pass.focus()}else{var u=new URL(location.href);u.searchParams.set("noauth","1");location.replace(u.toString())}}).catch(function(){sub.textContent="Network error. Please refresh."});function doLogin(){var p=pass.value;if(!p)return;btn.textContent="Verifying...";btn.disabled=true;fetch("/api/stream_auth",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:p})}).then(function(r){if(r.status===401){btn.textContent="Unlock";btn.disabled=false;err.textContent="Wrong password. Try again.";err.style.display="block";return null}if(!r.ok){btn.textContent="Unlock";btn.disabled=false;err.textContent="Server error.";err.style.display="block";return null}return r.json()}).then(function(data){if(data&&data.token){try{localStorage.setItem("wzml_stream_auth",data.token)}catch(e){}location.reload()}else{btn.textContent="Unlock";btn.disabled=false}}).catch(function(e){btn.textContent="Unlock";btn.disabled=false;err.textContent="Network error: "+e.message;err.style.display="block"})}btn.addEventListener("click",function(e){e.preventDefault();doLogin()});pass.addEventListener("keydown",function(e){if(e.key==="Enter"){e.preventDefault();doLogin()}})})();</scr'+'ipt></body></html>');
    document.close();
    return;
  }
  // Not user mode, has token, or noauth flag — hide overlay, let page load
  if (noauth) {
    try {
      var u = new URL(location.href);
      u.searchParams.delete('noauth');
      history.replaceState({}, '', u.toString());
    } catch(e) {}
  }
  var el = document.getElementById('stream-auth-overlay');
  if (el) el.style.display = 'none';
})();
</script>
<script>
(function() {
  var _streamAuth = {
    LS_KEY: 'wzml_stream_auth',
    token: null,
    overlay: null,
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
          btn.addEventListener('click', function(e) { e.preventDefault(); self.showOverlay(); });
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

print("PATCHED stream.html: document.write page blocking + async auth check + token forwarding")
