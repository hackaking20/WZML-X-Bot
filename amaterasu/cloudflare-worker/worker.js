/**
 * Minimal stable front door for Amaterasu running on an ephemeral runner.
 *
 * The bot's Cloudflare quick tunnel gets a new hostname on every boot. This
 * Worker holds the current hostname in KV and proxies to it, so you can
 * bookmark one URL. Optionally gates the whole thing behind a password.
 *
 * Deploy: Cloudflare dashboard → Workers → create → paste this file.
 * Bindings needed:
 *   KV namespace   TUNNEL_KV   (create one, bind as TUNNEL_KV)
 *   Secret         TUNNEL_SECRET   random string; the workflow sends it
 *   Variable       PASS            optional; if set, browsers must log in
 *
 * Routes:
 *   POST /update-tunnel   (header X-Tunnel-Secret) form field: url
 *   GET  /tunnel-status   current tunnel + reachability
 *   GET  /__login         password form (only when PASS is set)
 *   *                     proxied to the tunnel
 */

const COOKIE = 'amaterasu_gate';

async function sha256Hex(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function loginPage(error) {
  return new Response(
    `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
     <title>Amaterasu</title>
     <style>
       body{font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0;background:#111;color:#eee}
       form{display:flex;gap:.5rem}input,button{font:inherit;padding:.6rem .8rem;border-radius:8px;border:1px solid #444;background:#1b1b1b;color:#eee}
       p{color:#f66;height:1.2em}
     </style>
     <form method="POST" action="/__login">
       <input type="password" name="password" placeholder="password" autofocus>
       <button>Enter</button>
     </form>
     <p>${error || ''}</p>`,
    { status: error ? 401 : 200, headers: { 'content-type': 'text/html; charset=utf-8' } },
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ── Tunnel registration ──────────────────────────────────────────────
    if (url.pathname === '/update-tunnel') {
      if (request.method !== 'POST') return json({ error: 'POST only' }, 405);
      if (request.headers.get('X-Tunnel-Secret') !== env.TUNNEL_SECRET) {
        return json({ error: 'bad secret' }, 403);
      }
      const form = await request.formData();
      const target = String(form.get('url') || '').trim().replace(/\/+$/, '');
      if (!/^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/i.test(target)) {
        return json({ error: 'expected a https://*.trycloudflare.com URL', got: target }, 400);
      }
      await env.TUNNEL_KV.put('stream:url', target);
      await env.TUNNEL_KV.put('stream:updated', new Date().toISOString());
      return json({ ok: true, url: target });
    }

    if (url.pathname === '/tunnel-status') {
      const target = await env.TUNNEL_KV.get('stream:url');
      const updated = await env.TUNNEL_KV.get('stream:updated');
      let reachable = false;
      if (target) {
        try {
          const probe = await fetch(target + '/', { method: 'GET', redirect: 'manual' });
          reachable = probe.status < 500;
        } catch (_) {
          reachable = false;
        }
      }
      return json({ url: target, updated, reachable });
    }

    // ── Optional password gate ───────────────────────────────────────────
    const gate = env.PASS;
    if (gate) {
      const expected = await sha256Hex(`${gate}:${env.TUNNEL_SECRET}`);

      if (url.pathname === '/__login' && request.method === 'POST') {
        const form = await request.formData();
        if (String(form.get('password') || '') === gate) {
          return new Response(null, {
            status: 302,
            headers: {
              location: '/',
              'set-cookie': `${COOKIE}=${expected}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`,
            },
          });
        }
        return loginPage('wrong password');
      }

      const cookie = request.headers.get('Cookie') || '';
      const match = cookie.match(new RegExp(`${COOKIE}=([a-f0-9]{64})`));
      if (!match || match[1] !== expected) return loginPage('');
    }

    // ── Proxy ────────────────────────────────────────────────────────────
    const target = await env.TUNNEL_KV.get('stream:url');
    if (!target) {
      return new Response('No tunnel registered yet. The bot has not booted, or the last run has ended.', {
        status: 503,
        headers: { 'content-type': 'text/plain; charset=utf-8' },
      });
    }

    const upstream = new URL(target + url.pathname + url.search);
    // Constructing the Request from the upstream URL sets Host for us and
    // carries the method, headers (Range included) and body across. No header
    // surgery: Workers refuses to let us rewrite Host by hand.
    const proxied = new Request(upstream.toString(), request);

    try {
      const response = await fetch(proxied);
      // Re-wrap so the body streams instead of buffering; range requests for
      // video seeking pass through untouched.
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    } catch (error) {
      return new Response(`Tunnel unreachable: ${error.message}`, { status: 502 });
    }
  },
};
