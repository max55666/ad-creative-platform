import os, json, sqlite3, secrets, hashlib, time, urllib.request, urllib.parse, base64, re, uuid, subprocess, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from http.cookies import SimpleCookie
from contextlib import contextmanager, closing
from line_support import load_private_config, verify_id_token, validate_webhook_signature, inspect_bot, get_profile, send_push, send_reply, get_webhook_endpoint, set_webhook_endpoint, get_group_summary, send_group_text
from cloud_support import build_payload, init_queue, validate_endpoint, validate_secret, format_sheet_phone, PRIMARY_SHEET_ID, PICKUP_SHEET_ID, PICKUP_SHEET_GID
from dispatch_workflow import DispatchWorkflow, init_tables as init_dispatch_workflow, cancel_for_group as cancel_dispatch_workflow
from address_support import public_address_data, validate_case_addresses

ROOT = Path(__file__).parent
CLOUD_DEPLOYMENT = os.environ.get('REPAIR_DEPLOYMENT','').strip().lower()=='cloud'
LOCAL_SETUP_ENABLED = not CLOUD_DEPLOYMENT and os.environ.get('REPAIR_LOCAL_SETUP','1')=='1'
RUNTIME_ENV = os.environ.get('REPAIR_DATA_DIR','').strip()
DATA_DIR = (Path(RUNTIME_ENV) if RUNTIME_ENV else ROOT/'runtime').resolve()
if not RUNTIME_ENV and not DATA_DIR.is_relative_to(ROOT.resolve()):
    raise ValueError('Repair runtime directory is invalid')
DB = DATA_DIR / 'repairs.db'
DATA_DIR.mkdir(parents=True,exist_ok=True)
PUBLIC_SETTINGS = json.loads((ROOT / 'settings.json').read_text(encoding='utf-8'))
PRIVATE = load_private_config(ROOT, DATA_DIR if RUNTIME_ENV else None)
DEMO = os.environ.get('REPAIR_MODE', PRIVATE.get('mode','demo')) == 'demo'
PUBLIC_BASE = os.environ.get('PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL')
BASE = (PUBLIC_BASE or ('' if CLOUD_DEPLOYMENT else PRIVATE.get('publicUrl') or PUBLIC_SETTINGS.get('publicUrl') or 'http://127.0.0.1:8787')).rstrip('/')
CID = os.environ.get('LINE_CHANNEL_ID', PRIVATE.get('loginChannelId') or PUBLIC_SETTINGS.get('lineLoginChannelId',''))
LIFF_ID = os.environ.get('LINE_LIFF_ID', PRIVATE.get('liffId') or PUBLIC_SETTINGS.get('liffId',''))
SECRET = os.environ.get('LINE_CHANNEL_SECRET', PRIVATE.get('loginChannelSecret',''))
TOKEN = os.environ.get('LINE_ACCESS_TOKEN', PRIVATE.get('messagingAccessToken',''))
MESSAGE_SECRET = os.environ.get('LINE_MESSAGING_CHANNEL_SECRET', PRIVATE.get('messagingChannelSecret',''))
BOT_UID = os.environ.get('LINE_BOT_USER_ID', PRIVATE.get('botUserId',''))
OA = os.environ.get('LINE_OA_ID', PUBLIC_SETTINGS.get('lineOfficialAccountId', ''))
ADMIN = os.environ.get('REPAIR_ADMIN_PASSWORD', PRIVATE.get('adminPassword',''))
sessions, states, auth_attempts = {}, {}, {}
SETUP_TOKEN=secrets.token_urlsafe(32)
STATUS = ['已申請','待收件','已收件','檢測中','待客戶確認報價','維修中','待寄回','已寄回','已結案','待補資料','不維修退回','已取消']
PROBE_HEADING = '【維修申請連線確認】'
SUMMARY_HEADING = 'PetPivot 已收到您的商品檢修申請'
CONFIRMATION_HEADING = '【維修申請確認】'
SUMMARY_FOOTER = '如需補充資訊，請直接在此聊天室留言並附上案件編號。'
CASE_REFERENCE = re.compile(r'(?:案件|維修)編號[：:]\s*(R\d{8}-\d{4,})(?!\d)')
NONCE_PATTERN = re.compile(r'[A-Za-z0-9_-]{32}\Z')
ENTRY_TICKET_PATTERN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
ENTRY_SESSION_FIELDS = ('officialEntry','officialEntryExpiresAt','officialEntryTicketHash','officialEntryBotUserId')
SUMMARY_FIELDS_PATTERN = r'案件編號[：:][ \t]*(R\d{8}-\d{4,})[ \t]*\r?\n申請人[：:]([^\r\n]+)\r?\n訂單編號[：:]([^\r\n]+)'
# Keep pre-update summaries valid for already-open customer pages.
SUMMARY_SHIPPING_PATTERN = r'(?:\r?\n寄送方式[：:]([^\r\n]+))?'
THREE_LINE_SUMMARY = re.compile(SUMMARY_FIELDS_PATTERN+SUMMARY_SHIPPING_PATTERN+r'\Z')
CONFIRMATION_SUMMARY = re.compile(re.escape(CONFIRMATION_HEADING)+r'\r?\n'+SUMMARY_FIELDS_PATTERN+SUMMARY_SHIPPING_PATTERN+r'\r?\n\r?\n'+re.escape(SUMMARY_FOOTER)+r'\Z')
CLOUD_WAKE = threading.Event()
CLOUD_LOCK = threading.Lock()
CLOUD_WORKER_STARTED = False
CLOUD_VERIFIED_FINGERPRINT = ''
CLOUD_VERIFY_NEXT = 0
PICKUP_VERIFIED_FINGERPRINT = ''
PICKUP_VERIFY_NEXT = 0
PICKUP_NOTIFICATION_LOCK = threading.Lock()
PICKUP_GROUP_PATTERN = re.compile(r'C[0-9a-f]{32}\Z')
PICKUP_NOTIFICATION_RETRY_SECONDS = 23*3600
PICKUP_DISPATCH_PATTERN = re.compile(r'(R[0-9]{8}-[0-9]{4,})\s*已派車\Z')
PICKUP_DISPATCH_VERIFIED_FINGERPRINT = ''
PICKUP_DISPATCH_VERIFY_NEXT = 0
PICKUP_DISPATCH_LOCK = threading.Lock()
SERVICE_STARTED = False
SERVICE_LOCK = threading.Lock()
PAYMENTS = None
PAYMENT_WORKFLOW = 'payment-v1'
PAYMENT_REQUIRED_STATUSES = frozenset(('待收件','已收件','檢測中','維修中','待寄回','已寄回','已結案'))
DISPATCH_TEST_WARNING = '【系統驗收測試｜請勿實際派車】'
@contextmanager
def connect():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with c: yield c
    finally: c.close()

def seed_case_number_sequences(c,day=None):
    """Raise durable daily watermarks from existing/deleted IDs; never lower."""
    query='SELECT id FROM cases UNION ALL SELECT case_id AS id FROM deleted_case_requests'
    args=()
    if day is not None:
        prefix='R'+day+'-%'
        query='SELECT id FROM cases WHERE id LIKE ? UNION ALL SELECT case_id AS id FROM deleted_case_requests WHERE case_id LIKE ?'
        args=(prefix,prefix)
    maxima={}
    for row in c.execute(query,args):
        match=re.fullmatch(r'R([0-9]{8})-([0-9]{4,})',row['id'])
        if match:
            number=int(match[2])
            maxima[match[1]]=max(maxima.get(match[1],0),number)
    for date,number in maxima.items():
        c.execute('''INSERT INTO case_number_sequences(day,last_number) VALUES(?,?)
            ON CONFLICT(day) DO UPDATE SET last_number=excluded.last_number
            WHERE excluded.last_number>case_number_sequences.last_number''',(date,number))

def next_case_number(c,day):
    """Allocate inside the same BEGIN IMMEDIATE transaction as case insertion."""
    if not c.in_transaction or not isinstance(day,str) or not re.fullmatch(r'[0-9]{8}',day):
        raise ValueError('案件編號必須在申請交易中產生')
    # Also tolerate a reviewed import made after process startup.
    seed_case_number_sequences(c,day)
    c.execute('INSERT OR IGNORE INTO case_number_sequences(day,last_number) VALUES(?,0)',(day,))
    c.execute('UPDATE case_number_sequences SET last_number=last_number+1 WHERE day=?',(day,))
    number=c.execute('SELECT last_number FROM case_number_sequences WHERE day=?',(day,)).fetchone()[0]
    return 'R'+day+'-'+str(number).zfill(4)

def init_db():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, request_id TEXT NOT NULL, data TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, history TEXT NOT NULL, note TEXT NOT NULL DEFAULT "", notification TEXT NOT NULL DEFAULT "未傳送", UNIQUE(user_id, request_id))')
        c.execute('''CREATE TABLE IF NOT EXISTS deleted_case_requests (
            user_id TEXT NOT NULL,request_id TEXT NOT NULL,case_id TEXT NOT NULL,deleted_at TEXT NOT NULL,
            PRIMARY KEY(user_id,request_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS case_number_sequences (
            day TEXT PRIMARY KEY,last_number INTEGER NOT NULL
            CHECK(typeof(last_number)='integer' AND last_number>=0))''')
        seed_case_number_sequences(c)
        columns=[row['name'] for row in c.execute('PRAGMA table_info(cases)')]
        if 'cloud_revision' not in columns: c.execute('ALTER TABLE cases ADD COLUMN cloud_revision INTEGER NOT NULL DEFAULT 0')
        if 'line_display_name' not in columns: c.execute('ALTER TABLE cases ADD COLUMN line_display_name TEXT NOT NULL DEFAULT ""')
        c.execute('CREATE TABLE IF NOT EXISTS line_receipts (case_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,received TEXT NOT NULL,event_id TEXT UNIQUE NOT NULL)')
        if 'summary_received' not in [row['name'] for row in c.execute('PRAGMA table_info(line_receipts)')]:
            c.execute('ALTER TABLE line_receipts ADD COLUMN summary_received TEXT NOT NULL DEFAULT ""')
        c.execute('CREATE TABLE IF NOT EXISTS line_handshakes (nonce TEXT PRIMARY KEY,case_id TEXT NOT NULL,user_id TEXT NOT NULL,expires REAL NOT NULL,confirmed TEXT NOT NULL DEFAULT "",event_id TEXT NOT NULL DEFAULT "")')
        c.execute('CREATE TABLE IF NOT EXISTS line_webhook_events (event_id TEXT PRIMARY KEY,received REAL NOT NULL,reply_result TEXT NOT NULL DEFAULT "")')
        c.execute('CREATE TABLE IF NOT EXISTS line_entry_tickets (ticket_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,bot_user_id TEXT NOT NULL,expires REAL NOT NULL,created REAL NOT NULL,event_id TEXT UNIQUE NOT NULL)')
        c.execute('CREATE INDEX IF NOT EXISTS line_entry_tickets_expiry ON line_entry_tickets(expires)')
        c.execute('CREATE TABLE IF NOT EXISTS line_outbox (message_key TEXT PRIMARY KEY,retry_key TEXT NOT NULL,result TEXT NOT NULL DEFAULT "",created REAL NOT NULL DEFAULT 0)')
        if 'created' not in [row['name'] for row in c.execute('PRAGMA table_info(line_outbox)')]:
            c.execute('ALTER TABLE line_outbox ADD COLUMN created REAL NOT NULL DEFAULT 0')
        init_queue(c)
        c.execute('CREATE TABLE IF NOT EXISTS cloud_sync_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL,revision INTEGER NOT NULL,started REAL NOT NULL,finished REAL NOT NULL DEFAULT 0,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT "")')
        c.execute('''CREATE TABLE IF NOT EXISTS pickup_outbox (
            case_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',
            synced_at TEXT NOT NULL DEFAULT '',enrolled_at TEXT NOT NULL)''')
        c.execute('CREATE TABLE IF NOT EXISTS pickup_sync_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT NOT NULL,revision INTEGER NOT NULL,started REAL NOT NULL,finished REAL NOT NULL DEFAULT 0,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT "")')
        c.execute('''CREATE TABLE IF NOT EXISTS pickup_notification_groups (
            group_id TEXT PRIMARY KEY,name TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 0,
            event_stamp INTEGER NOT NULL,verified_event_stamp INTEGER NOT NULL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS pickup_notification_settings (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),group_id TEXT NOT NULL DEFAULT '')''')
        c.execute("INSERT OR IGNORE INTO pickup_notification_settings(singleton,group_id) VALUES(1,'')")
        c.execute('''CREATE TABLE IF NOT EXISTS pickup_notification_events (
            event_id TEXT PRIMARY KEY,group_id TEXT NOT NULL,event_type TEXT NOT NULL,event_stamp INTEGER NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS pickup_notification_outbox (
            case_id TEXT PRIMARY KEY,group_id TEXT NOT NULL,retry_key TEXT UNIQUE NOT NULL,message TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'waiting_sheet',created REAL NOT NULL,first_attempt REAL NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',result TEXT NOT NULL DEFAULT '',accepted_at TEXT NOT NULL DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS pickup_dispatch_outbox (
            case_id TEXT PRIMARY KEY,group_id TEXT NOT NULL,command_id TEXT UNIQUE NOT NULL,created REAL NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',synced_at TEXT NOT NULL DEFAULT '')''')
        if 'event_stamp' not in [row['name'] for row in c.execute('PRAGMA table_info(pickup_dispatch_outbox)')]:
            c.execute('ALTER TABLE pickup_dispatch_outbox ADD COLUMN event_stamp INTEGER NOT NULL DEFAULT 0')
        c.execute('''CREATE TABLE IF NOT EXISTS pickup_dispatch_events (
            event_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,event_stamp INTEGER NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS pickup_dispatch_events_case_stamp ON pickup_dispatch_events(case_id,event_stamp)')
        # Older jobs did not retain the LINE event timestamp. Preserve their
        # event IDs and conservatively seed the watermark from receipt time.
        c.execute('UPDATE pickup_dispatch_outbox SET event_stamp=CAST(created*1000 AS INTEGER) WHERE event_stamp=0')
        c.execute('''INSERT OR IGNORE INTO pickup_dispatch_events(event_id,case_id,event_stamp)
            SELECT command_id,case_id,event_stamp FROM pickup_dispatch_outbox''')
        if 'result_action' not in [row['name'] for row in c.execute('PRAGMA table_info(pickup_dispatch_outbox)')]:
            c.execute('ALTER TABLE pickup_dispatch_outbox ADD COLUMN result_action TEXT NOT NULL DEFAULT ""')
        init_dispatch_workflow(c)
init_db()

def pickup_notification_available():
    return bool(not DEMO and TOKEN and MESSAGE_SECRET and BOT_UID)

def selected_pickup_group(c):
    return c.execute('''SELECT g.* FROM pickup_notification_settings s JOIN pickup_notification_groups g
        ON g.group_id=s.group_id WHERE s.singleton=1''').fetchone()

def active_pickup_group(group):
    return bool(group and group['active'] and group['name']
                and group['verified_event_stamp']==group['event_stamp'])

def cancel_pickup_notifications(c,group_id=None,reason='group_changed'):
    condition=' AND group_id=?' if group_id else ''
    args=(reason,group_id) if group_id else (reason,)
    c.execute("UPDATE pickup_notification_outbox SET state='cancelled',last_error=? WHERE state IN ('waiting_sheet','pending','failed','working','needs_review')"+condition,args)
    c.execute("UPDATE pickup_dispatch_outbox SET state='cancelled',last_error=? WHERE state IN ('pending','failed','working')"+condition,args)
    cancel_dispatch_workflow(c,group_id)

def observe_pickup_group(event):
    """Called only after raw webhook signature and bot destination verification."""
    source=event.get('source',{}); kind=event.get('type'); group_id=source.get('groupId')
    message=event.get('message',{})
    if kind=='message' and (not isinstance(message,dict) or message.get('type')!='text' or message.get('text')!='派車通知設定'): return
    if kind not in ('join','leave','message') or not isinstance(group_id,str) or not PICKUP_GROUP_PATTERN.fullmatch(group_id): return
    ident=event.get('webhookEventId'); stamp=event.get('timestamp')
    if (not isinstance(ident,str) or not 1<=len(ident)<=128 or type(stamp) is not int
            or stamp<=0 or stamp>int(time.time()*1000)+300000): return
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            prior=c.execute('SELECT * FROM pickup_notification_groups WHERE group_id=?',(group_id,)).fetchone()
            if not prior and c.execute('SELECT COUNT(*) FROM pickup_notification_groups').fetchone()[0]>=100: return
            if not c.execute('INSERT OR IGNORE INTO pickup_notification_events VALUES(?,?,?,?)',(ident,group_id,kind,stamp)).rowcount: return
            # Leave wins equal timestamps; stale events cannot revive a group.
            if prior and (stamp<prior['event_stamp'] or (stamp==prior['event_stamp'] and not prior['active'] and kind!='leave')): return
            active=0 if kind=='leave' else 1
            # A signed keyword from the same already confirmed active group
            # refreshes its metadata without temporarily disabling that binding.
            carry_verified=(kind=='message' and active_pickup_group(prior))
            verified=stamp if carry_verified else 0
            c.execute('''INSERT INTO pickup_notification_groups(group_id,active,event_stamp,verified_event_stamp) VALUES(?,?,?,?)
                ON CONFLICT(group_id) DO UPDATE SET active=excluded.active,event_stamp=excluded.event_stamp,verified_event_stamp=excluded.verified_event_stamp''',(group_id,active,stamp,verified))
            if not active: cancel_pickup_notifications(c,group_id,'group_inactive')
        if kind=='leave': return
    # Name lookup is read-only and outside the DB transaction. A later distinct
    # keyword event can retry it; duplicate webhook deliveries never repeat it.
    if not TOKEN or DEMO: return
    try: summary=get_group_summary(TOKEN,group_id)
    except ValueError: return
    if summary.get('groupId')!=group_id or not isinstance(summary.get('groupName'),str): return
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c:
            c.execute('''UPDATE pickup_notification_groups SET name=?,verified_event_stamp=?
                WHERE group_id=? AND active=1 AND event_stamp=?''',(summary['groupName'],stamp,group_id,stamp))
    CLOUD_WAKE.set()

def bind_pickup_notification_group(group_id):
    """Explicit admin action: bind/disable future notices without sending any."""
    if group_id== '':
        with PICKUP_NOTIFICATION_LOCK:
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute("UPDATE pickup_notification_settings SET group_id='' WHERE singleton=1")
                cancel_pickup_notifications(c,reason='notifications_disabled')
        return True
    if not isinstance(group_id,str) or not PICKUP_GROUP_PATTERN.fullmatch(group_id): raise ValueError('invalid_group')
    if not pickup_notification_available(): raise ValueError('not_available')
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c: candidate=c.execute('SELECT * FROM pickup_notification_groups WHERE group_id=? AND active=1',(group_id,)).fetchone()
        if not active_pickup_group(candidate): raise ValueError('unobserved_group')
        try: summary=get_group_summary(TOKEN,group_id)
        except ValueError: raise ValueError('group_unavailable') from None
        name=summary.get('groupName')
        if summary.get('groupId')!=group_id or not isinstance(name,str) or not name.strip() or len(name)>300: raise ValueError('group_unavailable')
        if candidate['name'] and candidate['name']!=name:
            with connect() as c:
                c.execute('UPDATE pickup_notification_groups SET name=?,verified_event_stamp=event_stamp WHERE group_id=? AND active=1 AND event_stamp=?',(name,group_id,candidate['event_stamp']))
            raise ValueError('group_name_changed')
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT * FROM pickup_notification_groups WHERE group_id=? AND active=1',(group_id,)).fetchone()
            if not current or current['event_stamp']!=candidate['event_stamp']: raise ValueError('group_changed')
            prior=c.execute('SELECT group_id FROM pickup_notification_settings WHERE singleton=1').fetchone()[0]
            if prior!=group_id: cancel_pickup_notifications(c,reason='group_changed')
            c.execute('UPDATE pickup_notification_groups SET name=?,verified_event_stamp=event_stamp WHERE group_id=?',(name,group_id))
            c.execute('UPDATE pickup_notification_settings SET group_id=? WHERE singleton=1',(group_id,))
    return True

def pickup_notification_status():
    with connect() as c:
        selected=selected_pickup_group(c)
        groups=[{'id':g['group_id'],'name':g['name'],'active':active_pickup_group(g)}
                for g in c.execute('SELECT * FROM pickup_notification_groups ORDER BY event_stamp DESC LIMIT 100')]
        counts={r['state']:r['n'] for r in c.execute('SELECT state,COUNT(*) AS n FROM pickup_notification_outbox GROUP BY state')}
        last=c.execute("SELECT MAX(accepted_at) FROM pickup_notification_outbox WHERE state='accepted'").fetchone()[0]
    return {'available':bool(not DEMO and TOKEN),'enabled':bool(pickup_notification_available() and active_pickup_group(selected)),
            'group':{'id':selected['group_id'],'name':selected['name']} if selected else None,'groups':groups,
            'pending':sum(counts.get(state,0) for state in ('waiting_sheet','pending','working')),
            'failed':counts.get('failed',0)+counts.get('needs_review',0),'needsReview':counts.get('needs_review',0),
            'sent':counts.get('accepted',0),'lastSent':last or ''}

def pickup_notification_message(case):
    data=case['data']; data=json.loads(data) if isinstance(data,str) else data
    def one_line(value):
        return ' '.join(re.sub(r'[\x00-\x1f\x7f-\x9f\u2028\u2029]',' ',str(value or '')).split())
    values=[('送修編號',case['id']),('姓名',data.get('name','')),('電話',format_sheet_phone(data.get('phone',''))),
            ('回收地址',data.get('pickupAddress','')),('機型',data.get('model',''))]
    message='【派車安排通知】\n有一件派車回收案件需要安排。\n\n'+'\n'.join(key+'：'+one_line(value) for key,value in values)
    if dispatch_test_case(case):
        message=DISPATCH_TEST_WARNING+'\n此為付款流程測試，請勿聯絡客戶或安排物流。\n\n'+message
    return message

def enroll_new_pickup_notification(c,case_id):
    """Only called in the new case INSERT transaction; snapshots never change."""
    if not pickup_notification_available(): return False
    group=selected_pickup_group(c)
    case=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    if not active_pickup_group(group) or not case or not pickup_eligible(dict(case)): return False
    if not c.execute('SELECT 1 FROM pickup_outbox WHERE case_id=?',(case_id,)).fetchone(): return False
    return bool(c.execute('''INSERT OR IGNORE INTO pickup_notification_outbox(case_id,group_id,retry_key,message,created)
        VALUES(?,?,?,?,?)''',(case_id,group['group_id'],str(uuid.uuid4()),pickup_notification_message(dict(case)),time.time())).rowcount)

def promote_pickup_notification(c,case_id):
    group=selected_pickup_group(c)
    row=c.execute("SELECT group_id FROM pickup_notification_outbox WHERE case_id=? AND state='waiting_sheet'",(case_id,)).fetchone()
    if not row: return
    case=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    if not case or not pickup_eligible(dict(case)):
        c.execute("UPDATE pickup_notification_outbox SET state='cancelled',last_error='case_ineligible' WHERE case_id=? AND state='waiting_sheet'",(case_id,))
        return
    if not group or not group['active'] or row['group_id']!=group['group_id']:
        c.execute("UPDATE pickup_notification_outbox SET state='cancelled',last_error='group_changed' WHERE case_id=? AND state='waiting_sheet'",(case_id,))
        return
    c.execute("UPDATE pickup_notification_outbox SET state='pending',next_attempt=0 WHERE case_id=? AND state='waiting_sheet'",(case_id,))

def pickup_notification_process_once():
    """Immutable request retry, never a new UUID/text/recipient after uncertainty."""
    if not pickup_notification_available(): return {'processed':False,'state':'not_available'}
    with PICKUP_NOTIFICATION_LOCK:
        stamp=time.time()
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT * FROM pickup_notification_outbox WHERE state IN ('pending','failed','working') AND next_attempt<=? ORDER BY next_attempt,case_id LIMIT 1",(stamp,)).fetchone()
            if not row: return {'processed':False,'state':'idle'}
            case=c.execute('SELECT * FROM cases WHERE id=?',(row['case_id'],)).fetchone()
            if not case or not pickup_eligible(dict(case)):
                c.execute("UPDATE pickup_notification_outbox SET state='cancelled',last_error='case_ineligible' WHERE case_id=?",(row['case_id'],))
                return {'processed':True,'state':'cancelled'}
            group=selected_pickup_group(c)
            if not group or not group['active'] or row['group_id']!=group['group_id']:
                c.execute("UPDATE pickup_notification_outbox SET state='cancelled',last_error='group_inactive' WHERE case_id=?",(row['case_id'],))
                return {'processed':True,'state':'cancelled'}
            if row['first_attempt'] and stamp-row['first_attempt']>=PICKUP_NOTIFICATION_RETRY_SECONDS:
                c.execute("UPDATE pickup_notification_outbox SET state='needs_review',last_error='retry_window_expired' WHERE case_id=?",(row['case_id'],))
                return {'processed':True,'state':'needs_review'}
            if not active_pickup_group(group): return {'processed':False,'state':'group_verification_pending'}
            job=dict(row); first=job['first_attempt'] or stamp; attempts=job['attempts']+1
            c.execute("UPDATE pickup_notification_outbox SET state='working',first_attempt=?,attempts=?,next_attempt=? WHERE case_id=?",(first,attempts,stamp+90,job['case_id']))
        # A payment/refund change can occur between selection and delivery.
        # Never use an immutable message snapshot as payment authority.
        if not pickup_cases_allowed([job['case_id']]):
            with connect() as c:
                c.execute("UPDATE pickup_notification_outbox SET state='cancelled',last_error='case_ineligible' WHERE case_id=? AND state='working'",(job['case_id'],))
            return {'processed':True,'state':'cancelled'}
        try: result=send_group_text(TOKEN,job['group_id'],job['message'],job['retry_key'])
        except Exception: result={'state':'failed','retryable':True,'ambiguous':True}
        accepted=(isinstance(result,dict) and result.get('state')=='accepted'
                  and type(result.get('httpStatus')) is int and result.get('httpStatus') in (200,409)
                  and result.get('retryKey')==job['retry_key'])
        retryable=bool(isinstance(result,dict) and result.get('retryable') is True)
        bad_acceptance=bool(isinstance(result,dict) and result.get('state')=='accepted' and not accepted)
        if bad_acceptance: retryable=False
        ambiguous=bool(not accepted and (not isinstance(result,dict) or result.get('ambiguous') is True or bad_acceptance))
        finished=time.time()
        safe={'state':'accepted' if accepted else 'failed','retryable':retryable,'ambiguous':ambiguous}
        if accepted:
            state='accepted'; next_attempt=0; error=''; accepted_at=cloud_timestamp(finished)
        elif finished-first>=PICKUP_NOTIFICATION_RETRY_SECONDS or (ambiguous and not retryable):
            state='needs_review'; next_attempt=0; error='retry_window_expired' if finished-first>=PICKUP_NOTIFICATION_RETRY_SECONDS else 'acceptance_unconfirmed'; accepted_at=''
        else:
            state='failed'; error='line_group_delivery_failed'; accepted_at=''
            next_attempt=finished+min(3600,30*2**min(attempts-1,7)) if retryable else first+PICKUP_NOTIFICATION_RETRY_SECONDS
        with connect() as c:
            c.execute('''UPDATE pickup_notification_outbox SET state=?,next_attempt=?,last_error=?,result=?,accepted_at=?
                WHERE case_id=? AND state='working' ''',(state,next_attempt,error,json.dumps(safe),accepted_at,job['case_id']))
        return {'processed':True,'state':state}

def retry_pickup_notifications():
    """Explicit retry of failed existing jobs within their original LINE window."""
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE'); now=time.time(); group=selected_pickup_group(c)
            c.execute("UPDATE pickup_notification_outbox SET state='needs_review',last_error='retry_window_expired' WHERE state='failed' AND first_attempt>0 AND first_attempt<=?",(now-PICKUP_NOTIFICATION_RETRY_SECONDS,))
            if not active_pickup_group(group): return 0
            count=c.execute("UPDATE pickup_notification_outbox SET state='pending',next_attempt=0,last_error='' WHERE state='failed' AND group_id=?",(group['group_id'],)).rowcount
    if count: CLOUD_WAKE.set()
    return count

def pickup_dispatch_available():
    return bool(pickup_notification_available() and pickup_configured())


def pickup_dispatch_status():
    """Admin metadata only; reading never enqueues or contacts any provider."""
    with connect() as c:
        group=selected_pickup_group(c)
        counts={row['state']:row['n'] for row in c.execute('SELECT state,COUNT(*) AS n FROM pickup_dispatch_outbox GROUP BY state')}
        last=c.execute("SELECT MAX(synced_at) FROM pickup_dispatch_outbox WHERE state='completed'").fetchone()[0]
    available=pickup_dispatch_available()
    return {'available':available,'enabled':bool(available and active_pickup_group(group)),
            'pending':counts.get('pending',0)+counts.get('working',0),'failed':counts.get('failed',0),
            'completed':counts.get('completed',0),'lastSynced':last or ''}


def enqueue_pickup_dispatch(event):
    """Accept only a signed group command after webhook destination verification."""
    if not pickup_dispatch_available() or event.get('type')!='message': return False
    source=event.get('source',{}); message=event.get('message',{})
    if not isinstance(source,dict) or source.get('type')!='group' or not isinstance(message,dict) or message.get('type')!='text': return False
    text=message.get('text'); command_id=event.get('webhookEventId'); stamp=event.get('timestamp')
    if (not isinstance(text,str) or not isinstance(command_id,str) or not re.fullmatch(r'[!-~]{1,128}',command_id)
            or type(stamp) is not int or stamp<=0 or stamp>int(time.time()*1000)+300000): return False
    match=PICKUP_DISPATCH_PATTERN.fullmatch(text.strip())
    if not match or len(match[1])>80: return False
    case_id=match[1]
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            group=selected_pickup_group(c)
            if not active_pickup_group(group) or source.get('groupId')!=group['group_id'] or stamp<group['event_stamp']: return False
            case=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if not case or not pickup_eligible(dict(case)): return False
            latest=c.execute('SELECT MAX(event_stamp) FROM pickup_dispatch_events WHERE case_id=?',(case_id,)).fetchone()[0]
            # Record every valid event once, including repetitions received
            # while another command is in flight. Such events are never replayed.
            if not c.execute('INSERT OR IGNORE INTO pickup_dispatch_events(event_id,case_id,event_stamp) VALUES(?,?,?)',
                             (command_id,case_id,stamp)).rowcount: return False
            if latest is not None and stamp<=latest: return False
            prior=c.execute('SELECT state FROM pickup_dispatch_outbox WHERE case_id=?',(case_id,)).fetchone()
            if prior and prior['state'] not in ('completed','cancelled'): return False
            inserted=c.execute('''INSERT INTO pickup_dispatch_outbox(case_id,group_id,command_id,created,event_stamp)
                VALUES(?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET group_id=excluded.group_id,
                command_id=excluded.command_id,created=excluded.created,event_stamp=excluded.event_stamp,
                state='pending',attempts=0,next_attempt=0,last_error='',synced_at='',result_action='' ''',
                (case_id,group['group_id'],command_id,time.time(),stamp)).rowcount
    if inserted: CLOUD_WAKE.set()
    return bool(inserted)


def pickup_dispatch_ping(endpoint,secret,sheet_id):
    from cloud_support import pickup_dispatch_ping as send_ping
    return send_ping(endpoint,secret,sheet_id)


def pickup_dispatch_update(endpoint,secret,sheet_id,dispatch):
    from cloud_support import update_pickup_dispatch
    return update_pickup_dispatch(endpoint,secret,sheet_id,dispatch)


def pickup_dispatch_process_once(case_id=None):
    """Durable, idempotent existing-row update; never send LINE or change cases."""
    global PICKUP_DISPATCH_VERIFIED_FINGERPRINT,PICKUP_DISPATCH_VERIFY_NEXT
    if not pickup_dispatch_available(): return {'processed':False,'state':'not_available'}
    case_filter=' AND case_id=?' if case_id else ''
    query_args=(time.time(),case_id) if case_id else (time.time(),)
    # Binding and membership cannot change while this immutable command is sent.
    with PICKUP_NOTIFICATION_LOCK:
        with PICKUP_DISPATCH_LOCK:
            stamp=time.time(); values=cloud_settings()
            query_args=(stamp,case_id) if case_id else (stamp,)
            with connect() as c:
                row=c.execute("SELECT * FROM pickup_dispatch_outbox WHERE state IN ('pending','failed','working') AND next_attempt<=?"+case_filter+" ORDER BY next_attempt,case_id LIMIT 1",query_args).fetchone()
                if not row: return {'processed':False,'state':'idle'}
                group=selected_pickup_group(c)
                if not group or not group['active'] or row['group_id']!=group['group_id']:
                    c.execute("UPDATE pickup_dispatch_outbox SET state='cancelled',last_error='group_inactive' WHERE case_id=?",(row['case_id'],))
                    return {'processed':True,'state':'cancelled'}
                if not active_pickup_group(group): return {'processed':False,'state':'group_verification_pending'}
                case=c.execute('SELECT * FROM cases WHERE id=?',(row['case_id'],)).fetchone()
                if not case or not pickup_eligible(dict(case)):
                    c.execute("UPDATE pickup_dispatch_outbox SET state='cancelled',last_error='case_ineligible' WHERE case_id=?",(row['case_id'],))
                    return {'processed':True,'state':'cancelled'}
            fingerprint=cloud_fingerprint(values)
            if PICKUP_DISPATCH_VERIFIED_FINGERPRINT!=fingerprint:
                if stamp<PICKUP_DISPATCH_VERIFY_NEXT: return {'processed':False,'state':'verification_pending'}
                try: verified=pickup_dispatch_ping(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'])
                except Exception: verified=None
                if not isinstance(verified,dict) or verified.get('state')!='synced':
                    PICKUP_DISPATCH_VERIFY_NEXT=stamp+60
                    return {'processed':False,'state':'verification_failed'}
                PICKUP_DISPATCH_VERIFIED_FINGERPRINT=fingerprint; PICKUP_DISPATCH_VERIFY_NEXT=0
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute("SELECT * FROM pickup_dispatch_outbox WHERE state IN ('pending','failed','working') AND next_attempt<=?"+case_filter+" ORDER BY next_attempt,case_id LIMIT 1",query_args).fetchone()
                if not row: return {'processed':False,'state':'idle'}
                # A provider check happens outside a DB transaction; re-read the
                # saved case before claiming, without rewriting any case fields.
                case=c.execute('SELECT * FROM cases WHERE id=?',(row['case_id'],)).fetchone()
                if not case or not pickup_eligible(dict(case)):
                    c.execute("UPDATE pickup_dispatch_outbox SET state='cancelled',last_error='case_ineligible' WHERE case_id=?",(row['case_id'],))
                    return {'processed':True,'state':'cancelled'}
                job=dict(row); attempts=job['attempts']+1
                c.execute("UPDATE pickup_dispatch_outbox SET state='working',attempts=?,next_attempt=? WHERE case_id=?",(attempts,stamp+90,job['case_id']))
            dispatch={'caseId':job['case_id'],'commandId':job['command_id']}
            if not pickup_cases_allowed([job['case_id']]):
                with connect() as c:
                    c.execute("UPDATE pickup_dispatch_outbox SET state='cancelled',last_error='case_ineligible' WHERE case_id=? AND command_id=? AND state='working'",(job['case_id'],job['command_id']))
                return {'processed':True,'state':'cancelled'}
            try:
                result=pickup_dispatch_update(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'],dispatch)
                synced=isinstance(result,dict) and result.get('state')=='synced'
            except Exception: synced=False
            finished=time.time(); state='completed' if synced else 'failed'
            with connect() as c:
                c.execute('''UPDATE pickup_dispatch_outbox SET state=?,next_attempt=?,last_error=?,synced_at=?,result_action=?
                    WHERE case_id=? AND command_id=? AND state='working' ''',
                    (state,0 if synced else finished+min(3600,30*2**min(attempts-1,7)),
                     '' if synced else 'pickup_dispatch_failed',cloud_timestamp(finished) if synced else '',
                     result.get('action','') if synced and result.get('action') in ('updated','unchanged') else '',job['case_id'],job['command_id']))
            return {'processed':True,'state':state}


def retry_pickup_dispatches():
    """Retry only existing failed commands with the original case/event/group."""
    global PICKUP_DISPATCH_VERIFY_NEXT
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE'); group=selected_pickup_group(c)
            if not active_pickup_group(group): return 0
            count=c.execute("UPDATE pickup_dispatch_outbox SET state='pending',next_attempt=0,last_error='' WHERE state='failed' AND group_id=?",(group['group_id'],)).rowcount
    if count:
        PICKUP_DISPATCH_VERIFY_NEXT=0; CLOUD_WAKE.set()
    return count


def validated_entry_claim(session):
    """Revalidate only the ticket already proved by this verified session."""
    if not session or DEMO or session.get('admin') or not session.get('lineVerified') or not session.get('officialEntry'):
        return {}
    uid=session.get('id'); ticket_hash=session.get('officialEntryTicketHash'); expiry=session.get('officialEntryExpiresAt',0)
    if (not isinstance(uid,str) or not re.fullmatch(r'U[0-9a-f]{32}',uid)
            or not isinstance(ticket_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',ticket_hash)
            or session.get('officialEntryBotUserId')!=BOT_UID
            or not isinstance(expiry,(int,float)) or expiry<=time.time()):
        return {}
    with connect() as c:
        row=c.execute('SELECT expires FROM line_entry_tickets WHERE ticket_hash=? AND user_id=? AND bot_user_id=?',(ticket_hash,uid,BOT_UID)).fetchone()
    if not row or row['expires']!=expiry or row['expires']<=time.time(): return {}
    return {key:session[key] for key in ENTRY_SESSION_FIELDS}

def write_private_config(values):
    """Atomically preserve both LINE and cloud configuration with private ACLs."""
    temp=DATA_DIR/('private-config-'+secrets.token_hex(8)+'.tmp')
    target=DATA_DIR/'line-config.json'
    try:
        with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='utf-8') as f:
            json.dump(values,f,ensure_ascii=False)
        if os.name=='nt':
            account=os.environ.get('USERDOMAIN','')+'\\'+os.environ.get('USERNAME','')
            subprocess.run(['icacls',str(temp),'/inheritance:r','/grant:r',account+':(F)'],capture_output=True,check=True)
        os.replace(temp,target)
    except Exception:
        try:
            if temp.exists(): temp.unlink()
        except OSError: pass
        raise ValueError('無法安全儲存本機設定，請檢查資料夾權限') from None

def cloud_settings():
    values={key:PRIVATE.get(key,'') for key in ('googleSheetEndpoint','googleSheetSecret','googleSheetId')}
    values['googleSheetId']=values['googleSheetId'] or PUBLIC_SETTINGS.get('googleSheetId','')
    for key,env_key in [('googleSheetEndpoint','GOOGLE_SHEET_ENDPOINT'),('googleSheetSecret','GOOGLE_SHEET_SECRET'),('googleSheetId','GOOGLE_SHEET_ID')]:
        if env_key in os.environ: values[key]=os.environ[env_key]
    return values

def cloud_configured(values=None):
    values=values or cloud_settings()
    try:
        validate_endpoint(values.get('googleSheetEndpoint',''))
        validate_secret(values.get('googleSheetSecret',''))
        return bool(re.fullmatch(r'[A-Za-z0-9_-]{20,200}',values.get('googleSheetId','')))
    except (ValueError,TypeError): return False

def cloud_ping(endpoint,secret,sheet_id):
    from cloud_support import ping
    return ping(endpoint,secret,sheet_id)

def cloud_upsert(endpoint,secret,sheet_id,record):
    from cloud_support import upsert
    return upsert(endpoint,secret,sheet_id,record)

def pickup_configured(values=None):
    values=values or cloud_settings()
    return not DEMO and cloud_configured(values) and values['googleSheetId']==PRIMARY_SHEET_ID

def pickup_ping(endpoint,secret,sheet_id):
    from cloud_support import pickup_ping as send_ping
    return send_ping(endpoint,secret,sheet_id)

def pickup_upsert(endpoint,secret,sheet_id,record):
    from cloud_support import upsert_pickup
    return upsert_pickup(endpoint,secret,sheet_id,record)

def pickup_health():
    """Verify only fixed receiver metadata; never enroll, write cases or notify LINE."""
    global PICKUP_VERIFIED_FINGERPRINT,PICKUP_VERIFY_NEXT
    with CLOUD_LOCK:
        values=cloud_settings()
        if not pickup_configured(values): return None
        fingerprint=cloud_fingerprint(values)
        try: result=pickup_ping(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'])
        except Exception: result=None
        if not isinstance(result,dict) or result.get('state')!='synced':
            PICKUP_VERIFIED_FINGERPRINT=''; PICKUP_VERIFY_NEXT=time.time()+60
            return False
        PICKUP_VERIFIED_FINGERPRINT=fingerprint; PICKUP_VERIFY_NEXT=0
        return {'ok':True,'enabled':True,'verified':True,'scope':'new_cases_only',
                'sheetUrl':'https://docs.google.com/spreadsheets/d/'+PICKUP_SHEET_ID+'/edit#gid='+str(PICKUP_SHEET_GID)}

def payment_case_data(case):
    """Read only server-owned case rows; malformed data cannot bypass a gate."""
    try:
        data=case.get('data',{})
        if isinstance(data,str): data=json.loads(data)
        return data if isinstance(data,dict) else None
    except (ValueError,TypeError,AttributeError): return None

def payment_json_object(pairs):
    value={}
    for key,item in pairs:
        if key in value: raise ValueError('duplicate_payment_field')
        value[key]=item
    return value

def payment_json_constant(value):
    raise ValueError('non_finite_payment_field')

def payment_case_allowed(case):
    data=payment_case_data(case)
    if data is None: return False
    # Absence alone denotes a legacy case. Unknown/empty markers fail closed.
    if 'paymentWorkflow' not in data: return True
    if data.get('paymentWorkflow')!=PAYMENT_WORKFLOW or PAYMENTS is None: return False
    try: return PAYMENTS.is_allowed(case) is True
    except Exception: return False

def dispatch_test_case(case):
    """A display label only; never grants payment or dispatch eligibility."""
    data=payment_case_data(case)
    if not data or data.get('paymentWorkflow')!=PAYMENT_WORKFLOW: return False
    model=data.get('model')
    reserved=(isinstance(model,str) and (model=='TEST-PROD' or
        model.startswith('TEST-PROD-') and len(model)>len('TEST-PROD-')))
    return bool(reserved and any(isinstance(value,str) and '測試' in value
        for value in (data.get('extra'),case.get('note'))))

def dispatch_test_case_ids(case_ids):
    with connect() as c:
        result=[]
        for case_id in dict.fromkeys(case_ids):
            row=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if row and dispatch_test_case(dict(row)): result.append(case_id)
    return result

def pickup_requested(case):
    """Physical pickup selection, independent of the payment workflow."""
    uid=case.get('user_id',''); data=case.get('data',{})
    data=payment_case_data(case)
    return (not DEMO and isinstance(uid,str) and bool(re.fullmatch(r'U[0-9a-f]{32}',uid))
            and isinstance(data,dict) and data.get('shipping')=='由客服派遣物流回收')

def pickup_eligible(case):
    return pickup_requested(case) and payment_case_allowed(case)

def pickup_cases_allowed(case_ids):
    """Final read of current cases and payment authority before external I/O."""
    with connect() as c:
        for case_id in set(case_ids):
            row=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if not row or not pickup_eligible(dict(row)): return False
    return True

def promote_payment_case(case_id):
    """Enroll an explicitly managed, paid/free pickup after payment DB commit."""
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if not row or (payment_case_data(dict(row)) or {}).get('paymentWorkflow')!=PAYMENT_WORKFLOW:
                return False
            if not pickup_eligible(dict(row)): return False
            # Build a fresh server snapshot only on the initial promotion.
            # Subsequent calls preserve original delivery identities/history.
            existing=c.execute('SELECT state FROM pickup_outbox WHERE case_id=?',(case_id,)).fetchone()
            if not existing:
                enqueue_cloud_case(c,case_id,refresh_pickup=False)
                enroll_new_pickup_case(c,case_id)
            enroll_new_pickup_notification(c,case_id)
    CLOUD_WAKE.set()
    return True

def hold_payment_case(case_id):
    """Revoke unsent pickup work/cached lists, preserving completed history."""
    with PICKUP_NOTIFICATION_LOCK:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if not row or (payment_case_data(dict(row)) or {}).get('paymentWorkflow')!=PAYMENT_WORKFLOW:
                return False
            c.execute("UPDATE pickup_outbox SET state='payment_hold',next_attempt=0,last_error='payment_hold' WHERE case_id=?",(case_id,))
            c.execute("UPDATE pickup_notification_outbox SET state='cancelled',last_error='payment_hold' WHERE case_id=? AND state IN ('waiting_sheet','pending','failed','working','needs_review')",(case_id,))
            c.execute("UPDATE pickup_dispatch_outbox SET state='cancelled',last_error='payment_hold' WHERE case_id=? AND state IN ('pending','failed','working')",(case_id,))
            groups={r[0] for r in c.execute('SELECT group_id FROM pickup_notification_outbox WHERE case_id=? UNION SELECT group_id FROM pickup_dispatch_outbox WHERE case_id=?',(case_id,case_id))}
            selected=selected_pickup_group(c)
            if selected: groups.add(selected['group_id'])
            for group_id in groups:
                # Counts have no case IDs in visible text. Cancel the related
                # group batches conservatively; retain tomorrow's schedule.
                c.execute("UPDATE dispatch_query_events SET state='cancelled',reply_token='',last_error='payment_hold' WHERE group_id=? AND state IN ('pending','working','responding')",(group_id,))
                c.execute('DELETE FROM dispatch_query_snapshots WHERE group_id=?',(group_id,))
                c.execute("UPDATE dispatch_daily_jobs SET state='cancelled',last_error='payment_hold' WHERE group_id=? AND state IN ('pending','working','ready','failed')",(group_id,))
                c.execute("UPDATE dispatch_workflow_push SET state='cancelled',last_error='payment_hold' WHERE group_id=? AND state IN ('pending','working','failed','needs_review')",(group_id,))
    CLOUD_WAKE.set()
    return True

def cloud_timestamp(stamp=None):
    return time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime((time.time() if stamp is None else stamp)+8*3600))

def cloud_fingerprint(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

def enqueue_cloud_case(c,case_id,refresh_pickup=True):
    """Use the same transaction as each local case mutation; never call Google."""
    row=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    if not row: return
    case=dict(row); data=json.loads(case['data'])
    data['lineDisplayName']=case['line_display_name']
    case['data']=data
    receipt=c.execute('SELECT summary_received FROM line_receipts WHERE case_id=?',(case_id,)).fetchone()
    case['lineSummaryReceivedAt']=receipt['summary_received'] if receipt else ''
    prior=c.execute('SELECT revision FROM cloud_outbox WHERE case_id=?',(case_id,)).fetchone()
    prior_pickup=c.execute('SELECT revision FROM pickup_outbox WHERE case_id=?',(case_id,)).fetchone()
    revision=max(case['cloud_revision'],prior['revision'] if prior else 0,prior_pickup['revision'] if prior_pickup else 0)+1
    record=build_payload(case,revision,cloud_timestamp())
    c.execute('UPDATE cases SET cloud_revision=? WHERE id=?',(revision,case_id))
    c.execute('''INSERT INTO cloud_outbox(case_id,revision,payload) VALUES(?,?,?)
        ON CONFLICT(case_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,
        state='pending',attempts=0,next_attempt=0,last_error='' ''',
        (case_id,revision,json.dumps(record,ensure_ascii=False)))
    # Updating or retrying a legacy case must never enroll it in pickup sync.
    # Refresh only rows explicitly enrolled inside their new case INSERT.
    if refresh_pickup and prior_pickup:
        if pickup_eligible(case):
            c.execute('''UPDATE pickup_outbox SET revision=?,payload=?,state='pending',
                attempts=0,next_attempt=0,last_error='' WHERE case_id=?''',
                (revision,json.dumps(record,ensure_ascii=False),case_id))
        else:
            c.execute("UPDATE pickup_outbox SET state='skipped',next_attempt=0,last_error='' WHERE case_id=?",(case_id,))
    CLOUD_WAKE.set()

def enroll_new_pickup_case(c,case_id):
    """Call only inside a successful new case INSERT transaction, never backfill."""
    row=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    if not row or not pickup_eligible(dict(row)): return False
    queued=c.execute('SELECT revision,payload FROM cloud_outbox WHERE case_id=?',(case_id,)).fetchone()
    if not queued: return False
    cursor=c.execute('''INSERT OR IGNORE INTO pickup_outbox(case_id,revision,payload,enrolled_at)
        VALUES(?,?,?,?)''',(case_id,queued['revision'],queued['payload'],cloud_timestamp()))
    if cursor.rowcount: CLOUD_WAKE.set()
    return bool(cursor.rowcount)

def trusted_display_name(value):
    return value if isinstance(value,str) and value.strip() and len(value)<=300 else ''

def backfill_line_name(uid,display_name):
    """Persist trusted LINE claims/profile data for this UID's blank rows only."""
    display_name=trusted_display_name(display_name)
    if not isinstance(uid,str) or not re.fullmatch(r'U[0-9a-f]{32}',uid) or not display_name: return 0
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        ids=[row['id'] for row in c.execute('SELECT id FROM cases WHERE user_id=? AND TRIM(line_display_name)=""',(uid,))]
        for case_id in ids:
            c.execute('UPDATE cases SET line_display_name=? WHERE id=? AND TRIM(line_display_name)=""',(display_name,case_id))
            enqueue_cloud_case(c,case_id)
    return len(ids)

def backfill_cloud_cases():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        ids=[row['id'] for row in c.execute('SELECT id FROM cases')]
        for case_id in ids: enqueue_cloud_case(c,case_id,refresh_pickup=False)
    return len(ids)

def cloud_process_once():
    """One serial delivery; a newer revision is never marked by an old result."""
    global CLOUD_VERIFIED_FINGERPRINT,CLOUD_VERIFY_NEXT
    with CLOUD_LOCK:
        values=cloud_settings()
        if not cloud_configured(values): return {'processed':False,'state':'not_configured'}
        stamp=time.time()
        fingerprint=cloud_fingerprint(values)
        if CLOUD_VERIFIED_FINGERPRINT!=fingerprint:
            if stamp<CLOUD_VERIFY_NEXT: return {'processed':False,'state':'verification_pending'}
            try: verified=cloud_ping(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'])
            except Exception: verified=None
            if not isinstance(verified,dict) or verified.get('state')!='synced':
                CLOUD_VERIFY_NEXT=stamp+60
                return {'processed':False,'state':'verification_failed'}
            CLOUD_VERIFIED_FINGERPRINT=fingerprint; CLOUD_VERIFY_NEXT=0
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT * FROM cloud_outbox WHERE state IN ('pending','failed','working') AND next_attempt<=? ORDER BY next_attempt,case_id LIMIT 1",(stamp,)).fetchone()
            if not row: return {'processed':False,'state':'idle'}
            job=dict(row)
            c.execute("UPDATE cloud_outbox SET state='working',next_attempt=? WHERE case_id=? AND revision=?",(stamp+90,job['case_id'],job['revision']))
            run_id=c.execute('INSERT INTO cloud_sync_runs(case_id,revision,started,state) VALUES(?,?,?,?)',(job['case_id'],job['revision'],stamp,'working')).lastrowid
        try:
            result=cloud_upsert(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'],json.loads(job['payload']))
            synced=isinstance(result,dict) and result.get('state')=='synced'
        except Exception: synced=False
        finished=time.time(); state='synced' if synced else 'failed'; error='' if synced else 'cloud_delivery_failed'
        with connect() as c:
            c.execute('UPDATE cloud_sync_runs SET finished=?,state=?,error=? WHERE id=?',(finished,state,error,run_id))
            if synced:
                c.execute("UPDATE cloud_outbox SET state='synced',last_error='',synced_at=? WHERE case_id=? AND revision=?",(cloud_timestamp(),job['case_id'],job['revision']))
            else:
                attempts=job['attempts']+1
                delay=min(3600,30*2**min(attempts-1,7))
                c.execute("UPDATE cloud_outbox SET state='failed',attempts=?,next_attempt=?,last_error=? WHERE case_id=? AND revision=?",(attempts,finished+delay,error,job['case_id'],job['revision']))
        return {'processed':True,'state':state}

def pickup_process_once():
    """Independent delivery/retry, restricted to durably enrolled new cases."""
    global PICKUP_VERIFIED_FINGERPRINT,PICKUP_VERIFY_NEXT
    with CLOUD_LOCK:
        values=cloud_settings()
        if not pickup_configured(values): return {'processed':False,'state':'not_configured'}
        stamp=time.time()
        with connect() as c:
            row=c.execute("SELECT * FROM pickup_outbox WHERE state IN ('pending','failed','working') AND next_attempt<=? ORDER BY next_attempt,case_id LIMIT 1",(stamp,)).fetchone()
        if not row: return {'processed':False,'state':'idle'}
        fingerprint=cloud_fingerprint(values)
        if PICKUP_VERIFIED_FINGERPRINT!=fingerprint:
            if stamp<PICKUP_VERIFY_NEXT: return {'processed':False,'state':'verification_pending'}
            try: verified=pickup_ping(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'])
            except Exception: verified=None
            if not isinstance(verified,dict) or verified.get('state')!='synced':
                PICKUP_VERIFY_NEXT=stamp+60
                return {'processed':False,'state':'verification_failed'}
            PICKUP_VERIFIED_FINGERPRINT=fingerprint; PICKUP_VERIFY_NEXT=0
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT * FROM pickup_outbox WHERE state IN ('pending','failed','working') AND next_attempt<=? ORDER BY next_attempt,case_id LIMIT 1",(stamp,)).fetchone()
            if not row: return {'processed':False,'state':'idle'}
            case=c.execute('SELECT * FROM cases WHERE id=?',(row['case_id'],)).fetchone()
            if not case or not pickup_eligible(dict(case)):
                c.execute("UPDATE pickup_outbox SET state='skipped',next_attempt=0,last_error='' WHERE case_id=?",(row['case_id'],))
                return {'processed':True,'state':'skipped'}
            job=dict(row)
            c.execute("UPDATE pickup_outbox SET state='working',next_attempt=? WHERE case_id=? AND revision=?",(stamp+90,job['case_id'],job['revision']))
            run_id=c.execute('INSERT INTO pickup_sync_runs(case_id,revision,started,state) VALUES(?,?,?,?)',(job['case_id'],job['revision'],stamp,'working')).lastrowid
        # Serialize cancellation with the actual pickup write and ACK so a
        # refund hold cannot be overwritten by an older in-flight completion.
        with PICKUP_NOTIFICATION_LOCK:
            if not pickup_cases_allowed([job['case_id']]):
                with connect() as c:
                    c.execute("UPDATE pickup_outbox SET state='payment_hold',next_attempt=0,last_error='case_ineligible' WHERE case_id=? AND revision=? AND state='working'",(job['case_id'],job['revision']))
                    c.execute("UPDATE pickup_sync_runs SET finished=?,state='cancelled',error='case_ineligible' WHERE id=?",(time.time(),run_id))
                return {'processed':True,'state':'cancelled'}
            try:
                result=pickup_upsert(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'],json.loads(job['payload']))
                synced=isinstance(result,dict) and result.get('state')=='synced'
            except Exception: synced=False
            finished=time.time(); state='synced' if synced else 'failed'; error='' if synced else 'pickup_delivery_failed'
            with connect() as c:
                c.execute('UPDATE pickup_sync_runs SET finished=?,state=?,error=? WHERE id=?',(finished,state,error,run_id))
                if synced:
                    updated=c.execute("UPDATE pickup_outbox SET state='synced',last_error='',synced_at=? WHERE case_id=? AND revision=? AND state='working'",(cloud_timestamp(),job['case_id'],job['revision']))
                    if updated.rowcount: promote_pickup_notification(c,job['case_id'])
                else:
                    attempts=job['attempts']+1
                    delay=min(3600,30*2**min(attempts-1,7))
                    c.execute("UPDATE pickup_outbox SET state='failed',attempts=?,next_attempt=?,last_error=? WHERE case_id=? AND revision=? AND state='working'",(attempts,finished+delay,error,job['case_id'],job['revision']))
            return {'processed':True,'state':state}

def retry_existing_pickups():
    """Retry existing failed/pending enrollments only; never create jobs or LINE messages."""
    global PICKUP_VERIFY_NEXT
    with connect() as c:
        cursor=c.execute("UPDATE pickup_outbox SET state='pending',next_attempt=0,last_error='' WHERE state IN ('pending','failed')")
    if cursor.rowcount:
        PICKUP_VERIFY_NEXT=0
        CLOUD_WAKE.set()
    return cursor.rowcount

def start_cloud_worker():
    global CLOUD_WORKER_STARTED
    if CLOUD_WORKER_STARTED: return
    CLOUD_WORKER_STARTED=True
    with connect() as c:
        c.execute("UPDATE cloud_outbox SET state='pending',next_attempt=0 WHERE state='working'")
        c.execute("UPDATE cloud_sync_runs SET state='interrupted',finished=? WHERE state='working'",(time.time(),))
        c.execute("UPDATE pickup_outbox SET state='pending',next_attempt=0 WHERE state='working'")
        c.execute("UPDATE pickup_sync_runs SET state='interrupted',finished=? WHERE state='working'",(time.time(),))
        c.execute("UPDATE pickup_notification_outbox SET state='pending',next_attempt=0 WHERE state='working'")
        c.execute("UPDATE pickup_dispatch_outbox SET state='pending',next_attempt=0 WHERE state='working'")
    if cloud_configured():
        try: backfill_cloud_cases()
        except Exception: pass
    def worker():
        while True:
            processed=False
            for operation in (cloud_process_once,pickup_process_once,pickup_notification_process_once,pickup_dispatch_process_once):
                try: processed=operation()['processed'] or processed
                except Exception: pass
            if processed: continue
            CLOUD_WAKE.wait(5); CLOUD_WAKE.clear()
    threading.Thread(target=worker,name='repair-cloud-sync',daemon=True).start()

def public_cloud_status():
    values=cloud_settings(); sheet_id=values['googleSheetId']
    valid_id=bool(re.fullmatch(r'[A-Za-z0-9_-]{20,200}',sheet_id))
    with connect() as c:
        pending=c.execute("SELECT COUNT(*) FROM cloud_outbox WHERE state IN ('pending','working')").fetchone()[0]
        failed=c.execute("SELECT COUNT(*) FROM cloud_outbox WHERE state='failed'").fetchone()[0]
        last=c.execute("SELECT MAX(finished) FROM cloud_sync_runs WHERE state='synced'").fetchone()[0]
        pickup_pending=c.execute("SELECT COUNT(*) FROM pickup_outbox WHERE state IN ('pending','working')").fetchone()[0]
        pickup_failed=c.execute("SELECT COUNT(*) FROM pickup_outbox WHERE state='failed'").fetchone()[0]
        pickup_last=c.execute("SELECT MAX(finished) FROM pickup_sync_runs WHERE state='synced'").fetchone()[0]
    return {'configured':cloud_configured(values),'sheetUrl':'https://docs.google.com/spreadsheets/d/'+sheet_id+'/edit' if valid_id else '',
            'pending':pending,'failed':failed,'lastSynced':cloud_timestamp(last) if last else '',
            'pickupEnabled':not DEMO,'pickup':{'configured':pickup_configured(values),
                'verified':bool(PICKUP_VERIFIED_FINGERPRINT and PICKUP_VERIFIED_FINGERPRINT==cloud_fingerprint(values)),
                'pending':pickup_pending,'failed':pickup_failed,'lastSynced':cloud_timestamp(pickup_last) if pickup_last else '',
                'sheetUrl':'https://docs.google.com/spreadsheets/d/'+PICKUP_SHEET_ID+'/edit#gid='+str(PICKUP_SHEET_GID)},
            'pickupNotificationAvailable':pickup_notification_available(),'pickupDispatchAvailable':pickup_dispatch_available(),
            'dispatchWorkflowAvailable':pickup_dispatch_available()}

def admin_connection_status():
    """Return an explicit metadata allowlist, never configuration secrets."""
    messaging_id=PRIVATE.get('messagingChannelId') or PUBLIC_SETTINGS.get('lineMessagingChannelId','')
    def console_url(channel_id, section):
        ident=str(channel_id or '')
        return 'https://developers.line.biz/console/channel/'+ident+'/'+section if re.fullmatch(r'[0-9]{5,20}',ident) else 'https://developers.line.biz/console/'
    service_id=os.environ.get('RENDER_SERVICE_ID','')
    render_url='https://dashboard.render.com/web/'+service_id+'/env' if re.fullmatch(r'srv-[a-z0-9]{10,40}',service_id) else 'https://dashboard.render.com/'
    values=cloud_settings()
    return {
        'cloudDeployment':CLOUD_DEPLOYMENT,
        'localSetupEnabled':LOCAL_SETUP_ENABLED,
        'renderSettingsUrl':render_url,
        'line':{'oa':OA,'loginChannelId':str(CID or ''),'messagingChannelId':str(messaging_id or ''),'liffId':LIFF_ID,
                'loginConfigured':bool(CID and SECRET),'messagingConfigured':bool(TOKEN and MESSAGE_SECRET and BOT_UID),
                'callbackUrl':BASE+'/auth/callback','webhookUrl':BASE+'/api/line-webhook',
                'loginConsoleUrl':console_url(CID,'line-login'),'messagingConsoleUrl':console_url(messaging_id,'messaging-api'),
                'liffConsoleUrl':console_url(CID,'liff')},
        'cloud':{**public_cloud_status(),'endpointConfigured':bool(values['googleSheetEndpoint']),'secretConfigured':bool(values['googleSheetSecret'])}
    }

def probe_text(case_id,nonce):
    return PROBE_HEADING+'\n案件編號：'+case_id+'\n服務代碼：'+nonce

def webhook_public_info(info):
    """Show our known URL or only the origin of a different existing service."""
    expected=BASE+'/api/line-webhook'; endpoint=info['endpoint']; matches=endpoint==expected
    visible=expected if matches else ''
    if endpoint and not matches:
        parsed=urllib.parse.urlparse(endpoint)
        if parsed.scheme in ('http','https') and parsed.hostname:
            visible=parsed.scheme+'://'+parsed.hostname+'/(既有路徑已隱藏)'
    return {'endpoint':visible,'hasEndpoint':bool(endpoint),'active':info['active'],'matchesExpected':matches,'endpointRedacted':bool(endpoint and not matches)}
def remote(url, data, bearer=None, form=False):
    raw = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
    if bearer: headers['Authorization'] = 'Bearer '+bearer
    with urllib.request.urlopen(urllib.request.Request(url, data=raw, headers=headers), timeout=15) as r:
        return json.load(r)
def notify(case):
    if DEMO: return '測試模式：未傳送 LINE'
    if not TOKEN: return '待設定 Messaging API'
    if case.get('status') in PAYMENT_REQUIRED_STATUSES:
        with connect() as c: current=c.execute('SELECT * FROM cases WHERE id=?',(case['id'],)).fetchone()
        if not current or not payment_case_allowed(dict(current)):
            return '付款狀態暫停：未重新傳送送修進度通知'
    history=case.get('history',[])
    if isinstance(history,str): history=json.loads(history)
    message_key=hashlib.sha256(json.dumps([case['id'],case['status'],len(history) or 1]).encode()).hexdigest()
    with connect() as c:
        c.execute('INSERT OR IGNORE INTO line_outbox(message_key,retry_key,created) VALUES(?,?,?)',(message_key,str(uuid.uuid4()),time.time()))
        prior=c.execute('SELECT retry_key,result,created FROM line_outbox WHERE message_key=?',(message_key,)).fetchone()
        retry_key=prior['retry_key']
        if prior['result'] and json.loads(prior['result']).get('state')=='accepted':
            return 'LINE API 已接受通知（未確認送達）'
        if not prior['created'] or time.time()-prior['created']>=86400:
            return '通知重試期限已過，請由客服另行聯繫'
    case_data=case.get('data')
    if isinstance(case_data,str): case_data=json.loads(case_data)
    confirmation_data=case_data if case['status']=='已申請' and len(history)<=1 and isinstance(case_data,dict) else None
    result=send_push(TOKEN,case['user_id'],case['id'],case['status'],retry_key,confirmation_data=confirmation_data)
    with connect() as c: c.execute('UPDATE line_outbox SET result=? WHERE message_key=?',(json.dumps(result),message_key))
    if result['state']=='accepted': return 'LINE API 已接受通知（未確認送達）'
    return '通知失敗：'+str(result.get('error') or '無法傳送')+'；可由後台重送'

class Handler(BaseHTTPRequestHandler):
    def send(self, code, data, headers=None):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Referrer-Policy','no-referrer')
        pairs=headers.items() if isinstance(headers,dict) else headers or ()
        for k,v in pairs: self.send_header(k,v)
        self.end_headers(); self.wfile.write(raw)
    def user(self):
        cookie = SimpleCookie(self.headers.get('Cookie',''))
        key = cookie.get('repair_session')
        s = sessions.get(key.value) if key else None
        if not s or s['expires'] <= time.time(): return None
        if not validated_entry_claim(s):
            for field in ENTRY_SESSION_FIELDS: s.pop(field,None)
        return s
    def auto_login_paused(self):
        cookie=SimpleCookie(self.headers.get('Cookie',''))
        pause=cookie.get('repair_login_paused')
        return bool(pause and pause.value=='1')
    def cookie_options(self):
        local_request=self.client_address[0]=='127.0.0.1' and self.headers.get('Host','').split(':')[0] in ('127.0.0.1','localhost') and not self.headers.get('Cf-Connecting-IP') and not self.headers.get('X-Forwarded-For')
        return '; HttpOnly; SameSite=Lax; Path=/'+('; Secure' if CLOUD_DEPLOYMENT or BASE.startswith('https:') and not local_request else '')
    def login(self, uid, name, admin=False, display_name='', line_verified=False):
        # A renewed verified identity may retain its existing source proof, but
        # only from the same cookie session, UID, bot and original ticket expiry.
        previous=self.user()
        entry=validated_entry_claim(previous) if line_verified and not admin and previous and previous.get('id')==uid else {}
        verified_name=trusted_display_name(display_name)
        if verified_name: backfill_line_name(uid,verified_name)
        key=secrets.token_urlsafe(32)
        sessions[key]={'id':uid,'name':name,'displayName':verified_name,'admin':admin,'lineVerified':bool(line_verified),'expires':time.time()+86400}
        sessions[key].update(entry)
        options=self.cookie_options()
        return [('Set-Cookie','repair_session='+key+options),('Set-Cookie','repair_login_paused=; Max-Age=0'+options)]
    def allowed_origin(self):
        origin=self.headers.get('Origin')
        return not origin or origin==BASE or not CLOUD_DEPLOYMENT and origin=='http://127.0.0.1:8787'
    def local_setup(self):
        return LOCAL_SETUP_ENABLED and self.client_address[0]=='127.0.0.1' and self.headers.get('Host')=='127.0.0.1:8787' and not self.headers.get('Cf-Connecting-IP') and not self.headers.get('X-Forwarded-For')
    def case_dict(self, row, admin=False):
        d=dict(row); d['data']=json.loads(d['data']); d['history']=json.loads(d['history'])
        with connect() as c: receipt=c.execute('SELECT received,summary_received FROM line_receipts WHERE case_id=?',(d['id'],)).fetchone()
        d['lineReceivedAt']=receipt['received'] if receipt else ''
        d['lineSummaryReceivedAt']=receipt['summary_received'] if receipt else ''
        if not admin: d.pop('note',None); d.pop('user_id',None); d.pop('request_id',None)
        if not admin: d.pop('cloud_revision',None)
        return d
    def do_GET(self):
        url=urllib.parse.urlparse(self.path); path=url.path
        if PAYMENTS and PAYMENTS.handle_get(self,path,url.query): return
        if path=='/healthz':
            try:
                with closing(sqlite3.connect(DB.as_uri()+'?mode=rw',uri=True,timeout=2)) as c: c.execute('SELECT 1').fetchone()
            except sqlite3.Error: return self.send(503,{'ok':False})
            return self.send(200,{'ok':True})
        if DEMO and self.headers.get('Cf-Connecting-IP'):
            return self.send(503,{'error':'LINE 測試服務設定中，尚未開放申請'})
        if path=='/api/config': return self.send(200,{'demo':DEMO,'oa':OA,'loginReady':bool(CID and (SECRET or LIFF_ID)),'loginUrl':BASE+'/auth/line','liffId':LIFF_ID,'webhookReady':bool(MESSAGE_SECRET and BOT_UID),'officialEntryRequired':True,'autoLoginPaused':self.auto_login_paused(),'statuses':STATUS})
        if path=='/api/me':
            u=self.user()
            public_keys=('id','name','displayName','admin','lineVerified','expires','officialEntry','officialEntryExpiresAt')
            return self.send(200,{'user':{key:u[key] for key in public_keys if key in u} if u else None})
        if path=='/api/line-entry':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            verified=bool(u.get('lineVerified') and u.get('officialEntry'))
            return self.send(200,{'officialEntry':verified,'expiresAt':int(u.get('officialEntryExpiresAt',0)) if verified else 0})
        if path=='/api/cloud-status':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            return self.send(200,public_cloud_status())
        if path=='/api/pickup-health':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            result=pickup_health()
            if result is None: return self.send(503,{'error':'派車回收名單同步尚未設定'})
            if result is False: return self.send(502,{'error':'無法驗證派車回收名單同步連線'})
            return self.send(200,result)
        if path=='/api/pickup-notification-status':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            return self.send(200,pickup_notification_status())
        if path=='/api/pickup-dispatch-status':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            return self.send(200,pickup_dispatch_status())
        if path=='/api/dispatch-workflow-status':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            return self.send(200,WORKFLOW.status())
        if path=='/api/admin-connection-status':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            return self.send(200,admin_connection_status())
        if path in ('/setup-cloud','/api/local-cloud-config','/api/cloud-script'):
            if not self.local_setup(): return self.send(403,{'error':'設定頁只限本機使用'})
            if path=='/api/local-cloud-config':
                values=cloud_settings(); endpoint=values['googleSheetEndpoint']
                try: validate_endpoint(endpoint)
                except ValueError: endpoint=''
                return self.send(200,{**public_cloud_status(),'googleSheetId':values['googleSheetId'],'sheetId':values['googleSheetId'],
                                     'googleSheetEndpoint':endpoint,'endpoint':endpoint,'endpointConfigured':bool(endpoint),'secretConfigured':bool(values['googleSheetSecret'])})
            source='cloud-setup.html' if path=='/setup-cloud' else 'google-sheet-sync.gs'
            if not (ROOT/source).is_file(): return self.send(503,{'error':'雲端設定檔準備中'})
            raw=(ROOT/source).read_text(encoding='utf-8')
            if path=='/setup-cloud': raw=raw.replace('__SETUP_TOKEN__',SETUP_TOKEN)
            content_type='text/html' if path=='/setup-cloud' else 'text/plain'
            self.send_response(200); self.send_header('Content-Type',content_type+'; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('X-Frame-Options','DENY'); self.send_header('Referrer-Policy','no-referrer'); self.end_headers(); self.wfile.write(raw.encode()); return
        if path=='/api/line-health':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if DEMO or not TOKEN: return self.send(503,{'error':'正式 LINE 尚未設定'})
            try:
                bot=inspect_bot(TOKEN,OA); info=get_webhook_endpoint(TOKEN)
            except ValueError: return self.send(502,{'error':'無法確認 LINE 帳號或 Webhook 狀態'})
            return self.send(200,{'bot':bot,'webhook':webhook_public_info(info),'expectedWebhookUrl':BASE+'/api/line-webhook','liffUrl':'https://liff.line.me/'+LIFF_ID})
        if path=='/api/line-handshake':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            nonce=urllib.parse.parse_qs(url.query).get('nonce',[''])[0]
            if not NONCE_PATTERN.fullmatch(nonce): return self.send(400,{'error':'服務代碼格式錯誤'})
            with connect() as c:
                row=c.execute('SELECT confirmed,expires FROM line_handshakes WHERE nonce=? AND user_id=?',(nonce,u['id'])).fetchone()
            if not row: return self.send(404,{'error':'找不到連線確認'})
            expired=row['expires']<=time.time()
            return self.send(200,{'confirmed':bool(row['confirmed']) and not expired,'expired':expired})
        if path=='/api/line-receipt':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            ident=urllib.parse.parse_qs(url.query).get('id',[''])[0]
            with connect() as c:
                row=c.execute('SELECT id FROM cases WHERE id=? AND user_id=?',(ident,u['id'])).fetchone()
                if not row: return self.send(404,{'error':'找不到案件'})
                receipt=c.execute('SELECT received,summary_received FROM line_receipts WHERE case_id=?',(ident,)).fetchone()
            return self.send(200,{'receivedAt':receipt['received'] if receipt else '','summaryReceivedAt':receipt['summary_received'] if receipt else ''})
        if path in ('/setup-line','/api/line-setup-status'):
            if not self.local_setup(): return self.send(403,{'error':'設定頁只限本機使用'})
            if path=='/api/line-setup-status':
                return self.send(200,{'oa':OA,'loginChannelId':CID,'liffId':LIFF_ID,'messagingChannelId':PRIVATE.get('messagingChannelId') or PUBLIC_SETTINGS.get('lineMessagingChannelId',''),'publicUrl':BASE,'loginChannelSecretConfigured':bool(SECRET),'messagingChannelSecretConfigured':bool(MESSAGE_SECRET),'messagingAccessTokenConfigured':bool(TOKEN),'adminPasswordConfigured':bool(ADMIN)})
            raw=(ROOT/'line-setup.html').read_text(encoding='utf-8').replace('__SETUP_TOKEN__',SETUP_TOKEN).encode()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('X-Frame-Options','DENY'); self.send_header('Referrer-Policy','no-referrer'); self.end_headers(); self.wfile.write(raw); return
        if path=='/auth/line':
            if not CID or not SECRET: return self.send(503,{'error':'尚未設定 LINE 登入，請先使用測試模式。'})
            state=secrets.token_urlsafe(32); nonce=secrets.token_urlsafe(32); verifier=secrets.token_urlsafe(64)
            states[state]={'expires':time.time()+600,'nonce':nonce,'verifier':verifier}
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            query=urllib.parse.urlencode({'response_type':'code','client_id':CID,'redirect_uri':BASE+'/auth/callback','state':state,'nonce':nonce,'scope':'profile openid','bot_prompt':'normal','code_challenge':challenge,'code_challenge_method':'S256'})
            self.send_response(302); self.send_header('Location','https://access.line.me/oauth2/v2.1/authorize?'+query)
            self.send_header('Set-Cookie',f'oauth_state={state}'+self.cookie_options())
            self.send_header('Set-Cookie','repair_login_paused=; Max-Age=0'+self.cookie_options()); self.end_headers(); return
        if path=='/auth/callback':
            q=urllib.parse.parse_qs(url.query); state=q.get('state',[''])[0]
            cookie=SimpleCookie(self.headers.get('Cookie','')); actual=cookie.get('oauth_state')
            if self.auto_login_paused():
                if actual and secrets.compare_digest(actual.value,state): states.pop(state,None)
                return self.send(403,{'error':'您已登出，請按登入重新開始','code':'APP_LOGGED_OUT'})
            pending=states.get(state)
            if not actual or not secrets.compare_digest(actual.value,state) or not pending or pending['expires']<time.time(): return self.send(400,{'error':'登入驗證過期，請重新登入'})
            states.pop(state,None)
            try:
                t=remote('https://api.line.me/oauth2/v2.1/token',{'grant_type':'authorization_code','code':q.get('code',[''])[0],'redirect_uri':BASE+'/auth/callback','client_id':CID,'client_secret':SECRET,'code_verifier':pending['verifier']},form=True)
                profile=verify_id_token(t['id_token'],CID,pending['nonce'])
                verified_name=trusted_display_name(profile.get('name'))
                headers=self.login(profile['sub'],verified_name or 'LINE 客戶',display_name=verified_name,line_verified=True)
                self.send_response(302); self.send_header('Location','/')
                for k,v in headers: self.send_header(k,v)
                self.end_headers(); return
            except Exception: return self.send(400,{'error':'LINE 登入失敗，請重試'})
        if path=='/api/cases':
            u=self.user()
            if not u: return self.send(401,{'error':'請先登入'})
            with connect() as c:
                rows=c.execute('SELECT * FROM cases ORDER BY created DESC' if u['admin'] else 'SELECT * FROM cases WHERE user_id=? ORDER BY created DESC', () if u['admin'] else (u['id'],)).fetchall()
            return self.send(200,{'cases':[self.case_dict(r,u['admin']) for r in rows]})
        if path in ('/','/admin','/index.html'):
            raw=(ROOT/'index.html').read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer'); self.end_headers(); self.wfile.write(raw); return
        if path=='/address-data.json':
            return self.send(200,public_address_data())
        if path=='/assets/return-items.png':
            raw=(ROOT/'assets'/'return-items.png').read_bytes()
            self.send_response(200); self.send_header('Content-Type','image/png'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path=='/line-client.js':
            raw=(ROOT/'line-client.js').read_bytes(); self.send_response(200); self.send_header('Content-Type','text/javascript; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw); return
        self.send(404,{'error':'找不到頁面'})
    def do_POST(self):
        if DEMO and self.headers.get('Cf-Connecting-IP'):
            return self.send(503,{'error':'LINE 測試服務設定中，尚未開放申請'})
        path=urllib.parse.urlparse(self.path).path
        if path=='/api/line-webhook': return self.webhook()
        if not self.allowed_origin(): return self.send(403,{'error':'不允許的來源'})
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<=200000: return self.send(413,{'error':'資料大小錯誤'})
            raw=self.rfile.read(size)
            data=(json.loads(raw,object_pairs_hook=payment_json_object,parse_constant=payment_json_constant)
                  if path.startswith('/api/payments/') else json.loads(raw))
        except Exception: return self.send(400,{'error':'資料格式錯誤'})
        if not isinstance(data,dict): return self.send(400,{'error':'資料格式錯誤'})
        if path=='/api/line-setup': return self.configure_line(data)
        if path=='/api/local-cloud-config': return self.configure_cloud(data)
        if path=='/api/liff-login':
            if DEMO or not CID or not LIFF_ID: return self.send(503,{'error':'LIFF 尚未啟用'})
            if self.auto_login_paused() and data.get('explicit') is not True:
                return self.send(403,{'error':'您已登出，請按登入重新開始','code':'APP_LOGGED_OUT'})
            try:
                profile=verify_id_token(data.get('idToken'),CID)
                verified_name=trusted_display_name(profile.get('name'))
                return self.send(200,{'ok':True},self.login(profile['sub'],verified_name or 'LINE 客戶',display_name=verified_name,line_verified=True))
            except ValueError: return self.send(401,{'error':'LINE 登入驗證失敗，請重新登入'})
        if path=='/api/demo-login' and DEMO: return self.send(200,{'ok':True},self.login('demo-customer','測試客戶'))
        if path=='/api/demo-admin' and DEMO: return self.send(200,{'ok':True},self.login('demo-admin','測試管理員',True))
        if path=='/api/admin-login':
            attempts=auth_attempts.setdefault(self.client_address[0],[])
            attempts[:]=[stamp for stamp in attempts if stamp>time.time()-600]
            if len(attempts)>=10: return self.send(429,{'error':'登入嘗試過多，請稍後再試'})
            if not ADMIN: return self.send(503,{'error':'請先在啟動環境設定 REPAIR_ADMIN_PASSWORD'})
            if not isinstance(data.get('password'),str) or not secrets.compare_digest(data['password'].encode('utf-8'),ADMIN.encode('utf-8')):
                attempts.append(time.time())
                time.sleep(1); return self.send(403,{'error':'密碼不正確'})
            return self.send(200,{'ok':True},self.login('admin','管理員',True))
        if path=='/api/logout':
            cookie=SimpleCookie(self.headers.get('Cookie','')); key=cookie.get('repair_session')
            if key: sessions.pop(key.value,None)
            oauth_state=cookie.get('oauth_state')
            if oauth_state: states.pop(oauth_state.value,None)
            options=self.cookie_options()
            headers=[('Set-Cookie','repair_session=; Max-Age=0'+options),('Set-Cookie','repair_login_paused=1; Max-Age=2592000'+options),('Set-Cookie','oauth_state=; Max-Age=0'+options)]
            return self.send(200,{'ok':True},headers)
        u=self.user()
        if not u: return self.send(401,{'error':'請先登入'})
        if PAYMENTS and PAYMENTS.handle_post(self,path,data,u): return
        if path=='/api/line-entry':
            if DEMO or not MESSAGE_SECRET or not BOT_UID: return self.send(503,{'error':'官方 LINE 申請入口尚未設定'})
            if not u.get('lineVerified') or u.get('admin') or not re.fullmatch(r'U[0-9a-f]{32}',u['id']):
                return self.send(403,{'error':'請先完成 LINE 登入'})
            ticket=data.get('ticket')
            if set(data)!={'ticket'} or not isinstance(ticket,str) or not ENTRY_TICKET_PATTERN.fullmatch(ticket):
                return self.send(400,{'error':'申請入口已失效，請從客服 LINE 重新開啟'})
            ticket_hash=hashlib.sha256(ticket.encode('ascii')).hexdigest()
            with connect() as c:
                row=c.execute('SELECT expires FROM line_entry_tickets WHERE ticket_hash=? AND user_id=? AND bot_user_id=?',(ticket_hash,u['id'],BOT_UID)).fetchone()
            if not row: return self.send(404,{'error':'申請入口不適用此 LINE 帳號，請從客服 LINE 重新開啟'})
            if row['expires']<=time.time(): return self.send(410,{'error':'申請入口已逾時，請在客服 LINE 傳送「維修申請」重新開啟'})
            # The signed entry proves the OA source and logged-in user only.
            # A summary is received only when its own signed OA webhook arrives.
            u.update({'officialEntry':True,'officialEntryExpiresAt':row['expires'],'officialEntryTicketHash':ticket_hash,'officialEntryBotUserId':BOT_UID})
            return self.send(200,{'ok':True,'officialEntry':True,'expiresAt':int(row['expires'])})
        if path=='/api/line-profiles-sync':
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if data: return self.send(400,{'error':'此功能僅補查既有案件，不接受指定 LINE 帳號'})
            if DEMO or not TOKEN: return self.send(503,{'error':'正式 LINE 尚未設定'})
            try: inspect_bot(TOKEN,OA)
            except ValueError: return self.send(502,{'error':'無法驗證客服 LINE 帳號'})
            with connect() as c:
                rows=c.execute('SELECT user_id,COUNT(*) AS case_count FROM cases GROUP BY user_id').fetchall()
                blank_ids={row['user_id'] for row in c.execute('SELECT DISTINCT user_id FROM cases WHERE TRIM(line_display_name)=""')}
            updated=unavailable=skipped=0
            for row in rows:
                uid=row['user_id']
                if not isinstance(uid,str) or not re.fullmatch(r'U[0-9a-f]{32}',uid):
                    skipped+=row['case_count']; continue
                if uid not in blank_ids: continue
                try:
                    profile=get_profile(TOKEN,uid)
                    if profile.get('userId')!=uid or not trusted_display_name(profile.get('displayName')): raise ValueError('invalid profile')
                    updated+=backfill_line_name(uid,profile['displayName'])
                except ValueError: unavailable+=1
            return self.send(200,{'updated':updated,'unavailable':unavailable,'skippedTest':skipped})
        if path=='/api/cloud-retry':
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if not cloud_configured(): return self.send(503,{'error':'請先完成本機雲端同步設定'})
            count=backfill_cloud_cases()
            return self.send(200,{'ok':True,'queued':count,**public_cloud_status()})
        if path=='/api/pickup-retry':
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if not pickup_configured(): return self.send(503,{'error':'請先完成派車回收名單同步設定'})
            count=retry_existing_pickups()
            return self.send(200,{'ok':True,'queued':count,**public_cloud_status()})
        if path=='/api/pickup-notification-group':
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if set(data)!={'groupId'} or not isinstance(data.get('groupId'),str): return self.send(400,{'error':'群組設定格式錯誤'})
            try: bind_pickup_notification_group(data['groupId'])
            except ValueError as error:
                code=str(error)
                if code=='not_available': return self.send(503,{'error':'LINE 群組通知尚未設定'})
                if code=='group_unavailable': return self.send(502,{'error':'無法驗證此群組，請確認官方帳號仍在群組中'})
                if code=='group_name_changed': return self.send(409,{'error':'群組名稱已更新，請重新選取群組'})
                return self.send(400,{'error':'請選擇已確認官方帳號加入的有效群組'})
            return self.send(200,{'ok':True,**pickup_notification_status()})
        if path=='/api/pickup-notification-retry':
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if data: return self.send(400,{'error':'此功能只重試既有通知，不接受指定案件或訊息'})
            if not pickup_notification_available(): return self.send(503,{'error':'LINE 群組通知尚未設定'})
            count=retry_pickup_notifications()
            return self.send(200,{'ok':True,'queued':count,**pickup_notification_status()})
        if path=='/api/pickup-dispatch-retry':
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if data: return self.send(400,{'error':'此功能只重試既有派車指令，不接受指定案件或狀態'})
            if not pickup_dispatch_available(): return self.send(503,{'error':'派車指令同步尚未設定'})
            count=retry_pickup_dispatches()
            return self.send(200,{'ok':True,'queued':count,**pickup_dispatch_status()})
        if path in ('/api/dispatch-workflow-settings','/api/dispatch-workflow-menu'):
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            try:
                if path.endswith('settings'):
                    if set(data)!={'dailyEnabled'} or type(data['dailyEnabled']) is not bool: raise ValueError('invalid_setting')
                    WORKFLOW.configure(data['dailyEnabled'])
                else:
                    if set(data)!={'requestId'}: raise ValueError('invalid_request')
                    WORKFLOW.menu_push(data['requestId'])
            except ValueError: return self.send(400,{'error':'請確認群組連線及設定格式'})
            return self.send(200,{'ok':True,**WORKFLOW.status()})
        if path=='/api/line-handshake':
            if DEMO or not MESSAGE_SECRET or not BOT_UID: return self.send(503,{'error':'官方 LINE 連線確認尚未設定'})
            case_id=data.get('caseId')
            if not isinstance(case_id,str) or not re.fullmatch(r'R\d{8}-\d{4,}',case_id): return self.send(400,{'error':'案件編號格式錯誤'})
            with connect() as c:
                row=c.execute('SELECT id FROM cases WHERE id=? AND user_id=?',(case_id,u['id'])).fetchone()
                if not row: return self.send(404,{'error':'找不到案件'})
                nonce=secrets.token_urlsafe(24)
                c.execute('INSERT INTO line_handshakes(nonce,case_id,user_id,expires) VALUES(?,?,?,?)',(nonce,case_id,u['id'],time.time()+600))
            return self.send(201,{'nonce':nonce,'probeText':probe_text(case_id,nonce)})
        if path=='/api/line-webhook-config':
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            if DEMO or not TOKEN: return self.send(503,{'error':'正式 LINE 尚未設定'})
            expected=BASE+'/api/line-webhook'
            try:
                inspect_bot(TOKEN,OA); current=get_webhook_endpoint(TOKEN)
                if current['endpoint'] and current['endpoint']!=expected:
                    return self.send(409,{'error':'官方帳號已有其他 Webhook，本系統保留既有設定','webhook':webhook_public_info(current),'expectedWebhookUrl':expected})
                if not current['endpoint']: set_webhook_endpoint(TOKEN,expected)
            except ValueError: return self.send(502,{'error':'無法安全設定 LINE Webhook'})
            return self.send(200,{'ok':True,'endpoint':expected,'active':current['active'],'requiresActivation':not current['active']})
        if path=='/api/cases':
            if not DEMO and (u.get('admin') or not u.get('lineVerified') or not isinstance(u.get('id'),str) or not re.fullmatch(r'U[0-9a-f]{32}',u['id'])):
                return self.send(403,{'error':'請以客戶 LINE 帳號登入後提交維修申請'})
            fields=['name','phone','model','problem','shipping']
            if any(not isinstance(data.get(k),str) or not data[k].strip() for k in fields): return self.send(400,{'error':'請填寫所有必填欄位'})
            if any(len(str(v))>8000 for v in data.values()): return self.send(400,{'error':'欄位內容過長'})
            shipping = data['shipping'].strip()
            if shipping == '客服安排收件': shipping = '由客服派遣物流回收'
            if shipping not in ['自行寄送','由客服派遣物流回收','親自送回']:
                return self.send(400,{'error':'寄送方式錯誤'})
            order_choice = data.get('orderChoice')
            if order_choice not in ('provided', 'missing'):
                return self.send(400,{'error':'請選擇是否能提供訂單編號'})
            order_number = data.get('order', '')
            if order_choice == 'provided':
                if not isinstance(order_number, str) or not order_number.strip():
                    return self.send(400,{'error':'選擇有訂單編號時，請填寫訂單編號'})
                order_number = order_number.strip()
                if len(order_number) > 300:
                    return self.send(400,{'error':'訂單編號不可超過 300 字'})
            else:
                order_number = ''
            if data.get('rules')!=[True]*4 or data.get('checks')!=[True]*4 or data.get('privacy') is not True: return self.send(400,{'error':'請完成規範與最後確認'})
            rid=data.get('requestId','')
            if not isinstance(rid,str) or not 10<=len(rid)<=100: return self.send(400,{'error':'申請識別碼錯誤'})
            clean={k:str(data.get(k,'')) for k in ['name','phone','email','model','serial','order','purchase','problem','extra','shipping','pickupAddress','returnAddress']}
            clean.update({'order':order_number,'orderChoice':order_choice,
                          'repairPolicy':'保固外付費維修' if order_choice == 'missing' else '待核對保固'})
            clean.update({'shipping':shipping,
                          'pickupFeeTwd':350 if shipping == '由客服派遣物流回收' else None,
                          'shippingNote':'親自送回時，請先將商品妥善裝箱，並交由管理室代收。為維護商品安全，未裝箱之商品，管理室恕無法代收，敬請見諒。\n若技師評估包裝強度不足，可能於運送途中造成商品損壞，為保障商品安全，我們將於維修完成後通知您親自領回。\n若您了解上述風險後，仍選擇以寄送方式領回，運送途中之商品損壞風險須由您自行承擔，本公司恕無法負擔相關損壞之賠償責任。' if shipping == '親自送回' else ''})
            clean.update({'rules':[True]*4,'checks':[True]*4,'privacy':True,'rulesVersion':'shipping-2026-10-16-v6'})
            if PAYMENTS is not None and PAYMENTS.new_cases_enabled is True:
                clean['paymentWorkflow']=PAYMENT_WORKFLOW
            now=time.strftime('%Y-%m-%d %H:%M:%S'); day=time.strftime('%Y%m%d')
            with connect() as c:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT * FROM cases WHERE user_id=? AND request_id=?',(u['id'],rid)).fetchone()
                if old: return self.send(200,{'case':self.case_dict(old)})
                if c.execute('SELECT 1 FROM deleted_case_requests WHERE user_id=? AND request_id=?',(u['id'],rid)).fetchone():
                    return self.send(409,{'error':'此測試申請已清理，請重新開啟表單後再送出。','code':'case_cleaned'})
                try:
                    clean.update(validate_case_addresses(data, shipping))
                except ValueError as exc:
                    return self.send(400,{'error':str(exc)})
                ident=next_case_number(c,day)
                history=json.dumps([{'time':now,'status':'已申請','by':'客戶'}],ensure_ascii=False)
                c.execute('INSERT INTO cases(id,user_id,request_id,data,status,created,history,line_display_name) VALUES(?,?,?,?,?,?,?,?)',(ident,u['id'],rid,json.dumps(clean,ensure_ascii=False),'已申請',now,history,trusted_display_name(u.get('displayName'))))
                enqueue_cloud_case(c,ident)
                enroll_new_pickup_case(c,ident)
                enroll_new_pickup_notification(c,ident)
            if clean.get('paymentWorkflow')==PAYMENT_WORKFLOW:
                # The repair INSERT has committed before touching payments.db.
                # Background enrollment recovers failure without opening pickup.
                try:
                    PAYMENTS.enroll(ident)
                    PAYMENTS.wake()
                except Exception: pass
            result=notify({'user_id':u['id'],'id':ident,'status':'已申請','data':clean,'history':history})
            with connect() as c:
                c.execute('UPDATE cases SET notification=? WHERE id=?',(result,ident)); enqueue_cloud_case(c,ident); row=c.execute('SELECT * FROM cases WHERE id=?',(ident,)).fetchone()
            return self.send(201,{'case':self.case_dict(row)})
        if path in ('/api/update','/api/retry'):
            if not u['admin']: return self.send(403,{'error':'需要管理員權限'})
            send_status_notification=True
            with connect() as c:
                row=c.execute('SELECT * FROM cases WHERE id=?',(data.get('id'),)).fetchone()
                if not row: return self.send(404,{'error':'找不到案件'})
                case=dict(row)
                if path=='/api/update':
                    if data.get('status') not in STATUS: return self.send(400,{'error':'狀態錯誤'})
                    if data['status']!=row['status'] and data['status'] in PAYMENT_REQUIRED_STATUSES and not payment_case_allowed(case):
                        return self.send(409,{'error':'案件尚未完成付款或免付款核定，暫不能安排送修或派車','code':'payment_required'})
                    if data['status']==row['status'] and data['status'] in PAYMENT_REQUIRED_STATUSES and not payment_case_allowed(case):
                        send_status_notification=False
                    h=json.loads(row['history'])
                    if row['status']!=data['status']: h.append({'time':time.strftime('%Y-%m-%d %H:%M:%S'),'status':data['status'],'by':'客服'})
                    c.execute('UPDATE cases SET status=?,note=?,history=? WHERE id=?',(data['status'],str(data.get('note',''))[:8000],json.dumps(h,ensure_ascii=False),row['id']))
                    enqueue_cloud_case(c,row['id'])
                    case['status']=data['status']
                    case['history']=json.dumps(h,ensure_ascii=False)
                elif row['status'] in PAYMENT_REQUIRED_STATUSES and not payment_case_allowed(case):
                    return self.send(409,{'error':'案件付款狀態已暫停，請先完成付款核對','code':'payment_required'})
            result=notify(case) if send_status_notification else case['notification']
            with connect() as c:
                c.execute('UPDATE cases SET notification=? WHERE id=?',(result,case['id']))
                enqueue_cloud_case(c,case['id'])
            return self.send(200,{'ok':True,'notification':result})
        self.send(404,{'error':'找不到操作'})
    def webhook(self):
        if not MESSAGE_SECRET or not BOT_UID: return self.send(503,{'error':'Webhook 尚未設定'})
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<=1000000: return self.send(413,{'error':'資料大小錯誤'})
            raw=self.rfile.read(size)
        except Exception: return self.send(400,{'error':'資料格式錯誤'})
        if not validate_webhook_signature(raw,self.headers.get('X-Line-Signature',''),MESSAGE_SECRET):
            return self.send(401,{'error':'Webhook 簽章錯誤'})
        try: payload=json.loads(raw)
        except Exception: return self.send(400,{'error':'Webhook 資料格式錯誤'})
        if not isinstance(payload,dict) or payload.get('destination')!=BOT_UID or not isinstance(payload.get('events'),list):
            return self.send(400,{'error':'Webhook 帳號或事件格式錯誤'})
        for event in payload['events']:
            if not isinstance(event,dict): continue
            source=event.get('source',{}); message=event.get('message',{})
            if not isinstance(source,dict): continue
            if source.get('type')=='group':
                observe_pickup_group(event)
                if not WORKFLOW.enqueue(event): enqueue_pickup_dispatch(event)
                continue
            if not isinstance(message,dict): continue
            if event.get('type')!='message' or source.get('type')!='user' or message.get('type')!='text': continue
            event_id=event.get('webhookEventId'); text=message.get('text','')
            uid=source.get('userId')
            if not isinstance(event_id,str) or not 1<=len(event_id)<=128 or not isinstance(text,str) or not isinstance(uid,str) or not re.fullmatch(r'U[0-9a-f]{32}',uid): continue
            with connect() as c:
                inserted=c.execute('INSERT OR IGNORE INTO line_webhook_events(event_id,received) VALUES(?,?)',(event_id,time.time())).rowcount
            if not inserted: continue
            if text.strip() in ('維修申請','送修申請'):
                if LIFF_ID and TOKEN:
                    ticket=secrets.token_urlsafe(32); now=time.time()
                    with connect() as c:
                        c.execute('DELETE FROM line_entry_tickets WHERE expires<=?',(now,))
                        c.execute('INSERT INTO line_entry_tickets(ticket_hash,user_id,bot_user_id,expires,created,event_id) VALUES(?,?,?,?,?,?)',(hashlib.sha256(ticket.encode('ascii')).hexdigest(),uid,BOT_UID,int(now)+3600,now,event_id))
                    entry_url='https://liff.line.me/'+urllib.parse.quote(LIFF_ID,safe='')+'?'+urllib.parse.urlencode({'entry':ticket})
                    messages=[{'type':'template','altText':'開啟商品檢修申請','template':{'type':'buttons','text':'請點擊下方按鈕填寫商品檢修申請。送出後，系統會自動將案件資料傳回此客服聊天室。','actions':[{'type':'uri','label':'開始維修申請','uri':entry_url}]}}]
                    result=send_reply(TOKEN,event.get('replyToken'),messages)
                    with connect() as c: c.execute('UPDATE line_webhook_events SET reply_result=? WHERE event_id=?',(json.dumps(result),event_id))
                continue
            if text.startswith(PROBE_HEADING):
                match=re.fullmatch(re.escape(PROBE_HEADING)+r'\n案件編號：(R\d{8}-\d{4,})\n服務代碼：([A-Za-z0-9_-]{32})',text)
                if match:
                    with connect() as c:
                        c.execute('UPDATE line_handshakes SET confirmed=?,event_id=? WHERE nonce=? AND case_id=? AND user_id=? AND expires>? AND confirmed=""',(time.strftime('%Y-%m-%d %H:%M:%S'),event_id,match.group(2),match.group(1),uid,time.time()))
                # A routing probe proves this particular attempt reached the OA;
                # it is never evidence that the full application was received.
                continue
            match=CASE_REFERENCE.search(text)
            if not match: continue
            full_summary=(text.startswith(SUMMARY_HEADING+'\n')
                          and re.search(r'^申請人[：:][^\r\n]+$',text,re.MULTILINE)
                          and re.search(r'^訂單編號[：:][^\r\n]+$',text,re.MULTILINE))
            compact_summary=THREE_LINE_SUMMARY.fullmatch(text) or CONFIRMATION_SUMMARY.fullmatch(text)
            if compact_summary and all(value.strip() for value in compact_summary.groups() if value is not None):
                full_summary=True
            with connect() as c:
                row=c.execute('SELECT id,user_id FROM cases WHERE id=? AND user_id=?',(match.group(1),uid)).fetchone()
                if row:
                    received=time.strftime('%Y-%m-%d %H:%M:%S')
                    c.execute('INSERT OR IGNORE INTO line_receipts(case_id,user_id,received,event_id) VALUES(?,?,?,?)',(row['id'],row['user_id'],received,event_id))
                    if full_summary:
                        c.execute('UPDATE line_receipts SET summary_received=? WHERE case_id=? AND user_id=? AND summary_received=""',(received,row['id'],row['user_id']))
                    enqueue_cloud_case(c,row['id'])
        return self.send(200,{'ok':True})
    def configure_line(self,data):
        global CID, LIFF_ID, SECRET, TOKEN, MESSAGE_SECRET, BOT_UID, ADMIN, BASE, DEMO, PRIVATE
        if not self.local_setup() or self.headers.get('Origin')!='http://127.0.0.1:8787' or not secrets.compare_digest(self.headers.get('X-Repair-Setup',''),SETUP_TOKEN):
            return self.send(403,{'error':'設定頁只限本機使用，請重新開啟設定頁'})
        keys=['loginChannelId','liffId','messagingChannelId','publicUrl','loginChannelSecret','messagingChannelSecret','messagingAccessToken','adminPassword']
        if any(not isinstance(data.get(k,''),str) for k in keys): return self.send(400,{'error':'設定格式錯誤'})
        values={k:data.get(k,'').strip() for k in keys}
        for key,current in [('loginChannelSecret',SECRET),('messagingChannelSecret',MESSAGE_SECRET),('messagingAccessToken',TOKEN),('adminPassword',ADMIN)]:
            if not values[key]: values[key]=current
        parsed=urllib.parse.urlparse(values['publicUrl'])
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            return self.send(400,{'error':'請填入完整 HTTPS 網站根網址'})
        if not values['loginChannelId'].isdigit() or not values['messagingChannelId'].isdigit() or not re.fullmatch(re.escape(values['loginChannelId'])+r'-[A-Za-z0-9]+',values['liffId']):
            return self.send(400,{'error':'請確認 LINE Login Channel ID、Messaging Channel ID 與 LIFF ID'})
        if not all(values.values()) or len(values['adminPassword'])<12 or any(len(v)>10000 for v in values.values()):
            return self.send(400,{'error':'請完成所有設定，管理員密碼至少 12 字'})
        try: bot=inspect_bot(values['messagingAccessToken'],OA)
        except ValueError: return self.send(400,{'error':'Messaging API Token 無法驗證為 @694hrgtr，請檢查是否從正確客服帳號取得'})
        values['publicUrl']=values['publicUrl'].rstrip('/'); values['botUserId']=bot['userId']; values['mode']='live'
        try:
            with CLOUD_LOCK:
                combined={**PRIVATE,**values}; write_private_config(combined); PRIVATE=combined
        except ValueError:
            return self.send(500,{'error':'無法安全儲存本機設定，請檢查資料夾權限'})
        CID=values['loginChannelId']; LIFF_ID=values['liffId']; SECRET=values['loginChannelSecret']; TOKEN=values['messagingAccessToken']; MESSAGE_SECRET=values['messagingChannelSecret']; BOT_UID=bot['userId']; ADMIN=values['adminPassword']; BASE=values['publicUrl']; DEMO=False
        sessions.clear(); states.clear()
        return self.send(200,{'ok':True,'publicUrl':BASE,'liffId':LIFF_ID,'callbackUrl':BASE+'/auth/callback','webhookUrl':BASE+'/api/line-webhook'})
    def configure_cloud(self,data):
        global PRIVATE,CLOUD_VERIFIED_FINGERPRINT,CLOUD_VERIFY_NEXT
        if not self.local_setup() or self.headers.get('Origin')!='http://127.0.0.1:8787' or not secrets.compare_digest(self.headers.get('X-Repair-Setup',''),SETUP_TOKEN):
            return self.send(403,{'error':'雲端設定只限本機使用，請重新開啟設定頁'})
        aliases={'googleSheetEndpoint':'endpoint','googleSheetSecret':'secret','googleSheetId':'sheetId'}
        values={key:data.get(key,data.get(alias,'')) for key,alias in aliases.items()}
        if not all(isinstance(value,str) for value in values.values()): return self.send(400,{'error':'雲端設定格式錯誤'})
        values={key:value.strip() for key,value in values.items()}
        if not values['googleSheetSecret']: values['googleSheetSecret']=PRIVATE.get('googleSheetSecret','')
        if not cloud_configured(values): return self.send(400,{'error':'請確認 Google 部署網址、試算表 ID 與 32–128 字元的同步金鑰'})
        try:
            verified=cloud_ping(values['googleSheetEndpoint'],values['googleSheetSecret'],values['googleSheetId'])
            if not isinstance(verified,dict) or verified.get('state')!='synced':
                return self.send(400,{'error':'雲端接收端驗證失敗，請確認試算表綁定、部署權限與同步金鑰'})
            with CLOUD_LOCK:
                combined={**PRIVATE,**values}; write_private_config(combined); PRIVATE=combined
                CLOUD_VERIFIED_FINGERPRINT=cloud_fingerprint(values); CLOUD_VERIFY_NEXT=0
                count=backfill_cloud_cases()
        except ValueError: return self.send(500,{'error':'無法安全儲存雲端設定'})
        except Exception: return self.send(502,{'error':'暫時無法驗證或啟用 Google 雲端同步'})
        return self.send(200,{'ok':True,'queued':count,**public_cloud_status()})
    def log_message(self,*args): pass

def validate_service_config():
    """Fail closed before starting external integrations in a live deployment."""
    if not DEMO:
        parsed=urllib.parse.urlparse(BASE)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('','/') or any(char.isspace() for char in BASE)
                or not CID or not LIFF_ID or not SECRET or not TOKEN or not MESSAGE_SECRET or len(ADMIN)<12):
            raise ValueError('正式 LINE 設定不完整或網站網址不正確，尚未開放服務。')
    if CLOUD_DEPLOYMENT:
        hostname=urllib.parse.urlparse(BASE).hostname or ''
        if DEMO or not PUBLIC_BASE or not RUNTIME_ENV or not Path(RUNTIME_ENV).is_absolute() or hostname=='trycloudflare.com' or hostname.endswith('.trycloudflare.com'):
            raise ValueError('雲端服務需正式模式、固定 HTTPS 網址與獨立持久資料目錄。')
    probe=DATA_DIR/('.write-check-'+secrets.token_hex(8))
    created=False
    try:
        fd=os.open(probe,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        created=True
        os.close(fd); probe.unlink()
    except OSError:
        try:
            if created and probe.exists(): probe.unlink()
        except OSError: pass
        raise ValueError('維修資料目錄無法寫入，尚未開放服務。') from None

WORKFLOW = DispatchWorkflow(globals())

def start_service():
    """Initialize once per Python process; imports never start network/worker IO."""
    global SERVICE_STARTED,BOT_UID,PAYMENTS
    with SERVICE_LOCK:
        if SERVICE_STARTED: return
        validate_service_config()
        if not DEMO:
            try: BOT_UID=inspect_bot(TOKEN,OA)['userId']
            except (ValueError,KeyError): raise ValueError('無法驗證客服 LINE 帳號，尚未開放服務。') from None
        from production_payments import start_payments
        PAYMENTS=start_payments(globals())
        start_cloud_worker()
        WORKFLOW.start()
        SERVICE_STARTED=True

if __name__=='__main__':
    try:
        port=int(os.environ.get('PORT','8787'))
        if not 1<=port<=65535: raise ValueError('port')
        start_service()
    except ValueError as error: raise SystemExit(str(error)) from None
    print('Repair system: '+BASE,flush=True)
    print('Mode: '+('demo' if DEMO else 'live'),flush=True)
    ThreadingHTTPServer((os.environ.get('HOST','127.0.0.1'),port),Handler).serve_forever()
