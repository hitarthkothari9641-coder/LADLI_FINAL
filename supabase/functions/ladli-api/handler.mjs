import { createHash, randomBytes, timingSafeEqual, pbkdf2, scrypt } from 'node:crypto';
import { promisify } from 'node:util';
import { Buffer } from 'node:buffer';

const derivePbkdf2 = promisify(pbkdf2);
const deriveScrypt = promisify(scrypt);
const COOKIE = '__Host-ladli_admin';
const BUCKET = 'ladli-attachments';
const MAX_BODY = 4 * 1024 * 1024;
const MAX_PDF = 3 * 1024 * 1024;
const sha256 = value => createHash('sha256').update(value).digest('hex');
const secret = () => randomBytes(32).toString('base64url');
const fingerprint = hash => sha256(hash).slice(0, 16);
const timestamp = () => new Date().toISOString();
const cookie = (name, value, seconds) => `${name}=${value}; Path=/; Max-Age=${seconds}; HttpOnly; Secure; SameSite=Lax`;
const safeEqual = (a, b) => {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const left = Buffer.from(a), right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
};

export async function hashPassword(value) {
  const salt = randomBytes(16).toString('hex');
  const derived = await derivePbkdf2(value, salt, 1000000, 32, 'sha256');
  return `pbkdf2:sha256:1000000$${salt}$${derived.toString('hex')}`;
}

// Keep existing Werkzeug hashes valid when a historical database is restored.
export async function verifyPassword(encoded, value) {
  if (typeof encoded !== 'string' || typeof value !== 'string' || value.length > 256) return false;
  try {
    const [method, salt, expected, extra] = encoded.split('$');
    if (extra !== undefined || !salt || !/^[a-f0-9]+$/.test(expected)) return false;
    const options = method.split(':');
    let derived;
    if (options[0] === 'pbkdf2' && options[1] === 'sha256' && options.length === 3) {
      const iterations = Number(options[2]);
      if (!Number.isInteger(iterations) || iterations < 1000 || iterations > 2000000 || expected.length !== 64) return false;
      derived = await derivePbkdf2(value, salt, iterations, 32, 'sha256');
    } else if (options[0] === 'scrypt' && options.length === 4) {
      const [N, r, p] = options.slice(1).map(Number);
      if (![16384, 32768].includes(N) || r !== 8 || p !== 1 || expected.length !== 128) return false;
      derived = await deriveScrypt(value, salt, 64, { N, r, p, maxmem: 64 * 1024 * 1024 });
    } else return false;
    return safeEqual(derived.toString('hex'), expected);
  } catch { return false; }
}

class HttpError extends Error {
  constructor(status, message, detail = {}) { super(message); this.status = status; this.detail = detail; }
}
const fail = (status, message, detail) => { throw new HttpError(status, message, detail); };
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', ...headers },
});
function readCookies(request) {
  const values = Object.create(null);
  for (const part of (request.headers.get('cookie') || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0) values[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return values;
}

async function readBody(request) {
  if (Number(request.headers.get('content-length')) > MAX_BODY) fail(413, 'Request is too large.');
  const reader = request.body?.getReader();
  const chunks = []; let size = 0;
  if (reader) {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY) { await reader.cancel(); fail(413, 'Request is too large.'); }
      chunks.push(value);
    }
  }
  const bytes = Buffer.concat(chunks);
  const type = request.headers.get('content-type') || '';
  let data = {}; let attachment = null;
  try {
    if (type.includes('application/json') && bytes.length) {
      data = JSON.parse(bytes.toString('utf8'));
      if (!data || typeof data !== 'object' || Array.isArray(data)) fail(400, 'Request body must be a JSON object.');
    } else if (type.includes('multipart/form-data') || type.includes('application/x-www-form-urlencoded')) {
      const form = await new Response(bytes, { headers: { 'Content-Type': type } }).formData();
      data = Object.fromEntries([...form.entries()].filter(([, value]) => typeof value === 'string'));
      attachment = form.get('attachment');
      if (typeof attachment === 'string') attachment = null;
    } else if (bytes.length) fail(400, 'Unsupported request format.');
  } catch (error) {
    if (error instanceof HttpError) throw error;
    fail(400, 'Invalid request body.');
  }
  for (const key of ['username', 'password', 'current_password', 'new_password', 'token',
    'name', 'contact_name', 'email', 'phone', 'company', 'company_organisation', 'message', 'status', 'mode', '_honey']) {
    if (key in data && typeof data[key] !== 'string') fail(400, `${key} must be text.`);
  }
  for (const [key, value] of Object.entries(data)) {
    if (typeof value === 'string' && value.length > 20000) fail(400, `${key} is too long.`);
  }
  return { data, attachment };
}

function validAnswers(answers) {
  return Array.isArray(answers) && answers.length === 3 &&
    answers.every(a => a && Number.isInteger(a.question_id) && typeof a.answer === 'string' &&
      a.answer.trim().length >= 2 && a.answer.length <= 200) &&
    new Set(answers.map(a => a.question_id)).size === 3;
}

export function createHandler(config, fetcher = fetch) {
  const base = config.url?.replace(/\/$/, '');
  const authHeaders = { apikey: config.serviceKey,
    ...(config.serviceKey?.startsWith('sb_secret_') ? {} : { Authorization: `Bearer ${config.serviceKey}` }) };
  async function rest(resource, { method = 'GET', query = {}, body, prefer } = {}) {
    const url = new URL(`${base}/rest/v1/${resource}`);
    for (const [key, value] of Object.entries(query)) url.searchParams.set(key, String(value));
    const response = await fetcher(url, {
      method, headers: { ...authHeaders, 'Content-Type': 'application/json',
        ...(prefer ? { Prefer: prefer } : {}) },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error('Database request failed');
    return response.status === 204 ? null : response.json();
  }
  const rpc = (name, body) => rest(`rpc/${name}`, { method: 'POST', body });
  const first = async (table, query) => (await rest(table, { query: { select: '*', ...query, limit: 1 } }))[0];
  const update = (table, query, body) => rest(table, { method: 'PATCH', query, body, prefer: 'return=representation' });
  const insert = (table, body) => rest(table, { method: 'POST', body, prefer: 'return=representation' });
  const remove = (table, query) => rest(table, { method: 'DELETE', query, prefer: 'return=minimal' });
  async function allRows(table, query) {
    const rows = [];
    for (let offset = 0; ;) {
      const page = await rest(table, { query: { ...query, limit: 1000, offset } });
      if (!page.length) return rows;
      rows.push(...page);
      offset += page.length;
    }
  }
  async function admit(key, maximum, seconds) {
    if (!await rpc('ladli_admit', { p_bucket: sha256(key), p_limit: maximum, p_window: seconds }))
      fail(429, 'Too many attempts. Please try again later.');
  }
  async function session(request, allowMissing = false) {
    const raw = readCookies(request)[COOKIE];
    if (!raw || !/^[A-Za-z0-9_-]{43}$/.test(raw)) {
      if (allowMissing) return null;
      fail(401, 'Not authenticated');
    }
    const stored = await first('admin_sessions', { token_hash: `eq.${sha256(raw)}` });
    const user = stored && Date.parse(stored.expires_at) > Date.now() &&
      await first('admin_users', { id: `eq.${stored.admin_user_id}` });
    if (!user || stored.password_fingerprint !== fingerprint(user.password_hash)) {
      if (allowMissing) return null;
      fail(401, 'Session expired. Please log in again.');
    }
    return { user, stored };
  }
  async function storage(path, options) {
    const response = await fetcher(`${base}/storage/v1/${path}`, {
      ...options, headers: { ...authHeaders, ...options?.headers }, signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error('Attachment storage request failed');
    return response;
  }
  function validatePerson(data, isQuote) {
    const name = (data.contact_name || data.name || '').trim();
    if (!name || name.length > 200 || (!isQuote && !(data.message || '').trim()))
      fail(400, isQuote ? 'Contact name is required.' : 'Name and message are required.');
    const email = (data.email || '').trim(), phone = (data.phone || '').trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 255) fail(400, 'Invalid email address.');
    if (phone && !/^\d{7,15}$/.test(phone.replace(/[\s\-()+]/g, ''))) fail(400, 'Invalid phone number.');
    return { name, email, phone };
  }

  return async function handle(request) {
    const url = new URL(request.url);
    // The hosted gateway strips /functions/v1 before forwarding to Deno.
    const path = url.pathname.replace(/^(?:\/functions\/v1)?\/ladli-api(?=\/|$)/, '') || '/';
    try {
      if (path === '/healthz' || path === '/health') return json({ status: 'ok' });
      if (!base || !config.serviceKey || !config.proxyToken || config.proxyToken.length < 32)
        fail(503, 'Server configuration is incomplete.');
      if (!safeEqual(request.headers.get('x-ladli-proxy-token'), config.proxyToken)) fail(403, 'Forbidden.');
      const origin = request.headers.get('origin');
      const allowed = (config.origins || '').split(',').map(s => s.trim()).filter(Boolean);
      if (origin && !allowed.includes(origin)) fail(403, 'Forbidden origin.');
      if (request.method === 'OPTIONS') return new Response(null, { status: 204 });
      const ip = request.headers.get('x-ladli-client-ip') || 'unknown';
      if (path === '/ready') {
        await first('visitor_stats', { id: 'eq.1' });
        return json({ status: 'ok', database: 'connected', schema: 'ready' });
      }
      if (['/api/admin/get-user-questions', '/api/admin/verify-security-answers', '/api/admin/reset-password-with-token'].includes(path))
        fail(403, 'Contact the site owner to arrange an administrator password reset.');
      const write = !['GET', 'HEAD', 'OPTIONS'].includes(request.method);
      const { data, attachment } = write ? await readBody(request) : { data: {}, attachment: null };

      if (path === '/api/contact' || path === '/api/quote') {
        if (request.method !== 'POST') fail(405, 'Method not allowed.');
        const isQuote = path.endsWith('/quote');
        await admit(`${isQuote ? 'quote' : 'contact'}:${ip}`, isQuote ? 5 : 10, 60);
        if (data._honey) return json({ ok: true });
        const person = validatePerson(data, isQuote);
        const excluded = new Set(['contact_name', 'name', 'company', 'company_organisation', 'phone', 'email',
          'message', '_kind', '_next', '_honey', 'attachment']);
        const extra = Object.fromEntries(Object.entries(data).filter(([key]) => !excluded.has(key)));
        let objectKey = null, originalName = null, size = null;
        if (attachment && attachment.name) {
          if (!isQuote || !attachment.name.toLowerCase().endsWith('.pdf') ||
            !['application/pdf', 'application/octet-stream'].includes(attachment.type)) fail(400, 'Attachment must be a PDF file.');
          if (!attachment.size || attachment.size > MAX_PDF) fail(400, 'Attach a PDF no larger than 3 MB.');
          const bytes = new Uint8Array(await attachment.arrayBuffer());
          if (Buffer.from(bytes.subarray(0, 5)).toString() !== '%PDF-') fail(400, "That file doesn't look like a valid PDF.");
          objectKey = `attachments/${randomBytes(16).toString('hex')}.pdf`;
          originalName = attachment.name.split(/[\\/]/).pop().replace(/[^\w.\- ]/g, '_').slice(0, 180) || 'attachment.pdf';
          size = attachment.size;
          await storage(`object/${BUCKET}/${objectKey}`, { method: 'POST', body: bytes,
            headers: { 'Content-Type': 'application/pdf', 'x-upsert': 'false' } });
        }
        try {
          await insert('inquiries', { kind: isQuote ? 'quote' : 'contact', ...person,
            company: (data.company || data.company_organisation || '').trim(), message: data.message || '',
            extra_json: isQuote ? JSON.stringify(extra) : null, status: 'new', created_at: timestamp(),
            attachment_filename: null, attachment_original_name: originalName, attachment_size_bytes: size,
            s3_object_key: objectKey ? `supabase://${BUCKET}/${objectKey}` : null });
        } catch (error) {
          if (objectKey) {
            try { await storage(`object/${BUCKET}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prefixes: [objectKey] }) }); }
            catch { /* no false success; the orphan can be reconciled by the owner */ }
          }
          throw error;
        }
        if (request.headers.get('accept')?.includes('application/json') || request.headers.get('content-type')?.includes('application/json'))
          return json({ ok: true });
        return new Response(null, { status: 303, headers: { Location: '/thank-you.html', 'Cache-Control': 'no-store' } });
      }
      if (path === '/api/visitor-register' || path === '/api/visitor-count') {
        if (request.method !== (path.endsWith('register') ? 'POST' : 'GET')) fail(405, 'Method not allowed.');
        let raw = null;
        if (path.endsWith('register')) {
          await admit(`visit:${ip}`, 30, 60);
          if (!/bot|crawler|spider/i.test(request.headers.get('user-agent') || 'bot')) {
            const candidate = readCookies(request).ladli_visitor_id || data.visitor_id;
            raw = typeof candidate === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(candidate) ? candidate : randomBytes(16).toString('hex');
          }
        }
        const result = await rpc('ladli_visit', { p_token: raw ? sha256(raw) : null });
        return json({ ok: true, new_visitor: result.new_visitor, count: result.count, mode: result.mode }, 200,
          raw ? { 'Set-Cookie': cookie('ladli_visitor_id', raw, 31536000) } : {});
      }

      if (path === '/api/admin/login') {
        if (request.method !== 'POST') fail(405, 'Method not allowed.');
        await admit(`login:${ip}`, 10, 60);
        const username = (data.username || '').trim(), password = data.password || '';
        if (!username || username.length > 150 || !password || password.length > 256) fail(401, 'Invalid username or password.');
        if (await rpc('ladli_login_locked', { p_username: username.toLowerCase(), p_ip: ip }))
          fail(429, 'Too many failed attempts. Try again in 15 minutes.');
        const user = await first('admin_users', { username: `eq.${username}` });
        const valid = user && await verifyPassword(user.password_hash, password);
        await insert('login_attempts', { username: username.toLowerCase(), ip_address: ip, attempted_at: timestamp(), success: valid ? 1 : 0 });
        if (!valid) fail(401, 'Invalid username or password.');
        await remove('login_attempts', { username: `eq.${username.toLowerCase()}`, ip_address: `eq.${ip}` });
        const token = secret();
        await insert('admin_sessions', { token_hash: sha256(token), admin_user_id: user.id,
          password_fingerprint: fingerprint(user.password_hash), csrf_token: secret(),
          expires_at: new Date(Date.now() + 30 * 60000).toISOString() });
        return json({ ok: true, username: user.username, must_change_password: !!user.must_change_password,
          security_setup_completed: !!user.security_setup_completed }, 200, { 'Set-Cookie': cookie(COOKIE, token, 1800) });
      }
      if (path === '/api/admin/me') {
        if (request.method !== 'GET') fail(405, 'Method not allowed.');
        const s = await session(request, true);
        return json(s ? { logged_in: true, username: s.user.username, must_change_password: !!s.user.must_change_password,
          security_setup_completed: !!s.user.security_setup_completed } : { logged_in: false });
      }
      if (path === '/api/admin/security-questions') {
        if (request.method !== 'GET') fail(405, 'Method not allowed.');
        return json(await rest('security_questions', { query: { select: 'id,question', order: 'id' } }));
      }
      if (!path.startsWith('/api/admin/')) fail(404, 'Not found.');
      const s = await session(request);
      if (write && !safeEqual(request.headers.get('x-csrf-token'), s.stored.csrf_token)) fail(403, 'Forbidden.');
      if (path === '/api/admin/csrf-token' && request.method === 'GET') return json({ csrf_token: s.stored.csrf_token });
      if (s.user.must_change_password && !['/api/admin/change-password', '/api/admin/logout'].includes(path))
        fail(403, 'Password change required.', { must_change_password: true });

      if (path === '/api/admin/logout' && request.method === 'POST') {
        await remove('admin_sessions', { token_hash: `eq.${s.stored.token_hash}` });
        return json({ ok: true }, 200, { 'Set-Cookie': cookie(COOKIE, '', 0) });
      }
      if (path === '/api/admin/change-password' && request.method === 'POST') {
        const password = data.new_password || '';
        if (password.length < 12 || password.length > 256) fail(400, 'Password must be between 12 and 256 characters.');
        if (!await verifyPassword(s.user.password_hash, data.current_password || '')) fail(400, 'Current password is incorrect.');
        const history = await rest('password_history', { query: { select: 'password_hash', username: `eq.${s.user.username}`, order: 'id.desc', limit: 5 } });
        for (const previous of [s.user, ...history]) {
          if (await verifyPassword(previous.password_hash, password)) fail(400, 'Choose a password you have not used recently.');
        }
        if (!await rpc('ladli_change_password', { p_user: s.user.id, p_expected_hash: s.user.password_hash, p_new_hash: await hashPassword(password) }))
          fail(409, 'Account changed. Please log in again.');
        return json({ ok: true }, 200, { 'Set-Cookie': cookie(COOKIE, '', 0) });
      }
      if (path === '/api/admin/security-setup-status' && request.method === 'GET')
        return json({ completed: !!s.user.security_setup_completed });
      if (path === '/api/admin/my-security-questions' && request.method === 'GET') {
        const saved = await rest('admin_security_answers', { query: { select: 'question_id', admin_user_id: `eq.${s.user.id}` } });
        const questions = await rest('security_questions', { query: { select: 'id,question', order: 'id' } });
        return json({ questions: questions.filter(q => saved.some(a => a.question_id === q.id)).map(q => ({ question_id: q.id, question: q.question })) });
      }
      if (['/api/admin/setup-security-questions', '/api/admin/change-security-questions'].includes(path) && request.method === 'POST') {
        const setup = path.endsWith('/setup-security-questions');
        const answers = setup ? data.answers : data.new_answers;
        if (!setup && !await verifyPassword(s.user.password_hash, data.current_password || '')) fail(400, 'Current password is incorrect.');
        if (setup && s.user.security_setup_completed) fail(400, 'Security questions already configured. Use the change flow.');
        if (!validAnswers(answers)) fail(400, 'Exactly 3 different questions and valid answers are required.');
        const hashed = [];
        for (const a of answers) hashed.push({ question_id: a.question_id, answer_hash: await hashPassword(a.answer.trim().toLowerCase().replace(/\s+/g, ' ')) });
        if (!await rpc('ladli_set_questions', { p_user: s.user.id, p_expected_hash: s.user.password_hash, p_answers: hashed, p_setup_only: setup }))
          fail(409, 'Account changed. Please log in again.');
        return json({ ok: true });
      }
      if (path === '/api/admin/inquiries' && request.method === 'GET') {
        const query = { select: '*', order: 'created_at.desc,id.desc' };
        if (['contact', 'quote'].includes(url.searchParams.get('kind'))) query.kind = `eq.${url.searchParams.get('kind')}`;
        if (['new', 'contacted', 'closed'].includes(url.searchParams.get('status'))) query.status = `eq.${url.searchParams.get('status')}`;
        const rows = await allRows('inquiries', query);
        return json(rows.map(row => {
          let extra = {}; try { extra = JSON.parse(row.extra_json || '{}'); } catch { /* legacy malformed metadata */ }
          const { id, kind, name, company, phone, email, message, status, created_at, attachment_original_name, attachment_size_bytes } = row;
          return { id, kind, name, company, phone, email, message, status, created_at, extra,
            created_at_display: new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(created_at)),
            has_attachment: !!(row.attachment_filename || row.s3_object_key), attachment_original_name, attachment_size_bytes };
        }));
      }
      const inquiry = path.match(/^\/api\/admin\/inquiries\/(\d+)(?:\/(status|attachment))?$/);
      if (inquiry) {
        const id = Number(inquiry[1]);
        const row = await first('inquiries', { id: `eq.${id}` });
        if (!row) fail(404, 'Inquiry not found.');
        if (inquiry[2] === 'status' && request.method === 'POST') {
          if (!['new', 'contacted', 'closed'].includes(data.status)) fail(400, 'Invalid status.');
          const updated = await update('inquiries', { id: `eq.${id}` }, { status: data.status });
          if (!updated.length) fail(404, 'Inquiry not found.');
          return json({ ok: true });
        }
        const prefix = `supabase://${BUCKET}/`;
        const key = row.s3_object_key?.startsWith(prefix) ? row.s3_object_key.slice(prefix.length) : null;
        if (key && !/^attachments\/[a-f0-9]{32}\.pdf$/.test(key)) fail(503, 'Attachment storage is unavailable.');
        if (inquiry[2] === 'attachment' && request.method === 'GET') {
          if (!key) fail(row.s3_object_key || row.attachment_filename ? 503 : 404, 'Attachment is not available in the new storage.');
          const file = await storage(`object/authenticated/${BUCKET}/${key}`, { method: 'GET' });
          const name = encodeURIComponent(row.attachment_original_name || 'attachment.pdf');
          return new Response(file.body, { headers: { 'Content-Type': 'application/pdf', 'Cache-Control': 'no-store',
            'Content-Disposition': `attachment; filename="attachment.pdf"; filename*=UTF-8''${name}`, 'X-Content-Type-Options': 'nosniff' } });
        }
        if (!inquiry[2] && request.method === 'DELETE') {
          if ((row.s3_object_key || row.attachment_filename) && !key) fail(503, 'Attachment storage unavailable; enquiry retained.');
          if (key) await storage(`object/${BUCKET}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prefixes: [key] }) });
          await remove('inquiries', { id: `eq.${id}` });
          return json({ ok: true });
        }
      }
      if (path === '/api/admin/visitors') {
        if (request.method === 'POST') {
          const changes = { updated_at: timestamp() };
          if ('mode' in data) {
            if (!['auto', 'manual', 'hidden'].includes(data.mode)) fail(400, 'Mode must be auto, manual or hidden.');
            changes.mode = data.mode;
          }
          if ('manual_count' in data) {
            if (typeof data.manual_count === 'boolean' || !/^\d+$/.test(String(data.manual_count)) || Number(data.manual_count) > 2147483647)
              fail(400, 'Manual count must be a non-negative whole number.');
            changes.manual_count = Number(data.manual_count);
          }
          await update('visitor_stats', { id: 'eq.1' }, changes);
        } else if (request.method !== 'GET') fail(405, 'Method not allowed.');
        const result = await rpc('ladli_visit', { p_token: null });
        return json({ ok: true, unique_count: result.unique_count, manual_count: result.manual_count, mode: result.mode, updated_at: result.updated_at });
      }
      return json({ ok: false, error: 'Not found.' }, 404);
    } catch (error) {
      if (error instanceof HttpError) return json({ ok: false, error: error.message, ...error.detail }, error.status);
      console.error('LADLI backend operation failed. No request data or credentials logged.');
      return json({ ok: false, error: 'Service temporarily unavailable. Please try again shortly.' }, 503);
    }
  };
}
