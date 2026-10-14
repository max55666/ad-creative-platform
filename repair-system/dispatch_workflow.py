"""Private, persistent dispatch queries and daily summaries; imports do no I/O."""
import datetime as dt
import json
import math
import re
import secrets
import threading
import time
import uuid

TAIPEI = dt.timezone(dt.timedelta(hours=8))
CASE = r'R[0-9]{8}-[0-9]{4,}'
SNAPSHOT = r'[A-Za-z0-9_-]{16,64}'
RETRY_SECONDS = 23 * 3600


def init_tables(c):
    c.execute('''CREATE TABLE IF NOT EXISTS dispatch_query_events (
        event_id TEXT PRIMARY KEY,group_id TEXT NOT NULL,kind TEXT NOT NULL,args TEXT NOT NULL,
        reply_token TEXT NOT NULL,deadline REAL NOT NULL,created REAL NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',last_error TEXT NOT NULL DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS dispatch_query_snapshots (
        id TEXT PRIMARY KEY,group_id TEXT NOT NULL,case_ids TEXT NOT NULL,created REAL NOT NULL,
        expires REAL NOT NULL,next_page INTEGER NOT NULL DEFAULT 2)''')
    c.execute('''CREATE TABLE IF NOT EXISTS dispatch_workflow_settings (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),daily_enabled INTEGER NOT NULL DEFAULT 0,
        group_id TEXT NOT NULL DEFAULT '',enabled_at REAL NOT NULL DEFAULT 0,first_date TEXT NOT NULL DEFAULT '')''')
    c.execute('INSERT OR IGNORE INTO dispatch_workflow_settings(singleton) VALUES(1)')
    c.execute('''CREATE TABLE IF NOT EXISTS dispatch_daily_jobs (
        job_key TEXT PRIMARY KEY,group_id TEXT NOT NULL,local_date TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',created REAL NOT NULL,next_attempt REAL NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',UNIQUE(group_id,local_date))''')
    c.execute('''CREATE TABLE IF NOT EXISTS dispatch_workflow_push (
        job_key TEXT NOT NULL,sequence INTEGER NOT NULL,group_id TEXT NOT NULL,messages TEXT NOT NULL,
        retry_key TEXT UNIQUE NOT NULL,created REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
        first_attempt REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '',accepted_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(job_key,sequence))''')


def cancel_for_group(c, group_id=None):
    suffix = ' AND group_id=?' if group_id else ''
    args = (group_id,) if group_id else ()
    c.execute("UPDATE dispatch_query_events SET state='cancelled',reply_token='',last_error='group_changed' WHERE state IN ('pending','working','responding')"+suffix, args)
    c.execute("UPDATE dispatch_daily_jobs SET state='cancelled',last_error='group_changed' WHERE state IN ('pending','working','ready','failed')"+suffix, args)
    c.execute("UPDATE dispatch_workflow_push SET state='cancelled',last_error='group_changed' WHERE state IN ('pending','working','failed','needs_review')"+suffix, args)
    c.execute('DELETE FROM dispatch_query_snapshots'+(' WHERE group_id=?' if group_id else ''), args)
    c.execute("UPDATE dispatch_workflow_settings SET daily_enabled=0"+(' WHERE group_id=?' if group_id else ''), args)


def parse(event):
    if event.get('type') == 'postback':
        data = event.get('postback', {})
        value = data.get('data') if isinstance(data, dict) else None
        if value in ('pv1:menu', 'pv1:count', 'pv1:list', 'pv1:refresh'):
            return value.split(':')[1], {}
        if isinstance(value, str):
            match = re.fullmatch(r'pv1:next:('+SNAPSHOT+r'):([1-9][0-9]{0,5})', value)
            if match: return 'next', {'snapshot': match[1], 'page': int(match[2])}
            match = re.fullmatch(r'pv1:dispatch:('+CASE+r')', value)
            if match and len(match[1]) <= 80: return 'dispatch', {'caseId': match[1]}
        return None
    message = event.get('message', {})
    if event.get('type') != 'message' or not isinstance(message, dict) or message.get('type') != 'text': return None
    text = message.get('text')
    if not isinstance(text, str): return None
    text = text.strip()
    aliases = {'派車選單': 'menu', '派車指令': 'menu', '未派車幾筆': 'count', '未派車數量': 'count', '未派車名單': 'list', '下一頁': 'next'}
    if text in aliases: return aliases[text], {}
    match = re.fullmatch(r'派車查詢\s+('+CASE+r')', text)
    if match and len(match[1]) <= 80: return 'case', {'caseId': match[1]}
    match = re.fullmatch(r'('+CASE+r')\s*已派車', text)
    if match and len(match[1]) <= 80: return 'dispatch', {'caseId': match[1]}
    return None


class DispatchWorkflow:
    def __init__(self, server, clock=time.time):
        self.s, self.clock = server, clock
        self.query_wake, self.daily_wake = threading.Event(), threading.Event()
        self.query_lock, self.daily_lock, self.push_lock = threading.Lock(), threading.Lock(), threading.Lock()
        self.started = False

    def available(self): return self.s['pickup_dispatch_available']()

    def group(self, c, expected=None):
        group = self.s['selected_pickup_group'](c)
        return group if self.s['active_pickup_group'](group) and (expected is None or group['group_id'] == expected) else None

    def allowlist(self):
        with self.s['connect']() as c:
            rows = c.execute('''SELECT c.* FROM cases c JOIN pickup_outbox p ON p.case_id=c.id
                WHERE p.state='synced' OR p.synced_at<>'' ORDER BY c.created,c.id''').fetchall()
        return [row['id'] for row in rows if self.s['pickup_eligible'](dict(row))]

    def read(self, ids):
        from cloud_support import read_pickup_dispatch
        values = self.s['cloud_settings']()
        rows = []
        for start in range(0, max(1, len(ids)), 1000):
            requested = ids[start:start+1000]
            result = read_pickup_dispatch(values['googleSheetEndpoint'], values['googleSheetSecret'], values['googleSheetId'], requested)
            got = result.get('cases') if isinstance(result, dict) and result.get('state') == 'synced' else None
            if not isinstance(got, list) or [r.get('caseId') for r in got if isinstance(r, dict)] != requested:
                raise ValueError('query_unavailable')
            rows.extend(got)
        return rows

    def menu(self, total=None):
        from dispatch_cards import menu_messages
        return menu_messages(total=total)

    def cards(self, cases, total, snapshot, page, pages, queried, daily=False):
        from dispatch_cards import list_messages
        return list_messages(cases, total, snapshot, page, pages, queried, daily=daily)

    def case_cards(self, row, queried):
        from dispatch_cards import case_messages
        return case_messages(row, queried)

    def enqueue(self, event):
        parsed = parse(event)
        if not parsed or not self.available(): return False
        source = event.get('source', {})
        if not isinstance(source, dict) or source.get('type') != 'group': return False
        ident, stamp = event.get('webhookEventId'), event.get('timestamp')
        now = self.clock()
        if not isinstance(ident, str) or not re.fullmatch(r'[!-~]{1,128}', ident) or type(stamp) is not int or stamp <= 0 or stamp > now*1000+300000: return False
        kind, args = parsed
        inserted = 0
        # Admission is serialized with leave/disable/rebind cancellation. This
        # lock contains only local reads/writes, never Google or LINE requests.
        with self.s['PICKUP_NOTIFICATION_LOCK']:
            with self.s['connect']() as c:
                group = self.group(c, source.get('groupId'))
                if not group or stamp < group['event_stamp']: return False
            if kind in ('case', 'dispatch') and args['caseId'] not in self.allowlist():
                # Preserve pre-existing manual text dispatch for legacy eligible
                # cases; postback/query actions use the strict allowlist.
                if kind == 'dispatch' and event.get('type') == 'message': return False
                kind, args = 'error', {}
            reply = event.get('replyToken')
            if isinstance(reply, str) and 1 <= len(reply) <= 1024:
                deadline = min(now+45, stamp/1000+20*60)
                with self.s['connect']() as c:
                    c.execute('BEGIN IMMEDIATE')
                    current = self.group(c, source.get('groupId'))
                    if not current or stamp < current['event_stamp']: return False
                    inserted = c.execute('''INSERT OR IGNORE INTO dispatch_query_events(event_id,group_id,kind,args,reply_token,deadline,created)
                        VALUES(?,?,?,?,?,?,?)''', (ident,source['groupId'],kind,json.dumps(args),reply,deadline,now)).rowcount
        # The dispatch queue rechecks group/timestamp under the same lock.
        # Call outside it because that lock is deliberately non-reentrant.
        if kind == 'dispatch':
            converted = dict(event)
            converted.update(type='message', message={'type':'text','text':args['caseId']+'已派車'})
            self.s['enqueue_pickup_dispatch'](converted)
        if inserted: self.query_wake.set()
        return True

    def snapshot(self, group, ids):
        now, ident = self.clock(), secrets.token_urlsafe(18)
        with self.s['connect']() as c:
            c.execute('DELETE FROM dispatch_query_snapshots WHERE expires<=?', (now,))
            c.execute('INSERT INTO dispatch_query_snapshots(id,group_id,case_ids,created,expires) VALUES(?,?,?,?,?)', (ident,group,json.dumps(ids),now,now+600))
        return ident

    def messages(self, job):
        kind, args = job['kind'], json.loads(job['args'])
        if kind == 'menu': return self.menu()
        if kind == 'error': return [{'type':'text','text':'此案件不在已自動加入的派車名單中，無法查詢或回報。'}]+self.menu()
        if kind == 'dispatch':
            with self.s['connect']() as c: queued = c.execute('SELECT * FROM pickup_dispatch_outbox WHERE case_id=?', (args['caseId'],)).fetchone()
            if not queued: raise ValueError('query_unavailable')
            if queued['command_id'] != job['event_id']:
                text='已有回報處理中，可更新名單確認。' if queued['state'] in ('pending','working','failed') else '此回報未覆寫最新指令，可更新名單確認。'
                return [{'type':'text','text':text}]+self.menu()
            result = self.s['pickup_dispatch_process_once'](case_id=args['caseId'])
            with self.s['connect']() as c: queued = c.execute('SELECT * FROM pickup_dispatch_outbox WHERE case_id=?', (args['caseId'],)).fetchone()
            if queued['state'] == 'completed':
                text = '已更新派車狀態為「已派車」。' if queued['result_action'] == 'updated' else '已處理回報；已有狀態保持原樣。'
            else: text = '回報已收到，目前同步尚未完成，可更新名單確認。'
            return [{'type':'text','text':args['caseId']+'\n'+text}]+self.menu()
        allowed = self.allowlist()
        if kind == 'case':
            if args['caseId'] not in allowed: return [{'type':'text','text':'此案件不在已自動加入的派車名單中。'}]+self.menu()
            row = self.read([args['caseId']])[0]
            queried=dt.datetime.fromtimestamp(self.clock(),TAIPEI).strftime('%Y-%m-%d %H:%M:%S')
            return self.case_cards(row,queried)
        rows = self.read(allowed)
        unassigned = [row for row in rows if row['status'] == '']
        queried = dt.datetime.fromtimestamp(self.clock(),TAIPEI).strftime('%Y-%m-%d %H:%M:%S')
        if kind == 'count': return [{'type':'text','text':'目前未派車 '+str(len(unassigned))+' 筆。\n查詢時間：'+queried}]+self.menu(len(unassigned))
        if kind in ('list','refresh'):
            ident = self.snapshot(job['group_id'],[row['caseId'] for row in unassigned])
            return self.cards(unassigned[:10],len(unassigned),ident,1,max(1,math.ceil(len(unassigned)/10)),queried)
        if kind == 'next':
            with self.s['connect']() as c:
                if args.get('snapshot'):
                    snap = c.execute('SELECT * FROM dispatch_query_snapshots WHERE id=? AND group_id=? AND expires>?', (args['snapshot'],job['group_id'],self.clock())).fetchone()
                else:
                    snap = c.execute('SELECT * FROM dispatch_query_snapshots WHERE group_id=? AND expires>? ORDER BY created DESC LIMIT 1', (job['group_id'],self.clock())).fetchone()
            if not snap: return [{'type':'text','text':'名單已逾期，請重新查詢未派車名單。'}]+self.menu()
            ids = json.loads(snap['case_ids']); page = args.get('page',snap['next_page']); pages=max(1,math.ceil(len(ids)/10))
            if page > pages: return [{'type':'text','text':'已是最後一頁，可更新名單查看最新狀態。'}]+self.menu(len(unassigned))
            page_ids = set(ids[(page-1)*10:page*10])
            shown = [row for row in unassigned if row['caseId'] in page_ids]
            with self.s['connect']() as c: c.execute('UPDATE dispatch_query_snapshots SET next_page=MAX(next_page,?) WHERE id=?', (page+1,snap['id']))
            return self.cards(shown,len(unassigned),snap['id'],page,pages,queried)
        raise ValueError('query_unavailable')

    def query_once(self):
        with self.query_lock:
            now=self.clock()
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute("UPDATE dispatch_query_events SET state='expired',reply_token='',last_error='reply_expired' WHERE state='pending' AND deadline<=?", (now,))
                row=c.execute("SELECT * FROM dispatch_query_events WHERE state='pending' AND deadline>? ORDER BY created,event_id LIMIT 1", (now,)).fetchone()
                if not row: return {'processed':False,'state':'idle'}
                if not self.available() or not self.group(c,row['group_id']):
                    c.execute("UPDATE dispatch_query_events SET state='cancelled',reply_token='' WHERE event_id=?", (row['event_id'],))
                    return {'processed':True,'state':'cancelled'}
                job=dict(row); c.execute("UPDATE dispatch_query_events SET state='working' WHERE event_id=?", (job['event_id'],))
            try: messages=self.messages(job)
            except Exception: messages=[{'type':'text','text':'查詢暫不可用，請稍後重新查詢。'}]+self.menu()
            # Google I/O above deliberately holds no membership/binding lock.
            with self.s['PICKUP_NOTIFICATION_LOCK']:
                with self.s['connect']() as c:
                    row=c.execute('SELECT state FROM dispatch_query_events WHERE event_id=?', (job['event_id'],)).fetchone()
                    valid=(row and row['state']=='working' and self.available() and self.group(c,job['group_id']) and self.clock()<job['deadline'])
                    if not valid:
                        c.execute("UPDATE dispatch_query_events SET state='expired',reply_token='',last_error='reply_expired' WHERE event_id=? AND state='working'", (job['event_id'],))
                        return {'processed':True,'state':'expired'}
                    c.execute("UPDATE dispatch_query_events SET state='responding',reply_token='' WHERE event_id=? AND state='working'", (job['event_id'],))
                try: result=self.s['send_reply'](self.s['TOKEN'],job['reply_token'],messages)
                except Exception: result=None
                state='accepted' if isinstance(result,dict) and result.get('state')=='accepted' else 'failed'
                with self.s['connect']() as c: c.execute("UPDATE dispatch_query_events SET state=?,last_error=? WHERE event_id=? AND state='responding'", (state,'' if state=='accepted' else 'reply_failed',job['event_id']))
            return {'processed':True,'state':state}

    def configure(self, enabled):
        if type(enabled) is not bool: raise ValueError('invalid_setting')
        with self.s['PICKUP_NOTIFICATION_LOCK']:
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE'); old=c.execute('SELECT * FROM dispatch_workflow_settings WHERE singleton=1').fetchone()
                group=self.group(c)
                if enabled and (not self.available() or not group): raise ValueError('group_unavailable')
                if enabled and old['daily_enabled'] and old['group_id']==group['group_id']: return
                if not enabled:
                    c.execute('UPDATE dispatch_workflow_settings SET daily_enabled=0 WHERE singleton=1')
                    c.execute("UPDATE dispatch_daily_jobs SET state='cancelled' WHERE state IN ('pending','working','ready','failed')")
                    c.execute("UPDATE dispatch_workflow_push SET state='cancelled' WHERE job_key LIKE 'daily:%' AND state IN ('pending','working','failed','needs_review')")
                    return
                local=dt.datetime.fromtimestamp(self.clock(),TAIPEI); target=local.replace(hour=8,minute=0,second=0,microsecond=0)
                if target<=local: target+=dt.timedelta(days=1)
                c.execute('UPDATE dispatch_workflow_settings SET daily_enabled=1,group_id=?,enabled_at=?,first_date=? WHERE singleton=1', (group['group_id'],self.clock(),target.date().isoformat()))
        self.daily_wake.set()

    def schedule_once(self):
        local=dt.datetime.fromtimestamp(self.clock(),TAIPEI); today=local.date().isoformat()
        with self.s['connect']() as c:
            c.execute('BEGIN IMMEDIATE'); setting=c.execute('SELECT * FROM dispatch_workflow_settings WHERE singleton=1').fetchone()
            if not setting['daily_enabled'] or not self.available() or not self.group(c,setting['group_id']): return False
            if local.hour<8 or today<setting['first_date']: return False
            key='daily:'+setting['group_id']+':'+today
            return bool(c.execute('INSERT OR IGNORE INTO dispatch_daily_jobs(job_key,group_id,local_date,created) VALUES(?,?,?,?)', (key,setting['group_id'],today,self.clock())).rowcount)

    def add_push(self,c,key,group,messages,sequence=0):
        c.execute('''INSERT OR IGNORE INTO dispatch_workflow_push(job_key,sequence,group_id,messages,retry_key,created)
            VALUES(?,?,?,?,?,?)''', (key,sequence,group,json.dumps(messages,ensure_ascii=False),str(uuid.uuid4()),self.clock()))

    def menu_push(self,request_id):
        try:
            if not isinstance(request_id,str) or str(uuid.UUID(request_id))!=request_id: raise ValueError('invalid_request')
        except (ValueError,TypeError,AttributeError): raise ValueError('invalid_request') from None
        with self.s['PICKUP_NOTIFICATION_LOCK']:
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE'); group=self.group(c)
                if not self.available() or not group: raise ValueError('group_unavailable')
                self.add_push(c,'menu:'+request_id,group['group_id'],self.menu())
        self.daily_wake.set()

    def prepare_daily_once(self):
        with self.daily_lock:
            now=self.clock()
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute("SELECT * FROM dispatch_daily_jobs WHERE state IN ('pending','failed','working') AND next_attempt<=? ORDER BY created LIMIT 1", (now,)).fetchone()
                if not row: return {'processed':False,'state':'idle'}
                setting=c.execute('SELECT * FROM dispatch_workflow_settings WHERE singleton=1').fetchone()
                if not setting['daily_enabled'] or not self.available() or not self.group(c,row['group_id']) or setting['group_id']!=row['group_id'] or row['local_date']!=dt.datetime.fromtimestamp(now,TAIPEI).date().isoformat():
                    c.execute("UPDATE dispatch_daily_jobs SET state='cancelled' WHERE job_key=?", (row['job_key'],)); return {'processed':True,'state':'cancelled'}
                job=dict(row); c.execute("UPDATE dispatch_daily_jobs SET state='working',next_attempt=? WHERE job_key=?", (now+90,job['job_key']))
            try:
                rows=self.read(self.allowlist()); waiting=[r for r in rows if r['status']=='']
                ids=[r['caseId'] for r in waiting]; snapshot=self.snapshot(job['group_id'],ids)
                queried=dt.datetime.fromtimestamp(self.clock(),TAIPEI).strftime('%Y-%m-%d %H:%M:%S'); pages=max(1,math.ceil(len(waiting)/10))
                batches=[self.cards(waiting[p*10:p*10+10],len(waiting),snapshot,p+1,pages,queried,daily=True) for p in range(pages)]
                with self.s['connect']() as c:
                    c.execute('BEGIN IMMEDIATE'); setting=c.execute('SELECT * FROM dispatch_workflow_settings WHERE singleton=1').fetchone()
                    current=c.execute('SELECT state FROM dispatch_daily_jobs WHERE job_key=?',(job['job_key'],)).fetchone()
                    if not current or current['state']!='working' or not setting['daily_enabled'] or not self.group(c,job['group_id']): return {'processed':True,'state':'cancelled'}
                    for seq,batch in enumerate(batches): self.add_push(c,job['job_key'],job['group_id'],batch,seq)
                    c.execute("UPDATE dispatch_daily_jobs SET state='ready',last_error='' WHERE job_key=?", (job['job_key'],))
                return {'processed':True,'state':'ready'}
            except Exception:
                with self.s['connect']() as c: c.execute("UPDATE dispatch_daily_jobs SET state='failed',attempts=attempts+1,next_attempt=?,last_error='daily_query_failed' WHERE job_key=? AND state='working'", (now+60,job['job_key']))
                return {'processed':True,'state':'failed'}

    def push_once(self):
        with self.push_lock, self.s['PICKUP_NOTIFICATION_LOCK']:
            now=self.clock()
            with self.s['connect']() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute("""SELECT p.* FROM dispatch_workflow_push p WHERE p.state IN ('pending','failed','working') AND p.next_attempt<=?
                    AND NOT EXISTS(SELECT 1 FROM dispatch_workflow_push earlier WHERE earlier.job_key=p.job_key AND earlier.sequence<p.sequence AND earlier.state<>'accepted') ORDER BY p.created,p.job_key,p.sequence LIMIT 1""", (now,)).fetchone()
                if not row: return {'processed':False,'state':'idle'}
                if row['job_key'].startswith('daily:'):
                    setting=c.execute('SELECT * FROM dispatch_workflow_settings WHERE singleton=1').fetchone()
                    daily=c.execute('SELECT local_date FROM dispatch_daily_jobs WHERE job_key=?',(row['job_key'],)).fetchone()
                    if (not setting['daily_enabled'] or setting['group_id']!=row['group_id'] or not daily
                            or daily['local_date']!=dt.datetime.fromtimestamp(now,TAIPEI).date().isoformat()):
                        c.execute("UPDATE dispatch_workflow_push SET state='cancelled' WHERE job_key=? AND state IN ('pending','working','failed','needs_review')",(row['job_key'],))
                        c.execute("UPDATE dispatch_daily_jobs SET state='cancelled' WHERE job_key=? AND state<>'completed'",(row['job_key'],))
                        return {'processed':True,'state':'cancelled'}
                if not self.available() or not self.group(c,row['group_id']):
                    c.execute("UPDATE dispatch_workflow_push SET state='cancelled' WHERE job_key=? AND sequence=?", (row['job_key'],row['sequence'])); return {'processed':True,'state':'cancelled'}
                if row['first_attempt'] and now-row['first_attempt']>=RETRY_SECONDS:
                    c.execute("UPDATE dispatch_workflow_push SET state='needs_review',last_error='retry_window_expired' WHERE job_key=? AND sequence=?", (row['job_key'],row['sequence'])); return {'processed':True,'state':'needs_review'}
                job=dict(row); first=job['first_attempt'] or now; attempts=job['attempts']+1
                c.execute("UPDATE dispatch_workflow_push SET state='working',first_attempt=?,attempts=?,next_attempt=? WHERE job_key=? AND sequence=?", (first,attempts,now+90,job['job_key'],job['sequence']))
            try:
                from line_support import send_group_messages
                result=send_group_messages(self.s['TOKEN'],job['group_id'],json.loads(job['messages']),job['retry_key'])
            except Exception: result={'state':'failed','retryable':True,'ambiguous':True}
            accepted=(isinstance(result,dict) and result.get('state')=='accepted' and type(result.get('httpStatus')) is int and result['httpStatus'] in (200,409) and result.get('retryKey')==job['retry_key'])
            finished=self.clock(); retryable=isinstance(result,dict) and result.get('retryable') is True
            if isinstance(result,dict) and result.get('state')=='accepted' and not accepted: retryable=False
            ambiguous=not isinstance(result,dict) or result.get('ambiguous') is True or (result.get('state')=='accepted' and not accepted)
            state='accepted' if accepted else ('needs_review' if finished-first>=RETRY_SECONDS or not retryable else 'failed')
            next_attempt=0 if state!='failed' else finished+min(3600,30*2**min(attempts-1,7))
            accepted_at=dt.datetime.fromtimestamp(finished,TAIPEI).strftime('%Y-%m-%d %H:%M:%S') if accepted else ''
            with self.s['connect']() as c:
                c.execute("UPDATE dispatch_workflow_push SET state=?,next_attempt=?,last_error=?,accepted_at=? WHERE job_key=? AND sequence=? AND state='working'", (state,next_attempt,'' if accepted else ('push_acceptance_unconfirmed' if ambiguous else 'push_failed'),accepted_at,job['job_key'],job['sequence']))
                if accepted: c.execute("UPDATE dispatch_daily_jobs SET state='completed' WHERE job_key=? AND NOT EXISTS(SELECT 1 FROM dispatch_workflow_push WHERE job_key=? AND state<>'accepted')", (job['job_key'],job['job_key']))
            return {'processed':True,'state':state}

    def status(self):
        with self.s['connect']() as c:
            setting=dict(c.execute('SELECT * FROM dispatch_workflow_settings WHERE singleton=1').fetchone()); group=self.group(c)
            counts={r['state']:r['n'] for r in c.execute('SELECT state,COUNT(*) AS n FROM dispatch_workflow_push GROUP BY state')}
            query_counts={r['state']:r['n'] for r in c.execute('SELECT state,COUNT(*) AS n FROM dispatch_query_events GROUP BY state')}
            daily_counts={r['state']:r['n'] for r in c.execute('SELECT state,COUNT(*) AS n FROM dispatch_daily_jobs GROUP BY state')}
            last=c.execute("SELECT MAX(p.accepted_at) FROM dispatch_workflow_push p JOIN dispatch_daily_jobs d ON d.job_key=p.job_key WHERE p.state='accepted' AND d.state='completed'").fetchone()[0]
            last_menu=c.execute("SELECT MAX(accepted_at) FROM dispatch_workflow_push WHERE state='accepted' AND job_key LIKE 'menu:%'").fetchone()[0]
        effective=bool(setting['daily_enabled'] and self.available() and group and group['group_id']==setting['group_id'])
        next_run=''
        if effective:
            local=dt.datetime.fromtimestamp(self.clock(),TAIPEI); target=local.replace(hour=8,minute=0,second=0,microsecond=0)
            if target<=local: target+=dt.timedelta(days=1)
            if target.date().isoformat()<setting['first_date']: target=dt.datetime.fromisoformat(setting['first_date']+'T08:00:00').replace(tzinfo=TAIPEI)
            next_run=target.strftime('%Y-%m-%d %H:%M:%S')
        return {'available':self.available(),'groupConnected':bool(self.available() and group),'groupName':group['name'] if group else '', 'dailyEnabled':effective,
            'nextRun':next_run,'lastDaily':last or '', 'lastMenu':last_menu or '', 'pushPending':sum(counts.get(k,0) for k in ('pending','working'))+sum(daily_counts.get(k,0) for k in ('pending','working')),
            'failed':counts.get('failed',0)+counts.get('needs_review',0)+daily_counts.get('failed',0)+query_counts.get('failed',0)+query_counts.get('expired',0),
            'queryPending':query_counts.get('pending',0)+query_counts.get('working',0)}

    def start(self):
        if self.started: return
        self.started=True
        with self.s['connect']() as c:
            c.execute("UPDATE dispatch_query_events SET state='expired',reply_token='',last_error='reply_interrupted' WHERE state IN ('working','responding')")
            c.execute("UPDATE dispatch_daily_jobs SET state='pending',next_attempt=0 WHERE state='working'")
            c.execute("UPDATE dispatch_workflow_push SET state='pending',next_attempt=0 WHERE state='working'")
        def query_worker():
            while True:
                try: processed=self.query_once()['processed']
                except Exception: processed=False
                if not processed: self.query_wake.wait(5); self.query_wake.clear()
        def daily_worker():
            while True:
                try: self.schedule_once(); self.prepare_daily_once(); processed=self.push_once()['processed']
                except Exception: processed=False
                if not processed: self.daily_wake.wait(5); self.daily_wake.clear()
        threading.Thread(target=query_worker,name='dispatch-query-replies',daemon=True).start()
        threading.Thread(target=daily_worker,name='dispatch-daily-summary',daemon=True).start()
