from nonebot import require

require("nonebot_plugin_localstore")

import sqlite3
import asyncio
from typing import List, Tuple, Optional

import nonebot_plugin_localstore as store

# ————————————————————————————
# 数据目录初始化
# ————————————————————————————

DATA_DIR = store.get_plugin_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "subscriptions.db"


# ————————————————————————————
# 同步数据库操作（sqlite3）
# ————————————————————————————

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """同步创建订阅表"""
    conn = _connect()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            uid TEXT NOT NULL,
            last_video_bvid TEXT,
            last_video_time INTEGER,
            UNIQUE(group_id, uid)
        )
    ''')
    conn.commit()
    conn.close()


def _add_subscription(group_id: str, uid: str) -> bool:
    """同步添加订阅"""
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute(
            'INSERT INTO subscriptions (group_id, uid) VALUES (?, ?)',
            (group_id, uid)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def _remove_subscription(group_id: str, uid: str) -> bool:
    """同步取消订阅"""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        'DELETE FROM subscriptions WHERE group_id = ? AND uid = ?',
        (group_id, uid)
    )
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def _get_subscriptions() -> List[Tuple[str, str]]:
    """同步获取所有订阅"""
    conn = _connect()
    c = conn.cursor()
    c.execute('SELECT group_id, uid FROM subscriptions')
    rows = [tuple(r) for r in c.fetchall()]
    conn.close()
    return rows


def _get_subscription_groups(uid: str) -> List[Tuple[str, str, Optional[str], Optional[int]]]:
    """同步获取某个 UID 的全部订阅行（可能有多个群订阅同一位 UP 主）

    返回：(group_id, uid, last_video_bvid, last_video_time) 列表
    """
    conn = _connect()
    c = conn.cursor()
    c.execute(
        'SELECT group_id, uid, last_video_bvid, last_video_time '
        'FROM subscriptions WHERE uid = ?',
        (uid,)
    )
    rows = [(r[0], r[1], r[2], r[3]) for r in c.fetchall()]
    conn.close()
    return rows


def _update_last_video(uid: str, bvid: str, timestamp: int) -> None:
    """同步更新该 UID 全部订阅行的最新视频记录"""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        'UPDATE subscriptions SET last_video_bvid = ?, last_video_time = ? WHERE uid = ?',
        (bvid, timestamp, uid)
    )
    conn.commit()
    conn.close()


def _set_subscription_baseline(group_id: str, uid: str, bvid: str, timestamp: int) -> None:
    """同步设置单条订阅的基线（订阅时记录 UP 主当前最新视频，避免旧视频被当作新视频播报）"""
    conn = _connect()
    c = conn.cursor()
    c.execute(
        'UPDATE subscriptions SET last_video_bvid = ?, last_video_time = ? '
        'WHERE group_id = ? AND uid = ?',
        (bvid, timestamp, group_id, uid)
    )
    conn.commit()
    conn.close()


# ————————————————————————————
# 异步包装
# ————————————————————————————

async def init_db():
    """初始化数据库"""
    await asyncio.to_thread(_init_db)


async def add_subscription(group_id: str, uid: str) -> bool:
    """异步添加订阅"""
    return await asyncio.to_thread(_add_subscription, group_id, uid)


async def remove_subscription(group_id: str, uid: str) -> bool:
    """异步取消订阅"""
    return await asyncio.to_thread(_remove_subscription, group_id, uid)


async def get_subscriptions() -> List[Tuple[str, str]]:
    """异步获取所有订阅"""
    return await asyncio.to_thread(_get_subscriptions)


async def get_subscription_groups(uid: str) -> List[Tuple[str, str, Optional[str], Optional[int]]]:
    """异步获取某个 UID 的全部订阅行"""
    return await asyncio.to_thread(_get_subscription_groups, uid)


async def update_last_video(uid: str, bvid: str, timestamp: int) -> None:
    """异步更新该 UID 全部订阅行的最新视频记录"""
    await asyncio.to_thread(_update_last_video, uid, bvid, timestamp)


async def set_subscription_baseline(group_id: str, uid: str, bvid: str, timestamp: int) -> None:
    """异步设置单条订阅的基线"""
    await asyncio.to_thread(_set_subscription_baseline, group_id, uid, bvid, timestamp)
