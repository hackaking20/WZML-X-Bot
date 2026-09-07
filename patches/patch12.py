import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

# No-op: Auth and viewer limiting are now handled by the Cloudflare Worker.
# The Worker intercepts stream requests, checks auth tokens, and enforces
# viewer limits before requests reach the tunnel/bot.
#
# We still inject a minimal _streamAuth stub so existing stream.html code
# that references _streamAuth doesn't break. The stub just reads the auth
# token from the URL (which the Worker's /auth endpoint redirects to).

if '_streamAuth' in content:
    print("ALREADY PATCHED stream.html: _streamAuth exists (skipping)")
    sys.exit(0)

# Inject minimal stub
body_idx = content.index('<body')
body_end = content.index('>', body_idx) + 1

MINIMAL_STUB = """
<!-- ─── _streamAuth stub (auth handled by Cloudflare Worker) ─── -->
<script>
(function() {
  window._streamAuth = {
    getToken: function() {
      var sp = new URLSearchParams(location.search);
      return sp.get('auth') || '';
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
    getAuthQS: function() {
      var t = this.getToken();
      if (!t || !this.isUserMode()) return '';
      return '?auth=' + encodeURIComponent(t);
    }
  };
})();
</script>
"""

content = content[:body_end] + MINIMAL_STUB + content[body_end:]

with open(sys.argv[1], 'w') as f:
    f.write(content)

print("PATCHED stream.html: minimal _streamAuth stub (auth handled by Worker)")
