import { createHandler } from './handler.mjs';

const keys: Record<string, string> = JSON.parse(Deno.env.get('SUPABASE_SECRET_KEYS') || '{}');

Deno.serve(createHandler({
  url: Deno.env.get('SUPABASE_URL'),
  serviceKey: keys.default || Deno.env.get('SUPABASE_SERVICE_ROLE_KEY'),
  proxyToken: Deno.env.get('LADLI_PROXY_TOKEN'),
  origins: Deno.env.get('LADLI_ALLOWED_ORIGINS'),
}));
