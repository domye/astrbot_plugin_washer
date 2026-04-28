"""
公共洗衣机订阅插件

功能:
1. /洗衣机订阅 <位置ID> <楼层> <名称> - 订阅指定楼层洗衣机
2. /洗衣机查询 - 查询当前订阅楼层洗衣机状态
3. /洗衣机取消 - 取消订阅
4. /洗衣机列表 - 查看订阅列表
5. 后台持续轮询，有空位时自动@通知

位置ID映射示例:
- 9283: A/B/C栋
- 9284: D/E栋
"""

import asyncio
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.core.message.components import Plain, At

from .core.subscription import SubscriptionManager
from .core.api_client import WasherApiClient
from .core.poll_service import PollService


POSITION_MAP = {
    "A": "9283",
    "B": "9283",
    "C": "9283",
    "D": "9283",
    "E": "9283",
    "F": "9283",
    "G": "9284",
    "H": "9284",
    "I": "9284",
    "J": "9284",
    "K": "9284",
    "L": "9284",
}

FLOOR_CODE_MAP = {
    "1": "01",
    "2": "02",
    "3": "03",
    "4": "04",
    "5": "05",
    "6": "06",
}


@register(
    "astrbot_plugin_washer",
    "domye",
    "公共洗衣机订阅通知",
    "1.0.0",
    "https://github.com/astrbot/astrbot_plugin_washer"
)
class WasherPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

        data_dir = str(StarTools.get_data_dir())
        self.subscription_mgr = SubscriptionManager(data_dir)
        self.api_client = WasherApiClient()

        poll_interval = self.config.get("poll_interval", 60)
        self.poll_service = PollService(
            api_client=self.api_client,
            subscription_mgr=self.subscription_mgr,
            send_message_func=self._send_message,
            default_interval=poll_interval,
        )

        logger.info("[Washer] 插件初始化完成")

    async def initialize(self):
        self.poll_service.start()
        logger.info("[Washer] 轮询服务已启动")

    async def terminate(self):
        await self.poll_service.stop()
        await self.api_client.close()
        logger.info("[Washer] 插件已终止")

    async def _send_message(self, session_id: str, chain: MessageChain):
        await self.context.send_message(session_id, chain)

    def _parse_location(self, location_str: str) -> Optional[tuple]:
        """解析位置字符串，返回 (position_id, floor_code, display_name, building_filter)
        
        支持格式:
        - A西5楼 -> 订阅 A 栋西边 5 楼
        - J1西4楼 -> 精确订阅 J1 西边 4 楼
        - J14楼 -> 订阅 J1 栋 4 楼
        - J4 -> 订阅 J 栋 4 楼（所有 J1/J2/J3）
        """
        import re
        location = location_str.strip().upper()
        
        match = re.match(r"([A-L])(\d)?([东西])?(\d+)楼?", location)
        if match:
            building = match.group(1)
            building_num = match.group(2)
            direction = match.group(3) or ""
            floor = match.group(4)
        else:
            match = re.match(r"([A-L])(\d)?(\d+)", location)
            if match:
                building = match.group(1)
                building_num = match.group(2)
                direction = ""
                floor = match.group(3)
            else:
                return None

        position_id = POSITION_MAP.get(building)
        floor_code = FLOOR_CODE_MAP.get(floor, floor.zfill(2))

        if not position_id:
            return None

        building_filter = ""
        if building_num or direction:
            building_filter = f"{building}{building_num or ''}{direction}"
            display_name = f"{building}{building_num or ''}{direction}栋{floor}楼"
        else:
            display_name = f"{building}栋{floor}楼"

        return (position_id, floor_code, display_name, building_filter)

    @filter.command("洗衣机订阅")
    async def subscribe(self, event: AstrMessageEvent, location: str = ""):
        """订阅洗衣机通知
        
        用法: 
        /洗衣机订阅 J1西4楼 - 订阅 J1 西边 4 楼
        /洗衣机订阅 J14楼 - 订阅 J1 栋 4 楼
        /洗衣机订阅 J4 - 订阅 J 栋 4 楼所有洗衣机
        """
        if not location:
            yield event.plain_result(
                "请输入位置，例如:\n"
                "/洗衣机订阅 J1西4楼\n"
                "/洗衣机订阅 J14楼\n"
                "/洗衣机订阅 J4"
            )
            return

        parsed = self._parse_location(location)
        if not parsed:
            yield event.plain_result(
                "位置格式错误，支持:\n"
                "A-L栋，楼层1-6\n"
                "例如: J1西4楼 或 J4"
            )
            return

        position_id, floor_code, display_name, building_filter = parsed
        session_id = event.unified_msg_origin
        user_id = event.get_sender_id()

        await self.subscription_mgr.set_user_subscription(
            session_id, user_id, position_id, floor_code, display_name, building_filter
        )

        status = await self.api_client.check_floor_status(position_id, floor_code, building_filter)
        total = status.get("total", 0)
        available = status.get("available", 0)

        msg = (
            f"订阅成功!\n"
            f"位置: {display_name}\n"
            f"洗衣机总数: {total}台\n"
            f"当前空闲: {available}台\n"
            f"当有空闲洗衣机时会自动@通知你"
        )
        yield event.plain_result(msg)

    @filter.command("洗衣机查询")
    async def query(self, event: AstrMessageEvent):
        """查询订阅位置的洗衣机状态"""
        session_id = event.unified_msg_origin
        user_id = event.get_sender_id()

        sub = await self.subscription_mgr.get_user_subscription(session_id, user_id)
        if not sub:
            yield event.plain_result("你还没有订阅，请先使用 /洗衣机订阅 <位置> 订阅")
            return

        position_id = sub.get("position_id")
        floor_code = sub.get("floor_code")
        building_name = sub.get("building_name", "")
        building_filter = sub.get("building_filter", "")

        status = await self.api_client.check_floor_status(position_id, floor_code, building_filter)
        devices = status.get("devices", [])
        total = status.get("total", 0)
        available = status.get("available", 0)

        if not devices:
            yield event.plain_result(f"位置 {building_name} 暂无洗衣机数据")
            return

        lines = [
            f"【{building_name}洗衣机状态】",
            f"总数: {total}台 | 空闲: {available}台",
            "",
        ]

        for device in devices:
            status_icon = "✅" if device.is_available else "❌"
            lines.append(f"{status_icon} {device.name}: {device.status_text}")

        yield event.plain_result("\n".join(lines))

    @filter.command("洗衣机取消")
    async def unsubscribe(self, event: AstrMessageEvent):
        """取消订阅"""
        session_id = event.unified_msg_origin
        user_id = event.get_sender_id()

        removed = await self.subscription_mgr.remove_user_subscription(session_id, user_id)
        if removed:
            yield event.plain_result("已取消订阅")
        else:
            yield event.plain_result("你还没有订阅")

    @filter.command("洗衣机列表")
    async def list_subscriptions(self, event: AstrMessageEvent):
        """查看当前群的所有订阅"""
        session_id = event.unified_msg_origin
        subscriptions = await self.subscription_mgr.get_all_subscriptions(session_id)

        if not subscriptions:
            yield event.plain_result("当前群暂无订阅")
            return

        lines = ["【洗衣机订阅列表】", ""]
        for user_id, sub in subscriptions.items():
            building_name = sub.get("building_name", "")
            lines.append(f"用户 {user_id}: {building_name}")

        yield event.plain_result("\n".join(lines))

    @filter.command("洗衣机帮助")
    async def help_cmd(self, event: AstrMessageEvent):
        """查看帮助"""
        msg = (
            "【洗衣机订阅插件帮助】\n"
            "\n"
            "/洗衣机订阅 <位置> - 订阅洗衣机通知\n"
            "  精确订阅: A西5楼 / J1西4楼 / J14楼\n"
            "  整栋订阅: A5 / J4\n"
            "  支持楼栋: A-L栋\n"
            "\n"
            "/洗衣机查询 - 查询订阅位置状态\n"
            "/洗衣机取消 - 取消订阅\n"
            "/洗衣机列表 - 查看群订阅列表\n"
            "\n"
            "订阅后，当有空闲洗衣机时会自动@通知你"
        )
        yield event.plain_result(msg)

    @filter.command("洗衣机设置")
    async def settings(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """管理员设置（轮询间隔等）"""
        if not await self._is_admin(event):
            yield event.plain_result("仅管理员可执行此操作")
            return

        session_id = event.unified_msg_origin

        if action == "间隔":
            try:
                interval = int(value)
                if interval < 30:
                    yield event.plain_result("轮询间隔最少30秒")
                    return
                await self.subscription_mgr.set_session_poll_config(
                    session_id, True, interval
                )
                yield event.plain_result(f"已设置轮询间隔: {interval}秒")
            except ValueError:
                yield event.plain_result("请输入有效的数字，例如: /洗衣机设置 间隔 60")
        elif action == "开启":
            await self.subscription_mgr.set_session_poll_config(session_id, True)
            yield event.plain_result("已开启自动通知")
        elif action == "关闭":
            await self.subscription_mgr.set_session_poll_config(session_id, False)
            yield event.plain_result("已关闭自动通知")
        else:
            config = await self.subscription_mgr.get_session_config(session_id)
            msg = (
                "【洗衣机设置】\n"
                f"自动通知: {'开启' if config.get('poll_enabled', True) else '关闭'}\n"
                f"轮询间隔: {config.get('poll_interval', 60)}秒\n"
                "\n"
                "命令:\n"
                "/洗衣机设置 开启 - 开启自动通知\n"
                "/洗衣机设置 关闭 - 关闭自动通知\n"
                "/洗衣机设置 间隔 <秒> - 设置轮询间隔"
            )
            yield event.plain_result(msg)

    async def _is_admin(self, event: AstrMessageEvent) -> bool:
        if event.is_admin():
            return True
        if event.is_private_chat():
            return False
        sender_id = str(event.get_sender_id())
        role = str(getattr(event, "role", "") or "").lower()
        try:
            group = await event.get_group()
            if group:
                owner_candidates = [
                    getattr(group, "group_owner", None),
                    getattr(group, "owner_id", None),
                    getattr(group, "group_owner_id", None),
                ]
                if any(str(owner) == sender_id for owner in owner_candidates if owner):
                    return True
                admins = [str(x) for x in getattr(group, "group_admins", [])]
                if sender_id in admins:
                    return True
                if role in {"admin", "owner"}:
                    return True
        except Exception:
            if role in {"admin", "owner"}:
                return True
        return False
