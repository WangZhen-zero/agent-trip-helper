"""脱敏环境诊断：只报告依赖和配置是否存在，绝不打印 API Key 或完整 .env。"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import sys

from .config import Settings


def package_version(name: str) -> str | None:
    """未安装的包用 null 表示，便于复制诊断结果而不泄露环境内容。"""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="输出旅行助手的脱敏运行环境信息")
    parser.add_argument("--no-env", action="store_true", help="不读取项目根目录 .env，仅检查当前进程环境")
    args = parser.parse_args()
    settings = Settings(_env_file=None) if args.no_env else Settings()
    report = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "packages": {name: package_version(name) for name in ("fastapi", "fastmcp", "httpx", "pydantic", "pydantic-settings", "hello-agents", "openai")},
        "imports": {name: importlib.util.find_spec(name.replace("-", "_")) is not None for name in ("fastmcp", "hello_agents", "openai")},
        "mode": "demo" if settings.demo_mode else "live",
        "configured": {
            "deepseek": bool(settings.deepseek_api_key),
            "amap_web_service": bool(settings.amap_web_service_key),
            "baidu_map": bool(settings.baidu_map_ak),
            "route_token_secret": bool(settings.route_token_secret),
            "railgo_enabled": settings.railgo_enabled,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
