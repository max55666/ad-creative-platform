"""Shipping terms fixed by original application time, never quote time."""
from datetime import datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))
EFFECTIVE_AT = datetime(2026, 11, 30, tzinfo=TAIPEI)
PICKUP = '由客服派遣物流回收'
LEGACY_VERSION = 'shipping-2026-10-29-v7'
NEW_VERSION = 'shipping-2026-11-30-v8'

def application_time(value=None):
    if value is None:
        return datetime.now(TAIPEI)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('缺少有效的申請時間')
    return value.replace(tzinfo=TAIPEI) if value.tzinfo is None else value.astimezone(TAIPEI)

def policy(value=None):
    modern = application_time(value) >= EFFECTIVE_AT
    return {'version': NEW_VERSION if modern else LEGACY_VERSION,
            'effectiveAt': EFFECTIVE_AT.isoformat(), 'pickupFee': 700 if modern else 350,
            'roundTrip': modern, 'dropoffSelfCollect': modern}

def application_pickup_fee(shipping, created):
    return policy(created)['pickupFee'] if shipping == PICKUP else 0

def stored_pickup_fee(case):
    """Old payment snapshots without a stored rate keep the original 350."""
    if not case.get('pickup'):
        return 0
    fee = case.get('pickupFeeTwd', 350)
    if type(fee) is not int or fee not in (350, 700):
        raise ValueError('案件保存的物流費率不正確')
    return fee
