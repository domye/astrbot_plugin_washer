"""
洗衣机订阅管理器
"""

import os
import json
import copy
import asyncio
from typing import Dict, Any, Optional, List, Set
from astrbot.api import logger


class AsyncDataManager:
    """通用异步 JSON 数据管理器"""

    def __init__(self, data_dir: str, filename: str, default_data: Any):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, filename)
        self.default_data = default_data
        self.lock = asyncio.Lock()
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        self.data = self._load()

    def _load(self) -> Any:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[Washer] 加载 {self.path} 失败: {e}")
        return copy.deepcopy(self.default_data)

    async def _save(self):
        try:
            temp_path = self.path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.path)
        except Exception as e:
            logger.error(f"[Washer] 保存 {self.path} 失败: {e}")


class SubscriptionManager(AsyncDataManager):
    """洗衣机订阅管理器
    
    数据结构:
    {
        "session_id": {
            "subscriptions": {
                "user_id": {
                    "position_id": "9283",
                    "floor_code": "05",
                    "building_name": "C栋5楼"
                }
            },
            "poll_enabled": bool,
            "poll_interval": int
        }
    }
    """

    def __init__(self, data_dir: str):
        super().__init__(data_dir, "washer_subscriptions.json", {})

    async def get_user_subscription(
        self, session_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        async with self.lock:
            session_data = self.data.get(str(session_id), {})
            subscriptions = session_data.get("subscriptions", {})
            return copy.deepcopy(subscriptions.get(str(user_id)))

    async def set_user_subscription(
        self,
        session_id: str,
        user_id: str,
        position_id: str,
        floor_code: str,
        building_name: str,
        building_filter: str = "",
    ) -> None:
        async with self.lock:
            sid = str(session_id)
            uid = str(user_id)
            if sid not in self.data:
                self.data[sid] = {
                    "subscriptions": {},
                    "poll_enabled": True,
                    "poll_interval": 60,
                }
            if "subscriptions" not in self.data[sid]:
                self.data[sid]["subscriptions"] = {}
            self.data[sid]["subscriptions"][uid] = {
                "position_id": position_id,
                "floor_code": floor_code,
                "building_name": building_name,
                "building_filter": building_filter,
            }
            await self._save()

    async def remove_user_subscription(
        self, session_id: str, user_id: str
    ) -> bool:
        async with self.lock:
            sid = str(session_id)
            uid = str(user_id)
            if sid not in self.data:
                return False
            subscriptions = self.data[sid].get("subscriptions", {})
            if uid in subscriptions:
                del subscriptions[uid]
                await self._save()
                return True
            return False

    async def get_all_subscriptions(
        self, session_id: str
    ) -> Dict[str, Dict[str, Any]]:
        async with self.lock:
            session_data = self.data.get(str(session_id), {})
            return copy.deepcopy(session_data.get("subscriptions", {}))

    async def get_all_sessions(self) -> Set[str]:
        async with self.lock:
            return set(self.data.keys())

    async def get_session_config(
        self, session_id: str
    ) -> Dict[str, Any]:
        async with self.lock:
            session_data = self.data.get(str(session_id), {})
            return {
                "poll_enabled": session_data.get("poll_enabled", True),
                "poll_interval": session_data.get("poll_interval", 60),
            }

    async def set_session_poll_config(
        self, session_id: str, enabled: bool, interval: int = 60
    ) -> None:
        async with self.lock:
            sid = str(session_id)
            if sid not in self.data:
                self.data[sid] = {
                    "subscriptions": {},
                    "poll_enabled": enabled,
                    "poll_interval": interval,
                }
            else:
                self.data[sid]["poll_enabled"] = enabled
                self.data[sid]["poll_interval"] = interval
            await self._save()

    async def get_all_enabled_sessions(self) -> Dict[str, Dict[str, Any]]:
        async with self.lock:
            result = {}
            for sid, session_data in self.data.items():
                if session_data.get("poll_enabled", True) and session_data.get(
                    "subscriptions"
                ):
                    result[sid] = {
                        "subscriptions": copy.deepcopy(
                            session_data.get("subscriptions", {})
                        ),
                        "poll_interval": session_data.get("poll_interval", 60),
                    }
            return result
