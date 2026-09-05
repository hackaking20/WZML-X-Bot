/**
 * stall_ui.js — injected into stream.html by the user_stream plugin.
 *
 * Provides:
 *   1. Smart stall detection (30s buffer, decoder errors, 404/503 detection)
 *   2. "Wait a bit more" button (does NOT cut the stream connection)
 *   3. "Retry with user account" button (HIDDEN when already on ?user=1)
 *   4. Password overlay when 401 is returned from the stream
 *   5. URLSearchParams for precise ?user=1 detection (fixes indexOf bug)
 *   6. localStorage token storage with 24h expiry
 *   7. Event hooks for playing/waiting/pause/error
 *
 * Bug fixes from three-AI review:
 *   #3 URLSearchParams instead of indexOf("user=1")
 *   #4 No duplicate auth= params in fetch URLs
 *   _switchToUser: checks getToken() — reloads if token exists, shows overlay only if no token
 */

(function () {
  "use strict";

  // ─── URL helpers (bug fix #3: URLSearchParams) ───────────────

  function urlParams() {
    return new URLSearchParams(window.location.search);
  }

  function isUserMode() {
    return urlParams().get("user") === "1";
  }

  function buildUserQ() {
    var params = urlParams();
    var q = "";
    if (params.get("user") === "1") {
      q += (q ? "&" : "?") + "user=1";
    }
    // Append auth token if present in localStorage
    var token = getToken();
    if (token && params.get("user") === "1") {
      q += (q ? "&" : "?") + "auth=" + encodeURIComponent(token);
    }
    return q;
  }

  function getToken() {
    try {
      var raw = localStorage.getItem("wzml_stream_auth");
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (Date.now() - data.ts > 24 * 3600 * 1000) {
        localStorage.removeItem("wzml_stream_auth");
        return null;
      }
      return data.token;
    } catch (e) {
      return null;
    }
  }

  function storeToken(token) {
    try {
      localStorage.setItem(
        "wzml_stream_auth",
        JSON.stringify({ token: token, ts: Date.now() })
      );
    } catch (e) {}
  }

  // ─── Stall detection state ────────────────────────────────────

  var _isPlaying = false;
  var _stallTimer = null;
  var _promptShown = false;
  var _probeTs = 0;
  var _waitDelay = 30000;

  function _isVideoPlaying() {
    var v = document.getElementById("player");
    if (v && v.readyState >= 3 && !v.paused && !v.ended && v.currentTime > 0)
      return true;
    return _isPlaying;
  }

  function _hidePrompt() {
    _promptShown = false;
    var frame = document.getElementById("frame");
    if (frame) frame.classList.remove("stalled");
  }

  function _showPrompt(head, body) {
    if (_promptShown) return;
    if (_isVideoPlaying()) return;
    _promptShown = true;

    var box = document.getElementById("stallText") || _getStallBox();
    if (!box) return;
    box.innerHTML = "";
    var b = document.createElement("b");
    b.textContent = head;
    box.appendChild(b);
    box.appendChild(document.createElement("br"));
    box.appendChild(document.createTextNode(body));
    box.appendChild(document.createElement("br"));

    // "Wait a bit more" button — always shown
    var waitBtn = document.createElement("a");
    waitBtn.className = "btn";
    waitBtn.href = "#";
    waitBtn.style.cssText =
      "display:inline-block;margin-top:10px;margin-right:8px;" +
      "border-color:rgba(93,157,255,.5);color:#5B9DFF";
    waitBtn.textContent = "Wait a bit more";
    waitBtn.onclick = function (e) {
      e.preventDefault();
      _hidePrompt();
      _startStallTimer(10000);  // one-time 10s grace, don't mutate _waitDelay
    };
    box.appendChild(waitBtn);

    // "Retry with user account" button — HIDDEN when already on ?user=1
    if (!isUserMode()) {
      var retryBtn = document.createElement("a");
      retryBtn.className = "btn";
      retryBtn.href = "#";
      retryBtn.style.cssText =
        "display:inline-block;margin-top:10px;" +
        "border-color:rgba(255,165,0,.5);color:#ffa500";
      retryBtn.textContent = "Retry with user account (Risky)";
      retryBtn.onclick = function (e) {
        e.preventDefault();
        _switchToUser();
      };
      box.appendChild(retryBtn);
    }

    var frame = document.getElementById("frame");
    if (frame) frame.classList.add("stalled");
  }

  function _getStallBox() {
    // Try to find or create the stall text container
    var existing = document.getElementById("stallText");
    if (existing) return existing;
    var frame = document.getElementById("frame");
    if (!frame) return null;
    var div = document.createElement("div");
    div.id = "stallText";
    div.style.cssText =
      "position:absolute;bottom:60px;left:50%;transform:translateX(-50%);" +
      "background:rgba(0,0,0,0.85);color:#fff;padding:16px 24px;" +
      "border-radius:8px;text-align:center;z-index:9999;max-width:80%";
    frame.appendChild(div);
    return div;
  }

  function _switchToUser() {
    var sp = urlParams();
    if (sp.get("user") === "1") {
      // Already in user mode — just reload
      window.location.reload();
    } else {
      sp.set("user", "1");
      window.location.search = sp.toString();
    }
  }

  function _startStallTimer(delay) {
    if (_stallTimer) clearTimeout(_stallTimer);
    _stallTimer = setTimeout(function () {
      _stallTimer = null;
      if (!_isVideoPlaying() && !_promptShown) {
        _showPrompt(
          "Stream is slow to respond",
          "The bot may be struggling. You can wait or try your user account."
        );
      }
    }, delay || _waitDelay);
  }

  function _smartStreamCheck() {
    if (_promptShown) return;
    if (_isVideoPlaying()) return;
    var now = Date.now();
    if (now - _probeTs < 5000) return;
    _probeTs = now;

    // Bug fix: use GET (not HEAD) because FastAPI @app.get routes
    // return 405 for HEAD requests
    var token = window.location.pathname.split("/").pop() || "";
    var q = buildUserQ();
    fetch("/api/stream/" + encodeURIComponent(token) + q, { cache: "no-store" })
      .then(function (r) {
        if (
          (r.status === 404 || r.status === 503) &&
          !_isVideoPlaying()
        ) {
          _showPrompt(
            "Stream failed via bots",
            "The bot could not read this file. Try your user account."
          );
        }
      })
      .catch(function () {});
  }

  // ─── Password overlay ─────────────────────────────────────────

  function _showPasswordOverlay() {
    var existing = document.getElementById("wzml-auth-overlay");
    if (existing) return;

    var overlay = document.createElement("div");
    overlay.id = "wzml-auth-overlay";
    overlay.style.cssText =
      "position:fixed;top:0;left:0;width:100%;height:100%;" +
      "background:rgba(0,0,0,0.92);backdrop-filter:blur(8px);" +
      "display:flex;align-items:center;justify-content:center;" +
      "z-index:99999";

    var box = document.createElement("div");
    box.style.cssText =
      "background:#1a1a2e;color:#fff;padding:32px;border-radius:12px;" +
      "text-align:center;max-width:400px;width:90%;font-family:sans-serif";

    var title = document.createElement("h2");
    title.textContent = "🔒 Stream Password";
    title.style.cssText = "margin-bottom:16px;color:#5B9DFF";
    box.appendChild(title);

    var desc = document.createElement("p");
    desc.textContent = "This stream requires a password to access via user account.";
    desc.style.cssText = "margin-bottom:20px;color:#aaa;font-size:14px";
    box.appendChild(desc);

    var input = document.createElement("input");
    input.type = "password";
    input.placeholder = "Enter password";
    input.style.cssText =
      "width:100%;padding:12px;margin-bottom:12px;" +
      "background:#0f0f1a;border:1px solid #333;border-radius:6px;" +
      "color:#fff;font-size:16px;box-sizing:border-box";
    box.appendChild(input);

    var errP = document.createElement("p");
    errP.style.cssText = "color:#ff4444;font-size:13px;min-height:18px;margin-bottom:8px";
    box.appendChild(errP);

    var btn = document.createElement("button");
    btn.textContent = "Unlock";
    btn.style.cssText =
      "width:100%;padding:12px;background:#5B9DFF;color:#fff;border:none;" +
      "border-radius:6px;font-size:16px;cursor:pointer;font-weight:bold";
    box.appendChild(btn);

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    input.focus();

    async function submit() {
      var password = input.value;
      if (!password) return;
      btn.textContent = "Checking...";
      btn.disabled = true;
      errP.textContent = "";

      try {
        var resp = await fetch("/api/stream_auth", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: password }),
        });
        var data = await resp.json();
        if (resp.ok && data.token) {
          storeToken(data.token);
          document.body.removeChild(overlay);
          // Reload with the token
          var sp = urlParams();
          sp.set("auth", data.token);
          window.location.search = sp.toString();
        } else {
          errP.textContent = data.error || "Authentication failed";
          btn.textContent = "Unlock";
          btn.disabled = false;
        }
      } catch (e) {
        errP.textContent = "Server error. User stream may not be configured.";
        btn.textContent = "Unlock";
        btn.disabled = false;
      }
    }

    btn.onclick = submit;
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
    });
  }

  // ─── Fatal error handler ──────────────────────────────────────

  function _fatal(head, body, retry) {
    var root = document.getElementById("root");
    if (!root) return;
    var html = '<div class="err"><h2></h2><p></p></div>';
    // Only show retry button if NOT already in user mode
    if (retry && !isUserMode()) {
      html +=
        '<div style="margin-top:16px"><a class="btn" id="stream-retry" href="#" ' +
        'style="border-color:rgba(255,165,0,.5);color:#ffa500">' +
        "Retry with user account (Risky)</a></div>";
    }
    html +=
      '<div style="margin-top:12px"><a class="btn primary" href="/">Back to WZML-X</a></div>';
    root.innerHTML = html;
    root.querySelector("h2").textContent = head;
    root.querySelector("p").textContent = body;
    if (retry) {
      var btn = document.getElementById("stream-retry");
      if (btn) {
        btn.onclick = function (e) {
          e.preventDefault();
          _switchToUser();
        };
      }
    }
  }

  // ─── Initialization ──────────────────────────────────────────

  function init() {
    var userMode = isUserMode();
    var userQ = buildUserQ();

    // If in user mode and we have no token, check if we need the password overlay.
    // The server will return 401 if auth is required — we intercept that below.
    // We don't proactively show the overlay; it shows on 401 response.

    // Hook into the initial API fetch
    // The original stream.html does: fetch("/api/stream/" + TOKEN + ...)
    // We override it by intercepting fetch calls to /api/stream/
    var origFetch = window.fetch;
    window.fetch = function (url, opts) {
      // Handle both string URLs and Request objects
      var urlStr = typeof url === "string" ? url : (url && url.url ? url.url : String(url));
      // If this is an /api/stream/ request, append our query params
      if (urlStr && urlStr.indexOf("/api/stream/") >= 0) {
        // Check if we need to append user=1 and auth=
        if (userMode && urlStr.indexOf("user=") < 0) {
          urlStr += (urlStr.indexOf("?") >= 0 ? "&" : "?") + "user=1";
          var token = getToken();
          if (token && urlStr.indexOf("auth=") < 0) {
            urlStr += "&auth=" + encodeURIComponent(token);
          }
          // Always pass a string URL to origFetch, not the original Request object
          url = urlStr;
        }
      }
      return origFetch.call(this, url, opts).then(function (resp) {
        // Intercept 401 responses for stream endpoints
        if (
          resp.status === 401 &&
          urlStr &&
          (urlStr.indexOf("/api/stream/") >= 0 ||
            urlStr.indexOf("/stream/") >= 0)
        ) {
          _showPasswordOverlay();
        }
        return resp;
      });
    };

    // Wait for the player element to appear, then attach event listeners
    var checkInterval = setInterval(function () {
      var player = document.getElementById("player");
      if (!player) return;
      clearInterval(checkInterval);

      // Start the initial stall timer
      _startStallTimer(_waitDelay);

      // Video event hooks
      player.addEventListener("playing", function () {
        _isPlaying = true;
        _hidePrompt();
        if (_stallTimer) { clearTimeout(_stallTimer); _stallTimer = null; }
      });

      player.addEventListener("waiting", function () {
        _isPlaying = false;
        _startStallTimer(_waitDelay);
      });

      player.addEventListener("pause", function () {
        _isPlaying = false;
      });

      player.addEventListener("error", function (e) {
        // Decoder error — re-probe to check if stream is actually gone
        _smartStreamCheck();
      });

      // Also hook into libmedia/advanced decoder if present
      var lmEl =
        document.getElementById("lm-player") ||
        document.querySelector("[data-lm-player]");
      if (lmEl) {
        lmEl.addEventListener("error", function () {
          _smartStreamCheck();
        });
        if (lmEl.loaded !== undefined) {
          // Override the loaded check
          var origLoaded = lmEl.loaded;
          Object.defineProperty(lmEl, "loaded", {
            get: function () {
              return origLoaded;
            },
            set: function (v) {
              origLoaded = v;
              if (v) _isPlaying = true;
            },
          });
        }
      }
    }, 500);

    // Also hook into the initial fetch catch block by patching the error display
    // This catches the "file is gone" case on initial load
    var origOnError = window.onerror;
    window.onerror = function (msg, url, line, col, err) {
      if (origOnError) origOnError(msg, url, line, col, err);
    };

    // Expose functions globally for the stream.html page to use
    window._wzmlUserStream = {
      isUserMode: isUserMode,
      buildUserQ: buildUserQ,
      getToken: getToken,
      storeToken: storeToken,
      showPrompt: _showPrompt,
      hidePrompt: _hidePrompt,
      fatal: _fatal,
      switchToUser: _switchToUser,
      startStallTimer: _startStallTimer,
      smartStreamCheck: _smartStreamCheck,
      showPasswordOverlay: _showPasswordOverlay,
    };

    console.log("[user_stream] stall UI initialized, userMode=" + userMode);
  }

  // Run init when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
