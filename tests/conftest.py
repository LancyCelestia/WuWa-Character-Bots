"""Session-level guards for the whole test tree.

1. Autosync hook (top section): with ``BOT_AUTOSYNC=1`` (set by
   ``scripts/dev.ps1 -Task test``), regenerate the machine-owned files at
   session start so drift never reaches the resident gates; a summary is
   printed when the session finishes.  When the hash manifest is re-recorded
   the affected deliverables are named in a warning -- auto-fix stays silent
   for humans, but the change itself always leaves a trace.
2. Source-tree ``data/`` guard: fail any test that creates new files under
   the source-tree ``data/``.
3. Runtime-root isolation (L1, right below the hygiene block): ``.env`` points
   ``BOT_RUNTIME_DATA_DIR`` at the *production* runtime data root, so the test
   process displaces it to a per-pid temp root and registers the production root
   as forbidden (fail-closed ``refuse``).  Guard 2 only watches the source tree;
   without L1 a test could open the production SQLite files themselves.
4. basetemp container gate (G2, right below L1): L1 pushes the runtime root into
   ``%TEMP%``, so the only read roots ``domains/media/path_gate.py`` accepts are
   the workspace + ``%TEMP%`` + that isolated root.  A pytest container outside
   them makes every media-bearing premise die at ``logger.debug`` and produces
   fake reds; G2 refuses the whole session up front and names **which** option or
   environment variable supplied that container.  It judges the container pytest
   really derives (``--basetemp``, else ``PYTEST_DEBUG_TEMPROOT`` / the temp root),
   and additionally refuses a temp root pinned inside the protected runtime tree
   (the roster drifts with ``TMP``/``TEMP``, so the containment question alone is
   blind there).

Repo rules (AGENTS.md #2/#6): the source tree must never contain ``data/`` --
runtime paths resolve through ``scripts/runtime_paths.py`` into
``ChatBot_Runtime/`` and tests must write to ``tmp_path``.  Before and after
each of a test's setup/call/teardown phases we snapshot the repo ``data/``
directory; any file appearing mid-phase fails exactly that phase with the
list of offending paths.  Diagnostics are also appended to
``%TEMP%/g1-data-writes.log`` (outside the source tree).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 源码树零缓存守卫（S144，2026-09-22）
# ---------------------------------------------------------------------------
# 复现结论：测试进程只要以**不带** PYTHONDONTWRITEBYTECODE 的方式启动（例如
# `pytest tests/test_taxonomy_spec_gates.py` 裸跑，而非经 dev.ps1 -Task test），
# pytest 收集期 import scripts/*.py 门模块会当场在 scripts/__pycache__ 落 6~7 枚
# .pyc，被 runtime-layout 门记成"源码树有字节码"。dev.ps1 路线靠启动期同时设
# PYTHONDONTWRITEBYTECODE=1 + PYTHONPYCACHEPREFIX 兜住（scripts/dev.ps1:59-62）；
# 但"绕开 dev.ps1 的裸跑"是 AGENTS 规则 6 明确允许、且历史上被并行席反复踩到的
# 入口（S141 观察到的"亚分钟写-清四拍"正是某席裸跑写、别席清）。
# 修法＝在 conftest 这个"pytest 最早加载、且早于任何测试模块 import"的位置，把
# runtime_layout_smoke（S139 实证）同一套三通道设好，让测试树自护而非依赖调用方：
#   - sys.dont_write_bytecode：本进程（pytest）后续 import 不落 .pyc 的唯一有效闸
#     ——中途改 os.environ 对已启动解释器无效，只有这个直接生效；
#   - os.environ.setdefault：覆盖所有按环境继承起来的子进程（autosync 三件等）；
#   - PYTHONPYCACHEPREFIX：连 py_compile/compileall 这类无视 dont_write_bytecode 的
#     写也一并重定向到 Runtime，绝不进 AI 工作区。
# 三项均为"设缺省不覆盖"：dev.ps1 路线上它们本已就位⇒该守卫零行为变化；
# 只动 hygiene，绝不触碰任何判据 / 阈值 / 断言 / 门本体。
_RUNTIME_ROOT = REPO_ROOT.parent / "ChatBot_Runtime"
_PYCACHE_PREFIX = str(_RUNTIME_ROOT / "pycache")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("PYTHONPYCACHEPREFIX", _PYCACHE_PREFIX)
sys.dont_write_bytecode = True

# ---------------------------------------------------------------------------
# 测试进程 Runtime 根隔离装配（L1，2026-09-30 落地）
# ---------------------------------------------------------------------------
# 判据实现在 scripts/runtime_paths.py（L2，全仓唯一判定），执法锁＝
# tests/test_datafix_runtime_paths.py 下半部分 A 组。本段只做装配。
# 为什么非它不可：``.env`` 把 BOT_RUNTIME_DATA_DIR 指向**生产**根，而上面的 G1
# 守卫只快照源码树 data/ ⇒ "装配腿没传隔离根"的构造点（ReplyPolicyStore 之类
# __post_init__ 即 mkdir + connect + WAL）会在测试进程里直接打开生产库。台账 #66
# 那句「凡走 /bot reply 命令面的测试必须 monkeypatch shared_reply_policy_store，
# 因为 .env 的 Runtime 根指向生产、conftest 只守源码树」记的就是同一个洞——本段
# 是它的根治，旧写法继续有效（不再必需），两者都不许回退。
# 三条形态，逐枚被在册用例钉着，动本段前先读那三处：
#   ① **赋值式**调用 isolate_test_runtime_environment：函数内部就是赋值，把生产值
#      挤掉并登记成禁写根；外面套 setdefault ⇒ 带进来的生产值原样活着（B1 实测）；
#   ② 位置＝任何插件 import 之前（conftest 是 pytest 最早加载的一层，本段又在
#      conftest 自身其余段落之前）⇒ 没有测试模块导入时还看得见生产根；
#   ③ 缺省 refuse＝fail-closed：不注入 BOT_TEST_RUNTIME_GUARD_MODE，在册的只读
#      对照用例自己设 redirect；xdist 每 worker 独立进程 ⇒ 按 pid 各拿一枚隔离根。
# 不得由 runtime_paths 自行装配（那会把本段缺席洗成"一直在"＝规格明令禁止的假绿）。
# scripts/runtime_paths.py 缺席只发生在 tests/_autosync_fixture.py 拷出的骨架最小仓
# ⇒ 只容这一种缺席；真树里缝坏了由 A1 当场红，不许在本段退成"静默没装配"。
if str(REPO_ROOT) not in sys.path:  # 裸跑 pytest 时仓库根不在 sys.path（经 dev.ps1 才在）
    sys.path.insert(0, str(REPO_ROOT))

if (REPO_ROOT / "scripts" / "runtime_paths.py").is_file():
    from scripts.runtime_paths import isolate_test_runtime_environment

    _PYTEST_RUNTIME_ROOT = (
        Path(tempfile.gettempdir()) / "chatbot-pytest-runtime" / f"pid{os.getpid()}"
    )
    _DISPLACED_PROD_ROOTS: tuple[str, ...] = isolate_test_runtime_environment(
        os.environ, replacement_root=_PYTEST_RUNTIME_ROOT
    )

# ---------------------------------------------------------------------------
# basetemp 容器门守卫（G2，2026-10-04 立 · 2026-10-05 补两腿，根治台账 #76「basetemp 落在 Runtime 根下＝造出假红」）
# ---------------------------------------------------------------------------
# 机制（席 basetempisolate 四趟 A/B/C/D 现算＝cache/seat-basetempisolate/REPORT.md §4(c)）：
# 上面的 L1 把运行数据根挤进 %TEMP% 之后，``domains/media/path_gate.py::media_read_roots``
# 那份**唯一合法读根名册**＝工作区 + ``%TEMP%`` + 隔离根，**不含 ``ChatBot_Runtime`` 树**；
# 于是容器落在名册外时，``tmp_path`` 里的媒体件被容器门判 ``outside_root``，而拒读在
# ``ingest/vision_describe.py::_local_path_from_value`` **只写 ``logger.debug``** ⇒「本轮带语音/
# 带图」这条用例前提静默蒸发 ⇒ 只有断言跳序的用例因此变红（测量假象，不是被测代码坏了）；
# 不断言跳序的那些更是**失前提仍照绿**＝静默空跑。
# 本守卫＝把「容器必须是消费侧真用得上的容器」这一问收进这条中央缝，且只问**既有**判定件
# （``path_gate.contain_within`` + ``path_gate.media_read_roots``，全树判定面仍只 ``path_gate``
# 一处，见 ``tests/test_media_path_gate.py::test_single_containment_judgement_site``）：不新抄
# 名册、不开新根、不加配置键、不建新模块、不自派生第二套 tmp 根。判不过 ⇒ ``pytest.exit`` 当场
# 拒绝整场会话、点名**是哪一枚选项/环境变量**供出的根，绝不再让前提死在 debug 级。
#
# 两腿（同一次 ``contain_within`` 调用形态，各管一类，去掉任一腿都留下静默通路；
# 锁＝``tests/test_pytest_temproot_container_guard.py``）：
# ① 容器 ∈ 名册。判定输入＝**pytest 本轮真正会用的那一个容器**，按 installed
#    ``_pytest/tmpdir.py::TempPathFactory.getbasetemp``（:154-166）的派生法现算，不猜 API：
#    有 ``--basetemp`` 就用它；没有则 ``temproot = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT")
#    or tempfile.gettempdir())``，其下再落 ``pytest-of-<user>/pytest-N`` ⇒ **判父即判子**
#    （包含按段元组前缀，父在册⇒子必在册），于是不必复制 user 名、更不必调 ``getbasetemp()``。
#    这一腿补的正是复核席 guardverify2 §4 点名的洞：旧写法只读 ``--basetemp`` 字面值，
#    **环境钉而不传选项**时全盲（``PYTEST_DEBUG_TEMPROOT`` 钉进 Runtime＝#76 事故原形，
#    实测 6 枚假红 + 其余媒体用例假绿，守卫一声不吭）。
# ② 暂存根 ∉ 受保护运行数据根。``TMP``/``TEMP``/``TMPDIR`` 钉进 ``ChatBot_Runtime`` 时**名册自己
#    跟着漂**（``media_temp_root()`` 就是同一枚 ``tempfile.gettempdir()``）⇒ ① 在这条路上必然放行，
#    而产物（含 L1 的隔离运行数据根 ``chatbot-pytest-runtime/``）整颗长在受保护根里＝规则 2 直接
#    命中面。故拿**同一把尺**反着问一次：根表＝``_RUNTIME_ROOT``，「在里面」才是罪 ⇒ 判得进即拒。
# 不调 ``tmp_path_factory.getbasetemp()``：后者会在 ``_pytest/tmpdir.py:156-158`` 先 ``rm_rf``
# 再返回——那等于"先把在籍目录删了再拒绝启动"（规则 2）；两腿都只读**原始值**，被拒路径连创建
# 都不会发生（席 guardverify2 §1 反向取证：按 ``getbasetemp()`` 判时哨兵文件真被抹）。
# 8.3 短名 / 分隔符安全：判定输入与根表**两侧**都在 ``contain_within`` 里过 ``resolve()``
# （:363 ``resolve_roots`` 折根、:367 折候选），本机 ``%TEMP%`` 实测常是 ``LANCYC~1`` 短形态，
# 故 ``ChatBot_R~1`` 这类短名钉进来一样判"在内"，在册短名跑法一样判"在内"（不误拒）。
# 在册路线零行为变化：``scripts/dev.ps1`` 的 ``Get-PytestScratchBase``（:180-196，首候选＝
# ``%LOCALAPPDATA%\Temp\qoder-chatbot-ci``）先把子进程 TMP/TEMP/PYTEST_DEBUG_TEMPROOT 钉进那棵树、
# 再传 ``--basetemp=<同一目录>\basetemp``（:468-491）⇒ 两值同源且不在 ``ChatBot_Runtime`` 下。
# 骨架最小仓（``tests/_autosync_fixture.py`` 不拷 ``domains/media``）取不到容器门 ⇒ 两腿一起按本
# 文件既有缺席口径跳过（degrade＝不做判定、绝不崩；与 ``_quarantine_render_pool_between_modules`` 同形）。

#: 供出「暂存/容器根」的环境变量名——**逐字照 installed ``_pytest/tmpdir.py`` 与 CPython
#: ``tempfile`` 的取值顺序**（PYTEST_DEBUG_TEMPROOT 决定 pytest 派生根；TMP/TEMP/TMPDIR 决定
#: ``tempfile.gettempdir()``，而媒体名册与 L1 隔离根都从它派生）。判定只读这些**原始值**。
_G2_TEMP_ROOT_ENV_VARS: tuple[str, ...] = ("PYTEST_DEBUG_TEMPROOT", "TMP", "TEMP", "TMPDIR")


def _g2_effective_containers(config: pytest.Config) -> list[tuple[str, Path, bool]]:
    """pytest 本轮真正会用的容器 → ``[(来源标签, 待判容器, allow_root)]``（派生法见上①）。"""
    given = config.getoption("basetemp", None)
    if given:
        # 传了选项 ⇒ pytest 会对该目录先 rm_rf：allow_root 保持"根算越界"（--basetemp=%TEMP% 不许放行）。
        return [("--basetemp", Path(str(given)), False)]
    pinned = (os.environ.get("PYTEST_DEBUG_TEMPROOT") or "").strip()
    if pinned:
        return [
            (
                "PYTEST_DEBUG_TEMPROOT（未传 --basetemp ⇒ pytest 由它派生容器）",
                Path(pinned),
                True,
            )
        ]
    return [
        (
            "tempfile.gettempdir()（TMP/TEMP/TMPDIR 之一所定，未传 --basetemp）",
            Path(tempfile.gettempdir()),
            True,
        )
    ]


def _g2_env_pins_into_protected_tree(path_gate) -> list[tuple[str, Path]]:
    """② 那一问：枚枚变量原值 → 命中「被钉进 ``_RUNTIME_ROOT`` 之内」的（判得进＝罪）。"""
    hits: list[tuple[str, Path]] = []
    for name in _G2_TEMP_ROOT_ENV_VARS:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        probe = Path(raw)
        try:
            path_gate.contain_within(probe, [_RUNTIME_ROOT], allow_root=True)
        except path_gate.PathEscapeError:
            continue  # 不在受保护根内（或形态判不了）＝本腿不拒；那一问归 ①
        hits.append((name, probe))
    return hits


def _g2_refuse(source: str, container: Path, reason: str, remedy: str) -> None:
    """响亮拒绝：rc≠0、收集零条、被拒路径不碰；点名是**哪一枚**选项/环境变量供出的根。"""
    pytest.exit(
        f"tests/conftest.py G2 拒绝启动：{source}={container} {reason}"
        f"（判定件＝plugins/bot_unified_runtime/domains/media/path_gate.py::contain_within，"
        f"全树判定面只此一处）。这样跑出来的红是测量假象：tmp_path 下的媒体件会被"
        f" _local_path_from_value 静默拒读（只 logger.debug），凡「本轮带媒体」的用例前提无声"
        f"蒸发，不跳序的那些更是失前提仍照绿。{remedy}——本守卫不开根、不加键、不调"
        f" getbasetemp()（那会先 rm_rf 再拒绝，撞规则 2）。"
    )


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """G2：有效容器不在媒体读根名册里（或被钉进受保护运行数据根）⇒ 会话启动即拒绝并点名来源。"""
    try:
        from plugins.bot_unified_runtime.domains.media import path_gate
    except ImportError:  # 骨架最小仓无 domains/media ⇒ 无容器门可问，跳过即语义等价
        return
    for source, container, allow_root in _g2_effective_containers(config):
        try:
            path_gate.contain_within(
                container, path_gate.media_read_roots(container), allow_root=allow_root
            )
        except path_gate.PathEscapeError as exc:
            _g2_refuse(
                source,
                container,
                f"不在媒体容器门（media_read_roots）认得的任何合法读根内（code={exc.code}）",
                f"改把 scratch 放到 {path_gate.media_temp_root()} 之下（scripts/dev.ps1 的 "
                f"Get-PytestScratchBase 就走这条），或按 "
                f"patches/W5-MEDIA-PATH-GATE-CLOSURE-20261001.md 的正门裁定通道登记容器根",
            )
    for name, pinned in _g2_env_pins_into_protected_tree(path_gate):
        _g2_refuse(
            f"环境变量 {name}",
            pinned,
            f"落在受保护运行数据根 {_RUNTIME_ROOT} 之内（AGENTS.md 规则 2）：媒体读根名册会随这枚"
            f"变量一起漂走 ⇒「容器 ∈ 名册」那一问在这条路上永远判不到，而测试缓存与 L1 的隔离"
            f"运行数据根整颗写进运行数据根",
            "scratch 请留在 %LOCALAPPDATA%\\Temp\\qoder-chatbot-ci 或 %TEMP% 一侧"
            "（scripts/dev.ps1 的 Get-PytestScratchBase 走的就是前者）",
        )

# ---------------------------------------------------------------------------
# BOT_AUTOSYNC 常驻自动同步钩子（session 级，人完全无感）
# ---------------------------------------------------------------------------
# 仅当 BOT_AUTOSYNC=1（dev.ps1 -Task test 设置）时启用：session 开始时依次
# 静默重跑三个机器管文件的 --write（command-catalog / auto-facts /
# render_hashes），谁漂了就修谁，session 结束打印一行改动汇总。三个脚本
# 的 --write 输出字节确定（无漂移时前后字节一致＝不算改动），写后即与
# --check 一致（幂等）。子进程失败只 warning 不阻断测试——同步失败由既有
# 常驻门（tests/test_cross_validation_gates.py 的 --check）兜底报红。
# 未设 BOT_AUTOSYNC（CI/生产/裸 pytest）时整个钩子零开销跳过，绝不写盘。

_AUTOSYNC_STEPS: tuple[tuple[str, str], ...] = (
    ("scripts/command_catalog.py", "docs/command-catalog.md"),
    ("scripts/doc_sync.py", "docs/auto-facts.md"),
    ("tests/verify_hashes.py", "tests/render_hashes.json"),
)

_HASH_MANIFEST = "tests/render_hashes.json"

_autosync_changed: list[str] = []
_hash_baseline_changed: list[str] = []


# V2.1 §13（2026-09-17 A3）：autosync 启用判定抽成纯函数，供 ``run_autosync``
# 与回归测试（tests/test_autosync_gate.py）共用；``scripts/dev.ps1::Invoke-Test``
# 持同一语义（仅当调用方未显式设置 BOT_AUTOSYNC 时才默认 1，显式值原样透传）。
# 显式 0/false/no/off（大小写不敏感）= 禁自动重录——V2.1 验收模式下生成物
# 基线必须逐字节不变，自动 --write 不得把真实回归「洗绿」。
_AUTOSYNC_ENABLE_VALUE = "1"


def is_autosync_enabled(raw: str | None) -> bool:
    """判定 autosync 自动 ``--write`` 联动是否启用。

    仅当值为 ``"1"``（dev.ps1 未显式设置时的默认）时启用；显式
    ``0/false/no/off``（大小写不敏感）及其他任何值一律禁用；未设置
    （裸 pytest/CI）禁用，整个钩子零开销跳过。与历史 ``!= "1"`` 判定
    字节级兼容：任何取值组合下的启用/禁用结论不变。
    """
    return raw == _AUTOSYNC_ENABLE_VALUE


def _manifest_keys(raw: bytes | None) -> dict[str, str]:
    """把哈希清单字节解析成 {交付物: sha256}；解析失败返回空 dict。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run_autosync(root: Path | None = None) -> list[str]:
    """静默重生成机器管文件；返回被实际改动的文件（仓库相对路径）列表。

    哈希清单（``tests/render_hashes.json``）被重录时，额外记录**哪些交付物**
    的基线变了并发出 warning——自动修正保留「人无感」，但改动必须留痕，
    否则一次非有意的模板改动会被静默吸收成新的「正确基线」。
    """
    if not is_autosync_enabled(os.environ.get("BOT_AUTOSYNC")):
        return []
    root = REPO_ROOT if root is None else root
    changed: list[str] = []
    for script, output in _AUTOSYNC_STEPS:
        target = root / output
        try:
            before = target.read_bytes() if target.is_file() else None
            proc = subprocess.run(
                [sys.executable, str(root / script), "--write"],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",  # S8：钉死解码，不吃 locale（GBK 机器上必崩）
                timeout=120,
                check=False,
                # S144：会话级唯一的树内子进程出口显式带不写字节码的环境，
                # 不再依赖调用方 ambient 继承（tts_offline_selfcheck 同款配方）。
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPYCACHEPREFIX": _PYCACHE_PREFIX,
                },
            )
        except (OSError, subprocess.SubprocessError) as exc:
            warnings.warn(
                f"[autosync] {script} --write 未跑成（{exc}）；"
                "漂移由常驻门 --check 兜底报红",
                stacklevel=2,
            )
            continue
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            warnings.warn(
                f"[autosync] {script} --write 失败（exit {proc.returncode}）"
                f"{': ' + tail[-1] if tail else ''}；漂移由常驻门 --check 兜底报红",
                stacklevel=2,
            )
            continue
        try:
            after = target.read_bytes() if target.is_file() else None
        except OSError as exc:
            warnings.warn(f"[autosync] {output} 回读失败（{exc}）", stacklevel=2)
            continue
        if after != before:
            changed.append(output)
            if output == _HASH_MANIFEST:
                before_keys = _manifest_keys(before)
                after_keys = _manifest_keys(after)
                for name in sorted(set(before_keys) | set(after_keys)):
                    if before_keys.get(name) != after_keys.get(name):
                        _hash_baseline_changed.append(name)
    if _hash_baseline_changed:
        warnings.warn(
            "[autosync] 哈希基线被自动重录（非有意改动请复核）："
            + ", ".join(_hash_baseline_changed),
            stacklevel=2,
        )
    return changed


@pytest.fixture(autouse=True)
def _isolate_render_phase2_env(monkeypatch):
    """渲染 Phase 2 解锁键属机器级 .env 配置（A43 预跑 5 红根因）：
    契约测试断言「缺省=字节级现状」，套件内一律隔离；单测自设用 monkeypatch.setenv 在本 fixture 之后生效。"""
    monkeypatch.delenv("BOT_RENDER_MAX_CONCURRENCY", raising=False)
    monkeypatch.delenv("BOT_RENDER_WAIT_BUDGET_MS", raising=False)


@pytest.fixture(scope="module", autouse=True)
def _quarantine_render_pool_between_modules():
    """模块边界收口错误卡渲染池 + cap-proto 执行器（2026-09-18 REAPER 清障；
    CAPEXEC 收口席按其残余登记补 capability_protocols 一口）。

    ``error_report._RENDER_POOL`` 与 ``capability_protocols._EXECUTOR``
    （``cap-proto_0..3``，tests/test_v21_s10_protocols.py 经 invoke 拉起）都是
    模块级常驻单例（非 daemon worker、仅 atexit 收口）：任一测试模块拉起后，
    worker 线程会带进同会话后续任意模块，使线程面敏感用例（如
    test_v21r2_lifecycle_r2 的停机 reaper 扫描）随**用例执行顺序**飘——
    单独跑绿、组合/全量跑红。本 fixture 在每个测试模块前后各收口一次：
    两个 ``_shutdown_*`` 均幂等（单例为 None 时仅一次锁+判空，零开销）、
    ``wait=True`` 且不取消排队任务，与生产 atexit 同语义；shutdown 后池懒
    重建，后续用例零感知。语义回归锁：tests/test_render_pool_hygiene.py
    （组合复现命令见其文件头）。
    """
    try:
        from plugins.bot_unified_runtime.domains.ops.monitor import error_report
    except ModuleNotFoundError:  # autosync 骨架会话（tests/_autosync_fixture.py 最小仓）不含 domains 依赖闭包：模块缺位则池亦无从拉起，跳过即语义等价；真树模块缺位由 test_render_pool_hygiene 哨兵兜底
        error_report = None
    try:
        from plugins.bot_unified_runtime.runtime import capability_protocols
    except ModuleNotFoundError:  # 同上（骨架仓不含 runtime/capability_protocols.py）
        capability_protocols = None

    if error_report is not None:
        error_report._shutdown_render_pool()  # 挡前序模块残留
    if capability_protocols is not None:
        capability_protocols._shutdown_capability_executor()
    yield
    if error_report is not None:
        error_report._shutdown_render_pool()  # 不让本模块残留漏给后序
    if capability_protocols is not None:
        capability_protocols._shutdown_capability_executor()


@pytest.fixture(scope="session", autouse=True)
def _autosync_session_gate():
    _autosync_changed.extend(run_autosync())
    yield


def pytest_terminal_summary(terminalreporter) -> None:
    if _hash_baseline_changed:
        terminalreporter.write_line(
            "[autosync] 哈希基线已自动重录（非有意改动请复核）："
            + ", ".join(_hash_baseline_changed)
        )
    if _autosync_changed:
        terminalreporter.write_line(
            "[autosync] 自动同步：" + ", ".join(_autosync_changed)
        )


# ---------------------------------------------------------------------------
# 源码树 data/ 写入拦截守卫（G1，根治台账 #1）
# ---------------------------------------------------------------------------

_REPO_DATA = REPO_ROOT / "data"
_LOG = Path(os.environ.get("TEMP", ".")) / "g1-data-writes.log"


def _snapshot() -> set[str]:
    if not _REPO_DATA.is_dir():
        return set()
    return {str(p.relative_to(_REPO_DATA)) for p in _REPO_DATA.rglob("*")}


def _log(node: str, phase: str, fresh: list[str]) -> None:
    stamp = time.strftime("%H:%M:%S")
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.writelines(f"{stamp}\t{node}\t{phase}\tNEW\t{name}\n" for name in fresh)
    except OSError:  # pragma: no cover - diagnostics must never break the run
        pass


def _enforce(node: str, phase: str, before: set[str], excinfo: object) -> None:
    """Fail the phase when new files appeared under the source-tree data/.

    ``excinfo`` is the pluggy hookwrapper result's ``excinfo``: non-None means
    the phase already failed for its own reason and we must not mask it.
    """
    fresh = sorted(_snapshot() - before)
    if not fresh:
        return
    _log(node, phase, fresh)
    if excinfo is not None:
        return
    listing = "\n".join(f"  data/{name}" for name in fresh)
    raise AssertionError(
        f"{node} wrote new file(s) into the source tree data/ during {phase}:\n"
        f"{listing}\n"
        "Write to tmp_path (or resolve via scripts/runtime_paths.py) instead; "
        "see AGENTS.md rules 2/6."
    )


def _make_phase_guard(phase: str):
    @pytest.hookimpl(hookwrapper=True)
    def impl(item: pytest.Item):
        before = _snapshot()
        outcome = yield
        _enforce(item.nodeid, phase, before, outcome.excinfo)

    return impl


pytest_runtest_setup = _make_phase_guard("setup")
pytest_runtest_call = _make_phase_guard("call")
pytest_runtest_teardown = _make_phase_guard("teardown")
