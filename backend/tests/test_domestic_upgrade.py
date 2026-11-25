"""国内出发地、天气、交通和对话接口的离线契约测试。"""
from datetime import date, timedelta
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.schemas import TripRequest


def trip_payload():
    return {"origin_city": "北京", "cities": ["西安"],
            "start_date": str(date.today() + timedelta(days=1)),
            "end_date": str(date.today() + timedelta(days=2))}


def test_origin_is_not_destination_and_city_limit_is_one_to_three():
    data = trip_payload()
    assert TripRequest(**data).origin_city == "北京"
    with pytest.raises(ValidationError):
        TripRequest(**{**data, "cities": []})
    with pytest.raises(ValidationError):
        TripRequest(**{**data, "cities": ["西安", "上海", "杭州", "北京"]})
    with pytest.raises(ValidationError):
        TripRequest(**{**data, "cities": ["北京"]})
    with pytest.raises(ValidationError):
        TripRequest(**{**data, "start_date": str(date.today() + timedelta(days=16))})


def test_single_city_single_day_demo_is_valid():
    data = trip_payload()
    data["end_date"] = data["start_date"]
    with TestClient(create_app(Settings(_env_file=None, demo_mode=True))) as client:
        response = client.post("/api/v1/trips/plan/stream", json=data)
    assert response.status_code == 200
    assert '"type":"complete"' in response.text


def test_demo_weather_transport_chat_and_plan_are_offline():
    with TestClient(create_app(Settings(_env_file=None, demo_mode=True))) as client:
        weather = client.post("/api/v1/weather/forecast", json={"city": "西安"})
        assert weather.status_code == 200 and weather.json()["source"] == "演示数据"
        transport = client.post("/api/v1/transport/plan", json={"from": "北京", "to": "西安", "departure_date": trip_payload()["start_date"], "travelers": 2})
        assert transport.status_code == 200 and transport.json()["recommended_id"] == "demo-rail"
        chat = client.post("/api/v1/assistant/chat/stream", json={"messages": [{"role": "user", "content": "预算建议"}]})
        assert chat.status_code == 200 and "event: message" in chat.text
        plan = client.post("/api/v1/trips/plan/stream", json=trip_payload())
        assert plan.status_code == 200 and "event: transport" in plan.text and '"origin"' in plan.text


def test_aviation_catalog_is_static_and_domestic():
    with TestClient(create_app(Settings(_env_file=None, demo_mode=True))) as client:
        response = client.get("/api/v1/aviation/search", params={"q": "北京", "kind": "airport"})
        assert response.status_code == 200
        assert response.json()["airports"] and response.json()["airlines"] == []
        assert "静态" in response.json()["notice"]
