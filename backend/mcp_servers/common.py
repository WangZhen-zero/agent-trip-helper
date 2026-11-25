"""MCP 错误信封：业务错误作为脱敏数据返回，不向框架日志抛出原始 HTTP 异常。"""
from pydantic import BaseModel
from app.errors import ProviderError


async def envelope(operation) -> dict:
    try:
        result = await operation
        def encode(value):
            return value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        return {"ok": True, "data": [encode(item) for item in result] if isinstance(result, list) else encode(result)}
    except ProviderError as exc:
        return {"ok": False, "error": {"service": exc.service, "code": exc.code, "message": exc.message}}
    except Exception:
        return {"ok": False, "error": {"service": "MCP", "code": "invalid_response", "message": "工具返回了无法处理的数据"}}
