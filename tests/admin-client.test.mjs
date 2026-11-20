import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function client() {
  const window = { location: { href: '/admin/login', pathname: '/admin/login' } };
  const context = vm.createContext({ window,
    document: { readyState: 'loading', addEventListener() {} },
    fetch: async path => new Response(JSON.stringify({ error: path.includes('login')
      ? 'Invalid username or password.' : 'Authentication required.' }), { status: 401 }),
  });
  vm.runInContext(readFileSync(new URL('../admin/assets/admin.js', import.meta.url), 'utf8'), context);
  return { api: vm.runInContext('Admin.api', context), window };
}

test('rejected credentials show the server error without navigating away', async () => {
  const { api, window } = client();
  window.location.href = 'unchanged';
  await assert.rejects(api('/api/admin/login', { method: 'POST', body: '{}' }), /Invalid username or password/);
  assert.equal(window.location.href, 'unchanged');
});

test('an expired session on a private route still returns to the login page', async () => {
  const { api, window } = client();
  window.location.href = '/admin';
  await assert.rejects(api('/api/admin/inquiries'), /Not authenticated/);
  assert.equal(window.location.href, '/admin/login');
});
