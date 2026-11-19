"""One narrowly scoped, OAuth-protected MCP reader. No business write tools.

OAuth records live separately from repair/payment databases. No raw tokens,
authorization URLs, provider responses, or customer contact data are logged.
"""
import base64
import hashlib
import html
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlsplit

from payment_monitor_rules import TAIPEI, find_candidates

SCOPE = 'repair.payments.read'
PREFIX = '/payment-monitor'
MCP = PREFIX + '/mcp'
CALLBACKS = frozenset(('https://chatgpt.com/connector_platform_oauth_redirect',))
SUPPORTED = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}


def digest(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def one(values, name, default=''):
    result = values.get(name, [default])
    if len(result) != 1 or not isinstance(result[0], str):
        raise ValueError('invalid_request')
    return result[0]


def allowed_callback(value):
    # No arbitrary redirects, localhost redirects, URL fetching, or SSRF.
    return isinstance(value, str) and (value in CALLBACKS or bool(re.fullmatch(
        r'https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{8,128}', value)))


class MonitorConnector:
    def __init__(self, server, clock=time.time):
        self.s, self.clock = server, clock
        self.base = server['BASE']
        self.resource = self.base + MCP
        self.db = server['DATA_DIR'] / 'payment-monitor-oauth.sqlite3'
        self.scan_lock = threading.Lock()
        self.last_scan = 0
        self.rate_lock = threading.Lock()
        self.rates = {}

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def init(self):
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY, redirect TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, client TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, client TEXT NOT NULL,
                redirect TEXT NOT NULL, state TEXT NOT NULL, challenge TEXT NOT NULL,
                browser TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS codes(hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL,
                redirect TEXT NOT NULL, challenge TEXT NOT NULL, expires REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL,
                kind TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, checked REAL NOT NULL,
                payload TEXT NOT NULL);
            ''')
        try:
            self.db.chmod(0o600)
        except OSError:
            pass

    def limited(self, key, maximum):
        with self.rate_lock:
            now = self.clock()
            self.rates = {k: v for k, v in self.rates.items() if v[0] > now - 3600}
            stamp, count = self.rates.get(key, (now, 0))
            self.rates[key] = (stamp, count + 1)
            return count >= maximum

    def metadata(self):
        return {'issuer': self.base,
                'authorization_endpoint': self.base + PREFIX + '/authorize',
                'token_endpoint': self.base + PREFIX + '/token',
                'registration_endpoint': self.base + PREFIX + '/register',
                'revocation_endpoint': self.base + PREFIX + '/revoke',
                'response_types_supported': ['code'],
                'grant_types_supported': ['authorization_code', 'refresh_token'],
                'token_endpoint_auth_methods_supported': ['none'],
                'code_challenge_methods_supported': ['S256'],
                'authorization_response_iss_parameter_supported': True,
                'scopes_supported': [SCOPE]}

    def challenge(self, handler):
        return handler.send(401, {'error': 'authorization_required'}, {
            'WWW-Authenticate': 'Bearer resource_metadata="' + self.base +
            '/.well-known/oauth-protected-resource' + MCP + '", scope="' + SCOPE + '"'})

    def valid_access(self, header):
        if not isinstance(header, str) or not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}', header):
            return False
        with self.connect() as c:
            return bool(c.execute('''SELECT 1 FROM tokens t JOIN grants g ON g.id=t.grant_id
                WHERE t.hash=? AND t.kind='access' AND t.used=0 AND t.expires>?
                AND g.revoked=0 AND g.expires>?''', (digest(header[7:]), self.clock(), self.clock())).fetchone())

    def page(self, handler, status, body, headers=None):
        raw = ('<!doctype html><html lang="zh-Hant"><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1">'
               '<title>PetPivot 唯讀巡檢授權</title><body>' + body + '</body></html>').encode()
        handler.send_response(status)
        for k, v in [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store'),
                     ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'),
                     ('Content-Security-Policy', "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
                     *(headers or {}).items()]:
            handler.send_header(k, v)
        handler.end_headers()
        handler.wfile.write(raw)

    def authorize(self, handler, query):
        values = parse_qs(query, keep_blank_values=True, max_num_fields=12)
        client, redirect = one(values, 'client_id'), one(values, 'redirect_uri')
        with self.connect() as c:
            row = c.execute('SELECT redirect FROM clients WHERE id=?', (client,)).fetchone()
        if (not row or redirect != row['redirect'] or not allowed_callback(redirect)
                or one(values, 'response_type') != 'code'
                or one(values, 'scope') != SCOPE
                or one(values, 'resource') != self.resource
                or one(values, 'code_challenge_method') != 'S256'
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', one(values, 'code_challenge'))
                or not 16 <= len(one(values, 'state')) <= 1024):
            raise ValueError('invalid_request')
        user = handler.user()
        if not user or not user.get('admin'):
            return self.page(handler, 401, '<h1>請先登入維修管理後台</h1>'
                '<p>請在另一個分頁登入管理員，然後重新整理本頁。不要把密碼貼到 ChatGPT。</p>'
                '<a href="/admin" target="_blank" rel="noopener noreferrer">開啟管理後台</a>')
        if self.limited('consent', 100):
            return handler.send(429, {'error': 'rate_limited'})
        cookie = SimpleCookie(handler.headers.get('Cookie', ''))
        browser = cookie.get('repair_session')
        if not browser:
            raise ValueError('access_denied')
        request_id = secrets.token_urlsafe(32)
        with self.connect() as c:
            c.execute('DELETE FROM requests WHERE expires<=?', (self.clock(),))
            c.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)', (
                digest(request_id), client, redirect, one(values, 'state'),
                one(values, 'code_challenge'), digest(browser.value), self.clock() + 300))
        return self.page(handler, 200, '<h1>授權 ChatGPT 讀取付款巡檢摘要</h1>'
            '<p>可讀取：巡檢時間、案件編號、姓名、付款訂單編號、金額、寄送方式與核對警示。</p>'
            '<p>不提供完整電話、地址或金鑰。不能確認付款、修改案件、派車或發 LINE。</p>'
            '<p>授權最長 90 天，可隨時在管理後台撤銷。</p>'
            '<form method="post" action="' + PREFIX + '/consent">'
            '<input type="hidden" name="request" value="' + html.escape(request_id, quote=True) + '">'
            '<button type="submit">允許唯讀巡檢</button></form>')

    def consent(self, handler, values):
        user = handler.user()
        cookie = SimpleCookie(handler.headers.get('Cookie', ''))
        browser = cookie.get('repair_session')
        if handler.headers.get('Origin') != self.base or not user or not user.get('admin') or not browser:
            return handler.send(403, {'error': 'access_denied'})
        request_id = one(values, 'request')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', request_id):
            raise ValueError('invalid_request')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM requests WHERE id=? AND browser=? AND expires>?',
                (digest(request_id), digest(browser.value), self.clock())).fetchone()
            if not row:
                raise ValueError('access_denied')
            c.execute('DELETE FROM requests WHERE id=?', (digest(request_id),))
            grant, code = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            c.execute('INSERT INTO grants(id,client,expires) VALUES(?,?,?)', (grant, row['client'], self.clock() + 90 * 86400))
            c.execute('INSERT INTO codes(hash,grant_id,redirect,challenge,expires) VALUES(?,?,?,?,?)',
                (digest(code), grant, row['redirect'], row['challenge'], self.clock() + 60))
        handler.send_response(303)
        handler.send_header('Location', row['redirect'] + '?' + urlencode({'code': code, 'state': row['state'], 'iss': self.base}))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Referrer-Policy', 'no-referrer')
        handler.end_headers()

    def issue_tokens(self, values):
        if one(values, 'resource') != self.resource or one(values, 'scope', SCOPE) != SCOPE:
            raise ValueError('invalid_target')
        client, kind = one(values, 'client_id'), one(values, 'grant_type')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if kind == 'authorization_code':
                code, verifier = one(values, 'code'), one(values, 'code_verifier')
                if not re.fullmatch(r'[A-Za-z0-9_-]{43}', code) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier):
                    raise ValueError('invalid_grant')
                row = c.execute('''SELECT o.*,g.client,g.revoked,g.expires AS grant_expires FROM codes o
                    JOIN grants g ON g.id=o.grant_id WHERE o.hash=?''', (digest(code),)).fetchone()
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')
                if (not row or row['client'] != client or row['revoked'] or row['grant_expires'] <= self.clock()
                        or row['expires'] <= self.clock() or row['redirect'] != one(values, 'redirect_uri')
                        or not secrets.compare_digest(row['challenge'], challenge)):
                    raise ValueError('invalid_grant')
                if row['used']:
                    c.execute('UPDATE grants SET revoked=1 WHERE id=?', (row['grant_id'],))
                    c.commit()
                    raise ValueError('invalid_grant')
                c.execute('UPDATE codes SET used=1 WHERE hash=?', (digest(code),))
            elif kind == 'refresh_token':
                token = one(values, 'refresh_token')
                if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
                    raise ValueError('invalid_grant')
                row = c.execute('''SELECT t.*,g.client,g.revoked,g.expires AS grant_expires FROM tokens t
                    JOIN grants g ON g.id=t.grant_id WHERE t.hash=? AND t.kind='refresh' ''', (digest(token),)).fetchone()
                if not row or row['client'] != client or row['revoked'] or row['expires'] <= self.clock() or row['grant_expires'] <= self.clock():
                    raise ValueError('invalid_grant')
                if row['used']:
                    # Commit replay revocation before returning the error.
                    c.execute('UPDATE grants SET revoked=1 WHERE id=?', (row['grant_id'],))
                    c.commit()
                    raise ValueError('invalid_grant')
                c.execute('UPDATE tokens SET used=1 WHERE hash=?', (digest(token),))
            else:
                raise ValueError('unsupported_grant_type')
            access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            access_lifetime = min(3600, int(row['grant_expires'] - self.clock()))
            c.executemany('INSERT INTO tokens VALUES(?,?,?,?,0)', [
                (digest(access), row['grant_id'], 'access', self.clock() + access_lifetime),
                (digest(refresh), row['grant_id'], 'refresh', row['grant_expires'])])
        return {'access_token': access, 'token_type': 'Bearer', 'expires_in': access_lifetime,
                'refresh_token': refresh, 'scope': SCOPE}

    def collect(self):
        if not self.scan_lock.acquire(False):
            raise ValueError('scan_busy')
        try:
            if self.clock() - self.last_scan < 60:
                raise ValueError('scan_rate_limited')
            self.last_scan = self.clock()
            payments = self.s.get('PAYMENTS')
            if payments is None:
                raise ValueError('payments_unavailable')
            state = payments.state()
            with self.s['connect']() as c:
                repairs = [dict(r) for r in c.execute('SELECT * FROM cases')]
            cases = state.get('cases')
            if not isinstance(cases, list) or len(cases) >= 1000 or {r['id'] for r in cases} != {r['id'] for r in repairs}:
                raise ValueError('case_inventory_incomplete')
            fetched = payments.provider.fetch({'days': 30})
            if fetched.get('status') != 'ok' or fetched.get('truncated') is not False or not isinstance(fetched.get('orders'), list):
                raise ValueError('shopline_orders_incomplete')
            # Reload inventory after the provider request to detect concurrent case/payment changes.
            if state.get('cases') != payments.state().get('cases'):
                raise ValueError('case_inventory_changed')
            found, eligible = find_candidates(cases, repairs, fetched['orders'])
            public_fields = {'caseNumber', 'name', 'shippingMethod', 'requiresPickup', 'quoteVersion',
                'amountDue', 'orderNumber', 'amountPaid', 'providerPaymentStatus', 'orderCreatedAt',
                'paidAt', 'nameMatches', 'phoneMatches', 'remarkEmpty', 'warnings', 'requiresHumanApproval'}
            report = {'checkedAt': datetime.fromtimestamp(self.clock(), TAIPEI).isoformat(timespec='seconds'),
                'status': 'ok', 'lookbackDays': 30, 'scope': 'all_repair_shipping_methods',
                'eligibleRepairCases': eligible, 'repairOrdersScanned': len(fetched['orders']),
                'candidateCount': len(found), 'candidates': [{k: v for k, v in item.items() if k in public_fields} for item in found],
                'externalReadOnly': True, 'automaticMatching': False, 'automaticDispatch': False, 'lineMessagesSent': 0}
            with self.connect() as c:
                prior = c.execute('SELECT payload FROM reports WHERE id=1').fetchone()
                old = json.loads(prior['payload']) if prior else {}
                def key(item):
                    return tuple(item.get(k) for k in ('caseNumber', 'quoteVersion', 'orderNumber', 'amountDue'))
                keys = {key(item) for item in old.get('candidates', [])}
                for item in report['candidates']:
                    item['newSinceLastScan'] = key(item) not in keys
                report['newCandidateCount'] = sum(item['newSinceLastScan'] for item in report['candidates'])
                c.execute('INSERT OR REPLACE INTO reports VALUES(1,?,?)', (self.clock(), json.dumps(report, ensure_ascii=False)))
            return report
        finally:
            self.scan_lock.release()

    def tools(self):
        return [{'name': 'inspect_repair_payment_candidates', 'title': '維修付款唯讀巡檢',
            'description': 'Read current repair payment candidates for all shipping methods. Use for scheduled read-only checks. Never approves payments, updates cases, dispatches pickups, or sends LINE. Failed or incomplete checks are not zero candidates.',
            'inputSchema': EMPTY,
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False, 'idempotentHint': False},
            'securitySchemes': [{'type': 'oauth2', 'scopes': [SCOPE]}]}]

    def rpc(self, handler, data):
        if not self.valid_access(handler.headers.get('Authorization')):
            return self.challenge(handler)
        version = handler.headers.get('MCP-Protocol-Version')
        if version and version not in SUPPORTED:
            return handler.send(400, {'error': 'unsupported_protocol'})
        if not isinstance(data, dict) or data.get('jsonrpc') != '2.0' or not isinstance(data.get('method'), str):
            return handler.send(400, {'error': 'invalid_request'})
        method, ident, params = data['method'], data.get('id'), data.get('params', {})
        if 'id' not in data:
            if method == 'notifications/initialized':
                return handler.send(202, {})
            return handler.send(400, {'error': 'invalid_request'})
        error = None
        if method == 'initialize':
            result = {'protocolVersion': params.get('protocolVersion') if params.get('protocolVersion') in SUPPORTED else SUPPORTED[0],
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': 'petpivot-payment-monitor', 'version': '1.0.0'},
                'instructions': 'Only read payment candidates. Max must confirm all payments. Incomplete checks are failures, never zero candidates. No business write tools exist.'}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': self.tools()}
        elif method == 'tools/call':
            if not isinstance(params, dict) or params.get('name') != 'inspect_repair_payment_candidates' or params.get('arguments', {}) != {}:
                result = None
                error = {'code': -32602, 'message': 'Unsupported tool or arguments'}
            else:
                try:
                    report = self.collect()
                    result = {'content': [{'type': 'text', 'text': json.dumps(report, ensure_ascii=False)}], 'structuredContent': report}
                except Exception:
                    result = {'isError': True, 'content': [{'type': 'text', 'text': '巡檢未完整完成，不能判定為沒有待確認案件。未自動配對付款、派車或發 LINE。'}]}
        else:
            result = None
            error = {'code': -32601, 'message': 'Method not found'}
        return handler.send(200, {'jsonrpc': '2.0', 'id': ident, **({'error': error} if error else {'result': result})})

    def handle_get(self, handler, path, query):
        if path in ('/.well-known/oauth-protected-resource' + MCP, '/.well-known/oauth-protected-resource'):
            handler.send(200, {'resource': self.resource, 'authorization_servers': [self.base], 'scopes_supported': [SCOPE]})
        elif path in ('/.well-known/oauth-authorization-server', '/.well-known/openid-configuration'):
            handler.send(200, self.metadata())
        elif path == PREFIX + '/authorize':
            try:
                self.authorize(handler, query)
            except (ValueError, TypeError):
                handler.send(400, {'error': 'invalid_request'})
        elif path == MCP:
            if not self.valid_access(handler.headers.get('Authorization')):
                self.challenge(handler)
            else:
                handler.send(405, {'error': 'use_post'}, {'Allow': 'POST'})
        elif path == PREFIX + '/manage':
            user = handler.user()
            if not user or not user.get('admin'):
                handler.send(401, {'error': 'admin_required'})
            else:
                self.page(handler, 200, '<h1>撤銷 ChatGPT 唯讀巡檢授權</h1><p>撤銷後雲端無法繼續讀取，付款與派車功能不變。</p>'
                    '<form method="post" action="' + PREFIX + '/revoke-all"><button>撤銷全部唯讀巡檢授權</button></form>')
        else:
            return False
        return True

    def handle_post(self, handler, path):
        paths = {MCP, PREFIX + '/register', PREFIX + '/token', PREFIX + '/consent', PREFIX + '/revoke', PREFIX + '/revoke-all'}
        if path not in paths:
            return False
        try:
            origin = handler.headers.get('Origin')
            if origin and origin not in (self.base, 'https://chatgpt.com'):
                handler.send(403, {'error': 'invalid_origin'})
                return True
            size = int(handler.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                handler.send(413, {'error': 'invalid_size'})
                return True
            raw = handler.rfile.read(size)
            content_type = handler.headers.get('Content-Type', '').split(';')[0]
            if path in (MCP, PREFIX + '/register'):
                if content_type != 'application/json':
                    raise ValueError('invalid_request')
                data = json.loads(raw)
            else:
                if content_type != 'application/x-www-form-urlencoded':
                    raise ValueError('invalid_request')
                data = parse_qs(raw.decode('utf-8'), keep_blank_values=True, max_num_fields=15)
            if path == MCP:
                self.rpc(handler, data)
            elif path == PREFIX + '/register':
                redirects = data.get('redirect_uris') if isinstance(data, dict) else None
                if (not isinstance(redirects, list) or len(redirects) != 1 or not allowed_callback(redirects[0])
                        or data.get('token_endpoint_auth_method', 'none') != 'none'
                        or set(data.get('grant_types', ['authorization_code', 'refresh_token'])) - {'authorization_code', 'refresh_token'}
                        or data.get('scope', SCOPE) != SCOPE):
                    raise ValueError('invalid_client_metadata')
                if self.limited('register', 40):
                    handler.send(429, {'error': 'rate_limited'})
                    return True
                client = secrets.token_urlsafe(32)
                with self.connect() as c:
                    if c.execute('SELECT count(*) FROM clients').fetchone()[0] >= 500:
                        raise ValueError('registration_limit')
                    c.execute('INSERT INTO clients VALUES(?,?)', (client, redirects[0]))
                handler.send(201, {'client_id': client, 'redirect_uris': redirects,
                    'token_endpoint_auth_method': 'none', 'grant_types': ['authorization_code', 'refresh_token'],
                    'response_types': ['code'], 'scope': SCOPE})
            elif path == PREFIX + '/consent':
                self.consent(handler, data)
            elif path == PREFIX + '/token':
                if self.limited('token', 300):
                    handler.send(429, {'error': 'rate_limited'})
                else:
                    handler.send(200, self.issue_tokens(data))
            elif path == PREFIX + '/revoke-all':
                user = handler.user()
                if origin != self.base or not user or not user.get('admin'):
                    handler.send(403, {'error': 'admin_required'})
                else:
                    with self.connect() as c:
                        c.execute('UPDATE grants SET revoked=1')
                    handler.send(200, {'ok': True, 'readOnlyAccessRevoked': True})
            elif path == PREFIX + '/revoke':
                token, client = one(data, 'token'), one(data, 'client_id')
                if re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
                    with self.connect() as c:
                        c.execute('''UPDATE grants SET revoked=1 WHERE client=? AND id IN
                            (SELECT grant_id FROM tokens WHERE hash=?)''', (client, digest(token)))
                handler.send(200, {})
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as error:
            safe = str(error) if isinstance(error, ValueError) else ''
            handler.send(400, {'error': safe if safe in {
                'invalid_request', 'invalid_client_metadata', 'invalid_grant',
                'invalid_target', 'unsupported_grant_type', 'access_denied'} else 'invalid_request'})
        except Exception:
            handler.send(503, {'error': 'connector_unavailable'})
        return True
