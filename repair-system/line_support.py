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
_GROUP_ID = re.compile(r"C[0-9a-f]{32}\Z")
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


def _valid_group_token(token):
    return (isinstance(token, str) and 1 <= len(token) <= 8192
            and token.isascii() and token.isprintable()
            and not any(character.isspace() for character in token))


def get_group_summary(token, group_id):
    """Read the joined group's identity without sending any message.

    Return only {groupId, groupName}; never return member data or upstream error
    bodies. A missing/inaccessible group raises a sanitized ValueError.
    """
    try:
        if not _valid_group_token(token):
            raise ValueError("invalid token")
        if not isinstance(group_id, str) or not _GROUP_ID.fullmatch(group_id):
            raise ValueError("invalid group")
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/group/" + group_id + "/summary",
            headers={"Authorization": "Bearer " + token}, method="GET",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            if response.getcode() != 200:
                raise ValueError("unexpected status")
            summary = _read_json(response)
        name = summary.get("groupName")
        if (summary.get("groupId") != group_id or not isinstance(name, str)
                or not name.strip() or len(name) > 300
                or any(ord(character) < 32 or ord(character) == 127 for character in name)):
            raise ValueError("invalid group summary")
        name.encode("utf-8")
        return {"groupId": group_id, "groupName": name}
    except (urllib.error.URLError, http.client.HTTPException, OSError,
            UnicodeError, ValueError, TypeError, KeyError):
        raise ValueError("LINE group summary is unavailable") from None


def _group_push_result(state, retry_key, status=None, request_id=None,
                       error=None, retryable=False, ambiguous=False):
    result = _result(state, retry_key, status, request_id, error)
    result.update(retryable=retryable, ambiguous=ambiguous)
    return result


def send_group_text(token, group_id, text, retry_key):
    """Explicitly push one text to an authorized, previously selected group.

    Return the usual push result plus retryable/ambiguous booleans. Acceptance
    means API acceptance, never member delivery/read confirmation. Only 200 or
    409 with x-line-accepted-request-id is accepted. Network errors and 5xx may
    have delivered, so the caller must preserve the identical recipient, text,
    and retry key and retry within 24 hours of the first attempt. This helper
    never retries, creates a key, discovers/selects a group, or logs inputs.
    """
    try:
        normalized_key = str(uuid.UUID(str(retry_key)))
    except (ValueError, TypeError, AttributeError):
        return _group_push_result("failed", None, error="invalid_retry_key")
    if not _valid_group_token(token):
        return _group_push_result("failed", normalized_key, error="invalid_token")
    if not isinstance(group_id, str) or not _GROUP_ID.fullmatch(group_id):
        return _group_push_result("failed", normalized_key, error="invalid_recipient")
    try:
        valid_text = (isinstance(text, str) and bool(text.strip())
                      and 1 <= len(text.encode("utf-16-le")) // 2 <= 5000
                      and not any(ord(character) < 32 and character not in "\r\n\t"
                                  for character in text))
    except UnicodeError:
        valid_text = False
    if not valid_text:
        return _group_push_result("failed", normalized_key, error="invalid_payload")
    try:
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=json.dumps({"to": group_id, "messages": [{"type": "text", "text": text}]},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                     "X-Line-Retry-Key": normalized_key}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            status = response.getcode()
            request_id = _safe_request_id(response.headers, "x-line-request-id")
            accepted_id = _safe_request_id(response.headers, "x-line-accepted-request-id")
        if status == 200:
            return _group_push_result("accepted", normalized_key, status, request_id)
        if status == 409 and accepted_id:
            return _group_push_result("accepted", normalized_key, status, accepted_id)
        return _group_push_result("failed", normalized_key, status, request_id,
                                  "unexpected_status", retryable=status == 429 or 500 <= status < 600,
                                  ambiguous=status == 409 or 500 <= status < 600 or not 400 <= status < 500)
    except urllib.error.HTTPError as error:
        status = error.code
        accepted_id = _safe_request_id(error.headers, "x-line-accepted-request-id")
        error.close()
        if status == 409 and accepted_id:
            return _group_push_result("accepted", normalized_key, status, accepted_id)
        return _group_push_result("failed", normalized_key, status, error="http_error",
                                  retryable=status == 429 or 500 <= status < 600,
                                  ambiguous=status == 409 or 500 <= status < 600)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError,
            UnicodeError, TypeError):
        return _group_push_result("failed", normalized_key, error="network_error",
                                  retryable=True, ambiguous=True)


def _message_units(value, maximum, nonempty=False):
    if (not isinstance(value, str) or nonempty and not value.strip()
            or len(value.encode("utf-16-le")) // 2 > maximum
            or any(ord(char) < 32 and char not in "\r\n\t" for char in value)):
        raise ValueError("invalid message")


def _validate_flex_action(action):
    if not isinstance(action, dict):
        raise ValueError("invalid action")
    _message_units(action.get("label"), 40, True)
    kind = action.get("type")
    if kind == "postback":
        if not {"type", "label", "data"} <= set(action) or not set(action) <= {"type", "label", "data", "displayText"}:
            raise ValueError("invalid action")
        _message_units(action.get("data"), 300, True)
        if "displayText" in action:
            _message_units(action["displayText"], 300, True)
    elif kind == "clipboard":
        if set(action) != {"type", "label", "clipboardText"}:
            raise ValueError("invalid action")
        _message_units(action.get("clipboardText"), 1000, True)
    elif kind == "uri":
        if set(action) != {"type", "label", "uri"}:
            raise ValueError("invalid action")
        uri = action.get("uri")
        _message_units(uri, 1000, True)
        if any(char.isspace() for char in uri):
            raise ValueError("invalid action")
        parsed = urllib.parse.urlsplit(uri)
        if parsed.scheme == "tel":
            if not re.fullmatch(r"tel:\+?[0-9]{8,15}", uri):
                raise ValueError("invalid action")
        elif parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid action")
    else:
        raise ValueError("invalid action")


def _validate_flex_component(component, depth=0):
    if not isinstance(component, dict) or depth > 16:
        raise ValueError("invalid component")
    common = {"type", "margin", "flex", "position", "offsetTop", "offsetBottom", "offsetStart", "offsetEnd"}
    kind = component.get("type")
    if kind == "box":
        allowed = common | {"layout", "contents", "spacing", "paddingAll", "paddingTop", "paddingBottom",
                            "paddingStart", "paddingEnd", "backgroundColor", "borderColor", "borderWidth",
                            "cornerRadius", "width", "height", "justifyContent", "alignItems", "action"}
        if (component.get("layout") not in ("vertical", "horizontal", "baseline")
                or not isinstance(component.get("contents"), list) or not 1 <= len(component["contents"]) <= 50):
            raise ValueError("invalid component")
        for child in component["contents"]:
            _validate_flex_component(child, depth + 1)
    elif kind == "text":
        allowed = common | {"text", "size", "color", "weight", "wrap", "align", "gravity", "maxLines",
                            "lineSpacing", "decoration", "style", "action"}
        _message_units(component.get("text"), 2000, True)
        if "wrap" in component and type(component["wrap"]) is not bool:
            raise ValueError("invalid component")
    elif kind == "button":
        allowed = common | {"action", "style", "height", "color", "gravity"}
        if component.get("style", "link") not in ("link", "primary", "secondary"):
            raise ValueError("invalid component")
        if "action" not in component:
            raise ValueError("invalid component")
    elif kind == "separator":
        allowed = {"type", "margin", "color"}
    else:
        raise ValueError("invalid component")
    if not set(component) <= allowed:
        raise ValueError("invalid component")
    if "action" in component:
        _validate_flex_action(component["action"])
    for key, value in component.items():
        if key in ("contents", "action"):
            continue
        if isinstance(value, str):
            _message_units(value, 2000 if key == "text" else 1000)
        elif type(value) is bool:
            if key != "wrap":
                raise ValueError("invalid component")
        elif type(value) in (int, float):
            if not math.isfinite(value) or not 0 <= value <= 1000:
                raise ValueError("invalid component")
        else:
            raise ValueError("invalid component")


def _validate_flex_container(container):
    if not isinstance(container, dict):
        raise ValueError("invalid container")
    kind = container.get("type")
    if kind == "carousel":
        if (set(container) != {"type", "contents"} or not isinstance(container.get("contents"), list)
                or not 1 <= len(container["contents"]) <= 12):
            raise ValueError("invalid container")
        sizes = set()
        for bubble in container["contents"]:
            if not isinstance(bubble, dict) or bubble.get("type") != "bubble":
                raise ValueError("invalid container")
            _validate_flex_container(bubble)
            sizes.add(bubble.get("size", "mega"))
        if len(sizes) != 1:
            raise ValueError("invalid container")
        limit = 50000
    elif kind == "bubble":
        if (not set(container) <= {"type", "size", "direction", "header", "body", "footer"}
                or not any(key in container for key in ("header", "body", "footer"))
                or container.get("size", "mega") not in ("nano", "micro", "kilo", "mega", "giga")
                or container.get("direction", "ltr") not in ("ltr", "rtl")):
            raise ValueError("invalid container")
        for key in ("header", "body", "footer"):
            if key in container:
                if not isinstance(container[key], dict) or container[key].get("type") != "box":
                    raise ValueError("invalid container")
                _validate_flex_component(container[key])
        limit = 30000
    else:
        raise ValueError("invalid container")
    if len(json.dumps(container, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")) > limit:
        raise ValueError("invalid container")


def _group_messages_bytes(group_id, messages):
    """Local conservative schema for text and standard dispatch Flex messages."""
    if not isinstance(messages, list) or not 1 <= len(messages) <= 5:
        raise ValueError("invalid messages")
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("invalid message")
        if message.get("type") == "text":
            if set(message) != {"type", "text"}:
                raise ValueError("invalid message")
            _message_units(message.get("text"), 5000, True)
        elif message.get("type") == "flex":
            if set(message) != {"type", "altText", "contents"}:
                raise ValueError("invalid message")
            _message_units(message.get("altText"), 1500, True)
            _validate_flex_container(message.get("contents"))
        else:
            raise ValueError("invalid message")
    raw = json.dumps({"to": group_id, "messages": messages}, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > 200000:
        raise ValueError("invalid messages")
    return raw


def send_group_messages(token, group_id, messages, retry_key, opener=None):
    """Explicitly push 1..5 bounded text/Flex messages with one saved retry key.

    Standard dispatch Flex containers/actions are locally checked. Return the
    same sanitized accepted/failed + retryable/ambiguous contract as group text.
    The caller owns the immutable payload and 23-hour retry window. An optional
    callable opener(request, timeout=15) supports offline tests; no automatic
    retry, log, group discovery or UUID generation happens here.
    """
    try:
        normalized_key = str(uuid.UUID(str(retry_key)))
    except (ValueError, TypeError, AttributeError):
        return _group_push_result("failed", None, error="invalid_retry_key")
    if not _valid_group_token(token):
        return _group_push_result("failed", normalized_key, error="invalid_token")
    if not isinstance(group_id, str) or not _GROUP_ID.fullmatch(group_id):
        return _group_push_result("failed", normalized_key, error="invalid_recipient")
    if opener is not None and not callable(opener):
        return _group_push_result("failed", normalized_key, error="invalid_opener")
    try:
        raw = _group_messages_bytes(group_id, messages)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return _group_push_result("failed", normalized_key, error="invalid_payload")
    try:
        request = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push", data=raw,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                     "X-Line-Retry-Key": normalized_key}, method="POST",
        )
        with (opener or urllib.request.urlopen)(request, timeout=_TIMEOUT) as response:
            status = response.getcode()
            request_id = _safe_request_id(response.headers, "x-line-request-id")
            accepted_id = _safe_request_id(response.headers, "x-line-accepted-request-id")
        if status == 200:
            return _group_push_result("accepted", normalized_key, status, request_id)
        if status == 409 and accepted_id:
            return _group_push_result("accepted", normalized_key, status, accepted_id)
        return _group_push_result("failed", normalized_key, status, request_id, "unexpected_status",
                                  retryable=status == 429 or 500 <= status < 600,
                                  ambiguous=status == 409 or 500 <= status < 600 or not 400 <= status < 500)
    except urllib.error.HTTPError as error:
        status = error.code
        accepted_id = _safe_request_id(error.headers, "x-line-accepted-request-id")
        error.close()
        if status == 409 and accepted_id:
            return _group_push_result("accepted", normalized_key, status, accepted_id)
        return _group_push_result("failed", normalized_key, status, error="http_error",
                                  retryable=status == 429 or 500 <= status < 600,
                                  ambiguous=status == 409 or 500 <= status < 600)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError,
            UnicodeError, TypeError):
        return _group_push_result("failed", normalized_key, error="network_error",
                                  retryable=True, ambiguous=True)


def submission_confirmation(case_id, case_data):
    """The initial receipt, using only the server's saved application fields."""
    def one_line(value, fallback):
        return re.sub(r'[\r\n]+', ' ', str(value or fallback)).strip() or fallback
    applicant = one_line(case_data.get('name'), '未提供')
    order = ('無訂單編號／不記得了（保固外付費維修）'
             if case_data.get('orderChoice') == 'missing'
             else one_line(case_data.get('order'), '未提供'))
    shipping = one_line(case_data.get('shipping'), '未提供')
    return (f'【維修申請確認】\n案件編號：{case_id}\n申請人：{applicant}\n訂單編號：{order}'
            f'\n寄送方式：{shipping}'
            '\n\n如需補充資訊，請直接在此聊天室留言並附上案件編號。')


def send_push(token, user_id, case_id, status, retry_key, confirmation_data=None):
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
    if confirmation_data is not None:
        if status != '已申請' or not isinstance(confirmation_data, dict):
            return _result("failed", normalized_key, error="invalid_payload")
        text = submission_confirmation(case_id, confirmation_data)
    else:
        text = f"維修進度已更新\n維修編號：{case_id}\n目前狀態：{status}\n請由維修申請頁查看案件。"
    if len(text) > 5000:
        return _result("failed", normalized_key, error="invalid_payload")
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
