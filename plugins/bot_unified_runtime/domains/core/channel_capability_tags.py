"""渠道能力标签（``native-*``）的唯一真身（T4，2026-09-24 裁定「彻底修复＋加保险」）.

**要治的病**：渠道 tags 里的 ``native-audio`` / ``native-video`` /
``native-animation`` 三枚**能力标签**决定"音视频、动图原样进模型，还是先转译"。
它们今天能被三条路**静默抹掉**——不报错、不写日志，媒体理解只是退回 ASR/抽帧/
拼静态条（S28 现算）：

① 重跑 ``scripts/configure_axonhub_registry.py --apply``：脚本自带一张硬编码
   tags 表，`registry.update(build_registry())` 整条覆写运行时条目；
② ``/bot model update <id> tags=a,b,c``：整表替换，不保留、不提示；
③ ``.env`` 出现同名 ``BOT_MODEL_REGISTRY`` 条目：``model_router``
   ``_spec_from_dynamic_entry`` 与 ``runtime_admin._merge_registry_entries``
   都用 ``.env`` 的 tags 覆盖运行时 tags，除非 ``override_fields`` 里显式有 ``tags``。

①的根因形态是本仓最常见的那一种：**同一张表存在两份**。本件把它收成一份：
「哪条渠道声明了哪些原生媒体能力」只在这里写一次，写回脚本、重启前体检、管理员
整表替换守卫三处都从这里取，谁都不再抄。

设计口径（钉死）：
1. **能力标签 ≠ 档位标签**。``low/high/max/…`` 这类思考强度档位由管理员整表替换
   （旧语义保持）；``native-*`` 由本件在册，**不会**被 ``tags=`` 顺手带走。
2. **解释规则只有一份**：``declared_native_media_kinds`` 是「tags → 原生 kind」
   的唯一落点，``model_router`` 直接用它（装配期门与逐跳裁件本已同源，现在连
   标签前缀都同源）。为兼容既有 import 面，``model_router`` 以再导出方式暴露同名
   函数，不另立第二份实现。
3. **kind 集合不封死**：``NATIVE_MEDIA_KINDS`` 只登记"已知 kind"（用于校验与
   体检），``is_capability_tag`` 认的是 ``native-`` 前缀形态——将来加第四枚能力
   标签时守卫天然覆盖，不会因为漏登记而放过。
4. **全件零 I/O、零网络、零 config 依赖，且不 import 任何包内模块**：
   ``scripts/`` 侧经 ``scripts/channel_capability_declaration.py`` 以 AST 静态解析
   读取（与 ``board_doc_sync.py`` 读 ``board_taxonomy.py`` 同一哲学——插件根
   ``__init__.py`` 是重件，体检脚本不该为了一组常量去把 NoneBot 拉起来）。
   因此本件的模块级常量必须保持**字面量可 ``ast.literal_eval``** 的形态。
"""

from __future__ import annotations

from collections.abc import Iterable

# 标签前缀：`native-<kind>` 即一条能力声明（与 model_router 旧常量同值，已收编）
NATIVE_TAG_PREFIX = "native-"

# 已知 kind（登记用途：校验与体检；判据本身走前缀，见口径 3）
NATIVE_MEDIA_KINDS: tuple[str, ...] = ("animation", "audio", "video")

# ---------------------------------------------------------------- 唯一在册表
# entry_id -> 该渠道声明可原生接收的 kind。
# 现网真值取自 ChatBot_Runtime/data/settings/runtime_settings_shorekeeper.json
# 的 `axon-gemini-38-flash`（2026-09-24 现算：tags = low/high/max/vision/
# native-audio/native-video/native-animation）。
# 加/减一枚的合法通道：改这里 → 跑 `scripts/pre_restart_check.py` 的
# `channel_tags` 项确认在位 → 由写回脚本 `--apply` 落到运行时注册表。
CHANNEL_CAPABILITY_KINDS: dict[str, tuple[str, ...]] = {
    "axon-gemini-38-flash": ("animation", "audio", "video"),
}


def capability_tag(kind: str) -> str:
    """kind → 能力标签字面量（构造侧唯一写法，禁在调用点拼字符串）."""
    return f"{NATIVE_TAG_PREFIX}{str(kind).strip().lower()}"


def capability_tags_for(entry_id: str) -> tuple[str, ...]:
    """某渠道按声明**必须**携带的能力标签（已排序，确定性好比对）."""
    return tuple(sorted(capability_tag(kind) for kind in CHANNEL_CAPABILITY_KINDS.get(entry_id, ())))


def declared_native_media_kinds(tags: Iterable[str]) -> frozenset[str]:
    """渠道 tags → 它声明可原生接收的 kind 集合（标签解释的**唯一**落点）.

    大小写不敏感、两端空白先剥、``native-`` 后为空 kind 不算声明（与收编前的
    ``model_router`` 实现逐字节同语义，回归锁见
    ``tests/test_native_av_input.py::test_declared_native_kinds_reads_tags_case_and_space_tolerantly``）。
    """
    kinds: set[str] = set()
    for tag in tags or ():
        text = str(tag).strip().lower()
        if not text.startswith(NATIVE_TAG_PREFIX):
            continue
        kind = text[len(NATIVE_TAG_PREFIX) :].strip()
        if kind:
            kinds.add(kind)
    return frozenset(kinds)


def is_capability_tag(tag: object) -> bool:
    """这枚标签是不是能力标签（认前缀形态，不认 kind 在册表，见模块口径 3）."""
    text = str(tag or "").strip().lower()
    return text.startswith(NATIVE_TAG_PREFIX) and bool(text[len(NATIVE_TAG_PREFIX) :].strip())


def split_capability_tags(tags: Iterable[str]) -> tuple[list[str], list[str]]:
    """切成 (其余标签, 能力标签)，两侧都保持原顺序与原字面量."""
    others: list[str] = []
    capability: list[str] = []
    for tag in tags or ():
        (capability if is_capability_tag(tag) else others).append(tag)
    return others, capability


def preserve_capability_tags(
    authored: Iterable[str], existing: Iterable[str]
) -> tuple[list[str], list[str]]:
    """管理员整表替换 tags 时的守卫：档位按新值，能力标签**从旧值带过来**.

    返回 (合并后的 tags, 本次被保留下来的能力标签)。合并后顺序 = 管理员写的顺序
    在前、被保留的能力标签按字面量排序补在后；管理员自己写进来的能力标签原样生效
    （所以"加一枚能力标签"这条路完全通），重复的被去掉。

    刻意**不提供**"顺手删能力标签"的通道：摘一枚声明要走本件的在册表（一处变更
    处处跟随），而不是在聊天命令里整表替换——后者正是路②的原始事故形态。
    """
    authored_list = [str(tag).strip() for tag in authored or () if str(tag).strip()]
    _, existing_capability = split_capability_tags(existing)
    wanted = {str(tag).strip().lower() for tag in authored_list if is_capability_tag(tag)}
    carried = [tag for tag in existing_capability if str(tag).strip().lower() not in wanted]
    merged: list[str] = []
    seen: set[str] = set()
    for tag in [*authored_list, *sorted(carried, key=str.lower)]:
        if tag.lower() in seen:
            continue
        seen.add(tag.lower())
        merged.append(tag)
    return merged, sorted(carried, key=str.lower)


def missing_capability_tags(entry_id: str, tags: Iterable[str]) -> tuple[str, ...]:
    """某渠道相对声明**缺**了哪几枚能力标签（体检与写回闸共用的判据）."""
    have = {tag.lower() for tag in (tags or ()) if is_capability_tag(tag)}
    return tuple(tag for tag in capability_tags_for(entry_id) if tag.lower() not in have)
