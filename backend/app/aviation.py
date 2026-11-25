"""静态国内航空目录；更新脚本可用 openflights-cached 生成同结构快照，运行期不联网。"""
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[2] / "shared" / "openflights_china.json").read_text(encoding="utf-8"))

def search(query: str, kind: str = "all") -> dict:
    word = query.strip().upper()
    def matches(item: dict) -> bool: return not word or any(word in str(value).upper() for value in item.values())
    return {"source": CATALOG["source"], "notice": CATALOG["notice"],
            "airports": [item for item in CATALOG["airports"] if matches(item)] if kind in {"all", "airport"} else [],
            "airlines": [item for item in CATALOG["airlines"] if matches(item)] if kind in {"all", "airline"} else []}
