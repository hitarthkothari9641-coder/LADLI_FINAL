const securityHeaders = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
  'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://*.google.com https://*.googleapis.com https://*.gstatic.com https://*.openstreetmap.org; frame-src 'self' https://www.google.com https://maps.google.com https://www.google.co.in https://www.openstreetmap.org; connect-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; frame-ancestors 'none'",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname === 'www.ladlilab.com') {
      url.hostname = 'ladlilab.com';
      url.protocol = 'https:';
      return new Response(null, { status: ['GET', 'HEAD'].includes(request.method) ? 301 : 308,
        headers: { ...securityHeaders, Location: url.href } });
    }
    const path = url.pathname;
    const production = env.PREVIEW_MODE === 'false' && ['ladlilab.com', 'www.ladlilab.com'].includes(url.hostname);
    const staticFetch = async assetRequest => {
      if (env.ASSETS) return env.ASSETS.fetch(assetRequest);
      if (!env.STATIC_SITE_URL) return new Response('Static hosting is not configured.', { status: 503 });
      const target = new URL(new URL(assetRequest.url).pathname + new URL(assetRequest.url).search, env.STATIC_SITE_URL);
      const forwarded = new Headers(assetRequest.headers);
      for (const key of ['cookie', 'authorization', 'x-ladli-proxy-token', 'host']) forwarded.delete(key);
      return fetch(target, { method: assetRequest.method, headers: forwarded, redirect: 'follow' });
    };
    const headers = new Headers(securityHeaders);
    if (!production) headers.set('X-Robots-Tag', 'noindex, nofollow');
    const wrap = response => {
      const result = new Response(response.body, response);
      if (production && !path.startsWith('/admin')) result.headers.delete('X-Robots-Tag');
      for (const [key, value] of headers) result.headers.set(key, value);
      return result;
    };
    if (path.startsWith('/api/') || ['/ready', '/health', '/healthz'].includes(path)) {
      if (!env.LADLI_PROXY_TOKEN || !env.SUPABASE_PROJECT_URL)
        return wrap(Response.json({ ok: false, error: 'Migration configuration is incomplete.' }, { status: 503 }));
      const upstream = new URL(`/functions/v1/ladli-api${path}${url.search}`, env.SUPABASE_PROJECT_URL);
      const forwardHeaders = new Headers(request.headers);
      // Override client-controlled forwarding fields with Cloudflare's verified IP.
      forwardHeaders.set('x-ladli-client-ip', request.headers.get('cf-connecting-ip') || 'unknown');
      forwardHeaders.set('x-ladli-proxy-token', env.LADLI_PROXY_TOKEN);
      forwardHeaders.delete('x-forwarded-for');
      forwardHeaders.delete('host');
      try {
        const response = await fetch(upstream, {
          method: request.method, headers: forwardHeaders,
          body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
          redirect: 'manual', signal: AbortSignal.timeout(45000),
        });
        const result = wrap(response);
        result.headers.set('Cache-Control', 'no-store');
        return result;
      } catch {
        return wrap(Response.json({ ok: false, error: 'Service temporarily unavailable.' }, { status: 503 }));
      }
    }
    if (path === '/robots.txt') {
      const rules = production
        ? 'User-agent: *\nDisallow: /admin/\nDisallow: /api/\nDisallow: /data/\n\nSitemap: https://ladlilab.com/sitemap.xml\n'
        : 'User-agent: *\nDisallow: /\n';
      return wrap(new Response(rules, { headers: { 'Content-Type': 'text/plain' } }));
    }
    const redirect = destination => wrap(Response.redirect(new URL(destination, url).href, 301));
    if (['/index', '/index.html'].includes(path)) return redirect('/');
    if (['/test-colour', '/test-colour.html'].includes(path)) return redirect('/test-appearance.html');
    if (['/test-resistivity', '/test-resistivity.html'].includes(path)) return redirect('/test-tan-delta.html');
    const adminPages = { '/admin': 'dashboard', '/admin/': 'dashboard', '/admin/login': 'login',
      '/admin/settings': 'settings', '/admin/visitors': 'visitors',
      '/admin/forgot-password': 'owner_recovery', '/admin/setup-security': 'setup_security' };
    const assetUrl = new URL(url);
    if (path === '/') assetUrl.pathname = '/index.html';
    else if (adminPages[path]) assetUrl.pathname = `/admin/${adminPages[path]}.html`;
    else if (/^\/[a-z0-9-]+$/.test(path)) {
      const candidate = new URL(url); candidate.pathname += '.html';
      const page = await staticFetch(new Request(candidate, { method: 'HEAD' }));
      if (page.status === 200) return redirect(`${path}.html${url.search}`);
    }
    const response = await staticFetch(new Request(assetUrl, request));
    const result = wrap(response);
    if (path.startsWith('/admin')) {
      result.headers.set('Cache-Control', 'no-store');
      result.headers.set('X-Robots-Tag', 'noindex, nofollow');
    }
    return result;
  },
};
