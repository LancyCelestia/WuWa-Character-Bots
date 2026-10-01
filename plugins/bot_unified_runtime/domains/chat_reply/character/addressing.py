from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from plugins.bot_unified_runtime.domains.core.contracts.character import (
    AddressingContext,
)

_GENDER_VALUES = {"unknown", "male", "female", "nonbinary", "custom"}

# —— 称谓字面量单一真身（席 E2，P6.5，2026-10-02）——
# 历史上 `你 / 漂泊者 / 主人 / 创造者` 四套称谓各写各的：本文件把同一句话抄成
# 三四份 f-string 字面，群摘要与压缩提示词（character/shared_group.py）又各自
# 留了一份「群成员不是主角、不得称漂泊者」的禁令副本。正身只许这一处——字面与
# 句式都在下面定义，别处再手打一枚即被 `tests/test_addressing_single_source_gate.py`
# 判红（棘轮＝存量只降不升、新增即红；`主人` 作为**关系别名**的词表真身在
# `character/relationships.py`，那是另一维，本文件不并它）。
# 三条红线由本文件承载，任何改动都要同批过该门的红线锁：
#   ① 性别不推断（`gender_neutrality_clause`）；
#   ② 用户显式偏好最优先（`build_addressing_context` 的 preference 腿）；
#   ③「漂泊者」是群聊保留字——只有私聊与 master 可用，群友一律不称
#      （`WANDERER_TITLE` + `group_cast_prohibition`）。
NEUTRAL_ADDRESS: str = "你"
WANDERER_TITLE: str = "漂泊者"
MASTER_TITLE: str = "master"
CREATOR_TITLE: str = "创造者"

# —— 创造者双名事实（审查 G-05：单一事实源）——
# 澜汐与霞月是同一人（双名混用），是守岸人的创造者与唤醒者，也是生产超管。
# 此事实必须由代码结构化持有并稳定注入，不得依赖人格文件：生产人格副本
# 无双名记载，默认配置下 bot 曾答不上「澜汐是谁/霞月是谁」。
# 红线门对本文件内建豁免（tests/test_copy_redline_gate.py 的
# CREATOR_NAME_BUILTIN_EXEMPT），双名字面只允许出现在本文件。
CREATOR_ALIASES: tuple[str, ...] = ("澜汐", "霞月")
CREATOR_NOTE: str = (
    f"澜汐与霞月是同一人（双名混用），是守岸人的{CREATOR_TITLE}与唤醒者，"
    "也是这里的超级管理员；听到其中任何一个名字，都指向这同一位。"
)


def neutral_address() -> str:
    """中性第二人称缺省（性别不推断，不预设身份）。运行时读模块常量。"""
    return NEUTRAL_ADDRESS


def wanderer_title() -> str:
    """群聊保留字「漂泊者」（红线③）。运行时读模块常量，测试 monkeypatch
    必须能改变产出 ⇒ 证明没有第二份硬编码。"""
    return WANDERER_TITLE


def master_title() -> str:
    """超管档位称谓（指令句里指代「超级管理员」这一档，不是私人称呼）。"""
    return MASTER_TITLE


def creator_title() -> str:
    """「创造者」档位名；双名事实另见 `creator_aliases`。"""
    return CREATOR_TITLE


def gender_neutrality_clause() -> str:
    """红线①「性别不推断」的唯一句式（各分支指令句都插这一句，不许各写一份）。"""
    return "性别未知时不要猜测"


def group_cast_prohibition() -> str:
    """红线③的聚合表述：「群成员都不是唯一主角、不得称漂泊者」的唯一句式。

    群聊上下文里发言者是**一群人**，主角边界与单人会话不同。此句历史上在
    `character/shared_group.py` 的摘要头（旧 :281）与 LLM 压缩提示词（旧 :372）
    各留一份自写副本——两样措辞、一条判据，改一处必漏一处。席 E2 起两处都
    改成调用本函数，副本撤除，措辞只从这里出（该文件字符串常量内的称谓字面
    现算＝0，由本门的零容忍腿执法）。
    """
    return f"发言成员均为群友，不存在唯一主角，不得称任何成员为{WANDERER_TITLE}"


def creator_aliases() -> tuple[str, ...]:
    """创造者双名（运行时读模块常量，测试可 monkeypatch 验证无第二份硬编码）。"""
    return CREATOR_ALIASES



def creator_context_note() -> str:
    """注入 chat 人格上下文的稳定一行创造者事实；空串表示不注入。"""
    return CREATOR_NOTE


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# —— 称谓名消毒（INJ-G2，2026-09-27 修复席 S-FIX-INJG2）——
# `build_addressing_context` 把 name 逐字插进 system prompt 的
# 【当前称谓与主角边界】指令句（消费点 chat.py 只拼不洗）。两条来源腿都在
# 本件汇流之后收口：①群聊=当前发言人展示名（QQ 群名片可含换行/`】`/`system:`
# 行，探针 P3 实测换行直通）；②私聊/群主=「设置名称」偏好（`/bot identity
# set-name`，echo 侧门只挡控制字符/换行/32 字，同行 `“`/`【`/`】` 放行，
# 探针 P4 实测伪指令逐字进 system 段）。
# 分工：`security/injection.neutralize_internal_markers`（唯一真身，与
# `ingest/message_context._neutralize_markers` 共用 INTERNAL_MARKER_PATTERN）
# 只全角化 ASCII 成对边界标记 `[X]`/`[/X]`，**不碰** 【】、弯引号、换行与零宽
# 格式字符——而本落点的攻击面恰是这些形态；不强行把 marker 消毒器扩成第二
# 职责，本件自带最小「单行化 + 引号/方括号全角」私有函数。echo 侧 set-name
# 校验门不动（capabilities/echo.py 为禁写面），收口在两腿汇流之后。
_ADDRESS_NAME_ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
_ADDRESS_NAME_WS_PATTERN = re.compile(r"\s+")


def _sanitize_address_name(value: str) -> str:
    """称谓名专用消毒：去零宽/Cf、方括号与引号全角化、折叠为单行。

    幂等：全角产物（［］＂）不再命中任何替换规则，重复调用零副作用；
    正常中文名（如「澜汐」）逐字节不变。
    """
    # ① 摘掉不可见格式字符：Cf 类（方向控制、BOM 类）+ 逐列出的零宽字符。
    text = "".join(
        ch for ch in value if unicodedata.category(ch) != "Cf" and ch not in _ADDRESS_NAME_ZERO_WIDTH
    )
    # ② 破格形态全角化：CJK 方括号/角括号/双弯引号与 ASCII 引号方括号——
    #    指令模板的边界符号是 【】 与 “”，同名形态出现在名字里即可提前闭合。
    text = (
        text.replace("【", "［")
        .replace("】", "］")
        .replace("「", "〔")
        .replace("」", "〕")
        .replace("『", "〖")
        .replace("』", "〗")
        .replace("“", "＂")
        .replace("”", "＂")
        .replace('"', "＂")
        .replace("'", "＇")
        .replace("[", "［")
        .replace("]", "］")
    )
    # ③ 单行化：换行/制表/连续空白（含 Zs 类空格）折叠为单个空格。
    return _ADDRESS_NAME_WS_PATTERN.sub(" ", text).strip()


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
    name = str(preference or sender_display_name or NEUTRAL_ADDRESS).strip() or NEUTRAL_ADDRESS
    if can_use and not preference:
        name = WANDERER_TITLE
    # 两腿汇流后的唯一收口点（INJ-G2）：偏好与展示名都在此过一遍消毒，
    # 之后才进 f-string 指令句与 AddressingContext。
    name = _sanitize_address_name(name) or NEUTRAL_ADDRESS
    if scope == "group" and not is_master and name == WANDERER_TITLE:
        # 保留字兜底（评审 D1 + 席 E2 补的展示名腿，红线③）：群聊非 master
        # 一律不把「漂泊者」当个人称谓。旧写法只挡**偏好腿**（`preference ==
        # 「漂泊者」`），展示名腿漏了——QQ 群名片本就能填「漂泊者」，于是造出
        # 「优先称呼“漂泊者”+禁止称其为漂泊者」的自斥指令，与偏好腿同形事故，
        # 击穿群聊主角边界。兜底顺序：展示名（非保留字时）→ 中性称谓。
        fallback = _sanitize_address_name(str(sender_display_name or ""))
        name = fallback if fallback and fallback != WANDERER_TITLE else NEUTRAL_ADDRESS
    if scope == "group" and not is_master:
        instruction = f"当前是多人群聊；对方是群友，优先称呼“{name}”，禁止称其为{WANDERER_TITLE}，不要把群成员设为主角。"
    elif is_master:
        head = (
            f"当前是群聊；对方是配置确认的超级管理员 {MASTER_TITLE}，可在合适语境称为“{name}”或{WANDERER_TITLE}；"
            f"其他群友仍不得称为{WANDERER_TITLE}。"
        )
        # 双名表述唯一来源=CREATOR_ALIASES（审查 G-05）：此处禁止第二份硬编码，
        # monkeypatch 常量必须能改变本分支输出（tests/test_creator_dualname.py 锁）。
        aliases = [str(alias).strip() for alias in creator_aliases() if str(alias).strip()]
        dual = ""
        if aliases:
            count_word = {1: "这个名字"}.get(len(aliases), f"{len(aliases)}个名字")
            dual = (
                f"（2026-09-13 用户裁定）超级管理员就是{'，也是'.join(aliases)}——"
                f"{count_word}指同一位{CREATOR_TITLE}与唤醒者，叫哪一个都可以，但绝不能只记得一个："
                f"被问“{'/'.join(aliases)}是谁”都要完整答出她的{CREATOR_TITLE}身份，不得说资料里没有。"
            )
        instruction = head + dual
    elif scope == "private":
        instruction = (
            f"当前是私聊；对方可视为{WANDERER_TITLE}。默认使用“{NEUTRAL_ADDRESS}”，"
            f"关系自然时可使用“{WANDERER_TITLE}”；{gender_neutrality_clause()}。"
        )
    else:
        instruction = (
            f"当前称谓身份未知；使用中性称谓“{NEUTRAL_ADDRESS}”，{gender_neutrality_clause()}，"
            f"不得擅自称为{WANDERER_TITLE}。"
        )
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
