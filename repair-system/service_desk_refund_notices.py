"""Order-once refund notices, backed by authenticated internal refund evidence.

The shared durable delivery engine uses independent wb_refund_notice_* tables.
Operationally refunded means SHOPLINE refunding or refunded; partial refunds do
not qualify. The original provider value remains in the reconciliation ledger.
"""
import json

from service_desk_receipts import ServiceDeskReceipts, _json


class ServiceDeskRefundNotices(ServiceDeskReceipts):
    OUTBOX = 'wb_refund_notice_outbox'
    META = 'wb_refund_notice_meta'
    SEND_METHOD = 'send_refund_notice'
    PAYMENT_STATUS = '已退款'

    @staticmethod
    def _same_payload(current, saved):
        try:
            previous = json.loads(saved)
            if type(previous) is not dict:
                return False
            # Provider progress from refunding to refunded changes audit facts,
            # not the customer message or its original retry UUID/payload.
            return _json({key: value for key, value in current.items() if key != 'providerStatus'}) == _json(
                {key: value for key, value in previous.items() if key != 'providerStatus'})
        except (ValueError, TypeError):
            return False

    def _refund_current(self, case_id, *, baseline=False):
        receipt, reason = super()._current(case_id)
        if receipt is None:
            return None, reason
        with self._db() as c:
            names = {row['name'] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'wb_real_order_checks', 'wb_refund_followups'} <= names:
                return None, 'invalid_payment_proof'
            bound = c.execute('''SELECT order_id,order_number FROM wb_real_order_checks
                WHERE case_id=? AND quote_id=? AND quote_version=? AND order_number=?
                AND outcome='matched_internal_only' ''', (case_id, receipt['id'],
                    receipt['version'], receipt['orderNumber'])).fetchall()
            if len(bound) != 1:
                return None, 'invalid_payment_proof'
            followup = c.execute('''SELECT * FROM wb_refund_followups WHERE case_id=?
                AND quote_id=? AND order_id=? AND order_number=?''',
                (case_id, receipt['id'], bound[0]['order_id'], receipt['orderNumber'])).fetchone()
            if followup is None or followup['provider_status'] not in ('refunding', 'refunded'):
                return None, 'not_refunded'
            # A sticky business hold alone is insufficient to send a notice:
            # regular delivery needs the latest exact-order provider observation.
            # Baseline enrollment may read the preserved refund observation so
            # an older hold cannot be accidentally backfilled after restart.
            if baseline:
                observation = c.execute('''SELECT * FROM wb_real_order_checks WHERE id=?
                    AND case_id=? AND quote_id=? AND order_id=? AND order_number=?''',
                    (followup['observation_check_id'], case_id, receipt['id'],
                     bound[0]['order_id'], receipt['orderNumber'])).fetchone()
            else:
                observation = c.execute('''SELECT * FROM wb_real_order_checks WHERE case_id=?
                    AND quote_id=? AND quote_version=? AND order_id=? AND order_number=?
                    ORDER BY rowid DESC LIMIT 1''', (case_id, receipt['id'], receipt['version'],
                        bound[0]['order_id'], receipt['orderNumber'])).fetchone()
        if observation is None:
            return None, 'invalid_payment_proof'
        try:
            response = json.loads(observation['response'])
            result, facts = response['result'], response['result']['facts']
            if (any(response.get(key) is not value for key, value in
                    (('internalOnly', True), ('simulation', False), ('readOnly', True),
                     ('realPayment', False), ('releaseAllowed', False)))
                    or response.get('source') != 'shopline_api_observation'
                    or response.get('quoteId') != receipt['id']
                    or response.get('orderNumber') != receipt['orderNumber']
                    or result.get('state') != 'blocked' or 'refunded' not in result.get('reasons', [])
                    or facts.get('freshProviderLookup') is not True or facts.get('currentQuote') is not True
                    or type(facts.get('quoteVersion')) is not int or facts['quoteVersion'] != receipt['version']
                    or facts.get('providerPaymentStatus') not in ('refunding', 'refunded')
                    or facts['providerPaymentStatus'] != followup['provider_status']
                    or followup['observation_check_id'] != observation['id']):
                return None, 'not_refunded'
        except (ValueError, TypeError, KeyError):
            return None, 'invalid_payment_proof'
        return {**receipt, 'source': 'shopline_api_refund',
                'providerStatus': facts['providerPaymentStatus']}, ''

    def _current(self, case_id):
        return self._refund_current(case_id)

    def _baseline_current(self, case_id):
        return self._refund_current(case_id, baseline=True)

    def status(self):
        state = super().status()
        with self._db() as c:
            tables = {row['name'] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows = c.execute('SELECT quote_id,order_number,provider_status FROM wb_refund_followups').fetchall() if 'wb_refund_followups' in tables else []
        statuses = {(row['quote_id'], row['order_number']): row['provider_status'] for row in rows
                    if row['provider_status'] in ('refunding', 'refunded', 'partially_refunded')}
        for row in state['quotes']:
            row['providerStatus'] = statuses.get((row['quoteId'], row['orderNumber']), '')
        return state
