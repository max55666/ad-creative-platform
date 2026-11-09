"""Isolated group reporting and bounded payment-refresh deferral tests."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
GROUP='C'+'a'*32
CASE='R20261106-0001'


class Payments:
    ready=True
    reason='payment_sync_pending'
    def is_allowed(self,case): return self.ready
    def dispatch_wait_reason(self,case): return self.reason
    def wake(self): pass


class MemberReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        (root/'server.py').write_text((ROOT/'server.py').read_text(encoding='utf-8'),encoding='utf-8')
        (root/'settings.json').write_text('{}',encoding='utf-8')
        self.env=patch.dict(os.environ,{'REPAIR_MODE':'live','PUBLIC_URL':'https://offline.example'},clear=True)
        self.env.start()
        spec=importlib.util.spec_from_file_location('dispatch_test_'+uuid.uuid4().hex,root/'server.py')
        self.m=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
        self.m.pickup_dispatch_available=lambda:True
        self.m.cloud_settings=lambda:{'googleSheetEndpoint':'offline','googleSheetSecret':'offline','googleSheetId':'offline'}
        self.m.cloud_fingerprint=lambda _: 'offline'
        self.m.PICKUP_DISPATCH_VERIFIED_FINGERPRINT='offline'
        self.m.PAYMENTS=Payments()
        self.m.pickup_dispatch_update=Mock(return_value={'state':'synced','action':'updated'})
        self.m.send_reply=Mock(return_value={'state':'accepted'})
        self.tick=int(time.time()*1000)-1000
        with self.m.connect() as c:
            c.execute('INSERT INTO pickup_notification_groups VALUES(?,?,?,?,?)',(GROUP,'offline',1,1,1))
            c.execute('UPDATE pickup_notification_settings SET group_id=?',(GROUP,))
            data={'shipping':'由客服派遣物流回收','paymentWorkflow':'payment-v1'}
            c.execute('INSERT INTO cases(id,user_id,request_id,data,status,created,history) VALUES(?,?,?,?,?,?,?)',
                (CASE,'U'+'f'*32,'fixture',json.dumps(data),'已申請','2026-11-06','[]'))
            c.execute('INSERT INTO pickup_outbox(case_id,revision,payload,state,synced_at,enrolled_at) VALUES(?,?,?,?,?,?)',
                (CASE,1,'{}','synced','2026-11-07','2026-11-07'))

    def tearDown(self): self.env.stop(); self.temp.cleanup()

    def event(self,actor='U'+'1'*32,kind='postback',group=GROUP):
        self.tick+=1
        value={'type':kind,'webhookEventId':uuid.uuid4().hex,'timestamp':self.tick,
               'source':{'type':'group','groupId':group,'userId':actor},'replyToken':'offline'}
        if kind=='postback': value['postback']={'data':'pv1:dispatch:'+CASE}
        else: value['message']={'type':'text','text':CASE+'已派車'}
        return value

    def job(self):
        with self.m.connect() as c:
            row=c.execute('SELECT * FROM pickup_dispatch_outbox WHERE case_id=?',(CASE,)).fetchone()
            return dict(row) if row else None

    def process(self): return self.m.pickup_dispatch_process_once(case_id=CASE)

    def ready_again(self):
        with self.m.connect() as c: c.execute('UPDATE pickup_dispatch_outbox SET next_attempt=0 WHERE case_id=?',(CASE,))

    def reply(self):
        self.m.WORKFLOW.query_once()
        return json.dumps(self.m.send_reply.call_args.args[2],ensure_ascii=False)

    def test_all_group_members_can_use_postback_and_text_without_case_ownership(self):
        for actor,kind in [('U'+'1'*32,'postback'),('U'+'2'*32,'message'),('U'+'2'*32,'postback')]:
            with self.subTest(actor=actor,kind=kind):
                self.assertTrue(self.m.WORKFLOW.enqueue(self.event(actor,kind)))
                self.assertEqual(self.process()['state'],'completed')
                self.assertIn('已更新派車狀態',self.reply())
        self.assertEqual(self.m.pickup_dispatch_update.call_count,3)

    def test_copied_button_feedback_text_is_understood(self):
        event=self.event(kind='message'); event['message']['text']='將 '+CASE+' 標記為已派車'
        self.assertTrue(self.m.WORKFLOW.enqueue(event))
        self.assertEqual(self.process()['state'],'completed')

    def test_wrong_group_and_private_message_cannot_report(self):
        wrong=self.event(group='C'+'b'*32)
        private=self.event(); private['source']['type']='user'
        for event in (wrong,private): self.assertFalse(self.m.WORKFLOW.enqueue(event))
        self.assertIsNone(self.job()); self.m.pickup_dispatch_update.assert_not_called()

    def test_replay_does_not_create_second_update(self):
        event=self.event(); self.m.WORKFLOW.enqueue(event)
        self.assertEqual(self.process()['state'],'completed')
        self.m.WORKFLOW.enqueue(event)
        self.assertEqual(self.process()['state'],'idle')
        self.assertEqual(self.m.pickup_dispatch_update.call_count,1)

    def test_enrolled_pending_payment_is_deferred_then_updates_once(self):
        self.m.PAYMENTS.ready=False
        self.assertTrue(self.m.WORKFLOW.enqueue(self.event(actor='U'+'2'*32)))
        self.assertGreater(self.job()['payment_wait_until'],time.time())
        text=self.reply()
        self.assertIn('回報已收到',text); self.assertIn('會自動更新',text)
        self.assertNotIn('不在已自動加入',text)
        self.m.pickup_dispatch_update.assert_not_called()
        self.m.PAYMENTS.ready=True; self.ready_again()
        self.assertEqual(self.process()['state'],'completed')
        self.assertEqual(self.process()['state'],'idle')
        self.assertEqual(self.m.pickup_dispatch_update.call_count,1)

    def test_wait_has_fixed_deadline_and_expiry_cannot_release_even_if_now_paid(self):
        self.m.PAYMENTS.ready=False; self.m.WORKFLOW.enqueue(self.event())
        deadline=self.job()['payment_wait_until']
        for _ in range(2):
            self.ready_again(); self.assertEqual(self.process()['state'],'payment_verification_pending')
            self.assertEqual(self.job()['payment_wait_until'],deadline)
        with self.m.connect() as c:
            c.execute('UPDATE pickup_dispatch_outbox SET payment_wait_until=?,next_attempt=0',(time.time()-1,))
        self.m.PAYMENTS.ready=True
        self.assertEqual(self.process()['state'],'cancelled')
        self.assertEqual(self.job()['last_error'],'payment_wait_expired')
        self.m.pickup_dispatch_update.assert_not_called()

    def test_refund_or_unpaid_while_waiting_cancels(self):
        self.m.PAYMENTS.ready=False; self.m.WORKFLOW.enqueue(self.event())
        self.m.PAYMENTS.reason=''; self.ready_again()
        self.assertEqual(self.process()['state'],'cancelled')
        self.m.pickup_dispatch_update.assert_not_called()

    def test_cancelled_case_while_waiting_cancels(self):
        self.m.PAYMENTS.ready=False; self.m.WORKFLOW.enqueue(self.event())
        with self.m.connect() as c: c.execute("UPDATE cases SET status='已取消' WHERE id=?",(CASE,))
        self.ready_again(); self.assertEqual(self.process()['state'],'cancelled')
        self.m.pickup_dispatch_update.assert_not_called()

    def test_changed_shipping_or_group_cannot_finish_deferred_report(self):
        for change in ('shipping','group'):
            with self.subTest(change=change):
                self.m.PAYMENTS.ready=False
                self.m.WORKFLOW.enqueue(self.event())
                with self.m.connect() as c:
                    if change=='shipping':
                        c.execute('UPDATE cases SET data=? WHERE id=?',(json.dumps({'shipping':'自行寄送','paymentWorkflow':'payment-v1'}),CASE))
                    else: c.execute("UPDATE pickup_notification_groups SET active=0 WHERE group_id=?",(GROUP,))
                self.ready_again(); self.assertEqual(self.process()['state'],'cancelled')
                with self.m.connect() as c:
                    c.execute('UPDATE cases SET data=? WHERE id=?',(json.dumps({'shipping':'由客服派遣物流回收','paymentWorkflow':'payment-v1'}),CASE))
                self.m.pickup_dispatch_update.assert_not_called()

    def test_unknown_or_unenrolled_case_never_waits(self):
        with self.m.connect() as c: c.execute('DELETE FROM pickup_outbox')
        self.m.PAYMENTS.ready=False
        self.m.WORKFLOW.enqueue(self.event())
        self.assertIsNone(self.job()); self.assertIn('不在已自動加入',self.reply())

    def test_known_permanent_hold_has_specific_feedback_without_queue(self):
        self.m.PAYMENTS.ready=False; self.m.PAYMENTS.reason=''
        self.m.WORKFLOW.enqueue(self.event())
        self.assertIsNone(self.job()); self.assertIn('付款或案件狀態不允許',self.reply())
        self.m.pickup_dispatch_update.assert_not_called()

    def test_final_guard_refresh_race_defers_without_write(self):
        self.m.WORKFLOW.enqueue(self.event())
        with patch.object(self.m,'pickup_cases_allowed',return_value=False):
            self.assertEqual(self.process()['state'],'payment_verification_pending')
        self.m.pickup_dispatch_update.assert_not_called()
        self.ready_again(); self.assertEqual(self.process()['state'],'completed')

    def test_payment_finishes_during_wait_classification_is_not_blocked(self):
        self.m.PAYMENTS.is_allowed=Mock(side_effect=[False,True])
        self.m.PAYMENTS.reason=''
        with self.m.connect() as c:
            case=dict(c.execute('SELECT * FROM cases WHERE id=?',(CASE,)).fetchone())
            self.assertEqual(self.m.pickup_dispatch_gate(case,c),'ready')


if __name__=='__main__': unittest.main()
