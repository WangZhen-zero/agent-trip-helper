"""图片按需查询凭证：只允许检索已进入行程的真实 POI，不能用浏览器输入替换。"""
import base64
import hashlib
import hmac
import json
import math
import time

from .config import Settings
from .route_tokens import _secret, TOKEN_LIFETIME_SECONDS


def issue_photo_token(items: list[dict], kind: str, settings: Settings, *, now: int | None = None) -> str | None:
    if not items or kind not in {"attraction", "hotel_exterior"}:
        return None
    payload = {"v": 1, "purpose": "photos", "kind": kind,
               "exp": (now if now is not None else int(time.time())) + TOKEN_LIFETIME_SECONDS,
               "items": items}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_secret(settings), encoded, hashlib.sha256).hexdigest().encode("ascii")
    return (encoded + b"." + signature).decode("ascii")


def verify_photo_token(token: str, settings: Settings, *, now: int | None = None) -> dict:
    try:
        encoded, signature = token.encode("ascii").split(b".", 1)
        expected = hmac.new(_secret(settings), encoded, hashlib.sha256).hexdigest().encode("ascii")
        if not hmac.compare_digest(signature, expected):
            raise ValueError("图片凭证无效")
        payload = json.loads(base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4)))
        if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("purpose") != "photos":
            raise ValueError("图片凭证无效")
        if not isinstance(payload.get("exp"), int) or payload["exp"] < (now if now is not None else int(time.time())):
            raise ValueError("图片凭证已过期，请重新生成行程")
        kind, items = payload.get("kind"), payload.get("items")
        if kind not in {"attraction", "hotel_exterior"} or not isinstance(items, list) or not 1 <= len(items) <= (1 if kind == "hotel_exterior" else 6):
            raise ValueError("图片凭证无效")
        ids = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {"id", "name", "location"}:
                raise ValueError("图片凭证无效")
            if any(not isinstance(item[key], str) or not 1 <= len(item[key]) <= 1000 for key in ("id", "name")):
                raise ValueError("图片凭证无效")
            if item["id"] in ids:
                raise ValueError("图片凭证无效")
            ids.add(item["id"])
            location = item["location"]
            if not isinstance(location, list) or len(location) != 2 or any(type(value) not in (int, float) or not math.isfinite(value) for value in location):
                raise ValueError("图片凭证无效")
            if not 73 <= location[0] <= 135 or not 15 <= location[1] <= 54:
                raise ValueError("图片凭证无效")
        return payload
    except (UnicodeError, TypeError, KeyError, json.JSONDecodeError, base64.binascii.Error):
        raise ValueError("图片凭证无效") from None
