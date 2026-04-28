"""
洗衣机状态轮询服务
"""

import asyncio
from typing import Dict, Any, Set, Callable, Optional
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.core.message.components import Plain, At

from .api_client import WasherApiClient
from .subscription import SubscriptionManager


class PollService:
    """洗衣机状态轮询服务
    
    功能:
    1. 持续轮询已订阅用户的洗衣机状态
    2. 检测到空闲时立即通知用户
    3. 支持动态添加/移除轮询目标
    """

    def __init__(
        self,
        api_client: WasherApiClient,
        subscription_mgr: SubscriptionManager,
        send_message_func: Callable,
        default_interval: int = 60,
    ):
        self.api_client = api_client
        self.subscription_mgr = subscription_mgr
        self.send_message = send_message_func
        self.default_interval = default_interval

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._device_states: Dict[str, Dict[int, int]] = {}
        self._pending_notifications: Dict[str, Set[str]] = {}

    def start(self):
        """启动轮询服务"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[Washer] 轮询服务已启动")

    async def stop(self):
        """停止轮询服务"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[Washer] 轮询服务已停止")

    def _get_device_key(self, position_id: str, device_id: int) -> str:
        return f"{position_id}:{device_id}"

    async def _poll_loop(self):
        """轮询循环"""
        while self._running:
            try:
                await self._poll_all_sessions()
                await asyncio.sleep(self.default_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Washer] 轮询异常: {e}")
                await asyncio.sleep(10)

    async def _poll_all_sessions(self):
        """轮询所有会话"""
        enabled_sessions = await self.subscription_mgr.get_all_enabled_sessions()

        for session_id, session_data in enabled_sessions.items():
            try:
                await self._poll_session(session_id, session_data)
            except Exception as e:
                logger.error(f"[Washer] 轮询会话 {session_id} 失败: {e}")

    async def _poll_session(
        self, session_id: str, session_data: Dict[str, Any]
    ):
        """轮询单个会话"""
        subscriptions = session_data.get("subscriptions", {})
        if not subscriptions:
            return

        for user_id, sub in subscriptions.items():
            position_id = sub.get("position_id")
            floor_code = sub.get("floor_code")
            building_filter = sub.get("building_filter", "")
            building_name = sub.get("building_name", "")

            if not position_id or not floor_code:
                continue

            status = await self.api_client.check_floor_status(
                position_id, floor_code, building_filter
            )
            available_devices = status.get("available_devices", [])

            if available_devices:
                await self._notify_user(
                    session_id, user_id, building_name, available_devices
                )

    async def _notify_user(
        self,
        session_id: str,
        user_id: str,
        building_name: str,
        available_devices: list,
    ):
        """通知用户有空闲洗衣机"""
        device_names = [d.name for d in available_devices]
        msg = (
            f"【洗衣机空闲提醒】\n"
            f"位置: {building_name}\n"
            f"空闲洗衣机: {len(available_devices)}台\n"
            f"设备: {', '.join(device_names)}\n"
            f"请尽快前往使用!"
        )

        chain = MessageChain()
        chain.at(user_id)
        chain.message(f"\n{msg}")

        try:
            await self.send_message(session_id, chain)
            logger.info(f"[Washer] 已通知用户 {user_id} 洗衣机空闲")
        except Exception as e:
            logger.error(f"[Washer] 通知用户 {user_id} 失败: {e}")

    async def check_and_notify(
        self, session_id: str, user_id: str, position_id: str, floor_code: str
    ) -> Dict[str, Any]:
        """立即检查并返回结果（用于用户主动查询）"""
        status = await self.api_client.check_floor_status(position_id, floor_code)
        return status
