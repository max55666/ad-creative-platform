"""Small, server-only LINE API helpers.

Secrets are read or used here, never printed, returned in diagnostics, or included
in exception messages. Importing this module does not perform network requests.
"""

import base64
import binascii
import hashlib
import hmac
import http.client
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


_USER_ID = re.compile(r"U[0-9a-f]{32}\Z")
_LINE_ISSUER = "https://access.line.me"
_TIMEOUT = 15
_MAX_JSON_BYTES = 1024 * 1024


def load_private_config(root, data_dir=None):
    """Read line-config.json in the configured runtime; missing file returns {}.

    Keys and values must all be strings. Environment precedence is left to the
    caller. An explicit runtime may be outside the source root; the file must
    remain inside that resolved directory. Invalid content is never echoed.
    """
    try:
        root_path = Path(root).resolve()
        config_dir=(Path(data_dir) if data_dir is not None else root_path/'runtime').resolve()
        path = (config_dir / "line-config.json").resolve()
        if (data_dir is None and not config_dir.is_relative_to(root_path)) or not path.is_relative_to(config_dir):
            raise ValueError("invalid private configuration")
        if not path.exists():
            return {}
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("invalid private configuration")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in data.items()
        ):
            raise ValueError("invalid private configuration")
        return data
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ValueError("LINE private configuration could not be read") from None


def _read_json(response):
    raw = response.read(_MAX_JSON_BYTES + 1)
    if len(raw) > _MAX_JSON_BYTES:
        raise ValueError("response too large")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("invalid response")
    return payload


def verify_id_token(id_token, client_id, nonce=None):
    """Verify a raw LIFF/OAuth ID token with LINE and return verified claims.

    Returns sub, aud, iss, exp, plus name/picture/nonce when present. Raises a
    sanitized ValueError for any invalid token, channel, response, or outage.
    """
    try:
        if not isinstance(id_token, str) or not 1 <= len(id_token) <= 16384:
            raise ValueError("invalid token")
        if not isinstance(client_id, str) or not client_id.isdigit() or len(client_id) > 32:
            raise ValueError("invalid channel")
        form = {"id_token": id_token, "client_id": client_id}
        if nonce is not None:
            if not isinstance(nonce, str) or not nonce or len(nonce) > 1024:
                raise ValueError("invalid nonce")
            form["nonce"] = nonce
        request = urllib.request.Request(
            "https://api.line.me/oauth2/v2.1/verify",
            data=urllib.parse.urlencode(form).encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            claims = _read_json(response)
        expiry = claims.get("exp")
        if (
            not isinstance(claims.get("sub"), str)
            or not _USER_ID.fullmatch(claims["sub"])
            or claims.get("aud") != client_id
            or claims.get("iss") != _LINE_ISSUER
            or isinstance(expiry, bool)
            or not isinstance(expiry, (int, float))
            or not math.isfinite(expiry)
            or not expiry > time.time()
            or (nonce is not None and claims.get("nonce") != nonce)
        ):
            raise ValueError("invalid claims")
        verified = {key: claims[key] for key in ("sub", "aud", "iss", "exp")}
        for key in ("name", "picture", "nonce"):
            if isinstance(claims.get(key), str):
                verified[key] = claims[key]
        return verified
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TypeError, KeyError):
        raise ValueError("LINE identity verification failed") from None


def validate_webhook_signature(raw, signature, messaging_secret):
    """Return whether X-Line-Signature authenticates the unchanged body bytes."""
    if (
        not isinstance(raw, (bytes, bytearray))
        or not isinstance(signature, str)
        or not 1 <= len(signature) <= 128
        or not isinstance(messaging_secret, str)
        or not messaging_secret
    ):
        return False
    try:
        supplied = base64.b64decode(signature.encode("ascii"), validate=True)
        expected = hmac.new(
            messaging_secret.encode("utf-8"), bytes(raw), hashlib.sha256
        ).digest()
        return hmac.compare_digest(expected, supplied)
    except (UnicodeError, ValueError, binascii.Error):
        return False


def inspect_bot(token, expected_basic_id="@694hrgtr"):
    """Validate a Messaging API token's OA identity without sending a message.

    Return only userId/basicId/displayName/chatMode. Raises sanitized ValueError
    for mismatched account, invalid token/response, or network failure.
    """
    try:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("missing token")
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/info",
            headers={"Authorization": "Bearer " + token},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            profile = _read_json(response)
        if (
            profile.get("basicId") != expected_basic_id
            or not isinstance(profile.get("userId"), str)
            or not _USER_ID.fullmatch(profile["userId"])
            or not isinstance(profile.get("displayName"), str)
            or profile.get("chatMode") not in ("chat", "bot")
        ):
            raise ValueError("unexpected official account")
        return {key: profile[key] for key in ("userId", "basicId", "displayName", "chatMode")}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TypeError, KeyError):
        raise ValueError("LINE official account verification failed") from None


def get_profile(token, user_id):
    """Read a stored customer's main profile; never send a message.

    Only return the requested user ID and its nonempty display name. Users who
    blocked the OA, lack consent, or have not friended/contacted it may be
    unavailable. Errors never disclose credentials or upstream response bodies.
    """
    try:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("missing token")
        if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):
            raise ValueError("invalid user")
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/profile/" + user_id,
            headers={"Authorization": "Bearer " + token}, method="GET",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            profile = _read_json(response)
        display_name = profile.get("displayName")
        if (
            profile.get("userId") != user_id
            or not isinstance(display_name, str)
            or not display_name.strip()
            or len(display_name) > 300
        ):
            raise ValueError("invalid profile")
        return {"userId": user_id, "displayName": display_name}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TypeError, KeyError):
        raise ValueError("LINE customer profile is unavailable") from None


def _result(state, retry_key, status=None, request_id=None, error=None):
    return {
        "state": state,
        "httpStatus": status,
        "requestId": request_id,
        "retryKey": retry_key,
        "error": error,
    }


def _safe_request_id(headers, name):
    value = headers.get(name) if headers else None
    if isinstance(value, str) and 1 <= len(value) <= 128 and value.isascii() and value.isprintable():
        return value
    return None


def send_push(token, user_id, case_id, status, retry_key):
    """Send one explicit OA-to-customer notification with an idempotent retry key.

    Returns {state, httpStatus, requestId, retryKey, error}. `accepted` means API
    acceptance, never delivery/read confirmation. HTTP 409 is accepted only when
    LINE includes x-line-accepted-request-id. Failures contain stable categories,
    never response bodies, request bodies, credentials, or exception text.
    """
    try:
        normalized_key = str(uuid.UUID(str(retry_key)))
    except (ValueError, TypeError, AttributeError):
        return _result("failed", None, error="invalid_retry_key")
    if not isinstance(token, str) or not token.strip():
        return _result("failed", normalized_key, error="missing_token")
    if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):
        return _result("failed", normalized_key, error="invalid_recipient")
    if (
        not isinstance(case_id, str) or not 1 <= len(case_id) <= 100
        or not isinstance(status, str) or not 1 <= len(status) <= 100
        or any(char in case_id + status for char in "\r\n")
    ):
        return _result("failed", normalized_key, error="invalid_payload")
    title = "維修申請已受理" if status == "已申請" else "維修進度已更新"
    text = f"{title}\n維修編號：{case_id}\n目前狀態：{status}\n請由維修申請頁查看案件。"
    payload = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    request = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "X-Line-Retry-Key": normalized_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            http_status = response.getcode()
            request_id = _safe_request_id(response.headers, "x-line-request-id")
        if http_status == 200:
            return _result("accepted", normalized_key, http_status, request_id)
        return _result("failed", normalized_key, http_status, request_id, "unexpected_status")
    except urllib.error.HTTPError as error:
        if error.code == 409:
            accepted_id = _safe_request_id(error.headers, "x-line-accepted-request-id")
            if accepted_id:
                return _result("accepted", normalized_key, 409, accepted_id)
        return _result("failed", normalized_key, error.code, error="http_error")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return _result("failed", normalized_key, error="network_error")


def send_reply(token, reply_token, messages):
    """Explicitly reply to a freshly received LINE event; no automatic retries."""
    if not isinstance(token, str) or not token.strip():
        return _result("failed", None, error="missing_token")
    if not isinstance(reply_token, str) or not 1 <= len(reply_token) <= 1024:
        return _result("failed", None, error="invalid_reply_token")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 5 or any(not isinstance(item, dict) for item in messages):
        return _result("failed", None, error="invalid_payload")
    try:
        raw = json.dumps({"replyToken": reply_token, "messages": messages}, ensure_ascii=False).encode("utf-8")
        if len(raw) > 200000:
            return _result("failed", None, error="invalid_payload")
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/message/reply", data=raw,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            http_status = response.getcode()
            request_id = _safe_request_id(response.headers, "x-line-request-id")
        if http_status == 200:
            return _result("accepted", None, http_status, request_id)
        return _result("failed", None, http_status, request_id, "unexpected_status")
    except urllib.error.HTTPError as error:
        return _result("failed", None, error.code, error="http_error")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TypeError):
        return _result("failed", None, error="network_error")


def get_webhook_endpoint(token):
    """Read webhook URL/active state only. HTTP 404 represents an unset URL."""
    try:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("missing token")
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/channel/webhook/endpoint",
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                info = _read_json(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return {"endpoint": "", "active": False}
            raise
        if not isinstance(info.get("endpoint"), str) or not isinstance(info.get("active"), bool):
            raise ValueError("invalid response")
        return {"endpoint": info["endpoint"], "active": info["active"]}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TypeError):
        raise ValueError("LINE webhook status could not be read") from None


def set_webhook_endpoint(token, endpoint):
    """Explicitly set a webhook URL. Does not toggle the console's Use webhook."""
    try:
        if not isinstance(token, str) or not token.strip() or not isinstance(endpoint, str) or len(endpoint) > 500:
            raise ValueError("invalid configuration")
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("invalid URL")
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/channel/webhook/endpoint",
            data=json.dumps({"endpoint": endpoint}).encode("utf-8"),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            if response.getcode() != 200:
                raise ValueError("unexpected status")
        return {"configured": True, "endpoint": endpoint}
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, TypeError):
        raise ValueError("LINE webhook URL could not be configured") from None
