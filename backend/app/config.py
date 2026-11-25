from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """从项目根目录读取配置；密钥只供后端使用，修改后需重启服务。"""

    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env", env_file_encoding="utf-8", extra="ignore")

    demo_mode: bool = True
    deepseek_api_key: str | None = None
    llm_model_id: str = "deepseek-flash"
    llm_base_url: str = "https://api.deepseek.com"
    amap_web_service_key: str | None = None
    baidu_map_ak: str | None = None
    route_token_secret: str | None = None
    railgo_enabled: bool = True
    provider_timeout_seconds: float = Field(default=12.0, gt=0)
    route_min_interval_seconds: float = Field(default=0.4, ge=0, le=5)
    llm_timeout_seconds: float = Field(default=90.0, gt=0)
    llm_max_tokens: int = Field(default=16384, ge=1024, le=32768)
    trip_timeout_seconds: float = Field(default=300.0, gt=0)
    sse_heartbeat_seconds: float = Field(default=10.0, gt=0)

    def missing_provider_keys(self) -> list[str]:
        expected = {
            "DEEPSEEK_API_KEY": self.deepseek_api_key,
            "AMAP_WEB_SERVICE_KEY": self.amap_web_service_key,
        }
        return [name for name, value in expected.items() if not value]


@lru_cache
def get_settings() -> Settings:
    # 只缓存配置，不缓存用户行程；测试通过显式 Settings(_env_file=None) 隔离真实密钥。
    return Settings()
