"""
洗衣机状态轮询服务
"""

import asyncio
import time
from typing import Dict, Any, Set, Callable, Optional
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.core.message.components import Plain, At

from .api_client import WasherApiClient
from .subscription import SubscriptionManager


class PollService:
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
        self._reminder_tasks: Dict[str, asyncio.Task] = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[Washer] 轮询服务已启动")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for key, task in self._reminder_tasks.items():
            if not task.done():
                task.cancel()
        self._reminder_tasks.clear()
        logger.info("[Washer] 轮询服务已停止")

    async def _poll_loop(self):
        while self._running:
            try:
                await self._check_reminders()
                await asyncio.sleep(self.default_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Washer] 轮询异常: {e}")
                await asyncio.sleep(10)

    async def _check_reminders(self):
        enabled_sessions = await self.subscription_mgr.get_all_enabled_sessions()
        for session_id, session_data in enabled_sessions.items():
            subscriptions = session_data.get("subscriptions", {})
            for user_id, sub in subscriptions.items():
                reminder = await self.subscription_mgr.get_reminder(session_id, user_id)
                if not reminder:
                    continue
                remind_at = reminder.get("remind_at", 0)
                if time.time() >= remind_at:
                    await self._send_reminder(session_id, user_id, sub, reminder)
                    await self.subscription_mgr.remove_reminder(session_id, user_id)

    async def _send_reminder(
        self,
        session_id: str,
        user_id: str,
        subscription: Dict[str, Any],
        reminder: Dict[str, Any],
    ):
        position_id = subscription.get("position_id")
        floor_code = subscription.get("floor_code")
        building_filter = subscription.get("building_filter", "")
        building_name = subscription.get("building_name", "")
        device_name = reminder.get("device_name", "")

        status = await self.api_client.check_floor_status(
            position_id, floor_code, building_filter
        )
        devices = status.get("devices", [])
        available_devices = [d for d in devices if d.is_available]

        chain = MessageChain()
        chain.at(user_id)
        
        if available_devices:
            available_names = [d.name for d in available_devices]
            chain.message(
                f"\n【洗衣机空闲提醒】\n"
                f"位置: {building_name}\n"
                f"空闲洗衣机: {len(available_devices)}台\n"
                f"设备: {', '.join(available_names)}\n"
                f"请尽快前往使用!"
            )
        else:
            chain.message(
                f"\n【洗衣机提醒】\n"
                f"位置: {building_name}\n"
                f"{device_name} 应该已经空闲了，但当前检测到仍在使用\n"
                f"请前往确认或稍后重试 /洗衣机查询"
            )

        try:
            await self.send_message(session_id, chain)
            logger.info(f"[Washer] 已发送定时提醒给用户 {user_id}")
        except Exception as e:
            logger.error(f"[Washer] 发送定时提醒失败: {e}")

    async def schedule_reminder(
        self,
        session_id: str,
        user_id: str,
        device_name: str,
        remaining_seconds: int,
    ):
        remind_at = time.time() + remaining_seconds + 30
        await self.subscription_mgr.set_reminder(
            session_id, user_id, device_name, remind_at
        )
        logger.info(
            f"[Washer] 已为用户 {user_id} 设置定时提醒: {device_name}, "
            f"{remaining_seconds + 30}秒后"
        )
