"""命令目录生成器：从帮助注册表与路由 manifest 自动生成 docs/command-catalog.md。

数据真相源（全部静态提取，绝不 import 插件包——包导入会触发 NoneBot 装配，
脚本必须能脱离 bot 独立运行）：
- domains/chat_reply/capabilities/echo.py 的 ``_HELP_ENTRIES``（命令注册表）、
  ``_HELP_ENTRY_META``（结构化元数据）、``_HELP_EXTRA_LINES``（追加说明）；
- runtime/base_router.py 的 ``build_interface_manifest``（接口清单）、
  ``RouteKind``（路由 kind）与 ``INTERNAL_CAPABILITY_NOTES``（无帮助主题的内部路由能力）；
- runtime/aliases.py 的 ``DEFAULT_VERB_MAP``（昵称动词 → capability id）。

单一事实源纪律（HELP-1/HELP-2，2026-09-20）：``detail`` 的【指令与参数】段在 echo.py
里已不再手写，改由 ``_compose_help_detail()`` 从 ``lines[]`` 装配期派生。本脚本**绝不
重写**那份派生逻辑（重写＝造第二事实源，正是归一在治的病），而是按 AST 取 echo.py
中该定义的**源码片段**就地 exec——实现仍只有 echo.py 一份：它改这里自动跟随，它改名
或删定义这里立刻抛错（宁红不静默漂移）。

用法：``python scripts/command_catalog.py --write`` 写盘；无参数为校验模式
（目录过期时打印提示并返回 1，供测试与 CI 拦截）。
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
# v21r2 RWC3：echo 真身迁 domains/chat_reply/capabilities/（静态提取必指真身）。
ECHO_SOURCE = (
    ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "capabilities" / "echo.py"
)
ROUTER_SOURCE = ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "base_router.py"
ALIASES_SOURCE = ROOT / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "runtime" / "aliases.py"
DOC = ROOT / "docs" / "command-catalog.md"

_MANIFEST_KEYS = (
    "interface_id",
    "label",
    "status",
    "route_kind",
    "priority",
    "description",
    "help_topic",
    "internal_note",
)


def _module_tree(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # 多代理共享工作树：给出可归因的失败提示
        raise RuntimeError(
            f"{path.name} 语法解析失败（第 {exc.lineno} 行）："
            "该文件可能正被其他代理并发修改；确认改动归属后重试"
        ) from exc


def _literal_assign(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        target = getattr(node, "target", None)
        targets = node.targets if isinstance(node, ast.Assign) else [target]
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if name in names:
            # 只有 Assign / AnnAssign / AugAssign 这类语句才带 value；`ast.stmt` 基类没有该属性，
            # 故取一次并显式判空（判空分支对三型赋值语句恒不成立，只为让类型面收口）。
            value = getattr(node, "value", None)
            if value is None:
                raise ValueError(f"assignment has no value: {name}")
            return ast.literal_eval(value)
    raise ValueError(f"assignment not found: {name}")


def _entries() -> list[dict[str, object]]:
    value = _literal_assign(_module_tree(ECHO_SOURCE), "_HELP_ENTRIES")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("_HELP_ENTRIES is not a list of dictionaries")
    return value


def _entry_meta() -> dict[str, dict[str, object]]:
    value = _literal_assign(_module_tree(ECHO_SOURCE), "_HELP_ENTRY_META")
    if not isinstance(value, dict):
        raise TypeError("_HELP_ENTRY_META is not a dict")
    return value


def _extra_lines() -> dict[str, tuple[str, ...]]:
    value = _literal_assign(_module_tree(ECHO_SOURCE), "_HELP_EXTRA_LINES")
    if not isinstance(value, dict):
        raise TypeError("_HELP_EXTRA_LINES is not a dict")
    return value


def _manifest_entries() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for node in ast.walk(_module_tree(ROUTER_SOURCE)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "InterfaceEntry"
        ):
            args = [ast.literal_eval(arg) for arg in node.args]
            item = dict(zip(_MANIFEST_KEYS, args))
            for kw in node.keywords:
                if kw.arg and kw.arg in _MANIFEST_KEYS:
                    item[kw.arg] = ast.literal_eval(kw.value)
            out.append(item)
    return out


def _internal_capability_notes() -> dict[str, str]:
    value = _literal_assign(_module_tree(ROUTER_SOURCE), "INTERNAL_CAPABILITY_NOTES")
    if not isinstance(value, dict):
        raise TypeError("INTERNAL_CAPABILITY_NOTES is not a dict")
    return value


def _route_kind_values() -> list[str]:
    """按声明顺序取 RouteKind 枚举成员的字符串取值。"""
    values: list[str] = []
    for node in ast.walk(_module_tree(ROUTER_SOURCE)):
        if isinstance(node, ast.ClassDef) and node.name == "RouteKind":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                    values.append(str(stmt.value.value))
    return values


def _route_kind_member_values() -> dict[str, str]:
    """RouteKind 成员名 → 字符串取值，供路由规则行解析。"""
    pairs: dict[str, str] = {}
    for node in ast.walk(_module_tree(ROUTER_SOURCE)):
        if isinstance(node, ast.ClassDef) and node.name == "RouteKind":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            pairs[target.id] = str(stmt.value.value)
    return pairs


def _route_capabilities() -> list[tuple[str, str]]:
    """路由表 build_route_rules() 内的 (kind 取值, capability id)，按源码顺序去重。

    只扫该函数段：classify_message_route 等处的 RouteDecision（如空消息 IGNORE
    兜底）不是路由表行，混入会虚增规则数。
    """
    members = _route_kind_member_values()
    tree = _module_tree(ROUTER_SOURCE)
    source_lines = ROUTER_SOURCE.read_text(encoding="utf-8").splitlines()
    segment = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build_route_rules":
            segment = "\n".join(source_lines[node.lineno - 1 : node.end_lineno])
            break
    if not segment:
        raise ValueError("build_route_rules not found")
    seen: list[tuple[str, str]] = []
    for member, capability_id in re.findall(r'RouteKind\.([A-Z_]+),\s*"([a-z_.]+)"', segment):
        pair = (members.get(member, member.lower()), capability_id)
        if pair not in seen:
            seen.append(pair)
    return seen


def _route_capability_ids() -> set[str]:
    return {capability_id for _, capability_id in _route_capabilities()}


def _alias_capability_ids() -> set[str]:
    value = _literal_assign(_module_tree(ALIASES_SOURCE), "DEFAULT_VERB_MAP")
    if not isinstance(value, dict):
        raise TypeError("DEFAULT_VERB_MAP is not a dict")
    return set(value.values())


# echo.py 中「由 lines[] 派生 detail 的【指令与参数】段」这条链的**全部**模块级定义。
# 少列一个 ⇒ 就地 exec 时 NameError（响亮失败）；多列一个而 echo 已删 ⇒ 下面的
# missing 检查抛错。两种情况都逼人来同步，绝不静默退化成"生成器自己抹一份"。
_HELP_DERIVATION_NAMES: tuple[str, ...] = (
    "_HELP_COMMAND_SECTION_HEADER",
    "_HELP_INTRO_HEADER",
    "_HELP_NARRATIVE_HEADER_RE",
    "_derive_help_command_section",
    "_compose_help_detail",
)

_HELP_COMPOSER_CACHE: dict[str, Callable[[str, list[str]], str]] = {}


def _echo_help_detail_composer() -> Callable[[str, list[str]], str]:
    """返回 echo.py 的派生函数 ``_compose_help_detail`` 本体（同一份实现，零复制）。

    为什么用「AST 取源码片段 + 隔离命名空间 exec」而不是 import：
    import 插件包会触发 NoneBot 装配（本脚本的既有约束是能脱离 bot 独跑）；
    而在本文件里另写一份拼接逻辑会造出第二个事实源——HELP-1 归一治的就是这个病。
    exec 的是 echo.py 的原语句，因此真源仍只有一份：它改了这里自动跟随。
    """
    cached = _HELP_COMPOSER_CACHE.get("compose_help_detail")
    if cached is not None:
        return cached
    source = ECHO_SOURCE.read_text(encoding="utf-8")
    tree = _module_tree(ECHO_SOURCE)
    namespace: dict[str, object] = {"__name__": "command_catalog_echo_derivation", "re": re}
    defined: set[str] = set()
    for node in tree.body:
        names: set[str] = set()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
        hits = names.intersection(_HELP_DERIVATION_NAMES)
        if not hits:
            continue
        segment = ast.get_source_segment(source, node)
        if not segment:
            raise RuntimeError(
                f"{ECHO_SOURCE.name}：取不到 {sorted(hits)} 的源码片段，无法复用派生真源"
            )
        exec(  # noqa: S102 - 输入源固定为仓内 `ECHO_SOURCE`（帮助注册表真身，非任何外部/用户输入）：
            # 这里执行的是从该文件按 AST 原样取出的**模块级定义语句**，目的正是复用而非重写
            # echo.py 的派生实现。改成"在这里再拼一遍"才是本波在治的第二事实源缺陷。
            compile(segment, f"{ECHO_SOURCE.name}::<help-derivation>", "exec"),
            namespace,
        )
        defined.update(hits)
    missing = [name for name in _HELP_DERIVATION_NAMES if name not in defined]
    if missing:
        raise RuntimeError(
            f"{ECHO_SOURCE.name} 里找不到帮助文案派生真源 {missing}；"
            "请同步本脚本的 _HELP_DERIVATION_NAMES——禁止在生成器里另抄一份派生逻辑"
        )
    composer = namespace["_compose_help_detail"]
    if not callable(composer):
        raise TypeError(f"{ECHO_SOURCE.name} 的 _compose_help_detail 不可调用（派生真源形状变了）")
    fn = cast("Callable[[str, list[str]], str]", composer)
    _HELP_COMPOSER_CACHE["compose_help_detail"] = fn
    return fn


def merged_entries() -> list[dict[str, object]]:
    """把元数据与追加说明按 echo.py 运行时的同一套合并规则并回注册表。

    与 ``echo.py`` 的 ``_HELP_ENTRIES`` 装配循环逐语句同构（extras 并 lines →
    META setdefault → detail 的【指令与参数】段按 lines 派生），派生调用
    ``_echo_help_detail_composer()`` 拿到的 echo 原函数；
    ``tests/test_documentation_consistency.py::test_runtime_help_entries_match_static_merge``
    钉的就是这两条路径必须逐字段相等。
    """
    extra = _extra_lines()
    meta = _entry_meta()
    compose_detail = _echo_help_detail_composer()
    merged = [dict(entry) for entry in _entries()]
    for entry in merged:
        additions = extra.get(str(entry.get("topic")), ())
        if additions:
            entry["lines"] = [*_seq(entry.get("lines")), *additions]
        for key, value in meta.get(str(entry.get("topic")), {}).items():
            entry.setdefault(key, value)
        entry["detail"] = compose_detail(
            str(entry.get("detail") or ""),
            [str(line) for line in _seq(entry.get("lines"))],
        )
    return merged


def _text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return "；".join(str(item) for item in value)
    return str(value or "")


def _seq(value: object) -> list[object]:
    """把 `dict[str, object]` 里的序列值收成列表（与 `_text` 同一条窄化口径）。

    `merged_entries()` / `render()` 处理的条目全是 `dict[str, object]`，
    取值后直接 `len()` 或 `for` 迭代会让类型面看到 `object`；非序列（含缺省 None）一律视作空。
    """
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def render(entries: list[dict[str, object]]) -> str:
    admin_count = sum(1 for item in entries if item.get("admin_only"))
    alias_count = sum(len(_seq(item.get("aliases"))) for item in entries)
    network_topics = [str(item["topic"]) for item in entries if item.get("network") is True]
    local_topics = [str(item["topic"]) for item in entries if item.get("network") is False]
    image_topics = [str(item["topic"]) for item in entries if item.get("html_image") is True]
    internal_notes = _internal_capability_notes()
    rules = _route_capabilities()
    manifest = _manifest_entries()
    topics = {str(item.get("topic")) for item in entries}

    lines = [
        "# 守岸人命令与教程目录",
        "",
        "> 本文件由 `scripts/command_catalog.py` 从 `domains/chat_reply/capabilities/echo.py` 的帮助注册表与",
        "> `runtime/base_router.py` 的路由/接口清单自动生成。不要手工修改；",
        "> 修改帮助页数据后运行 `python scripts/command_catalog.py --write`。",
        "> `/bot help`、`/bot help <模块>` 与本目录共享同一数据源。",
        "",
        f"- 模块数：{len(entries)}",
        f"- 别名数：{alias_count}",
        f"- 普通用户可用模块：{len(entries) - admin_count}；仅管理员模块：{admin_count}",
        f"- 路由规则数：{len(rules)}；其中登记为内部能力：{len(internal_notes)}",
        "",
        "## 使用入口",
        "",
        "- `/bot help`：查看当前用户有权限看到的模块总览。",
        "- `/bot help <模块>`：查看一个模块的参数、效果、权限和示例。",
        "- `/bot commands`：输出机器可读命令目录。",
        "- `守岸人 <命令>`、`岸宝 <命令>`：在昵称触发已配置时等价于对应自然语言入口。",
        "",
        "## 新用户教程",
        "",
        "### 这个机器人能做什么",
        "",
        (
            f"- 全部 {len(entries)} 个模块都列在本文件「模块详情」里；普通用户可直接使用其中 "
            f"{len(entries) - admin_count} 个公开模块，其余 {admin_count} 个为管理员诊断与配置模块。"
        ),
        (
            "- 能力横跨人格闲聊、链接解析、点歌、天气、行情、占卜、提醒、订阅推送、"
            "表情包、下载与一整套管理员运维命令；全部 "
            f"{len(entries)} 个模块逐个列在下方「模块详情」，公开模块名单以 /bot help 为准。"
        ),
        "",
        "### 怎么开始聊天",
        "",
        (
            "- 群聊：@机器人，或直接用昵称点名（如「守岸人」「岸宝」）后说话；自然语言不用记命令，"
            "例如「天气 上海」「点歌 晴天」「12点提醒我写作业」。"
        ),
        "- 私聊：在白名单内可直接发消息；机器人主动搭话受好感度门控（好感达到亲近档才会主动开口）。",
        "- 想被称呼特定名字：请管理员用 `/bot identity set <昵称>` 设定本会话称呼（只影响称呼与语气，人格不变）。",
        "",
        "### 怎么查看所有功能 / 单个模块",
        "",
        "- `/bot help`：按权限返回模块总览（管理员会多看到诊断与配置模块）。",
        "- `/bot help <模块>`：看单个模块的参数、取值范围、权限与示例，如 `/bot help 点歌`（别名同样可用，如 `/bot help music`）。",
        "- `/bot commands`：机器可读目录（路由表 + 命令清单），脚本与文档也以它对账。",
        "- 本文件：离线可读的全部模块教程，与帮助页同源生成。",
        "",
        "### 怎么修改运行时参数",
        "",
        "- `/bot runtime get <KEY>`：看参数实际生效值（标注来自运行时覆盖还是 .env 默认）。",
        "- `/bot runtime set <KEY> <VALUE>`：热改参数，立即生效、持久保存、重启保留；只接受 SETTABLE_KEYS 白名单内的键，发错键会列出可用键。",
        "- `/bot runtime reset [KEY]`：撤销热改（省略 KEY = 清空全部覆盖）。",
        "- 注意：白名单外的键（如部分持久化开关）只能改 .env 后重启生效；个别装配期读取的键热改后也要重启。",
        "",
        "### 哪些命令只有管理员能用",
        "",
        (
            f"- 仅管理员模块共 {admin_count} 个，全部走 `/bot` 前缀（例如 `/bot status`、`/bot runtime`、`/bot model`），"
            "普通成员发送会收到拒绝提示；权限由六级角色体系（user/trusted/enterprise/admin/super_admin/blocked）判定。"
        ),
        "- 排障第一入口是 `/bot status`，追问原因用 `/bot why`。",
        "",
        "### 群聊和私聊有什么差别",
        "",
        "- 群聊有门禁（黑白名单、安静时间、限流句数帽、好感门）；私聊在白名单内直接对话。",
        "- 标注「群聊/私聊差异」的模块在详情里有具体行为（例如记忆：私聊=全部个人记忆，群聊=仅公开/群组两级）。",
        "- 大模型调用失败时：私聊会收到守岸人话术的失败提示，群聊保持静默不刷屏。",
        "",
        "### 哪些功能会发图片？失败怎么办？",
        "",
        "- 帮助页、行情、点歌候选等场景会渲染「釉瑚云母」卡片图；渲染失败会自动回退纯文本，功能不中断。",
        "- 当前列为图片输出的模块：" + ("、".join(image_topics) if image_topics else "（见各模块「输出形式」标注）") + "。",
        "- 下载/文件类模块输出文件段；所有命令失败时都会给出可读原因，不抛堆栈。",
        "",
        "### 哪些功能依赖网络？",
        "",
        "- 需要联网的模块：" + ("、".join(network_topics) if network_topics else "（见各模块「网络依赖」标注）") + "。",
        "- 纯本地模块：" + ("、".join(local_topics) if local_topics else "（未标注的模块以模块详情为准）") + "。",
        "- 联网模块自带重试与兜底（各模块的「失败兜底」行写明具体行为）；外部源不可用时给可读失败原因。",
        "",
        "### 高频入口速查",
        "",
        "- `/bot help` / `/bot help <模块>`：帮助总览 / 单模块教程。",
        "- `/bot commands`：机器可读命令目录。",
        "- `/bot runtime get|set|reset`：参数查询 / 热改 / 回滚。",
        "- `/bot identity set <昵称>`：设定本会话称呼（管理员）。",
        "- 昵称触发：`守岸人 天气 上海`、`/岸宝点歌 晴天`（昵称清单可用 `/bot runtime nickname list` 查看）。",
        "",
        "## 模块详情",
        "",
    ]
    for entry in entries:
        topic = _text(entry.get("topic"))
        aliases = _text(entry.get("aliases"))
        access = "仅管理员" if entry.get("admin_only") else "普通用户可用"
        lines.extend([
            f"## {topic}",
            "",
            f"- 权限：{access}",
            f"- 触发别名：{aliases}",
        ])
        if entry.get("capability"):
            lines.append(f"- 能力入口：{_text(entry.get('capability'))}")
        if entry.get("triggers_nl"):
            lines.append(f"- 自然语言触发：{_text(entry.get('triggers_nl'))}")
        if entry.get("chat_scope"):
            lines.append(f"- 群聊/私聊差异：{_text(entry.get('chat_scope'))}")
        if entry.get("network") is True:
            lines.append("- 网络依赖：需要联网")
        elif entry.get("network") is False:
            lines.append("- 网络依赖：纯本地")
        if entry.get("outputs"):
            lines.append(f"- 输出形式：{_text(entry.get('outputs'))}")
        if entry.get("html_image") is True:
            lines.append("- 会渲染卡片图：是（失败自动回退纯文本）")
        if entry.get("fallback"):
            lines.append(f"- 失败兜底：{_text(entry.get('fallback'))}")
        if entry.get("config_vars"):
            lines.append(f"- 配置变量：{_text(entry.get('config_vars'))}")
        if entry.get("examples"):
            lines.append(f"- 可复制示例：{_text(entry.get('examples'))}")
        if entry.get("tests"):
            lines.append(f"- 关联回归测试：{_text(entry.get('tests'))}")
        lines.extend([
            f"- 总览：{_text(entry.get('index'))}",
            f"- 标题：{_text(entry.get('title_line'))}",
            "",
            "### 教程",
            "",
        ])
        # 教程块的取值口径＝**派生后的 detail**（叙述小节 + 由 lines 派生的【指令与参数】段），
        # 与深页同源；else 只在 detail 被改空时兜底，正常永不走到（正常态下 detail 必含派生段）。
        derived_detail = _text(entry.get("detail"))
        if derived_detail:
            lines.extend(derived_detail.splitlines())
        else:
            lines.extend(f"- {line}" for line in _seq(entry.get("lines")))
        lines.extend(["", "### 帮助页一致性要求", "", "- 本模块的实时帮助以 `/bot help " + topic + "` 为准。", ""])

    lines.extend([
        "## 路由覆盖与内部接口",
        "",
        "### 路由规则 → 帮助模块",
        "",
        "- 路由 kind | 能力 id | 归属：",
        "",
    ])
    topic_by_capability: dict[str, str] = {}
    for entry in entries:
        for cid in re.findall(r"bot\.[a-z_]+", str(entry.get("capability", ""))):
            topic_by_capability.setdefault(cid, str(entry["topic"]))
    for kind, capability_id in rules:
        owner = topic_by_capability.get(capability_id) or internal_notes.get(capability_id) or "（未登记）"
        lines.append(f"  - {kind} | {capability_id} | {owner}")
    lines.extend([
        "",
        "### 接口清单（manifest）",
        "",
        "- interface_id | 状态 | 归属/说明：",
        "",
    ])
    for item in manifest:
        help_topic = str(item.get("help_topic") or "")
        note = str(item.get("internal_note") or "")
        owner = help_topic if help_topic in topics else (note or "（未登记）")
        lines.append(f"  - {item.get('interface_id')} | {item.get('status')} | {owner}")
    lines.extend([
        "",
        "### 内部路由能力（无独立帮助模块）",
        "",
    ])
    if internal_notes:
        for capability_id, note in internal_notes.items():
            lines.append(f"- `{capability_id}`：{note}")
    else:
        lines.append("- （无——全部路由能力均有帮助主题；接口级内部登记见上表 internal 说明。）")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    merged = merged_entries()
    expected = render(merged)
    if "--write" in sys.argv[1:]:
        DOC.write_text(expected, encoding="utf-8", newline="\n")
        print(f"wrote {DOC} ({len(expected)} bytes)")
        return 0
    actual = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    if actual != expected:
        print("command catalog is stale; run: python scripts/command_catalog.py --write")
        return 1
    print(f"command catalog is current ({len(merged)} topics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
