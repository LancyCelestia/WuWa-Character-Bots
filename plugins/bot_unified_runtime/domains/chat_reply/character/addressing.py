from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from plugins.bot_unified_runtime.domains.core.contracts.character import (
    AddressingContext,
)

_GENDER_VALUES = {"unknown", "male", "female", "nonbinary", "custom"}

# —— 创造者双名事实（审查 G-05：单一事实源）——
# 澜汐与霞月是同一人（双名混用），是守岸人的创造者与唤醒者，也是生产超管。
# 此事实必须由代码结构化持有并稳定注入，不得依赖人格文件：生产人格副本
# 无双名记载，默认配置下 bot 曾答不上「澜汐是谁/霞月是谁」。
# 红线门对本文件内建豁免（tests/test_copy_redline_gate.py 的
# CREATOR_NAME_BUILTIN_EXEMPT），双名字面只允许出现在本文件。
CREATOR_ALIASES: tuple[str, ...] = ("澜汐", "霞月")
CREATOR_NOTE: str = (
    "澜汐与霞月是同一人（双名混用），是守岸人的创造者与唤醒者，"
    "也是这里的超级管理员；听到其中任何一个名字，都指向这同一位。"
)


def creator_aliases() -> tuple[str, ...]:
    """创造者双名（运行时读模块常量，测试可 monkeypatch 验证无第二份硬编码）。"""
    return CREATOR_ALIASES


def creator_context_note() -> str:
    """注入 chat 人格上下文的稳定一行创造者事实；空串表示不注入。"""
    return CREATOR_NOTE


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_addressing_context(
    *,
    session_type: str,
    sender_display_name: str | None = None,
    sender_roles: list[str] | None = None,
    gender_identity: str = "unknown",
    addressing_preference: str = "",
) -> AddressingContext:
    scope = str(session_type or "other").strip().lower()
    scope = scope if scope in {"private", "group"} else "other"
    roles = {str(role).strip().lower() for role in (sender_roles or [])}
    is_master = scope == "group" and "super_admin" in roles
    can_use = scope == "private" or is_master
    explicit_gender = str(gender_identity or "unknown").strip() or "unknown"
    preference = str(addressing_preference or "").strip()
    name = str(preference or sender_display_name or "你").strip() or "你"
    if can_use and not preference:
        name = "漂泊者"
    if scope == "group" and not is_master and preference == "漂泊者":
        # 保留字兜底（评审 D1）：群友自设「漂泊者」会造出
        # 「优先称呼“漂泊者”+禁止称其为漂泊者」的自斥指令，击穿群聊主角
        # 边界——群聊非 master 一律忽略该偏好，回退展示名。
        name = str(sender_display_name or "你").strip() or "你"
    if scope == "group" and not is_master:
        instruction = f"当前是多人群聊；对方是群友，优先称呼“{name}”，禁止称其为漂泊者，不要把群成员设为主角。"
    elif is_master:
        head = (
            f"当前是群聊；对方是配置确认的超级管理员 master，可在合适语境称为“{name}”或漂泊者；其他群友仍不得称为漂泊者。"
        )
        # 双名表述唯一来源=CREATOR_ALIASES（审查 G-05）：此处禁止第二份硬编码，
        # monkeypatch 常量必须能改变本分支输出（tests/test_creator_dualname.py 锁）。
        aliases = [str(alias).strip() for alias in creator_aliases() if str(alias).strip()]
        dual = ""
        if aliases:
            count_word = {1: "这个名字"}.get(len(aliases), f"{len(aliases)}个名字")
            dual = (
                f"（2026-09-13 用户裁定）超级管理员就是{'，也是'.join(aliases)}——"
                f"{count_word}指同一位创造者与唤醒者，叫哪一个都可以，但绝不能只记得一个："
                f"被问“{'/'.join(aliases)}是谁”都要完整答出她的创造者身份，不得说资料里没有。"
            )
        instruction = head + dual
    elif scope == "private":
        instruction = "当前是私聊；对方可视为漂泊者。默认使用“你”，关系自然时可使用“漂泊者”；性别未知时不要猜测。"
    else:
        instruction = "当前称谓身份未知；使用中性称谓“你”，不要猜测性别或擅自称为漂泊者。"
    return AddressingContext(
        scope=scope,
        preferred_name=name,
        gender_identity=explicit_gender,
        gender_confidence="explicit" if explicit_gender != "unknown" else "unknown",
        can_use_wanderer_title=can_use,
        is_master=is_master,
        instruction=instruction,
    )


class AddressingPreferenceStore:
    """用户主动设置的称谓与性别偏好（显式声明，优先于一切推断）。

    SQLite 单连接 + ``threading.Lock`` + WAL 先于 DDL（与会话身份 store 同款）。
    主键 (session_type, session_id, sender_id)：私聊按人、群聊按群+人。
    只存用户显式设置/纠正的值；本 store 不做任何推断。
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS addressing_preferences (
                    session_type TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    sender_id TEXT NOT NULL,
                    addressing_preference TEXT NOT NULL DEFAULT '',
                    gender_identity TEXT NOT NULL DEFAULT 'unknown',
                    relationship TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_type, session_id, sender_id)
                )
                """
            )
            # 关系档（2026-09-24 用户裁定 R2 A）：旧库自动补列，不要求人工迁移
            # （家规先例=affinity 的 first_signals/first_impression/created_at 三列）。
            existing = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(addressing_preferences)")
            }
            if "relationship" not in existing:
                self._conn.execute(
                    "ALTER TABLE addressing_preferences"
                    " ADD COLUMN relationship TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _normalize_gender(raw: str | None) -> str:
        value = str(raw or "").strip().lower()
        return value if value in _GENDER_VALUES else "unknown"

    def get(
        self,
        *,
        session_type: str,
        session_id: str = "",
        sender_id: str,
    ) -> tuple[str, str]:
        """返回 (addressing_preference, gender_identity)；无记录返回 ("", "unknown")。"""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT addressing_preference, gender_identity"
                    " FROM addressing_preferences"
                    " WHERE session_type=? AND session_id=? AND sender_id=?",
                    (str(session_type), str(session_id), str(sender_id)),
                ).fetchone()
        except sqlite3.Error:
            return "", "unknown"
        if row is None:
            return "", "unknown"
        return str(row[0] or ""), self._normalize_gender(str(row[1]))

    def get_relationship(
        self,
        *,
        session_type: str,
        session_id: str = "",
        sender_id: str,
    ) -> str:
        """关系档 canon id（词表见 `character/relationships.py`）；无记录返回空串。"""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT relationship FROM addressing_preferences"
                    " WHERE session_type=? AND session_id=? AND sender_id=?",
                    (str(session_type), str(session_id), str(sender_id)),
                ).fetchone()
        except sqlite3.Error:
            return ""
        if row is None:
            return ""
        return str(row[0] or "")

    def set_relationship(
        self,
        *,
        session_type: str,
        session_id: str = "",
        sender_id: str,
        relationship: str,
    ) -> str:
        """设定关系档，返回**实际落档**的 canon id。

        词表外（打错字、没裁过的关系）→ 回空串且**不动原值**：一个错别字不许把
        用户已设的关系洗掉。显式清空传空串（空串在词表里合法=回到默认相处分寸）。
        本方法不做权限判定——谁能设由调用面（/bot identity 的"仅本人"门）负责。
        """
        from plugins.bot_unified_runtime.domains.chat_reply.character.relationships import (
            normalize_relationship,
        )

        canon = normalize_relationship(relationship)
        if canon == "" and str(relationship or "").strip() != "":
            return ""  # 垃圾输入：不落档、不清档。
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO addressing_preferences (
                    session_type, session_id, sender_id, relationship, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_type, session_id, sender_id) DO UPDATE SET
                    relationship=excluded.relationship,
                    updated_at=excluded.updated_at
                """,
                (
                    str(session_type),
                    str(session_id),
                    str(sender_id),
                    canon,
                    _utc_now_iso(),
                ),
            )
        return canon

    def set(
        self,
        *,
        session_type: str,
        session_id: str = "",
        sender_id: str,
        addressing_preference: str | None = None,
        gender_identity: str | None = None,
    ) -> None:
        """部分更新：未指定的字段保留原值；性别超出已知集合时归一为 unknown。"""
        current_preference, current_gender = self.get(
            session_type=session_type, session_id=session_id, sender_id=sender_id
        )
        preference = (
            str(addressing_preference).strip()
            if addressing_preference is not None
            else current_preference
        )
        gender = (
            self._normalize_gender(gender_identity)
            if gender_identity is not None
            else current_gender
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO addressing_preferences (
                    session_type, session_id, sender_id,
                    addressing_preference, gender_identity, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_type, session_id, sender_id) DO UPDATE SET
                    addressing_preference=excluded.addressing_preference,
                    gender_identity=excluded.gender_identity,
                    updated_at=excluded.updated_at
                """,
                (
                    str(session_type),
                    str(session_id),
                    str(sender_id),
                    preference,
                    gender,
                    _utc_now_iso(),
                ),
            )

    def clear(
        self,
        *,
        session_type: str,
        session_id: str = "",
        sender_id: str,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM addressing_preferences"
                " WHERE session_type=? AND session_id=? AND sender_id=?",
                (str(session_type), str(session_id), str(sender_id)),
            )
