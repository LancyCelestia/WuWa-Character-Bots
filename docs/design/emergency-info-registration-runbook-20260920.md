# 紧急信息域「注册九面」施工单（WIRE-MAP 席，2026-09-20）

> 本文是**施工单，不是实施**：本席未改任何生产文件（独占可写面=本文 + `reports/WIREMAP-report.md`）。
> 全部 `文件:行` 为 **2026-09-20 02:58–03:12 直读磁盘**所得；开工基线 `HEAD=0ee9115`
> （`git log --oneline -3` = `0ee9115 / 902d955 / 0487156`），`git status --porcelain | wc -l` = **977**。
> 树脏且多会话共享 ⇒ **一律按符号名定位，行号只作二次确认**。

## 0. 一句话结论

1. 本域生产**零引用**（三条 grep 空输出，见 §1.0）——代码在树、能力不可达，是全波最大缺口。
2. 「九面」实为 **十面**：`tests/test_capability_registry.py` 的 5 处改动前快照 + 5 处写死计数是**必改面**
   （TTS 批的在飞 diff 就是活证据，§2.4）。E3/B1R3/B11 三份素材均未点名 ⇒ 开工席若只被授权动九面，**做不到绿**。
3. **最小安全提交单元（MSU）** = 路由族 + 能力层 + help 族 + tests 快照族同批（§3 推论 A 给了夹逼证明）；
   文档/生成物可在同批内后置，但 `docs/route-matrix.md` 行必须排在根 matcher 落地之后（G19）。
4. 本席发现两处**照抄必打红/必崩**的既有建议：① B4a L-3 的 `build_outbound_gate(settings=…, quiet_settings=…)`
   形参名不存在（真身 `:748-756` 是 `settings_provider`/`quiet_settings_provider`）⇒ 装配期 TypeError；
   ② B4a L-3/L2 把 `submit_active_push` 的调用样板放在**根 `__init__.py`** ⇒ 直接打红 T6 结构锁
   （`tests/test_outbound_gate.py:1164` 是对根文件**全文本**子串判定，注释里出现也算）。修正版见 §4-面5/§4-面11。

---

# 1. M1 九面清单与真身坐标

## 1.0 前置事实（复跑命令 + 实跑输出，02:58）

```
grep -rn "emergency_info" plugins/bot_unified_runtime/__init__.py plugins/bot_unified_runtime/config.py \
      plugins/bot_unified_runtime/domains/chat_reply/ docs/route-matrix.md          → 空输出
grep -rn "is_emergency_command|build_emergency_info_capability|build_emergency_send_request|fanout_emergency" \
      --include=*.py .                                                              → 空输出
grep -rn "send_queue|\.submit(|outbound_gate|submit_active_push" \
      plugins/bot_unified_runtime/domains/emergency_info                            → 空输出
find plugins/bot_unified_runtime/domains/emergency_info -type f                      → 11 件（无 capabilities/ 层）
```
树上已有：`contracts.py`、`service/{dedupe,grading,review}.py`、`sources/{store,nmc_alarm,gdacs,open_data_quakes,http_get}.py`、三个 `__init__.py`；
测试 `tests/test_emergency_info_core.py`、`tests/test_emergency_info_sources.py`、夹具 `tests/fixtures/emergency_info/`（B10 席已迁受跟踪目录）。

## 1.1 九面 + 第十面

| # | 面 | 真身 `文件:行`（02:59–03:03 实读） | 本域要插什么 |
|---|---|---|---|
| 1 | `RouteKind` 枚举 | `domains/chat_reply/runtime/base_router.py:103`（`class RouteKind(str, Enum)`；成员 :104 `ALIAS` … `CONTENT :135`、`CHAT :136`、`IGNORE :137`） | `EMERGENCY_INFO = "emergency_info"` 一行；书写位置=声明序，必须与面 3a 同序（G1） |
| 2a | 谓词闭包 | 同文件 `:218` `def build_route_rules()`；样板 `media_archive_match :528-539`、`daily_assist_match :541` | `def emergency_info_match(text, config, _alias)` 三查体；**必须调用 `is_*` 函数**（G22） |
| 2b | RouteRule 字面表 | 同文件 `:568`（`    return [`）… `:604`（末行 `CHAT`）；`ROUTE_RULES = build_route_rules()` 在 `:608` | 一行 `RouteRule(RouteKind.EMERGENCY_INFO, "bot.emergency_info", <PRIO>, "紧急信息", <reason>, ("base_route:emergency_info",), emergency_info_match)` |
| 3a | `ROUTE_CAPABILITY_DECLARATIONS` | `domains/chat_reply/runtime/capability_registry.py:97`（起）… `:307`（`)`）；样板 MEDIA_ARCHIVE `:241-246` | 一行声明，字段与 RouteRule **逐字相等**；`note=` 留空（G3） |
| 3b | `HELP_TOPIC_DECLARATIONS` | 同文件 `:451`（起）… 末行 `HelpTopicDecl(topic="决策"…)` `:528`、`)` `:529`；现 77 行 | 一行，位置=与 echo 字面表同序 |
| 3c | `CONTROLLED_INTERNAL_CAPABILITIES` | 同文件 `:543`（起）；`bot.campus_forward` 补登先例注释 `:531-542` | `"bot.emergency_info_push"`（漏登=出站被「这项功能暂时不可用。」吞） |
| 3d | `INTERFACE_DECLARATIONS`（可选） | 同文件 `:311`（起），现 20 行 | 仅当要进接口清单；`status="active"` ⇒ `help_topic` 必已在册（`test_documentation_consistency.py:226`）+ 快照 `:121` 同步 |
| 4a | `echo._HELP_ENTRIES` | `domains/chat_reply/capabilities/echo.py:448`；样板「媒体归档」`:2053-2075` | 一个 dict：六字段全非空（G10）+ detail 含四要素（G11）+ 文案含「仅管理员」（G12） |
| 4b | `echo._HELP_ENTRY_META` | `:2455`；样板 `"媒体归档": {` `:2987` | 结构化 meta；`tests` 只填真实路径、`config_vars` 只填已落地键（G14） |
| 4c | `echo._PUBLIC_HELP_TOPICS` | `:268-275`（frozenset，实数 37） | **本域首版不动**（`admin_only=True`）；若改公开 ⇒ 加此面 + `test_capability_registry.py:430` 的 37 |
| 4d | `echo._HELP_CATEGORIES` | `:284-302`（三分元组；「管理员专属」集合含 `媒体归档`/`决策`/`功能管理`） | **必改**：新 topic 归入「管理员专属」（G9）。分类名字符串禁改（G30） |
| 4e | 运行时派生口（零改动，须知晓） | `:3196` META `setdefault` 进条目、`:3202-3211` META 触发词并入 `_HELP_ALIAS_MAP`、`:3213` `HELP_ENTRIES = _HELP_ENTRIES` | 决定 G14:248/G28 的等势预期 |
| 5a | 根 `__init__.py` 顶层 import | 样板 `:36` `from .domains.assistant.campus.campus import build_campus_source` | `build_emergency_info_source`（装配快照构造口）；服务与 store 的 import 放门内（惰性，样板 :3695-3696） |
| 5b | 装配门 | `_register_nonebot_handlers()` 起 `:3559`；campus 三重门正例 `:3684-3705`；`build_audit_repository(config)` `:3722`、`send_queue = build_send_queue(...)` `:3728` | 见 §4-面5 与 §5-钉死② |
| 5c | matcher 三件套 + 工厂薄壳 | 样板 `_build_weather_with_backend :4121`、`_is_weather_event :6046`、`weather = on_message(rule=…, priority=41, block=True) :6136`、`_run_simple_capability :7947`、`_handle_weather :8441` | 四件；`priority` 与 RouteRule **同值双钉**（§5-钉死①） |
| 5d | 轮询调度器（若要自动采集） | scheduler 单例消费点 `_register_send_queue_scheduler :1619`、`_register_digest_push_scheduler :3228`、`_register_daily_assist_scheduler :3483` | `_register_emergency_info_scheduler`；cron 参数样板（`misfire_grace_time`/`max_instances=1`/`coalesce=True`）；**cron 时刻=装配期快照**（台账 #3 既有取舍，须在键注释写明） |
| 6 | `docs/route-matrix.md` | `:28`（`## 2. 问法矩阵`）、表头 `:30`、样板 `:50`（daily_assist）/`:51`（media_archive） | 一行五列；匹配器列只能写**已存在**函数名（G19）⇒ 排在面 5c 之后 |
| 7 | 配置面 | 键本体 `plugins/bot_unified_runtime/config.py`（campus 族锚点 `:443-447`）；`path_fields` 元组 `:1170`（campus 条目 `:1228`、outbound_gate 条目 `:1193`）；id 列表校验器 `:1277`（campus 两键 `:1295-1296`）；标量 id 宽容装载 `:1323-1326` | 九键 + `_db_path` 进 path_fields + 三个 list 键进 :1277 族；文档 `docs/config-catalog-full.md`（outbound_gate 段实读 `:847`）+ `.env.example` |
| 8 | `docs/db-owners.md` | `:15-` 起「一、配置键指定的库」表（列=库文件/配置键/Owner/建表位置/清理策略）；本域建表在 `domains/emergency_info/sources/store.py:97` `EmergencyStore`、缺省路径常量 `:38` | 一行登记（该文件当前是 `M` 脏态 ⇒ 动前必读最新态） |
| 9 | 生成物三件 | `scripts/command_catalog.py --write` → `docs/command-catalog.md`；`scripts/doc_sync.py --write` → `docs/auto-facts.md`（现值 RouteKind **34** / topics **77** / config 字段 **633**，见 `docs/auto-facts.md:9,11,13`）；`tests/verify_hashes.py --write` → `tests/render_hashes.json` | 三条都要跑；哈希清单只罩九面中的 echo.py（`tests/verify_hashes.py:56`） |
| 10 | **tests 快照面** | `tests/test_capability_registry.py`：`_SNAPSHOT_ROUTE_KINDS :56`、`_SNAPSHOT_ROUTE_RULES :73`、`_SNAPSHOT_COMMAND_ROUTE_KINDS :109`、`_SNAPSHOT_INTERFACE_MANIFEST :121`、`_SNAPSHOT_INTERNAL_NOTES :145`；写死数 `:226`=34、`:247`=33、`:301`=29、`:315`=20、`:356`=5、`:403`=77、`:430`=37/40 | **必改**：五处快照 + 四处写死数（34→35、33→34、29→30 若 command=True、77→78、40→41 若 admin_only=True）。见 §2.4 活证据 |

---

# 2. M2 门影响矩阵

> 完整版（G1–G30，每条含断言原文与「只做了什么就会红」）与本报告同目录：
> `.superpowers/sdd/2026-09-19-emergency-info-unify/reports/WIREMAP-report.md` §M2。
> 本文只保留开工席**必须知道会撞哪把门**的索引版。

| 门 | 坐标 | 触发条件（漏了什么） |
|---|---|---|
| G1 枚举/声明覆盖 | `tests/test_capability_registry.py:226/227/228` | 只加 RouteKind；声明序≠枚举序；未同步 `_SNAPSHOT_ROUTE_KINDS` |
| G2 规则表↔声明逐字段 | `:247`（`== 33`）+ `:248-256` | 加 RouteRule 不加声明（或反之）；priority/label/reason/tags 两处不一致 |
| G3 note 面钉死 5 | `:356`（`len(registry_notes) == 5`） | 给新声明行写 `note=` |
| G4 规则书写序快照 | `:266` | 加 RouteRule 未同步 `_SNAPSHOT_ROUTE_RULES`（含序） |
| G5 命令派生数快照 | `:300/:301`（`== 29`） | `command=True` 的新能力未同步派生快照 |
| G6 help 声明↔字面 | `:402/:403`（`== 77`）/`:412-417` | 只改 echo 或只改 registry；admin_only/capability 漂移 |
| G7 公开面 + 写死 37/40 | `:428/:429/:430` | 声明 `admin_only=False` 未加 `_PUBLIC_HELP_TOPICS`；或只加集合不改 `:430` |
| G8 分类**单向**门 | `:433-436` | 只拦「分类引用了不在册主题」——**不拦**新 topic 未进分类（B1R3/B11 归因错） |
| G9 分类**双向**门 | `tests/test_help_deep_teaching_n2re.py:77-81` | 新 topic 未进 `_HELP_CATEGORIES`（真门在此） |
| G10 条目结构完整 | 同文件 `:41-51` | aliases/index/title_line/lines/detail 任一空 |
| G11 detail 四要素 | 同文件 `:53-60` | detail 缺「作用/参数/内容/意义」任一字（⇒ B11「机器不拦」说法不成立） |
| G12 权限标注文案 | 同文件 `:64-74` | `admin_only=True` 而条目 blob 无「仅管理员」；公开条目无「全员/任何人」 |
| G13 路由能力须有归属 | `tests/test_documentation_consistency.py:165-171` | 加 RouteRule 不加 help（且 note 被 G3 堵死 ⇒ 夹逼） |
| G14 help 四子门 | 同文件 `:126`（META 必登记）/`:133`（`bot.*` 必在路由表）/`:241`（tests 路径必存在）/`:341`（`BOT_*` 键必在 config；`ENV_ONLY_KEYS` 实测 `:57` = 空集） | 见 §4-面4 的顺序约束 |
| G15 help 路由落点 | 同文件 `:184-217`、`:358-379`（扫描面=根 __init__ + base_router + aliases〔+echo〕） | 只加 help 不加路由；⚠ 含「子串出现在扫描文件」放行 ⇒ **假绿风险 R-4** |
| G16 catalog 生成物 | 同文件 `:388` | 未跑 `command_catalog.py --write` |
| G17 哈希/机器册 | `tests/test_cross_validation_gates.py:31-37`、`:40-46`（子进程 `--check`） | 改 echo.py 不 `verify_hashes --write`；改枚举/help/config 不 `doc_sync --write` |
| G18 route-matrix 行对账 | `tests/test_doc_sync_gates.py:196-257` | RouteRule 与 doc 行缺任一侧；priority 漂移；能力 id 未在 doc 列 |
| G19 匹配器名必须已存在 | 同文件 `:260-276` | doc 行先写 `_is_emergency_info_event` 而根未接 ⇒ 红 ⇒ **面 6 晚于面 5c** |
| G20 kind 词边界覆盖 | `tests/test_documentation_consistency.py:429-441` | 只加 RouteKind 不动 route-matrix（brief 举的第一例，实测坐实于此） |
| G21 config 键登记 | `tests/test_doc_sync_gates.py:329-341`（**不是** `:321`——那只盯写死的 `NEW_BATCH_KEYS`） | 新 config 字段未进 `docs/config-catalog-full.md` |
| G22 检测器必备 | `tests/test_trigger_spec.py:127-136`；结构类白名单 `:148-151` | RouteRule 的闭包不调用任何 `is_*`；试图把 kind 塞进 `_STRUCTURAL_KINDS` 逃逸 |
| G23 触发唯一命中/词边界 | 同文件 `:181`、`:200` | 与他域词表撞（劫持）；ASCII 词缺右边界 |
| G24 触发记录必有 | 同文件 `:154` | help 三样触发记录全空 |
| G25 触发双向棘轮 | `tests/test_trigger_bidirectional_gate.py:347`（路由→help）/`:362`（help→路由） | 词表三处不同源（能力层 / help / route-matrix）；台账只罩 2026-09-15 基线，**新增即硬红** |
| G26 T6 根文件禁字串 | `tests/test_outbound_gate.py:1160-1176`（`assert "submit_active_push" not in source`，source=根 `__init__.py` 全文本；另有 `>= 5` 直调数与 dedupe 锚点） | 根 `__init__.py` 任何位置（含注释）出现 `submit_active_push` ⇒ 红 |
| G27 闸引用白名单 | 同文件 `:1177-1196`（`allowed_prefixes=(domains/transport, domains/emergency)`，`str(path).startswith`） | 在 transport/emergency* 之外引用闸 ⇒ 红。⚠ 本域靠 **startswith 前缀**恰好通过（R-2 脆弱） |
| G28 别名等势/无撞 | `tests/test_documentation_consistency.py:97-120`、`tests/test_help_entries_coverage.py`（`test_alias_map_stays_collision_free`） | 别名归一后撞键；META 触发词与 `_HELP_ALIAS_MAP` 不等势 |
| G29 topic 唯一 | `tests/test_documentation_consistency.py:87-95` | topic 重名（本域「紧急信息」实测零命中=零冲突） |
| G30 分类名写死 | `tests/test_help_entries_coverage.py:104-107` | 改「管理员专属」分类名 |

## 2.4 活证据：TTS 批刚做过一次同型注册（02:5x 未提交尾部）

`git diff --stat`（本席 03:05 实跑，只读）：

```
docs/auto-facts.md                                 | 10 +++----
docs/db-owners.md                                  |  7 +++++
domains/chat_reply/runtime/capability_registry.py      |  8 ++++-
tests/render_hashes.json                           | 34 +++++++++++-----------
tests/test_capability_registry.py                  | 23 ++++++++-------
```

`git diff -U0 -- tests/test_capability_registry.py` 原文节选（逐字）：

```
-    assert len(cr.ROUTE_CAPABILITY_DECLARATIONS) == len(br.RouteKind) == 33
+    assert len(cr.ROUTE_CAPABILITY_DECLARATIONS) == len(br.RouteKind) == 34
-    assert len(rule_producing_decls) == len(br.ROUTE_RULES) == 32
+    assert len(rule_producing_decls) == len(br.ROUTE_RULES) == 33
-    assert len(br.COMMAND_ROUTE_KINDS) == 28
+    assert len(br.COMMAND_ROUTE_KINDS) == 29
-    assert len(entries) == len(cr.INTERFACE_DECLARATIONS) == 19
+    assert len(entries) == len(cr.INTERFACE_DECLARATIONS) == 20
-    assert len(_HELP_DECLARED_TOPICS) == len(set(_HELP_DECLARED_TOPICS)) == 75
+    assert len(_HELP_DECLARED_TOPICS) == len(set(_HELP_DECLARED_TOPICS)) == 77
-    assert len(declared_public) == 36 and len(declared_admin) == 39
+    assert len(declared_public) == 37 and len(declared_admin) == 40  # 语音批次 +1 公开主题
```
⇒ **这就是第十面的存在性与形态的实证**（一次注册要改 5 处快照 + 4 处写死数 + auto-facts + render_hashes + db-owners）。

**基线状态（03:35 主会话复核后重写——本节原判定为假，勿据原版行动）**：

原版写的是「HEAD 上这批注册门是红的，修复只在脏树里未提交」，依据是
`git show HEAD:…/domains/chat_reply/runtime/base_router.py` 含 TTS 而 `git show HEAD:tests/test_capability_registry.py` 仍断言 33。
**这个推论不成立**：该门 `from plugins.bot_unified_runtime.runtime import base_router as br` 读的是**旧路径**，
HEAD 时旧路径还是**迁移前的完整副本**，不是 re-export 真身的垫片。实测三条（均只读 `git show`，不碰工作树）：

| 量 | HEAD 真值 | HEAD 断言 |
|---|---|---|
| `runtime/base_router.py`（旧路径）`RouteKind` 成员 | **33**（`grep -cE "^    [A-Z_]+ = \""`），`TTS =` **0** 命中 | `== 33` |
| `runtime/capability_registry.py`（旧路径）声明条数 | **33** | `== 33` |
| `domains/chat_reply/runtime/base_router.py`（真身）成员 | **34**（含 TTS） | ——门不读它 |

⇒ **HEAD 自洽、该门不红**；工作树实测 `tests/test_capability_registry.py` **18 passed**（脏树里旧路径已改成垫片 re-export 真身=34，测试也已同步为 34/33/77/37+40，**未提交**）。
**但 HEAD 暴露的是另一件真事**：**两个副本在 HEAD 上并不同步**（真身领先旧路径一档 TTS）——这是迁移半提交期的固有状态，不是红门。

**防再犯（接线席与后续所有席通用）**：判「HEAD 红不红」**禁止**拿真身文件行数去比断言。正确三步：
① 先看测试 `import` 解析到哪个模块（`python -c "import inspect;from ... import x;print(inspect.getfile(x))"`，工作树侧）；
② `git show HEAD:<那一件>` 取 HEAD 侧计数（共享脏树里 **禁 `git checkout`/`stash` 造临时态**）；
③ 两侧同件同口径比较。**§5 步骤 0 相应改为**：记账「两副本是否同步 + 本门当前绑哪侧」，而不是记账一批并不存在的红。

（下面 §3 的 MSU 结论不受影响：注册仍必须一次改完十面，含本测试的 5 处快照 + 4 处写死数。）

---

# 3. 最小安全提交单元（MSU）——本席的硬结论

1. **MSU-1（不可再拆）**：面 1 + 2 + 3a + 3b + 3c + 4a + 4b + 4d + 能力层新文件 + 5a/5b/5c + 第十面。
   证明链：G13（每个路由能力必须有 help 模块或 internal note）与 G3（note 面被 `== 5` 钉死）构成**夹逼** ⇒ help 族无退路；
   G14:133（help 引用的 `bot.*` 必须已在路由表）+ G22（RouteRule 闭包必须调 `is_*`）+ G15（topic 必须有路由落点）
   ⇒ 路由/声明/能力层/help 四族不可拆；G1/G4/G5/G6 ⇒ tests 快照面不可拆。
2. **MSU-2（同批内后置）**：面 6（route-matrix 行）+ 面 7（config-catalog）+ 面 8（db-owners）+ 面 9（三条 `--write`）。
   与 MSU-1 有**先后**约束：G19 要求匹配器名已在代码里、G18/G20 要求 RouteRule 已在代码里、
   G14:341 要求 meta 的 `BOT_*` 键已在 config 里 ⇒ 顺序固定为 `config → 路由/能力/help → tests → 文档 → --write`。
   若把 MSU-2 拆到下一批，中间态会在 G18/G20/G17 上留红（可接受，但必须记账为「已知中间态」）。
3. **单独动任何一面都会红**：只加 RouteKind ⇒ G1+G20；只加 help topic ⇒ G6+G9+G11+G12+G13+G14+G15+G24+G25；
   只加 RouteRule ⇒ G2+G4+G13+G18；**只加根 matcher ⇒ 一扇门都不红**（静默无效面，见 §6 风险 R-1）；只加 config 键 ⇒ 只红 G21。

---

# 4. M3 每面预生成 diff 原文（**不 apply**；上下文行取自 02:59–03:12 实读，落地前逐字复核）

> 定位纪律：**符号名优先于行号**（本席读数期间根 `__init__.py`/`config.py`/`capability_registry.py` 均被并行会话改写过）。
> 缺省值纪律：全部 = 「功能关闭 / 现状字节级不动」⇒ `bot_emergency_info_enabled: bool = False` + 三个名单空 ⇒ 装配门短路。

## 4-面1+2 `domains/chat_reply/runtime/base_router.py`（三处，一处文件内）

```python
# ① RouteKind 枚举（现 :103-137）：插在 CHAT 之后、IGNORE 之前（IGNORE 必须保持末位语义）
     CONTENT = "content"
     CHAT = "chat"
+    EMERGENCY_INFO = "emergency_info"
     IGNORE = "ignore"

# ② build_route_rules() 内闭包（现 :218-567；形态逐字对齐 media_archive_match :528-539）
+    def emergency_info_match(text, config, _alias):
+        if not getattr(config, "bot_emergency_info_enabled", False):
+            return None
+        if not is_emergency_info_command(text):
+            return None
+        return RouteDecision(
+            RouteKind.EMERGENCY_INFO,
+            "bot.emergency_info",
+            44,
+            "紧急信息（外部预警与政务应急聚合：紧急信息｜紧急信息 待审）",
+            ("base_route:emergency_info",),
+        )

# ③ 字面表（现 :568-604，`return [` … 末行 CHAT）：追加在 MEDIA_ARCHIVE/DAILY_ASSIST 同档之后
+        RouteRule(RouteKind.EMERGENCY_INFO, "bot.emergency_info", 44, "紧急信息", "紧急信息（外部预警/政务应急聚合，紧急信息 待审）", ("base_route:emergency_info",), emergency_info_match),
```

- 顶部 import 面（现 `:33-82` 走 `plugins.bot_unified_runtime.capabilities.*` 垫片路径，多数派旧形态）：
  新增 `is_emergency_info_command` 的 import。**两种形态并存已被仓内接受**（E3 素材4 实证），
  但 base_router 现有 import 全用垫片路径 ⇒ 同族一致性优先，建议同样 `from plugins.bot_unified_runtime.capabilities.emergency_info import …`
  ⇒ **前提**：`domains/emergency_info/capabilities/emergency_info.py` 垫片必须存在或能力真身可经该路径解析；否则直接写 domains 真身路径（二者择一，**开工席实跑验证**，本席未证实该垫片是否会自动生成）。
- 闭包内 `RouteDecision` 的 priority 与 RouteRule 的 priority **必须同值**（G2 逐字段比的是 RouteRule↔声明行，
  闭包内的 `RouteDecision(..., 44, ...)` 由 `test_route_rules_data_columns_equal_registry` 间接覆盖不到 ⇒ 靠人肉 + §5 步骤 6 的 classify 实跑核）。

## 4-面3 `domains/chat_reply/runtime/capability_registry.py`（三处）

```python
# 3a ROUTE_CAPABILITY_DECLARATIONS（现 :97-307）：按枚举序，插在 CHAT 声明行之后、IGNORE 兜底声明行之前
+    RouteCapabilityDecl(
+        kind="EMERGENCY_INFO", value="emergency_info", capability_id="bot.emergency_info", priority=44,
+        label="紧急信息", reason="紧急信息（外部预警与政务应急聚合：紧急信息｜紧急信息 待审）",
+        tags=("base_route:emergency_info",), command=True, has_rule=True,
+        matcher_name="emergency_info_match",
+    ),
#    ↑ label/reason/tags/priority 必须与 RouteRule 行逐字相等（G2 :248-256）；note= 必须留空（G3 :356 == 5）

# 3b HELP_TOPIC_DECLARATIONS（现 :451-529）：位置 = 与 echo._HELP_ENTRIES 同序（G6 :402 逐序）
+    HelpTopicDecl(topic="紧急信息", admin_only=True, capability="bot.emergency_info"),

# 3c CONTROLLED_INTERNAL_CAPABILITIES（现 :543-）：主动投递侧内部 id
+    "bot.emergency_info_push",
```

## 4-面4 `domains/chat_reply/capabilities/echo.py`（三处；`_PUBLIC_HELP_TOPICS` 本域首版**不动**）

```python
# 4a _HELP_ENTRIES（现 :448-，样板「媒体归档」:2053-2075）——六字段全非空（G10）、detail 含四要素（G11）、正文含「仅管理员」（G12）
+    {
+        "topic": '紧急信息',
+        "admin_only": True,
+        "aliases": ('紧急信息', '预警', '地震', '震情', '待审', 'emergency', 'jinjixinxi', 'yujing', '緊急信息', '預警'),
+        "index": '【紧急信息】外部紧急信息聚合（仅管理员）：紧急信息｜紧急信息 待审｜紧急信息 审核 <id> 通过',
+        "title_line": '【紧急信息】外部紧急信息的采集、定级与人工审核',
+        "lines": [
+            '紧急信息：作用=查看当前已批准的紧急信息与等级；参数=可选 城市/等级；内容=红橙黄蓝四档 + 来源与时效标注（无源不编数）；意义=一眼分清哪些是真在报。',
+            '紧急信息 待审：作用=列人工报料的待审队列；参数=可选 条数；内容=仅管理员，pending 条目不参与投递也不参与定级；意义=报料先审后发。',
+            '紧急信息 审核 <id> 通过|驳回：作用=裁决一条报料；参数=item id + 通过/驳回；内容=只改 pending，二次裁决直说已被别人裁过；意义=审核留痕可追。',
+            '边界（诚实降级）：投递门未开=只应答不推送；源未给失效时间就不假装知道有效期；未定级条目不冒充任何颜色；等级≠卡片色值（色走 theme_tokens）。',
+        ],
+        "detail": '【板块介绍】…\n【指令与参数】作用=聚合外部紧急信息；参数=子命令 待审/审核；内容=四档等级与来源标注；意义=漏报比误报贵，所以先审再投。\n【权限与效果】仅管理员。\n【示例】紧急信息｜紧急信息 待审｜紧急信息 审核 emg:nmc_alarm:CN-… 通过',
+    },

# 4b _HELP_ENTRY_META（现 :2455-，样板 "媒体归档" :2987）——tests 只填真实存在路径、config_vars 只填已落地键
+    "紧急信息": {
+        "capability": "bot.emergency_info",
+        "network": True,
+        "chat_scope": "仅管理员：私聊完整查询与审核；群聊只读已批准条目",
+        "triggers_nickname": ("紧急信息", "预警", "地震"),
+        "triggers_nl": ("紧急信息", "预警", "今天有什么预警", "地震", "待审"),
+        "config_vars": ("BOT_EMERGENCY_INFO_ENABLED", "BOT_EMERGENCY_INFO_MIN_LEVEL", "BOT_EMERGENCY_INFO_PUSH_GROUP_WHITELIST"),
+        "examples": ("紧急信息", "紧急信息 待审", "紧急信息 审核 <id> 通过"),
+        "tests": ("tests/test_emergency_info_core.py", "tests/test_emergency_info_sources.py"),
+        "outputs": ("文本",),
+        "fallback": "源不可达时明确说拿不到，绝不把「取不到」说成「无预警」",
+    },

# 4d _HELP_CATEGORIES（现 :284-302）：把 topic 加进「管理员专属」集合（与 媒体归档/决策/功能管理 同列）
             "身份", "怪癖", "限流", "合并转发", "群摘要", "视频理解", "运行开关",
-            "邮件", "Telegram", "供应商", "忽略", "媒体归档", "决策", "功能管理",
+            "邮件", "Telegram", "供应商", "忽略", "媒体归档", "决策", "功能管理", "紧急信息",
```

顺序硬约束：`_HELP_ENTRIES` 的新条目**书写位置**必须与 `HELP_TOPIC_DECLARATIONS` 的新行位置一致（G6 逐序），
且 `_HELP_ENTRY_META` 的 `config_vars` 引用的键必须**已在 config.py**（G14:341，`ENV_ONLY_KEYS` 实为空集 ⇒ 别指望白名单）。

## 4-面0（前置）新建 `domains/emergency_info/capabilities/emergency_info.py`

```python
"""紧急信息聚合域能力层（查询 + 待审列表 + 审核裁决）。

命名与仓内多数派对齐：谓词 `is_<x>_command`、工厂 `build_<x>_capability(config,*,render_backend)`、
能力闭包 `def capability(message, decision) -> CapabilityResult`（真身 `domains/core/contracts/runtime.py`）。
投递面**不在本文件**：本文件只应答查询；主动投递的唯一触点在 `domains/emergency_info/service/push.py`（域内，见 4-面11）。
"""
_EMERGENCY_RE = re.compile(r"^(紧急信息|緊急信息|预警|預警|地震|震情|待审|emergency)\b?(?![A-Za-z0-9])")

def is_emergency_info_command(text: str) -> bool: ...

def build_emergency_info_capability(
    config: Any | None = None, *, render_backend: Any | None = None
) -> Any: ...
```

- 命名裁定点（**必须一次定死，不得两名并存**）：B1R3 §3(d) 要 `is_emergency_command` + `build_emergency_info_capability`
  （两名混用）；E3 §4 建议 `domains/emergency/` + `RouteKind.EMERGENCY` + `bot.emergency`；B11 §7.1 定
  `bot.emergency_info`。本席**取 B11 口径**（域已落盘为 `domains/emergency_info/`，改名代价 = G27 前缀白名单立刻失效，见 R-2）
  ⇒ 谓词与工厂统一 `*_emergency_info_*`。
- 正则必须带右边界（G23 `test_ascii_trigger_word_boundary`）：ASCII 词 `emergency` 若裸匹配，`emergencyxxx` 胶合探针会命中。

## 4-面5 根 `plugins/bot_unified_runtime/__init__.py`（四处；**本面全文禁止出现 `submit_active_push` 字样**）

```python
# 5a 顶层 import（现 :36 为 campus 先例）
 from .domains.assistant.campus.campus import build_campus_source
+from .domains.emergency_info.capabilities.emergency_info import build_emergency_info_source

# 5b 装配门（现 :3684-3705 campus 三重门同段；正例逐字抄 campus）
     campus_service = None
     campus_source = build_campus_source(config)
     if (
         campus_source.enabled and campus_source.self_ids and campus_source.whitelist and campus_source.notify_qq
     ):
         ...
+    # 外部紧急信息聚合：三重来源门 enabled ∧ sources ∧ (群白名单 ∨ 私聊名单)，
+    # 任一空=整链不装配（绝不猜群、绝不猜人）；审核名单空=审核面关闭（ReviewGate 缺省拒绝）。
+    emergency_service = None
+    emergency_source = build_emergency_info_source(config)
+    if (
+        emergency_source.enabled
+        and emergency_source.sources
+        and (emergency_source.push_group_whitelist or emergency_source.push_user_ids)
+    ):
+        from .domains.emergency_info.capabilities.emergency_info import EmergencyInfoService
+        from .domains.emergency_info.sources.store import build_emergency_store
+
+        emergency_service = EmergencyInfoService(
+            store=build_emergency_store(str(config.bot_emergency_info_db_path)),
+            source=emergency_source,
+            gate=outbound_gate,          # 唯一投递闸：见 5b-2，缺它=整链不装配
+        )

# 5b-2 中央闸单实例（与发送队列同组装配；`build_outbound_gate` 不含被禁字样，安全）
+    from .domains.transport.sender.outbound_gate import build_outbound_gate
+
+    outbound_gate = build_outbound_gate(
+        config,
+        audit_logger=audit_logger,
+        settings_provider=lambda: build_outbound_gate_settings(runtime_view),      # ← 形参名以真身 :748-756 为准
+        quiet_settings_provider=lambda: build_quiet_hours_settings(runtime_view),
+    )

# 5c matcher 三件套 + 工厂薄壳（现 :6046/:6136/:8441/:4121 为 weather 正例）
+    async def _is_emergency_info_event(state: T_State, event: Event) -> bool:
+        return (
+            _cached_route_decision(state, event, config=config).kind
+            is RouteKind.EMERGENCY_INFO
+        )
+
+    emergency_info = on_message(rule=_is_emergency_info_event, priority=44, block=True)   # ← 与 RouteRule 同值双钉
+
+    def _build_emergency_info_with_backend(config_: Any, **_kwargs: Any) -> Any:
+        return build_emergency_info_capability(config_, render_backend=render_backend)
+
+    @emergency_info.handle()
+    async def _handle_emergency_info(bot: Bot, event: Event) -> None:
+        await _run_simple_capability(
+            bot, event, _build_emergency_info_with_backend, "bot.emergency_info", emergency_info
+        )

# 5d 轮询调度器（若要自动采集；cron 参数样板见 _register_digest_push_scheduler :3228）
+        if emergency_service is not None:
+            _register_emergency_info_scheduler(scheduler, config, emergency_service)
```

⚠ **三处高危**（本席独立复核，非素材原文）：
1. `build_outbound_gate` 的真身形参是 `settings_provider` / `quiet_settings_provider` / `audit_logger` / `clock` / `store` / `issue_sink`
   （`domains/transport/sender/outbound_gate.py:748-756`）。**B4a §7 L-3 与 §R2-4 L1 写的 `settings=` / `quiet_settings=` 不存在**
   ⇒ 装配期 `TypeError`，而 `_register_nonebot_handlers` 的失败会带走整个插件装载（铁律：改代码必须重启才生效 ⇒ 表现为「重启后 bot 起不来」）。
2. `outbound_gate` 与 `emergency_service` 的装配次序不能反：5b-2 必须在 5b 之前（`gate=outbound_gate` 引用在前）。
   本席实读：`send_queue = build_send_queue(config, audit_logger=audit_logger)` 在 `:3728`，campus 门块在 `:3684-3705`
   ⇒ 闸要插在 `:3728` 之后、紧急门要插在闸之后。**别照抄本席行号，按 `build_send_queue(` 与 `campus_service = None` 两个符号定位。**
3. 5b 的 `gate=None` 语义要显式定：若闸未装配（例如未来把 `build_outbound_gate` 挪进 `service_wiring` 主门后），
   紧急服务**必须整链不装配**而不是退化成裸 submit（否则违反 §5-钉死③且 G27 不红 ⇒ 无声旁路）。

## 4-面11 域内唯一投递触点（新建 `domains/emergency_info/service/push.py`，非九面之内但**是钉死③的落点**）

```python
"""紧急域一切主动投递的唯一出口。

结构约束（本席静态推演）：
- 本文件所在目录 `domains/emergency_info/` 以 `domains/emergency` 为前缀 ⇒ 通过
  `tests/test_outbound_gate.py:1177-1196` 的 startswith 白名单（意外通过，见风险 R-2）。
- 禁止在此文件之外、尤其在根 `__init__.py` 出现 `submit_active_push`（G26 全文本子串判定）。
"""
from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
    DEDUPE_FAMILY_DAILY,
    submit_active_push,
)

def deliver_emergency(send_queue: Any, gate: Any, item: EmergencyItem, target: EmergencyTarget, *, now: datetime) -> str:
    if item.level is None:
        return "skip_ungraded"                       # 未定级不冒充任何等级（D-1）
    request = build_emergency_send_request(item, target, priority=str(item.level.value), …)
    outcome = submit_active_push(send_queue, request, gate, now=now, dedupe_family=DEDUPE_FAMILY_DAILY)
    return outcome.verdict.action                     # allow | defer | skip
```

`SendRequest` 必填面（实读 `domains/core/contracts/runtime.py`，`class SendRequest(StrictBaseModel)` 起 :296 附近）：
`request_id / session_id / target_scope / target_id / capability_id / content / send_policy / priority /
max_messages / dedupe_key / cooldown_key / privacy_level / persona_profile_id`——
`dedupe_key` 与 `cooldown_key` 的空串会被 `field_validator` 直接拒（B4a/E3 双证），
故 `build_emergency_send_request` 必须**同时**给两键；键形规范唯一出处
`domains/emergency_info/service/dedupe.py:39 build_emergency_dedupe_key`（核验口 `:70 is_emergency_dedupe_key`）。

## 4-面6 `docs/route-matrix.md`（一行，**必须晚于 4-面5**）

```markdown
| `紧急信息`、`预警`、`地震`、`紧急信息 待审`、英文 `emergency`、拼音 `jinjixinxi/yujing` | emergency_info | 44 | `_is_emergency_info_event` -> `_handle_emergency_info` | bot.emergency_info（外部预警与政务应急聚合：采集→定级→去重→审核→经中央闸投递；三重门任一空=整链不装配） |
```

- 第 3 列（优先级）必须是**整数文本**且等于 RouteRule 的 44（G18）；第 4 列反引号里的两个名字
  必须已在 `__init__.py` 定义（G19 `test_route_matrix_matcher_names_exist_in_code`）。
- 第 2 列 `emergency_info` 同时满足 G20 的 `\b` 词边界覆盖门（`emergency_info` 与 `media_archive` 无子串纠缠）。

## 4-面7 配置键 + catalog + `.env.example`

```python
# config.py：锚点 = campus 族末行 `bot_campus_db_path: str = "data/campus.sqlite3"`（实读 :447）之后
+    # 外部紧急信息聚合（bot.emergency_info）：采集→定级→去重→审核→经中央闸多通道投递。
+    # 三重来源门任一空=整链不装配（绝不猜群/绝不猜人）；审核名单空=审核面关闭（缺省拒绝而非放行）。
+    # _enabled/_sources/名单为装配期快照（改当夜不生效，同台账 #3 口径）；_min_level/_poll_interval 建议热改。
+    bot_emergency_info_enabled: bool = False
+    bot_emergency_info_sources: list[str] = []
+    bot_emergency_info_poll_interval_seconds: int = 300
+    bot_emergency_info_min_level: str = "P2"
+    bot_emergency_info_push_group_whitelist: list[str] = []
+    bot_emergency_info_push_user_ids: list[str] = []
+    bot_emergency_info_reviewer_ids: list[str] = []
+    bot_emergency_info_keep_days: int = 90
+    bot_emergency_info_db_path: str = "data/emergency_info.sqlite3"
```

```python
 # path_fields（现 :1170 起，campus 条目在 :1228）：紧跟同族追加，否则 data/ 落源码树（铁律 6 / 台账 #1）
             "bot_campus_db_path",
+            "bot_emergency_info_db_path",

 # id 列表宽容装载 @field_validator（现 :1277 起，campus 两键在 :1295-1296）
         "bot_campus_self_ids",
         "bot_campus_group_whitelist",
+        "bot_emergency_info_sources",
+        "bot_emergency_info_push_group_whitelist",
+        "bot_emergency_info_push_user_ids",
+        "bot_emergency_info_reviewer_ids",
```

- 文档：`docs/config-catalog-full.md` 每键一行（表格首列写反引号形态 `` `BOT_EMERGENCY_INFO_ENABLED` `` 才会被
  `_catalog_registered_keys` 认出，实读该函数 `tests/test_doc_sync_gates.py:305-318`）⇒ 门 G21（`:329`）。
- `.env.example` 同名注释块（值留空或 `env:`；真实值只进 `.env`）。**无机器门拦 .env.example**（本席 grep
  `tests/` 只有 `test_control_plane_host_guard.py`/`test_tts.py`/`test_v21_s0_root_collect.py` 提到 env.example）
  ⇒ 属人审欠账，登记即可，别把它当门修。
- `min_level` 值域=`EmergencyLevel` 字面（`P0..P3`），非法值按缺省：**不得**在 config 校验器里造第二套等级枚举（D-3）。

## 4-面8 `docs/db-owners.md`（一行；该文件当前是脏态 `M`，动前必读最新态）

```markdown
| `data/emergency_info.sqlite3` | `BOT_EMERGENCY_INFO_DB_PATH` | `domains/emergency_info/sources/store.py`（`EmergencyStore` :97 / `build_emergency_store` :226 / 缺省常量 :38） | `CREATE TABLE`（唯一 `_SCHEMA`，含 `(source_id, external_id)` UNIQUE 与 `status` CHECK）；prune `keep_days=BOT_EMERGENCY_INFO_KEEP_DAYS` | 待审队列属活动数据：`/bot` 审核面可改状态，禁手工删库；清理先停进程（WAL 伴生 `-wal/-shm`） |
```
⇒ 无机器门读 db-owners.md（本席 grep 未在 tests 命中该文件的解析门；**若另有门则属未证实**）。

## 4-面9 生成物三连（顺序：catalog → auto-facts → hashes）

```
python scripts/command_catalog.py --write      # 或 BOT_AUTOSYNC=1 下由 dev.ps1 -Task test 代跑
python scripts/doc_sync.py --write             # 机器册：RouteKind 列表 / topics 数 / config 字段数
python tests/verify_hashes.py --write          # 只因 echo.py 在 TRACKED_FILES（tests/verify_hashes.py:56）而需要
COMMANDS.md / docs/README.md：只指链，禁写死「N 个模块/N 个别名」（G: test_documentation_consistency.py:414/:422）
```

## 4-面10 `tests/test_capability_registry.py`（第十面，逐处清单）

| 位置 | 现值（脏树 03:05） | 目标值 | 为什么 |
|---|---|---|---|
| `_SNAPSHOT_ROUTE_KINDS :56-71` | 34 对（末 `("CHAT","chat"), ("IGNORE","ignore")` 形态） | +`("EMERGENCY_INFO","emergency_info")`（同枚举位置） | G1 `:228` |
| `_SNAPSHOT_ROUTE_RULES :73-107` | 33 行 | +`("emergency_info","bot.emergency_info",44,"紧急信息",<reason 与 RouteRule 逐字>,("base_route:emergency_info",))` | G4 `:266` |
| `_SNAPSHOT_COMMAND_ROUTE_KINDS :109-119` | 29 员 | +`"EMERGENCY_INFO"` | G5 `:300` |
| `_SNAPSHOT_INTERFACE_MANIFEST :121-143` | 20 行 | **不动**（除非加 InterfaceDecl） | G: `:329` |
| `_SNAPSHOT_INTERNAL_NOTES :145-` | 5 条 | **不动**（⇒ decl 的 `note=` 必须留空） | G3 `:347/:356/:366` |
| `:226` | `== 34` | `== 35` | G1 |
| `:247` | `== 33` | `== 34` | G2 |
| `:301` | `== 29` | `== 30` | G5 |
| `:315` | `== 20` | 不动 | — |
| `:356` | `== 5` | 不动 | G3 |
| `:403` | `== 77` | `== 78` | G6 |
| `:430` | `== 37 and … == 40` | `== 37 and … == 41`（本域 admin_only=True ⇒ 只动 admin 那侧） | G7 |
| 文件头 docstring `:3-35` | 「四处离线静态解析器…」叙述 | 建议加一行「本波新增第 10 面登记说明」 | 人审可读性（无门） |

---

# 5. 三条必须钉死的实质内容

## 钉死① 两个 `priority` 不是同一个东西（brief 措辞需拆开，否则会把 P0 弄成双重含义）

| 字段 | 类型与真身 | 取值形态 | 后果 |
|---|---|---|---|
| `RouteRule.priority` / `RouteDecision.priority` | `int`（`domains/chat_reply/runtime/base_router.py` 的 `RouteRule` :187 / `RouteDecision` :141），`classify_message_route` 用 `sorted(ROUTE_RULES, key=lambda c: c.priority)` 判定（现 :734 附近，同值按书写序先到先得） | **裸整数 44** | 写成字符串 ⇒ `test_route_rules_data_columns_equal_registry` 逐字段红；写错值 ⇒ 判定序错 |
| 根 matcher `on_message(priority=…)` | NoneBot 参数（`__init__.py:6136` 正例 `priority=41`） | **与 RouteRule 同值的裸整数 44** | 不同值 ⇒ NoneBot 侧与中央判定序不一致；**仓内无此门**（E3 §3 欠账①，本席二次 grep 复确认零命中）⇒ 只能靠人肉 + §6 步骤 6 |
| `SendRequest.priority` | `str`（`domains/core/contracts/runtime.py`，`class SendRequest` 字段清单内 `priority: str`）——**这才是中央闸读 severity 的载体** | **`str(item.level.value)`**，即 `"P0".."P3"`（大写字面值） | 漏传/传 `"normal"` ⇒ 闸侧 `_severity_of`→`_is_urgent` 判非紧急 ⇒ **P0 预警在 00:00–06:00 被当非紧急顺延到 06:00 = 漏报**（B4a L-6 + B11 §6.2 同源，方向性后果唯一） |

⇒ **写单时把「同值双钉」与「`str(level.value)`」分开钉**：前者是路由判定序（int，两处同值），后者是投递载体（str，枚举字面）。
把等级塞进 `RouteRule.priority` 会同时打红 G18（`test_doc_sync_gates.py:211` 对文档列做 `int(prio_raw)`）与 G2；
把等级塞进 `audit_tags` / `content.risk_level` / 新建字段 = 造第二载体，B11 §6.2 明令禁止。
建议锁（域内测试）：`assert build_emergency_send_request(item_p0, …).priority == "P0"`。

## 钉死② 三重装配门（抄 campus 正例，任一空=整链不装配）

正例逐字（本席 03:02 实读，根 `__init__.py:3684-3705`）：

```python
    campus_service = None
    campus_source = build_campus_source(config)
    if (
        campus_source.enabled
        and campus_source.self_ids
        and campus_source.whitelist
        and campus_source.notify_qq
    ):
        ...CampusForwardService(store=CampusStore(str(config.bot_campus_db_path)), source=campus_source)
```
形态要点全部照搬：① 条件写成 `and` 链且**逐条来自装配期 frozen 快照对象**（`build_*_source(config)`，campus 真身
`domains/assistant/campus/campus.py:54-67`），② 门不成立 ⇒ 服务保持 `None` ⇒ matcher/调度器整块不注册
（campus 消费点 `:5022 if campus_service is not None:`），③ 白名单支持 `"*"` 通配由 `matches_*` 判定
（campus `:70-78`），④ **绝不猜群/猜人**：`push_group_whitelist` 与 `push_user_ids` 全空 ⇒ 关闭，不是「全开」。
本域差异只在第四条件：`whitelist or user_ids` 二者其一非空即可（私聊投递与群投递是两条独立腿），
但**审核名单 `reviewer_ids` 不参与装配门**——它空 ⇒ `ReviewGate.authorizer=None` ⇒ 过审一律拒
（`domains/emergency_info/service/review.py` 的 `approve_is_closed_until_an_authorizer_is_injected` 用例已锁死该方向，
⇒ 装配链可跑、报料可入库、但永远投不出去，属**安全的缺省态**，须在 catalog 里写明白）。

## 钉死③ 紧急域主动投递只经 `submit_active_push`，禁直调 `send_queue.submit`

1. **唯一入口**：`domains/transport/sender/outbound_gate.py:639 submit_active_push(send_queue, send_request, gate, *, now=None, dedupe_family="once")`
   （常量 `DEDUPE_FAMILY_ONCE="once"` :92 / `DEDUPE_FAMILY_DAILY="daily"` :93）。按日重投族**必须**显式传 `dedupe_family="daily"`
   ⇒ 否则闸放过缺 `date_key` 的四段键 ⇒ 跨日不再重投（**漏发**，非重发，B4a-R2 §R2-3 会错的③）。
2. **物理落点只能在 `domains/emergency_info/**`**（G26 禁根文件出现该字样；G27 白名单只放 `domains/transport` 与 `domains/emergency`）。
3. **现存结构锁只锁了一半**：`tests/test_outbound_gate.py:1177-1196` 锁「谁能 import 闸」，`:1160-1176` 锁「根 __init__ 不许用闸」。
   **没有任何门禁止 `domains/emergency_info/` 内部直接 `send_queue.submit(request)`**——绕过闸不红任何门。
   ⇒ 开工席必须在域内测试补两条锁（新行为先 RED 后 GREEN，B 波纪律 §2.2）：

```python
# 建议新增于 tests/test_emergency_info_core.py（本席只给原文，不 apply）
def test_emergency_domain_has_zero_direct_queue_submit() -> None:
    """唯一投递触点=中央闸：域内出现裸 `*queue*.submit(...)` 即红（与 T6 同向、互补）。"""
    offenders: list[str] = []
    for path in sorted(EMERGENCY_DOMAIN.rglob("*.py")):
        for lineno in _direct_submit_calls(path):      # 语义同 tests/test_outbound_gate.py:1145 的 AST 判定
            offenders.append(f"{path.name}:{lineno}")
    assert offenders == [], f"紧急域绕过中央闸直调队列：{offenders}"


def test_emergency_domain_push_gate_touchpoint_exists() -> None:
    """反证自锁：上一条在「域内零投递」时恒真 ⇒ 必须同时断言触点确实存在，防门退化成摆设。"""
    hits = [p.name for p in sorted(EMERGENCY_DOMAIN.rglob("*.py"))
            if "submit_active_push" in p.read_text(encoding="utf-8")]
    assert hits == ["push.py"], f"紧急域投递触点应恰有一处（实读：{hits}）"
```
（`_direct_submit_calls` 现成实现在 `tests/test_outbound_gate.py:1145-1157`，两行 AST 判定可直接复制，
不必 import 兄弟测试模块。）

4. 回执消化口径不得自造：`outcome.receipt.operational_issue` 非空即交既有告警面
   （同 `worker.py:337` 的 `_notify_operational_issue_safely` 先例；`AdminAlertSuppression` 自带 300s 抑制）。
   **`issue_sink` 未接前，degraded/storm 只落 `logger.warning` ⇒ 不得宣称「已告警」**（B4a L-3 原话，仍成立）。

---

# 6. M4 开工前置条件与执行序

## 6.1 冷热实况（本席 03:16 二次实测，覆盖 brief 02:56 表）

```
date +%H:%M:%S = 03:16:16        HEAD = 14e6480（02:58 时是 0ee9115 ⇒ 18 分钟内动了 ≥1 笔）
git status --porcelain | wc -l = 953（02:58 为 977）
--- 九面脏态（只列被点名的面）---
 M docs/auto-facts.md
 M docs/db-owners.md
 M plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py
 M tests/render_hashes.json
 M tests/test_capability_registry.py
--- mtime ---
20:01:58(昨) echo.py     02:01:16 base_router.py     02:06:03 docs/route-matrix.md（现为干净态）
02:10:50 capability_registry.py     02:50:05 根 __init__.py     02:50:28 config.py
```

**结论（与 brief 表的差异要记账）**：brief 标为「热」的 `docs/route-matrix.md` 在 03:16 已是**干净态**（他席已提交），
而真正卡住的不是 mtime 而是**两枚未提交的注册尾部**：`capability_registry.py` + `tests/test_capability_registry.py`（TTS/F3/CAMPUS-FIX-9 面）。
⇒ 本席把「冷面判据」升级为「**脏面判据优先于 mtime 判据**」。

## 6.2 开工前置条件（全部为**硬门**，任一不满足 ⇒ 不开工）

| # | 条件 | 判据（只读命令） |
|---|---|---|
| P-1 | 在飞的注册尾部已落地 | `git status --porcelain -- plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py tests/test_capability_registry.py docs/auto-facts.md tests/render_hashes.json` **无输出**。（否则：两个席位同时改同一批快照字面，必撞车，且快照现值不可信） |
| P-2 | 四个热面同时安静 | `ls -l --time-style=+%H:%M:%S` 根 `__init__.py` / `config.py` / `echo.py` / `base_router.py` 的 mtime 距今 **>15 分钟**，且 `git status --porcelain -- <这四个>` 无输出 |
| P-3 | 脏树总量回落且无本域新冲突 | `git status --porcelain \| wc -l` 相对开工首测（953@03:16）**不再上升**；`git status --porcelain -- plugins/bot_unified_runtime/domains/emergency_info/` 与开工首测逐行一致（该目录当前 untracked ⇒ 无 git 基线，还原不可自证） |
| P-4 | 基线红名单已记账 | 见 §6.3 步骤 0 的输出必须**原样写进开工席 report 首节**，否则后续任何红都不可归因 |
| P-5 | 写权清单齐备 | 主会话授权必须覆盖：`config.py`、`base_router.py`、`capability_registry.py`、`echo.py`、根 `__init__.py`、`domains/emergency_info/**`、`tests/test_capability_registry.py`、`tests/test_emergency_info_core.py`、`docs/route-matrix.md`、`docs/config-catalog-full.md`、`docs/db-owners.md`、`docs/command-catalog.md`、`docs/auto-facts.md`、`tests/render_hashes.json`、`.env.example`。**少一件 = 该面必红**（第十面缺权尤其致命，见 §2.4） |
| P-6 | 四个裁决点已定（否则开工即返工） | ①`priority=44` 还是 `43`（43 与 MEDIA_ARCHIVE 同值，同值=书写序先到先得）；②`admin_only=True`（本席建议，投递面上线后再公开 ⇒ 届时才动 `_PUBLIC_HELP_TOPICS` 与 `:430` 的 37）；③命名统一 `emergency_info`（禁 `emergency`/`emergency_info` 两名并存，B1R3 §6 已自陈此险）；④层名 `sources/` 还是 `data/`（B1R3 §3(f)4 提请；改目录名会**同时**影响 G27 前缀白名单，见 R-2） |
| P-7 | 禁自动部署 | 本席与开工席一律不重启 bot、不 commit、不 push（铁律 4/7）。注册完成后的生效口径永远写「代码+测试完成，重启生效」 |

## 6.3 开工席一页操作单（11 步，含每步验证与预期）

> 通用卫生（每步实跑都带）：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <面> -p no:cacheprovider --basetemp="$TEMP/e-wave-WIRE-<步号>" -q`

| 步 | 动作 | 立刻跑什么 | 预期 |
|---|---|---|---|
| 0 | **基线记账**：跑门族 `tests/test_capability_registry.py tests/test_documentation_consistency.py tests/test_doc_sync_gates.py tests/test_trigger_spec.py tests/test_trigger_bidirectional_gate.py tests/test_help_deep_teaching_n2re.py tests/test_help_entries_coverage.py tests/test_cross_validation_gates.py tests/test_outbound_gate.py` | 同上 | 记「开工前已红 N 条」原样入 report（§2.4 已证 HEAD 上有红）；此后只比自己多出来的红 |
| 1 | config.py 九键 + `path_fields` + id 列表装载 | `pytest tests/test_doc_sync_gates.py -q` | 红 1 条：`test_config_catalog_covers_config_fields`（G21）——**属预期**，第 8 步消 |
| 2 | 新建 `domains/emergency_info/capabilities/emergency_info.py`（先写 RED 用例：`is_emergency_info_command('紧急信息') is True`、`'emergencyxxx'` 不命中） | 该文件族 + `pytest tests/test_emergency_info_core.py -q` | 先 RED 后 GREEN；词边界用例锁 G23 |
| 3 | base_router 三处（枚举 + 闭包 + RouteRule）+ import | `pytest tests/test_trigger_spec.py -q` | G22 需已满足（闭包调 `is_*`）；G27/G25 会红（词表未同源）⇒ 第 5 步消 |
| 4 | registry 三处（3a/3b/3c） | `pytest tests/test_capability_registry.py -q` | **必红一批**（G1/G2/G4/G5/G6/G7 + 快照）⇒ 属预期，第 6 步消 |
| 5 | echo 三处（4a/4b/4d，`_PUBLIC_HELP_TOPICS` 不动） | `pytest tests/test_help_deep_teaching_n2re.py tests/test_help_entries_coverage.py tests/test_documentation_consistency.py -q` | 消 G9–G12/G28；若 G14:341 红 ⇒ 说明第 1 步键名拼错或未落 |
| 6 | **第十面**：`tests/test_capability_registry.py` 五处快照 + 四处写死数（逐字见 §4-面10 表） | 同第 4 步 | 归零；`== 35 / 34 / 30 / 78 / 41` |
| 7 | 根 `__init__.py` 四处（5a/5b/5c，闸在 :3728 之后、紧急门在闸之后） | `pytest tests/test_outbound_gate.py -q`（G26/G27）+ 导入自检 | T6 两条仍绿（**根文件全文不得出现 `submit_active_push`**）；若红 = 第 7 步越界写了投递，回退到域内 |
| 8 | 文档三件：`docs/route-matrix.md` 行（匹配器列用第 7 步真名）+ `docs/config-catalog-full.md` 九行 + `.env.example` 块 + `docs/db-owners.md` 行 | `pytest tests/test_doc_sync_gates.py tests/test_documentation_consistency.py -q` | 消 G18/G19/G20/G21 |
| 9 | 生成物三连 | `python scripts/command_catalog.py --write`、`python scripts/doc_sync.py --write`、`python tests/verify_hashes.py --write`，再 `pytest tests/test_cross_validation_gates.py tests/test_documentation_consistency.py::test_catalog_document_matches_registry -q` | 消 G16/G17；机器册应见 RouteKind 35、topics 78、config 字段数 +9 |
| 10 | 域内投递触点 `domains/emergency_info/service/push.py` + 两条结构锁（§5-钉死③ 原文，先 RED 后 GREEN） | `pytest tests/test_emergency_info_core.py tests/test_outbound_gate.py -q` | 锁生效：把 `submit_active_push` 挪进根文件 ⇒ T6 红；域内裸 submit ⇒ 新锁红。两把门各自**注毒复验一次**再还原（B1R3 §5.2 口径） |
| 11 | 收尾：`dev.ps1` 四门禁（`test`/`lint`/`typecheck`/`runtime-layout`）**仅在主会话确认无在飞席时**跑；否则只跑 scoped 门族并如实标注「未跑全量」 | 见 `AGENTS.md` 第五部分 | 全量红需逐条归属（B4a/B1R3 先例：不把他席中间态记到本席账） |

## 6.4 回滚（写清，**本次不执行**）

1. **受跟踪面**（config/base_router/registry/echo/根 __init__/docs/tests）：
   `git diff -- <文件> > %TEMP%/wire-<文件短名>.patch` 先存档，再 `git checkout -- <文件>` 逐文件还原。
   ⚠ **红线**：只有在「该文件本次仅本席动过」时才允许 checkout——多会话共享树下这会连带吃掉他席未提交改动。
   有他席在飞时改用**反向打补丁**：`git apply -R %TEMP%/wire-<名>.patch`（先 `git apply -R --check` 试探）。
   禁 `git checkout -- .`、`git restore .`、`git stash`、`git clean`（铁律 4 + 共享树）。
2. **新增未跟踪件**（`domains/emergency_info/capabilities/`、`domains/emergency_info/service/push.py`、新测试函数）：**无 git 基线 ⇒ 还原不可自证**。
   规程=先整目录复制到 `%TEMP%/wire-emergency-<ts>/`，再用 venv python 删（本机 Git Bash 无 `rm`/`mv`）：
   `"../ChatBot_Runtime/venv/Scripts/python.exe" -c "import shutil;shutil.rmtree('<路径>')"`。
3. **生成物**（command-catalog / auto-facts / render_hashes）：属可再生件，回滚=还原源面后**重跑三条 `--write`**，
   不要手工改生成物（手工改必在下一次 `--check` 红）。
4. **回滚后的自证**：重跑 §6.3 步骤 0 的门族，红名单必须回到开工首测那一份（逐条比对，不比对「大概差不多」）。

---

# 7. 风险登记与诚实缺口

## 7.1 会炸的

- **R-1 根 matcher 单独接线不红任何门**（静默无效面）。E3 §3 欠账① 与 grep 复确认：
  `grep -rn "priority" tests/test_doc_sync_gates.py tests/test_documentation_consistency.py` 中「NoneBot matcher ↔ RouteRule」比对 **零命中**
  ⇒ RouteRule.priority 与 `on_message(priority=…)` 双钉**无机器门**。若开工席只改根文件而忘改 base_router，
  全部常驻门照样绿，而路由行为按 44 之外的旧序走 ⇒ 唯一防线是 §6.3 步骤 6 的人工核 + 建议新增锁（见 7.4）。
- **R-2 闸引用白名单是 `startswith` 前缀形**（`tests/test_outbound_gate.py:1177-1196`，`allowed_prefixes` 含 `domains/emergency`）。
  本域 `domains/emergency_info/` 恰好落在前缀内 ⇒ **现下绿，属意外通过**：
  ①任何 `domains/emergency*` 命名的目录都能无声引用闸（白名单值形=前缀内皆自由）；
  ②若评审把判定收紧为整段匹配（`path.parent.name == "emergency"` 之类），或本域按 B11 §8.2 裁决点①改名 ⇒ 立刻红。
  ⇒ 建议裁决：把白名单显式改为 `domains/emergency_info`（真身名），与本域一次定名同批做。
- **R-3 双 `priority` 混用**（§5-钉死①）。漏传 `str(item.level.value)` 的失败方向是**漏报**，且**离线测试全绿**
  （缺省 `bot_outbound_gate_enabled=False` ⇒ 走裸 submit，零判定）。⇒ 唯一可行的防线是「P0 出网时 priority == "P0"」域内锁。
- **R-4 help 落点门含子串放行 ⇒ 假绿**（`tests/test_documentation_consistency.py:184-217` 的落点三选一里
  有「capability 核心词出现在扫描文件文本中」）。base_router 里只要写了 `emergency_info_match`，
  即使根 matcher 不存在，该门也可能放行 ⇒ 不能拿「G15 绿」当「已接线」的证据。

## 7.2 会错的

- 把「代码在树」当「生产在跑」：本域与闸都是**缺省关闭 + 未重启**，§6.3 全部为离线证据。
- cron 时刻/名单是装配期快照（台账 #3 同款），`bot_emergency_info_*` 的 `_enabled/_sources/名单` 热改当夜不生效 ⇒ 键注释必须写明。
- 分类表门归因错（G8 单向 / G9 才是双向）⇒ 若照 B1R3 只补 `_HELP_CATEGORIES` 而没照 G9 的对称差去核对，
  会漏检「分类里有、代码里删了」的反向漂移（`categorized == set(_ALL_TOPICS)` 双向才拦得住）。
- `_HELP_ALIAS_MAP` 是派生面（`echo.py:3202-3211`）：改了 META 触发词就等于改别名面 ⇒ 别名撞键在 G28 红，不要手工去改映射。

## 7.3 欠账的

- `tests/test_capability_registry.py` 文件头叙述仍写「四处离线静态解析器」与「18 行接口清单」，实值已是 20 行/34 员
  ⇒ 第十面的 docstring 漂移无人管（无门）。本席建议开工席在第 6 步顺手同步叙述，但不列为必做。
- `.env.example` 无机器门（§4-面7 已证）⇒ 属人审面。
- `docs/db-owners.md` 无解析门（本席 grep tests 未命中该文件的对账门）⇒ 登记靠人审。

## 7.4 建议新增的三把门（属 `tests/**`，本席**未实施**，交裁决）

1. 双钉一致性：从 `__init__.py` AST 提 `on_message(rule=..., priority=N)` 的 N，与该 rule 在 `ROUTE_RULES` 的 priority 比对
   （治 R-1；注意被动旁路族 `block=False` 的 3–13 小值不适用，需按 `block=True` 过滤）。
2. severity 载体：`build_emergency_send_request(...)` 的 `priority` 字面必须是 `"P0".."P3"`（治 R-3）。
3. 白名单整段化：把 `domains/emergency` 改成 `domains/emergency_info` + 一条负样本（`domains/emergencyXXX` 不得放行）（治 R-2）。

## 7.5 本席未证实（诚实缺口）

1. 垫片 `plugins/bot_unified_runtime/capabilities/emergency_info.py` 是否会自动出现 ⇒ §4-面1+2 的 import 形态二选一未定；
   开工席实跑 `python -c "import plugins.bot_unified_runtime.capabilities.emergency_info"` 判定。
2. 全量 `dev.ps1 -Task test` 未跑（只读席 + 脏树多席在飞，全量红不可归因）⇒ 本文所有「会红」均为**读断言原文 + 静态推演**，
   无一条来自实跑注毒（B1R3 §5.2 那种变异检验本席无写权做）。
3. `EmergencyTarget` / `build_emergency_send_request` 尚未存在（全树 grep 零命中）⇒ §4-面11 的签名是**规约草案**，非磁盘事实。
4. 未核 `domains/chat_reply/runtime/settings.py` 的 `SETTABLE_KEYS` 条目形态（B4a L-4 同一缺口，本席只登记）；
   `test_help_config_keys_resolve` 放行 `key in settable` 这条支路因此未逐条验证。
5. WebUI/控制面对新域的可见性要求（`docs/design/control-plane-registry.md` 面）未核 ⇒ 若控制面 feature_catalog 需要登记
   `bot.emergency_info`，那是**第十一面**，本席未发现门，属未证实。
6. `docs/route-matrix.md` 的其他小节（§1 链路叙述、§「覆盖门」之外的说明段）是否需同步，只核了 §2 表门。

## 7.6 对既有素材/口径的更正（逐条，带证据）

| 素材原文 | 本席判定 | 证据 |
|---|---|---|
| E3 素材5「新增一个 topic 的同步面 ①②③（echo 两处 + registry 一处）」 | **不全**：echo 内实为四处（含 `_PUBLIC_HELP_TOPICS:268`、`_HELP_CATEGORIES:284`），且未列第十面 | `echo.py:268/:284` 反读 + `tests/test_capability_registry.py:428/:430` 与 `tests/test_help_deep_teaching_n2re.py:77` |
| B1R3 §3(e)「echo.py 帮助注册实为**四处**，不是 E3 说的三处」 | **对**（四处成立：ENTRIES/META/PUBLIC/CATEGORIES），但**门归因部分错**：`test_capability_registry.py:433-436` 是单向门，拦不住「新 topic 未进分类」 | `tests/test_capability_registry.py:433-436`（`topics - declared` 单侧差集）vs `tests/test_help_deep_teaching_n2re.py:77-81`（对称差） |
| brief 括注「既有素材 E3 只列了两处」 | **不准确**：E3 素材5 列了三处（第③处在 registry 不在 echo）⇒ 正确对照口径是 B1R3 的「四处 vs 三处」 | `E3-report.md` 素材5 ①②③ 原文 |
| B11 §7.3 第 5 行「分类门=`test_capability_registry.py:433-436`」 | 同上错归因 | 同 G8/G9 |
| B11 §7.3 末「四要素目前机器不拦，建议把紧急信息加入 `_TONE4_TOPICS`」 | **不成立**：`tests/test_help_deep_teaching_n2re.py:53-60` 已对**全体** entry 的 detail 断言含四要素字。加入 `_TONE4_TOPICS` 只会额外启用「逐行四要素」细门（`test_documentation_consistency.py:465`），可选非必需 | 两文件原文 |
| B4a §7 L-3 / §R2-4 L1「装配接线写在根 `__init__.py`，并示范 `outcome = submit_active_push(...)`」 | **照抄必打红 T6**；且示例形参名 `settings=`/`quiet_settings=` 不存在 ⇒ 装配期 TypeError | `tests/test_outbound_gate.py:1164` 全文本子串；`outbound_gate.py:748-756` 真身形参 |
| B4a L-6 / B11 §6.2「`priority=str(item.level.value)`」 | **成立且是本次最高价值约束**（R-3） | 闸 `_severity_of`→`_is_urgent`（B11 引 `:248/:252`，本席按符号复核在闸内） |
| E3 §4「priority 建议 43（与 MEDIA_ARCHIVE 同档）」 | 可用但有同值先到先得语义 ⇒ 本席建议 **44** 并入裁决点 P-6① | `base_router.py:598`（MEDIA_ARCHIVE=43）、`:601-604`（45/46/50 已被占） |

## 7.7 本席复跑证据（全部只读；禁改面零触碰、零 git 写、零 commit、零子代理）

| # | 命令 | 输出摘要 |
|---|---|---|
| 1 | `date` / `git log --oneline -3` | `Sun Sep 20 02:57:37 2026`；`0ee9115 / 902d955 / 0487156` |
| 2 | `find plugins/bot_unified_runtime/domains/emergency_info -type f \| sort` | 11 件，**无 capabilities/** |
| 3 | `grep -rn "emergency_info" __init__.py config.py domains/chat_reply/ docs/route-matrix.md` | **空输出**（=生产零引用） |
| 4 | `grep -rn "is_emergency_command\|build_emergency_info_capability\|build_emergency_send_request\|fanout_emergency" --include=*.py .` | **空输出** |
| 5 | `grep -c "RouteCapabilityDecl("` / `"HelpTopicDecl("`（registry） | **34** / **77**（InterfaceEntry=0 ⇒ 该表元素名是 `InterfaceDecl`） |
| 6 | `grep -n "^_PUBLIC_HELP_TOPICS\|^_HELP_CATEGORIES\|^_HELP_ENTRIES\|^_HELP_ENTRY_META" echo.py` | `268 / 284 / 448 / 2455`（四处坐标实证） |
| 7 | `grep -n "^def test_" tests/test_capability_registry.py` + sed 逐条读断言 | 17 把门，写死数在 `:226/:247/:301/:315/:356/:403/:430` |
| 8 | `grep -n "_HELP_CATEGORIES" tests/*.py` | 命中 `test_help_deep_teaching_n2re.py:77`、`test_help_entries_coverage.py:6` ⇒ 反查 G9/G30 |
| 9 | `git diff --stat -- <五面>` + `git diff -U0 -- tests/test_capability_registry.py` | TTS 批注册尾部原文（§2.4 逐字引用） |
| 10 | `git show HEAD:…/base_router.py \| grep -c "TTS\|tts"` = **9**；`git show HEAD:tests/test_capability_registry.py \| grep "== 33\|== 32\|== 28\|== 75\|== 36"` 全在 | **HEAD 基线红**实证（开工席必记） |
| 11 | `sed -n '1160,1200p' tests/test_outbound_gate.py` | G26/G27 断言原文 |
| 12 | `sed -n '748,775p' domains/transport/sender/outbound_gate.py` | `build_outbound_gate` 真身形参（证伪 B4a 示例） |
| 13 | 二次冷热实测（03:16:16） | HEAD=`14e6480`、脏 953 行、脏面 5 件（§6.1） |

**生效边界**：本文与本报告是**文档产出**，不改生产行为；紧急域在本席收席时点仍为「零注册、零接线、生产不可达」。





