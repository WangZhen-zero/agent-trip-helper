"""Playwright 专用离线 API 入口：显式忽略开发者真实 .env。"""
from app.config import Settings
from app.main import create_app

# 演示数据不访问网络；不要改成 get_settings()，以免 E2E 误读取本机密钥。
app = create_app(Settings(_env_file=None, demo_mode=True))
