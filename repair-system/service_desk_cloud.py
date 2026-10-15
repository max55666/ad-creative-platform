"""Independent cloud rehearsal host. Never imports the production WSGI app.

Secrets and a copied wb-only database are explicit operator inputs. The only
network adapters are a read-only SHOPLINE reader, Max's allowlisted test LINE
sender and the fixed private payment-sheet copy. Formal routes and workers are
unreachable from this adapter.
"""
import atexit
import base64
import binascii
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import Message
from http import HTTPStatus
import io
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
from urllib.parse import urlsplit, parse_qs
from http.cookies import SimpleCookie
import uuid

DATA_DIRECTORY = Path('/var/data/service-desk')
_RENDER_SECRET_ROOT = Path('/etc/secrets')
_RENDER_SECRET_FILENAMES = frozenset({'service-desk-config.json', 'service-desk-seed.b64'})
TEST_SHEET_ID = '1hu5VVS3Ark9Iv-SD4JYFuBfEOqkUQrf7yMlUWuWi1R4'
APPROVED_CASE_ID = 'WB-fc9b8753-a8b1-47bb-a01d-a158d1ec57f1'
APPROVED_CASE_NUMBER = 'R20261014-0006'
_SEED_TABLES = frozenset({'wb_cases', 'wb_quotes', 'wb_notifications',
    'wb_orders', 'wb_requests', 'wb_audit', 'wb_real_order_checks',
    'wb_payment_sheet_state', 'wb_payment_sheet_outbox'})
_CONFIG_KEYS = frozenset({'adminPassword', 'shoplineApiToken', 'lineAccessToken',
    'testLineUserId', 'recipientLabel', 'testSheetEndpoint', 'testSheetSecret',
    'enableAutomation', 'testLoginChannelId', 'testLoginChannelSecret'})
_CONTROL = re.compile(r'[\x00-\x20\x7f]')
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate',
    'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}
MAX_BODY_BYTES = 16384
_BOOT_LOCK = threading.Lock()
_BOOT_RUNTIME = None
_BOOT_LOG_LOCK = threading.Lock()
_BOOT_LOG_NEXT = 0.0
_BOOT_LOG_COUNT = 0
_BOOT_STAGES = frozenset({'config', 'seed', 'server', 'adapters', 'workers'})


def _error_kind(error):
    # Never use exception text, repr, arbitrary class names, paths or traceback.
    for kind in (FileNotFoundError, PermissionError, sqlite3.DatabaseError,
                 ModuleNotFoundError, ImportError, ValueError, TypeError,
                 KeyError, OSError, RuntimeError):
        if isinstance(error, kind):
            return kind.__name__
    return 'Exception'


class BootstrapFailure(RuntimeError):
    def __init__(self, stage, error):
        self.stage = stage if stage in _BOOT_STAGES else 'runtime'
        self.error_kind = _error_kind(error)
        super().__init__('Independent cloud bootstrap failed')


@contextmanager
def _bootstrap_stage(stage):
    try:
        yield
    except BootstrapFailure:
        raise
    except Exception as error:
        raise BootstrapFailure(stage, error) from None


def _report_bootstrap_failure(error):
    """One static, secret-free signal per minute, at most ten per process."""
    global _BOOT_LOG_NEXT, _BOOT_LOG_COUNT
    now = time.monotonic()
    with _BOOT_LOG_LOCK:
        if _BOOT_LOG_COUNT >= 10 or now < _BOOT_LOG_NEXT:
            return
        _BOOT_LOG_NEXT, _BOOT_LOG_COUNT = now + 60, _BOOT_LOG_COUNT + 1
    stage = error.stage if isinstance(error, BootstrapFailure) and error.stage in _BOOT_STAGES else 'runtime'
    kind = error.error_kind if isinstance(error, BootstrapFailure) else _error_kind(error)
    if kind not in {'FileNotFoundError', 'PermissionError', 'DatabaseError',
                    'ModuleNotFoundError', 'ImportError', 'ValueError', 'TypeError',
                    'KeyError', 'OSError', 'RuntimeError', 'Exception'}:
        kind = 'Exception'
    flags = _default_secret_diagnostics(stage)
    logging.getLogger('petpivot.internal.bootstrap').warning(
        'internal_cloud_bootstrap_failure stage=%s error_type=%s '
        'default_secret_exists=%s default_secret_symlink=%s '
        'default_secret_regular=%s default_secret_within_root=%s',
        stage, kind, flags['exists'], flags['symlink'], flags['regular'], flags['within_root'])


def _default_secret_diagnostics(stage):
    """Only filesystem booleans for a fixed platform path; never read content."""
    flags = {key: 'not_checked' for key in ('exists', 'symlink', 'regular', 'within_root')}
    filename = {'config': 'service-desk-config.json', 'seed': 'service-desk-seed.b64'}.get(stage)
    if filename is None:
        return flags
    path = _RENDER_SECRET_ROOT / filename
    probes = {'exists': path.exists, 'symlink': path.is_symlink, 'regular': path.is_file,
        'within_root': lambda: path.resolve(strict=True).is_relative_to(_RENDER_SECRET_ROOT.resolve(strict=True))}
    for key, probe in probes.items():
        try:
            flags[key] = int(bool(probe()))
        except Exception:
            flags[key] = 'unknown'
    return flags


def _fail():
    raise ValueError('Independent cloud rehearsal configuration is invalid')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _platform_secret(path):
    return path.parent == _RENDER_SECRET_ROOT and path.name in _RENDER_SECRET_FILENAMES


def _read_file(path, maximum):
    path = Path(path)
    if not path.is_absolute():
        _fail()
    if _platform_secret(path):
        # Render owns these two fixed files. Its secret mount may use symlinks
        # for atomic updates; follow those only inside the same secret root.
        root = _RENDER_SECRET_ROOT.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            _fail()
    else:
        if (path.is_symlink() or not path.is_file()
                or path.resolve() != path.absolute() or path.stat().st_nlink != 1):
            _fail()
        resolved = path
    with resolved.open('rb') as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            _fail()
        raw = source.read(maximum + 1)
    if len(raw) > maximum:
        _fail()
    return raw


def _credential(value, minimum=1, maximum=4096):
    return (isinstance(value, str) and minimum <= len(value) <= maximum
            and value.isascii() and all(32 < ord(c) < 127 for c in value))


def _public_url(value):
    parsed = urlsplit(value) if isinstance(value, str) else None
    if (parsed is None or parsed.scheme != 'https'
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,62}\.onrender\.com', parsed.netloc)
            or parsed.netloc == 'ad-creative-platform.onrender.com'
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        _fail()
    return 'https://' + parsed.netloc


@dataclass(frozen=True)
class Configuration:
    public_url: str
    admin_password: str = field(repr=False)
    shopline_token: str = field(default='', repr=False)
    line_token: str = field(default='', repr=False)
    line_user: str = field(default='', repr=False)
    sheet_endpoint: str = field(default='', repr=False)
    sheet_secret: str = field(default='', repr=False)
    automation_enabled: bool = False
    test_login_id: str = field(default='', repr=False)
    test_login_secret: str = field(default='', repr=False)

    @classmethod
    def load(cls, environ=None):
        env = os.environ if environ is None else environ
        config_path = Path(env.get('SERVICE_DESK_CONFIG_FILE', '/etc/secrets/service-desk-config.json'))
        if (not config_path.is_absolute()
                or config_path.is_symlink() and not _platform_secret(config_path)):
            _fail()
        settings = {}
        if config_path.exists():
            try:
                settings = json.loads(_read_file(config_path, 32768).decode('utf-8-sig'),
                    object_pairs_hook=_unique,
                    parse_constant=lambda value: _fail())
            except (OSError, UnicodeError, ValueError, TypeError):
                _fail()
        if (type(settings) is not dict or set(settings) - _CONFIG_KEYS
                or settings.get('recipientLabel', 'Max🚀') != 'Max🚀'
                or type(settings.get('enableAutomation', False)) is not bool):
            _fail()
        password = env.get('SERVICE_DESK_ADMIN_PASSWORD') or settings.get('adminPassword', '')
        if (not isinstance(password, str) or not 20 <= len(password) <= 256
                or any(ord(c) < 33 or ord(c) == 127 for c in password)
                or password == 'PaymentLab-Local-Only'):
            _fail()
        shopline, line = settings.get('shoplineApiToken', ''), settings.get('lineAccessToken', '')
        user = settings.get('testLineUserId', '')
        endpoint, secret = settings.get('testSheetEndpoint', ''), settings.get('testSheetSecret', '')
        if (any(not isinstance(value, str) for value in (shopline, line, user, endpoint, secret))
                or any(value and not _credential(value) for value in (shopline, line))
                or bool(line) != bool(user)
                or user and re.fullmatch(r'U[0-9a-f]{32}', user) is None
                or bool(endpoint) != bool(secret)):
            _fail()
        if endpoint:
            parsed = urlsplit(endpoint) if isinstance(endpoint, str) else None
            if (parsed is None or parsed.scheme != 'https' or parsed.netloc != 'script.google.com'
                    or parsed.query or parsed.fragment
                    or re.fullmatch(r'/macros/s/[A-Za-z0-9_-]{20,300}/exec', parsed.path) is None
                    or not isinstance(secret, str) or re.fullmatch(r'[A-Za-z0-9_-]{32,128}', secret) is None):
                _fail()
        enabled = settings.get('enableAutomation', False)
        login_id = settings.get('testLoginChannelId', '')
        login_secret = settings.get('testLoginChannelSecret', '')
        if (not isinstance(login_id, str) or not isinstance(login_secret, str)
                or bool(login_id) != bool(login_secret)
                or login_id and (not re.fullmatch(r'[0-9]{6,15}', login_id)
                    or not _credential(login_secret, 16, 256))):
            _fail()
        if enabled and not all((shopline, line, user, endpoint, secret)):
            _fail()
        return cls(_public_url(env.get('SERVICE_DESK_PUBLIC_URL') or env.get('RENDER_EXTERNAL_URL')),
                   password, shopline, line, user, endpoint, secret, enabled, login_id, login_secret)


def _database_valid(path, allowed_tables=None):
    if path.is_symlink() or path.resolve() != path.absolute() or path.stat().st_nlink != 1:
        _fail()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            _fail()
        schema = connection.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        tables = {name for kind, name, sql in schema if kind == 'table'}
        if (not {'wb_cases', 'wb_quotes', 'wb_audit'} <= tables
                or any(not name.startswith('wb_') for name in tables)
                or allowed_tables is not None and not tables <= allowed_tables
                or any(kind not in ('table', 'index') or 'VIRTUAL' in (sql or '').upper()
                       for kind, name, sql in schema)):
            _fail()
        row = connection.execute('SELECT data FROM wb_cases WHERE id=?', (APPROVED_CASE_ID,)).fetchone()
        try:
            data = json.loads(row[0]) if row else {}
        except (ValueError, TypeError):
            _fail()
        if data.get('source') != 'snapshot' or data.get('caseNumber') != APPROVED_CASE_NUMBER:
            _fail()


def prepare_database(data_dir=DATA_DIRECTORY, seed_path=None):
    """One-time, validated SQLite backup import; an existing database wins."""
    data_dir = Path(data_dir)
    if not data_dir.is_absolute() or data_dir.resolve() != data_dir.absolute() or data_dir.is_symlink():
        _fail()
    data_dir.mkdir(parents=True, exist_ok=True)
    if any((data_dir / name).exists() for name in ('repairs.db', 'payment-lab.db', 'line-config.json')):
        _fail()
    target = data_dir / 'service-desk.db'
    if target.exists():
        _database_valid(target)
        return target
    seed_path = Path(seed_path or os.environ.get('SERVICE_DESK_SEED_FILE', '/etc/secrets/service-desk-seed.b64'))
    if seed_path.name.lower() in ('repairs.db', 'payment-lab.db'):
        _fail()
    raw = _read_file(seed_path, 70 * 1024 * 1024)
    if seed_path.suffix == '.b64':
        try:
            raw = base64.b64decode(b''.join(raw.split()), validate=True)
        except (ValueError, binascii.Error):
            _fail()
    if not raw.startswith(b'SQLite format 3\x00') or len(raw) > 50 * 1024 * 1024:
        _fail()
    temporary = data_dir / ('.seed-' + uuid.uuid4().hex + '.db')
    staged = data_dir / ('.import-' + uuid.uuid4().hex + '.db')
    try:
        with temporary.open('xb') as output:
            output.write(raw)
        _database_valid(temporary, _SEED_TABLES)
        with closing(sqlite3.connect(temporary.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(staged)) as destination:
                source.backup(destination)
        _database_valid(staged, _SEED_TABLES)
        # Atomic publish without ever replacing an existing workbench database.
        os.link(staged, target)
        staged.unlink()
        try:
            target.chmod(0o600)
        except OSError:
            pass
    finally:
        for path in (temporary, staged):
            path.unlink(missing_ok=True)
    return target


class BackupWorker:
    def __init__(self, database):
        self.database = Path(database)
        self.stop_event = threading.Event()
        self.thread = None

    def run_once(self):
        _database_valid(self.database)
        directory = self.database.parent / 'backups'
        if directory.is_symlink() or directory.resolve().parent != self.database.parent.resolve():
            _fail()
        directory.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = directory / ('service-desk-' + stamp + '.db')
        with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
        _database_valid(target)
        for old in sorted(directory.glob('service-desk-*.db'))[:-3]:
            if old.is_symlink() or old.resolve().parent != directory.resolve():
                _fail()
            old.unlink()
        return target

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                pass  # Exception text can contain customer paths/data.
            self.stop_event.wait(86400)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name='service-desk-only-backup', daemon=True)
            self.thread.start()

    def stop(self, timeout=2):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout)


@dataclass
class Runtime:
    server: object = field(repr=False)
    config: Configuration = field(repr=False)
    workers: list = field(default_factory=list, repr=False)

    def stop(self):
        for worker in reversed(self.workers):
            worker.stop()


def bootstrap(*, config=None, data_dir=DATA_DIRECTORY, seed_path=None, start_workers=True):
    """Called inside one non-preloaded Gunicorn worker, never by production."""
    with _bootstrap_stage('config'):
        config = config or Configuration.load()
        if not isinstance(config, Configuration):
            _fail()
    with _bootstrap_stage('seed'):
        database = prepare_database(data_dir, seed_path)
    with _bootstrap_stage('server'):
        # No provider credentials are put in the formal repair environment.
        for name in list(os.environ):
            if name.startswith(('REPAIR_', 'LINE_', 'GOOGLE_', 'SHOPLINE_')):
                os.environ.pop(name)
        os.environ.update({'REPAIR_DEPLOYMENT': 'cloud', 'REPAIR_MODE': 'demo',
            'REPAIR_LOCAL_SETUP': '0', 'REPAIR_PAYMENT_LAB': '1', 'REPAIR_SERVICE_DESK': '1',
            'REPAIR_SERVICE_DESK_ISOLATED_IMPORT': '1',
            'REPAIR_DATA_DIR': str(database.parent), 'PUBLIC_URL': config.public_url,
            'REPAIR_ADMIN_PASSWORD': config.admin_password})
        import server
        if (server.DATA_DIR != database.parent.resolve() or server.PRIVATE
                or server.TOKEN or server.SECRET or server.MESSAGE_SECRET or not server.DEMO):
            _fail()
        server.SERVICE_DESK_CLOUD_INTERNAL = True
        server.SERVICE_DESK_RECONCILIATION_ALLOWED_CASES = frozenset({APPROVED_CASE_ID})
    with _bootstrap_stage('adapters'):
        from shopline_preview import ShoplinePreview
        from shopline_orders import fetch_repair_orders
        from line_case_test_sender import CaseBoundTestSender
        from service_desk_intake import TestIntake
        from service_desk_operations import ServiceDeskOperations
        import line_support
        desk = server.service_desk_service()
        intake = TestIntake(server.service_desk_connect, public_url=config.public_url,
            channel_id=config.test_login_id, channel_secret=config.test_login_secret,
            id_verifier=line_support.verify_id_token,
            profile_reader=lambda uid: line_support.get_profile(config.line_token, uid),
            legacy_case=APPROVED_CASE_ID if config.line_user else '', legacy_user=config.line_user)
        intake.init()
        server.SERVICE_DESK_TEST_INTAKE = intake
        server.SERVICE_DESK_RECONCILIATION_ALLOWED_CASES = lambda: intake.allowed_case_ids() | {APPROVED_CASE_ID}
        server.SERVICE_DESK_ORDER_PREVIEW = ShoplinePreview(lambda: config.shopline_token,
            lambda: desk.state()['cases'], fetch_repair_orders)
        server.SERVICE_DESK_LINE_TEST_SENDER = CaseBoundTestSender(token=config.line_token,
            recipient_resolver=intake.recipient)
        server.SERVICE_DESK_PAYMENT_SHEET_TARGET = {'sheetId': TEST_SHEET_ID,
            'url': 'https://docs.google.com/spreadsheets/d/' + TEST_SHEET_ID + '/edit#gid=515406948'}
        server.service_desk_reconciliation_service()
        sync = server.service_desk_payment_sheet_service()
        def case_quote(case_id):
            wrapper = desk.get_case(case_id)
            return {**wrapper, 'quote': wrapper['case'].get('latestQuote')}
        operations = ServiceDeskOperations(server.service_desk_connect,
            quote_reader=case_quote,
            payment_reader=lambda cid: next(iter(sync.preview(cid)['rows']), None),
            allowed_case_ids=lambda cid: cid in server.service_desk_allowed_case_ids())
        operations.init()
        server.SERVICE_DESK_OPERATIONS = operations
        from service_desk_receipts import ServiceDeskReceipts
        receipts = ServiceDeskReceipts(server.service_desk_connect,
            quote_reader=case_quote,
            payment_reader=lambda cid: sync.preview()['rows'] if cid is None else next(iter(sync.preview(cid)['rows']), None),
            sender=server.SERVICE_DESK_LINE_TEST_SENDER,
            allowed_case_ids=server.SERVICE_DESK_RECONCILIATION_ALLOWED_CASES,
            enabled=config.automation_enabled)
        receipts.init()
        server.SERVICE_DESK_RECEIPTS = receipts
        from service_desk_refund_notices import ServiceDeskRefundNotices
        refund_notices = ServiceDeskRefundNotices(server.service_desk_connect,
            quote_reader=case_quote,
            payment_reader=lambda cid: sync.preview()['rows'] if cid is None else next(iter(sync.preview(cid)['rows']), None),
            sender=server.SERVICE_DESK_LINE_TEST_SENDER,
            allowed_case_ids=server.SERVICE_DESK_RECONCILIATION_ALLOWED_CASES,
            enabled=config.automation_enabled)
        refund_notices.init()
        server.SERVICE_DESK_REFUND_NOTICES = refund_notices
        runtime = Runtime(server, config)
        if config.sheet_endpoint:
            from payment_sheet_worker import PaymentSheetWorker
            worker = PaymentSheetWorker(sync, endpoint=config.sheet_endpoint,
                secret=config.sheet_secret, sheet_id=TEST_SHEET_ID,
                allowed_case_ids=server.SERVICE_DESK_RECONCILIATION_ALLOWED_CASES)
            server.SERVICE_DESK_PAYMENT_SHEET_WORKER = worker
            runtime.workers.append(worker)
        from service_desk_automation import ServiceDeskAutomation
        automation = ServiceDeskAutomation(server.service_desk_connect, quote_reader=desk.get_quote,
            line_sender=server.SERVICE_DESK_LINE_TEST_SENDER,
            order_provider=server.SERVICE_DESK_ORDER_PREVIEW, reconcile=server.service_desk_reconcile,
            allowed_case_ids=server.SERVICE_DESK_RECONCILIATION_ALLOWED_CASES,
            enabled=config.automation_enabled)
        automation.init()
        server.SERVICE_DESK_AUTOMATION = automation
        runtime.workers.extend((automation, receipts, refund_notices, BackupWorker(database)))
    with _bootstrap_stage('workers'):
        if start_workers:
            for worker in runtime.workers:
                worker.start()
            atexit.register(runtime.stop)
    return runtime


class RequestRejected(Exception):
    def __init__(self, status):
        self.status = status


def _target(environ):
    target = environ.get('RAW_URI') or environ.get('REQUEST_URI')
    if not target:
        target = environ.get('PATH_INFO', '/') + ('?' + environ['QUERY_STRING'] if environ.get('QUERY_STRING') else '')
    if (not isinstance(target, str) or not target.startswith('/') or target.startswith('//')
            or _CONTROL.search(target) or '\\' in target or '#' in target):
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
                or re.search(r'[\x00-\x08\x0a-\x1f\x7f]', value)
                or key in ('HTTP_CONTENT_LENGTH', 'HTTP_CONTENT_TYPE')):
            raise RequestRejected(400)
        headers[name] = value
    return headers


def _body(environ, headers):
    raw = environ.get('CONTENT_LENGTH', '')
    if raw and re.fullmatch(r'[0-9]+', raw) is None:
        raise RequestRejected(400)
    length = int(raw) if raw else 0
    if length > MAX_BODY_BYTES:
        raise RequestRejected(413)
    # Gunicorn 26 marks every parsed request input_terminated, including framed
    # Content-Length requests. It is not evidence of chunked transfer encoding.
    if headers.get('Transfer-Encoding'):
        raise RequestRejected(400)
    source = environ.get('wsgi.input')
    data = source.read(length) if length and source is not None else b''
    if not isinstance(data, bytes) or len(data) != length:
        raise RequestRejected(400)
    if 'Content-Length' in headers:
        del headers['Content-Length']
    headers['Content-Length'] = str(len(data))
    return data


def _response(start_response, status, headers, body, head=False):
    headers = [(key, value) for key, value in headers
        if key.lower() not in _HOP_HEADERS | {'content-length'}]
    present = {key.lower() for key, value in headers}
    for key, value in [('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
        ('X-Frame-Options', 'DENY'), ('X-Robots-Tag', 'noindex, nofollow, noarchive'),
        ('Strict-Transport-Security', 'max-age=31536000'), ('Cache-Control', 'no-store')]:
        if key.lower() not in present:
            headers.append((key, value))
    headers.append(('Content-Length', str(len(body))))
    start_response(str(status) + ' ' + HTTPStatus(status).phrase, headers)
    return [b'' if head else body]


def _json_response(start_response, status, payload, head=False):
    return _response(start_response, status, [('Content-Type', 'application/json; charset=utf-8')],
        json.dumps(payload, ensure_ascii=False).encode('utf-8'), head)


_INTAKE_PATHS = frozenset({'/test-application', '/test-line-login', '/test-line-callback',
    '/api/test-intake/session', '/api/test-intake/cases', '/api/test-intake/logout'})


def _cookie(headers, name):
    values = headers.get_all('Cookie', [])
    if len(values) > 1 or any(len(value) > 8192 for value in values):
        raise RequestRejected(400)
    parsed = SimpleCookie()
    try:
        parsed.load(values[0] if values else '')
        return parsed[name].value if name in parsed else ''
    except Exception:
        raise RequestRejected(400) from None


def _set_cookie(name, value, maximum=86400):
    # All values are server-generated opaque tokens, never identity/contact data.
    if value and re.fullmatch(r'[A-Za-z0-9_-]{43}', value) is None:
        raise ValueError('Invalid internal session')
    return ('Set-Cookie', name + '=' + value + '; Path=/; Max-Age=' + str(maximum)
            + '; Secure; HttpOnly; SameSite=Lax')


def _intake_request(current, path, query, method, headers, body, start_response, head):
    intake = getattr(current.server, 'SERVICE_DESK_TEST_INTAKE', None)
    if intake is None:
        raise RequestRejected(503)
    session = _cookie(headers, 'wb_intake_session')
    identity = intake.identity(session) if session else None
    if path == '/test-application':
        try:
            parameters = parse_qs(query, keep_blank_values=True, strict_parsing=bool(query), max_num_fields=2)
        except ValueError:
            raise RequestRejected(400) from None
        if set(parameters) - {'invite', 'login'} or any(len(v) != 1 for v in parameters.values()):
            raise RequestRejected(400)
        response_headers = [('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")]
        if 'invite' in parameters:
            if not intake.valid_invite(parameters['invite'][0]):
                raise RequestRejected(403)
            response_headers.append(_set_cookie('wb_intake_invite', parameters['invite'][0]))
            # Strip the invitation capability from the address bar before rendering.
            return _response(start_response, 303, response_headers + [('Location', '/test-application')], b'', head)
        if parameters.get('login', [''])[0] not in ('', 'failed'):
            raise RequestRejected(400)
        content = (Path(__file__).parent / 'test-application.html').read_bytes()
        return _response(start_response, 200, response_headers, content, head)
    if path == '/test-line-login':
        if query:
            raise RequestRejected(400)
        try:
            state, destination = intake.start(_cookie(headers, 'wb_intake_invite'))
        except ValueError:
            raise RequestRejected(403) from None
        return _response(start_response, 303, [('Location', destination),
            _set_cookie('wb_intake_state', state, 600)], b'', head)
    if path == '/test-line-callback':
        if len(query) > 4096:
            raise RequestRejected(400)
        try:
            parameters = parse_qs(query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
            if 'error' in parameters:
                provider_code = parameters['error'][0].lower()
                known_errors = {'access_denied', 'invalid_request', 'unauthorized_client',
                    'server_error', 'temporarily_unavailable', 'login_required',
                    'interaction_required', 'consent_required', 'unsupported_response_type', 'invalid_scope'}
                label = provider_code if provider_code in known_errors else 'other_provider_error'
                logging.getLogger('petpivot.internal.intake').warning(
                    'internal_test_intake_failure stage=callback_provider_%s', label)
                raise ValueError()
            # RFC 6749 section 4.1.2: ignore extension response parameters.
            # Only the validated code/state participate in authentication;
            # unknown fields never become an identity or redirect target.
            if any(len(parameters.get(key, [])) != 1 for key in ('code', 'state')):
                logging.getLogger('petpivot.internal.intake').warning(
                    'internal_test_intake_failure stage=callback_parameters')
                raise ValueError()
            token = intake.finish(parameters.get('state', [''])[0],
                _cookie(headers, 'wb_intake_state'), parameters.get('code', [''])[0])
        except (ValueError, TypeError):
            return _response(start_response, 303, [('Location', '/test-application?login=failed'),
                _set_cookie('wb_intake_state', '', 0)], b'', head)
        return _response(start_response, 303, [('Location', '/test-application'),
            _set_cookie('wb_intake_session', token), _set_cookie('wb_intake_state', '', 0)], b'', head)
    if query:
        raise RequestRejected(400)
    if path == '/api/test-intake/session':
        invited = intake.valid_invite(_cookie(headers, 'wb_intake_invite'))
        return _json_response(start_response, 200, {'configured': intake.configured(),
            'authenticated': bool(identity), 'profile': {'displayName': identity['displayName']} if identity else None,
            'customerSession': bool(identity), 'formEnabled': bool(identity), 'invited': invited,
            'source': 'test_intake', 'internalOnly': True}, head)
    if headers.get_content_type() != 'application/json' or not body:
        raise RequestRejected(400)
    try:
        payload = json.loads(body.decode('utf-8'), object_pairs_hook=_unique,
            parse_constant=lambda value: _fail())
    except (ValueError, UnicodeError):
        raise RequestRejected(400) from None
    if type(payload) is not dict:
        raise RequestRejected(400)
    if path == '/api/test-intake/logout':
        if payload:
            raise RequestRejected(400)
        intake.logout(session)
        return _response(start_response, 200, [('Content-Type', 'application/json'),
            _set_cookie('wb_intake_session', '', 0)], b'{"ok":true}', head)
    if identity is None:
        raise RequestRejected(401)
    if (set(payload) != {'name', 'phone', 'address', 'model', 'shipping', 'originalOrderNumber',
            'problem', 'consent', 'requestId'} or payload.get('consent') is not True):
        raise RequestRejected(400)
    request_id = payload.pop('requestId')
    try:
        # The service deduplicates one customer's request before inserting.
        result = current.server.service_desk_service().create_verified_intake(payload, identity, request_id)
        intake.consent(identity['customerId'])
        case = result.get('case', result)
        case_id = case['id']
        current.server.service_desk_enqueue_payment_sheet(case_id)
        operations = getattr(current.server, 'SERVICE_DESK_OPERATIONS', None)
        if operations is not None:
            operations.refresh(case_id)
        return _json_response(start_response, 200, {'case': case, 'internalOnly': True}, head)
    except (ValueError, TypeError, KeyError):
        raise RequestRejected(400) from None


def create_app(runtime=None, runtime_factory=bootstrap):
    """Lazy bootstrap keeps import inert and starts threads inside the worker."""
    lock = threading.Lock()
    holder = [runtime]

    def app(environ, start_response):
        method = environ.get('REQUEST_METHOD', '')
        head = method == 'HEAD'
        try:
            if method not in ('GET', 'HEAD', 'POST'):
                raise RequestRejected(405)
            target = _target(environ)
            parsed = urlsplit(target)
            path = parsed.path
            if (path not in ('/', '/admin/service-desk', '/api/admin-login', '/api/logout', '/healthz') and path not in _INTAKE_PATHS
                    and not path.startswith('/api/service-desk/')):
                raise RequestRejected(404)
            if ((path in ('/', '/admin/service-desk', '/healthz') and method == 'POST')
                    or path in ('/api/admin-login', '/api/logout') and method != 'POST'):
                raise RequestRejected(405)
            if path in _INTAKE_PATHS and ((path in ('/api/test-intake/cases', '/api/test-intake/logout')) != (method == 'POST')):
                raise RequestRejected(405)
            if path in ('/', '/admin/service-desk', '/api/admin-login', '/api/logout', '/healthz') and parsed.query:
                raise RequestRejected(400)
            headers = _headers(environ)
            # Render forwards TLS through Gunicorn's trusted forwarded-proto
            # handling. Do not accept an HTTP request or arbitrary Host header.
            health_probe = path == '/healthz' and method in ('GET', 'HEAD')
            if not health_probe and environ.get('wsgi.url_scheme') != 'https':
                raise RequestRejected(403)
            with lock:
                if holder[0] is None:
                    try:
                        holder[0] = runtime_factory()
                    except Exception as error:
                        _report_bootstrap_failure(error)
                        raise
                current = holder[0]
            if not health_probe and headers.get_all('Host', []) != [urlsplit(current.config.public_url).netloc]:
                raise RequestRejected(403)
            if method == 'POST' and headers.get_all('Origin', []) != [current.config.public_url]:
                raise RequestRejected(403)
            body = _body(environ, headers)
            if path in _INTAKE_PATHS:
                return _intake_request(current, path, parsed.query, method, headers, body, start_response, head)
            if path == '/':
                return _response(start_response, 303, [('Location', '/admin/service-desk')], b'', head)
            if path == '/healthz':
                try:
                    with current.server.service_desk_connect() as connection:
                        connection.execute('SELECT 1 FROM wb_cases LIMIT 1').fetchone()
                except Exception:
                    return _json_response(start_response, 503, {'ok': False}, head)
                return _json_response(start_response, 200, {'ok': True, 'internalOnly': True}, head)
            if path in ('/api/admin-login', '/api/logout'):
                if headers.get_content_type() != 'application/json' or not body:
                    raise RequestRejected(400)
                try:
                    payload = json.loads(body.decode('utf-8'), object_pairs_hook=_unique)
                except (ValueError, UnicodeError):
                    raise RequestRejected(400) from None
                expected = {'password'} if path.endswith('admin-login') else set()
                if type(payload) is not dict or set(payload) != expected:
                    raise RequestRejected(400)
            # Proxy transport headers do not belong to the repair business
            # handler. Host, Origin and TLS were validated by this adapter.
            for name in ('Cf-Connecting-IP', 'X-Forwarded-For', 'Forwarded', 'X-Forwarded-Proto'):
                if name in headers:
                    del headers[name]
            server = current.server

            class Handler(server.Handler):
                def __init__(self):
                    self.path, self.headers, self.command = target, headers, method
                    self.request_version = 'HTTP/1.1'
                    self.client_address = (environ.get('REMOTE_ADDR', ''), 0)
                    self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
                    self.response_status, self.response_headers = None, []

                def send_response(self, code, message=None):
                    self.response_status, self.response_headers = code, []

                def send_header(self, keyword, value):
                    key, value = str(keyword), str(value)
                    if not _HEADER_NAME.fullmatch(key) or re.search(r'[\r\n\x00]', value):
                        raise ValueError('Invalid response header')
                    if key.lower() not in _HOP_HEADERS:
                        self.response_headers.append((key, value))

                def end_headers(self):
                    pass

                def log_message(self, *args):
                    pass

            handler = Handler()
            if method in ('GET', 'HEAD'):
                handler.do_GET()
            else:
                handler.do_POST()
            if handler.response_status is None:
                raise ValueError('Missing response')
            return _response(start_response, handler.response_status, handler.response_headers,
                handler.wfile.getvalue(), head)
        except RequestRejected as error:
            return _json_response(start_response, error.status, {'error': '內測請求無法完成'}, head)
        except Exception:
            return _json_response(start_response, 503, {'error': '獨立內測服務尚未就緒，請聯絡管理員'}, head)

    return app


application = create_app()
