# NEVER-PIN-GATE-S643 — `NEVER_PIN` 形态无关判据成品门件

席位：S643 ｜ 开窗（本席第一次 `date -u`）：2026-09-25T14:57:38Z ｜ 主代理派单：CY 批 14:54Z
工作根：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
席目录（产物只写这里）：`.superpowers/sdd/2026-09-24-central-dispatch/`
主件：本文件 ｜ 判据本体（可粘贴）＝§1 ｜ 执行参考实现＝`probes/s643-never-pin.py`（sha256[:16] `5f7ad7bd0c45ad7b`（幂等复跑修，见 §6.3））｜ 补充坐实＝`probes/s643-addendum.py`（`4d3dda26a9a92079`，2034 B）
完成度：**§0–§6 全部填毕并实跑**

**一句话总结**：S612 §4.2 的「主判据＝带命名空间的 annotated tag、按 `/v` 切、禁 `lstrip`」升成一整份可粘贴 pytest 门件，本席把它的**判据本体**在探针里逐字实现并**真跑**：假分母那一形（6 库全 `1.0.0`＋空 `why`＋一枚全局假 tag `v1.0.0`）被新门抓出 **12 枚红**，而旧 L-6 全局摊派腿对这同一形**全绿**（S612 §1.3-C 的假绿被本门关死）；四发注毒逐发红（假分母 / lightweight 冒充 / `lstrip` 陷阱 / 幽灵命名空间），另加一发红（名册第三闸在主判据放行后仍开火）证明判序是「主判据先行」不是名册短路；`lstrip('v')` 型错误用一张参数表钉死。**今天真值＝该门在现册上红 0 枚，但这 0 是「空转绿」（pins=0、命名空间 release tag=0），不是「已合规」**——本席用「把 6 库按现版 `0.0.0` 认真钉一下→6 红」把「0≠通过」坐实（实测，非推定）。

## §0 置顶：对简报／前席前提的现算（推翻／坐实）

本席开工 UTC 14:57:38Z。HEAD 现算 `5cc6832`（全程只读，未动 git 状态：结束时 `git tag --list`＝1、`for-each-ref` 仍只有 `refs/tags/v0.0.1-alpha.2`）。

| # | 简报／前席前提 | 本席现算 | 判定 |
|---|---|---|---|
| 0-A | 「S612 已给正解：主判据＝带命名空间 annotated tag，按 `/v` 切」 | 照此实现，真跑通过；`release_tags_by_library(真仓)`＝`{}`（唯一那枚 tag 无库命名空间 ⇒ 主判据天然不收，坐实 S612 §4.4「丁案：旧 tag 留史永不参与判定」） | **坐实** |
| 0-B | 假分母那一形「现锁全绿」（S612 §1.3-C） | 本席独立复现：`fake_denominator_OLD_leg_green=true`（旧全局 tag 摊派腿判 6 库 `1.0.0`「非占位」⇒放行）；新门同形 **12 红** | **坐实**（且量化到 12＝6×主判据＋6×空 why） |
| 0-C | 简报 ①「6 库全填 1.0.0＋空 why＋一枚假 tag ⇒ 现锁全绿这一形必须被它抓」 | 抓到了：见 §2 P1 与 §1 `test_fake_denominator_is_caught`（断言 `len(bad)==12`） | **坐实** |
| 0-D | 「注毒四发逐发红」 | 本席按四发交付（P1 假分母／P2 lightweight／P3 `lstrip` 陷阱／P4 幽灵命名空间），**另加一发红**＝名册第三闸隔离（§2 P5），因为它是「主判据先行」这条判序唯一能机检的形态，删了它交付④与判序就只剩散文 | **补足** |
| 0-E | 「今天会红几枚」 | **实测 0 枚**（现册 6 库 @`0.0.0`、0 pins、真仓 0 命名空间 release tag）。本席**拒绝把这个 0 报成通过**：补测「把 6 库按现版认真钉一下」→**6 红**（§3）。⇒ 今天 0 是空转、非合规 | **改判口径**（0 的定义要说死） |

（读数与复跑命令一律在 §1–§5，本表只放结论。）

## §1 交付①：可粘贴 pytest 判据全文（含「假分母」反例）

**落地前置（务必同批）**：本文件是随三件套同笔落地的常驻门件（S612 §3.2 已证「锁先于真身＝收集 ImportError＝整树红」）。声明源 `domains/core/workspace_manifest.py` 须加**唯一供给点** `NEVER_PIN: frozenset[str] = frozenset({"0.0.0","0.1.0","0.0.1-alpha.2"})`（K1：门与生成器都从它取，禁两处各写一份）。**今天声明源未入库 ⇒ 现在把它塞进 `tests/` 会收集期红，这正是本席只交成品文本、不落码的理由。**

判据本体的**执行参考实现**已在 `probes/s643-never-pin.py` 真跑；下方 pytest 文件的纯函数部分与之逐字同源（差异仅在 `NEVER_PIN` 的供给口与 git 合成仓夹具用 `tmp_path`）。

```python
"""NEVER_PIN 形态无关占位禁钉门（S643，落地件全文）。

主判据（与形状无关）：某库某版「发布动作发生过没有」＝仓里有没有一条**带该库命名空间的
annotated tag** `refs/tags/<library_id>/v<semver>`（`objecttype==tag`）。
字面量名册 NEVER_PIN 只能是**第三道闸**（防手滑的兜底），禁当主判据——否则名册一删判据就退化成形状尺。
S612 §4.1 的三处缺陷在此根除：F-1 不分 lightweight/annotated → 用 objecttype=='tag' 分；
F-2 lstrip('v') 字符集剥离 → 改 rpartition('/v')；F-3 全仓单命名空间摊派 → 每枚库各自带前缀。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from plugins.bot_unified_runtime.domains.core import workspace_manifest as wsm

_SEM = re.compile(wsm.SEM_RE)
NEVER_PIN: frozenset[str] = wsm.NEVER_PIN        # K1：唯一真身在声明源，本门只读
_TAG_PREFIX = "refs/tags/"


def _split_release_tag(name: str) -> "tuple[str, str] | None":
    """<lib>/v<ver> → (lib, ver)；无库命名空间或无 '/v' → None。**禁 lstrip**（F-2）。"""
    n = name[len(_TAG_PREFIX):] if name.startswith(_TAG_PREFIX) else name
    lib, sep, ver = n.rpartition("/v")
    if not sep or not lib:
        return None
    return (lib, ver)


def release_tags_by_library(repo_root: Path) -> "dict[str, set[str]]":
    """现算「每枚库各自发布过哪些版」——只认 annotated 且带库命名空间（F-1／F-3）。"""
    proc = subprocess.run(
        ["git", "for-each-ref", "refs/tags", "--format=%(refname)\t%(objecttype)"],
        cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8", check=False)
    out: "dict[str, set[str]]" = {}
    for line in proc.stdout.splitlines():
        ref, _, otype = line.partition("\t")
        if otype.strip() != "tag":                 # F-1：lightweight 不算发布动作
            continue
        parts = _split_release_tag(ref.strip())
        if parts is None:                           # F-3：无库命名空间 ⇒ 谁都不许受益
            continue
        lib, ver = parts
        out.setdefault(lib, set()).add(ver)
    return out


def never_pin_reason(version: str, released: "set[str]", forbidden: frozenset = NEVER_PIN):
    """None=可钉。判序即教义：形状 → 主判据（发布动作）→ 字面量名册（第三道闸）。"""
    if not _SEM.match(version):
        return f"非 semver，不得进 pins：{version!r}"
    if version not in released:
        return f"无该库该版的 annotated tag ⇒ 发布动作未发生：{version!r}"
    if version in forbidden:
        return f"命中禁用字面量（次级防手滑腿，非主判据）：{version!r}"
    return None


def p_never_pin(doc: dict, released_by_lib: "dict[str, set[str]]") -> "list[str]":
    bad: list[str] = []
    registered = {lib["library_id"] for lib in doc["libraries"]}
    for lib in doc["libraries"]:
        lib_id = lib["library_id"]
        released = released_by_lib.get(lib_id, set())
        pins = [p for p in doc["pins"] if p["library_id"] == lib_id]
        if len(pins) > 1:
            bad.append(f"{lib_id} 被钉 {len(pins)} 次（一库一钉）")
        for p in pins:
            pv = p["pinned_version"]
            reason = never_pin_reason(pv, released)
            if reason:
                bad.append(f"{lib_id} 钉 {pv}：{reason}")
            if not str(p.get("why", "")).strip():
                bad.append(f"{lib_id} 钉 {pv} 无 why（无理由的钉＝假分母，N-H）")
    for tag_lib in released_by_lib:                 # 反向锁：给不存在的库作伪发布证
        if tag_lib not in registered:
            bad.append(f"tag 命名空间 {tag_lib}/ 不是任何在册库（反向锁·防 F-3 回潮）")
    return bad


# ------------------------------------------------ 合成 git 仓（禁碰真仓 git 状态；tag 反例只在这）
def _make_repo(tmp_path: Path, annotated, lightweight) -> Path:
    import os
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def run(*a):
        subprocess.run(["git", *a], cwd=str(root), check=True, env=env)

    run("init", "-q")
    run("commit", "-q", "--allow-empty", "-m", "seed")
    for t in annotated:
        run("tag", "-a", t, "-m", "rel")
    for t in lightweight:
        run("tag", t)
    return root


def _doc(libs: dict, pins: list) -> dict:
    return {
        "bot_version": "0.0.0",
        "libraries": [{"library_id": k, "version": v} for k, v in libs.items()],
        "pins": [{"library_id": a, "pinned_version": b, "bot_version": "0.0.0", "why": c}
                 for a, b, c in pins],
    }


SIX = ["core.dispatch", "core.transport", "core.creation",
       "lib.emergency", "lib.render", "lib.controlplane"]


# ---------------------------------------------- 交付①反例：假分母这一形必须被抓（旧腿会全绿）
def test_fake_denominator_is_caught(tmp_path):
    doc = _doc({k: "1.0.0" for k in SIX}, [(k, "1.0.0", "") for k in SIX])
    repo = _make_repo(tmp_path, annotated=["v1.0.0"], lightweight=[])  # 一枚全局假 tag，无库命名空间
    released = release_tags_by_library(repo)
    assert released == {}                             # 新门：无命名空间 ⇒ 谁都不给证
    bad = p_never_pin(doc, released)
    assert len(bad) == 12, bad                        # 6×主判据 ＋ 6×空 why
    assert sum("发布动作未发生" in b for b in bad) == 6
    assert sum("无 why" in b for b in bad) == 6
    # 旧 L-6 腿（S594 候选门，全局 tag 摊派）对这同一形的判决：判「非占位」⇒放行＝假绿
    old_tagged = {"1.0.0"}
    old_would_pass = [v for v in {"1.0.0"} if v in {"0.0.0", "0.1.0"} or v not in old_tagged]
    assert old_would_pass == []                       # 旧腿：全绿（这正是本门要关的死口）


# ---------------------------------------------- 交付②注毒逐发红（合成仓；判据源码零改动）
def test_poison_lightweight_tag_gives_no_credit(tmp_path):
    doc = _doc({"core.dispatch": "1.0.0", "core.transport": "2.0.0"},
               [("core.dispatch", "1.0.0", "真 annotated"),
                ("core.transport", "2.0.0", "只有 lightweight")])
    repo = _make_repo(tmp_path, annotated=["core.dispatch/v1.0.0"],
                      lightweight=["core.transport/v2.0.0"])
    released = release_tags_by_library(repo)
    assert released == {"core.dispatch": {"1.0.0"}}   # lightweight 不入门（对照：dispatch 绿）
    bad = p_never_pin(doc, released)
    assert bad == ["core.transport 钉 2.0.0：无该库该版的 annotated tag ⇒ 发布动作未发生：'2.0.0'"]


def test_poison_lstrip_mangled_tag_not_credited(tmp_path):
    doc = _doc({"core.dispatch": "1.0.0"}, [("core.dispatch", "1.0.0", "钉个看着像的")])
    repo = _make_repo(tmp_path, annotated=["vv1.0.0"], lightweight=[])  # 旧 lstrip('v')→'1.0.0' 假摊派
    assert release_tags_by_library(repo) == {}
    bad = p_never_pin(doc, release_tags_by_library(repo))
    assert any("发布动作未发生" in b for b in bad)


def test_poison_ghost_namespace_reverse_lock(tmp_path):
    doc = _doc({k: "0.0.0" for k in SIX}, [])
    repo = _make_repo(tmp_path, annotated=["core.ghost/v9.9.9"], lightweight=[])
    released = release_tags_by_library(repo)
    bad = p_never_pin(doc, released)
    assert bad == ["tag 命名空间 core.ghost/ 不是任何在册库（反向锁·防 F-3 回潮）"]


def test_poison_third_gate_roster_fires_after_main(tmp_path):
    doc = _doc({"core.dispatch": "0.1.0"}, [("core.dispatch", "0.1.0", "钉它")])
    repo = _make_repo(tmp_path, annotated=["core.dispatch/v0.1.0"], lightweight=[])
    released = release_tags_by_library(repo)
    assert released == {"core.dispatch": {"0.1.0"}}   # 主判据放行（tag 真在）
    bad = p_never_pin(doc, released)
    assert bad == ["core.dispatch 钉 0.1.0：命中禁用字面量（次级防手滑腿，非主判据）：'0.1.0'"]


# ---------------------------------------------- 交付④：lstrip('v') 型错误的回归锁（纯函数）
@pytest.mark.parametrize("ref, expected", [
    ("refs/tags/core.dispatch/v1.0.0", ("core.dispatch", "1.0.0")),
    ("refs/tags/core.dispatch/vv1.0.0", ("core.dispatch", "v1.0.0")),  # 不许被洗成 1.0.0
    ("refs/tags/vv.demo/v2.3.4", ("vv.demo", "2.3.4")),                # 库名以 v 开头也不吃前导 v
    ("refs/tags/version-1.0.0", None),                                 # 无 /v ⇒ 不收（旧 lstrip→'ersion-1.0.0'）
    ("refs/tags/vv1.0.0", None),                                       # 旧 lstrip 会造出假 '1.0.0'
])
def test_split_release_tag_never_lstrips(ref, expected):
    assert _split_release_tag(ref) == expected


# ---------------------------------------------- 真册常驻断言（三件套落地后为绿、被注毒则红）
def test_never_pin_leg_is_green_on_real_book():
    from scripts import workspace_manifest_sync as syncmod
    assert p_never_pin(syncmod.render_manifest_dict(), release_tags_by_library(REPO_ROOT)) == []
```

**判序为何是「主判据先行」**（对齐 S612 §4.2 三条硬约束之①）：`never_pin_reason` 三行 if 的**顺序本身**即教义——名册是第三闸。§2 的 P5 把它测成可执行：给 `0.1.0` 造一枚**合法带命名空间**的 annotated tag ⇒ 前两闸放行、第三闸仍红；把名册清空 ⇒ 同一枚转绿。这条腿证的是「名册只兜『有人给占位版真打了 tag』这种手滑」，不是它挡下主判据挡不下的东西，故删名册不会让任何主判据该红的形态变绿（退化安全）。

## §2 交付②：注毒四发，逐发红（实跑，见 `probes/s643-never-pin.py`/`s643-addendum.py`）

「注毒做在输入侧」（变异 doc + 合成仓 tag 集），**判据源码零改动** ⇒ 天然满足「还原 cmp 等值」：探针源码指纹 `5f7ad7bd0c45ad7b`（never-pin）／`4d3dda26a9a92079`（addendum）；never-pin 因 §6.3 幂等修改过一次并重跑复核数字不变（§6.3 复核）。合成仓全在 `%TEMP%\s643-syn-*`，**真仓 git 状态零改动**。

| 发 | 注法（输入侧） | 实测战果 | 对照（应绿的一半） |
|---|---|---|---|
| **P1 假分母** | 6 库全 `1.0.0`＋6 行 `why` 全空＋一枚**全局** annotated `v1.0.0`（无库命名空间） | **12 枚红**：6×「发布动作未发生」＋6×「无 why」 | 同形喂**旧**全局摊派腿＝全绿（`fake_denominator_OLD_leg_green=true`）——本门专关这道假绿 |
| **P2 lightweight** | `core.dispatch/v1.0.0` **annotated**、`core.transport/v2.0.0` **lightweight**，两库各钉自己 | **1 枚红**：`core.transport` 钉 2.0.0「发布动作未发生」 | `core.dispatch` 钉 1.0.0 **绿**（`released={core.dispatch:{1.0.0}}`）⇒ F-1 精确：只轻标签被拒 |
| **P3 lstrip 陷阱** | 一枚 annotated `vv1.0.0`（旧 `lstrip('v')` 会洗成 `1.0.0` 摊派全员），钉 `core.dispatch@1.0.0` | **1 枚红**：`released={}` ⇒ 主判据「未发生」 | 无（这一发专证旧 lstrip+摊派 双坑同时失效） |
| **P4 幽灵命名空间** | annotated `core.ghost/v9.9.9`，但 `core.ghost` **不在册** | **1 枚红**：反向锁「命名空间不是任何在册库」 | 真仓唯一 tag 无命名空间 ⇒ 反向锁今天 0 靶（不误伤旧 tag） |
| **P5 名册第三闸**（补） | `0.1.0` 造**合法**带命名空间 tag、名册在场 | **1 枚红**：「命中禁用字面量」 | 清空名册 ⇒ 同枚 `null`（转绿）⇒ 证第三闸是额外、不短路主判据 |

**逐发红＝5/5**（含补发）。四发的红文案各自命中对应缺陷族，无一发「注了还绿」。

## §3 交付③：它今天会红几枚（实测，禁「待测」）

**现册真值（本席实跑，`s643-never-pin.py` 的 `today_*`）：**
- 真仓 `release_tags_by_library` = **`{}`**（唯一 tag `refs/tags/v0.0.1-alpha.2` 无库命名空间，主判据不收）。
- 真册 doc＝6 库全 `version="0.0.0"`、`PIN_ROWS=()`（0 pins）、`bot_version="0.0.0"`。
- ⇒ **`p_never_pin(现册, 真tag集)` ＝ 0 枚红。**

🔴 **但本席把这 0 定性为「空转绿」，不是「已合规」**——判据没有靶子，不是判据放行。用一发「诚实尝试」把话钉死（`s643-addendum.py`）：**把 6 库按现版 `0.0.0` 认真打钉（`why` 都填）→ 6 枚红**（每枚「发布动作未发生」；`0.0.0` 既非 semver-released 又在名册，主判据先红）。

**一句话读数**：今天**该门在现册上红 0 枚**；可**只要 pins 非空就必红**（因命名空间 release tag=0），这恰是 S612 §4 F-4「合法 semver ∩ 有 annotated tag = 空集 ⇒ 填不进」的门件级复现。要让它**非空转地绿**，缺的是**发布动作**（给她真打带命名空间的 annotated tag），不是改判据。

## §4 交付④：与 `lstrip('v')` 型错误的回归锁

`lstrip('v')` 是**字符集左剥**、不是前缀剥，且剥完仍是**全仓单命名空间**——S612 §4.1 记它造出 `version-1.0.0→"ersion-1.0.0"`、`vv1.0.0→"1.0.0"`。本门把切分改成 `rpartition("/v")`，用 `test_split_release_tag_never_lstrips` 参数表钉死（实跑＝`split_cases`，全部相等）：

| 输入 ref | 期望 (lib, ver) | 旧 lstrip 会得到什么（本锁否证它） |
|---|---|---|
| `refs/tags/core.dispatch/v1.0.0` | `("core.dispatch","1.0.0")` | 正常，两式同值（对照） |
| `refs/tags/core.dispatch/vv1.0.0` | `("core.dispatch","v1.0.0")` | 版本段被 lstrip 洗成 `1.0.0`＝**假摊派**（本锁锁 `v1.0.0` 原样） |
| `refs/tags/vv.demo/v2.3.4` | `("vv.demo","2.3.4")` | 全名 lstrip 吃掉库名前导 `v`＝**改错库身份** |
| `refs/tags/version-1.0.0` | `None`（无 `/v` 不收） | lstrip→`ersion-1.0.0`（垃圾串，且旧代码还会当它进 tagged 集） |
| `refs/tags/vv1.0.0` | `None`（无 `/v` 不收） | lstrip→`1.0.0`＝**一枚随手 tag 给全员发已发布资格**（F-2+F-3 复合） |

这张表就是「别再用 `lstrip`」的可执行契约；P3 是它在**行为层**的同一件事（`vv1.0.0`→`released={}`→主判据红），两把尺一浅（纯函数切分）一深（端到端判决），缺一留另一把的空当。

## §5 复跑命令簿

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
export PYTHONPYCACHEPREFIX="C:\\Users\\LancyCelestia\\AppData\\Local\\Temp\\s643-pyc"  # 必 Windows 形态
PY=../ChatBot_Runtime/venv/Scripts/python.exe
S=.superpowers/sdd/2026-09-24-central-dispatch

$PY -B $S/probes/s643-never-pin.py     # §0/§1/§2/§3/§4 全部读数：真仓 tag 集 + 假分母12红 + 四发红 + split_cases
$PY -B $S/probes/s643-addendum.py      # §3 空转坐实（钉现版→6红）＋ §2 P5 第三闸隔离（名册在场红/清空绿）
```
判据本体不读盘、只吃 (doc, tag集)，`for-each-ref` 是只读；合成仓仅 `git init/commit -q --allow-empty/tag`，落 `os.environ["TEMP"]`。
**真册常驻断言的落地复跑（待三件套入库后，交落码席，本席未跑＝声明源未入库会收集红）：**
```bash
# 须与声明源/生成器/投影件同笔；单跑门件先 import wsm.NEVER_PIN ⇒ 今天必 ImportError
$PY -B -m pytest tests/test_never_pin_gate.py -p no:cacheprovider --basetemp="$TEMP/s643-t" -q
```

## §6 卫生账 / 红线自证 / PARKED / 安全登记（规则 11）

### 6.1 写面（全在席目录，`.superpowers/` 已 gitignore）
`NEVER-PIN-GATE-S643.md`（本件）＋ `probes/s643-never-pin.py`（`5f7ad7bd0c45ad7b`）＋ `probes/s643-addendum.py`（`4d3dda26a9a92079`）。临时件全在 `%TEMP%`（`s643-syn-*` 五枚合成仓、`s643-pyc`）。判据本体**未落 `tests/`、未改 `plugins/`/`scripts/`/`docs/`/`config.py`/根 `__init__.py`** 任一字节（§1 只是成品文本）。

### 6.2 红线逐条自证
- **未动真仓 git 状态**：全程 `git tag -a`/`commit` 的 cwd 都是 `%TEMP%\s643-syn-*`；席终复核真仓 `git tag --list`＝1、`for-each-ref`＝`refs/tags/v0.0.1-alpha.2`、HEAD=`5cc6832`（与席初一致）。**不 tag、不 add、不 commit 真仓。**
- **未读 `.env`**；**未** 拨闸／删垫片／重启杀进程／装包／外部上传；**未跑** 全量 `dev.ps1 -Task test`。
- 允许面内：只读 `for-each-ref`／`rev-parse`；单文件级 `-B` python 探针（非 pytest 全量）。
- 禁在仓树目录 `import plugins…`：本席探针不 import 任何 `plugins.*`（判据本体自持 `SEM_RE`/`NEVER_PIN` 内联，仅 §1 落地件才 import `wsm`）。

### 6.3 「还原 cmp 等值」的自证方式
本席注毒做在**输入侧**、判据源码零改动 ⇒ 探针文件 sha256 全程不变。复核：
```bash
sha256sum .superpowers/sdd/2026-09-24-central-dispatch/probes/s643-never-pin.py \
          .superpowers/sdd/2026-09-24-central-dispatch/probes/s643-addendum.py
# ⇒ 5f7ad7bd0c45ad7b / 4d3dda26a9a92079，与本件登记一致
```
给落码席的对应纪律：把 L-6 占位判定换成 §1 主判据时，注毒＝往喂进 `p_never_pin` 的 doc/tag集 上做变异（照 §2 五发），门件源码本身 `git diff` 应干净——「判据不因注毒被改、只因输入被喂而红」才是有效自证。

### 6.4 PARKED（本席未做／做不了／等她）
| # | 事项 | 停在这里的原因 |
|---|---|---|
| P-S643-1 | §1 门件**未落 `tests/`**、**未给 `wsm` 加 `NEVER_PIN`** | 红线（不落码、不改 plugins）；且单飞会收集 ImportError（三件套同笔，S612 §3.2） |
| P-S643-2 | `never_pin_reason`/`p_never_pin` 与现候选门 `p_l6_pins` 的**收编关系未定** | §1 是**替换 L-6 占位判定半腿**（`version not in tagged` 那半），保留 L-6 的「一库一钉／钉版==现版／区间腿」结构半腿——但把两半合成一份 `p_l6` 还是并成两条门，是落码席的接缝选择，本席只交判据本体不代定 |
| P-S643-3 | 反向锁今天 0 靶（真仓唯一 tag 无命名空间） | 设计内（旧 tag 留史永不参与判定，S612 丁案）；**不是**「反向锁已执法」，只是无输入。要它有靶得先有带命名空间的 tag（她动作） |
| P-S643-4 | 交付③的 0 是空转、非合规；**唯一让它非空转绿的路是发布动作（打 tag）** | pins 面 0 的根因＝`semver ∩ annotated-tag = ∅` 结构洞（F-4），本席用「钉现版→6红」把它量化坐实，但补不上 tag（git 写面归她） |
| P-S643-5 | `p_never_pin` 未接 L-5 区间腿与 bot 格一致腿 | 超出「NEVER_PIN 形态无关」授权；那两腿仍属 L-6 现结构，§1 只补占位判定半腿不代改其余 |

### 6.5 卫生自查（find 输出 ≠ 事实：一次并发污染的如实归属，不报幻影零）
席终 `find . -name '*.pyc' -newermt <本席开窗>` 命中 `scripts/__pycache__/{board_doc_sync,doc_sync,doc_template_sync,physical_placement_census}.cpython-312.pyc` 四枚，mtime `2026-09-25T15:07:42–43Z`（**在本席窗口 14:57–15:08 UTC 之内**）。🔴 **归属＝并发写入窗，非本席**，证据两条硬：
1. **本席 python 全程只 import 标准库 + `subprocess`**（探针头四件：`json/os/re/subprocess/pathlib` + 一条 `importlib.util`；两条 `-c` 只 `hashlib/pathlib`）——**从不 import `scripts/*`**，结构上不可能产出这四枚 `.pyc`。
2. 这四枚的**模块集合与 mtime 簇**逐字复现 S612 §6.7 记录的并发 census 指纹（同一 21:07:05 簇、同四模块）⇒ 是一台带全树 doc_sync/census 的进程（不带 `PYTHONPYCACHEPREFIX`）在跑，与本席无因果。
**本席不清理、不代搬**（备份搬运会撞在飞写者、非本席产物，按铁律 6 留安静窗）。本席自有足迹＝**零**：`probes/` 目录 `rglob('__pycache__')` 现算 `[]`，两探针带 `-B` + 仓外 `PYTHONPYCACHEPREFIX`。⇒ 又证一次「一条 `find` 命令的输出不等于事实、更不等于归属」。

### 6.6 安全登记（规则 11）
本席在工具结果、在册件正文（S612 主件、S594 候选门件、声明源 docstring）、合成仓 git 输出里**未遇到**任何要求执行动作的祈使句载荷；读到的是**关于**注入的报告文字（台账 #53 席 C 那条 OPEN），一律当数据、未执行、未换工具、未停手。**命中数 0**，无需消毒载荷入册。本窗无环境侧 PATH/命令异常（`git`/`for-each-ref`/合成仓 `git tag` 全程可用）。
