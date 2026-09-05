import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'stream-retry' in content:
    print("ALREADY PATCHED stream.html: retry button exists")
    sys.exit(0)

old_stream_var = 'var STREAM = location.origin + "/stream/" + encodeURIComponent(TOKEN);'
new_stream_var = 'var _userQ = location.search || ""; var STREAM = location.origin + "/stream/" + encodeURIComponent(TOKEN) + _userQ;'
if old_stream_var not in content:
    print("WARNING: stream.html STREAM var not found"); sys.exit(1)
content = content.replace(old_stream_var, new_stream_var, 1)

old_clearstall = '''            function clearStall() {
                el("frame").classList.remove("stalled");
            }

            function fatal(head, body) {'''

new_clearstall = '''            function clearStall() {
                el("frame").classList.remove("stalled");
            }

            var _isPlaying = false;
            var _stallTimer = null;
            var _promptShown = false;
            var _probeTs = 0;
            var _waitDelay = 30000;

            function _isVideoPlaying() {
                var v = el("player");
                if (v && v.readyState >= 3 && !v.paused && !v.ended && v.currentTime > 0) return true;
                if (lmEl && lmEl._loaded) return true;
                return _isPlaying;
            }

            function _hidePrompt() { _promptShown = false; el("frame").classList.remove("stalled"); }

            function _switchToUser() {
                                if (new URLSearchParams(location.search).get("user") === "1") { location.reload(); }
                else { var sp = new URLSearchParams(location.search); sp.set("user", "1"); location.href = location.pathname + "?" + sp.toString(); }
            }

            function _showPrompt(head, body) {
                if (_promptShown) return;
                if (_isVideoPlaying()) return;
                _promptShown = true;
                var box = el("stallText");
                box.innerHTML = "";
                var b = document.createElement("b"); b.textContent = head; box.appendChild(b);
                box.appendChild(document.createElement("br"));
                box.appendChild(document.createTextNode(body));
                box.appendChild(document.createElement("br"));
                var waitBtn = document.createElement("a");
                waitBtn.className = "btn"; waitBtn.href = "#";
                waitBtn.style.cssText = "display:inline-block;margin-top:10px;margin-right:8px;border-color:rgba(93,157,255,.5);color:#5B9DFF";
                waitBtn.textContent = "Wait a bit more";
                waitBtn.onclick = function(e) { e.preventDefault(); _hidePrompt(); _waitDelay = 10000; _startStallTimer(10000); };
                box.appendChild(waitBtn);
                var retryBtn = document.createElement("a");
                retryBtn.className = "btn"; retryBtn.href = "#";
                retryBtn.style.cssText = "display:inline-block;margin-top:10px;border-color:rgba(255,165,0,.5);color:#ffa500";
                retryBtn.textContent = new URLSearchParams(location.search).get("user") === "1" ? "Retry user account" : "Retry with user account (Risky)";
                retryBtn.onclick = function(e) { e.preventDefault(); _switchToUser(); };
                box.appendChild(retryBtn);
                el("frame").classList.add("stalled");
            }

            function _startStallTimer(delay) {
                if (_stallTimer) clearTimeout(_stallTimer);
                _stallTimer = setTimeout(function() {
                    _stallTimer = null;
                    if (!_isVideoPlaying() && !_promptShown)
                        _showPrompt("Stream is slow to respond", "The bot may be struggling. You can wait or try your user account.");
                }, delay || _waitDelay);
            }

            function smartStreamCheck() {
                if (_promptShown) return;
                if (_isVideoPlaying()) return;
                var now = Date.now();
                if (now - _probeTs < 5000) return;
                _probeTs = now;
                fetch("/api/stream/" + encodeURIComponent(TOKEN) + _userQ, { cache: "no-store" })
                    .then(function (r) {
                        if ((r.status === 404 || r.status === 503) && !_isVideoPlaying())
                            _showPrompt("Stream failed via bots", "The bot could not read this file. Try your user account.");
                    }).catch(function () {});
            }

            function fatal(head, body, retry) {'''

if old_clearstall not in content:
    print("WARNING: stream.html clearStall+fatal block not found"); sys.exit(1)
content = content.replace(old_clearstall, new_clearstall, 1)

old_fatal_body = '''            function fatal(head, body, retry) {
                el("root").innerHTML = '<div class="err"><h2></h2><p></p>' +
                    '<a class="btn primary" href="/">Back to WZML-X</a></div>';
                el("root").querySelector("h2").textContent = head;
                el("root").querySelector("p").textContent = body;
            }'''

new_fatal_body = '''            function fatal(head, body, retry) {
                var html = '<div class="err"><h2></h2><p></p></div>';
                if (retry) html += '<div style="margin-top:16px"><a class="btn" id="stream-retry" href="#" style="border-color:rgba(255,165,0,.5);color:#ffa500">Retry with user account (Risky)</a></div>';
                html += '<div style="margin-top:12px"><a class="btn primary" href="/">Back to WZML-X</a></div>';
                el("root").innerHTML = html;
                el("root").querySelector("h2").textContent = head;
                el("root").querySelector("p").textContent = body;
                if (retry) el("stream-retry").onclick = function(e) { e.preventDefault(); _switchToUser(); };
            }'''

if old_fatal_body not in content:
    print("WARNING: stream.html fatal() body not found"); sys.exit(1)
content = content.replace(old_fatal_body, new_fatal_body, 1)

old_vid_error = '''                vid.addEventListener("error", function () {
                    el("loading").classList.add("gone");
                    var e = vid.error;'''
new_vid_error = '''                vid.addEventListener("error", function () {
                    el("loading").classList.add("gone");
                    smartStreamCheck();
                    var e = vid.error;'''
if old_vid_error not in content:
    print("WARNING: stream.html vid error handler not found"); sys.exit(1)
content = content.replace(old_vid_error, new_vid_error, 1)

old_lm_error = '''                    lmEl.addEventListener("error", function () {
                        el("loading").classList.add("gone");
                        stall("Cannot play this file",'''
new_lm_error = '''                    lmEl.addEventListener("error", function () {
                        el("loading").classList.add("gone");
                        smartStreamCheck();
                        stall("Cannot play this file",'''
if old_lm_error not in content:
    print("WARNING: stream.html lmEl error handler not found"); sys.exit(1)
content = content.replace(old_lm_error, new_lm_error, 1)

old_catch = '''                .catch(function (e) {
                    if (e && e.message === "gone") {
                        fatal("This file is no longer available",
                            "It was removed from the source chat, or the link is wrong.");
                    } else {
                        fatal("Could not load this file",
                            "The streaming service did not respond. Try again shortly.");
                    }
                });'''
new_catch = '''                .catch(function (e) {
                    if (e && e.message === "gone") {
                        if (new URLSearchParams(location.search).get("user") === "1") {
                            fatal("This file is no longer available",
                                "It was removed from the source chat, or the link is wrong.");
                        } else {
                            _promptShown = true;
                            fatal("Stream failed via bots",
                                "The bot could not read this file (privacy mode). Try your user account.", true);
                        }
                    } else {
                        fatal("Could not load this file",
                            "The streaming service did not respond. Try again shortly.");
                    }
                });'''
if old_catch not in content:
    print("WARNING: stream.html catch block not found"); sys.exit(1)
content = content.replace(old_catch, new_catch, 1)

old_fetch = 'fetch("/api/stream/" + encodeURIComponent(TOKEN), { cache: "no-store" })'
new_fetch = 'fetch("/api/stream/" + encodeURIComponent(TOKEN) + _userQ, { cache: "no-store" })'
if old_fetch not in content:
    print("WARNING: stream.html fetch URL not found"); sys.exit(1)
content = content.replace(old_fetch, new_fetch, 1)

old_stall_timeout = '''                setTimeout(function () {
                    if (!el("loading").classList.contains("gone")) {
                        el("loadingText").textContent =
                            "Still buffering, large files take a moment";
                    }
                }, 6000);'''
new_stall_timeout = '''                setTimeout(function () {
                    if (!el("loading").classList.contains("gone")) {
                        el("loadingText").textContent =
                            "Still buffering, large files take a moment";
                    }
                }, 6000);
                _startStallTimer(30000);'''
if old_stall_timeout not in content:
    print("WARNING: stream.html stall timeout not found"); sys.exit(1)
content = content.replace(old_stall_timeout, new_stall_timeout, 1)

old_playing_hook = '''                m.addEventListener("playing", clearStall);
                m.addEventListener("playing", dropArt);'''
new_playing_hook = '''                m.addEventListener("playing", function () {
                    _isPlaying = true; _promptShown = false;
                    if (_stallTimer) { clearTimeout(_stallTimer); _stallTimer = null; }
                    el("frame").classList.remove("stalled"); clearStall();
                });
                m.addEventListener("playing", dropArt);
                m.addEventListener("waiting", function () { _isPlaying = false; _startStallTimer(_waitDelay); });
                m.addEventListener("pause", function () { _isPlaying = false; });'''
if old_playing_hook not in content:
    print("WARNING: stream.html playing hook not found"); sys.exit(1)
content = content.replace(old_playing_hook, new_playing_hook, 1)

with open(sys.argv[1], 'w') as f:
    f.write(content)
print("PATCHED stream.html: v3 final — GET (not HEAD) + always retry + smart stall")
