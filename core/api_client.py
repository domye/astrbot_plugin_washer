"""
洗衣机 API 客户端
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import httpx
from astrbot.api import logger


@dataclass
class WasherDevice:
    id: int
    name: str
    imei: str
    floor_code: str
    state: int
    enable_reserve: bool
    reserve_state: int
    last_maintenance_time: Optional[str]
    finish_time: Optional[str]
    device_id: int

    @property
    def is_available(self) -> bool:
        return self.state in (0, 2)

    @property
    def status_text(self) -> str:
        if self.state == 0:
            return "空闲"
        elif self.state == 1:
            return "使用中"
        elif self.state == 2:
            return "已完成"
        else:
            return f"状态{self.state}"


class WasherApiClient:
    """海尔洗衣机 API 客户端"""

    API_URL = "https://yshz-user.haier-ioc.com/position/deviceDetailPage"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_devices(
        self,
        position_id: str,
        floor_code: str,
        page: int = 1,
        page_size: int = 30,
    ) -> List[WasherDevice]:
        """获取指定位置的洗衣机列表"""
        try:
            client = await self._get_client()
            payload = {
                "positionId": position_id,
                "categoryCode": "00",
                "page": page,
                "floorCode": floor_code,
                "pageSize": page_size,
            }
            resp = await client.post(self.API_URL, json=payload)
            if resp.status_code != 200:
                logger.warning(f"[Washer] API 返回状态码: {resp.status_code}")
                return []

            data = resp.json()
            devices = []
            for item in data.get("data", {}).get("items", []):
                devices.append(
                    WasherDevice(
                        id=item.get("id", 0),
                        name=item.get("name", ""),
                        imei=item.get("imei", ""),
                        floor_code=item.get("floorCode", ""),
                        state=item.get("state", -1),
                        enable_reserve=item.get("enableReserve", False),
                        reserve_state=item.get("reserveState", 0),
                        last_maintenance_time=item.get("lastMaintenanceTime"),
                        finish_time=item.get("finishTime"),
                        device_id=item.get("deviceId", 0),
                    )
                )
            return devices
        except Exception as e:
            logger.error(f"[Washer] 获取洗衣机列表失败: {e}")
            return []

    async def check_floor_status(
        self, position_id: str, floor_code: str, building_filter: str = ""
    ) -> Dict[str, Any]:
        """检查楼层洗衣机状态
        
        Args:
            position_id: 位置ID
            floor_code: 楼层代码
            building_filter: 楼栋过滤，如 "J1"、"H3" 等
        
        返回:
        {
            "total": 总数,
            "available": 空闲数量,
            "devices": [WasherDevice, ...],
            "available_devices": [空闲设备列表]
        }
        """
        devices = await self.get_devices(position_id, floor_code)
        
        if building_filter:
            building_filter_upper = building_filter.upper()
            devices = [d for d in devices if building_filter_upper in d.name.upper()]
        
        available_devices = [d for d in devices if d.is_available]
        return {
            "total": len(devices),
            "available": len(available_devices),
            "devices": devices,
            "available_devices": available_devices,
        }
