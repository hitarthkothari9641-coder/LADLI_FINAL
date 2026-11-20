"""One-time loopback-only owner setup. Plaintext passwords never leave the browser."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import html
from pathlib import Path
import re
import secrets
import urllib.request
import urllib.error

PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>LADLI owner setup</title>
<style>body{font:16px system-ui;background:#f2f6fc;color:#163157;margin:0;padding:40px 20px}main{max-width:460px;margin:auto;padding:32px;background:white;border-radius:20px;box-shadow:0 12px 40px #16315716}h1{margin-top:0}label{display:block;margin-top:18px;font-weight:600}input{box-sizing:border-box;width:100%;padding:12px;margin-top:6px;border:1px solid #bbc9da;border-radius:8px;font:inherit}button{width:100%;padding:14px;margin-top:24px;background:#1f6fe5;color:white;border:0;border-radius:9px;font:inherit;font-weight:700}button:disabled{opacity:.65}p{line-height:1.5}#status{white-space:pre-wrap}</style>
<main><h1>LADLI owner setup</h1><p>Create the administrator login for your fresh database. Save it privately. Your password stays in this browser; only its salted hash is sent to the database.</p>
<form id="setup" autocomplete="off"><label>Username<input name="username" value="admin" required pattern="[a-zA-Z0-9_.@-]{3,150}" autocomplete="username"></label>
<label>Owner email<input name="email" type="email" value="ladlielec@gmail.com" required autocomplete="email"></label>
<label>New password<input name="password" type="password" required minlength="12" maxlength="256" autocomplete="new-password"></label>
<label>Confirm password<input name="confirm" type="password" required minlength="12" maxlength="256" autocomplete="new-password"></label>
<button id="create">Create owner login</button></form><p id="status" role="status"></p></main>
<script>
const form=document.getElementById('setup'),status=document.getElementById('status'),button=document.getElementById('create');
const hex=bytes=>Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('');
form.addEventListener('submit',async event=>{event.preventDefault();status.textContent='';
 const password=form.elements.password.value;
 if(password!==form.elements.confirm.value){status.textContent='Passwords do not match.';return;}
 if(password.length<12||password.length>256){status.textContent='Use 12–256 characters.';return;}
 button.disabled=true;status.textContent='Creating your owner login…';
 try{
  const salt=hex(crypto.getRandomValues(new Uint8Array(16)));
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveBits']);
  const bits=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:new TextEncoder().encode(salt),iterations:1000000},key,256);
  const response=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.elements.username.value,email:form.elements.email.value,password_hash:'pbkdf2:sha256:1000000$'+salt+'$'+hex(bits)})});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Setup failed.');
  form.elements.password.value='';form.elements.confirm.value='';form.hidden=true;
  status.textContent='Owner login created successfully. Save your username and password privately. You can return to the chat now.';
 }catch(error){status.textContent=error.message;button.disabled=false;}
});
</script></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8174)
    parser.add_argument('--secrets', type=Path, default=Path('.dist/ladli-local-secrets.json'))
    parser.add_argument('--reset-owner', metavar='USERNAME', help='Recover this existing owner locally; does not create an account.')
    args = parser.parse_args()
    configuration = json.loads(args.secrets.read_text(encoding='utf-8'))
    project_url, api_key = configuration['url'], configuration['serviceKey']
    if not re.fullmatch(r'https://[a-z0-9]+\.supabase\.co', project_url):
        raise SystemExit('Unexpected project URL.')
    nonce = '/' + secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{args.port}'
    complete = args.secrets.parent / 'owner-setup-complete.json'
    page, owner = PAGE, None
    if args.reset_owner:
        headers = {'apikey': api_key}
        if not api_key.startswith('sb_secret_'):
            headers['Authorization'] = 'Bearer ' + api_key
        request = urllib.request.Request(project_url + '/rest/v1/admin_users?select=id,username,email,password_hash', headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            owners = json.load(response)
        if len(owners) != 1 or owners[0]['username'] != args.reset_owner:
            raise SystemExit('Recovery requires exactly one matching owner account.')
        owner = owners[0]
        complete = args.secrets.parent / 'owner-reset-complete.json'
        page = PAGE.replace('LADLI owner setup', 'LADLI owner recovery').replace(
            'Create the administrator login for your fresh database.', 'Set a new password for your existing website owner login.').replace(
            'Create owner login', 'Save new owner password').replace(
            'Creating your owner login…', 'Saving your new owner password…').replace(
            'Owner login created successfully.', 'Owner password updated successfully. Sign in on the Cloudflare preview with this new password.').replace(
            'value="admin"', 'value="' + html.escape(owner['username'], quote=True) + '" readonly').replace(
            'value="ladlielec@gmail.com"', 'value="' + html.escape(owner['email'], quote=True) + '" readonly')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body, content_type='application/json'):
            encoded = body.encode('utf-8') if isinstance(body, str) else json.dumps(body).encode('utf-8')
            self.send_response(status)
            for key, value in {'Content-Type': content_type, 'Content-Length': str(len(encoded)),
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer', 'Cross-Origin-Resource-Policy': 'same-origin',
                'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'"}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(encoded)

        def valid_target(self):
            return self.path == nonce and self.headers.get('Host') == f'127.0.0.1:{args.port}'

        def do_GET(self):
            if not self.valid_target():
                return self.reply(404, {'error': 'Not found.'})
            self.reply(200, page, 'text/html; charset=utf-8')

        def do_POST(self):
            if not self.valid_target() or self.headers.get('Origin') != origin:
                return self.reply(403, {'error': 'Forbidden.'})
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 2048 or self.headers.get('Content-Type') != 'application/json':
                return self.reply(400, {'error': 'Invalid setup request.'})
            try:
                data = json.loads(self.rfile.read(length))
                username, email, encoded = data['username'], data['email'], data['password_hash']
                if not re.fullmatch(r'[a-zA-Z0-9_.@-]{3,150}', username):
                    raise ValueError('Invalid username.')
                if not isinstance(email, str) or len(email)>255 or '@' not in email:
                    raise ValueError('Invalid owner email.')
                if not re.fullmatch(r'pbkdf2:sha256:1000000\$[a-f0-9]{32}\$[a-f0-9]{64}', encoded):
                    raise ValueError('Invalid password hash.')
                headers = {'apikey': api_key, 'Content-Type': 'application/json'}
                if not api_key.startswith('sb_secret_'):
                    headers['Authorization'] = 'Bearer ' + api_key
                if owner:
                    if username != owner['username'] or email != owner['email']:
                        raise ValueError('Recovery account cannot be changed.')
                    rpc, payload = 'ladli_change_password', {'p_user': owner['id'], 'p_expected_hash': owner['password_hash'], 'p_new_hash': encoded}
                else:
                    rpc, payload = 'ladli_provision_owner', {'p_username': username, 'p_hash': encoded, 'p_email': email}
                request = urllib.request.Request(project_url + '/rest/v1/rpc/' + rpc,
                    data=json.dumps(payload).encode(), headers=headers, method='POST')
                with urllib.request.urlopen(request, timeout=20) as response:
                    owner_id = json.load(response)
                if owner:
                    if owner_id is not True:
                        raise ValueError('Owner changed; restart recovery.')
                    owner_id = owner['id']
                complete.write_text(json.dumps({'username': username, 'email': email, 'id': owner_id}), encoding='utf-8')
                self.reply(200, {'ok': True})
            except (ValueError, KeyError, TypeError):
                self.reply(400, {'error': 'Check the username, email and password fields.'})
            except Exception:
                self.reply(503, {'error': 'Could not create the owner login. The account may already exist; return to the chat for verification.'})

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print('Owner setup page:', origin + nonce, flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
