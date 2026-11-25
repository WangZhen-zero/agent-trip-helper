"""未取得国内图片展示授权时，前后端都不应查询或伪造实景图片。"""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.photo_tokens import issue_photo_token


def test_legacy_photo_endpoint_returns_placeholder_without_network(monkeypatch):
    class ForbiddenGateway:
        def __init__(self, *_args):
            raise AssertionError("图片占位不应访问外部服务")

    monkeypatch.setattr("app.main.MCPGateway", ForbiddenGateway)
    config = Settings(_env_file=None, demo_mode=False, route_token_secret="TEST_PHOTO_SIGNING_SECRET")
    token = issue_photo_token([{"id": "poi-1", "name": "测试酒店", "location": [116.403, 39.915]}],
                              "hotel_exterior", config)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/photos/resolve", json={"photo_token": token})
        invalid = client.post("/api/v1/photos/resolve", json={"photo_token": token[:-2] + "xx"})
    assert response.status_code == 200
    assert response.json() == {"photos": {"poi-1": None}, "warnings": []}
    assert invalid.status_code == 422
