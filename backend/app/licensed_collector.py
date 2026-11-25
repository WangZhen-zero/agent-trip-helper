"""许可网页采集的扩展边界：没有审核通过的来源时禁止发起抓取。"""
from dataclasses import dataclass
from typing import Protocol

from .errors import ProviderError
from .schemas import TransportOption


@dataclass(frozen=True)
class SourceApproval:
    """新增来源必须在代码审查中写明授权与归属，不能由浏览器传入网址。"""
    source_id: str
    allowed_host: str
    license_url: str
    attribution: str


class SchedulePageAdapter(Protocol):
    approval: SourceApproval

    async def collect(self, origin_city: str, destination_city: str,
                      departure_date: str) -> list[TransportOption]: ...


# 尚无已确认允许公开展示且自动采集指定日期国内航班的网页，默认注册表为空。
APPROVED_PAGE_SOURCES: dict[str, SchedulePageAdapter] = {}


async def collect_approved(source_id: str, origin_city: str, destination_city: str,
                           departure_date: str) -> list[TransportOption]:
    adapter = APPROVED_PAGE_SOURCES.get(source_id)
    if adapter is None:
        raise ProviderError("许可采集", "not_approved", "尚无获准自动采集的班次网页来源")
    return await adapter.collect(origin_city, destination_city, departure_date)
