"""Invitation-only LINE identity and case registry for the isolated test host.

No formal repair database, webhook, dispatch group or provider write is used.
LINE identifiers stay in the server registry and never come from a case form.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit
import urllib.request
import uuid


_FAILURE_STAGES = frozenset({'oauth_state', 'token_exchange', 'id_verify',
    'profile_read', 'claims_validation', 'profile_validation', 'invite_binding'})


def _diagnostic(stage):
    """One fixed stage only: never log exception text, URLs or identity data."""
    safe_stage = stage if type(stage) is str and stage in _FAILURE_STAGES else 'oauth_state'
    logging.getLogger('petpivot.internal.intake').warning(
        'internal_test_intake_failure stage=%s', safe_stage,
        exc_info=None, stack_info=False)


@contextmanager
def _stage(stage, message):
    try:
        yield
    except Exception:
        _diagnostic(stage)
        raise ValueError(message) from None


def _hash(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _token(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', value) is not None


def _identity(value, prefix=''):
    try:
        if type(value) is not str or not value.startswith(prefix):
            return False
        suffix = value[len(prefix):]
        parsed = uuid.UUID(suffix)
        return parsed.version == 4 and str(parsed) == suffix
    except (ValueError, AttributeError):
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def exchange_code(code, verifier, channel_id, channel_secret, callback):
    request = urllib.request.Request('https://api.line.me/oauth2/v2.1/token',
        data=urlencode({'grant_type': 'authorization_code', 'code': code,
            'redirect_uri': callback, 'client_id': channel_id,
            'client_secret': channel_secret, 'code_verifier': verifier}).encode('ascii'),
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        value = json.loads(raw)
        token = value.get('id_token')
        if not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise ValueError()
        return token
    except Exception:
        raise ValueError('內測 LINE 登入交換未完成，請重新登入') from None


class TestIntake:
    def __init__(self, connection_factory, *, public_url, channel_id='', channel_secret='',
                 id_verifier=None, profile_reader=None, exchange=exchange_code,
                 legacy_case='', legacy_user='', clock=time.time):
        parsed = urlsplit(public_url) if isinstance(public_url, str) else None
        if (not callable(connection_factory) or not callable(clock)
                or parsed is None or parsed.scheme != 'https' or not parsed.hostname
                or parsed.hostname == 'ad-creative-platform.onrender.com'
                or not parsed.hostname.endswith('.onrender.com')
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('內測 LINE 身分必須使用獨立 HTTPS 內測站')
        if (bool(legacy_case) != bool(legacy_user)
                or (legacy_case and (not _identity(legacy_case, 'WB-')
                    or not isinstance(legacy_user, str) or not re.fullmatch(r'U[0-9a-f]{32}', legacy_user)))):
            raise ValueError('既有內測身分綁定不正確')
        if any(fn is not None and not callable(fn) for fn in (id_verifier, profile_reader)) or not callable(exchange):
            raise ValueError('內測 LINE 身分服務設定不正確')
        self.factory, self.base, self.channel_id, self.secret = connection_factory, public_url.rstrip('/'), channel_id, channel_secret
        self.verify, self.profile, self.exchange = id_verifier, profile_reader, exchange
        self.legacy_case, self.legacy_user, self.clock = legacy_case, legacy_user, clock

    @contextmanager
    def _db(self, write=False):
        with self.factory() as c:
            if not isinstance(c, sqlite3.Connection):
                raise ValueError('內測身分資料庫連線不正確')
            c.row_factory = sqlite3.Row
            for row in c.execute('PRAGMA database_list'):
                if row['name'] not in ('main', 'temp'):
                    raise ValueError('內測身分不得連接外部資料庫')
                if row['file']:
                    absolute, resolved = os.path.abspath(row['file']), os.path.realpath(row['file'])
                    if (os.path.normcase(absolute) != os.path.normcase(resolved)
                            or os.path.basename(resolved).lower() in ('repairs.db', 'payment-lab.db')
                            or os.stat(resolved).st_nlink > 1):
                        raise ValueError('內測身分必須使用獨立客服資料庫檔案')
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            if not tables or any(not name.startswith('wb_') for name in tables):
                raise ValueError('內測身分必須使用獨立客服資料庫')
            with c:
                if write and not c.in_transaction:
                    c.execute('BEGIN IMMEDIATE')
                yield c

    def init(self):
        with self._db(True) as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS wb_intake_invites (
                    hash TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    expires REAL NOT NULL, bound_customer TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS wb_intake_oauth (
                    hash TEXT PRIMARY KEY, invite_hash TEXT NOT NULL, nonce TEXT NOT NULL,
                    verifier TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS wb_intake_customers (
                    id TEXT PRIMARY KEY, line_user TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS wb_intake_sessions (
                    hash TEXT PRIMARY KEY, customer_id TEXT NOT NULL, expires REAL NOT NULL);
            ''')

    def configured(self):
        return bool(isinstance(self.channel_id, str) and self.channel_id
                    and isinstance(self.secret, str) and self.secret and self.verify and self.profile)

    def create_invite(self, request_id):
        if not _identity(request_id):
            raise ValueError('邀請識別碼不正確')
        if not self.configured():
            raise ValueError('獨立內測 LINE 登入尚未設定完成')
        value, expiry = secrets.token_urlsafe(32), self.clock() + 86400
        with self._db(True) as c:
            if c.execute('SELECT 1 FROM wb_intake_invites WHERE request_id=?', (request_id,)).fetchone():
                raise ValueError('此邀請已建立，請另建新邀請；不會重送舊連結')
            c.execute('INSERT INTO wb_intake_invites(hash,request_id,expires) VALUES(?,?,?)', (_hash(value), request_id, expiry))
        return {'url': self.base + '/test-application?invite=' + value, 'expiresAt': expiry,
                'internalOnly': True, 'singleAccount': True}

    def valid_invite(self, value):
        if not _token(value):
            return False
        with self._db() as c:
            row = c.execute('SELECT expires FROM wb_intake_invites WHERE hash=?', (_hash(value),)).fetchone()
        return bool(row and row['expires'] > self.clock())

    def start(self, invite):
        if not self.configured() or not self.valid_invite(invite):
            raise ValueError('內測邀請已失效，請向管理員取得新連結')
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        with self._db(True) as c:
            c.execute('DELETE FROM wb_intake_oauth WHERE expires<?', (self.clock(),))
            c.execute('INSERT INTO wb_intake_oauth VALUES(?,?,?,?,?)', (_hash(state), _hash(invite), nonce, verifier, self.clock() + 600))
        return state, 'https://access.line.me/oauth2/v2.1/authorize?' + urlencode({
            'response_type': 'code', 'client_id': self.channel_id,
            'redirect_uri': self.base + '/test-line-callback', 'state': state,
            'scope': 'openid profile', 'nonce': nonce,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})

    def finish(self, state, cookie_state, code):
        with _stage('oauth_state', 'LINE 登入狀態不符或已逾時，請重新登入'):
            if (not self.configured() or not _token(state) or not _token(cookie_state)
                    or not secrets.compare_digest(state, cookie_state)
                    or not isinstance(code, str) or not 1 <= len(code) <= 2048):
                raise ValueError()
            with self._db(True) as c:
                row = c.execute('SELECT * FROM wb_intake_oauth WHERE hash=?', (_hash(state),)).fetchone()
                if not row or row['expires'] <= self.clock():
                    raise ValueError()
                c.execute('DELETE FROM wb_intake_oauth WHERE hash=?', (_hash(state),))
                saved = dict(row)
        with _stage('token_exchange', '內測 LINE 登入交換未完成，請重新登入'):
            token = self.exchange(code, saved['verifier'], self.channel_id, self.secret, self.base + '/test-line-callback')
            if not isinstance(token, str) or not 1 <= len(token) <= 16384:
                raise ValueError()
        with _stage('id_verify', 'LINE 身分驗證未完成，請重新登入'):
            claims = self.verify(token, self.channel_id, nonce=saved['nonce'])
        with _stage('claims_validation', 'LINE 身分驗證未完成，請重新登入'):
            if not isinstance(claims, dict):
                raise ValueError()
            uid, expiry = claims.get('sub'), claims.get('exp')
            if (not isinstance(uid, str) or not re.fullmatch(r'U[0-9a-f]{32}', uid)
                    or claims.get('aud') != self.channel_id or claims.get('iss') != 'https://access.line.me'
                    or claims.get('nonce') != saved['nonce'] or type(expiry) not in (int, float)
                    or not math.isfinite(expiry) or expiry <= self.clock()):
                raise ValueError()
        with _stage('profile_read', '請先加入客服官方 LINE 好友，再使用內測邀請登入'):
            profile = self.profile(uid)
        with _stage('profile_validation', '請先加入客服官方 LINE 好友，再使用內測邀請登入'):
            if not isinstance(profile, dict):
                raise ValueError()
            name = profile.get('displayName')
            if (profile.get('userId') != uid or not isinstance(name, str) or not 1 <= len(name) <= 80
                    or not name.strip() or any(ord(ch)<32 or ord(ch)==127 or 0xD800 <= ord(ch) <= 0xDFFF for ch in name)):
                raise ValueError()
        with _stage('invite_binding', '內測邀請綁定未完成，請使用自己的新邀請重新登入'):
            session = secrets.token_urlsafe(32)
            with self._db(True) as c:
                invite = c.execute('SELECT * FROM wb_intake_invites WHERE hash=?', (saved['invite_hash'],)).fetchone()
                if not invite or invite['expires'] <= self.clock():
                    raise ValueError()
                person = c.execute('SELECT * FROM wb_intake_customers WHERE line_user=?', (uid,)).fetchone()
                cid = person['id'] if person else 'WC-' + str(uuid.uuid4())
                if invite['bound_customer'] and invite['bound_customer'] != cid:
                    raise ValueError()
                c.execute('INSERT INTO wb_intake_customers VALUES(?,?,?,0,?) ON CONFLICT(line_user) DO UPDATE SET display_name=excluded.display_name', (cid, uid, name, self.clock()))
                c.execute('UPDATE wb_intake_invites SET bound_customer=? WHERE hash=?', (cid, saved['invite_hash']))
                c.execute('INSERT INTO wb_intake_sessions VALUES(?,?,?)', (_hash(session), cid, self.clock()+86400))
        return session

    def identity(self, token):
        if not _token(token):
            return None
        with self._db() as c:
            row = c.execute('''SELECT p.id,p.display_name FROM wb_intake_sessions s
                JOIN wb_intake_customers p ON p.id=s.customer_id WHERE s.hash=? AND s.expires>?''', (_hash(token), self.clock())).fetchone()
        return {'customerId': row['id'], 'displayName': row['display_name']} if row else None

    def consent(self, customer_id):
        if not _identity(customer_id, 'WC-'):
            raise ValueError('內測身分識別碼不正確')
        with self._db(True) as c:
            if not c.execute('UPDATE wb_intake_customers SET enabled=1 WHERE id=?', (customer_id,)).rowcount:
                raise ValueError('找不到已驗證的內測帳號')

    def logout(self, token):
        if _token(token):
            with self._db(True) as c:
                c.execute('DELETE FROM wb_intake_sessions WHERE hash=?', (_hash(token),))

    def allowed_case_ids(self):
        result = {self.legacy_case} if self.legacy_case else set()
        with self._db() as c:
            enabled = {r['id'] for r in c.execute('SELECT id FROM wb_intake_customers WHERE enabled=1')}
            for row in c.execute('SELECT id,data FROM wb_cases ORDER BY rowid DESC LIMIT 1000'):
                data = json.loads(row['data'])
                if data.get('source') == 'test_intake' and data.get('customerId') in enabled:
                    result.add(row['id'])
        if len(result) > 100:
            raise ValueError('內測案件超過限制，請由管理員整理')
        return frozenset(result)

    def recipient(self, case_id):
        if case_id == self.legacy_case and self.legacy_user:
            return {'userId': self.legacy_user, 'displayName': 'Max🚀', 'verified': True}
        if case_id not in self.allowed_case_ids():
            raise ValueError('案件未列入已同意的內測範圍')
        with self._db() as c:
            row = c.execute('SELECT data FROM wb_cases WHERE id=?', (case_id,)).fetchone()
            case = json.loads(row['data'])
            person = c.execute('SELECT * FROM wb_intake_customers WHERE id=? AND enabled=1', (case.get('customerId'),)).fetchone()
        if not person:
            raise ValueError('案件未綁定內測帳號')
        return {'userId': person['line_user'], 'displayName': person['display_name'], 'verified': True}
