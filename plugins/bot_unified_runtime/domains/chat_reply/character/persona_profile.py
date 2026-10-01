"""人格册（persona register）与热切换下发收口件。

设计锚点＝docs/HANDBOOK.md §49.4 七面 + §49.8 用户裁定（H-0..H-5）+ §49.9 两套资料。

三件事，逐条对应裁定：

1. **人格册是唯一事实源（H-5乙）**：``personas/registry/<persona_id>.json`` 一号一份，
   按 ``(st_mtime_ns, st_size)`` 签名热读——改一次即生效，不重启（否则仍是半热）。
   ``.env`` 的 ``bot_persona_alt_profiles`` 降为**兼容位**：只登记未搬进册子的人格；
   同一 persona 一旦入册，其外观与文件清单**以册子为准**，不留第二真身
   （``build_effective_alt_personas`` 的优先级唯一、可判）。
2. **唯一下发口（H-1）**：``apply_persona_profile`` 是「把人格外观推到 QQ + 卡片」的
   唯一收口件，内部只经传入的 ``call_api`` 通道调 ``set_qq_profile`` / ``set_qq_avatar``，
   卡片头像复用既有 ``bot_avatar.set_local_path``——**不新建第二条头像通路、不新建第二条
   出站通道**。昵称/签名一发、头像一发是两次独立调用，可能一半成功：逐项出回执，
   任一项未落地就点名「哪几项已落／哪几项没落」，禁止在半切态宣称"已切换"。
   **动作册可写四样**（判活只走 SnowLuma 真身安装目录 ``config-*.js`` 的
   ``ACTION_REGISTRY`` 口径，非插件树考古）：``set_qq_profile`` 收
   nickname/personal_note/sex（sex 整型 0 未知·1 男·2 女）、``set_qq_avatar`` 收 file；
   本件对四样逐一支持，**在册未表态的格绝不下发**（性别尤其禁从名字推断，§49.9）。
   回执除外观三格外含**人格文本腿**（``persona_text``）与**知识清单腿**
   （``knowledge_list``，S-IMPL-PERSONA-QQLEG 收口 H-1 五格项集）：备用人格在册
   设定清单为空 ⇒ 点名「文本未落」，绝不默认成功（S-FIX-PERSONA-TEXT ②，堵 H-1
   的回判据缝隙）；清单未表态 ⇒ skipped 点名回落基线（兼容语义，不是半切）。
3. **自身名字以册子为准（台账 #60 硬约束）**：``get_login_info`` 的自身身份缓存改后
   仍回旧昵称，实测禁作自称事实源；``current_bot_nickname`` 只读册子/兼容显示名，
   绝不读 ``get_login_info``（tests 里立一把扫源码的防回归锁）。

音色（tts_refs）按 H-3 **只声明未接线**：在册登记，本批不实现下发腿。

S-FIX-PERSONA-R2（F-C/F-D/F-B）加三条装载/出站纪律（判定零副本，全部问
``domains/core/safety_exec/paths.py`` 唯一真身）：

4. **册子清单锚定（F-D）**：``files.settings`` / ``files.knowledge`` 条目必须落在
   ``personas/<persona_id>/`` 子树内（锚根＝注册表目录的父目录拼 persona_id，
   生产即 ``<repo>/personas/<id>/``；包含判定只问 ``paths.check_staged_target``）。
   越锚条目点名跳过（warning 点到文件名），绝不假成功。persona_id 自身带分隔/穿越
   ⇒ 整册清单不采信。
5. **头像出站闸（F-C）**：``qq.avatar_path`` 装载时先拒一切 URL 形态（册子头像没有
   远程合法形态；硬要远程图请走既有、另受闸的下载腿——本票不建这条能力），再问
   ``paths.check_sendable``（允许根＝工作区 + 运行数据域，含 ``data/avatar``）。
   ``apply_persona_profile`` 下发前对同一值**复核**同一枚闸（装载时的放行不作数，
   TOCTOU 锁）。被拦头像回执 ``failed`` 点名，不是 ``skipped``。
6. **回执打码（F-B）**：一切进 ``ItemReceipt.detail`` / ``summary()`` 的动态文本
   过 ``render.plain_text.redact_local_secrets``（只 import 调用，不改咽喉真身）；
   缺文件异常只留文件名。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from plugins.bot_unified_runtime.domains.chat_reply.character.persona_set import (
    AltPersonaSpec,
    build_alt_personas,
)

# 路径域判定唯一真身（别名形态＝restricted_runner 同族接线；已登记消费点，
# 名册见 tests/test_safety_exec_paths.py::ALLOWED_CONSUMERS，主代理授权补登）。
from plugins.bot_unified_runtime.domains.core.safety_exec import paths

logger = logging.getLogger(__name__)

# persona_profile.py 位于 .../domains/chat_reply/character/ 下，parents[5]＝仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_REGISTRY_DIR = _REPO_ROOT / "personas" / "registry"

# call_api 适配器形态：``async (action, params) -> dict``。根 __init__ 接线时传
# ``lambda action, params: bot.call_api(action, **params)``；测试传 fake transport。
CallApi = Callable[[str, dict], Awaitable[dict]]

# Windows 裸盘符路径（``C:\x`` / ``C:/x``）不是 URL：urlsplit 会把盘符读成
# scheme="c"，必须先行短路（bot_avatar._local_avatar_target 同族教训/8.3 陷阱）。
_WINDOWS_DRIVE_FORM_RE = re.compile(r"^[A-Za-z]:[\\/]")


# ---------------------------------------------------------------------------
# 装载/出站共用闸（S-FIX-PERSONA-R2 F-C/F-D）：判定全部问 paths.py，本域零抄尺
# ---------------------------------------------------------------------------

def _avatar_url_form(text: str) -> bool:
    """头像值是否为 URL 形态（scheme://…）。盘符裸路径先行短路，绝不误杀。"""
    raw = str(text or "").strip()
    if not raw or _WINDOWS_DRIVE_FORM_RE.match(raw):
        return False
    try:
        return bool(urllib.parse.urlsplit(raw).scheme)
    except ValueError:  # 解不动的畸形串按 URL 处理（fail-closed）
        return True


def _avatar_sendable(raw: str) -> tuple[bool, str]:
    """头像出站唯一判定：装载与下发两处问**同一枚闸**。

    口径：空值不表态（False, ""，由调用方走"无头像"腿）；URL 形态一律点名拒绝
    （册子头像无远程合法形态，接 check_download_url 会新造一条能力腿，本票裁定
    不接）；其余问 ``paths.check_sendable``，只有 ``allowed`` 放行——
    ``needs_review`` 也拦（fail-closed）。返回 ``(放行?, 拒因明文)``。
    """
    text = str(raw or "").strip()
    if not text:
        return False, ""
    if _avatar_url_form(text):
        return False, "URL 形态头像一律拒绝（仅接受本地路径形态，下发前由协议端回读即外泄面）"
    try:
        decision = paths.check_sendable(text)
    except Exception:  # noqa: BLE001 - 判定件不可用＝按最保守口径拒绝
        return False, "路径出站判定不可用（fail-closed 拒绝）"
    if decision.verdict == paths.VERDICT_ALLOWED:
        return True, ""
    return False, paths.plain_reason(decision.reason_code) or "路径出站判定未放行"


def _anchored_register_file(entry: str, anchor_root: Path) -> str:
    """册子清单条目的锚定判定：条目规范后必须落在 ``personas/<id>/`` 锚根内。

    包含判据只问 ``paths.check_staged_target``（两侧 resolve 后逐段比对，8.3/穿越
    全折平；该谓词刻意不查禁触名册——锚根本身就是 personas 子树，用 check_sendable
    会同源自拒）。通过则回**锚内绝对形态**字符串；越锚/解析失败回空串（点名跳过）。
    """
    candidate = Path(str(entry).strip()).expanduser()
    if not candidate.is_absolute():
        candidate = anchor_root / candidate
    try:
        decision = paths.check_staged_target(str(candidate), str(anchor_root))
    except Exception:  # noqa: BLE001 - 判定不可用＝不放行（fail-closed）
        return ""
    return str(candidate) if decision.verdict == paths.VERDICT_ALLOWED else ""


#: ``set_qq_profile.sex`` 枚举（0 未知 / 1 男 / 2 女）——判活口径＝SnowLuma 真身
#: 安装目录 ``config-*.js`` 的 ACTION_REGISTRY 声明，不抄插件树里的历史宣称。
#: 白名单之外一律装载时点名拒收；**绝不**从昵称/名字推断性别（§49.9 红线）。
_QQ_SEX_MANUAL_VALUES = (0, 1, 2)


def _parse_qq_sex(raw: object, source_name: str) -> int | None:
    """装载 ``qq.sex``：缺省/空串⇒不表态（None，下发腿跳过该格）；
    0/1/2（整型或等价数字串）⇒采信；其余形态⇒拒收点名，不猜、不折算。"""
    if raw is None or isinstance(raw, bool):  # bool 是 int 子类，必须先行排除
        return None
    value: int | None = None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            value = None
    if value is None or value not in _QQ_SEX_MANUAL_VALUES:
        logger.warning(
            "persona register %s qq.sex rejected (不在动作册 sex 枚举 0/1/2，按不表态处理)",
            source_name,
        )
        return None
    return int(value)


@dataclass(frozen=True)
class PersonaProfileRecord:
    """一个 persona 的在册资料（值对象）。空字符串/空元组＝该项"不表态"，
    由调用方按兼容位/基线回落，或按「空＝不切该项」跳过（§49.4-1）。"""

    persona_id: str
    display_name: str = ""
    qq_nickname: str = ""
    qq_signature: str = ""
    # 性别＝动作册可写四样里唯一「在册才发」的一格：None＝不表态（绝不下发、
    # 绝不从名字推断，§49.9）；0 未知 / 1 男 / 2 女（判活口径＝真身安装目录
    # config-*.js 的 set_qq_profile.sex 枚举，白名单外的值装载时点名拒收）。
    qq_sex: int | None = None
    qq_avatar_path: str = ""
    # 装载闸拒因（F-C）：非空＝在册头像被出站闸拦下（qq_avatar_path 已清空），
    # 下发腿必须据此出 failed 回执点名，绝不塌成「无头像」的 skipped 假成功。
    avatar_rejected_reason: str = ""
    settings_files: tuple[str, ...] = ()
    knowledge_files: tuple[str, ...] = ()
    tts_refs: tuple[str, ...] = ()
    display_only: tuple[tuple[str, str], ...] = ()  # 六不可写字段（仅展示，§49.7）
    is_main: bool = False
    source_path: str = ""

    @property
    def resolved_avatar(self) -> str:
        """相对路径经 scripts/runtime_paths 中央件解析；绝对路径原样返回。

        注册表里存的是数据根相对路径（如 ``data/avatar/x.jpg``），不硬编码本机绝对路径；
        运行期真实头像在 Runtime 数据根（.env ``BOT_RUNTIME_DATA_DIR``）下——解析统一走
        ``runtime_path()`` 唯一真身，与 providers.py 等同口径，禁止在本模块自拼路径。
        解析不到文件时仍返回可判空路径，由下发腿点名跳过、绝不假成功。
        """
        import sys

        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scripts.runtime_paths import (
            runtime_path,  # 中央件唯一入口（同目录 providers.py 既有范式：函数级懒导+路径注入）
        )

        raw = self.qq_avatar_path.strip()
        if not raw:
            return ""
        candidate = Path(raw)
        return str(candidate if candidate.is_absolute() else runtime_path(candidate))


# ---------------------------------------------------------------------------
# 人格册加载器：(mtime,size) 热读，逐文件签名缓存
# ---------------------------------------------------------------------------

def _signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (0, 0)


def _parse_profile_file(path: Path) -> PersonaProfileRecord | None:
    """把一个 profile.json 解成 record；解析失败记一行 warning 返回 None（不误当空册）。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("persona register file unreadable, skipped: %s (%s)", path, type(exc).__name__)
        return None
    if not isinstance(payload, dict):
        logger.warning("persona register entry not a JSON object, skipped: %s", path)
        return None
    persona_id = str(payload.get("persona_id") or path.stem).strip()

    def _dict_field(container: dict, key: str) -> dict:
        raw = container.get(key)
        return raw if isinstance(raw, dict) else {}

    qq = _dict_field(payload, "qq")
    files = _dict_field(payload, "files")
    voice = _dict_field(payload, "voice")
    display_only = _dict_field(payload, "display_only")

    def _raw_str_list(container: dict, key: str) -> tuple[str, ...]:
        raw = container.get(key)
        if isinstance(raw, list):
            return tuple(str(item).strip() for item in raw if str(item).strip())
        return ()

    # ---- F-D：清单锚定 personas/<id>/（越锚点名跳过，绝不假成功）-----------
    # persona_id 自身带分隔/穿越 ⇒ 锚根不可信，整册清单不采信（8.3 短名陷阱同族：
    # 锚必须由可信成分构成）。
    anchor_ok = bool(persona_id) and persona_id == Path(persona_id).name
    anchor_root = path.parent.parent / persona_id if anchor_ok else None

    def _anchored_list(key: str) -> tuple[str, ...]:
        entries = _raw_str_list(files, key)
        if not entries:
            return ()
        if anchor_root is None:
            logger.warning(
                "persona register %s: unsafe persona_id, all %s entries dropped: %s",
                path.name, key, len(entries),
            )
            return ()
        kept: list[str] = []
        for entry in entries:
            anchored = _anchored_register_file(entry, anchor_root)
            if anchored:
                kept.append(anchored)
            else:
                # 只点名文件名：装载 warning 也不带全路径（F-B 同口径）。
                logger.warning(
                    "persona register %s entry outside persona anchor, named-and-skipped: %s (%s)",
                    path.name, Path(entry).name or entry, key,
                )
        return tuple(kept)

    settings_files = _anchored_list("settings")
    knowledge_files = _anchored_list("knowledge")

    # ---- F-C：头像装载闸（URL 形态点名拒 + check_sendable）------------------
    avatar_raw = str(qq.get("avatar_path") or "").strip()
    avatar_kept = ""
    avatar_rejected_reason = ""
    if avatar_raw:
        avatar_ok, avatar_why = _avatar_sendable(avatar_raw)
        if avatar_ok:
            avatar_kept = avatar_raw
        else:
            avatar_rejected_reason = avatar_why
            logger.warning(
                "persona register %s avatar rejected at load (named-and-skipped): %s (%s)",
                path.name, Path(avatar_raw).name or "avatar", avatar_why,
            )

    display_meta = tuple(
        (str(key), str(value))
        for key, value in display_only.items()
        if not str(key).startswith("_")
    )
    return PersonaProfileRecord(
        persona_id=persona_id,
        display_name=str(payload.get("display_name") or persona_id).strip(),
        qq_nickname=str(qq.get("nickname") or "").strip(),
        qq_signature=str(qq.get("signature") or "").strip(),
        qq_sex=_parse_qq_sex(qq.get("sex"), path.name),
        qq_avatar_path=avatar_kept,
        avatar_rejected_reason=avatar_rejected_reason,
        settings_files=settings_files,
        knowledge_files=knowledge_files,
        tts_refs=_raw_str_list(voice, "tts_refs"),
        display_only=display_meta,
        is_main=bool(payload.get("is_main", False)),
        source_path=str(path),
    )


class PersonaProfileRegistry:
    """人格册加载器。每次读都逐文件重算 ``(mtime,size)`` 签名（文件数是个位数，代价可忽略）：
    签名未变复用缓存，变了重解析，新增/删除文件下一轮自然纳入。这就是"热读"。"""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else DEFAULT_REGISTRY_DIR
        self._cache: dict[Path, tuple[tuple[int, int], PersonaProfileRecord | None]] = {}
        self._lock = threading.Lock()

    def _scan(self) -> dict[str, PersonaProfileRecord]:
        records: dict[str, PersonaProfileRecord] = {}
        files = sorted(self.directory.glob("*.json")) if self.directory.is_dir() else []
        seen = set(files)
        for path in files:
            signature = _signature(path)
            with self._lock:
                cached = self._cache.get(path)
                if cached is not None and cached[0] == signature:
                    record = cached[1]
                else:
                    record = _parse_profile_file(path)
                    self._cache[path] = (signature, record)
            if record is not None:
                records[record.persona_id] = record
        with self._lock:
            for stale in [p for p in self._cache if p not in seen]:
                del self._cache[stale]
        return records

    def get(self, persona_id: str) -> PersonaProfileRecord | None:
        return self._scan().get(str(persona_id or "").strip())

    def all(self) -> dict[str, PersonaProfileRecord]:
        return self._scan()

    def persona_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._scan()))


_REGISTRY_LOCK = threading.Lock()
_SHARED_REGISTRY: PersonaProfileRegistry | None = None


def get_shared_registry() -> PersonaProfileRegistry:
    """进程级共享人格册（懒建）；测试可自建实例注入，不依赖本单例。"""
    global _SHARED_REGISTRY
    with _REGISTRY_LOCK:
        if _SHARED_REGISTRY is None:
            _SHARED_REGISTRY = PersonaProfileRegistry()
        return _SHARED_REGISTRY


def reset_shared_registry_for_tests() -> None:
    global _SHARED_REGISTRY
    with _REGISTRY_LOCK:
        _SHARED_REGISTRY = None


# ---------------------------------------------------------------------------
# 兼容位与真身的优先级：人格册 > .env dict（唯一、可判，不留第二真身）
# ---------------------------------------------------------------------------

def _spec_from_record(record: PersonaProfileRecord, compat: AltPersonaSpec | None) -> AltPersonaSpec:
    """在册 persona 的 spec：外观/清单以册子为准；册子未表态的文件清单回落兼容位。"""
    files = record.settings_files or (compat.files if compat is not None else ())
    return AltPersonaSpec(
        profile_id=record.persona_id,
        display_name=record.display_name or record.persona_id,
        files=files,
        weight=(compat.weight if compat is not None else 0.0),
        emotions=(compat.emotions if compat is not None else ()),
        knowledge_files=record.knowledge_files or (compat.knowledge_files if compat is not None else ()),
    )


def build_effective_alt_personas(
    config: object,
    *,
    registry: PersonaProfileRegistry | None = None,
) -> dict[str, AltPersonaSpec]:
    """备用人格权威视图：先取人格册（真身），未入册的 persona 才回落到 ``.env`` 兼容位。

    同一 persona 只可能来自一处（在册 ⇒ 用册子，且不再叠加 ``.env`` 的 display_name 等），
    故优先级唯一、无双真身（tests 逐点钉）。
    """
    active_registry = registry if registry is not None else get_shared_registry()
    compat = build_alt_personas(config)
    specs: dict[str, AltPersonaSpec] = {}
    for persona_id, record in active_registry.all().items():
        if record.is_main:
            continue
        specs[persona_id] = _spec_from_record(record, compat.get(persona_id))
    for persona_id, spec in compat.items():
        specs.setdefault(persona_id, spec)
    return specs


def main_persona_knowledge_files(
    persona_id: str,
    *,
    registry: PersonaProfileRegistry | None = None,
) -> tuple[str, ...]:
    """主人格（在册 is_main）自带的知识/设定清单；无册项或清单为空 ⇒ 回空（调用方用 .env 基线）。"""
    active_registry = registry if registry is not None else get_shared_registry()
    record = active_registry.get(persona_id)
    if record is None:
        return ()
    return record.knowledge_files


# ---------------------------------------------------------------------------
# 自身名字的唯一事实源（禁 get_login_info）
# ---------------------------------------------------------------------------


def active_persona_id(
    config: object | None = None,
    *,
    override_provider: Callable[[], object] | None = None,
) -> str:
    """""我是哪一格人格"的唯一读法——**只定 id，不产名字**（名字仍由
    ``current_bot_nickname`` 单口出）。

    为什么要有这一枚：``current_bot_nickname`` 要调用方自己交 ``persona_id``，而
    "当前生效谁"＝「runtime 切换态 override → 配置主人格档」这条序。此前这条序
    没有公共读法，各署名面（卡片页脚 / 管理命令回执 / 状态行）于是各自去抄
    ``config.bot_persona_display_name``——切人格后配置没动 ⇒ 抄出来的还是旧名
    （台账 P-G3「自称与页面名分家」的机制根因）。补这一枚**不是第二条取名腿**：
    它一个名字都不产，只把 id 交回给唯一读法。

    取法（每轮现读，不留构造期快照）：
    ① 显式传入的 ``override_provider``（可调用，命令面手边已有 store 时用它）；
    ② ``config.persona_override_provider``（装配层注入的同形态，与
       ``providers`` 的 ``persona_registry`` 注入口同一约定）；
    ③ runtime 人格切换态（``/bot runtime persona switch`` 的落点，经进程级缓存的
       settings manager 现读，逐实例＝``effective_instance``）；
    ④ ``config.bot_persona_profile_id``（主人格档）；都没有 ⇒ ``"default"``。

    ③ 任何异常（非生产环境、未装配、读盘失败）一律吞成空串回落到 ④——署名面
    不许因为取不到切换态而炸掉一张卡。**绝不读 ``get_login_info``**（台账 #60★）。
    """
    provider = override_provider
    if provider is None:
        provider = getattr(config, "persona_override_provider", None)
    if callable(provider):
        try:
            override = str(provider() or "").strip()
        except Exception:  # noqa: BLE001 - 注入的读法坏了不等于人格没了
            override = ""
        if override:
            return override
    if config is None:
        return "default"
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import (
            build_runtime_settings_store,
        )

        override = str(
            build_runtime_settings_store(config).get_persona_override() or ""
        ).strip()
    except Exception:  # noqa: BLE001 - 切换态读不到 ⇒ 回配置主人格档，绝不抛
        override = ""
    if override:
        return override
    return (
        str(getattr(config, "bot_persona_profile_id", "") or "").strip() or "default"
    )


def current_bot_nickname(
    persona_id: str,
    *,
    registry: PersonaProfileRegistry | None = None,
    config: object | None = None,
) -> str:
    """/bot status、卡片页脚、人格自称「我现在叫什么」的唯一读法：先查人格册，
    回落兼容显示名，**绝不读 ``get_login_info``**（其自身身份缓存改后不刷新，台账 #60）。"""
    record = (registry if registry is not None else get_shared_registry()).get(persona_id)
    if record is not None:
        if record.qq_nickname.strip():
            return record.qq_nickname.strip()
        if record.display_name.strip():
            return record.display_name.strip()
    if config is not None:
        return str(getattr(config, "bot_persona_display_name", "") or "").strip()
    return ""


# ---------------------------------------------------------------------------
# 热切换唯一下发口（H-1：逐项回执，半切态禁止说"已切换"）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ItemReceipt:
    """一条外观下发的回执。status ∈ {ok, failed, skipped}；skipped＝该项未表态（不切）。"""

    item: str
    status: str
    detail: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"


@dataclass(frozen=True)
class PersonaSwitchReceipt:
    persona_id: str
    items: tuple[ItemReceipt, ...]

    @property
    def attempted(self) -> tuple[ItemReceipt, ...]:
        return tuple(item for item in self.items if item.status != "skipped")

    @property
    def landed(self) -> tuple[str, ...]:
        return tuple(item.item for item in self.items if item.is_ok)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(item.item for item in self.items if item.is_failed)

    @property
    def fully_applied(self) -> bool:
        """只有真正下发的每一项都成功才算"已切换"；无一项落地或有一项失败 → False。"""
        attempted = self.attempted
        return bool(attempted) and all(item.is_ok for item in attempted)

    def summary(self) -> str:
        """按诊断卡口径出人话：点名已落/未落，半切态绝不写"已切换"。"""
        return _redact(self._summary_unlocked())

    def _summary_unlocked(self) -> str:
        if not self.attempted:
            return f"人格「{self.persona_id}」没有需要下发的外观项（昵称/签名/性别/头像均未在册）。"
        if self.fully_applied:
            return (
                f"已切换人格「{self.persona_id}」："
                + "、".join(_item_label(name) for name in self.landed)
                + " 均已下发。"
            )
        landed_text = "、".join(_item_label(name) for name in self.landed) or "无"
        failed_text = "、".join(
            f"{_item_label(item.item)}（{item.detail or '原因未知'}）" for item in self.items if item.is_failed
        )
        return (
            f"⚠ 人格「{self.persona_id}」未完全切换——已落地：{landed_text}；"
            f"未落地：{failed_text}。请按未落项排查后重试，切勿当作已完成切换。"
        )


_ITEM_LABELS_ZH = {
    "qq_profile": "QQ昵称/签名",
    "qq_avatar": "QQ头像",
    "card_avatar": "卡片头像",
    "knowledge_list": "知识清单",
    "persona_text": "人格文本",
}


def _item_label(item: str) -> str:
    return _ITEM_LABELS_ZH.get(item, item)


#: 打码真身缺失时的保守回退：只裁盘符绝对路径形态，整串留类型名级信息。
_LOCAL_PATH_FALLBACK_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"']+")
_LOCAL_PATH_FALLBACK_PLACEHOLDER = "<本机路径已隐藏>"


def _redact(text: str) -> str:
    """F-B：一切动态回执文本过中央打码件（只 import 调用，绝不改咽喉真身）。

    中央件不可用时不放开、反而更紧：盘符路径整段落段替换（宁可少信息，不可泄漏）。
    """
    value = str(text or "")
    if not value:
        return value
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )
    except ImportError:  # pragma: no cover - 中央件缺失走保守分支
        return _LOCAL_PATH_FALLBACK_RE.sub(_LOCAL_PATH_FALLBACK_PLACEHOLDER, value)
    return redact_local_secrets(value)


async def _call_status(call_api: CallApi, action: str, params: dict) -> tuple[str, str]:
    try:
        result = await call_api(action, params)
    except Exception as exc:  # noqa: BLE001 - 平台拒绝/不支持：诚实回执，不外抛半个下发
        return "failed", _redact(f"{type(exc).__name__}: {exc}")
    if isinstance(result, dict) and result.get("retcode") == 0:
        return "ok", "retcode 0"
    if isinstance(result, dict):
        return "failed", _redact(f"retcode={result.get('retcode')} msg={result.get('message', '')}")
    return "failed", f"unexpected_result_type={type(result).__name__}"


def _default_card_avatar_hook(path: str) -> None:
    """卡片头像复用既有出口 ``bot_avatar.set_local_path``（§49.4-5，不建第二条通路）。
    文件读不到必须点名（``set_local_path`` 对缺文件静默 no-op，这里补判据以出诚实回执）。
    点名只留**文件名 + 缺失原因**——全路径不进异常链，也就不会进回执/日志（F-B）。"""
    from plugins.bot_unified_runtime.domains.render.bot_avatar import set_local_path

    candidate = Path(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"{candidate.name}（本地头像文件不存在或不可读）")
    set_local_path(candidate)


def _persona_text_receipt(record: PersonaProfileRecord) -> ItemReceipt:
    """人格文本回执腿（H-1 逐项点名）：切换后文本是否真的落地，缺腿绝不默认成功。

    判据与消费腿同构（①修复后文本消费＝可调用视图每轮现读本册）：
    - 切到备用人格：在册 ``files.settings`` 非空 ⇒ 下一轮设定文本即该人格（ok，
      只报份数不报路径，F-B 同口径）；空 ⇒ 「人格文本为空」点名**未落**（failed）
      ——不为 ``.env`` 兼容位旧清单背书（H-5乙：册是唯一事实源，兼容位只服务
      未入册人格）；
    - 回切 default（主人格在册项）：override 已由命令主链读回确认清空，文本腿
      每轮现读主人格册（``_effective_persona_files``：在册清单非空⇒优先，
      空⇒回落 .env 基线装配视图），不依赖本次外观下发 ⇒ ok 并声明判据来源。
    """
    if record.is_main:
        return ItemReceipt(
            "persona_text",
            "ok",
            "回切主人格：文本腿每轮现读主人格册，在册清单优先、空则回落基线装配视图（override 已确认清空）",
        )
    settings_count = len(record.settings_files)
    if settings_count:
        return ItemReceipt(
            "persona_text",
            "ok",
            f"在册设定清单 {settings_count} 份，文本腿每轮现读册随切",
        )
    return ItemReceipt(
        "persona_text",
        "failed",
        "人格文本未落：在册 files.settings 清单为空，下一轮不会带上该人格的设定文本（需补册内清单）",
    )


def _knowledge_list_receipt(record: PersonaProfileRecord) -> ItemReceipt:
    """知识清单回执腿（H-4甲：切的是**人格自带的设定/知识文件清单**，向量库不碰）。

    判据与消费腿同构（``providers._effective_knowledge_files`` 每轮现取同一本册）：
    - 在册 ``files.knowledge`` 非空 ⇒ 下一轮静态兜底腿即用该清单（ok，只报份数
      不报路径，F-B 同口径）；
    - 册未表态 ⇒ **skipped 并点名回落口径**——回落基线清单是登记在册的兼容语义
      （与设定文本腿不同：空设定＝人格没灵魂⇒failed，空知识清单＝照旧吃基线，
      不是半切态）。绝不静默省略此项（S-IMPL-PERSONA-QQLEG：H-1 整套切换项
      「昵称/签名/头像/文本/清单」逐格点名，清单格不许缺位）。
    """
    count = len(record.knowledge_files)
    if count:
        return ItemReceipt(
            "knowledge_list",
            "ok",
            f"在册知识清单 {count} 份，静态兜底腿每轮现读册随切（向量库不碰，H-4甲）",
        )
    return ItemReceipt(
        "knowledge_list",
        "skipped",
        "册内未表态知识清单⇒静态兜底腿按基线清单继续（兼容位回落，非半切；该项未随人格改动）",
    )


async def apply_persona_profile(
    record: PersonaProfileRecord,
    *,
    call_api: CallApi,
    card_avatar_hook: Callable[[str], None] | None = None,
) -> PersonaSwitchReceipt:
    """把一个人格的外观推到 QQ + 卡片：唯一收口件，逐腿出回执。

    - 昵称+签名一发（``set_qq_profile``），空字段不进参数＝不切该项；
    - 头像一发（``set_qq_avatar``），随后卡片头像走既有 ``set_local_path``；
    - 两发独立，可能半成 ⇒ 交回 ``PersonaSwitchReceipt``，由调用方按 ``summary()`` 说话，
      半切态绝不宣称"已切换"（H-1）。
    """
    items: list[ItemReceipt] = []

    profile_params: dict = {}
    if record.qq_nickname.strip():
        profile_params["nickname"] = record.qq_nickname.strip()
    if record.qq_signature.strip():
        profile_params["personal_note"] = record.qq_signature.strip()
    # 动作册可写四样之「性别」：仅当在册明确表态（0/1/2）才拼入同发 set_qq_profile；
    # None＝不表态⇒该格零下发（绝不默认 0，绝不从名字推断，§49.9）。
    if record.qq_sex is not None:
        profile_params["sex"] = int(record.qq_sex)
    if profile_params:
        status, detail = await _call_status(call_api, "set_qq_profile", profile_params)
        items.append(ItemReceipt("qq_profile", status, detail))
    else:
        items.append(ItemReceipt("qq_profile", "skipped", "昵称与签名均空"))

    avatar_src = record.resolved_avatar
    if avatar_src:
        # F-C TOCTOU 锁：装载时的放行不作数，下发前对同一枚闸复核一次。
        sendable, gate_reason = _avatar_sendable(avatar_src)
        if not sendable:
            items.append(
                ItemReceipt("qq_avatar", "failed", _redact(f"头像出站检查未通过：{gate_reason}"))
            )
            items.append(ItemReceipt("card_avatar", "skipped", "QQ头像未过出站闸，卡片不跟随"))
            items.append(_knowledge_list_receipt(record))
            items.append(_persona_text_receipt(record))
            return PersonaSwitchReceipt(record.persona_id, tuple(items))
        status, detail = await _call_status(call_api, "set_qq_avatar", {"file": avatar_src, "skip_cache": True})
        items.append(ItemReceipt("qq_avatar", status, detail))
        if status == "ok":
            # 卡片头像在 QQ 头像落地后才跟随（§49.4-5：切完 QQ 头像再刷卡片），
            # 且复用既有 set_local_path，不新建第二条头像通路。
            hook = card_avatar_hook if card_avatar_hook is not None else _default_card_avatar_hook
            try:
                hook(avatar_src)
            except Exception as exc:  # noqa: BLE001
                items.append(ItemReceipt("card_avatar", "failed", _redact(f"{type(exc).__name__}: {exc}")))
            else:
                # 回执不带本地全路径（F-B）：落地事实本身即凭证，路径不外发。
                items.append(ItemReceipt("card_avatar", "ok", "卡片头像已登记（路径不随回执外发）"))
        else:
            items.append(ItemReceipt("card_avatar", "skipped", "QQ头像未落地，卡片暂不跟随"))
    elif record.avatar_rejected_reason:
        # 装载闸拦下的头像：failed 点名（不是「无头像」的 skipped 假成功，F-C）。
        items.append(
            ItemReceipt(
                "qq_avatar",
                "failed",
                _redact(f"册子头像在装载时已被出站闸拦下：{record.avatar_rejected_reason}"),
            )
        )
        items.append(ItemReceipt("card_avatar", "skipped", "头像未过出站闸，卡片不跟随"))
    else:
        items.append(ItemReceipt("qq_avatar", "skipped", "无头像路径"))
        items.append(ItemReceipt("card_avatar", "skipped", "无头像路径"))

    # ②清单腿：知识清单格逐项表态随没随（H-1 整套切换项，S-IMPL-PERSONA-QQLEG 补位）；
    # ③文本腿：无论外观三格落没落，切换回执必须逐项表态人格文本跟没跟（H-1）；
    # 判定失败（空清单）⇒ failed 进「未落」清单，fully_applied 随之为 False。
    items.append(_knowledge_list_receipt(record))
    items.append(_persona_text_receipt(record))

    return PersonaSwitchReceipt(record.persona_id, tuple(items))
