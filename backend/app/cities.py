"""读取前后端共用的城市级目的地名录；不把县区、景点或模糊地址当作城市。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[2] / "shared" / "china_cities.json"


@lru_cache
def city_catalog() -> dict[str, str]:
    """返回“可接受写法 -> 规范城市名”的映射，值同时可反查省份。"""
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog: dict[str, str] = {}
    for province in data["provinces"]:
        for city in province["cities"]:
            catalog[city] = city
            catalog[city.removesuffix("市")] = city
            # 自治州、盟和地区常用简称与正式名称不同，搜索/手输都应接受常见前缀。
            for suffix in ("自治州", "地区", "盟", "林区"):
                if suffix in city:
                    prefix = city.split(suffix, 1)[0]
                    catalog[prefix] = city
                    # 民族自治州的城市名通常是开头两个汉字，例如“大理”“恩施”。
                    if "自治州" in city and len(city) >= 2:
                        catalog[city[:2]] = city
    return catalog


@lru_cache
def province_for(city: str) -> str:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for province in data["provinces"]:
        if city in province["cities"]:
            return province["name"]
    raise KeyError(city)


def canonical_city(value: str) -> str | None:
    """规范化用户输入；返回 None 即不是本应用支持的中国大陆城市级目的地。"""
    compact = "".join(value.split())
    return city_catalog().get(compact) or city_catalog().get(compact.removesuffix("市"))
