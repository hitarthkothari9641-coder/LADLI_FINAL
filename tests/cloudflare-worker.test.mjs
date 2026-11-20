import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../cloudflare/worker.mjs';

function assets(calls) {
  return { fetch: async request => {
    const path = new URL(request.url).pathname;
    calls.push(path);
    return new Response(request.method === 'HEAD' ? null : 'unchanged site content', {
      status: path.includes('missing') ? 404 : 200, headers: { 'X-Robots-Tag': 'noindex, nofollow' },
    });
  } };
}
test('homepage resolves to index.html without changing the public URL', async () => {
  const calls = [];
  const response = await worker.fetch(new Request('https://preview.example/'), { ASSETS: assets(calls) });
  assert.equal(response.status, 200); assert.deepEqual(calls, ['/index.html']);
  assert.equal(await response.text(), 'unchanged site content');
});

test('existing .html URLs and retired links preserve canonical routing', async () => {
  const calls = [], env = { ASSETS: assets(calls) };
  assert.equal((await worker.fetch(new Request('https://preview.example/resources.html'), env)).status, 200);
  assert.equal(calls.pop(), '/resources.html');
  for (const [source, target] of [['/index.html', '/'], ['/index', '/'], ['/test-colour.html', '/test-appearance.html'],
    ['/test-resistivity', '/test-tan-delta.html'], ['/resources', '/resources.html']]) {
    const response = await worker.fetch(new Request('https://preview.example' + source), env);
    assert.equal(response.status, 301); assert.equal(response.headers.get('location'), 'https://preview.example' + target);
  }
});

test('preview indexing exclusions do not leak into production responses or robots', async () => {
  const env = { ASSETS: assets([]) };
  assert.match((await worker.fetch(new Request('https://preview.example/'), env)).headers.get('x-robots-tag'), /noindex/);
  const production = { ...env, PREVIEW_MODE: 'false' };
  const response = await worker.fetch(new Request('https://ladlilab.com/'), production);
  assert.equal(response.headers.has('x-robots-tag'), false);
  assert.equal(response.headers.get('X-Frame-Options'), 'DENY');
  assert.match(response.headers.get('Content-Security-Policy'), /connect-src 'self'/);
  const robots = await (await worker.fetch(new Request('https://ladlilab.com/robots.txt'), production)).text();
  assert.match(robots, /Sitemap: https:\/\/ladlilab.com\/sitemap.xml/);
  assert.doesNotMatch(robots, /^Disallow: \/$/m);
  const preview = await worker.fetch(new Request('https://ladli-app.ladlielec.workers.dev/robots.txt'), production);
  assert.match(preview.headers.get('X-Robots-Tag'), /noindex/);
  assert.match(await preview.text(), /^Disallow: \/$/m);
});

test('static admin pages retain no-store and noindex protection', async () => {
  const calls = [];
  const response = await worker.fetch(new Request('https://ladlilab.com/admin/login'), { ASSETS: assets(calls), PREVIEW_MODE: 'false' });
  assert.deepEqual(calls, ['/admin/login.html']);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.match(response.headers.get('X-Robots-Tag'), /noindex/);
});

test('API proxy overwrites forged identity headers and preserves secure session cookies', async t => {
  let upstream;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    upstream = { url, options };
    return new Response('{"ok":true}', { headers: { 'Set-Cookie': '__Host-ladli_admin=opaque; Secure; HttpOnly; Path=/' } });
  });
  const response = await worker.fetch(new Request('https://ladlilab.com/api/admin/me', {
    headers: { 'cf-connecting-ip': '192.0.2.10', 'x-ladli-client-ip': 'forged', 'x-ladli-proxy-token': 'forged', 'x-forwarded-for': 'forged' },
  }), { SUPABASE_PROJECT_URL: 'https://project.supabase.co', LADLI_PROXY_TOKEN: 'server-token' });
  assert.equal(upstream.url.origin, 'https://project.supabase.co');
  assert.equal(upstream.url.pathname, '/functions/v1/ladli-api/api/admin/me');
  assert.equal(upstream.options.headers.get('x-ladli-client-ip'), '192.0.2.10');
  assert.equal(upstream.options.headers.get('x-ladli-proxy-token'), 'server-token');
  assert.equal(upstream.options.headers.has('x-forwarded-for'), false);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.match(response.headers.get('Set-Cookie'), /Secure; HttpOnly/);
});

test('an unconfigured API proxy fails explicitly instead of displaying a false success', async () => {
  const response = await worker.fetch(new Request('https://preview.example/api/contact', { method: 'POST' }), {});
  assert.equal(response.status, 503); assert.equal((await response.json()).ok, false);
});
