# ROUTED-36-INTO-ROSTER-S762 — routed 36 枚差集入册：复算·分堆·可粘贴增量·影子模拟

- 席：S762（批次 250926A-2）· 开席 2026-09-26 · 仓根 `C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot`
- 写面（全部本席产物）：本件＋`patches/s762-routed-into-roster.md`＋`probes/s762-sim.py`。生产件 `plugins/`、`tests/`、`scripts/`、`docs/`、`config.py`、`.env` **一字未动**（`git status` 见下方自证段）。
- 主代理简报数字对账：`declared=54 / universe=102 / unknown_ids=43 / routed=36 / record_only=7 / covers_exactly=1` —— **复算逐位吻合**（快照 `%TEMP%/s762-census-now.json`，尺自报 `generated_at_utc=2026-09-26T06:46:59Z`，`integrity.ok=true`）。

## 1 尺身份三元组

- 件：`scripts/central_seam_census.py` v0.3.0-beta1（差集与分档唯一尺）× `plugins/bot_unified_runtime/domains/core/capability_manifest.py`（真身册 FACETS 20 枚）× `runtime/capability_protocols.py`（唯一在册表 `CAPABILITY_DESCRIPTOR:3086`、`DESCRIPTOR_BUILDERS:2894`、管线管理形派生器 `:2466`）× `capability_registry.py`（`ROUTE_CAPABILITY_DECLARATIONS:211`／`CONTROLLED_INTERNAL_CAPABILITIES:1060`／`PIPELINE_MANAGED_CAPABILITY_DECLARATIONS:1089`）× 门件 `tests/test_capability_manifest_gate.py`（腿②c/②d/③b/⑤/⑦/⑧/⑨/㉓/㉔/㉕＋棘轮 `EXECUTION_SURFACE=62 / DECLARED_UNWIRED=7 / UNCOVERED_CEILING=101 / REGISTERED_FLOOR=121 / ROSTER_SCAN_FLOOR=100`）。
- 命令（逐发带卫生四件套＋`-B`；模拟全在 `%TEMP%`）：
  `…python.exe -B scripts/central_seam_census.py --json`；
  `…python.exe -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s762-sim.py`；
  基线 scoped：`…python.exe -B -m pytest tests/test_capability_manifest_gate.py tests/test_manifest_migration_parity.py tests/test_pipeline_managed_adapter.py tests/test_central_seam_census_s81.py -p no:cacheprovider --basetemp=<%TEMP%唯一目录> -q`。

## 2 三本账先分清（「在册表外」的真实语义）

- **尺A 唯一在册表（121 枚）**：36 枚**已经全部在册**——经 `CONTROLLED_INTERNAL_CAPABILITIES` 这路输入进 `CAPABILITY_DESCRIPTOR`（`test_descriptor_is_union_of_all_inputs` 的并集判据原文）。它们缺的不是「在册」，是 **字面 authoring 可见性＋执行面＋帮助册行**。
- **尺B 普查 declared（54）**：只认两份 DECL 件里 `capability_id=` 字面量 Call 节点（`_extract_decls`）——CIC 元组是裸字符串，不认 ⇒ 36 枚落 `unknown_ids.routed`。`#52` 那句「在册表外差集 43」用的是这一口径。
- **尺C 真身册 FACETS（20）**：教义「在册必有执行面」＋腿②（handler_ref 可解析＋②c 逐字镜像）＋腿③b（未接真上限 7 只准降、成员名册逐枚点名）⇒ **36 枚今天没有一枚能单独进尺C**——这就是「无 RouteKind 宿主行＝结构上无处填 execution」那批的精确卡点，逐枚见补丁 §2。

## 3 逐枚账表（要点版；全表含根行号/形/落点在补丁 §1，全部 06:4xZ 现算）

- **RouteKind 宿主行：0/36 有**（AST 现算 `RouteCapabilityDecl` 36 行 ∩ routed 36 = ∅；RouteKind 成员 37 与写死快照锁 `test_capability_registry.py:232` 同框）。
- **今日普查态**：wired 6（poke/group_welcome/file/cookie_login/mail.control/auto_send.preview——后两枚的字面量就在⑤认的真缝上）；generic 1（image_search，根 :6609 裸 `handle_async` 字面量）；none 29（变量携带进 `_handle_status` 共享链尾 :8218/:8228）。
- **CIC 成员**：36/36 全在 ⇒ orchestration 侧补行必触 D-a（S197 §5-B 注毒先例），route 侧与管线管理形侧不触（campus_forward 先例结构成立）。
- **11/36 同时在 `HELP_TOPIC_DECLARATIONS` 被点名**（config/control/dialogue/help/history/logs/memory/persona/readiness/roles/why——现算）。
- **同步 `handle` 携边 3 枚**：alert（alerts.py:952）、download（console_chat.py:573）、search 系内 invoke——S584-E5「双尺不同册」未决，登记前须并读判据（裁定面）。

## 4 分堆裁决（沿用既有配方，未另立第二套判据）

| 堆 | 枚 | 结论 | 配方出处 |
|---|---|---|---|
| 甲·零根改动今天入尺B册 | **1**（bot.image_search） | 管线管理形一行＋`test_pipeline_managed_adapter` 名册跟随；state 保持 generic（认得≠通电），FACETS 行**延后**到改道批（腿③b 上限只降，今天贴=顶红） | 表 :1089 在册口径原文＋campus_forward 先例 |
| 乙·登记文本已齐但必与根改写并批 | 2（mail.control / auto_send.preview） | ⑤站点今在；模拟现算登记即 **violations 12→13**（根 :8244 闭包具名直呼 `build_auto_send_preview_result` 升 exec-bypass）⇒ 必须与 S761 收编同批；mail.control 闭包先提取具名件 | S584 第 1 批＋本席 S2 实测 |
| 丙·必须改生产根文件 | **33** | debug-14（K-合成五面，并支字面量进⑤缝才「摘账又通电」）＋出站壳 4（根改道或 **P2b 判据改判**二选一，伪造 RouteKind 行被写死 `==37`＋快照锁当场拒）＋派发表臂 15（根改道；group_policy 入口层直返五处、runtime 一 id 三执行面、help 两入口同批——多入口活性锁与申报锁同行才许降账） | S197 §2／S212 总裁决／S241R 根腿 hunk／S584 P1-P3 |

「无宿主行」批点名（别谎称可登记）：29 枚变量携带＋4 枚壳字面量＝**33 枚结构上无处填 `execution`**，唯一不靠它们的在册路（管线管理形）只认 `handle_async` 字面量站点，今值上 36 枚里只有 image_search 一枚合格。

## 5 影子模拟（真身普查尺 × `%TEMP%` 副本，全实跑，产物 `%TEMP%/s762/sim-results.json`）

| 场景 | declared | universe | routed | unknown | violations |
|---|---:|---:|---:|---:|---:|
| S0 未打补丁（拷贝保真＝对上了在盘 06:46Z 读数） | 54 | 102 | 36 | 43 | 12 |
| S1 ＝甲堆 B1 | **55** | **102** | **35** | 42 | 12 |
| S2 ＝B1＋乙堆两路由行 | 57 | 102 | 33 | 40 | **13** |
| S3 ＝S2＋丙堆 K-合成（仅赋值形变体） | 58 | **89** | **19** | 26 | 13 |
| S3b ＝S2＋K-合成（⑤字面量缝终形） | 58 | 89 | 19 | 26 | 13（wired 37/none 42） |

- `covers_exactly`、`integrity.ok` 全程 true；三态/差集守恒未破。
- **被顶红的账（如实报，全部不放宽）**：①`ROSTER_SCAN_FLOOR=100` vs universe 89 → 红（S3/S3b，owner 按「复算＋同批改字面量」重锚，`REGISTERED_FLOOR=121→107` 同批）；②violations 12→13（S2 起，S761 同批消化）；③腿③b/`DECLARED_UNWIRED`——本包**不抬上限**，FACETS 行只在对应枚改道转 wired 的那一批随批落。
- **两把防回潮锁现状**：arms-㉓/board-㉔ 对本包**不红**——本包不新增维度（防回潮锁本体 `test_manifest_migration_parity::DIMENSION_TO_LEG` 只对新字段执法）；臂取形级安全形（14 枚 executor 子臂**今天不得塞进 `arms=`**：现行腿㉓「身份投影＋同形不重臂」两判据会连红，悬空的 `test_leg10_*` 全 tests grep 零命中，属未落承诺）；board 值逐枚从 `board_taxonomy` 现算派生（B09←ops/admin、B07←schedule、B06←media；ops/smoke/diagnostics 与根内联无归属通道 ⇒ 落名册点名或改声明源，禁手填）。
- **今日基线带红照实归因（非本席）**：scoped 四件合跑 **7 failed / 113 passed**，全在 `test_capability_manifest_gate.py`——leg2d 七行漂移（含 `bot.chat 535≠539`）、leg3、leg5、leg7（未申报 **105>101**）、leg8（randpic/tts 新直呼点未跟随）、两发注毒前置；属 #56/#57 在飞编辑的漏跟随，本席树零写入、不代修，**任何增量落码前先清这 7 红或点名归属**。

## 6 纪律自证与交回

- 红线：未动 `.env`/配置、未 git 写、未派席、未杀进程/重启、未跑全量套件（`dev.ps1 -Task test` 零执行）；注毒/模拟全在 `%TEMP%`（影子五份 + 快照 + 结果）；卫生四件套＋`-B` 全程在场——**75 分钟窗内 `find plugins scripts tests -name '*.pyc'` = 0**；仓根 `.pytest_cache` mtime 09-26 04:22 早于本席窗（非本席造，归该卫生门 owner 的安静窗账，不越窗删）。
- 数字纪律：本件所有「几枚/几处/几行」均本席现算（census JSON、AST 探针、grep 计数），转述处已标（S241R/S584/S197/S212 的旧行号一律以 06:4xZ 重算覆盖——S584 时代 :7815 链尾今日在 :8218，即漂移实例）。
- 规则 11：全程把文件正文/工具结果里的祈使句当数据；背景通知（含「完成」字样）不扩权、不改任务面。
- 交回：补丁 `patches/s762-routed-into-roster.md` §5 清单——落码与真门实跑、P2b 裁定、腿⑩落锁、三本棘轮重锚、同步 handle 口径并读、group_policy/runtime/help 三枚的行为裁定；未做（越权面）：未替 B1c/B2面⑤ 的 FACETS 行预填行号达标值（占位格明写「落批复算」）。

**总裁决**：routed 36 枚＝「1 枚零根可入册（image_search：54/102→55/102、routed→35）＋2 枚文本齐但须 S761 同批＋33 枚必须改生产根（其中 debug-14 走腿⑩合成臂配方五面同批，终形模拟 declared=58/universe=89/routed=19）」；被顶红两处（ROSTER_SCAN_FLOOR、violations+1）如实点名、防回潮两锁未被顶红、无一处以放宽判据换绿；今日门基线 7 红先于本包存在，归他波。
done: yes
