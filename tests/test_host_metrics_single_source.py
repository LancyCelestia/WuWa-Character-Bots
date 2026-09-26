"""需求 5：宿主机读数**取数口唯一**的机器门（S-T-HOST-2，2026-09-26）。

要拦的事只有一句：**读这台机器的手段只准有一处**——
``plugins/bot_unified_runtime/domains/ops/host_metrics.py``。

这条门为什么长这样（每一条都对上一次真实踩过的坑）：

1. **判据必须是 AST、不许是 grep**。现算过：全仓 ``plugins/`` 里
   ``platform.`` 的文本命中有 11 个文件，其中 9 个是**假阳**——
   ``platform.py`` 这种文件名、``cfg.platform.get()``、``s.platform.capitalize()``
   这种**同名变量**的方法调用。拿正则扫必然出现「门红了但不是谁的错」或
   「门绿着而真凶没抓到」。本门把 ``platform`` 解析成**导入绑定**，只有真的
   ``import platform`` 之后 ``platform.system()`` 才算读数点。
2. **门要有两条腿**：① 白名单之外不许有第二处读数（防回潮）；② 真身**必须**
   有读数点（防「扫描器瞎了也满分」）。只写①的门，会在有人把真身整个删掉时
   仍然绿——那是本项目反复记账的「存在性糊过活性判据」同型事故。
3. **注毒自证常驻**（腿 E）：造一个含第二取数点的假文件让**同一个扫描器**去读，
   断言它被点名。这样扫描器哪天失效，本件当场红，而不是等到真有第二真身。
4. **降级件要单独钉**（腿 B）：``monitor/host_status.py`` 今天已降为呈现适配器，
   它体内零直调这件事必须有一条**点名它的**断言，不能只靠白名单里没它——
   否则将来有人往白名单加条目就顺手把它放宽了。
5. **消费点不许各读各的**（腿 D）：真身的同步/异步入口只准被适配器叫，
   命令面（``/bot status``）与人格分区都走同一个 ``cached_host_snapshot``。
   「都吃同一份读数」这句话不写成锁，就一定会退化成两处各读各的。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from plugins.bot_unified_runtime.domains.ops import host_metrics
from plugins.bot_unified_runtime.domains.ops.monitor import host_status

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = REPO_ROOT / "plugins"

HOST_READING_TRUE_SOURCE = "bot_unified_runtime/domains/ops/host_metrics.py"
HOST_PRESENTATION_ADAPTER = "bot_unified_runtime/domains/ops/monitor/host_status.py"

# 什么算「读这台机器」。平台函数只收遥测语义的那几个，不收 platform() 本身
# （它返回的是发行版串，本项目没人读它当机器状态）。
_PLATFORM_READS: Final[frozenset[str]] = frozenset(
    {
        "system",
        "release",
        "version",
        "machine",
        "processor",
        "python_version",
        "uname",
        "arch",
        "architecture",
        "node",
        "freemem",
        "totalmem",
    }
)
_OS_READS: Final[frozenset[str]] = frozenset({"cpu_count"})
_SHUTIL_READS: Final[frozenset[str]] = frozenset({"disk_usage"})
# psutil / winreg 整门都是机器遥测（psutil 没有任何非遥测用法；winreg 只有
# 注册表读数），所以**任意属性调用**都算读数点。
_WHOLE_MODULE_READS: Final[frozenset[str]] = frozenset({"psutil", "winreg"})

# 白名单：每一枚都得写清「为什么它有资格读机器」。**新增条目=改口径**，
# 必须在报告里点名，不许为了让自己绿而加一行。
READERS_ALLOWLIST: Final[dict[str, str]] = {
    HOST_READING_TRUE_SOURCE: "需求 5 的唯一取数真身（本门立的正是它）",
    # 现算依据：这两处各只有 `psutil.Process()` 一类进程自视读数，
    # 服务于控制面资源指标端点（与本仓 #47 之前就在册的子系统），
    # 不是「宿主机状态卡」那条链，合并进来反而会让控制面依赖 ops 域。
    "bot_unified_runtime/control_plane/resources.py": "控制面资源指标端点自带腿（进程级，非需求 5 链路）",
    # 现算依据：error_report 是**版本腿的唯一真身**（`_version_pairs`），
    # 本门拦的是「谁自己拼机器读数」，而版本这一路全仓只有它在拼，
    # host_metrics 与适配器都是调它、不是重抄它。
    "bot_unified_runtime/domains/ops/monitor/error_report.py": "版本与构建段的中央采集口本体（其它件只准调它）",
}

# 真身的两个公共入口只准被这些件叫（腿 D）。适配器在列：它就是那条唯一缝。
# capabilities/host_state.py 走的是本门断言消息里「明确改吃真身并在此登记」
# 那条被允许的路（2026-09-26 S-T-HOST-2 二段）：能力入口要的是三态语义
# （未探测/采集失败都得上卡），缺行语义的旧适配器表达不了，故直连真身同步
# 入口；它的 loop 线程降级腿仍走 cached_host_snapshot 那条缝，不绕门。
ENTRY_CALLERS_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        HOST_READING_TRUE_SOURCE,
        HOST_PRESENTATION_ADAPTER,
        "bot_unified_runtime/domains/ops/capabilities/host_state.py",
    }
)


class _ReaderVisitor(ast.NodeVisitor):
    """按**导入绑定**识别取数点：同名变量不算，真 import 才算。"""

    def __init__(self) -> None:
        # 局部/模块内的名字绑定：alias -> 真实模块名（platform/psutil/...）
        self._module_aliases: dict[str, str] = {}
        # 从模块里直接引进来的函数名：name -> (真实模块名, 属性名)
        self._function_aliases: dict[str, tuple[str, str]] = {}
        self.sites: list[tuple[int, str]] = []

    @staticmethod
    def _qualifies(root: str, attr: str) -> bool:
        if root in _WHOLE_MODULE_READS:
            return True
        if root == "platform":
            return attr in _PLATFORM_READS
        if root == "os":
            return attr in _OS_READS
        if root == "shutil":
            return attr in _SHUTIL_READS
        return False

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in {"platform", "psutil", "winreg", "os", "shutil"}:
                self._module_aliases[alias.asname or root] = root
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".")[0]
        if root in {"platform", "psutil", "winreg", "os", "shutil"}:
            for alias in node.names:
                name = alias.asname or alias.name
                if alias.name == "*":
                    self._module_aliases[name] = root
                elif self._qualifies(root, alias.name):
                    self._function_aliases[name] = (root, alias.name)
        self.generic_visit(node)

    def _bind_target(self, target: ast.expr, root: str) -> None:
        if isinstance(target, ast.Name):
            self._module_aliases[target.id] = root

    def visit_Assign(self, node: ast.Assign) -> None:
        # 真身的写法是 `ps = _psutil_module()` 再 `ps.virtual_memory()`——只认
        # import 绑定的话这条路会**漏检**（第一版就漏了，靠活性腿才逼出来）。
        # 所以把「取自 psutil 取数口 / 取自已绑定的读数名」的赋值目标也绑成读数名。
        root = self._resolve_root(node.value)
        if root:
            for target in node.targets:
                self._bind_target(target, root)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        root = self._resolve_root(node.value) if node.value is not None else None
        if root:
            self._bind_target(node.target, root)
        self.generic_visit(node)

    def _resolve_root(self, value: ast.expr | None) -> str | None:
        if isinstance(value, ast.Name):
            return self._module_aliases.get(value.id)
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Name):
                # `_psutil_module()` / `import psutil` 之后转手的包装口。
                if "psutil" in func.id.lower():
                    return "psutil"
                return self._module_aliases.get(func.id)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                bound = self._module_aliases.get(func.value.id)
                if bound and self._qualifies(bound, func.attr):
                    return bound
        return None

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            root = func.value.id
            bound = self._module_aliases.get(root)
            if bound and self._qualifies(bound, func.attr):
                self.sites.append((node.lineno, f"{bound}.{func.attr}"))
        elif isinstance(func, ast.Name):
            hit = self._function_aliases.get(func.id)
            if hit:
                self.sites.append((node.lineno, f"{hit[0]}.{hit[1]}"))
        self.generic_visit(node)


def scan_for_host_reads(source: str, path: str = "<memory>") -> list[tuple[int, str]]:
    """返回 ``[(行号, 读数点)]``；解析不了的文件按「不算」处理（门不背语法债）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - 语法坏的文件由静态门负责，不由本门定责
        return []
    visitor = _ReaderVisitor()
    visitor.visit(tree)
    if not visitor.sites:
        return []
    # 同一个文件里 `import platform` 只可能来自模块级或函数内惰性导入；两条都算，
    # 因为本门拦的是「谁有本事读机器」，不是「在什么作用域读」。
    return sorted(set(visitor.sites))


def _iter_plugin_py(root: Path = PLUGINS_ROOT) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _readers_under(root: Path = PLUGINS_ROOT) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for path in _iter_plugin_py(root):
        sites = scan_for_host_reads(path.read_text(encoding="utf-8", errors="replace"))
        if sites:
            out[path.relative_to(root).as_posix()] = sites
    return out


# ---------------------------------------------------------------------------
# 腿 A：白名单之外零第二取数点
# ---------------------------------------------------------------------------


def test_only_the_registered_true_source_reads_the_machine() -> None:
    readers = _readers_under()
    offenders = {rel: sites for rel, sites in readers.items() if rel not in READERS_ALLOWLIST}
    assert not offenders, (
        "出现第二处自拼宿主机读数的件（需求 5 取数口只准一处，"
        f"真身={HOST_READING_TRUE_SOURCE}）："
        + "; ".join(f"{rel}:{','.join(f'{ln} {what}' for ln, what in sites)}" for rel, sites in offenders.items())
        + "。要么改成调真身，要么在本文件白名单里写明资格理由并在报告里点名。"
    )


def test_true_source_still_has_the_reads_it_owns() -> None:
    """活性腿：真身必须**确实**在读机器。

    少了这条，把真身的取数整个删掉（或让扫描器认不出它）也能骗过腿 A——
    那正是本项目反复记账的「门绿着而判据已瞎」。
    """
    readers = _readers_under()
    sites = readers.get(HOST_READING_TRUE_SOURCE)
    assert sites, "真身一个读数点都没被扫到＝扫描器或真身坏了，腿 A 随即成为假绿"
    kinds = {what for _ln, what in sites}
    assert any(k.startswith("psutil.") for k in kinds), kinds
    assert any(k.startswith("winreg.") for k in kinds), kinds
    assert "shutil.disk_usage" in kinds, kinds
    assert any(k.startswith("platform.") for k in kinds), kinds


# ---------------------------------------------------------------------------
# 腿 B：降级件零直调（点名钉，不靠白名单兜）
# ---------------------------------------------------------------------------


def test_presentation_adapter_contains_no_direct_host_reads() -> None:
    adapter = PLUGINS_ROOT / HOST_PRESENTATION_ADAPTER
    assert adapter.is_file(), f"降级件不见了：{adapter}"
    sites = scan_for_host_reads(adapter.read_text(encoding="utf-8"))
    assert sites == [], (
        f"{HOST_PRESENTATION_ADAPTER} 应只是呈现形态适配器（分组/TTL 缓存/文本），"
        f"却出现取数直调：{sites}"
    )


def test_true_source_does_not_depend_back_on_the_adapter() -> None:
    """收敛的前提是依赖单向：真身不许 import 垫片。

    收敛前正是反的（host_metrics 调 host_status._cpu_label），那种形态下
    「谁是真身」无法用删除来检验，两件套只能永远互相供氧。
    """
    src = (PLUGINS_ROOT / HOST_READING_TRUE_SOURCE).read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    back: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and "host_status" in (node.module or ""):
            back.append(node.module or "")
        elif isinstance(node, ast.Import):
            back.extend(alias.name for alias in node.names if "host_status" in alias.name)
    assert back == [], f"真身反向依赖呈现适配器：{back}"


# ---------------------------------------------------------------------------
# 腿 C：呈现分组只有一处声明
# ---------------------------------------------------------------------------


def test_legacy_group_names_are_declared_once() -> None:
    """「硬件 / 占用 / 系统与运行时」这三个字面量的声明处只准有一枚。

    旧真身与适配器各写一份的话，改一处就漂一处（出卡顺序即分组顺序）。
    """
    declared: list[str] = []
    for path in _iter_plugin_py():
        src = path.read_text(encoding="utf-8", errors="replace")
        if '"硬件", "占用", "系统与运行时"' not in src:
            continue
        tree = ast.parse(src)
        for node in tree.body:  # 只认模块级赋值，注释/docstring 里提一句不算声明
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):  # 带注解的声明也算（第一版漏了它）
                targets = [node.target]
            if any(isinstance(t, ast.Name) and t.id == "HOST_GROUP_NAMES" for t in targets):
                declared.append(path.relative_to(PLUGINS_ROOT).as_posix())
    assert declared == [HOST_PRESENTATION_ADAPTER], declared


# ---------------------------------------------------------------------------
# 腿 D：消费点同源，不得各读各的
# ---------------------------------------------------------------------------


def test_metric_entries_are_called_only_by_the_adapter() -> None:
    """真身入口（``collect_host_metrics*``）的调用方只准是适配器。

    命令面与人格分区都吃 ``host_status.cached_host_snapshot`` 这一条缝，
    「/bot status 侧与调试侧各读各的」在结构上就不成立。
    """
    callers: list[str] = []
    for path in _iter_plugin_py():
        rel = path.relative_to(PLUGINS_ROOT).as_posix()
        src = path.read_text(encoding="utf-8", errors="replace")
        if "collect_host_metrics" not in src:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("collect_host_metrics"):
                callers.append(rel)
                break
    unexpected = sorted(set(callers) - set(ENTRY_CALLERS_ALLOWLIST))
    assert unexpected == [], (
        f"绕过适配器直接叫真身入口的件：{unexpected}；"
        "呈现面请统一走 host_status.cached_host_snapshot（或明确改吃真身并在此登记）"
    )


def test_wired_consumers_read_through_one_seam() -> None:
    """现算过的三个已接线消费点都必须只经那条缝（少一枚=那条缝被绕过）。"""
    seam_users = {
        "bot_unified_runtime/domains/chat_reply/capabilities/chat.py": "cached_host_snapshot",
        "bot_unified_runtime/domains/chat_reply/capabilities/echo.py": "cached_host_snapshot",
        "bot_unified_runtime/domains/chat_reply/character/temporal.py": "_runtime_versions",
    }
    for rel, seam in seam_users.items():
        path = PLUGINS_ROOT / rel
        src = path.read_text(encoding="utf-8", errors="replace")
        assert seam in src, f"{rel} 不再经 {seam} 取宿主读数——消费点漂了，须同批改本门"
        assert "collect_host_metrics" not in src, f"{rel} 直连真身入口＝第二通路"


# ---------------------------------------------------------------------------
# 腿 F：收敛期间真身修掉的一处算法缺陷，留回滚点（锁写在这里的理由见注释）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (7, "0 分"),
        (59, "0 分"),
        (60, "1 分"),
        (3600, "1 小时 0 分"),
        (3661, "1 小时 1 分"),
        # 修复前这行会算成「10 小时 91 分」——`divmod(rest, 360)` 把小时除错了。
        (10202, "2 小时 50 分"),
        (86400, "1 天 0 小时"),
        (99000, "1 天 3 小时"),
    ],
)
def test_duration_text_divides_hours_by_3600(seconds: int, expected: str) -> None:
    """`_duration_text` 的算法锁（S-T-HOST-2 收敛时给「已开机」接线才撞出来）。

    为什么不写在 ``tests/test_host_metrics.py``：那件不在本席可写面内，而它
    对这条腿**没有任何断言**（只断「常驻内存」在值里），所以旧缺陷一路全绿。
    数值 ≥3600 秒才会现形，本机「本 bot 进程累计 CPU」恰好常低于一小时。
    """
    assert host_metrics._duration_text(seconds) == expected


def test_newly_carry_over_metrics_are_registered_and_collected() -> None:
    """从旧真身迁来的两枚读数必须**在册且可采**，不许成只有名字的空壳。

    ``swap`` / ``machine_uptime`` 是「收敛不减少一行读数」这条承诺的全部内容；
    它们没进 ``METRIC_SPECS`` 或没接采集器的话，旧卡上那两行就静默消失了。
    """
    ids = set(host_metrics.METRIC_SPEC_IDS)
    assert {"swap", "machine_uptime"} <= ids, ids
    labels = {spec.metric_id: spec.label for spec in host_metrics.METRIC_SPECS}
    assert labels["swap"] == "页面文件" and labels["machine_uptime"] == "已开机"
    report = host_metrics.collect_host_metrics_sync()
    by_id = report.by_id()
    for metric_id in ("swap", "machine_uptime"):
        assert metric_id in by_id, f"{metric_id} 在册却没被采集＝死条目"
        assert by_id[metric_id][0].state in {
            host_metrics.STATE_OK,
            host_metrics.STATE_NOT_PROBED,
            host_metrics.STATE_FAILED,
        }


# ---------------------------------------------------------------------------
# 腿 G：降级件仍要能独立工作（适配器不是把旧名字删了就完事）
# ---------------------------------------------------------------------------


def test_adapter_still_serves_every_legacy_name() -> None:
    """旧消费方点名的每个名字都还得在（chat.py / echo.py / temporal.py / 旧测试件）。

    少一枚就是「收敛」把已接线的路砍断了——那类事故本仓记过不止一次。
    """
    for name in (
        "HOST_GROUP_NAMES",
        "collect_host_snapshot",
        "cached_host_snapshot",
        "host_status_rows",
        "host_status_text",
        "invalidate_cached_snapshot_for_tests",
        "_runtime_versions",
        "_cpu_label",
        "_gpu_labels",
        "_SNAPSHOT_CACHE",
        "_VERSION_SOURCE",
    ):
        assert hasattr(host_status, name), f"降级件丢了旧名字 {name}（消费方会当场 AttributeError）"


def test_adapter_groups_keep_legacy_order_and_shape() -> None:
    groups = host_status.collect_host_snapshot()
    assert list(groups) == ["硬件", "占用", "系统与运行时"]
    for rows in groups.values():
        for row in rows:
            assert isinstance(row, tuple) and len(row) == 2
            assert row[0].strip() and row[1].strip()
            assert "未知" not in row[1] and "unknown" not in row[1].lower()



# ---------------------------------------------------------------------------
# 腿 E：注毒自证（常驻）——扫描器失效应当场红，而不是等有第二真身
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected_fragment",
    [
        ("import psutil\nx = psutil.virtual_memory()\n", "psutil.virtual_memory"),
        ("from shutil import disk_usage\nx = disk_usage('C:/')\n", "shutil.disk_usage"),
        ("import winreg\nwinreg.OpenKey(0, 'k')\n", "winreg.OpenKey"),
        ("import platform\nx = platform.processor()\n", "platform.processor"),
        ("import os\nx = os.cpu_count()\n", "os.cpu_count"),
        ("def f():\n    import psutil\n\n    return psutil.cpu_percent()\n", "psutil.cpu_percent"),
    ],
    ids=["psutil", "shutil-import", "winreg", "platform", "os-cpu-count", "lazy-import"],
)
def test_scanner_catches_each_poison_form(code: str, expected_fragment: str) -> None:
    sites = scan_for_host_reads(code, "<poison>")
    assert any(expected_fragment in what for _ln, what in sites), sites


def test_scanner_is_not_blind_to_a_second_reader(tmp_path: Path) -> None:
    """假树里造一枚第二取数件 ⇒ 腿 A 的判据必须点名它（真仓同理）。"""
    fake_root = tmp_path / "plugins" / "pkg"
    fake_root.mkdir(parents=True)
    (fake_root / "copycat.py").write_text(
        "import psutil\n\n\ndef rows():\n    return psutil.cpu_percent(interval=0.2)\n",
        encoding="utf-8",
    )
    (fake_root / "innocent.py").write_text(
        "cfg = {}\n\n\ndef show():\n    return cfg.get('platform'), 'platform.py'\n",
        encoding="utf-8",
    )
    readers = _readers_under(tmp_path / "plugins")
    assert [rel for rel in readers if rel.endswith("copycat.py")] == [
            "pkg/copycat.py"
        ], readers
    assert not [rel for rel in readers if rel.endswith("innocent.py")], (
        "同名变量/文件名字段被判成取数点＝判据太钝，会在真仓里造假阳"
    )


def test_allowlist_entries_are_all_real_and_still_read() -> None:
    """白名单不许挂空名：每一枚都得在盘、且**确实**有读数点。

    防的是「条目留着、件早已不读机器」——那种僵尸条目会让门看起来在执法，
    实际放宽了一次回潮。
    """
    readers = _readers_under()
    for rel, reason in READERS_ALLOWLIST.items():
        assert reason.strip(), f"{rel} 的白名单理由为空"
        assert (PLUGINS_ROOT / rel).is_file(), rel
        assert rel in readers, f"{rel} 挂在白名单上却已不读机器＝僵尸条目，请删掉本行"
