"""无数据库的按天接驳凭证：客户端不能替换服务端核实过的景点坐标。"""
import base64
import hashlib
import hmac
import json
import math
import secrets
import time

from .cities import canonical_city
from .config import Settings
from .schemas import DayPlan

_PROCESS_SECRET = secrets.token_bytes(32)
TOKEN_LIFETIME_SECONDS = 24 * 3600


def _secret(settings: Settings) -> bytes:
    return settings.route_token_secret.encode("utf-8") if settings.route_token_secret else _PROCESS_SECRET


def issue_day_token(day: DayPlan, mode: str, settings: Settings, *, now: int | None = None) -> str | None:
    pairs = []
    for first, second in zip(day.activities, day.activities[1:]):
        if first.poi_id and second.poi_id and first.location and second.location:
            pairs.append({"a": list(first.location), "b": list(second.location),
                          "from": first.title, "to": second.title})
    if not pairs:
        return None
    payload = {"v": 1, "exp": (now if now is not None else int(time.time())) + TOKEN_LIFETIME_SECONDS,
               "day": day.day, "city": day.city, "mode": mode, "pairs": pairs}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=")
    signature = hmac.new(_secret(settings), encoded, hashlib.sha256).hexdigest().encode("ascii")
    return (encoded + b"." + signature).decode("ascii")


def verify_day_token(token: str, settings: Settings, *, now: int | None = None) -> dict:
    try:
        encoded, signature = token.encode("ascii").split(b".", 1)
        expected = hmac.new(_secret(settings), encoded, hashlib.sha256).hexdigest().encode("ascii")
        if not hmac.compare_digest(signature, expected):
            raise ValueError("日程凭证无效")
        raw = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError("日程凭证无效")
        if not isinstance(payload.get("exp"), int) or payload["exp"] < (now if now is not None else int(time.time())):
            raise ValueError("日程凭证已过期，请重新生成行程")
        if canonical_city(payload.get("city", "")) != payload.get("city") or payload.get("mode") not in {"transit", "walking", "driving"}:
            raise ValueError("日程凭证无效")
        if not isinstance(payload.get("day"), int) or not 1 <= payload["day"] <= 14:
            raise ValueError("日程凭证无效")
        pairs = payload.get("pairs")
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 5:
            raise ValueError("日程凭证无效")
        for item in pairs:
            if not isinstance(item, dict) or any(not isinstance(item.get(name), str) or not 1 <= len(item[name]) <= 1000 for name in ("from", "to")):
                raise ValueError("日程凭证无效")
            for key in ("a", "b"):
                location = item.get(key)
                if not isinstance(location, list) or len(location) != 2 or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in location):
                    raise ValueError("日程凭证无效")
                if not 73 <= location[0] <= 135 or not 18 <= location[1] <= 54:
                    raise ValueError("日程凭证无效")
        return payload
    except (UnicodeError, TypeError, KeyError, json.JSONDecodeError, base64.binascii.Error):
        raise ValueError("日程凭证无效") from None
