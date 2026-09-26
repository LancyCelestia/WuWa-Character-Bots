"""ownership_map — 文件/目录**写权互斥规则**的唯一声明源（中央调度收编波 S71 / 目标 5）。

## 这枚册管什么、不管什么（先划界，防第二真身）
S34 已判定并留档（`SEAT-S34.md` §4.2）：机器投影产不出「席位互斥表」，因为三支投影源
（`capability_manifest` / `central_seam_census` / `physical_placement_census`）里**没有任何字段
说"这件文件在写权上归谁、允许几个席位同时写"**。S34 提议的补法是新建一支携带**静态 `seat` 字段**
的 `wave_ownership.py`——本席明确否掉那一半：**席位是运行时事实、每波都在漂移**（谁在写、写到第几阶段），
把它冻结成静态声明＝把排班流水账当教义，正是简报点名的反模式。

本册因此**只声明两样会跨越席位寿命稳定成立的事实**：
  1. **owner**：这个面归哪个**域 / 治理区**（不是席位）。
  2. **写并发规则**：这个面在写权上允许**几个写者同时持锁**（`max_writers`）+ 互斥类别（`policy`）。
「此刻是哪一席占着这把锁」由**调度侧现算**（读在飞席位 + 本册规则），本册与投影件都**不**记它。

## 与相邻真身的分工（各管一面，互不复制）
- 「哪个能力物理住在 `domains/<d>/` 哪一层」＝ `physical_placement_census` 的 G-P1/G-P2
  （判据读 `board_placement.py` 的落点白名单）。本册**不判物理落位**，只判**写权并发**。
  同一枚 `domains/media/…/tts.py` 在两支里语义正交：那边回答"它该住在 media 域"，
  这边回答"media 这一区一波最多 2 个席位同时写、且这枚文件本身结构写独占"。
- 「哪些能力走这件文件」＝三支投影源的强项，`scripts/ownership_project.py` §2 已在投影。
  本册**不复制能力归属**；投影器新增的 §7「互斥视图」只读本册，与 §2/§4/§5 的能力账**分账不并计**
  （本波有"两本独立账的斥离锁"先例：绝不把一本账搬到另一本凑零）。

## 四条教义（写进代码，也写进门）
  · **只声明规则、不声明占用**：本册任何字段都不得出现"某席位号占着这面"。由 `WritePolicy`
    + `max_writers` 表达规则；席位占用现算归调度侧（投影件 §7 明写这条边界）。
  · **字面路径、禁通配/正则/目录兜底作豁免**（沿用 `board_placement.py` 纪律）：文件面精确、
    目录面（`kind="zone"`）以单个 `/` 结尾表示"这一子树共享一份并发预算"，是**分组**不是**豁免**。
  · **每条必带 why**：`why` 为空的行一律红——无因的写权声明不可审，等于没声明。
  · **owner 取自 `KNOWN_OWNERS` 白名单**：防止 owner 变成随手写的自由文本（那会退化成第二真身）。

## 谁消费它
- 投影器 `scripts/ownership_project.py`：AST 单件装载本册（禁包 import，与 `load_manifest` 同法），
  生成 `OWNERSHIP.generated.md` §7「席位互斥视图」。
- 门禁 `tests/test_ownership_map_gate.py`：结构自洽（字面路径 / owner ∈ 白名单 / max_writers 与
  policy 一致 / why 非空 / **反席位锁**——源码里出现 `seat`/`phase` 字段名即红）+ 投影一致性 + 注毒自证。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class WritePolicy(str, Enum):
    """一个面的写权互斥类别（决定调度侧能不能给第二个席位开这把锁）。"""

    EXCLUSIVE = "exclusive"      # 同一时刻至多 1 个写者（结构写独占，典型＝单一真身文件）
    APPEND_ONLY = "append_only"  # 结构写独占、并发尾附安全（多席位各自追加不冲突）
    READ_ONLY = "read_only"      # 本波席位只读不可写（真身另有 owner 在治理，改它须该 owner）
    BANNED = "banned"            # 硬禁写面（动它就顶漂坐标棘轮 / 有覆写数据事故史）


@dataclass(frozen=True)
class FaceOwnership:
    """一个文件/目录面在写权上的规则（**不含席位**）。"""

    face: str          # 仓根相对 posix 字面路径；目录面以单个 '/' 结尾（zone），文件面精确
    owner: str         # 归属域 / 治理区（取自 KNOWN_OWNERS，非席位）
    policy: WritePolicy
    max_writers: int   # 允许的并发写者席位数：read_only/banned=0，exclusive=1，zone 可 >1
    kind: str          # "file"（精确面）| "zone"（子树共享预算）
    why: str           # 一句为什么（必填；无因即门红）
    since: str         # 静态锚（登记波次日期），非席位、非席位阶段


_OWNERS = (
    "core",            # domains/core 治理真身
    "runtime",         # 插件运行根（registry/protocols/invoker）
    "config",          # config.py / settings 装配面
    "chat_reply",      # 主对话域
    "media",           # 语音/媒体域
    "creation",        # 绘画 / 语音合成协议域
    "render",          # 渲染域
    "control-plane",   # 控制面 API
    "dispatch-tools",  # 本波量具与投影脚本
    "governance-docs", # 波次治理册（人写 OWNERSHIP / SEAT-MAIN / PARKED 等，主代理独占）
)
KNOWN_OWNERS: Final[frozenset[str]] = frozenset(_OWNERS)

#: 写权互斥规则册（种子：只填今天已稳定成立、且被本波反复援引为「禁写 / 独占 / 分区并发」的面）。
#: 覆盖度是**活性**概念——未申报的面不是"无人管"，而是"本册尚未声明其规则"，
#: 投影件 §7 会把「落在任何 exact/zone 之外的面」如实计入 unzoned，不硬塞。
FACE_OWNERSHIP: Final[tuple[FaceOwnership, ...]] = (
    # ---- 硬禁写面（BANNED，席位 0 写；改动即顶漂坐标棘轮 / 数据事故史）----
    FaceOwnership("plugins/bot_unified_runtime/__init__.py", "runtime", WritePolicy.BANNED, 0, "file",
                  "NoneBot 插件根：插行顶漂 campus matcher 坐标棘轮（test_outbound_registry_*）", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/config.py", "config", WritePolicy.BANNED, 0, "file",
                  "单一 Config 真身：加字段要跟 catalog/SETTABLE/env.example 四面，本波禁席写", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/runtime/capability_protocols.py", "runtime", WritePolicy.BANNED, 0, "file",
                  "唯一在册表 CAPABILITY_DESCRIPTOR 宿主：本波主代理独占（S09/S35 补丁文本走主代理）", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py", "core", WritePolicy.BANNED, 0, "file",
                  "出站登记册坐标棘轮：行号随根文件增删漂移，登记基线只降不升", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py", "config", WritePolicy.BANNED, 0, "file",
                  "RESTART_REQUIRED_KEYS 装配快照真身：热改假象即源于此，禁席写", "2026-09-24"),

    # ---- 只读真身（READ_ONLY，席位可读不可写：另有 owner 在治理）----
    FaceOwnership("plugins/bot_unified_runtime/domains/core/capability_manifest.py", "core", WritePolicy.READ_ONLY, 0, "file",
                  "能力多维标签唯一真身：S67 在写，其余席位只读", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/domains/core/board_taxonomy.py", "core", WritePolicy.READ_ONLY, 0, "file",
                  "十板块树唯一声明源：board_doc_sync/板块门 owner 独占", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/domains/core/channel_capability_tags.py", "core", WritePolicy.READ_ONLY, 0, "file",
                  "渠道 native-* 标签声明源：与运行时注册表对齐面，禁随写", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/domains/core/ownership_map.py", "core", WritePolicy.READ_ONLY, 0, "file",
                  "本写权声明源自指：规则改动须门 owner 复核，席只读自己产物外不得改册", "2026-09-24"),
    FaceOwnership(".superpowers/sdd/2026-09-24-central-dispatch/OWNERSHIP.md", "governance-docs", WritePolicy.READ_ONLY, 0, "file",
                  "双区投影物：§M 机器区由 ownership_project --emit-ownership 从本册生成、席勿手改；§H 人写区（席位认领/欠账）逐字回环、"
                  "改它走 dts.tail_append CAS 口（历史上两席截零过，机器区仅投影器/主代理可换）", "2026-09-24"),
    FaceOwnership(".superpowers/sdd/2026-09-24-central-dispatch/SEAT-MAIN.md", "governance-docs", WritePolicy.READ_ONLY, 0, "file",
                  "主代理总账：席不得写（简报列禁写面）", "2026-09-24"),
    FaceOwnership(".superpowers/sdd/2026-09-24-central-dispatch/PARKED.md", "governance-docs", WritePolicy.READ_ONLY, 0, "file",
                  "挂账册：主代理独占，席记账写各自 SEAT-*.md", "2026-09-24"),
    FaceOwnership(".superpowers/sdd/2026-09-24-central-dispatch/progress.md", "governance-docs", WritePolicy.READ_ONLY, 0, "file",
                  "进度册：主代理独占", "2026-09-24"),
    FaceOwnership(".superpowers/sdd/2026-09-24-central-dispatch/findings.md", "governance-docs", WritePolicy.READ_ONLY, 0, "file",
                  "发现册：主代理独占", "2026-09-24"),

    # ---- 单一真身量具（EXCLUSIVE，同一时刻 1 写者；规则非占用）----
    FaceOwnership("scripts/central_seam_census.py", "dispatch-tools", WritePolicy.EXCLUSIVE, 1, "file",
                  "缝外直呼点普查尺：S48 门与投影器共同读它，改尺面须串行", "2026-09-24"),
    FaceOwnership("scripts/physical_placement_census.py", "dispatch-tools", WritePolicy.EXCLUSIVE, 1, "file",
                  "物理归位四本账尺：棘轮基线只降不升，改判据须现算证据、串行", "2026-09-24"),
    FaceOwnership("scripts/ownership_project.py", "dispatch-tools", WritePolicy.EXCLUSIVE, 1, "file",
                  "OWNERSHIP 投影器：与 S71 声明源/门禁同面，独占写者规则为 1（占者现算）", "2026-09-24"),

    # ---- 分区并发预算（zone：该子树共享一份 max_writers，跨文件不互斥、区内限并发）----
    FaceOwnership("plugins/bot_unified_runtime/domains/creation/", "creation", WritePolicy.EXCLUSIVE, 2, "zone",
                  "creation 协议域：波内文件级独占、整区并发上限 2（S07/S09 同域曾并行）", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/domains/media/", "media", WritePolicy.EXCLUSIVE, 2, "zone",
                  "media 语音域：文件级独占、整区并发上限 2（TTS 多席曾并行）", "2026-09-24"),
    FaceOwnership("plugins/bot_unified_runtime/domains/chat_reply/", "chat_reply", WritePolicy.EXCLUSIVE, 1, "zone",
                  "主对话域：registry/echo/base_router 高撞车面，整区串行 1", "2026-09-24"),
    FaceOwnership("scripts/", "dispatch-tools", WritePolicy.EXCLUSIVE, 3, "zone",
                  "scripts 面各量具互不相干：整区并发上限 3", "2026-09-24"),
    FaceOwnership("tests/", "governance-docs", WritePolicy.EXCLUSIVE, 4, "zone",
                  "tests 各门件互不相干：整区并发上限 4（一席一测试面天然错峰）", "2026-09-24"),
    # ---- 席位报告册（APPEND_ONLY：每席写各自 SEAT-<self>.md，跨席不冲突，靠文件名天然错峰）----
    FaceOwnership(".superpowers/sdd/2026-09-24-central-dispatch/", "governance-docs", WritePolicy.APPEND_ONLY, 99, "zone",
                  "波次过程目录：各席写各自 SEAT-<self>.md 天然按文件名错峰；四本共享册另列 READ_ONLY 收窄", "2026-09-24"),
)


def exact_faces() -> frozenset[str]:
    return frozenset(r.face for r in FACE_OWNERSHIP if r.kind == "file")


def zone_faces() -> tuple[str, ...]:
    return tuple(r.face for r in FACE_OWNERSHIP if r.kind == "zone")


def resolve(face: str) -> FaceOwnership | None:
    """面 → 生效的写权规则：精确文件面优先，否则取**最长**包含它的 zone 面。找不到即 None（未声明，不猜）。"""
    text = (face or "").strip().replace("\\", "/")
    for row in FACE_OWNERSHIP:
        if row.kind == "file" and row.face == text:
            return row
    best: FaceOwnership | None = None
    for row in FACE_OWNERSHIP:
        if (row.kind == "zone" and (text == row.face or text.startswith(row.face))
                and (best is None or len(row.face) > len(best.face))):
            best = row
    return best
