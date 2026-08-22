import asyncio
import inspect
import json
from collections.abc import Callable
from pathlib import Path

from nonebot import get_driver, logger
from packaging.version import Version as version_parser
from tortoise import Tortoise

get_current_context: Callable[[], object | None] | None


def _detect_tortoise_v1() -> bool:
    """Tortoise 1.x 才有 context 模块与 _enable_global_fallback 参数。"""
    try:
        from tortoise.context import get_current_context as _gcc
    except ImportError:
        return False

    global get_current_context
    get_current_context = _gcc
    params = inspect.signature(Tortoise.init).parameters
    return "_enable_global_fallback" in params


get_current_context = None
_TORTOISE_V1 = _detect_tortoise_v1()

from ..utils import get_path
from ..version import VERSION as APP_VERSION
from .models import Group, Sub, User, Version

uid_list = {"live": {"list": [], "index": 0}, "dynamic": {"list": [], "index": 0}}
dynamic_offset = {}

_db_init_lock = asyncio.Lock()


class DB:
    """数据库交互类，与增删改查无关的部分不应该在这里面实现"""

    _ready = False

    @classmethod
    def get_dynamic_offset_path(cls) -> Path:
        return Path(get_path("dynamic_offset.json"))

    @classmethod
    def _orm_context_ok(cls) -> bool:
        """_ready 与 Tortoise 1.x 全局上下文需同时成立，否则会出现 No TortoiseContext。"""
        if not cls._ready:
            return False
        if not _TORTOISE_V1:
            return True
        return get_current_context() is not None

    @classmethod
    async def _do_init(cls) -> None:
        """在持有 _db_init_lock 时执行完整初始化。"""
        cls._ready = False
        config = {
            "connections": {
                "bililive": f"sqlite://{get_path('data.sqlite3')}"
            },
            "apps": {
                "bililive_app": {
                    "models": ["nonebot_plugin_bililive.database.models"],
                    "default_connection": "bililive",
                }
            },
        }

        init_kwargs = (
            {"_enable_global_fallback": True} if _TORTOISE_V1 else {}
        )
        try:
            await Tortoise.init(config, **init_kwargs)
        except TypeError:
            if init_kwargs:
                await Tortoise.init(config)
            else:
                raise

        await Tortoise.generate_schemas()
        await cls.migrate()
        await cls.update_uid_list()
        await cls.load_dynamic_offsets()
        await cls.save_dynamic_offsets()
        cls._ready = True

    @classmethod
    async def init(cls):
        """初始化数据库"""
        async with _db_init_lock:
            await cls._do_init()

    @classmethod
    async def close(cls):
        async with _db_init_lock:
            cls._ready = False
            await cls.save_dynamic_offsets()
            await Tortoise.close_connections()

    @classmethod
    async def _recover_stale_orm(cls) -> None:
        """_ready 仍为 True 但 Tortoise 上下文已丢失时，关闭并重新初始化。"""
        if not _TORTOISE_V1:
            return
        async with _db_init_lock:
            if get_current_context() is not None:
                return
            if not cls._ready:
                return
            logger.warning(
                "Tortoise ORM 上下文已失效（可能被其他代码关闭连接），"
                "正在重新初始化数据库"
            )
            try:
                await Tortoise.close_connections()
            except Exception:
                logger.exception("关闭 Tortoise 连接时出错，仍将尝试重新初始化")
            cls._ready = False
            await cls._do_init()

    @classmethod
    async def wait_until_ready(cls, timeout: float = 30) -> bool:
        if cls._orm_context_ok():
            return True

        waited = 0.0
        interval = 0.1
        while waited < timeout:
            if cls._orm_context_ok():
                return True
            if cls._ready and _TORTOISE_V1 and get_current_context() is None:
                await cls._recover_stale_orm()
                if cls._orm_context_ok():
                    return True
            await asyncio.sleep(interval)
            waited += interval

        return cls._orm_context_ok()

    @classmethod
    async def load_dynamic_offsets(cls):
        path = cls.get_dynamic_offset_path()
        if not path.exists():
            return
        try:
            raw_offsets = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("动态偏移量缓存读取失败，将使用当前内存状态继续运行")
            return

        for uid_str, value in raw_offsets.items():
            try:
                uid = int(uid_str)
                dynamic_id = int(value)
            except (TypeError, ValueError):
                continue
            if uid in dynamic_offset:
                dynamic_offset[uid] = dynamic_id

    @classmethod
    async def save_dynamic_offsets(cls):
        path = cls.get_dynamic_offset_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized_offsets = {
            str(uid): dynamic_offset[uid] for uid in sorted(dynamic_offset)
        }
        path.write_text(
            json.dumps(serialized_offsets, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    async def set_dynamic_offset(cls, uid: int, value: int):
        dynamic_offset[int(uid)] = int(value)
        await cls.save_dynamic_offsets()

    @classmethod
    async def get_user(cls, **kwargs):
        """获取 UP 主信息"""
        return await User.get(**kwargs).first()

    @classmethod
    async def get_name(cls, uid) -> str | None:
        """获取 UP 主昵称"""
        user = await cls.get_user(uid=uid)
        if user:
            return user.name
        return None

    @classmethod
    async def add_user(cls, **kwargs):
        """添加 UP 主信息"""
        return await User.add(**kwargs)

    @classmethod
    async def delete_user(cls, uid) -> bool:
        """删除 UP 主信息"""
        if await cls.get_sub(uid=uid):
            # 还存在该 UP 主订阅，不能删除
            return False
        await User.delete(uid=uid)
        return True

    @classmethod
    async def update_user(cls, uid: int, name: str) -> bool:
        """更新 UP 主信息"""
        if await cls.get_user(uid=uid):
            await User.update({"uid": uid}, name=name)
            return True
        return False

    @classmethod
    async def get_group(cls, **kwargs):
        """获取群设置"""
        return await Group.get(**kwargs).first()

    @classmethod
    async def get_group_admin(cls, group_id) -> bool:
        """获取指定群权限状态"""
        group = await cls.get_group(id=group_id)
        if not group:
            # TODO 自定义默认状态
            return True
        return bool(group.admin)

    @classmethod
    async def add_group(cls, **kwargs):
        """创建群设置"""
        return await Group.add(**kwargs)

    @classmethod
    async def delete_group(cls, id) -> bool:
        """删除群设置"""
        if await cls.get_sub(type="group", type_id=id):
            # 当前群还有订阅，不能删除
            return False
        await Group.delete(id=id)
        return True

    @classmethod
    async def set_permission(cls, id, switch) -> bool:
        """设置指定群组权限"""
        group = await cls.get_group(id=id)
        if not group:
            await cls.add_group(id=id, admin=switch)
            return True
        if bool(group.admin) == switch:
            return False
        await Group.update({"id": id}, admin=switch)
        return True

    @classmethod
    async def get_sub(cls, **kwargs):
        """获取指定位置的订阅信息"""
        return await Sub.get(**kwargs).first()

    @classmethod
    async def get_subs(cls, **kwargs):
        return await Sub.get(**kwargs)

    @classmethod
    async def get_push_list(cls, uid, func) -> list[Sub]:
        """根据类型和 UID 获取需要推送的 QQ 列表"""
        return await cls.get_subs(uid=uid, **{func: True})

    @classmethod
    async def get_sub_list(cls, type, type_id) -> list[Sub]:
        """获取指定位置的推送列表"""
        return await cls.get_subs(type=type, type_id=type_id)

    @classmethod
    async def add_sub(cls, *, name, **kwargs) -> bool:
        """添加订阅"""
        if not await Sub.add(**kwargs):
            return False
        await cls.add_user(uid=kwargs["uid"], name=name)
        if kwargs["type"] == "group":
            await cls.add_group(id=kwargs["type_id"], admin=True)
        await cls.update_uid_list()
        return True

    @classmethod
    async def delete_sub(cls, uid, type, type_id) -> bool:
        """删除指定订阅"""
        if await Sub.delete(uid=uid, type=type, type_id=type_id):
            await cls.delete_user(uid=uid)
            await cls.update_uid_list()
            return True
        # 订阅不存在
        return False

    @classmethod
    async def delete_sub_list(cls, type, type_id):
        """删除指定位置的推送列表"""
        async for sub in Sub.get(type=type, type_id=type_id):
            await cls.delete_sub(uid=sub.uid, type=sub.type, type_id=sub.type_id)
        await cls.update_uid_list()

    @classmethod
    async def set_sub(cls, conf, switch, **kwargs):
        """开关订阅设置"""
        sub = await cls.get_sub(**kwargs)
        if not sub:
            return False
        previous = getattr(sub, conf, None)
        updated = await Sub.update(kwargs, **{conf: switch})
        if not updated:
            return False
        if conf == "dynamic":
            if switch and not previous:
                dynamic_offset[int(kwargs["uid"])] = -1
                await cls.save_dynamic_offsets()
            await cls.update_uid_list()
        return True

    @classmethod
    async def get_version(cls):
        """获取数据库版本"""
        version = await Version.first()
        return version_parser(version.version) if version else None

    @classmethod
    async def migrate(cls):
        """迁移数据库"""
        DBVERSION = await cls.get_version()
        # 新数据库
        if not DBVERSION:
            # 检查是否有旧的 json 数据库需要迁移
            await cls.migrate_from_json()
            await Version.add(version=str(APP_VERSION))
            return
        if DBVERSION != APP_VERSION:
            # await cls._migrate()
            await Version.update({}, version=APP_VERSION)
            return

    @classmethod
    async def migrate_from_json(cls):
        """从 TinyDB 的 config.json 迁移数据"""
        json_path = Path(get_path("config.json"))
        if not json_path.exists():
            return

        logger.info("正在从 config.json 迁移数据库")
        with json_path.open("r", encoding="utf-8") as f:
            old_db = json.loads(f.read())
        subs: dict[int, dict] = old_db["_default"]
        groups: dict[int, dict] = old_db["groups"]
        for sub in subs.values():
            await cls.add_sub(
                uid=sub["uid"],
                type=sub["type"],
                type_id=sub["type_id"],
                bot_id=sub["bot_id"],
                name=sub["name"],
                live=sub["live"],
                dynamic=sub["dynamic"],
                at=sub["at"],
            )
        for group in groups.values():
            await cls.set_permission(group["group_id"], group["admin"])

        json_path.rename(get_path("config.json.bak"))
        logger.info("数据库迁移完成")

    @classmethod
    async def get_uid_list(cls, func) -> list:
        """根据类型获取需要爬取的 UID 列表"""
        return uid_list[func]["list"]

    @classmethod
    async def next_uid(cls, func):
        """获取下一个要爬取的 UID"""
        func = uid_list[func]
        if func["list"] == []:
            return None

        if func["index"] >= len(func["list"]):
            func["index"] = 1
            return func["list"][0]
        else:
            index = func["index"]
            func["index"] += 1
            return func["list"][index]

    @classmethod
    async def update_uid_list(cls):
        """更新需要推送的 UP 主列表"""
        subs = Sub.all()
        uid_list["live"]["list"] = list(
            set([sub.uid async for sub in subs if sub.live])
        )
        uid_list["dynamic"]["list"] = list(
            set([sub.uid async for sub in subs if sub.dynamic])
        )

        # 清除没有订阅的 offset
        changed = False
        dynamic_offset_keys = set(dynamic_offset)
        dynamic_uids = set(uid_list["dynamic"]["list"])
        for uid in dynamic_offset_keys - dynamic_uids:
            del dynamic_offset[uid]
            changed = True
        for uid in dynamic_uids - dynamic_offset_keys:
            dynamic_offset[uid] = -1
            changed = True
        if changed:
            await cls.save_dynamic_offsets()

    async def backup(self):
        """备份数据库"""
        pass

    @classmethod
    async def get_login(cls):
        """获取登录信息"""
        pass

    @classmethod
    async def update_login(cls, tokens):
        """更新登录信息"""
        pass


get_driver().on_startup(DB.init)
get_driver().on_shutdown(DB.close)
