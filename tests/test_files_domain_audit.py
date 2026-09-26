"""文件/文档/代码「读—建—改—发」四腿的域审计锁（席位 S-T-FILES-AUDIT，需求 16 全条）。

本件只管三件事，逐条与简报的四张判定表对齐：

① **装配可达性**（(1) 读 + (2) 创建的「真通」判据）：不能只看函数存在，
   必须证明生产根文件真的调它、且结果真的进对话面/发送面。
② **单一判据不被复制**（(4) 容器）：回读半边只准走运行器；能力层不得自己
   读字节（否则「读—改—写」的第二份 containment 判据就从这里长出来）。
③ **在册未执法的账**（(2)(4) 两条腿的欠账）：用带名字的 xfail 钉在盘上，
   不许变成散文里的「以后再说」。修好后本件自己转绿。

全部离线、零网络；只读生产文件源码做静态判据，绝不写生产目录。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.core.safety_exec import action_catalog
from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ROOT_INIT = (
    _REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
)
_CAPABILITY_REGISTRY = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "runtime"
    / "capability_registry.py"
)
_FILE_EXCHANGE = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "files"
    / "capabilities"
    / "file_exchange.py"
)


def _source(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    assert source.strip(), f"{path.name} 是空的＝本判据假绿"
    return source


def _called_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


# ---------------------------------------------------------------------------
# ① 装配可达性：读腿真的进对话面，创建腿真的走统一管线
# ---------------------------------------------------------------------------


def test_ingest_read_leg_is_assembled_into_the_conversation_text() -> None:
    """(1) 读：入站归一确实调 ``read_supported_file`` 并把内容并进正文。

    并进正文＝这段内容跟着 ``IncomingMessage`` 走聊天链进模型，所以「给出反馈和
    理解」走的是 **LLM 理解**，不是纯抽取；反过来，若哪天只回显抽取结果，
    这一腿就退化成了「念文件」。
    """
    source = _source(_ROOT_INIT)
    assert "file_reader.read_supported_file(" in source, "入站不再调读取真身"
    assert "[文件内容：" in source, "读取结果不再拼进对话面"
    assert 'segment.get("type"' in source or '!= "file"' in source
    #: 读腿的门：装配期特性开关（关＝整条读腿不跑）
    assert 'feature_enabled("bot.ingress.file_read")' in source


def test_code_debug_leg_is_assembled_but_execution_is_hard_off() -> None:
    """(1) 读代码 + (4) 容器：报告走 ``run_code_debug``，而执行开关是常量 False。

    这一枚钉两件事：装配点在（不然「上传代码给我看」这条永远不通），
    且**生产装配路径不传 ``execute=``**（缺省即不跑）。
    """
    source = _source(_ROOT_INIT)
    assert "run_code_debug, saved_path" in source
    assert "asyncio.to_thread(run_code_debug" in source, "同步子进程检查必须在子线程"
    assert "execute=" not in source.split("run_code_debug, saved_path")[0][-400:], (
        "装配层出现 execute=＝在绕过「默认不执行」这条红线"
    )
    exchange = _source(_FILE_EXCHANGE)
    assert "_CODE_EXECUTION_ENABLED = False" in exchange
    assert "import subprocess" in exchange, "子进程分支还在（关态死代码），别把它读成已删"


def test_document_export_leg_reaches_the_unified_send_pipeline() -> None:
    """(2) 创建 + (3) 收发：``文件 <fmt> <主题>`` 的生成-转换-上传三段都在生产根里。

    只看 ``export_document`` 存在会读成「通」——它还要 LLM 生成、落盘走运行器、
    并且**只经统一管线**发出去（旧 ``call_api`` 直传二分支已按裁定 R-4 退役）。
    """
    source = _source(_ROOT_INIT)
    assert "_DOCUMENT_PROMPT" in source, "生成腿没了提示词真身"
    assert "export_document, markdown, fmt, out_dir" in source
    assert "_send_files_through_unified_pipeline(" in source
    export_block = source.split("_handle_admin_file_export")[1].split(
        "async def _is_admin_cookie_command"
    )[0]
    assert 'capability_id="bot.file"' in export_block
    assert "bot.call_api" not in export_block, "导出腿出现直连 call_api＝第二通路"
    assert "file_export = on_message(" in source, "导出命令在生产没有 matcher"


def test_file_capability_is_registered_once_with_its_own_id() -> None:
    """注册面（开发约束硬门 ②）：``bot.file`` 在唯一在册表上，且**只登一次**。

    枚数按 ==1 断言：多一枚＝同 id 两处登记（在册表之外另立 gate 绑定的形态，
    该表头注已写明禁止）；少一枚＝本域能力从册上消失。
    """
    registry = _source(_CAPABILITY_REGISTRY)
    assert registry.count('"bot.file"') == 1


# ---------------------------------------------------------------------------
# ② 单一判据：回读只准走运行器
# ---------------------------------------------------------------------------


#: ⚠ S-16-READBACK **已转正**（2026-09-26 S-FILES-LAND，主裁定收编波第⑤件）。
#: 原判定理由留档（回滚点＝恢复 xfail 并把 run_code_debug 改回直读）：
#: 「上传代码给我看」这条腿的回读真身在 ``file_exchange.run_code_debug``，它用
#: ``Path.read_text`` 直读整份文件——既不过运行器的受限回读口，也没有字节上限，
#: 500MB 的 .py 会被整份读进内存再 ``ast.parse``。修法（已落）＝两条读路径统一走
#: ``_confined_debug_read_text`` → ``read_confined_bytes``（缺省单根＝文件所在目录，
#: 装配层可交 ``write_policy_from_config`` 的策略），限额/禁触名册/段消毒全照问咽喉。
def test_capability_layer_has_no_read_back_of_its_own() -> None:
    """能力层不得自己回读文件字节：回读的唯一受限口是 ``read_confined_bytes``。

    「修改已有文件」要读—改—写三半；写半边存量件已锁（禁直写原语），
    读半边此前**无人执法**——没有这一枚，任何人补回读时都会顺手写一份
    ``Path.read_bytes()``，把白名单与禁触名册的判据复制成第二份。
    """
    calls = _called_names(_source(_FILE_EXCHANGE))
    for banned in ("read_bytes", "read_text", "open"):
        assert banned not in calls, f"能力层出现自带回读：{banned}"


def test_runner_is_the_only_confined_read_door_in_the_domain() -> None:
    """受限回读口只准长在运行器一侧（正向半边，与上面那枚 xfail 对拍）。"""
    domain = _REPO_ROOT / "plugins/bot_unified_runtime/domains/files"
    doors = [
        path.relative_to(_REPO_ROOT).as_posix()
        for path in sorted(domain.rglob("*.py"))
        if "def read_confined_bytes" in path.read_text(encoding="utf-8")
    ]
    assert doors == [
        "plugins/bot_unified_runtime/domains/files/sender/restricted_runner.py"
    ], f"受限回读口长出了第二处：{doors}"


def test_runner_exposes_the_modify_leg() -> None:
    """「修改」腿的三个公共口都在，且都是那颗咽喉的入口而非第二颗。"""
    for name in ("resolve_existing", "read_confined_bytes", "revise_in_place"):
        assert callable(getattr(rr, name, None)), f"缺 {name}"
    for name in ("create_bytes", "replace_bytes", "write_document"):
        assert callable(getattr(rr, name, None)), f"缺 {name}"


# ---------------------------------------------------------------------------
# ③ 在册未执法：两枚带名字的欠账钉在盘上
# ---------------------------------------------------------------------------


def test_file_write_action_is_on_the_book_with_a_role_floor() -> None:
    """正向锁：``file.write``／``file.read``／``file.send`` 在唯一动作册上，
    且各自带角色下限与风险档（册不在＝(2)(3) 两条腿连"该被谁批"都没有）。"""
    catalog = action_catalog.ACTION_CATALOG
    for action in (
        action_catalog.ActionId.FILE_READ,
        action_catalog.ActionId.FILE_WRITE,
        action_catalog.ActionId.FILE_SEND,
    ):
        spec = catalog[action]
        assert spec.semantics, f"{action.value} 没有语义说明"
        assert spec.role_floor, f"{action.value} 没有角色下限"
        assert spec.default_tier is not None, f"{action.value} 没有缺省风险档"
        assert spec.landing_domain is not None, f"{action.value} 没有落点域标签"
    assert action_catalog.adjudication_point() == "safety_exec.policy.decide"


#: ⚠ S-16-DECIDE-WIRE **已转正**（2026-09-26 S-FILES-LAND，主裁定收编波第⑥件）。
#: 原判定理由留档（回滚点＝删掉 ``file_exchange.adjudicate_file_write`` 并恢复 xfail）：
#: 「``policy.decide`` 在生产零调用点（现算＝全仓只有 outbound_gate 调自己那把 feature
#: gate），故 file.write 的角色下限 R1/trusted 与风险档**在册而未执法**；接线属调度层
#: Wave（主代理面）。」
#: 本次落的是**域内唯一出口**：``adjudicate_file_write`` 是文件域问裁决口的唯一一处，
#: 装配入口（``run_document_create``/``run_document_revise``）必须先拿它的产物才动字节。
#: ⚠ 未做（属主代理施工单，见席位日志 §施工单二）：根 ``__init__.py`` 的会话 handler
#: 尚未把真实 actor 可信级/角色喂进来，且 ``file.write`` 在册 R1 的一次性确认回路
#: （consent Wave 2）没接——缺这两件，装配入口今天只会拿到 ``ConsentRequired``→拒写
#: （fail-closed，绝不误放行）。故「导出腿」暂不切来（切了会把管理员 ``文件`` 命令打死），
#: 本锁钉的是「写盘入口向裁决口问过」这条不变量，不是「R1 已端到端放行」。
def test_file_write_actually_asks_the_adjudication_point() -> None:
    """写盘入口应当向唯一裁决点问过一遍（不再是只问路径名册）。"""
    sources = [
        _FILE_EXCHANGE,
        _REPO_ROOT / "plugins/bot_unified_runtime/domains/files/sender/restricted_runner.py",
    ]
    asked = any(
        "decide(" in _source(path) or "policy.decide" in _source(path)
        for path in sources
    )
    assert asked, "file.write 未经 safety_exec.policy.decide 裁决"
    # 域内唯一出口：整个 files 域调 decide 的非测试件只有 file_exchange 一处（不多开第二条通路）。
    domain = _REPO_ROOT / "plugins/bot_unified_runtime/domains/files"
    askers = [
        path.relative_to(_REPO_ROOT).as_posix()
        for path in domain.rglob("*.py")
        if ".decide(" in _source(path)
    ]
    assert askers == [
        "plugins/bot_unified_runtime/domains/files/capabilities/file_exchange.py"
    ], f"文件域裁决出口不止一处：{askers}"


#: ⚠ S-16-READ-HONESTY **已转正**（2026-09-26 S-FILES-LAND，主裁定收编波第⑤件，
#: 与 S-T-PDF-3 §5.2 并批落成「读诚实化三格」）。原判定理由留档（回滚点＝删
#: ``KIND_SILENCE_SENTENCES`` 的 kind 分支并恢复 xfail，同时把
#: ``test_file_ingress_failure_feedback.py`` 的被改判两断言改回 == ""）：
#: 「不支持的类型（.zip/.doc/.epub 一族）与文件已失（kind missing/unknown）在入站时
#: 既无正文也无降级措辞 ⇒ 会话面完全无反馈。措辞真身在
#: ``file_reader.file_read_failure_note``，该件本窗由 S-T-PDF-3 在写（mtime 现算
#: 45 分钟内）⇒ 本席只登记不修，交主代理落第三族句子。」——S-T-PDF-3 早已交付，
#: 安静窗内由本席落码。
def test_unsupported_or_missing_file_still_gets_a_plain_sentence() -> None:
    """(1) 的诚实半边：读不了要说「读不了」，沉默不算说过。"""
    from plugins.bot_unified_runtime.domains.files.sources import file_reader

    unknown = file_reader.FileReadResult(Path("a.zip"), "unknown", "", "a.zip")
    missing = file_reader.FileReadResult(Path("gone.md"), "missing", "")
    assert file_reader.file_read_failure_note(unknown)
    assert file_reader.file_read_failure_note(missing)
    # 反向半边（原「不许瞎猜」初衷没被推翻）：真读到内容的成功结果绝不产失败行。
    ok = file_reader.FileReadResult(Path("a.md"), "text", "有内容", "a.md")
    assert file_reader.file_read_failure_note(ok) == ""
    # 措辞唯一真身：句子来自登记表本身，不在别处另写一份。
    assert file_reader.KIND_SILENCE_SENTENCES["unknown"] in file_reader.file_read_failure_note(unknown)


#: ⚠ S-16-ALIGNED-OUTBOUND **已转正=已删**（2026-09-26 S-FILES-LAND，收编波第⑦件，
#: 与前席「该删不该接」同判）。原判定理由留档（回滚点＝恢复
#: ``build_aligned_file_outbound`` 一族与本文件第⑧节被删六例并恢复 xfail）：
#: 「``build_aligned_file_outbound`` 全仓零生产调用点，而三通道附件投递的真身在
#: domains/transport（file_gateway._deliver_mail / _deliver_telegram_document +
#: sender/nonebot.py 装配口）。要么接上它、要么删掉它——本锁在两种收敛下都会绿
#: （删掉时属性不存在＝无死账可钉）。」收敛走的是**删**：墓碑见
#: ``test_file_exchange_restricted_runner.py`` 第⑧节与 ``restricted_runner`` 文末。
def test_aligned_outbound_helper_is_wired_or_gone() -> None:
    helper = getattr(rr, "build_aligned_file_outbound", None)
    if helper is None:
        return  # 已删除＝欠账已清，判绿
    production = _REPO_ROOT / "plugins" / "bot_unified_runtime"
    callers = [
        path
        for path in production.rglob("*.py")
        if "restricted_runner.py" not in path.name
        and "build_aligned_file_outbound" in path.read_text(encoding="utf-8")
    ]
    assert callers, "三通道对齐件在册而无调用点"
