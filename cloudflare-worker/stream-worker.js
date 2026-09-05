/**
 * WZML-X Single-Bot Cloudflare Worker
 * 
 * Simple proxy: registers one tunnel URL, proxies all traffic to it.
 * Uses STREAM_KV for persistence across isolate evictions.
 * 
 * Routes:
 *   POST /update-tunnel  — register tunnel URL (X-Tunnel-Secret required)
 *   GET  /tunnel-status  — check current tunnel
 *   GET  /health         — health check through tunnel
 *   GET  /*               — proxy to tunnel
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // ─── Tunnel registration ──────────────────────────────────
    if (path === '/update-tunnel') {
      const secret = request.headers.get('X-Tunnel-Secret');
      if (secret !== env.WORKER_SECRET) {
        return json({ error: 'unauthorized' }, 401);
      }
      let body;
      try {
        body = await request.json();
      } catch {
        return json({ error: 'invalid JSON body' }, 400);
      }
      if (!body.url) {
        return json({ error: 'missing url in body' }, 400);
      }
      
      globalThis._tunnelUrl = body.url;
      
      if (env.STREAM_KV) {
        await env.STREAM_KV.put('stream:url', body.url);
      }
      
      return json({ ok: true, url: body.url });
    }

    // ─── Tunnel status ────────────────────────────────────────
    if (path === '/tunnel-status') {
      let tunnelUrl = globalThis._tunnelUrl;
      if (!tunnelUrl && env.STREAM_KV) {
        tunnelUrl = await env.STREAM_KV.get('stream:url');
        if (tunnelUrl) globalThis._tunnelUrl = tunnelUrl;
      }
      return json({ tunnel: tunnelUrl || null });
    }

    // ─── Health check ────────────────────────────────────────
    if (path === '/health') {
      let tunnelUrl = globalThis._tunnelUrl;
      if (!tunnelUrl && env.STREAM_KV) {
        tunnelUrl = await env.STREAM_KV.get('stream:url');
        if (tunnelUrl) globalThis._tunnelUrl = tunnelUrl;
      }
      if (!tunnelUrl) {
        return json({ error: 'no tunnel registered', bot_responding: false, tunnel_connected: false }, 502);
      }
      try {
        const resp = await fetch(tunnelUrl + '/health', { signal: AbortSignal.timeout(10000) });
        const data = await resp.json();
        return json(data, resp.status);
      } catch (e) {
        return json({ error: e.message, bot_responding: false, tunnel_connected: false }, 502);
      }
    }

    // ─── Proxy all other traffic to tunnel ───────────────────
    let tunnelUrl = globalThis._tunnelUrl;
    if (!tunnelUrl && env.STREAM_KV) {
      tunnelUrl = await env.STREAM_KV.get('stream:url');
      if (tunnelUrl) globalThis._tunnelUrl = tunnelUrl;
    }
    
    if (tunnelUrl) {
      const targetUrl = tunnelUrl + path + url.search;
      return proxyRequest(request, targetUrl);
    }

    return json({ error: 'no tunnel registered', hint: 'POST /update-tunnel to register' }, 502);
  }
};

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
