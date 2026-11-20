import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createHandler, hashPassword, verifyPassword } from '../supabase/functions/ladli-api/handler.mjs';

const config = { url: 'https://project.example', serviceKey: 'server-only-test-key',
  proxyToken: 'test-proxy-key-000000000000000000000000', origins: 'https://ladli.example' };
const digest = s => createHash('sha256').update(s).digest('hex');
const request = (path, method = 'GET', body, extra = {}) => new Request('https://edge.example/functions/v1/ladli-api' + path, {
  method, headers: { 'x-ladli-proxy-token': config.proxyToken, 'x-ladli-client-ip': '192.0.2.1',
    'Content-Type': 'application/json', Accept: 'application/json', ...extra },
  ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
});
const ok = body => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });

test('hosted gateway and local function URL prefixes resolve to the same route', async () => {
  const handle = createHandler(config);
  for (const prefix of ['/ladli-api', '/functions/v1/ladli-api', '']) {
    const response = await handle(new Request('https://edge.example' + prefix + '/health'));
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { status: 'ok' });
  }
});

test('new password hashes interoperate with Werkzeug, and legacy scrypt hashes still verify', async () => {
  const password = 'Migration-only-test-password-123';
  const encoded = await hashPassword(password);
  assert.equal(await verifyPassword(encoded, password), true);
  assert.equal(await verifyPassword(encoded, 'wrong'), false);
  const localPython = '.venv-migration/Scripts/python.exe';
  const python = process.env.LADLI_TEST_PYTHON || (process.platform === 'win32' && existsSync(localPython)
    ? localPython : process.platform === 'win32' ? 'python' : 'python3');
  const checked = execFileSync(python, ['-c', 'from werkzeug.security import check_password_hash; import sys; print(check_password_hash(sys.argv[1],sys.argv[2]))', encoded, password], { encoding: 'utf8' });
  assert.equal(checked.trim(), 'True');
  const legacy = execFileSync(python, ['-c', 'from werkzeug.security import generate_password_hash; import sys; print(generate_password_hash(sys.argv[1], method="scrypt"))', password], { encoding: 'utf8' }).trim();
  assert.equal(await verifyPassword(legacy, password), true);
  assert.equal(await verifyPassword('pbkdf2:sha256:999999999$salt$abcd', password), false);
});

test('direct requests, incorrect proxy tokens and foreign origins never reach storage or database', async () => {
  let calls = 0;
  const handle = createHandler(config, async () => { calls++; throw new Error('should not run'); });
  for (const headers of [{ 'x-ladli-proxy-token': '' }, { 'x-ladli-proxy-token': 'é'.repeat(config.proxyToken.length) }, { Origin: 'https://attacker.example' }]) {
    const r = await handle(request('/api/admin/inquiries', 'GET', undefined, headers));
    assert.equal(r.status, 403);
  }
  assert.equal(calls, 0);
});

test('missing configuration fails closed, while liveness stays independent', async () => {
  const handle = createHandler({}, async () => assert.fail('unexpected network request'));
  assert.equal((await handle(request('/api/contact', 'POST', {}))).status, 503);
  assert.equal((await handle(request('/healthz'))).status, 200);
});

test('malformed JSON and oversized bodies never cause successful submissions', async () => {
  const handle = createHandler(config, async () => assert.fail('unexpected network request'));
  for (const body of [[], null, 'text']) assert.equal((await handle(request('/api/quote', 'POST', body))).status, 400);
  const huge = request('/api/contact', 'POST', {}); huge.headers.set('content-length', String(5 * 1024 * 1024));
  assert.equal((await handle(huge)).status, 413);
});

test('a failed database operation cannot produce a successful enquiry', async () => {
  let inserted = false;
  const handle = createHandler(config, async url => {
    if (new URL(url).pathname.endsWith('/ladli_admit')) return ok(true);
    inserted = true; return new Response('storage unavailable', { status: 503 });
  });
  const result = await handle(request('/api/contact', 'POST', { name: 'Migration test', email: 'test@example.com', message: 'test only' }));
  assert.equal(result.status, 503); assert.equal((await result.json()).ok, false); assert.equal(inserted, true);
});

test('contact validation and honeypot preserve their contract', async () => {
  let inserts = 0;
  const handle = createHandler(config, async (url, init) => {
    if (new URL(url).pathname.endsWith('/ladli_admit')) return ok(true);
    assert.equal(new URL(url).pathname, '/rest/v1/inquiries');
    assert.equal(init.method, 'POST'); inserts++; return ok([{ id: 1 }]);
  });
  assert.equal((await handle(request('/api/contact', 'POST', { _honey: 'spam' }))).status, 200);
  assert.equal((await handle(request('/api/contact', 'POST', { name: 'Test', email: 'bad', message: 'x' }))).status, 400);
  const r = await handle(request('/api/contact', 'POST', { name: 'Test', email: 'test@example.com', message: 'x' }));
  assert.equal(r.status, 200); assert.deepEqual(await r.json(), { ok: true }); assert.equal(inserts, 1);
});

test('every private admin operation rejects an absent session', async () => {
  const handle = createHandler(config, async () => assert.fail('unexpected network request'));
  for (const path of ['/api/admin/inquiries', '/api/admin/visitors', '/api/admin/my-security-questions', '/api/admin/csrf-token'])
    assert.equal((await handle(request(path))).status, 401);
  assert.deepEqual(await (await handle(request('/api/admin/me'))).json(), { logged_in: false });
});

function authenticatedHarness({ expired = false, changed = false, forced = false, expectedCsrf = 'test-csrf-token' } = {}) {
  const sessionToken = 'A'.repeat(43), hash = 'private-test-hash'; let mutations = 0;
  const handle = createHandler(config, async (url, init) => {
    const p = new URL(url).pathname;
    if (p.endsWith('/admin_sessions') && init.method === 'GET') return ok([{
      token_hash: digest(sessionToken), admin_user_id: 1, password_fingerprint: changed ? 'stale' : digest(hash).slice(0, 16),
      csrf_token: expectedCsrf, expires_at: new Date(Date.now() + (expired ? -60000 : 60000)).toISOString(),
    }]);
    if (p.endsWith('/admin_users') && init.method === 'GET') return ok([{ id: 1, username: 'owner', password_hash: hash, must_change_password: forced ? 1 : 0 }]);
    if (p.endsWith('/admin_sessions') && init.method === 'DELETE') { mutations++; return new Response(null, { status: 204 }); }
    assert.fail('unexpected network operation ' + p);
  });
  const headers = { Cookie: '__Host-ladli_admin=' + sessionToken };
  return { handle, headers, mutationCount: () => mutations };
}

test('expired and password-invalidated sessions cannot read private data', async () => {
  for (const option of [{ expired: true }, { changed: true }]) {
    const h = authenticatedHarness(option);
    assert.equal((await h.handle(request('/api/admin/inquiries', 'GET', undefined, h.headers))).status, 401);
  }
});

test('all admin mutations require a matching CSRF token', async () => {
  const h = authenticatedHarness();
  for (const [path, method] of [['/api/admin/logout', 'POST'], ['/api/admin/visitors', 'POST'],
    ['/api/admin/inquiries/1', 'DELETE'], ['/api/admin/change-password', 'POST'], ['/api/admin/change-security-questions', 'POST']]) {
    assert.equal((await h.handle(request(path, method, {}, h.headers))).status, 403);
    assert.equal((await h.handle(request(path, method, {}, { ...h.headers, 'x-csrf-token': 'wrong' }))).status, 403);
  }
  assert.equal(h.mutationCount(), 0);
});

test('forced password change blocks enquiry access but allows CSRF and logout', async () => {
  const h = authenticatedHarness({ forced: true });
  const rejected = await h.handle(request('/api/admin/inquiries', 'GET', undefined, h.headers));
  assert.equal(rejected.status, 403); assert.equal((await rejected.json()).must_change_password, true);
  assert.equal((await h.handle(request('/api/admin/csrf-token', 'GET', undefined, h.headers))).status, 200);
  const logout = await h.handle(request('/api/admin/logout', 'POST', {}, { ...h.headers, 'x-csrf-token': 'test-csrf-token' }));
  assert.equal(logout.status, 200); assert.match(logout.headers.get('set-cookie'), /Max-Age=0/); assert.equal(h.mutationCount(), 1);
});

test('public security-question recovery remains disabled', async () => {
  const handle = createHandler(config, async () => assert.fail('unexpected network request'));
  for (const path of ['get-user-questions', 'verify-security-answers', 'reset-password-with-token'])
    assert.equal((await handle(request('/api/admin/' + path, 'POST', {}))).status, 403);
});

test('enquiry listing does not silently truncate at a server page cap', async () => {
  const token = 'A'.repeat(43), passwordHash = 'test-private-hash';
  const fixture = Array.from({ length: 5 }, (_, i) => ({ id: i + 1, kind: 'contact', name: 'Test',
    created_at: '2026-11-20T00:00:00Z', extra_json: '{}', status: 'new' }));
  const offsets = [];
  const handle = createHandler(config, async (resource, options) => {
    const url = new URL(resource);
    if (url.pathname.endsWith('/admin_sessions')) return ok([{ token_hash: digest(token), admin_user_id: 1,
      password_fingerprint: digest(passwordHash).slice(0, 16), csrf_token: 'csrf', expires_at: new Date(Date.now() + 60000).toISOString() }]);
    if (url.pathname.endsWith('/admin_users')) return ok([{ id: 1, username: 'owner', password_hash: passwordHash, must_change_password: 0 }]);
    assert.equal(url.pathname, '/rest/v1/inquiries'); assert.equal(options.method, 'GET');
    const offset = Number(url.searchParams.get('offset')); offsets.push(offset);
    return ok(fixture.slice(offset, offset + 2));
  });
  const response = await handle(request('/api/admin/inquiries', 'GET', undefined, { Cookie: '__Host-ladli_admin=' + token }));
  assert.equal(response.status, 200); assert.equal((await response.json()).length, 5);
  assert.deepEqual(offsets, [0, 2, 4, 5]);
});

test('invalid PDF content and failed uploads cannot create enquiry rows', async () => {
  let inserts = 0;
  const handle = createHandler(config, async url => {
    const path = new URL(url).pathname;
    if (path.endsWith('/ladli_admit')) return ok(true);
    if (path.includes('/storage/v1/')) return new Response('unavailable', { status: 503 });
    inserts++; assert.fail('An enquiry must not be written after an upload failure');
  });
  for (const [contents, expected] of [['not a PDF', 400], ['%PDF-1.7\ntest only', 503]]) {
    const form = new FormData();
    form.set('contact_name', 'Test'); form.set('email', 'test@example.com');
    form.set('attachment', new File([contents], 'test.pdf', { type: 'application/pdf' }));
    const response = await handle(new Request('https://edge.example/functions/v1/ladli-api/api/quote', {
      method: 'POST', body: form, headers: { 'x-ladli-proxy-token': config.proxyToken, Accept: 'application/json' },
    }));
    assert.equal(response.status, expected);
  }
  assert.equal(inserts, 0);
});
