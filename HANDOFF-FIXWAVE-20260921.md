# HANDOFF — 2026-09-21 全面修复波（给下一个 AI 的第一入口）

> **冷启动读这一份就够**：现状/四态/门禁真值/待办/禁碰面/证据地图/复跑命令/踩过的坑，全在这里。
> 想深挖再按 §7 的文件地图点进去。**别从 `AGENTS.md` 从头考古**（那是规则+项目全貌，不是本波进度）。
> 交接口径：以下每一条"已完成"都带**可复跑命令或实跑数字**；凡只有席位自述、我没复跑的，一律标「席述」。

## 0. 五问（你可以在 30 秒内答出来 = 上下文接上了）

| 问 | 答 | 出处 |
|---|---|---|
| 我在哪？ | 用户十三项裁定的实施波已**收口并落账**；套件可跑，门禁已归零（除 1 条外部坐标红） | §2 §4 |
| 我要去哪？ | 剩两块**按裁定故意没做**：③ 紧急域定级改造（挂账）、⑩ 中央调度层 Wave 1–4 | §5 |
| 目标是什么？ | 三条尺子：①按功能归类 ②内容实时自动同步+规格自动统一 ③内容只能调用函数与模板产出 | `docs/audit-20260921.md` §0 |
| 我学到了什么？ | 十二类"全绿但没执法"形态 + 本波新增四类坑（编码假红/探针被自家门打脸/再导出≠修复/typecheck 污染树） | `findings.md` 末段 + §6 |
| 我做了什么？ | 13 席交付 + 主会话落 28 枚配置键 + 阻断项根修 + 收尾网 + 四份台账 | §3 §4 |

## 1. 一句话总结

审计（435 个 `domains/` 真身通读 + 十条全景线）→ 十三项裁定 → **实施波**：
11 项落码、1 项落码但半成品挂账（③）、1 项只完成地基（⑩ Wave 0/5）；
收尾网（哈希/生成物/四门禁/全量真值/台账/真机清单）已做完并写进 md；
**未 commit、未重启**（提交与重启的裁决权都在用户）。

## 2. 十三项四态总表

| # | 裁定 | 态 | 一句话 | 证据 |
|---|---|---|---|---|
| 1 | A 凭证外泄 | 已落码·**主会话复跑** | `http_util` 咽喉 + 跨 host 重定向剥凭证 + `allowed_hosts` 归因，域名表扩写不新建 | `test_credential_domain_binding_gate.py` 27P（席）+ 我跑 404P 批内含 |
| 2 | C 换繁简库 | 已落码·**复跑** | zhconv 1.4.3，`zh-cn`（`cn` 是**静默 no-op**），旧 102 对表降为兜底 | 我跑 `test_content_safety_v2..v6`+全族 345P；探针 `FOLD_STATE=library` |
| 3 | A 不够→全预警谱 | 已落码·**半成品挂账** | `alert_taxonomy` 9 族 31 类（她列的 14 类气象信号全覆盖 + 15 类其他，10 类诚实标"无源"）；**注册表/震级驱动定级未做** | 我实跑 import 打印 9 族 31 类；`WP3-TAXONOMY` 20 实例 xfail |
| 4 | A TTS 退避 | 已落码·**复跑** | 清零移到 `synthesize` 落盘后唯一提交点；静音陷阱计入退避窗 | 我跑 tts 三族含在 235P 批 |
| 5 | A 路由拆位 | 已落码·**复跑** | fx36/商品37/债38/北向39 + market 词表收紧 + 前导让路 | 我跑 `test_route_priority_disambiguation`+`test_finance_routing` |
| 6 | A1 但算法要重做 | 已落码·**复跑**·灰度关 | 单一事实总线 + 作用域列化（走 `session_keys`）+ 证据累积 + 召回打分 + 迁移守恒 | 我跑 `test_memory_bus_v2*` 全绿 |
| 7 | A 且全量重写好感度 | 已落码·**复跑**·灰度关 | 潜变量 `z`+`tanh`（**结构上永不触顶**）+ 质量分/新鲜度/按人归一/修复通道/三护栏；存量分数惰性映射不重置 | 我跑 `test_affinity_v7.py`（37 例）绿；席报合跑 349P |
| 8 | A 落盘告警 | 保留 | `settings._save` OSError 打"重启会丢"人话 | `test_runtime_hygiene_wave_20260921.py` |
| 9 | A shared_export | 保留 | 会话键走中央件，不再 `"group:" in s` | `test_shared_export_key_shape.py` |
| 10 | 全部内容接中央调度层 | **只做 Wave 0/5** | 两个同名 `CapabilityResult` 分层归并（壳侧改名 `InvocationResult`）+ 唯一性门 | 我跑 `test_capability_result_unique.py` 15P；Wave 1–4 见 §5 |
| 11 | C 条件合并占卜 | 已落码·**复跑** | 算法真身 `divination/data/deck_math.py`、存储真身 `store/draw_store.py`；第二套算法与第二颗 `DrawError` 删除；旧表不 DROP（实测本部署从未建过=零搬运） | 我跑 `test_divination_consolidation_wp9.py` 绿 |
| 12 | A 救活 sync_drift | 已落码·**复跑**·缺省关 | 病根=读七个 Config 上不存在的键 ⇒ 恒 False ⇒ 巡检器永不注册；主会话落键 + WP10 接线 | 我跑 `test_sync_drift_activation.py` 37P；`runtime-layout` PASS |
| 13 | A 叙述计数 | 已落码·**复跑** | 11 处手写计数处置 + 新机器门（含注毒自证）+ **AGENTS 规则 10**；WP11b 把旧路径 **854→357** | 我跑 `test_documentation_consistency.py` 25P |

## 3. 本波到底改了什么（成果清单）

- **新增生产件 6 个**：`link_parse/parsers/http_util.py`（咽喉段）、`domains/emergency_info/service/alert_taxonomy.py`、
  `domains/chat_reply/character/memory_bus_v2.py`(≈1260 行)、`domains/divination/data/deck_math.py`(505 行)、
  `domains/ops/sync_drift/`（接线+46→0 修）、`runtime/capability_protocols.py`（Wave 0 契约改名）。
- **重写 2 个核心算法件**：`character/affinity.py` 1324→2081 行（v7）、`domains/chat_reply/security/content_safety.py`（繁简折形换库）。
- **新配置键 28 枚**（全部主会话串行落 `config.py`+`.env.example`+catalog 四处；**一律未登记 `SETTABLE_KEYS`**，理由=不接合并层的热改是假热改）：
  记忆 9 / 好感度 12 / 漂移巡检 7。**缺省全部=关闭或旧行为**。
- **新增测试 15 件**（含 `test_affinity_v7` / `test_memory_bus_v2`+`_migration` / `test_capability_result_unique` /
  `test_divination_consolidation_wp9` / `test_sync_drift_activation` / `test_emergency_info_taxonomy` /
  `test_route_priority_disambiguation` / `test_tts_backoff_commit_point` / `test_content_safety_v6` / 两个凭证门）。
- **新规格件 4 份**：`docs/design/{affinity-v7-design,memory-reflection-v2-design,divination-consolidation-20260921,capability-orchestration-adoption-spec}.md`。
- **台账 3 处**：`AGENTS.md` 第六部分 **#47**、`docs/HANDBOOK.md` **§38**、本文件 + `.superpowers/sdd/2026-09-21-fix-wave/master-plan.md`（§捌交接态 / §8.8 收尾执行记录 / §8.6 结案表）。

## 4. 门禁真值（主会话本人实跑，`BOT_AUTOSYNC=0`）

```
全量：1 failed / 10961 passed / 13 skipped / 27 xfailed / 2 xpassed / 613.41s
唯一红：tests/test_campus_digest.py::test_outbound_registry_campus_coordinate_is_live
        （登记表 __init__.py:5027 ≠ 活体 :5032；其间有【本会话之外】的编辑动过根文件，按纪律未代改）
runtime-layout      PASS（RC=0；python_bytecode=absent / source_generated_dirs=empty）
verify_hashes --check   EXIT 0（零漂移）
doc_sync --check        EXIT 0（--write 复录后）
command_catalog --check EXIT 0（78 topics）
ruff check .            21 错 / 16 文件 —— 本波 0
mypy（650 文件）        7 错 / 2 文件 —— 本波 0（command_catalog.py×6 + emergency_info/subscriptions.py:132×1）
机器册现值            测试文件 514 / config bot_* 字段 672 / RouteKind 35 / topic 78 / 模板 7
```
复跑：见 §8。**注意**：`dev.ps1 -Task test` 会因 `BOT_AUTOSYNC=1` 自动 `--write`，生成物门**结构性不可能红**；
要真值必须自己带 `BOT_AUTOSYNC=0`。

## 5. 还没做的（按优先级，含"为什么没做"）

| 序 | 事项 | 为什么停在这 | 接手的确切第一步 |
|---|---|---|---|
| 1 | **③ 紧急域定级改造**：注册表驱动合法色档、按震级/深度/位置定级（含境内外门）、`grading.grading_candidates()` 审计面、缺省关键词表去掉种类词 | 实施席 WP3 撞 150 轮上限中断且**没留日志**；她这轮令"只修阻断项" | 全树搜 `WP3-TAXONOMY` 看 10 条用例（它们就是规格）；先修 `alert_taxonomy.UP035`/`push.RUF100` 顺手清 |
| 2 | **⑩ 中央调度层 Wave 1–4**：22 描述符通电 → 注册表升唯一真源 → 逐域接入 → 三硬骨头（根 handler 下沉 / pipeline 17 旁路 / 主动投递族） | 她这轮令只收阻断+收尾；Wave 0 是前置地基，已绿 | `impl-WP8W0-log.md` §8 写死了三处改法与"不得松的三把闸"；**动手前先复核规格 §2 的计数**（席位纠正了 5 处，见该 log ⑤） |
| 3 | **campus 坐标红** | 属外部在飞面，代改会被下一轮漂移覆盖 | 让该门 owner 在树稳定后一次性对齐 `tests/test_outbound_registry.py` |
| 4 | **待裁 P-1…P-4**（P-5 已自证销案） | 需她裁决 | ①占卜三键 + `bot_divination_db_path` 是否与 control_plane 键合一（推荐：合一+旧名再导出）②Wave 1–4 是否继续（推荐：先 1+2）③`SETTABLE_KEYS` 是否登记（推荐：只登记已证逐调用现读且接了合并层的）④v7/记忆总线开 true 的时机（推荐：重启后先开给自己） |
| 5 | **她的两件事** | 只有她能做 | ①提权重启 bot ②把 `test_doc_link_integrity._BASELINE_COORD_LEGACY` 从 837 下调（实降已到 357） |
| 6 | 全仓另外 **10 处 `subprocess.run(text=True)` 未钉 `encoding`** | 今天没咬到（子进程输出恰好纯 ASCII），怕范围失控没 sweep-fix | 症状=`stderr is None` + GBK `UnicodeDecodeError`；名单在 `master-plan.md` §8.8 B 表末段 |

## 6. 下一个 AI 必知的六个坑（每一个都真实咬过人）

1. **再导出 ≠ 修复**。§5-1 的阻断项原判"3 行再导出即可"是**错的**：真身签名收 `category_id`，调用方传 `item+allowed_levels`，
   照字面做只会把 ImportError 换成运行时 TypeError。**改前先读调用方与真身两边的签名**。
2. **半成品席留下的测试是规格**，不是噪音。别为了让门绿去放宽断言——**挂 `xfail(strict=False)` 并写摘牌指引**。
3. **xpass ≠ 实现**。`WP3-TAXONOMY` 里有 2 个实例是"旧关键词表恰好蒙对"，转正前必须查它是不是被兜住的。
4. **GBK 编码假红**：本仓铁律要 `export PYTHONIOENCODING=utf-8`，而若干测试用 `subprocess.run(text=True)` 不钉 `encoding`
   ⇒ 父进程按 GBK 解码子进程 UTF-8 中文 → reader 线程崩 → `stdout/stderr=None` → 门红。**先判编码再改产品码。**
5. **`dev.ps1 -Task typecheck` 会往源码树写 `__pycache__`**（该步不设 `PYTHONDONTWRITEBYTECODE`）⇒ 跑完必查
   `runtime-layout`，红了就按铁律 6「备份 %TEMP% 再移出」。（本波 95 个目录 / 369 个 .pyc 就是这么来的，已清并复跑 PASS。）
6. **文案红线门会打到自己人**：`test_copy_redline_gate` 扫随包源码，WP2 的繁简探针用了红线句简体字面量被判 Critical。
   处置=**换样本**，不是加豁免（豁免只会让门更软）。

## 7. 证据地图（要哪份点哪份）

| 主题 | 文件 |
|---|---|
| 审计总报告（三尺子 + 435 真身通读 + E/D 系列席位结论） | `docs/audit-20260921.md`（§0–§9，含 §9.6 全域通读与自纠） |
| 十三项决策书（给她看的白话版，含逐条利害） | `docs/audit-20260921-decisions.md` |
| 真机验收清单（A–G 组，G 组=本波 15 条） | `docs/audit-20260921-commands.md` |
| **本波交接态正文**（四态明细到符号 / 未提交清单 / 禁碰面 / 复跑命令 / 收尾执行记录） | `.superpowers/sdd/2026-09-21-fix-wave/master-plan.md` §捌 |
| 逐席交付报告（13 份） | 同目录 `impl-WP{1,2,3?,4,5,6,7,8D,8W0,9,10,11B}-log.md`（**WP3 无日志**） |
| 未提交文件全量清单（机器生成，1083 条） | `.superpowers/sdd/2026-09-21-fix-wave/uncommitted-inventory.md` |
| 设计规格 | `docs/design/{affinity-v7-design,memory-reflection-v2-design,divination-consolidation-20260921,capability-orchestration-adoption-spec,tts-contract-layer}.md` |
| 台账总账 | `AGENTS.md` #47、`docs/HANDBOOK.md` §38、`docs/issue-ledger-p2-p3.md` |
| 机器事实册（唯一与代码逐字相等的计数源） | `docs/auto-facts.md` |

## 8. 复跑命令簿（Git Bash，直接粘贴）

```bash
cd /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
export PYTHONIOENCODING=utf-8
P=../ChatBot_Runtime/venv/Scripts/python.exe

# 本波全部新门族（实跑 404 passed）
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 $P -m pytest \
  tests/test_affinity_v7.py tests/test_memory_bus_v2.py tests/test_memory_bus_v2_migration.py \
  tests/test_sync_drift_activation.py tests/test_capability_result_unique.py \
  tests/test_divination_consolidation_wp9.py tests/test_credential_domain_binding_gate.py \
  tests/test_content_safety_v6.py tests/test_route_priority_disambiguation.py \
  -p no:cacheprovider --basetemp="$TEMP/replay" -q

# 紧急域（阻断项修复后：0 红）
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 $P -m pytest tests/test_emergency_info_*.py tests/test_outbound_gate.py \
  -p no:cacheprovider --basetemp="$TEMP/em" -q

# 文档/生成物门族（实跑 104 passed）
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 $P -m pytest tests/test_documentation_consistency.py \
  tests/test_doc_link_integrity.py tests/test_cross_validation_gates.py tests/test_db_owners_coverage.py \
  tests/test_env_example_gate.py tests/test_doc_sync_gates.py tests/test_commands_md_generated_index.py \
  tests/test_copy_redline_gate.py tests/test_verify_hashes_coverage.py tests/test_autosync_hook.py \
  -p no:cacheprovider --basetemp="$TEMP/doc" -q

# 全量真值（务必带 BOT_AUTOSYNC=0，否则生成物门被自动 --write 抹平）
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 $P -m pytest tests -p no:cacheprovider --basetemp="$TEMP/full" -q
```

## 9. 红线（照抄自 `AGENTS.md` 第一部分，本波一条没破）

不 commit / 不 push（提交裁决权在用户）；不重启、不碰生产进程（用户提权重启）；
`.env` 与 `ChatBot_Runtime/**` 只读不写不删；`domains/weather/assets/qx.json` 禁动（历史上被误清 3 次）；
密钥零入日志/报告/聊天；直跑 python 必带 `PYTHONDONTWRITEBYTECODE=1` + `--basetemp` + `-p no:cacheprovider`；
子代理禁 git 写、禁再派代理、禁 `--write`（生成物只在收尾集中重录）；
人格/好感度红线：任何档位不攻击不强硬、算法说明只定性不展示数值；R-18 判据单一来源 `content_safety.py`。
## 10. 与同日另一波（#48 十板块文档体系）的合流对账

**同一工作树、同一天、两条线并行**：本波管**代码与能力**；#48 管**文档结构与命名归类**，
入口 [`HANDOFF-BOARDS-20260921.md`](HANDOFF-BOARDS-20260921.md) 与 [`docs/boards/_conventions.md`](docs/boards/_conventions.md)，
台账 `AGENTS.md` **#48**。两份入口在 AGENTS 顶部并列、各管一面（我已把自己那条的「优先于下方各条」改成「并列各管一面」，
没动他们那条）。

| 面 | 谁做的 | 内容 |
|---|---|---|
| 代码 / 能力 | 本波（#47） | 见 §3 |
| 文档体系 | #48 | 声明源 `domains/core/board_taxonomy.py` + 投影器 `scripts/board_doc_sync.py` + 生成物 `docs/boards/**`（`<!-- BOARD-AUTO -->` 标记内归机器、外归人）+ 常驻门 `tests/test_board_taxonomy_gate.py` + 规范 `docs/boards/_conventions.md` + 两份 `_meta` 台账；`dev.ps1 -Task sync` 已纳入板块重算与体检 |
| 共享文件重叠 | 两波先后改过 `AGENTS.md`、`task_plan.md`、`progress.md`、`findings.md` | #48 还 corrected 了 AGENTS 第四部分若干**路径口径**（例：错误卡真身 `domains/ops/monitor/error_report.py`、审核面真身 `domains/render/reviewer.py`）⇒ **路径以他们为准**，本波 #47 行内若有旧写法属文档滞后，不是代码问题 |

**合流真值（两波都落盘后，我本人实跑）**：

```bash
export PYTHONIOENCODING=utf-8
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_board_taxonomy_gate.py tests/test_doc_link_integrity.py tests/test_documentation_consistency.py \
  tests/test_doc_sync_gates.py tests/test_cross_validation_gates.py tests/test_env_example_gate.py \
  tests/test_db_owners_coverage.py -p no:cacheprovider --basetemp="$TEMP/merge" -q
PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/board_doc_sync.py --check
```

→ 门族 **79 passed**；`board_doc_sync --check` **EXIT 0**（板块/功能/入口/主题计数以生成物
`docs/boards/README.md` 为准，本文件不手写）。

**全量真值以谁为准**：#48 的终跑**晚于**本波 §4，且已含本波全部改动 ⇒
现役最新全量 = **#48 报的 `2 failed / 10975 passed / 13 skipped / 27 xfailed / 2 xpassed / 498.67s`**。
两红归属：① campus 坐标棘轮（**两波共同继承**，都不代改，归该门 owner）；
② 当时 #48 自己顶高的全量文档面棘轮（181 > 167，成因=席位把测试件名缩写成残名、把外部仓文件当本仓路径引用）——
**他们已逐条改回真身路径归零、没有降任何基线**，所以那条是修复前现场的记录。
**⇒ 现在新会话复跑全量，预期就是 1 failed**；一律以实跑为准，别拿任何一份文档里的数当现役。

**互指现状**：#48 已把本波收进 `docs/boards/_meta/doc-classification-20260921.md`；本文件 §7 与本节已回指 #48。
**建议（我没替他们改）**：`HANDOFF-BOARDS-20260921.md` 里补一条指回 #47 / 本文件，
否则只读文档线的 AI 会漏掉代码侧两笔挂账（`WP3-TAXONOMY`、调度层 Wave 1–4）。

**接手取舍**：动代码前看 §5（哪些是故意没做）；动文档/结构/命名前看 #48 §柒
（他们 11 席中 9 席被服务侧掐死、正文当时填充 152/225 页，续跑三步在他们 §7.3）。
两波都**未 commit、未重启** ⇒ `git status --porcelain | wc -l` 是唯一能看清全貌的东西：
本波登记时 1083 条，两波合流后 1090 条，这个数还会漂，**别把任何一份文档里的计数当现值**。
