"""Bounded WSGI adapter for the existing repair routes.

Import this module in one non-preloaded worker. Requests, headers and exceptions
are never logged here because OAuth URLs and session cookies contain secrets.
"""
import io
import json
import re
import threading
from email.message import Message
from http import HTTPStatus
from urllib.parse import urlsplit

import server as repair_server

MAX_BODY_BYTES = 200000
_START_LOCK = threading.Lock()
_STARTED = False
_CONTROL = re.compile(r'[\x00-\x08\x0a-\x1f\x7f]')
_HEADER_NAME = re.compile(r'[!#$%&\'*+.^_`|~0-9A-Za-z-]+\Z')
_HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate',
                'proxy-authorization', 'te', 'trailer', 'transfer-encoding',
                'upgrade'}


class RequestRejected(Exception):
    def __init__(self, status):
        self.status = status


def _target(environ):
    target = environ.get('RAW_URI') or environ.get('REQUEST_URI')
    if not target:
        path = environ.get('PATH_INFO', '/') or '/'
        query = environ.get('QUERY_STRING', '')
        if not isinstance(path, str) or not isinstance(query, str):
            raise RequestRejected(400)
        target = path + ('?' + query if query else '')
    if (not isinstance(target, str) or not target.startswith('/')
            or target.startswith('//') or _CONTROL.search(target)
            or '\t' in target or '#' in target):
        raise RequestRejected(400)
    return target


def _headers(environ):
    headers = Message()
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            name = key[5:].replace('_', '-')
        elif key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            name = key.replace('_', '-')
        else:
            continue
        if (not _HEADER_NAME.fullmatch(name) or not isinstance(value, str)
                or _CONTROL.search(value)):
            raise RequestRejected(400)
        # WSGI has one canonical place for these two HTTP headers.
        if key in ('HTTP_CONTENT_LENGTH', 'HTTP_CONTENT_TYPE'):
            raise RequestRejected(400)
        headers[name] = value
    return headers


def _host_parts(value, default_port=443):
    if (not isinstance(value, str) or not value or _CONTROL.search(value)
            or any(character.isspace() for character in value)
            or any(character in value for character in '/\\?#@')):
        raise RequestRejected(400)
    try:
        parsed = urlsplit('//' + value)
        hostname, port = parsed.hostname, parsed.port
    except ValueError:
        raise RequestRejected(400) from None
    if not hostname or parsed.path or parsed.username or parsed.password:
        raise RequestRejected(400)
    return hostname.lower(), port if port is not None else default_port


def _check_host(headers, target, method):
    base = urlsplit(repair_server.BASE)
    default_port = 443 if base.scheme == 'https' else 80
    received = _host_parts(headers.get('Host', ''), default_port)
    if method in ('GET', 'HEAD') and urlsplit(target).path == '/healthz':
        return
    expected = _host_parts(base.netloc, default_port)
    if received != expected:
        raise RequestRejected(403)


def _body(environ, headers):
    raw_length = environ.get('CONTENT_LENGTH', '')
    if raw_length:
        if not re.fullmatch(r'[0-9]+', raw_length):
            raise RequestRejected(400)
        try:
            length = int(raw_length)
        except ValueError:
            raise RequestRejected(400) from None
        if length > MAX_BODY_BYTES:
            raise RequestRejected(413)
        source = environ.get('wsgi.input')
        if source is None:
            if length:
                raise RequestRejected(400)
            body = b''
        else:
            chunks, remaining = [], length
            while remaining:
                chunk = source.read(remaining)
                if not isinstance(chunk, bytes) or not chunk or len(chunk) > remaining:
                    raise RequestRejected(400)
                chunks.append(chunk)
                remaining -= len(chunk)
            body = b''.join(chunks)
    elif environ.get('wsgi.input_terminated'):
        source = environ.get('wsgi.input')
        chunks, remaining = [], MAX_BODY_BYTES + 1
        while source is not None and remaining:
            chunk = source.read(remaining)
            if not isinstance(chunk, bytes) or len(chunk) > remaining:
                raise RequestRejected(400)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b''.join(chunks)
        if len(body) > MAX_BODY_BYTES:
            raise RequestRejected(413)
    else:
        # An unframed stream cannot be read safely without risking a blocked
        # worker. Empty POSTs are rejected by the unchanged handler contract.
        body = b''
    if headers.get('Transfer-Encoding') and not environ.get('wsgi.input_terminated'):
        raise RequestRejected(400)
    if headers.get('Transfer-Encoding') and raw_length:
        raise RequestRejected(400)
    if 'Content-Length' in headers:
        del headers['Content-Length']
    headers['Content-Length'] = str(len(body))
    return body


class WSGIHandler(repair_server.Handler):
    def __init__(self, environ, target, headers, body):
        # BaseHTTPRequestHandler.__init__ owns a socket and must not run.
        self.path = target
        self.headers = headers
        self.command = environ['REQUEST_METHOD']
        self.request_version = 'HTTP/1.1'
        self.client_address = (environ.get('REMOTE_ADDR', ''), 0)
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.response_status = None
        self.response_headers = []

    def send_response(self, code, message=None):
        self.response_status = code
        self.response_headers = []

    def send_header(self, keyword, value):
        name, content = str(keyword), str(value)
        if not _HEADER_NAME.fullmatch(name) or _CONTROL.search(content):
            raise ValueError('Invalid response header')
        if name.lower() not in _HOP_HEADERS:
            self.response_headers.append((name, content))

    def end_headers(self):
        pass

    def log_message(self, *args):
        pass


def _response(start_response, status, headers, body, head=False):
    if not isinstance(status, int) or not 200 <= status <= 599:
        raise ValueError('Invalid response status')
    headers = [(key, value) for key, value in headers
               if key.lower() not in _HOP_HEADERS | {'content-length'}]
    present = {key.lower() for key, _ in headers}
    for key, value in [('X-Content-Type-Options', 'nosniff'),
                       ('Referrer-Policy', 'no-referrer'),
                       ('X-Frame-Options', 'DENY')]:
        if key.lower() not in present:
            headers.append((key, value))
    headers.append(('Content-Length', str(len(body))))
    try:
        reason = HTTPStatus(status).phrase
    except ValueError:
        reason = 'Response'
    start_response(str(status) + ' ' + reason, headers)
    return [b'' if head else body]


def _error(start_response, status, head=False):
    message = {400: '請求格式錯誤', 403: '不允許的來源',
               405: '不支援的請求方式', 413: '資料大小錯誤',
               500: '服務暫時無法完成，請稍後重試'}.get(status, '請求無法完成')
    body = json.dumps({'error': message}, ensure_ascii=False).encode('utf-8')
    headers = [('Content-Type', 'application/json; charset=utf-8'),
               ('Cache-Control', 'no-store')]
    if status == 405:
        headers.append(('Allow', 'GET, HEAD, POST'))
    return _response(start_response, status, headers, body, head)


def create_app(startup=True):
    global _STARTED
    if startup:
        with _START_LOCK:
            if not _STARTED:
                repair_server.start_service()
                from database_tools import start_backup_worker
                start_backup_worker(repair_server.DB)
                _STARTED = True

    def app(environ, start_response):
        method = environ.get('REQUEST_METHOD', '')
        head = method == 'HEAD'
        try:
            if method not in ('GET', 'HEAD', 'POST'):
                raise RequestRejected(405)
            target = _target(environ)
            headers = _headers(environ)
            _check_host(headers, target, method)
            body = _body(environ, headers)
            handler = WSGIHandler(environ, target, headers, body)
            if method in ('GET', 'HEAD'):
                handler.do_GET()
            else:
                handler.do_POST()
            status = handler.response_status
            if status is None:
                raise ValueError('Handler did not return a response')
            return _response(start_response, status, handler.response_headers,
                             handler.wfile.getvalue(), head)
        except RequestRejected as error:
            return _error(start_response, error.status, head)
        except Exception:
            # Never expose exception text, headers, query strings or tokens.
            return _error(start_response, 500, head)

    return app


application = create_app()
