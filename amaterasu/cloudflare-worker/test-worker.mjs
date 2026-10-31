// Unit test for the Worker's routing/auth logic.
//
// This sandbox's Node cannot instantiate WASM, so undici's fetch/Request/Response
// are unusable here. We shim the four web primitives the worker actually touches
// and exercise the real handler logic against them.
//
// Run: cp worker.js worker.mjs && node test-worker.mjs

class HeadersShim {
  constructor(init = {}) {
    this.map = new Map();
    if (init instanceof HeadersShim) {
      init.forEach((v, k) => this.map.set(k, v));
    } else {
      for (const [k, v] of Object.entries(init)) this.map.set(k.toLowerCase(), v);
    }
  }
  get(k) { return this.map.get(k.toLowerCase()) ?? null; }
  set(k, v) { this.map.set(k.toLowerCase(), v); }
  delete(k) { this.map.delete(k.toLowerCase()); }
  forEach(fn) { for (const [k, v] of this.map) fn(v, k); }
}

class RequestShim {
  constructor(url, init = {}) {
    if (init instanceof RequestShim) {
      this.url = url;
      this.method = init.method;
      this.headers = new HeadersShim(init.headers);
      this._body = init._body;
      return;
    }
    this.url = String(url);
    this.method = init.method || 'GET';
    this.headers = new HeadersShim(init.headers || {});
    this._body = init.body;
  }
  async formData() {
    const params = new URLSearchParams(typeof this._body === 'string' ? this._body : '');
    return { get: (k) => params.get(k) };
  }
}

class ResponseShim {
  constructor(body, init = {}) {
    this._body = body;
    this.status = init.status || 200;
    this.statusText = init.statusText || '';
    this.body = body;
    this.headers = new HeadersShim(init.headers || {});
  }
  async text() { return this._body == null ? '' : String(this._body); }
  async json() { return JSON.parse(String(this._body)); }
}

globalThis.Headers = HeadersShim;
globalThis.Request = RequestShim;
globalThis.Response = ResponseShim;

const worker = (await import('./worker.mjs')).default;

const store = new Map();
const env = {
  TUNNEL_KV: {
    get: async (k) => store.get(k) ?? null,
    put: async (k, v) => void store.set(k, v),
  },
  TUNNEL_SECRET: 's3cret',
};

let proxiedTo = null;
let upstreamStatus = 200;
globalThis.fetch = async (input) => {
  const url = typeof input === 'string' ? input : input.url;
  if (url.includes('trycloudflare.com')) {
    proxiedTo = url;
    return new ResponseShim('upstream-body', { status: upstreamStatus });
  }
  throw new Error('unexpected fetch ' + url);
};

const call = (path, init = {}, extraEnv = {}) =>
  worker.fetch(new RequestShim('https://worker.example' + path, init), { ...env, ...extraEnv });

const results = [];
const check = (name, cond, detail = '') => results.push([cond ? 'PASS' : 'FAIL', name, detail]);

// 1. registration rejects a bad secret
let r = await call('/update-tunnel', {
  method: 'POST',
  headers: { 'X-Tunnel-Secret': 'nope' },
  body: new URLSearchParams({ url: 'https://a-b.trycloudflare.com' }).toString(),
});
check('rejects bad secret', r.status === 403, 'status ' + r.status);

// 2. registration rejects a non-tunnel URL (no open proxy)
r = await call('/update-tunnel', {
  method: 'POST',
  headers: { 'X-Tunnel-Secret': 's3cret' },
  body: new URLSearchParams({ url: 'https://evil.example.com' }).toString(),
});
check('rejects non-tunnel url', r.status === 400, 'status ' + r.status);

// 3. registration accepts and normalises a tunnel URL
r = await call('/update-tunnel', {
  method: 'POST',
  headers: { 'X-Tunnel-Secret': 's3cret' },
  body: new URLSearchParams({ url: 'https://silly-river-abc.trycloudflare.com/' }).toString(),
});
const body = await r.json();
check('accepts tunnel url, strips trailing slash',
  r.status === 200 && body.url === 'https://silly-river-abc.trycloudflare.com', JSON.stringify(body));
check('stores url in KV', store.get('stream:url') === 'https://silly-river-abc.trycloudflare.com');

// 4. proxy with no password set
r = await call('/webdl?x=1');
check('proxies when no PASS', r.status === 200 && (await r.text()) === 'upstream-body', 'status ' + r.status);
// Built at runtime: the literal form gets mangled in transit by the
// proxy this file is pushed through, which silently dropped the query.
const QMARK = String.fromCharCode(63);
const expectedProxy = 'https://silly-river-abc.trycloudflare.com/webdl' + QMARK + 'x=1';
check('preserves path and query', proxiedTo === expectedProxy,
  `got=${JSON.stringify(proxiedTo)} (len ${String(proxiedTo).length}) expected=${JSON.stringify(expectedProxy)} (len ${expectedProxy.length})`);

// 5. upstream errors pass through rather than being masked
upstreamStatus = 404;
r = await call('/missing');
check('passes upstream status through', r.status === 404, 'status ' + r.status);
upstreamStatus = 200;

// 6. password gate
r = await call('/', {}, { PASS: 'hunter2' });
let gateBody = await r.text();
check('gate serves login page instead of upstream',
  gateBody.includes('password') && gateBody !== 'upstream-body', 'status ' + r.status);

r = await call('/__login', { method: 'POST', body: new URLSearchParams({ password: 'wrong' }).toString() }, { PASS: 'hunter2' });
check('gate rejects wrong password', r.status === 401, 'status ' + r.status);

r = await call('/__login', { method: 'POST', body: new URLSearchParams({ password: 'hunter2' }).toString() }, { PASS: 'hunter2' });
const cookie = (r.headers.get('set-cookie') || '').split(';')[0];
check('gate issues cookie', r.status === 302 && cookie.startsWith('amaterasu_gate='), cookie.slice(0, 28));

r = await call('/', { headers: { Cookie: cookie } }, { PASS: 'hunter2' });
check('valid cookie reaches upstream', r.status === 200, 'status ' + r.status);

r = await call('/', { headers: { Cookie: 'amaterasu_gate=' + 'a'.repeat(64) } }, { PASS: 'hunter2' });
gateBody = await r.text();
check('forged cookie never reaches upstream',
  gateBody !== 'upstream-body' && gateBody.includes('password'), 'status ' + r.status);

// 7. nothing registered yet
store.delete('stream:url');
r = await call('/');
check('503 when no tunnel registered', r.status === 503, 'status ' + r.status);

// 8. status endpoint
store.set('stream:url', 'https://silly-river-abc.trycloudflare.com');
r = await call('/tunnel-status');
const st = await r.json();
check('status reports url and reachability',
  st.url === 'https://silly-river-abc.trycloudflare.com' && st.reachable === true, JSON.stringify(st));

for (const [state, name, detail] of results) {
  console.log(`${state}  ${name}${detail ? '  [' + detail + ']' : ''}`);
}
const failed = results.filter(([s]) => s === 'FAIL').length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
