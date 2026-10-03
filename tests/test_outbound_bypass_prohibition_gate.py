"""Wave 4.2「B 类直 `call_api` 旁路」禁止式门（统一接入波 SEAT-U4，2026-09-21）。

> 2026-09-22 SEAT-S-W42 扩面：新增「A 类裸 `send_queue.submit` 旁路」维度（见文件
> 末 A 类段），与上半部 B 类互补、共用同一扫描面，故扩本件而非另建第二把扫全树的门。
> 分工详见 `.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-W42.md` §2/§3。

用户令：所有内容走中央调度层。规格 `docs/design/capability-orchestration-adoption-spec.md`
§4.2 定的判据原文：「根文件与 `domains/**`（sender 漏斗最底层除外）出现
`call_api("send_*` / `send_group_msg` / `send_private_msg` 即红」。本件就是那句话的
可执行形态。

它取代谁（§7 禁第三套问答）：**纯新增门，无取代对象**（规格 §7 表已把它登记为常驻新增门）。
它与 `domains/core/decision/outbound_registry.py` 的 `DirectSendEntry` 关系 =
**登记表是叙事册（人工维护、含历史注记、行号只做说明用），本件是执法表（AST 实测、
按「路径 + API + 条数」比对）**。二者不合并的理由与合并建议见
`.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-U4.md` §5。

本批**不改任何投递语义**：现存旁路全部逐条挂名豁免（每条必须是「门关旧直连分支」，
即上方 60 行内存在缺省 False 的 `getattr(config, "<*_via_queue>", False)` 卫哨），
新写的直发没有豁免表条目 ⇒ 当场红。

裁定 R-4 后的口径变更（2026-09-24T06:33Z 落码，席位 S153 同批改本件）
-----------------------------------------------------------------
上面那句「现存旁路逐条挂名豁免」**已作废**：R-4 把根文件四条投递路径的 `call_api`
直发分支一次删净，四枚 `*_via_queue` 开关同时从 `config.py` 退役 ⇒ 豁免表的两行
（cookie 两枚 / welcome+qr 两枚，合 4 处）**同批摘牌**，B 类扫描面进入**零容忍**形态：

* 豁免表为空是**结果**不是**手段**——空表必须与「实测零命中」同时成立，
  只清表不清债当场红（`test_exemption_table_covers_actual_bypasses_exactly` 双向现算）；
* 旧的「上方 60 行内有缺省 False 的 `*_via_queue` 卫哨」不再是豁免理由——卫哨键本体
  已在 `config.py` 零命中，长不回来了（`test_zero_tolerance_via_queue_sentinel_is_no_exemption`）；
* 判据名集自 R-4 起扩到文件上传两枚（`upload_group_file` / `upload_private_file`）：
  被删的四条分支里文件导出那两条走的就是它们，旧名集只认 `send_*` ⇒ 那两条一直在尺外，
  不扩则下一位手写一条 `bot.upload_group_file(...)` 门照样绿。**扩面方向＝收严，非放宽**。

折叠三口分账（2026-09-24T09:2xZ 落码，席位 S195；**旁路桶一字未动**）
-----------------------------------------------------------------
R-4 把旁路桶清空后，本件剩下的洞不在"记了什么"，而在"什么都没记"：旧扫描
（`:160-178`）把**前缀过滤写在折叠条件内部**，于是 `call_api` 通道调用点的三种结局
——折出空白（`""` / `"   "`）、折出非直发 api 名、根本折不出来（首参是 Name / 计算值）
——**合并成同一个静默 `continue`**，而本件**没有任何「不可判」名册** ⇒ 条目三本账都不进
＝第四态就地蒸发（同族已连修三处：五入口件 `_visit`／S189、齿锁两桶／S191）。

现在三种结局各有名字（`scan_send_bypasses_with_fold` 一次遍历产三本账）：

* 折出非空且命中直发前缀 → 旁路桶，判据与改造前**逐枚相等**
  （`test_bypass_bucket_unchanged_by_fold_accounting` 拿 `_fold_legacy` 旧口在真树 + 十形态
  电池上反证，且带反空跑腿）；
* 折出非空但不命中前缀 → `DecidedNonBypassSite`：一次**判定完成的结论**，放过但留名可数；
* 折出空白 / 根本折不出 → `FoldFailureSite`（可疑），**由唯一真身名册**
  `test_five_entry_seam_lock.py::_DYNAMIC_BOUNDED_SITES` 按 (路径, 函数) 认领，**册外即红**
  （`test_fold_failure_sites_are_claimed_by_unique_roster` 八腿）。

本件**不立第三本动态名账**（两本各说各话正是 S189 点名的新洞），于是名册也不是逃生门：
往那本册塞一枚权威尺扫不到的名字，五入口件「在册未扫到＝假豁免」普查先红；塞一枚
"权威尺判已折叠"的名字来藏本尺站点，本锁第⑦腿与那条普查**双向**咬住（⑥b 在内存里预演
过杀伤力）。无位置实参的 `call_api(**kw)` 是**判定边界**（没有 api 名位不构成投递），
与五入口件 `_scan_call_api_sites` 的牙 7 同一口径，由 `test_authority_ruler_fold_failures
_are_never_blinder` 末腿核对同判——真树今天该维零实例，故这条是前瞻耦合，**不是已成立的执法**。
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from dataclasses import dataclass

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"

#: 判据锁定的出站直发 API（规格 §4.2 原文两枚 + 裁定 R-4 扩面两枚，见文件头口径变更）。
SEND_API_NAMES = frozenset(
    {
        "send_group_msg",
        "send_private_msg",
        "upload_group_file",
        "upload_private_file",
    }
)

#: `call_api("<action>", …)` 首参的直发动词前缀（与 `SEND_API_NAMES` 同批改，防只扩一半）。
CALL_API_ACTION_PREFIXES = ("send_", "upload_")

#: sender 漏斗最底层＝唯一合法的协议通道本体，按规格排除在扫描面之外。
SENDER_FUNNEL_DIRS = ("domains/transport/sender/",)



@dataclass(frozen=True)
class BypassExemption:
    """一条在册旁路的豁免理由（结构保留给注毒用例；**现役表为空**，见 `BYPASS_EXEMPTIONS`）。

    R-4 之前这条数据类的存在意义是「每条豁免必须可核」；R-4 之后 B 类零容忍，
    任何人往表里塞回一行，本件的退役锁与双向互认锁会一起点名它。
    """

    path: str
    api: str
    count: int
    gate_key: str
    reason: str
    registry_ref: str


#: 已退役的四枚「门关」卫哨键（R-4 从 `config.py` 删除）。列在这里是为了让门去**现算**
#: 它们确实回不来（`test_zero_tolerance_via_queue_sentinel_is_no_exemption`），
#: 不是为了给新直发留一条"我以前有过开关"的说法。
RETIRED_VIA_QUEUE_KEYS: tuple[str, ...] = (
    "bot_group_welcome_via_queue",
    "bot_cookie_qr_via_queue",
    "bot_cookie_expiry_reminder_via_queue",
    "bot_file_export_via_queue",
)


@dataclass(frozen=True)
class ExemptionTableRetirement:
    """豁免表摘牌记录：时刻 + 裁定 + 现算证据 + 被摘条目（缺一即不可审计）。"""

    retired_at_utc: str
    ruling: str
    retired_rows: int
    retired_sites: int
    retired_apis: tuple[str, ...]
    reason: str
    evidence_cmds: tuple[str, ...]


EXEMPTION_TABLE_RETIREMENT = ExemptionTableRetirement(
    retired_at_utc="2026-09-24T06:33Z",
    ruling="裁定 R-4（统一接入波第四批根改动：四条投递路径 call_api 直发分支全删）",
    retired_rows=2,
    retired_sites=4,
    retired_apis=("send_private_msg", "send_group_msg"),
    reason=(
        "两条豁免各自挂在「缺省 False 的 *_via_queue 门关旧直连分支」上；R-4 把分支与"
        "四枚开关一次删净 ⇒ 门关分支不再存在，豁免失去宿主，同批摘牌而非留成幽灵白名单"
    ),
    evidence_cmds=(
        (
            "grep -c 'send_group_msg\\|send_private_msg\\|upload_group_file\\|upload_private_file'"
            " plugins/bot_unified_runtime/__init__.py ⇒ 字符串命中 5 处，逐条皆为注释/文档串"
            "（:4820/:5280/:6100 等），AST 判据命中 0"
        ),
        "grep -n 'via_queue' plugins/bot_unified_runtime/config.py ⇒ 零命中（键本体已退役）",
        (
            "pytest tests/test_outbound_bypass_prohibition_gate.py -q @2026-09-24T06:59:10Z"
            " ⇒ 3 failed（两行幽灵豁免 + 清点账 4≠0），本件即该三红的跟随"
        ),
    ),
)


def _collect_scan_sources(package_root: pathlib.Path) -> dict[str, str]:
    """扫描面的「文件 → 源码」表：根 `__init__.py` + `domains/**`，sender 漏斗除外。

    与判据分开成两个函数，是为了让注毒用例能**在内存里**改根文件文本再喂同一把尺
    （绝不为造一例红去写生产树）。
    """
    files = [package_root / "__init__.py"]
    files.extend(sorted((package_root / "domains").rglob("*.py")))
    sources: dict[str, str] = {}
    for file in files:
        if not file.exists():
            continue
        rel = file.relative_to(package_root).as_posix()
        if any(rel.startswith(prefix) for prefix in SENDER_FUNNEL_DIRS):
            continue
        sources[rel] = file.read_text(encoding="utf-8")
    return sources


# --------------------------------------------------------------------------- 折叠三口分账（S195）
#
# 旧尺（2026-09-24T09:0xZ 之前的 `:160-178`）把「**前缀过滤写在折叠条件内部**」，于是
# `call_api` 通道调用点的三种结局——① 折出空白（`""` / `"   "`）② 折出非直发 api 名
# ③ 根本折不出来（首参是 Name / 计算值 / 拼接）——**合并成同一个静默 `continue`**，
# 且本件当时**没有任何「不可判」名册** ⇒ 条目三本账都不进＝第四态（就地蒸发）。
# 这与本窗已连修三处同族：五入口件 `_visit`（S189，判据 `api is not None and api.strip()`）、
# 齿锁两桶（S191，折不出落第二桶并要求由唯一名册认领）。
#
# 现口径（S195）：**旁路桶一字不动**（`test_bypass_bucket_unchanged_by_fold_accounting`
# 用改造前的旧取数口逐枚等值反证），只把折叠的三种结局**各给一个名字**：
#   * 折出非空且命中直发前缀 → 旁路桶（`found`，判据与旧尺逐字节同形）；
#   * 折出非空但不命中前缀   → `DecidedNonBypassSite`（一次**判定完成的结论**，放过但留名）；
#   * 折出空白 / 根本折不出   → `FoldFailureSite`（可疑），由**唯一真身名册**
#     `test_five_entry_seam_lock.py::_DYNAMIC_BOUNDED_SITES` 按 (路径, 函数) 认领，**册外即红**。
# 本件**不立第三本动态名账**（两把尺各说各话正是 S189 点名的新洞）；名册因此不是本件的
# 逃生门——往那本册塞一枚权威尺扫不到的名字，会被五入口件自己的「在册未扫到＝假豁免」
# 普查当场打红（本锁第七腿在内存里复算这条咬合，不改任何禁写文件）。
# 无位置实参的 `call_api(**kw)` 是**判定边界**（没有 api 名位就不构成投递），与五入口件
# `_scan_call_api_sites` 的牙 7 同一口径，不再算静默丢弃：它由那条锁执法，本件另有一腿
# 断言「本尺在这一维与权威尺同判」。
# 保守方向锁死：本次改动**只让可疑集合变大**，绝不让旁路桶、`decided` 放过面或任何
# 豁免表变小（`test_authority_ruler_fold_failures_are_never_blinder` 双向核对）。

#: 五入口件名册的路径是仓根相对（`plugins/bot_unified_runtime/…`），本件的键是包根相对。
_PKG_PREFIX = "plugins/bot_unified_runtime/"
#: 模块级站点的宿主函数名占位（与五入口件 `_scan_call_api_sites` 的 `<module>` 同字面）。
_MODULE_SCOPE = "<module>"


@dataclass(frozen=True)
class FoldFailureSite:
    """`call_api` 通道上**折叠给不出合法 api 名**的一枚站点（旧尺的第四态在此显式化）。

    * ``kind="blank-fold"``：首参是字符串字面量、但 strip 后为空 ⇒ 折叠"看起来成功"却交出
      垃圾值。空串不是任何 OneBot 动作名，它既不是旁路、也不是"已判定的非旁路"。
    * ``kind="unfoldable"``：首参存在但不是字符串字面量（Name / 计算值 / 拼接 / 下标…）
      ⇒ 本尺折不出 api 名＝真不可判。
    * ``shape``：人读证据（`首参源码形 -> 折出值`），**不参与认领键**——认领只看 (path, func)，
      与齿锁 S191 第 (E) 腿同一形状，免得指纹措辞一变就成"册外"假红。
    """

    path: str
    func: str
    kind: str
    shape: str


@dataclass(frozen=True)
class DecidedNonBypassSite:
    """折叠**成功**且折出的名字不命中直发前缀 ⇒ 一次判定完成的结论（放过，但要留名可数）。"""

    path: str
    func: str
    api: str


def _shape_of(expr: ast.expr) -> str:
    """折叠失败站点的首参源码形（人读指纹，截 120）。

    不做 try/except 兜底：`ast.unparse` 对刚 `ast.parse` 成功的树不会失败，加裸 `except`
    会被 `BLE001` 打回，且真失败时让尺自身崩比静默交一个假指纹好（静默兜底＝新第四态）。
    """
    return ast.unparse(expr)[:120]


def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    """节点 id → 最近宿主函数名（BFS 外层先入、内层后入 ⇒ 后写覆盖＝取最深，方法名同理）。

    旧尺只记行号，于是「这一枚在哪个函数里」这条信息在扫描当场就被丢掉——而唯一名册的
    认领键是 (路径, 函数)，**不指认到函数就无法认领**。归属口径与五入口件 `_visit` 的
    `func_name` 一致（只在 `FunctionDef/AsyncFunctionDef` 上换栈，类体不换）。
    """
    owners: dict[int, str] = {}
    queue: list[tuple[ast.AST, str]] = [(tree, _MODULE_SCOPE)]
    head = 0
    while head < len(queue):
        node, func = queue[head]
        head += 1
        owners[id(node)] = func
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else func
            queue.append((child, inner))
    return owners


def _fold_legacy(source: str, rel: str) -> dict[tuple[str, str], list[int]]:
    """**改造前的旧取数口**（前缀过滤写在折叠条件内部），专用于「旁路桶一字不动」对照。

    逐字保留旧逻辑（含那个把三种结局压成一次 `continue` 的判据），不是文档而是尺——
    新尺若哪天悄悄改了旁路桶，本函数与它的差集当场点名。
    """
    found: dict[tuple[str, str], list[int]] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        api: str | None = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "call_api"
            and node.args
        ):
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.startswith(CALL_API_ACTION_PREFIXES)
            ):
                api = first.value
        elif isinstance(node, ast.Attribute) and node.attr in SEND_API_NAMES:
            api = node.attr
        if api is None:
            continue
        found.setdefault((rel, api), []).append(int(getattr(node, "lineno", 0)))
    return {key: sorted(lines) for key, lines in found.items()}


def scan_send_bypasses_with_fold(
    sources: dict[str, str],
) -> tuple[dict[tuple[str, str], list[int]], list[FoldFailureSite], list[DecidedNonBypassSite]]:
    """一次遍历产**三本账**：旁路桶 / 折叠失败（可疑）/ 已判定的非旁路（结论）。

    三本账由**同一次遍历、同一个折叠口**产出（齿锁 S191 同型理由）：分成两个函数各扫一遍
    ＝"投影口径与真身漂移"的第二把尺，那种洞正是本波在连修的东西。

    折叠口的三种结局各有去处（见本节上方注释块的口径），**没有任何一条 `continue` 是静默的**：
    每一条不记旁路的路径要么落 `fold_failures`，要么落 `decided`，要么是点名过的判定边界。
    """
    found: dict[tuple[str, str], list[int]] = {}
    fold_failures: list[FoldFailureSite] = []
    decided: list[DecidedNonBypassSite] = []
    for rel, source in sources.items():
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # 语法错误由静态门处理，这里如实报错不静默跳过
            raise AssertionError(f"禁止式门无法解析 {rel}: {exc}") from exc
        owners = _enclosing_functions(tree)
        for node in ast.walk(tree):
            func = owners.get(id(node), _MODULE_SCOPE)
            api: str | None = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "call_api"
            ):
                if not node.args:
                    continue  # 判定边界（无 api 名位）：五入口件牙 7 同口径，本件第七腿核对同判
                first = node.args[0]
                folded = (
                    first.value
                    if isinstance(first, ast.Constant) and isinstance(first.value, str)
                    else None
                )
                if folded is None:
                    fold_failures.append(
                        FoldFailureSite(rel, func, "unfoldable", _shape_of(first))
                    )
                    continue
                if not folded.strip():
                    fold_failures.append(
                        FoldFailureSite(rel, func, "blank-fold", f"{_shape_of(first)}->{folded!r}")
                    )
                    continue
                if not folded.startswith(CALL_API_ACTION_PREFIXES):
                    decided.append(DecidedNonBypassSite(rel, func, folded))
                    continue
                api = folded
            elif isinstance(node, ast.Attribute) and node.attr in SEND_API_NAMES:
                api = node.attr
            if api is None:
                continue
            found.setdefault((rel, api), []).append(int(getattr(node, "lineno", 0)))
    return (
        {key: sorted(lines) for key, lines in found.items()},
        sorted(fold_failures, key=lambda s: (s.path, s.func, s.kind, s.shape)),
        sorted(decided, key=lambda s: (s.path, s.func, s.api)),
    )


def scan_send_bypasses_in_sources(sources: dict[str, str]) -> dict[tuple[str, str], list[int]]:
    """对「文件 → 源码」表跑判据，返回 {(相对路径, API): [行号…]}（B 类直发唯一尺本体）。

    这是 `scan_send_bypasses_with_fold` 的**第一投影**——旁路桶语义与改造前逐枚相等
    （`test_bypass_bucket_unchanged_by_fold_accounting` 执法）；折叠失败与已判定非旁路两本账
    由同一次遍历的另两个投影承担（`scan_fold_failure_sites` / `scan_decided_non_bypass_sites`）。
    """
    return scan_send_bypasses_with_fold(sources)[0]


def scan_fold_failure_sites(sources: dict[str, str]) -> list[FoldFailureSite]:
    """折叠失败（折出空白 ∪ 根本折不出）站点（第二投影）——本件唯一"不可判"出口。"""
    return scan_send_bypasses_with_fold(sources)[1]


def scan_decided_non_bypass_sites(sources: dict[str, str]) -> list[DecidedNonBypassSite]:
    """已判定为非直发的 `call_api` 站点（第三投影，如 `get_msg` / `delete_msg`）。"""
    return scan_send_bypasses_with_fold(sources)[2]



def scan_send_bypasses(package_root: pathlib.Path) -> dict[tuple[str, str], list[int]]:
    """AST 扫描根 `__init__.py` + `domains/**`，返回 {(相对路径, API): [行号…]}。

    命中形态（只认这两类，避免把注册表里的字符串常量算成旁路）：
    ① `x.call_api("send_…" / "upload_…", …)` 首参为字符串字面量且以直发动词起头；
    ② 属性直发 `x.send_group_msg` / `x.send_private_msg` / `x.upload_group_file` /
    `x.upload_private_file`（含 `await bot.send_group_msg(...)`）。
    """
    return scan_send_bypasses_in_sources(_collect_scan_sources(package_root))


#: 现存 B 类旁路：**空表＝零容忍**（2026-09-24T06:33Z 裁定 R-4 同批摘牌，摘牌记录见
#: `EXEMPTION_TABLE_RETIREMENT`）。原两行 `(__init__.py, send_private_msg, 2)` /
#: `(__init__.py, send_group_msg, 2)` 的宿主分支（cookie 到期提醒 job、入群欢迎 notice、
#: cookie 登录二维码图片群/私聊二分支、文件导出上传分支）已随 R-4 从生产根删除，
#: 四枚 `*_via_queue` 卫哨键同批从 `config.py` 退役 ⇒ 保留任何一行都是幽灵豁免。
#: 今天起根与 `domains/**`（sender 漏斗除外）出现任何一处直发即红，**没有豁免通道**。
BYPASS_EXEMPTIONS: tuple[BypassExemption, ...] = ()



def _table() -> dict[tuple[str, str], BypassExemption]:
    return {(row.path, row.api): row for row in BYPASS_EXEMPTIONS}


def _unexempted(
    found: dict[tuple[str, str], list[int]], table: dict[tuple[str, str], BypassExemption]
) -> list[str]:
    """把「表外新写」与「条数超册」判成违规，返回人话清单。"""
    problems: list[str] = []
    for (rel, api), lines in sorted(found.items()):
        row = table.get((rel, api))
        if row is None:
            problems.append(
                f"{rel}:{lines[0]} 新写直发 `{api}`（表外旁路）——"
                f"必须改走 SendQueue/outbound_gate 或 `_send_text_through_unified_pipeline`"
            )
        elif len(lines) > row.count:
            problems.append(
                f"{rel} 的 `{api}` 实有 {len(lines)} 处 > 在册 {row.count} 处，"
                f"多出行={lines[row.count:]}（豁免按条数封顶，不给你白涨）"
            )
    return problems


# ---------- ① 执法面 ----------


def test_scan_targets_root_and_domains() -> None:
    """扫描面必须真的含根文件与 domains/**，否则整扇门是空转假绿。"""
    files = [PKG_ROOT / "__init__.py"] + sorted((PKG_ROOT / "domains").rglob("*.py"))
    assert (PKG_ROOT / "__init__.py").is_file()
    assert len(files) > 400, f"扫描面异常收缩，仅 {len(files)} 件——门形同虚设"


def test_no_unexempted_send_bypass() -> None:
    """主判据：表外直发即红（规格 §4.2「禁止式门」原句）。"""
    found = scan_send_bypasses(PKG_ROOT)
    problems = _unexempted(found, _table())
    assert not problems, "发现未登记出站直发旁路：\n" + "\n".join(problems)


def test_exemption_table_covers_actual_bypasses_exactly() -> None:
    """双向现算互认：表 ⊇ 实测 **且** 实测 ⊇ 表，两侧都要数（S153 按 R-4 现状重写）。

    旧版只数一侧（在册行的条数须等于实到条数），实测多出来的那部分靠另一条判据兜；
    今天表已空 ⇒ 单侧腿会退化成"没有行可核＝空跑"，所以两侧各自都必须是**算出来的**：

    * 实测 ⊄ 表 ⇒ 有人新写直发（零容忍，当场红）；
    * 表 ⊄ 实测 ⇒ 幽灵豁免（债已清、白名单还留着，当场红）。
    """
    found = scan_send_bypasses(PKG_ROOT)
    table = _table()
    live_keys, table_keys = set(found), set(table)
    unlisted = sorted(live_keys - table_keys)
    ghosts = sorted(table_keys - live_keys)
    assert not unlisted, f"表外直发（零容忍）：{[(k[0], k[1], found[k]) for k in unlisted]}"
    assert not ghosts, f"幽灵豁免（旁路已收编却没删行）：{ghosts}"
    for (rel, api), row in sorted(table.items()):
        assert len(found[(rel, api)]) == row.count, (
            f"豁免表漂移：{rel} `{api}` 在册 {row.count} 处、实到 {len(found[(rel, api)])} 处"
        )
    # 现役基线：B 类实测为零（此值由上面两条 + 本条共同执法，不是"达标"二字）
    assert live_keys == set(), f"B 类直发现算应为零，实到 {found}"


def test_zero_tolerance_via_queue_sentinel_is_no_exemption(tmp_path: pathlib.Path) -> None:
    """零容忍形态（继承并改写 `test_every_exempted_bypass_is_gate_closed_legacy_branch`）。

    旧判据的用途是"在册旁路必须个个是门关分支"，它**遍历豁免表**——表一空就整例空跑，
    绿得毫无内容（计数腿真空，统一波记过的同型陷阱）。本例换成三腿实算：

    ① 表空必须与实测空同时成立（只清尺不清债当场红）；
    ② 旧豁免理由的本体（四枚缺省关 `*_via_queue` 卫哨）在 `config.py` 零命中、
       且全扫描面零读点（AST 级）⇒ 没人能再援引"它有开关门"当豁免理由；
    ③ 杀伤力：合成一条**上方带 `getattr(config, "bot_group_welcome_via_queue", False)`
       卫哨**的直发，同一把尺必须点名它；去掉卫哨的同一形态同样点名（防判据只对某一种
       形态敏感）。
    """
    # ① 表空 ⇔ 实测空
    assert BYPASS_EXEMPTIONS == (), (
        "B 类豁免表自 2026-09-24T06:33Z 起退役封账；要塞回一行请先拿到新裁定"
    )
    live = scan_send_bypasses(PKG_ROOT)
    assert live == {}, f"豁免表为空而实测仍有直发 ⇒ 只清表不清债：{live}"

    # ② 卫哨键本体已退役（读 config.py 文本 + 全扫描面一次 AST 现算，不猜）
    config_text = (PKG_ROOT / "config.py").read_text(encoding="utf-8")
    read_points = _retired_key_read_points(PKG_ROOT)
    assert set(read_points) == set(RETIRED_VIA_QUEUE_KEYS), "四枚退役键须逐枚有账，不许合并计数"
    for key in RETIRED_VIA_QUEUE_KEYS:
        assert key not in config_text, f"{key} 在 config.py 复活 ⇒ 旧豁免理由被偷偷养回来"
        assert read_points[key] == [], f"{key} 在生产面仍有读点 {read_points[key]}"


    # ③ 卫哨形态不再构成豁免：带哨/不带哨各一发，同一把尺都要点名
    guarded = tmp_path / "plugins_pkg"
    (guarded / "domains").mkdir(parents=True)
    (guarded / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (guarded / "domains" / "guarded.py").write_text(
        "async def handle(bot, config):\n"
        '    if not getattr(config, "bot_group_welcome_via_queue", False):\n'
        "        await bot.send_group_msg(group_id=1, message=[])\n",
        encoding="utf-8",
    )
    plain = tmp_path / "plugins_pkg_plain"
    (plain / "domains").mkdir(parents=True)
    (plain / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (plain / "domains" / "plain.py").write_text(
        "async def handle(bot):\n    await bot.send_group_msg(group_id=1, message=[])\n",
        encoding="utf-8",
    )
    # 带哨版调用在第 3 行（卫哨 if 占第 2 行），无哨版在第 2 行——两个行号各按夹具算，不猜
    for root, rel, call_line in (
        (guarded, "domains/guarded.py", 3),
        (plain, "domains/plain.py", 2),
    ):
        hits = scan_send_bypasses(root)
        assert hits == {(rel, "send_group_msg"): [call_line]}, (
            f"{rel} 判据未命中或行号漂移，尺瞎了：{hits}"
        )
        problems = _unexempted(hits, _table())
        assert len(problems) == 1 and rel in problems[0], (
            f"{rel} 带卫哨形态被放行 ⇒ 零容忍失守：{problems}"
        )


def _is_key_reference(node: ast.AST, keys: frozenset[str]) -> str | None:
    """这个节点是不是「把某个在册键当名字用」：属性访问 `x.key` 或 `getattr(obj, "key", …)`。

    命中返回该键名，否则 None。一次遍历核完全部键，不逐键重扫全树（四枚键各扫一遍
    是纯开销，一把门的成本要花在判据上）。
    """
    if isinstance(node, ast.Attribute):
        return node.attr if node.attr in keys else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
    ):
        value = node.args[1].value
        if isinstance(value, str) and value in keys:
            return value
    return None


def _retired_key_read_points(package_root: pathlib.Path) -> dict[str, list[str]]:
    """全扫描面里把四枚退役键当**名字**用的地方，返回 {键: [路径:行号…]}（缺键＝零读点）。

    只认 AST 节点，不认注释与叙事串——`outbound_registry.py` 的散文里写着这些键名
    （历史注记），那不该把本例判红；真正的读点（`config.bot_xxx_via_queue` /
    `getattr(config, "bot_xxx_via_queue", False)`）才是"卫哨复活"。
    """
    keys = frozenset(RETIRED_VIA_QUEUE_KEYS)
    hits: dict[str, list[str]] = {key: [] for key in RETIRED_VIA_QUEUE_KEYS}
    for rel, source in _collect_scan_sources(package_root).items():
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute | ast.Call):
                continue
            key = _is_key_reference(node, keys)
            if key is not None:
                hits[key].append(f"{rel}:{node.lineno}")
    return hits



def test_retirement_record_is_auditable() -> None:
    """摘牌必须留可复核的账（时刻/裁定/被摘枚数/证据命令），不许悄悄删两行了事。

    同时保留旧版逐行审计（理由长度 + 门关键 + 登记册指针）：表一旦被人塞回任何一行，
    这例立刻按旧标准核它——退役不等于把审计尺一起拆掉。
    """
    rec = EXEMPTION_TABLE_RETIREMENT
    assert re.fullmatch(r"2026-09-2\dT\d{2}:\d{2}Z", rec.retired_at_utc), rec.retired_at_utc
    assert "R-4" in rec.ruling, "摘牌须点名裁定"
    assert rec.retired_rows == 2 and rec.retired_sites == 4, "被摘枚数须与两行在册条数一致"
    assert rec.retired_apis == ("send_private_msg", "send_group_msg"), rec.retired_apis
    assert len(rec.reason) >= 24, "退役理由过短，不可审计"
    assert len(rec.evidence_cmds) >= 3, "须留可复跑证据命令"
    assert len(RETIRED_VIA_QUEUE_KEYS) == 4, RETIRED_VIA_QUEUE_KEYS
    for row in BYPASS_EXEMPTIONS:  # 现役空表 ⇒ 零次迭代，本例的实内容由上面各腿保证
        assert len(row.reason) >= 24, f"{row.path}/{row.api} 理由过短，不可审计"
        assert row.gate_key, f"{row.path}/{row.api} 缺门关卫哨键"
        assert "outbound_registry" in row.registry_ref, "豁免须指回叙事登记册条目"



# ---------- ② 注毒自证：这扇门真的会红 ----------


def test_poison_new_bypass_line_turns_gate_red(tmp_path: pathlib.Path) -> None:
    """注毒：新写一处 `call_api("send_group_msg"` ⇒ 扫描必命中、判据必红。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "demo").mkdir(parents=True)
    (fake / "__init__.py").write_text(
        "async def handler(bot):\n"
        '    await bot.call_api("send_group_msg", group_id=1, message=[])\n',
        encoding="utf-8",
    )
    (fake / "domains" / "demo" / "cap.py").write_text(
        "async def other(bot):\n    await bot.send_private_msg(user_id=2)\n",
        encoding="utf-8",
    )
    found = scan_send_bypasses(fake)
    assert {("__init__.py", "send_group_msg"): [2]} == {
        k: v for k, v in found.items() if k[0] == "__init__.py"
    }
    problems = _unexempted(found, {})
    assert len(problems) == 2, f"掏空豁免表后应两条全红，现={problems}"


def test_poison_sender_funnel_stays_out_of_scope(tmp_path: pathlib.Path) -> None:
    """注毒：漏斗最底层（sender/）按规格不扫——它写了也不能被当旁路，但别指望能借道藏。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "transport" / "sender").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "transport" / "sender" / "onebot.py").write_text(
        'async def f(bot):\n    await bot.call_api("send_group_msg")\n', encoding="utf-8"
    )
    assert scan_send_bypasses(fake) == {}


#: 注毒片段：**只在内存里**拼到真实根文件文本后面，绝不落盘（旧用例靠"掏空表 + 数现存
#: 4 处"自证，R-4 后现存为 0 ⇒ 那条腿空跑；换成"同一把尺对生产文本必须点名"）。
#: 三种形态各覆盖判据一半：属性直发两枚（群/私聊）+ `call_api` 字面量一枚。
_POISON_SNIPPETS: dict[str, str] = {
    "send_group_msg": (
        "async def _s153_poison_attr(bot) -> None:\n"
        "    await bot.send_group_msg(group_id=1, message=[])\n"
    ),
    "upload_group_file": (
        "async def _s153_poison_call_api(bot) -> None:\n"
        '    await bot.call_api("upload_group_file", group_id=1, file="x", name="x")\n'
    ),
    "upload_private_file": (
        "async def _s153_poison_attr_private(bot) -> None:\n"
        "    await bot.upload_private_file(user_id=2, file='x', name='x')\n"
    ),
}


@pytest.mark.parametrize("api", sorted(_POISON_SNIPPETS))
def test_poison_injected_into_root_source_in_memory_is_named_by_same_ruler(api: str) -> None:
    """杀伤力自证（取代 `test_empty_exemption_table_would_flag_all_live_bypasses`）。

    旧例的判据是「掏空豁免表 ⇒ 现存 4 处全数现形」，它同时钉了两个数：现存=4、
    表外组=2。R-4 把四条分支删净后这两个数都变 0 ⇒ 该例退化成 `0 == 0` 的空跑，
    什么也不证明。新例反过来问：**同一把尺**（`scan_send_bypasses_in_sources`）
    吃生产根文件的**真文本**，在内存里追加一条合成直发，必须点名它与其行号；
    不追加时该文件必须干净——两半各数一次，缺一即假绿。真树全程只读。
    """
    snippet = _POISON_SNIPPETS[api]
    rel = "__init__.py"
    root_text = (PKG_ROOT / rel).read_text(encoding="utf-8")
    baseline = scan_send_bypasses_in_sources({rel: root_text})
    assert baseline == {}, f"根文件今天就有直发，注毒用例失去对照物：{baseline}"

    head = root_text if root_text.endswith("\n") else f"{root_text}\n"
    poisoned_text = head + snippet
    found = scan_send_bypasses_in_sources({rel: poisoned_text})
    # 片段共两行（def + 调用），调用是末行 ⇒ 行号 = 原文件行数 + 片段行数（现算，不硬编）
    expected_line = len(head.splitlines()) + len(snippet.splitlines())
    assert found == {(rel, api): [expected_line]}, f"注毒未被同一把尺点名：{found}"
    problems = _unexempted(found, _table())
    assert len(problems) == 1 and api in problems[0], f"零容忍失守：{problems}"


def test_random_picture_domain_has_no_direct_send_bypass() -> None:
    """O5 实证锁：`domains/meme/**`（随机图/表情）零直发 ⇒ 规格 §4.2「随机图主动发
    :5959/:5965」不是随机图，那两行实为 cookie 登录二维码分支（该分支已于 R-4 删除，
    本例升为「该域任何时候都不许长出直发」的常驻反向锁）。"""
    found = scan_send_bypasses(PKG_ROOT)
    meme_hits = {key: lines for key, lines in found.items() if key[0].startswith("domains/meme/")}
    assert meme_hits == {}, f"meme 域出现新的直发旁路，需按 §4.2 收编：{meme_hits}"


@pytest.mark.parametrize("api", sorted(SEND_API_NAMES))
def test_gate_scope_excludes_only_sender_funnel(api: str) -> None:
    """口径自检：豁免前缀只有 sender 一条，且判据两半（属性名集 / call_api 前缀）不脱节。"""
    assert SENDER_FUNNEL_DIRS == ("domains/transport/sender/",)
    assert api in SEND_API_NAMES
    # 属性直发认名集、call_api 认前缀：名集里冒出一个前缀盖不住的动作，两半就脱节了
    assert api.startswith(CALL_API_ACTION_PREFIXES), (
        f"{api} 在属性名集内却不被 call_api 前缀判据覆盖 ⇒ 同一形态换个写法就逃逸"
    )



# ------------------------------------------------------------------ 折叠失败认领（唯一名册，S195）


def _unique_dynamic_roster() -> frozenset[tuple[str, str, str, str]]:
    """不可判/折叠失败站点的**唯一真身名册**（住 `test_five_entry_seam_lock.py`）。

    本件**只读**它、绝不另立第二本动态名账（齿锁 S191 同口径：两本各说各话正是 S189
    点名的新洞）。按名 import 而非复制内容：复制＝第二真身，改名即静默失联。
    """
    if str(REPO_ROOT) not in sys.path:  # 与五入口件自身同一 sys.path 口径（本仓 pytest 走 -m）
        sys.path.insert(0, str(REPO_ROOT))
    from tests.test_five_entry_seam_lock import _DYNAMIC_BOUNDED_SITES

    assert isinstance(_DYNAMIC_BOUNDED_SITES, frozenset), (
        "五入口件那本动态名册不在了或换了形态＝本件的认领指针失效，两账须同批复判"
    )
    return _DYNAMIC_BOUNDED_SITES


def roster_claim_pairs(
    roster: frozenset[tuple[str, str, str, str]] | set[tuple[str, str, str, str]],
) -> set[tuple[str, str]]:
    """名册 → 本件键形态的认领集 `{(包相对路径, 函数)}`（剥 `plugins/bot_unified_runtime/` 前缀）。"""
    return {(path.removeprefix(_PKG_PREFIX), func) for (path, func, _form, _arg) in roster}


def unclaimed_fold_failures(
    sites: list[FoldFailureSite], claims: set[tuple[str, str]]
) -> list[FoldFailureSite]:
    """册外折叠失败站点＝本件唯一允许的"违反"形态（认领之外的静默丢弃已被本改动消灭）。"""
    return [site for site in sites if (site.path, site.func) not in claims]


def _authority_scan_exclude_parts() -> tuple[str, ...]:
    """权威尺（齿锁）的扫描排除面——**按名现读，不复制字面量**。

    本件的折叠失败要与那本唯一名册对账，就得知道"同一张文件地"是哪张：本件扫描面
    （根 + `domains/**`，只剔 sender 漏斗）比权威尺**宽**，多出 `domains/ops/smoke/` 与
    `domains/core/decision/outbound_registry.py` 两块——那两块在权威尺的排除面上，
    名册**永远不可能合法认领**它们（塞进去会被五入口件「在册未扫到＝假豁免」普查当场打红）。
    复制那份字面量＝第二真身（改名即静默失联），故按名 import 同一本账。
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests.test_active_push_entry_teeth import _SCAN_EXCLUDE_PARTS

    assert isinstance(_SCAN_EXCLUDE_PARTS, tuple) and all(
        isinstance(part, str) for part in _SCAN_EXCLUDE_PARTS
    ), "齿锁排除面换了形态＝两把尺的文件地不再可比，本锁须重判"
    return _SCAN_EXCLUDE_PARTS


def on_authority_ground(rel: str) -> bool:
    """包相对路径 `rel` 是否落在两把尺共用的那张扫描地上（按齿锁同款子串判据）。"""
    keyed = f"{_PKG_PREFIX}{rel}"  # 齿锁的键是仓根相对，这里逐字复现它的匹配输入
    return not any(part in keyed for part in _authority_scan_exclude_parts())


# ---------- ③ 折叠三口分账执法面（S195 收口第四态） ----------


def test_fold_outcomes_land_in_three_named_buckets() -> None:
    """最小样本喂**本件自己的尺**：六种折叠结局必须各自落到**唯一一本账**，不再共用 `continue`。

    复现的是 S191 交回主代理的那处同型洞——旧尺对下面前四种形态的输出**逐字相同**（`{}`），
    于是"折出空白"与"判定完成的非旁路"在账面上不可区分，且没有任何一册认领前者。
    """
    rel = "synth.py"
    cases: dict[str, tuple[str, str]] = {  # 形态 → (源码, 期望归属)
        "字面空串": ('async def f(bot):\n    await bot.call_api("", group_id=1)\n', "blank-fold"),
        "字面纯空白": ('async def f(bot):\n    await bot.call_api("   ", group_id=1)\n', "blank-fold"),
        "折不出-Name": ("async def f(bot, action):\n    await bot.call_api(action)\n", "unfoldable"),
        "折不出-计算值": (
            'async def f(bot):\n    await bot.call_api("send_" + "group_msg")\n',
            "unfoldable",
        ),
        "折不出-下标": (
            'ACTION = {"a": "get_msg"}\n\n\nasync def f(bot):\n    await bot.call_api(ACTION["a"])\n',
            "unfoldable",
        ),
        "已判定非旁路": ('async def f(bot):\n    await bot.call_api("get_msg", message_id=1)\n', "decided"),
        "无位置实参": ("async def f(bot):\n    await bot.call_api(**kw)\n", "boundary"),
        "命中前缀": (
            'async def f(bot):\n    await bot.call_api("send_group_msg", group_id=1)\n',
            "bypass",
        ),
    }
    seen_kinds: set[str] = set()
    for name, (source, expect) in cases.items():
        bypass, failures, decided = scan_send_bypasses_with_fold({rel: source})
        hit_bypass = bool(bypass)
        hit_fail = {f.kind for f in failures}
        hit_decided = {d.api for d in decided}
        if expect == "bypass":
            assert bypass == {(rel, "send_group_msg"): [2]}, f"{name}：旁路桶形态漂移 {bypass}"
            assert not failures and not decided, f"{name}：真旁路被记成别的账＝桶在互相吞 {failures}{decided}"
        elif expect == "decided":
            assert hit_decided == {"get_msg"}, f"{name}：已判定非旁路没留名（旧尺正是在这里与失败态合流）"
            assert not hit_bypass and not hit_fail, f"{name}：判定结论被错记 {bypass}{failures}"
        elif expect == "boundary":
            assert not hit_bypass and not hit_fail and not hit_decided, (
                f"{name}：无 api 名位的调用不构成投递（判定边界，口径同五入口件牙 7），"
                "本例把这条锁成断言而非静默——它一旦变成入账或变成旁路都须来此复判"
            )
        else:
            assert len(failures) == 1 and failures[0].kind == expect, (
                f"{name}：折叠失败没落进可疑桶（failures={failures}）＝第四态仍在静默丢弃"
            )
            assert not hit_bypass, f"{name}：不可判被硬折成旁路＝凭空造阳 {bypass}"
            assert not hit_decided, f"{name}：折不出却记成「已判定」＝把「我不知道」写成「它没有」"
            seen_kinds.add(expect)
        if expect in {"blank-fold", "unfoldable"}:
            site = failures[0]
            assert (site.path, site.func) == (rel, "f"), f"{name}：站点没指认到函数＝无法被名册认领"
            assert site.shape, f"{name}：没留可读指纹＝只记有洞不记洞在哪"
    assert seen_kinds == {"blank-fold", "unfoldable"}, f"两种失败形态少了一格（{seen_kinds}）＝合并未拆净"


def test_bypass_bucket_unchanged_by_fold_accounting() -> None:
    """「旁路桶一字不动」硬证：真树 + 八形态电池上，新尺第一投影与**改造前旧取数口逐枚相等**。

    本席只做分账、不做改判：可疑桶变大是唯一的合法方向，旁路桶若因这次改动多一枚或少一枚
    都是失守（少了＝漏报，多了＝把"判不出"当旁路＝假阳，两种都会让人去放宽判据）。
    """
    battery = [
        'async def f(bot):\n    await bot.call_api("send_group_msg", group_id=1)\n',
        'async def f(bot):\n    await bot.call_api("upload_group_file", group_id=1)\n',
        'async def f(bot):\n    await bot.call_api("   ")\n',
        "async def f(bot, action):\n    await bot.call_api(action)\n",
        "async def f(bot):\n    await bot.call_api(**kw)\n",
        'async def f(bot):\n    await bot.call_api("get_msg", message_id=1)\n',
        "async def f(bot):\n    await bot.send_private_msg(user_id=1)\n",
        "async def f(bot):\n    await bot.upload_private_file(user_id=1)\n",
        "class C:\n    async def m(self, bot):\n        await bot.call_api(self._a)\n",
        'x = "send_group_msg"\n',
    ]
    battery_hits = 0
    for idx, source in enumerate(battery):
        rel = f"battery{idx}.py"
        new = scan_send_bypasses_in_sources({rel: source})
        old = _fold_legacy(source, rel)
        assert new == old, f"电池第 {idx} 枚旁路桶漂移：新={new} 旧={old}"
        battery_hits += sum(len(v) for v in new.values())
    # 反空跑：电池里必须真有旁路命中，否则"两侧相等"就是 `{} == {}` 的空证（计数腿真空）
    assert battery_hits >= 4, f"电池旁路命中仅 {battery_hits} 枚＝等值证的空跑，须补形态"
    sources = _collect_scan_sources(PKG_ROOT)
    real_new = scan_send_bypasses_in_sources(sources)
    real_old: dict[tuple[str, str], list[int]] = {}
    for rel, source in sources.items():
        real_old.update(_fold_legacy(source, rel))
    # 真树这一腿今天是 `{} == {}`（B 类零容忍已降为空），它的价值是**耦合**：
    # 任何人往旁路桶动手脚（放宽前缀、改属性名集判定）都会在这里与旧口分叉。
    assert real_new == real_old, f"真树旁路桶两侧不等：新={real_new} 旧={real_old}"


def test_fold_failure_sites_are_claimed_by_unique_roster() -> None:
    """真树零容忍：本面每一枚折叠失败站点都**必须由那本唯一名册按 (路径,函数) 认领**，册外即红。

    八腿各管一件事，缺一腿本锁退化成空跑：
    ① 面非空（尺没瞎）；② 册外＝红；③ 可疑桶与旁路桶不互相吞；④ `decided` 每一枚都是
    "非空且不命中前缀"的真结论（防它变成新垃圾桶）；⑤ 名册在本面内的认领必须**真有其站**
    （假认领＝名册搬家，红）；⑥ 合成册外站点不被真名册吞（豁免面不是藏人抽屉）+ ⑥b 塞名
    预演；⑦ 被认领的站点权威尺同判折不出（往名册塞名字来藏本站点 ⇒ 此腿与五入口件的
    「在册未扫到＝假豁免」普查**双向**当场红）；⑧ 本件比权威尺宽出的那两块地
    （`domains/ops/smoke/`、`domains/core/decision/outbound_registry.py`）今天不得有折叠失败
    ——那一维上名册结构上无从认领，红因写清"改源站点或同批复判两尺排除面"，**不开第三本账**。
    """
    sources = _collect_scan_sources(PKG_ROOT)
    assert len(sources) > 400, f"扫描面塌陷（{len(sources)} 件）＝本锁空跑"
    bypass, failures, decided = scan_send_bypasses_with_fold(sources)
    roster = _unique_dynamic_roster()
    claims = roster_claim_pairs(roster)

    # ② 册外即红
    offenders = unclaimed_fold_failures(failures, claims)
    assert not offenders, (
        f"折叠失败站点无人认领（{[(o.path, o.func, o.kind, o.shape) for o in offenders]}）："
        "折出空白/折不出既不是旁路也不是已判定，就是第四态静默丢——"
        "要么把该 api 名改成可判定形态，要么附现算证据收进五入口件那本唯一动态名册，"
        "绝不在本件新立一本豁免（两本各说各话＝新洞）"
    )
    # ① 非空跑：真树至少一枚折叠失败，否则 ②⑤⑥⑦ 全是测夹具
    assert failures, (
        "真树连一枚折叠失败都扫不到＝可疑桶没接到真树，上面那条「册外即红」是散文"
        f"（failures={failures}，请连同五入口件普查一起复判）"
    )
    # ③ 两桶不互吞
    assert not {(s.path, s.func) for s in failures} & set(bypass), (
        "同一枚站点既进旁路桶又进可疑桶＝折叠口在自我矛盾，账数会随遍历顺序漂"
    )
    # ④ decided 只收"真结论"
    for site in decided:
        assert site.api.strip(), f"{site.path}:{site.func} 空串混进已判定桶＝垃圾桶化"
        assert not site.api.startswith(CALL_API_ACTION_PREFIXES), (
            f"{site.path}:{site.func} 的 `{site.api}` 命中直发前缀却记成非旁路＝旁路桶漏计"
        )
    # ⑤ 名册在本面内的认领须真有其站
    surface_claims = {(path, func) for (path, func) in claims if path in sources}
    failure_pairs = {(site.path, site.func) for site in failures}
    stale = surface_claims - failure_pairs
    assert not stale, (
        f"名册认领了本面上今天并不存在的折叠失败站点（{sorted(stale)}）＝名册搬家或路径形态变了；"
        "本件的认领指针随之失效，两账须同批复判"
    )
    # ⑥ 合成册外站点不得被真名册吞（键形态不同 ⇒ 结构上藏不住）
    ghost = FoldFailureSite("domains/__s195_ghost__.py", "sneaky", "unfoldable", "action")
    assert unclaimed_fold_failures([ghost], claims) == [ghost], "合成站点被真名册认领＝名册成了藏人抽屉"
    # ⑦ 被认领者权威尺同判折不出（塞名字藏站点在这里红，不靠"记得改回来"）
    from tests.test_five_entry_seam_lock import _scan_call_api_sites

    authority_dynamic_pairs: set[tuple[str, str]] = set()
    for rel, source in sources.items():
        if not on_authority_ground(rel):
            continue  # 权威尺不扫这块地，故它在这一维不是"可对照的裁判"，由第⑧腿单独执法
        _resolved, dynamic = _scan_call_api_sites(source, rel)
        authority_dynamic_pairs |= {(path, func) for (path, func, _form, _arg) in dynamic}
    blind = [
        site
        for site in failures
        if on_authority_ground(site.path) and (site.path, site.func) not in authority_dynamic_pairs
    ]
    assert not blind, (
        f"本尺判折不出、权威尺却判已折叠（{[(b.path, b.func, b.kind) for b in blind]}）："
        "两把尺对「不可判」的定义开始各说各话，名册会被塞进权威尺不认的名字来藏旁路"
    )
    # ⑧ 本件扫描面比权威尺宽出的那两块地（smoke / outbound_registry）今天不得有折叠失败：
    #    那一维上名册结构上认领不了（塞进去必被五入口件的活性普查打红），所以要么源站点改成
    #    可判定形态，要么由两把尺的 owner 同批复判排除面——**不许**在本件新开一本豁免。
    off_ground = [site for site in failures if not on_authority_ground(site.path)]
    assert not off_ground, (
        f"共用排除面之外的地长出折叠失败（{[(o.path, o.func, o.kind) for o in off_ground]}）："
        "本尺扫得到、权威尺不扫，那本唯一名册在这块地上无从认领——请改源站点或同批复判两尺排除面"
    )
    # ⑥b 「塞名字藏站点」这条路的杀伤力预演（全程在内存里造，一个禁写文件都不碰）：
    #     真往那本册塞一枚"权威尺判已折叠"的名字，本尺这一腿会先放过（册外判据不报），
    #     但权威尺的反查必判它不是动态名 ⇒ 五入口件「在册未扫到＝假豁免」普查随后红。
    #     两把尺因此咬成一只：本件不立第二本账，也借不到第一本账藏人。
    dirty = ("__init__.py", "_handle_dirty_guard")  # 权威尺在本面**判得出来**的一枚（delete_msg）
    assert dirty not in authority_dynamic_pairs, (
        "对照物变了：权威尺如今把 `_handle_dirty_guard` 判成折不出＝本腿的预演失去靶子，须换样本"
    )
    stuffed = claims | {dirty}
    fake_site = FoldFailureSite(*dirty, "unfoldable", "self._a")
    assert unclaimed_fold_failures([fake_site], stuffed) == [], (
        "塞名后仍报册外＝认领判据没走名册，那 ② 那腿执法的是别的东西"
    )


def test_authority_ruler_fold_failures_are_never_blinder() -> None:
    """单向对齐（保守方向锁）：权威尺在本件扫描面上判折不出的每一枚，本尺也必须看见。

    本尺的折叠**弱于**五入口件（不做同帧字符串赋值折叠），所以「本尺可疑 ⊇ 权威尺动态」
    恒成立才是安全方向；反向（权威尺抓到、本尺没抓到）说明本尺在这一维彻底失明——
    最典型就是别名 `c = bot.call_api` / `getattr(bot,"call_api")` 形态（本尺只认属性直调）。
    今天真树该维**零实例**（探针 C 段 09:11:00Z 实测），所以这条现在是"若有人写就红"的
    前瞻耦合，不是已成立的执法；**不得**叙述成"别名旁路本件也挡得住"。
    """
    sources = _collect_scan_sources(PKG_ROOT)
    _bypass, failures, _decided = scan_send_bypasses_with_fold(sources)
    from tests.test_five_entry_seam_lock import _scan_call_api_sites

    authority: set[tuple[str, str]] = set()
    boundary_sites: list[str] = []
    for rel, source in sources.items():
        tree = ast.parse(source)
        if on_authority_ground(rel):
            _resolved, dynamic = _scan_call_api_sites(source, rel)
            authority |= {(path, func) for (path, func, _form, _arg) in dynamic}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "call_api"
                and not node.args
            ):
                boundary_sites.append(f"{rel}:{node.lineno}")
    mine_on_ground = {
        (site.path, site.func) for site in failures if on_authority_ground(site.path)
    }
    missed = authority - mine_on_ground
    assert not missed, (
        f"权威尺判折不出而本尺一个字没记（{sorted(missed)}）＝本尺比权威尺瞎，"
        "第四态只是搬了家；须扩本尺的被调体识别（别名/getattr 通道）或同批复判两把尺"
    )
    # 判定边界同判：无位置实参的 call_api 在两把尺上都不构成投递（一侧改口径必来此复判）
    assert not boundary_sites, (
        f"真树长出无位置实参的 call_api（{boundary_sites}）＝判定边界需重判："
        "两把尺今天都不计，若某一侧改判入账请同批改本锁与五入口件牙 7"
    )


# =========================================================================
# Wave 4.2「A 类裸 send_queue.submit 旁路」维度（SEAT-S-W42，2026-09-22 扩面）
#
# 分工（§7 禁第三套自查）：上半部（U4 建）扫 B 类 `call_api("send_*` /
# `send_group_msg` / `send_private_msg`（绕过队列的直发）；本半部扫 A 类
# 「有队列、但绕过 outbound_gate 静默窗/限流/审计的裸 `send_queue.submit`」。
# 同一扫描面（根 + domains/**，sender 漏斗除外）⇒ 合并在同一件，不建第二把
# 扫全树的门。二者互补：B 类=不排队直发，A 类=排队但不走中央闸。
# 中央投递出口 `submit_active_push` 本体在 `domains/transport/sender/`，天然豁免。
#
# 已知局限：①别名裸调 `submit = x.send_queue.submit; submit(req)` —— **2026-09-22 已收编**
# （S-BYPASS 实证该逃逸面真的吞掉了 error_report 两条在跑的投递，判据升级为
# `_submit_alias_names`：按**作用域**把绑到队列 `.submit` 的局部名一并计命中，
# 见 `test_submit_alias_is_caught_within_scope_only`）。登记这条历史不是为了记账，
# 是为了说清"清点账 6→8 那两条一直都在，是门瞎"。
# ②异名接收者（队列实例绑到词表外变量名）同样逃逸；全树唯一真实例
# （smoke.py 裸 `queue`，S-W42 后由 S-FIXB 实测发现）已扩词表收进判据面，
# 残余异名面（self.send_q/self.q/self._q 类）见
# `test_poison_divergently_named_receiver_escapes_by_design` 自证=登记的局限非判据正确。
# 收编施工图见 `.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-W42.md` §5。
# =========================================================================

#: submit 旁路的接收者标识：`send_queue`/`queue`（裸 Name）或链中属性 `.send_queue` / `._queue` / `.queue`。
#: `queue` 为 S-FIXB 账2 新增：smoke.py:1151/1152 用异名 `queue` 绑 SQLiteSendRequestQueue，
#: 系全树唯一真实异名接收者（实测登记），不扩则它静默逃逸。
SUBMIT_QUEUE_ATTRS = frozenset({"send_queue", "_queue", "queue"})


@dataclass(frozen=True)
class SubmitBypassExemption:
    """一条在册裸 submit 旁路（按文件路径计条数封顶 + 改道去向）。"""

    path: str
    count: int
    retire_to: str
    reason: str


def _queue_base_is_receiver(base: ast.expr) -> bool:
    """`<base>` 这条链是不是"队列实例"（裸名或链中属性命中词表即算）。"""
    if isinstance(base, ast.Name) and base.id in SUBMIT_QUEUE_ATTRS:
        return True
    cur: ast.expr = base
    while isinstance(cur, ast.Attribute):
        if cur.attr in SUBMIT_QUEUE_ATTRS:
            return True
        cur = cur.value
    return False


def _submit_receiver_is_queue(node: ast.Call) -> bool:
    """`<base>.submit(...)` 且 base 链含 send_queue / _queue / queue 才判命中。

    命中：send_queue.submit / self.send_queue.submit / pipeline.send_queue.submit /
    self._queue.submit / queue.submit。不命中：`submit(...)`（别名裸调——**2026-09-22 起
    由 `_submit_alias_names` 单独收编**，不再算逃逸面）、
    self.send_q/self.q/self._q（词表外异名，见局限②）、pool.submit、executor.submit、
    review_gate.submit、ledger sink.submit 等非投递队列提交（段名精确匹配，
    task_queue 类前缀近似不连带误伤）。
    """
    func = node.func
    return bool(
        isinstance(func, ast.Attribute)
        and func.attr == "submit"
        and _queue_base_is_receiver(func.value)
    )


def _own_nodes(scope: ast.AST):
    """该作用域**自己**的节点：不下钻进更内层的函数。

    没有这一步，模块作用域会把函数里的 `submit = …send_queue.submit` 当作全局绑定，
    于是另一个同名函数里的 `submit(req)` 被算成投递旁路（假阳性）。
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue  # 内层函数由它自己那一份统计负责
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _submit_alias_names(scope: ast.AST) -> set[str]:
    """该作用域内把队列 `.submit` **绑成局部名**的别名（局限①的收编判据）。

    形如 `submit = pipeline.send_queue.submit` 的赋值是 **Store 侧**、不是 Call，
    所以接收者判据结构性看不见它，随后的 `submit(req)` 就成了静默逃逸
    （S-BYPASS 实证：本门只报 `error_report.py:1037`，真正发出去的两条在 :1052/:1054，
    两个集合交集为空）。按**作用域**收别名而不是全文件一把抓：`submit` 这种短名
    在别的函数里可能指完全不同的东西，全局匹配会造出假阳性、进而逼人放宽判据。
    """
    names: set[str] = set()
    for node in _own_nodes(scope):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.Attribute) and value.attr == "submit" and _queue_base_is_receiver(
            value.value
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _file_submit_bypass_lines(tree: ast.Module) -> list[int]:
    """一个文件里所有 A 类裸 submit 行号（直调 ∪ 别名裸调），去重升序。"""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _submit_receiver_is_queue(node):
            lines.add(int(getattr(node, "lineno", 0)))
    scopes: list[ast.AST] = [
        tree,
        *(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)),
    ]
    for scope in scopes:
        aliases = _submit_alias_names(scope)
        if not aliases:
            continue
        for node in _own_nodes(scope):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in aliases
            ):
                lines.add(int(getattr(node, "lineno", 0)))
    return sorted(lines)


def scan_submit_bypasses(package_root: pathlib.Path) -> dict[str, list[int]]:
    """扫描根 + `domains/**`（sender 漏斗除外），返回 {相对路径: [submit 行号…]}。"""
    files = [package_root / "__init__.py"]
    files.extend(sorted((package_root / "domains").rglob("*.py")))
    found: dict[str, list[int]] = {}
    for file in files:
        if not file.exists():
            continue
        rel = file.relative_to(package_root).as_posix()
        if any(rel.startswith(prefix) for prefix in SENDER_FUNNEL_DIRS):
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            raise AssertionError(f"submit 旁路门无法解析 {rel}: {exc}") from exc
        lines = _file_submit_bypass_lines(tree)
        if lines:
            found[rel] = lines
    return found


#: 现存 A 类裸 submit 旁路逐条挂名（2026-09-22 实测+S-FIXB 扩词表收编：原 10 处 / 5 文件；
#: Wave 4.2/4.3 逐批改道 ⇒ root 四条主动投递已全部接中央出口、整行删净；
#: 同日 S-BYPASS 把**别名裸调**收编进判据 ⇒ 现役 8 处 / 4 文件，比旧清点多出 error_report 两条
#: ——那两条一直都在，是门瞎，不是代码变坏。计数上升一次是"补视力量"，不是新欠债。
#: 2026-10-02 聊天体验波 +1（pipeline 限流补回耗尽说明，与群失败 ack 同形）⇒ 9 处 / 4 文件）。
#: 前 4 处登记为「待改道 submit_active_push」——改道当笔删行，幽灵豁免会当场红；
#: smoke 两条为「自测器演练 submit API 本体」（临时库+fake transport 永不外发），无改道义务，
#: 但实例数一变本行照样红，逼着重估——不许借「自测」名义给门留暗门。
SUBMIT_BYPASS_EXEMPTIONS: tuple[SubmitBypassExemption, ...] = (
    SubmitBypassExemption(
        path="domains/chat_reply/runtime/pipeline.py",
        count=3,
        retire_to="主输出步:896=层1正当出口常驻在册；群失败 ack:945 与限流耗尽说明同形（自带节流的池内短句），若挂入站事件改走 _send_text_through_unified_pipeline",
        reason=(
            ":896 中央 pipeline 主输出提交步(非旁路，上游已过 gate/review/render，登记以免误判新增)；"
            ":945 群失败 ack 自带滑窗节流但绕 outbound_gate(A 类)；"
            "限流补回耗尽说明 _maybe_submit_rate_limit_exhausted_notice（2026-10-02 聊天体验波）："
            "判据/文案真身住 rate_limit、自带每收件面节流、固定文案池不过 review，与群失败 ack 同形(A 类)"
        ),
    ),
    SubmitBypassExemption(
        path="domains/ops/monitor/error_report.py",
        count=3,
        retire_to="裁定=不迁移（S-BYPASS 判定：回合内诊断面，非主动投递族）；"
                  "真要收编须先解决两件事：丢 caller 侧 deliver_after≥3s 的 A-plus 次序、"
                  "邮件键 `email:…@…` 过不了键规范（实测 False）",
        reason=(
            "错误卡两段式投递：:1037 文本回执直调、:1052/:1054 卡片补发经别名 "
            "`submit = pipeline.send_queue.submit`——**别名面 2026-09-22 已由 "
            "`_submit_alias_names` 收编进判据**（此前只登记 1 处、真发两条静默逃逸）。"
            "自带 ErrorCardGate 冷却闸但不经 outbound_gate(A 类)，且已在件内打 "
            "_GATE_BYPASS_TAG='gate:bypass_by_design'"
        ),
    ),
    SubmitBypassExemption(
        path="domains/schedule/delivery.py",
        count=1,
        retire_to="接线(生产零装配)前必须先改 submit_active_push，禁止直 submit",
        reason="S11 occurrence 投递门面 self._queue.submit(:233)——干跑件、消费者仅两测试件，非现行生产旁路",
    ),
    SubmitBypassExemption(
        path="domains/ops/smoke/smoke.py",
        count=2,
        retire_to="无改道义务：run_queue_smoke 演练队列 submit API 本体（:1133 临时库实例+fake transport 永不外发），改名或迁出扫描面前本行常驻",
        reason=(
            "异名接收者裸 `queue.submit`(:1151/:1152)——S-FIXB 账2 实测全树唯一真实例，"
            "扩 SUBMIT_QUEUE_ATTRS 收进判据面后按条数登记，量变即红"
        ),
    ),
)


def _submit_table() -> dict[str, SubmitBypassExemption]:
    return {row.path: row for row in SUBMIT_BYPASS_EXEMPTIONS}


def _unexempted_submit(
    found: dict[str, list[int]], table: dict[str, SubmitBypassExemption]
) -> list[str]:
    problems: list[str] = []
    for rel, lines in sorted(found.items()):
        row = table.get(rel)
        if row is None:
            problems.append(
                f"{rel}:{lines[0]} 新写裸 `send_queue.submit`/`._queue.submit`（表外旁路）"
                f"——改走 submit_active_push 或 _send_*_through_unified_pipeline"
            )
        elif len(lines) > row.count:
            problems.append(
                f"{rel} 裸 submit 实有 {len(lines)} 处 > 在册 {row.count} 处，多出行={lines[row.count:]}"
            )
    return problems


# ---------- A 类 submit 执法面 ----------


def test_live_submit_bypass_total_matches_ledger() -> None:
    """清点账自检：现存裸 submit **恰 9 处**。

    轨迹与口径（2026-09-22 更正本 docstring——它一直写着"6 处"而断言是 8，
    典型的注释比代码先腐烂）：原 10 处 → Wave 4.2/4.3 把 root 四条改走中央出口 = 6 处 →
    别名入口收编时把扫描面按作用域修正，**又照出两条一直都在的**（门瞎，不是码坏）= 8 处 →
    2026-10-02 聊天体验波在 pipeline 加限流补回耗尽说明一条（与群失败 ack 同形、
    在册 A 类，见豁免表该行 reason）= 9 处。
    "只准降"由**逐文件豁免表**执法（多一处红、少一处也红＝幽灵豁免锁），
    本条总数断言只作自检：改站点数必须同时改表，逼人来核。
    """
    found = scan_submit_bypasses(PKG_ROOT)
    assert sum(len(v) for v in found.values()) == 9, found


def test_no_unexempted_submit_bypass() -> None:
    """主判据：表外新写、或同文件条数超册 ⇒ 红。"""
    found = scan_submit_bypasses(PKG_ROOT)
    problems = _unexempted_submit(found, _submit_table())
    assert not problems, "发现未登记裸 submit 旁路：\n" + "\n".join(problems)


def test_submit_exemption_table_covers_actual_exactly() -> None:
    """幽灵豁免锁：改道后没删行 ⇒ 实到 < 在册 ⇒ 红（机器替代「记得改回来」）。"""
    found = scan_submit_bypasses(PKG_ROOT)
    for rel, row in _submit_table().items():
        actual = len(found.get(rel, []))
        assert actual == row.count, (
            f"submit 豁免表漂移：{rel} 在册 {row.count} 处、实到 {actual} 处——改道后删行，别留幽灵豁免"
        )


def test_submit_exempted_rows_carry_retire_plan() -> None:
    """每条 submit 豁免必须给「改道去向 + 可审计理由」（防一格一词糊门）。"""
    for row in SUBMIT_BYPASS_EXEMPTIONS:
        assert row.retire_to and len(row.retire_to) >= 12, f"{row.path} 缺改道去向"
        assert len(row.reason) >= 24, f"{row.path} 理由过短，不可审计"


# ---------- A 类 submit 注毒自证 ----------


def test_poison_new_submit_bypass_forms_turn_red(tmp_path: pathlib.Path) -> None:
    """注毒：四种接收者形态各造一处 ⇒ 全命中且掏空表后全红（含 S-FIXB 扩的裸 `queue` 异名）。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "demo").mkdir(parents=True)
    (fake / "__init__.py").write_text(
        "def a(send_queue, req):\n    send_queue.submit(req)\n",  # 裸 Name send_queue
        encoding="utf-8",
    )
    (fake / "domains" / "demo" / "cap.py").write_text(
        "class C:\n"
        "    def b(self, req):\n        self.send_queue.submit(req)\n"  # self.send_queue
        "    def c(self, req):\n        self._queue.submit(req)\n",  # self._queue
        encoding="utf-8",
    )
    (fake / "domains" / "demo" / "renamed.py").write_text(
        "def d(queue, req):\n    queue.submit(req)\n",  # 异名裸 Name（smoke 同款，已收编判据面）
        encoding="utf-8",
    )
    found = scan_submit_bypasses(fake)
    assert found == {
        "__init__.py": [2], "domains/demo/cap.py": [3, 5], "domains/demo/renamed.py": [2],
    }, found
    assert len(_unexempted_submit(found, {})) == 3  # 三个文件各一组问题


def test_submit_alias_is_caught_within_scope_only(tmp_path: pathlib.Path) -> None:
    """别名裸调判据的两面：作用域内必须抓到，作用域外不得假阳性。

    收编前这里是一条"如实登记的逃逸面"自证（S-BYPASS 用它证明门瞎——error_report 真发的
    两条一直落在逃逸面里）；收编后同一形态必须命中。反向半边同样重要：`submit` 这种短名
    在别的函数里可能指线程池或别的东西，全局匹配会造出假阳性，而假阳性的下场是逼人放宽
    判据——那比漏报更常发生。
    """
    fake = tmp_path / "plugins_pkg"
    (fake / "domains").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "alias.py").write_text(
        "def f(pipeline, req):\n"
        "    submit = pipeline.send_queue.submit\n"  # 队列 .submit 绑成局部名
        "    submit(req)\n",  # 别名裸调：现在必须命中
        encoding="utf-8",
    )
    (fake / "domains" / "unrelated.py").write_text(
        "def g(pool, req):\n"
        "    submit = pool.submit\n"  # 线程池，不是投递队列
        "    submit(req)\n",
        encoding="utf-8",
    )
    (fake / "domains" / "otherscope.py").write_text(
        "def h(req):\n"
        "    submit(req)\n"  # 本作用域内没有队列绑定 ⇒ 不算命中
        "\n"
        "\n"
        "def k(pipeline, req):\n"
        "    submit = pipeline.send_queue.submit\n"
        "    submit(req)\n",  # 这个作用域里有绑定 ⇒ 命中
        encoding="utf-8",
    )
    found = scan_submit_bypasses(fake)
    assert found == {
        "domains/alias.py": [3],
        "domains/otherscope.py": [7],
    }, found


def test_poison_divergently_named_receiver_escapes_by_design(tmp_path: pathlib.Path) -> None:
    """自证已知局限②：词表外异名接收者（self.send_q/self.q/self._q）判据扫不到=ESCAPED。

    这是登记的局限、不是判据正确——2026-09-22 实测全树该形态零真实例（唯一异名
    接收者 smoke 裸 `queue` 已扩词表收编）；将来新队列变量起异名时不许默认本门能挡，
    要么扩段名表（登记式，幽灵行照样红）要么改道 central 出口让旁路本体消失。
    """
    fake = tmp_path / "plugins_pkg"
    (fake / "domains").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "altname.py").write_text(
        "class C:\n"
        "    def a(self, req):\n        self.send_q.submit(req)\n"
        "    def b(self, req):\n        self.q.submit(req)\n"
        "    def c(self, req):\n        self._q.submit(req)\n",
        encoding="utf-8",
    )
    assert scan_submit_bypasses(fake) == {}


def test_non_queue_submit_is_not_flagged(tmp_path: pathlib.Path) -> None:
    """反向锁：线程池/审核门/账本 sink 的 .submit 不得被当旁路（防豁免表被误报淹没）。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "noise.py").write_text(
        "def f(pool, gate, sink, ex, req):\n"
        "    pool.submit(req)\n    gate.review_gate.submit(req)\n"
        "    sink._ledger_sink.submit(req)\n    ex.executor.submit(req)\n",
        encoding="utf-8",
    )
    assert scan_submit_bypasses(fake) == {}


def test_sender_funnel_submit_stays_out_of_scope(tmp_path: pathlib.Path) -> None:
    """中央投递出口 `submit_active_push` 本体（sender 漏斗）天然豁免，不误伤。"""
    fake = tmp_path / "plugins_pkg"
    (fake / "domains" / "transport" / "sender").mkdir(parents=True)
    (fake / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (fake / "domains" / "transport" / "sender" / "outbound_gate.py").write_text(
        "def submit_active_push(send_queue, req):\n    return send_queue.submit(req)\n",
        encoding="utf-8",
    )
    assert scan_submit_bypasses(fake) == {}
