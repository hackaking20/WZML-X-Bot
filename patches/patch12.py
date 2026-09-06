import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if '_streamAuth' in content:
    print("ALREADY PATCHED stream.html: auth infrastructure exists")
    sys.exit(0)

# ─── 1. Inject minimal _streamAuth stub (token forwarding only, no overlay) ───
body_idx = content.index('<body')
body_end = content.index('>', body_idx) + 1

AUTH_STUB = """
<!-- ─── User Stream Auth Token Forwarding (auth handled by Worker) ─── -->
<script>
(function() {
  var _streamAuth = {
    LS_KEY: 'wzml_stream_auth',
    token: null,
    resolved: true,

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

content = content[:body_end] + AUTH_STUB + content[body_end:]

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
                    location.reload();
                    return;
                }
                if (new URLSearchParams(location.search).get("user") === "1") {"""
content = content.replace(old_catch_block, new_catch_block, 1)

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: token forwarding only (auth handled by Worker)")
