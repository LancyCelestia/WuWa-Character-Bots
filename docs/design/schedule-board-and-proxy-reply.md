# 日程记录与智能代答（第 20 项）设计规格（2026-09-26，S-SCHEDULE-20 席）

> 状态：**§A 规格 + §B 记录腿 + §C 代答腿已实现并离线测试**；生产生效需重启。
> 本文件是设计唯一权威；实现细节以代码与测试为准，叙述文档不写过期计数（AGENTS 规则 10）。

## 0. 三条硬边界（用户原话直译，全部写进代码注释与测试）

1. **信息来源只能是「她亲口对 bot 说了什么」**——日程条目只能由会话内容（文本命令、
   自然语言、她粘贴/发送的课表文本或图片）产生。本能力**不做任何本机监控**：
   不读设备、不读摄像头、不读定位、不读日历软件、不扫文件系统找"她的行踪"。
   执法：本能力全部代码面的取数入口只有三类——入站消息、日程库内条目、
   显式注入的 provider（识图，由她发消息触发）；无任何系统采集 import
   （`tests/test_schedule_board.py::test_no_host_monitoring_imports` AST 锁）。
2. **隐私判定发生在出站前，不靠模型自觉**——代答正文由确定性代码从条目投影
   （字段白名单 + 分级词表），**从不把她的原始条目（尤其隐私条目）交给 LLM 生成**；
   出站文本再统一过 `domains/render/plain_text.py::redact_local_secrets`。
   执法：代答路径零模型调用（AST 锁）；投影函数逐字段白名单（注毒锁）。
3. **缺省最保守**——`BOT_SCHEDULE_ENABLED` 关（沿用既有键，缺省 False）；
   新登两枚键 `BOT_SCHEDULE_STATUS_REPLY_ENABLED` / `BOT_SCHEDULE_NATURAL_CAPTURE_ENABLED`
   缺省 False；条目可见性缺省**隐私**。三道闸任一关着 = 对应腿整链路零行为。

## 1. 数据模型（复用 S11 V2.1 引擎，禁第二真身）

`domains/schedule/` 下已有 V2.1 日程引擎全家（`service/schedule_dag.py` 模型、
`service/schedule_service.py` 门面、`service/schedule_store.py` SQLite、
`service/schedule_rrule.py` 展开、`llm_draft.py`、`timetable.py`、`delivery.py`），
配置键族 `bot_schedule_*` 七枚已在册（`config.py`），库路径
`bot_schedule_db_path = data/schedules_v21.sqlite3`（已进 `path_fields` 重映射）。
**本能力不新建表、不新建库、不新建第二套日程模型**，映射如下：

| 概念（她的语言） | 引擎真身 |
|---|---|
| 一张日程表（她或任何用户的） | 一个 plan：`plan_id = "board-<owner_user_id>"`，`state="active"`，`timezone=config.bot_timezone` |
| 一条日程 | 一个 `TaskTemplate`（fixed_time，title=活动，duration_minutes）+ 一条规则 `RecurrenceRule`（once / weekly_by_day / teaching_week） |
| 什么时候 | 规则 `start_date + local_time`（+ `weekdays`/`week_parity` 重复语义）；具体实例 = 物化的 `Occurrence`（UTC 存、展示换算配置时区） |
| 公开还是隐私 | task/occurrence 的 `tags` 含 **`vis:public`** = 公开；**无该标签 = 隐私（fail-closed）**。`schedule_rrule.expand_occurrences` 把 task.tags 原样带到 occurrence（已核实），改可见性时同步重打**已在库的未来 pending 实例**（新增 store 方法 `retag_future_occurrences`，见 §4） |
| 来源消息 id | `TaskTemplate.tags` 另载 `src:<message_id>`（可缺省）；纯溯源用，永不进代答投影 |
| 状态监测（睡了/醒了/吃饭） | 只可能是她**说出来**的日程条目（分类见 §5 敏感档），绝无自动探测 |

条目编号（"删 3"的 3）= 「日程列表」展示序（按开始时刻升序、同刻按 rule_id）中的
1 起始序号，落到 `(plan_id, rule_id, task_id, occurrence_id)` 四元组；编号是**会话内
易变引用**，每次操作前重新列算，绝不持久化编号。

## 2. 解析入口（三条，全部复用真身，禁第二解析器）

### 2.1 自然语言（确定性半边，本波主交付）
- 时间点解析**唯一复用** `domains/schedule/store/reminders.py` 的编译正则与级联
  （相对分钟/小时 → 绝对"X月Y日Z点" → 时段词），本波把 `parse_reminder_intent`
  的级联体抽为共享私有函数 `_first_time_target(raw, current)`，新增公开口
  `parse_time_target()` / `iter_time_phrases()`（复用同一批 `re.Pattern` 常量做
  span 剥离）；`parse_reminder_intent` 行为**逐字节不变**（既有提醒全家桶测试锁死）。
- 范围「8点到9点半」：同一 `_ABS_TIME_RE.finditer` 取第二个时刻 → duration。
- 重复语义「每周三/单周/双周」：词面判定 → weekly_by_day / teaching_week 规则；
  学期锚缺失时单双周**拒绝入库并回问**（引擎禁猜哲学与 llm_draft 同口径）。
- 宽口径自然捕捉（她说"我要干什么"没带"日程"二字）：受
  `BOT_SCHEDULE_NATURAL_CAPTURE_ENABLED` 缺省关控制；开=仅当
  「时间表达 + 第一人称活动词（有课/要去/得去/要上…）+ 短句 ≤48 字 + 非疑问 +
  无提醒信号词」全成立才建条目（缺省隐私）；关=只认 §2.1 显式命令与 §2.2 文本导入。
- LLM 草稿链（`llm_draft.py`，`bot_schedule_llm_draft_enabled`）本波**不接**：
  它是 V2.1 合同「草稿→人确认」多轮流程，需要独立的会话态设计，见 §8。

### 2.2 文本课表/计划导入（本波实现）
「日程 导入 <多行文本>」——逐行确定性解析：
`周X 8:00-9:40 高数 [地点] [单|双]`（节次/全角冒号/破折号宽容）。
每行 → 一条 weekly_by_day（带 单/双 → teaching_week，缺学期锚整批回问不落库）。
她直接粘贴课程表文字即得日程表；行内地点存 task 标题外**不**进投影（§5）。

### 2.3 图片课表识别（本波交付接线，生效依赖视觉配置）
消息含图片段 + 「课表」触发 → 复用 `timetable.py`：
`build_timetable_provider(config)`（识图 registry 真身惰性 import，媒体域零改动）→
`recognize_timetable()` → 需要澄清（缺学期起点/节次表）就**只发问不落库**（无状态、
绝不猜）；一次成型（时间齐全）→ `timetable_draft_to_plan_payload()` 的**去重合并**
语义按 §4 落库为隐私条目（导入不等于公开——公开是她对外的单独决定，「日程 公开 N」）。
图片字节只交给视觉 provider，不落任何第三方。

### 文件（PDF/表格）摄取 —— 本波不做，见 §8（根摄取面与容器读取口的路由属主代理协调面）。

## 3. 路由与装配（REMINDER 车道复用，notes 同型先例）

- **不新增 RouteKind**。判据链：`base_router.reminder_match → capabilities/
  reminder.is_reminder_command(text, config)`——本波在其后并入
  `schedule_board.is_schedule_command(text, config)`（记录/管理面，受
  `bot_schedule_enabled`）与 `schedule_board.is_status_question(text, config)`
  （代答面，受 `bot_schedule_enabled ∧ status_reply_enabled`）。
  理由（对照本仓头号假绿形态「代码有但生产不跑」）：新 RouteKind 的 NoneBot
  matcher 只能落在根 `__init__.py`（本席禁改），未落根前**消息会被路由判走而
  无人处理=静默黑洞**（#45 三腿教义）；REMINDER 车道已有中央信封
  （`orchestrated_command`，缺口账在册），重启即全链生效，零根改动。
  升级为独立 kind 的完整清单（Keystone 四处 + FACETS + 台账 + 根三件套）写在
  席位报告 §F，作为可选后续，不是本能力生效的前置。
- 能力分发：`build_reminder_capability` 内**笔记面之前**加日程分支（词表零交集，
  顺序仅为可读性）；`CapabilityResult.capability_id` 沿用 `bot.reminder`
  （与 notes 同一 id 归属旧账，manifest FACETS 注释如实点名）。
- FACETS（`domains/core/capability_manifest.py` bot.reminder 行）：`config_keys`
  并为本席新增读点的键（配置键唯一真身在此）；`implementation_line` 因
  `build_reminder_capability` 行号随 import 下移而**现算刷新**（一处变更处处跟随）。
- 帮助主题「日程」四处同步：echo `_PUBLIC_HELP_TOPICS`、`_HELP_CATEGORIES`（子功能）、
  `_HELP_ENTRIES`（topic/aliases/index/title_line/lines/detail）、`_HELP_ENTRY_META`
  （capability=bot.reminder、triggers、config_vars、tests 指真实测试件）+
  `capability_registry.HELP_TOPIC_DECLARATIONS` 一行 + 板卡认领
  （board_taxonomy B07 新节点 `schedule-board`，`dev.ps1 -Task sync` 重算生成页）。
- 投递口径：代答是**会话内正常回复**（走 pipeline 回复面），不是主动投递，
  不经 `submit_active_push`（那是无入站消息触发的主动推送的唯一出口；本面每条
  都由提问消息直接触发，在请求-回复同一事务里）。

## 4. 存储、迁移与清理

- 复用 S11 `ScheduleStore`（WAL、busy_timeout、BEGIN IMMEDIATE），**schema 零变更**
  ⇒ 无 ALTER-if-missing（家规适用于加列，本波不加列）。新子类
  `ScheduleBoardStore(ScheduleStore)`（`service/board_store.py`）只**加查询**：
  `get_plan_row_by_owner(owner)`、`list_board_items(owner, from_epoch, to_epoch)`
  （plans⋈occurrences，展开未物化规则→由调用方先 expand）、`retag_future_occurrences(...)`、
  `purge_terminal(before_epoch, limit)`。
- 写路径全部经 `ScheduleService`（submit_plan 乐观 revision、expand_occurrences
  幂等物化、cancel_occurrence 租约线性化、supersede_rule 改期退役）——**不绕过门面直写**。
- 限额：单表条目 = 引擎 `DEFAULT_MAX_TASKS`（100，DAG 校验既有闸）；导入单次行数 ≤ 60；
  活动标题 ≤ 60 字（截断并如实标注）。
- 清理（过期日程怎么 prune）：任何写操作顺带
  `purge_terminal(before_epoch = now - 90d)`（终态 done/cancelled/superseded/expired/
  digest/skipped 的物理删除，限量 500/次，失败静默只记日志——清理绝不阻塞记录）。
  模块常量 `RETENTION_DAYS=90`（不新加配置键：这是存储卫生不是策略面）。
- 到点督促**不在本波范围**（提醒域既有；`delivery.py` 引擎投递腿仍按 V2.1 原样
  未接线，属她裁定的另一件事，见 §8）。

## 5. 代答分级策略（★ 独立成节，给她过目的那张表）

### 5.1 谁在问（判据唯一来源：入站消息自带的 `actor_roles`，零新名单）

| 档位 | 判定 | 能拿到什么 |
|---|---|---|
| **超管本人（=条目主人 owner）** | `sender_id == owner` 且 roles 含 super_admin | 她自己的全部条目（含隐私、含地点/溯源标签）——这是她自己的数据，仅在她本人会话里 |
| **其他超管（非 owner）** | roles 含 super_admin 但非 owner | 与 trusted 同格——**隐私不因同级而绕行** |
| **管理员 / trusted** | roles 含 admin/trusted | 该 owner 的**公开条目**：活动名 + 起止时刻（如「她正在上 高数，8:00 到 9:40」） |
| **普通用户（默认档）** | 其余全部 | 该 owner 的**公开条目**的**类别词 + 起止时刻**（如「她在上课，8:00 到 9:40」），**不给活动名** |

### 5.2 字段级铁律（对所有非 owner 档一致，写死）

- **只投影两样**：活动（名称或类别，按 5.1 档位）与时刻。**地点、教室、备注、
  溯源消息 id、置信度、文件路径——无论条目是否标公开，一律不进代答**。
  （她说"三教101"是她亲口说的，但对外代答缺省不点名地点；若要放开是她改代码常量
  或后续裁定的显式动作，不做成能拨错的开关。）
- **敏感类别下限**：条目类别为 健康/饮食/作息/心理 时，对非 owner 档永远折叠为
  「有事情」，**连类别词都不给**（即便她手滑标了公开）——"她在吃药"本身即泄露健康
  信息；类别映射：上课/考试→"在上课"，外出/办事/会议→"外出/有安排"，其余→"有事情"。
- **隐私条目对任何非 owner 档恒零呈现**：不存在、不计数、不否认——
  无公开可答条目时统一回模糊句（"她这会儿有事情，不在状态里～"），
  **绝不说"她的日程里没有安排"**（条目缺席不是证据，防"日程表是空的"这类反向泄露）。
- 出站正文统一过 `redact_local_secrets`（双保险：条目正文若含绝对路径形态，出站前洗）。
- 代答**不经 LLM**：模板池确定性成句（守岸人语气），杜绝"模型把隐私条目说漏嘴"。

### 5.3 触发与归属

- 触发词面（记录与代答各自成表，双向门词级对齐帮助册）：
  代答问句形如「她在干嘛/主人在忙什么/守岸人出去了吗」——**整句判据**（≤24 字、
  剥 mention/昵称前缀与句读后 fullmatch），防长句从句截胡；昵称动词「她在干嘛」
  带任何后缀探针（双向门 " 测试"/"？"）靠裸词命中。
- 被问对象（target）：缺省=本 bot 的**超管主人**（`bot_super_admin_user_ids`）；
  问句点名（"霞月在干嘛"）→ 该超管（按 `bot_admin_profiles` 显示名匹配）；
  多位超管且未点名 → 取**当前时刻有公开活动条目**的一位，都无 → 模糊句（绝不猜人）。
- 提问者是超管本人问"我在干嘛" → 走 owner 档（她自己的完整呈现）。

## 6. 失效与一致性

- 时区：全链 `config.bot_timezone`（经 reminders 的 `_as_local`/timesync 单一口径），
  UTC 落库、配置时区展示；跨时区部署不漂。
- 幂等：引擎 occurrence_id=hash(rule, revision, at)——重复导入同一课表不双落。
- 冲突：引擎 DAG/硬碰撞检测在 submit 处生效，冲突=拒绝并回显原因（不静默顺延，
  硬预约语义与合同一致）。
- 兼容：本波对 `reminders.py` 只做**行为不变的抽取重构**；对 `reminder.py`
  只做判据并联与分发插入（笔记/勾选/取消等既有分支逐字不动）。

## 7. 配置键台账（四处同生点名）

| 键 | 处置 | config.py | catalog A26 | .env.example | settings.py |
|---|---|---|---|---|---|
| `BOT_SCHEDULE_ENABLED` | **既有键启用**（缺省 False 不变） | 已有（更新注释：已被记录腿读取） | 既有行更新 | 既有行 | — |
| `BOT_SCHEDULE_DB_PATH` | 既有键（path_fields 在册） | 已有 | 既有 | 既有 | — |
| `BOT_SCHEDULE_STATUS_REPLY_ENABLED` | **新**，缺省 False | 新增字段 | 新增行 | 新增行 | **RESTART_REQUIRED_KEYS**（装配期快照 config 现读，与 bot_reminder_enabled 同型；不做"看着能热改"） |
| `BOT_SCHEDULE_NATURAL_CAPTURE_ENABLED` | **新**，缺省 False | 同上 | 同上 | 同上 | 同上 |

（读点全部 `getattr(config, "<字面量>")`——config 读点普查门的"名字直读"形态，
不造死键、不造幻影键；两枚新键同时并入 FACETS bot.reminder 的 `config_keys`。）

## 8. 有意不做 / 后置（理由在席位报告 §G）

- LLM 草稿多轮确认流、图片课表的**多轮补锚**（无会话态，一次问清为准）；
- 文件课表（PDF/xlsx）摄取路由（跨 files 域与根摄取面）；
- 引擎投递腿 `delivery.py` 接线（到点督促已由提醒域承担，双投递=行为变更需她裁）;
- 独立 RouteKind `SCHEDULE` 升级（配方在 §F，等安静窗与根文件协调）；
- 跨平台代答（QQ 之外）：条目由 QQ 会话产生，代答天然同会话面回；无特判。
