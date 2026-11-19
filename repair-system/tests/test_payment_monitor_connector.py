import base64
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.parse import urlencode, urlsplit, parse_qs

from payment_monitor_connector import MonitorConnector, SCOPE, MCP, PREFIX, digest
from payment_monitor_rules import find_candidates


class Handler:
    def __init__(self, data=None, form=False, admin=False, token=None, origin=None):
        self.headers = {'Cookie': 'repair_session=' + 's' * 43}
        if token:
            self.headers['Authorization'] = 'Bearer ' + token
        if origin:
            self.headers['Origin'] = origin
        self.admin = admin
        self.body = b'' if data is None else (urlencode(data).encode() if form else json.dumps(data).encode())
        self.headers.update({'Content-Length': str(len(self.body)),
            'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'})
        self.rfile, self.wfile = io.BytesIO(self.body), io.BytesIO()
        self.response_headers = {}

    def user(self):
        return {'admin': True} if self.admin else None

    def send(self, status, data, headers=None):
        self.status, self.result = status, data
        self.response_headers.update(headers or {})

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 2_000_000_000
        self.base = 'https://ad-creative-platform.onrender.com'
        self.server = {'BASE': self.base, 'DATA_DIR': Path(self.temp.name)}
        self.m = MonitorConnector(self.server, clock=lambda: self.now)
        self.m.init()
        self.redirect = 'https://chatgpt.com/connector_platform_oauth_redirect'
        self.client = self.register()
        self.verifier = 'a' * 43
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')

    def tearDown(self):
        self.temp.cleanup()

    def register(self):
        h = Handler({'redirect_uris': ['https://chatgpt.com/connector_platform_oauth_redirect']})
        self.m.handle_post(h, PREFIX + '/register')
        self.assertEqual(h.status, 201)
        return h.result['client_id']

    def code(self):
        h = Handler(admin=True)
        query = urlencode({'client_id': self.client, 'redirect_uri': self.redirect,
            'response_type': 'code', 'scope': SCOPE, 'resource': self.m.resource,
            'state': 'state' * 8, 'code_challenge': self.challenge, 'code_challenge_method': 'S256'})
        self.m.authorize(h, query)
        import re
        request_id = re.search(r'name="request" value="([^"]+)"', h.wfile.getvalue().decode())[1]
        consent = Handler({'request': request_id}, form=True, admin=True, origin=self.base)
        self.m.handle_post(consent, PREFIX + '/consent')
        self.assertEqual(consent.status, 303)
        values = parse_qs(urlsplit(consent.response_headers['Location']).query)
        self.assertEqual(values['iss'], [self.base])
        return values['code'][0]

    def exchange(self, code=None, **overrides):
        return self.m.issue_tokens({k: [v] for k, v in dict(
            grant_type='authorization_code', client_id=self.client, redirect_uri=self.redirect,
            code=code or self.code(), code_verifier=self.verifier, resource=self.m.resource, **overrides).items()})

    def test_complete_oauth_flow_and_hashed_storage(self):
        tokens = self.exchange()
        self.assertTrue(self.m.valid_access('Bearer ' + tokens['access_token']))
        with self.m.connect() as c:
            stored = list(c.execute('SELECT hash FROM tokens'))
        self.assertTrue(all(len(row['hash']) == 64 for row in stored))
        self.assertNotIn(tokens['access_token'].encode(), self.m.db.read_bytes())

    def test_rejects_unapproved_redirects_and_auth_methods(self):
        for uri in ('https://chatgpt.com.evil.test/x', 'http://chatgpt.com/x', 'https://evil.test/callback',
                    'https://chatgpt.com/connector_platform_oauth_redirect?x=1'):
            h = Handler({'redirect_uris': [uri]})
            self.m.handle_post(h, PREFIX + '/register')
            self.assertEqual(h.status, 400)

    def test_code_cannot_be_replayed_or_swapped(self):
        code = self.code()
        bad = dict(grant_type=['authorization_code'], client_id=[self.register()], redirect_uri=[self.redirect],
                   code=[code], code_verifier=[self.verifier], resource=[self.m.resource])
        with self.assertRaises(ValueError):
            self.m.issue_tokens(bad)
        tokens = self.exchange(code)
        with self.assertRaises(ValueError):
            self.exchange(code)
        self.assertFalse(self.m.valid_access('Bearer ' + tokens['access_token']))

    def test_pkce_and_resource_are_mandatory(self):
        for field, value in (('code_verifier', 'b' * 43), ('resource', 'https://evil.test'), ('scope', 'write')):
            code = self.code()
            values = dict(grant_type=['authorization_code'], client_id=[self.client], redirect_uri=[self.redirect],
                code=[code], code_verifier=[self.verifier], resource=[self.m.resource])
            values[field] = [value]
            with self.assertRaises(ValueError):
                self.m.issue_tokens(values)

    def test_expired_code_and_access(self):
        code = self.code()
        self.now += 61
        with self.assertRaises(ValueError):
            self.exchange(code)
        token = self.exchange()['access_token']
        self.now += 3601
        self.assertFalse(self.m.valid_access('Bearer ' + token))

    def test_refresh_rotates_and_replay_revokes_grant(self):
        tokens = self.exchange()
        values = {'grant_type': ['refresh_token'], 'client_id': [self.client],
            'refresh_token': [tokens['refresh_token']], 'resource': [self.m.resource]}
        renewed = self.m.issue_tokens(values)
        self.assertTrue(self.m.valid_access('Bearer ' + renewed['access_token']))
        with self.assertRaises(ValueError):
            self.m.issue_tokens(values)
        self.assertFalse(self.m.valid_access('Bearer ' + renewed['access_token']))

    def test_consent_requires_admin_session_and_same_origin(self):
        for admin, origin in ((False, self.base), (True, 'https://evil.test'), (True, None)):
            h = Handler({'request': 'a' * 43}, form=True, admin=admin, origin=origin)
            self.m.handle_post(h, PREFIX + '/consent')
            self.assertEqual(h.status, 403)

    def test_mcp_requires_token_and_exports_no_write_tools(self):
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
        h = Handler(request)
        self.m.handle_post(h, MCP)
        self.assertEqual(h.status, 401)
        token = self.exchange()['access_token']
        h = Handler(request, token=token)
        self.m.handle_post(h, MCP)
        self.assertEqual(len(h.result['result']['tools']), 1)
        self.assertTrue(h.result['result']['tools'][0]['annotations']['readOnlyHint'])
        h = Handler({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                     'params': {'name': 'confirm_payment', 'arguments': {}}}, token=token)
        self.m.handle_post(h, MCP)
        self.assertIn('error', h.result)
        self.assertFalse(self.m.handle_post(Handler(request, token=token), '/api/payments/settings'))

    def test_failure_is_error_and_never_zero_candidates(self):
        token = self.exchange()['access_token']
        h = Handler({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'inspect_repair_payment_candidates', 'arguments': {}}}, token=token)
        self.m.handle_post(h, MCP)
        self.assertTrue(h.result['result']['isError'])
        self.assertNotIn('candidateCount', json.dumps(h.result))

    def test_revocation_does_not_require_business_write_capability(self):
        token = self.exchange()['access_token']
        h = Handler({'token': token, 'client_id': self.client}, form=True)
        self.m.handle_post(h, PREFIX + '/revoke')
        self.assertEqual(h.status, 200)
        self.assertFalse(self.m.valid_access('Bearer ' + token))

    def test_complete_empty_scan_and_incomplete_inventory(self):
        @contextmanager
        def connect():
            c = sqlite3.connect(':memory:')
            c.row_factory = sqlite3.Row
            c.execute('CREATE TABLE cases(id TEXT)')
            try:
                yield c
            finally:
                c.close()
        class Provider:
            def fetch(self, filters):
                assert filters == {'days': 30}
                return {'status': 'ok', 'truncated': False, 'orders': []}
        class Payments:
            provider = Provider()
            def state(self):
                return {'cases': []}
        self.server.update(PAYMENTS=Payments(), connect=connect)
        report = self.m.collect()
        self.assertEqual(report['candidateCount'], 0)
        self.assertFalse(report['automaticMatching'])
        self.assertEqual(report['lineMessagesSent'], 0)
        self.now += 61
        self.server['PAYMENTS'].state = lambda: {'cases': [{'id': 'missing'}]}
        with self.assertRaisesRegex(ValueError, 'case_inventory_incomplete'):
            self.m.collect()


if __name__ == '__main__':
    unittest.main()
