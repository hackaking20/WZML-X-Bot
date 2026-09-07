/**
 * WZML-X Single-Bot Cloudflare Worker
 * 
 * Proxy + Viewer Limiter + Auth Gate
 * 
 * Features:
 *   - Registers one tunnel URL, proxies all traffic to it
 *   - Viewer limiter: tracks unique IPs via CF-Connecting-IP, limits to MAX_VIEWERS
 *   - Auth gate: if STREAM_PASS is set in KV, requires ?auth=TOKEN cookie
 *   - Priority bypass: ?pkey=SECRET bypasses viewer limit
 *   - Uses STREAM_KV for persistence
 * 
 * KV keys:
 *   stream:url         — current tunnel URL
 *   stream:pass        — STREAM_PASS password (set via /set-pass)
 *   stream:max_viewers — max concurrent viewers (default 3, set via /set-limit)
 *   stream:priority    — priority key for bypass (set via /set-priority)
 *   viewer_slot:N      — {ip, ts} for each viewer slot
 * 
 * Routes:
 *   POST /update-tunnel — register tunnel URL (X-Tunnel-Secret required)
 *   GET  /tunnel-status — check current tunnel
 *   GET  /health        — health check through tunnel + active viewer count
 *   POST /set-pass      — set STREAM_PASS (X-Tunnel-Secret required)
 *   POST /set-limit     — set MAX_VIEWERS (X-Tunnel-Secret required)
 *   POST /set-priority  — set PRIORITY_KEY (X-Tunnel-Secret required)
 *   POST /auth          — submit password, get token (browser-facing)
 *   GET  /*             — proxy to tunnel (with limiter + auth gate)
 */

const VIEWER_TIMEOUT = 300; // 5 minutes

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const clientIp = request.headers.get('CF-Connecting-IP') || 'unknown';

    // ─── Tunnel registration ──────────────────────────────────
    if (path === '/update-tunnel') {
      const secret = request.headers.get('X-Tunnel-Secret');
      if (secret !== env.WORKER_SECRET) {
        return json({ error: 'unauthorized' }, 401);
      }
      let body;
      try { body = await request.json(); } catch { return json({ error: 'invalid JSON body' }, 400); }
      if (!body.url) { return json({ error: 'missing url in body' }, 400); }
      
      globalThis._tunnelUrl = body.url;
      if (env.STREAM_KV) { await env.STREAM_KV.put('stream:url', body.url); }
      return json({ ok: true, url: body.url });
    }

    // ─── Set STREAM_PASS ──────────────────────────────────────
    if (path === '/set-pass') {
      const secret = request.headers.get('X-Tunnel-Secret');
      if (secret !== env.WORKER_SECRET) return json({ error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ error: 'invalid JSON' }, 400); }
      if (env.STREAM_KV) {
        if (body.password) {
          await env.STREAM_KV.put('stream:pass', body.password);
        } else {
          await env.STREAM_KV.delete('stream:pass');
        }
      }
      return json({ ok: true, pass_set: !!body.password });
    }

    // ─── Set MAX_VIEWERS ──────────────────────────────────────
    if (path === '/set-limit') {
      const secret = request.headers.get('X-Tunnel-Secret');
      if (secret !== env.WORKER_SECRET) return json({ error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ error: 'invalid JSON' }, 400); }
      const limit = parseInt(body.limit) || 3;
      if (env.STREAM_KV) { await env.STREAM_KV.put('stream:max_viewers', String(limit)); }
      globalThis._maxViewers = limit;
      return json({ ok: true, limit });
    }

    // ─── Set PRIORITY_KEY ─────────────────────────────────────
    if (path === '/set-priority') {
      const secret = request.headers.get('X-Tunnel-Secret');
      if (secret !== env.WORKER_SECRET) return json({ error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ error: 'invalid JSON' }, 400); }
      if (env.STREAM_KV) {
        if (body.key) {
          await env.STREAM_KV.put('stream:priority', body.key);
        } else {
          await env.STREAM_KV.delete('stream:priority');
        }
      }
      return json({ ok: true, priority_set: !!body.key });
    }

    // ─── Tunnel status ────────────────────────────────────────
    if (path === '/tunnel-status') {
      let tunnelUrl = await getTunnelUrl(env);
      return json({ tunnel: tunnelUrl || null });
    }

    // ─── Health check ────────────────────────────────────────
    if (path === '/health') {
      let tunnelUrl = await getTunnelUrl(env);
      if (!tunnelUrl) {
        return json({ error: 'no tunnel registered', bot_responding: false, tunnel_connected: false }, 502);
      }
      try {
        const resp = await fetch(tunnelUrl + '/health', { signal: AbortSignal.timeout(10000) });
        const data = await resp.json();
        const viewerCount = await countActiveViewers(env);
        data.active_viewers = viewerCount;
        return json(data, resp.status);
      } catch (e) {
        return json({ error: e.message, bot_responding: false, tunnel_connected: false }, 502);
      }
    }

    // ─── Auth endpoint (browser submits password here) ────────
    if (path === '/auth') {
      if (request.method !== 'POST') {
        return json({ error: 'POST required' }, 405);
      }
      let body;
      try { body = await request.json(); } catch { return json({ error: 'invalid JSON' }, 400); }
      
      const storedPass = env.STREAM_KV ? await env.STREAM_KV.get('stream:pass') : null;
      if (!storedPass) {
        return json({ error: 'STREAM_PASS not set' }, 200);
      }
      if (body.password !== storedPass) {
        return json({ error: 'wrong password' }, 401);
      }
      const token = await makeToken(storedPass);
      return json({ token, expires: 86400 });
    }

    // ─── Proxy all other traffic to tunnel ───────────────────
    let tunnelUrl = await getTunnelUrl(env);
    if (!tunnelUrl) {
      return json({ error: 'no tunnel registered', hint: 'POST /update-tunnel to register' }, 502);
    }

    // Skip limiter/auth for non-stream paths (API, static assets, health probes)
    const isStreamPath = path.startsWith('/stream/') || path.startsWith('/api/stream/') || path.startsWith('/dl/');

    if (isStreamPath && request.method !== 'HEAD') {
      // ── Auth gate ──
      const storedPass = env.STREAM_KV ? await env.STREAM_KV.get('stream:pass') : null;
      if (storedPass) {
        const authParam = url.searchParams.get('auth');
        const validToken = await makeToken(storedPass);
        if (authParam !== validToken) {
          return authPage(request.url);
        }
      }

      // ── Viewer limiter ──
      const priorityKey = env.STREAM_KV ? await env.STREAM_KV.get('stream:priority') : null;
      const providedPkey = url.searchParams.get('pkey');
      const isPriority = priorityKey && providedPkey === priorityKey;

      if (!isPriority) {
        const maxViewers = await getMaxViewers(env);
        if (maxViewers > 0) {
          const allowed = await tryAcquireViewer(env, clientIp);
          if (!allowed) {
            return new Response(
              `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Stream Limit Reached</title>` +
              `<style>body{background:#0d1117;color:#c9d1d9;font-family:sans-serif;display:flex;align-items:center;` +
              `justify-content:center;min-height:100vh;margin:0}div{text-align:center;padding:2rem}` +
              `h1{color:#f85149}p{color:#8b949e}button{background:#238636;color:white;border:none;padding:10px 20px;` +
              `border-radius:6px;cursor:pointer;font-size:16px;margin-top:1rem}</style></head>` +
              `<body><div><h1>Stream Limit Reached</h1>` +
              `<p>Maximum ${maxViewers} concurrent viewers. Please try again in a few minutes.</p>` +
              `<button onclick="location.reload()">Retry</button></div></body></html>`,
              { status: 503, headers: { 'Content-Type': 'text/html', 'Retry-After': '30' } }
            );
          }
        }
      }
    }

    // ── Forward to tunnel ──
    const targetUrl = tunnelUrl + path + url.search;
    return proxyRequest(request, targetUrl);
  }
};

// ─── Helpers ──────────────────────────────────────────────────

async function getTunnelUrl(env) {
  if (globalThis._tunnelUrl) return globalThis._tunnelUrl;
  if (env.STREAM_KV) {
    const url = await env.STREAM_KV.get('stream:url');
    if (url) { globalThis._tunnelUrl = url; return url; }
  }
  return null;
}

async function getMaxViewers(env) {
  if (globalThis._maxViewers !== undefined) return globalThis._maxViewers;
  if (env.STREAM_KV) {
    const val = await env.STREAM_KV.get('stream:max_viewers');
    if (val) { globalThis._maxViewers = parseInt(val); return globalThis._maxViewers; }
  }
  globalThis._maxViewers = 3;
  return 3;
}

async function makeToken(password) {
  const now = Math.floor(Date.now() / 86400000);
  const data = new TextEncoder().encode(password + ':' + now);
  const hash = await crypto.subtle.digest('SHA-256', data);
  const arr = Array.from(new Uint8Array(hash));
  return arr.map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

async function tryAcquireViewer(env, ip) {
  if (!env.STREAM_KV) return true;
  const maxViewers = await getMaxViewers(env);
  const now = Date.now();
  const cutoff = now - VIEWER_TIMEOUT * 1000;
  
  for (let i = 0; i < maxViewers + 1; i++) {
    const slotKey = 'viewer_slot:' + i;
    const slot = await env.STREAM_KV.get(slotKey, 'json');
    if (!slot || slot.ts < cutoff) {
      await env.STREAM_KV.put(slotKey, JSON.stringify({ ip, ts: now }));
      return true;
    }
    if (slot.ip === ip) {
      await env.STREAM_KV.put(slotKey, JSON.stringify({ ip, ts: now }));
      return true;
    }
  }
  return false;
}

async function countActiveViewers(env) {
  if (!env.STREAM_KV) return 0;
  const maxViewers = await getMaxViewers(env);
  const now = Date.now();
  const cutoff = now - VIEWER_TIMEOUT * 1000;
  let count = 0;
  for (let i = 0; i < maxViewers + 1; i++) {
    const slot = await env.STREAM_KV.get('viewer_slot:' + i, 'json');
    if (slot && slot.ts >= cutoff) count++;
  }
  return count;
}

function authPage(originalUrl) {
  return new Response(
    `<!DOCTYPE html><html><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>Stream Password</title>` +
    `<style>` +
    `*{margin:0;padding:0;box-sizing:border-box}` +
    `body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,sans-serif;` +
    `display:flex;align-items:center;justify-content:center;min-height:100vh}` +
    `.box{background:#161b22;border:1px solid #30363d;border-radius:12px;` +
    `padding:2.5rem;width:100%;max-width:360px;text-align:center}` +
    `h1{font-size:1.4rem;margin-bottom:1.5rem;color:#58a6ff}` +
    `input{width:100%;padding:12px 14px;background:#0d1117;border:1px solid #30363d;` +
    `border-radius:8px;color:#c9d1d9;font-size:15px;margin-bottom:1rem}` +
    `input:focus{outline:none;border-color:#58a6ff}` +
    `button{width:100%;padding:12px;background:#238636;color:white;border:none;` +
    `border-radius:8px;cursor:pointer;font-size:15px;font-weight:600}` +
    `button:hover{background:#2ea043}` +
    `.err{color:#f85149;font-size:13px;margin-top:1rem;display:none}` +
    `</style></head><body>` +
    `<div class="box">` +
    `<h1>Stream Access</h1>` +
    `<form id="f"><input type="password" id="p" placeholder="Enter password" autofocus>` +
    `<button type="submit">Unlock Stream</button></form>` +
    `<div class="err" id="e">Wrong password. Try again.</div></div>` +
    `<script>` +
    `document.getElementById('f').onsubmit=function(ev){ev.preventDefault();` +
    `var p=document.getElementById('p').value;` +
    `fetch('/auth',{method:'POST',headers:{'Content-Type':'application/json'},` +
    `body:JSON.stringify({password:p})})` +
    `.then(function(r){return r.json()})` +
    `.then(function(d){if(d.token){` +
    `var u=new URL('${originalUrl}');u.searchParams.set('auth',d.token);` +
    `location.href=u.toString();}else{` +
    `document.getElementById('e').style.display='block';` +
    `document.getElementById('p').value='';document.getElementById('p').focus();}})` +
    `.catch(function(){document.getElementById('e').textContent='Request failed';` +
    `document.getElementById('e').style.display='block';});};` +
    `</script></body></html>`,
    { status: 401, headers: { 'Content-Type': 'text/html' } }
  );
}

async function proxyRequest(request, targetUrl) {
  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.set('X-Forwarded-Host', new URL(request.url).hostname);
  
  const init = {
    method: request.method,
    headers: headers,
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body;
  }
  
  try {
    const resp = await fetch(targetUrl, init);
    const respHeaders = new Headers(resp.headers);
    respHeaders.set('X-Proxied-By', 'wzml-stream-worker');
    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers: respHeaders,
    });
  } catch (e) {
    return json({ error: e.message, status: 'proxy_failed' }, 502);
  }
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
