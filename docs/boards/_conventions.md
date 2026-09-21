# 统一规范（十板块文档树 · 代码结构 · 命名 · 开发约束）

> **本文件是规范本体，不是说明书。** 它规定的六件事对应用户 2026-09-21 的六条要求：
> 文件结构、统一规范、开发约束、自动化变更、问题处理、代码质量。
> 凡与本文件冲突的旧文档（`docs/HANDBOOK.md` 历史章节、各 `HANDOFF-*` 波次件）
> 一律以本文件为准；本文件与代码事实冲突时以代码为准，并立刻来改本文件。
>
> 计数一律不手写：板块/功能/主题数量由 `python scripts/board_doc_sync.py --check`
> 从代码派生，叙述文档只写「以生成物为准」。

## 〇、术语与三层结构

| 层级 | 名称 | 定义 | 磁盘形态 |
|---|---|---|---|
| 一级 | 板块 board（`BNN`） | 「实现这个 bot 需要哪十大块」，十块为上限，不得随意增删 | `docs/boards/BNN-<slug>/` |
| 二级 | 功能 feature（`BNN.<slug>`） | 一组同源实现、同一门禁口径的功能簇，一个功能一个目录 | `docs/boards/BNN-<slug>/<slug>/` |
| 三级 | 入口 function（`BNN.<slug>.<l3-slug>`） | 一个可独立调用/独立开关的功能入口：一个 RouteKind 席位、一个 `capability_id`，或一个显式声明项 | `<二级目录>/<l3-slug>.md` |

三级入口的判定规则（写死，不接受"感觉这算一个功能"）：

1. 代码里占一个 `RouteKind` 席位 ⇒ 一个三级入口（一个能力一张卡）。
2. 不占路由席位但有 `capability_id`（内部能力、旁路监听、调度器）⇒ 一个三级入口。
3. 纯机制件（契约、护栏、生成物、规范）由二级功能用 `extra_l3` 显式声明 ⇒ 一个三级入口。
4. 帮助主题**不**生成三级入口，它挂到对应三级入口的「别名与帮助页」列。
5. 其余任何粒度（一个函数、一个参数、一个模板）都不是独立入口，写在所属入口卡片的正文里。

## 一、文件结构规范（要求 1）

1. **一个功能一个目录**：二级功能目录必须存在，且其文档只允许出现在该目录内。
   禁止在板块根目录散放功能文档（板块根只放 `README.md`）。
2. **代码同构**：新增能力的代码落点固定为
   `plugins/bot_unified_runtime/domains/<域>/<层>/<capability_file>.py`，
   层名只准用现役集合：`capabilities` `service` `services` `store` `stores` `data`
   `sources` `feeds` `runtime` `character` `policy` `security` `render` `sender`
   `collectors` `admin` `monitor` `audit` `features` `incident` `recovery` `repair`
   `smoke` `acceptance` `sync_drift` `card_render` `templates` `ingest` `archive`
   `registry` `search` `video` `extensions` `_common` `config` `contracts`
   `credentials` `decision` `supervisor`。要加新层名，先在本文件登记一行并说明为什么。
3. **禁止跨功能混写**：一个 `.py` 文件只服务一个二级功能；确需共用则提到
   `domains/core/`（全仓唯一口径件）或该板块的 `_common/`。
4. **域内禁建第二真身**：同一逻辑只允许一个真身文件，旧路径只能留再导出垫片
   （`Compat shim` 头注 + PEP 562 `__getattr__`），且垫片不算实现。
5. 根目录与 `docs/` 只准保留**现役权威件**与生成物；波次过程件（席位日志、
   brief、report）留在 `.superpowers/`，不进 `docs/boards/`。

## 二、命名规范（要求 2）

| 对象 | 规则 | 例 | 反例 |
|---|---|---|---|
| 模块文件 | `snake_case`，名词或动名词，不带 `helper`/`util`/`common`/`new`/`v2` 之外的后缀 | `deck_math.py` `memory_bus_v2.py` | 万能名（tools / utils / common / final_fix） |
| 版本化真身 | 大版本换代的真身允许 `_vN` 尾（旧名保留为垫片） | `affinity.py`（v7 在内部）`memory_store_v21.py` | 同义改名（`affinity2.py`） |
| 公开函数 | `build_*` 构造装配 / `get_*` 取值 / `is_*`、`has_*` 谓词 / `resolve_*` 归一 / `load_*`、`save_*` 存储 / `handle_*` 能力入口 / `check_*` 门禁与体检 / `normalize_*`、`sanitize_*` 文本整形 | `build_model_router` `check_tts_voice_identity` | `do_stuff` `process2` |
| 私有函数 | 单下划线前缀，且只在同文件内使用 | `_enforce_context_caps` | 跨模块调 `_x` |
| 参数 | 全 `snake_case`；布尔参数以 `enabled`/`_only`/`_once` 结尾；判定上下文用 `*for_session`；关键词-only 边界用 `*` | `allowed_levels=None` `session_type` | `flag` `tmp` `arg1` |
| 常量表 | 全大写复数名词，`*_DECLARATIONS` / `*_REGISTRY` / `*_TABLE` | `ROUTE_CAPABILITY_DECLARATIONS` | `configList` |
| 配置键 | `bot_<域>_<项>`，pydantic 字段 `bot_*`；`.env` 名 `BOT_*`；路径类必进 `path_fields` 重映射 | `bot_tts_ref_audios` | `BOT_ENABLE2` |
| 稳定 id | 能力 `bot.<域概念>`；路由 `RouteKind.<UPPER>`；板块 `BNN`；功能 `BNN.<slug>`；帮助主题中文名 | `bot.emergency_info` | 用中文当 id |
| 板块文档名 | 目录/文件名全 `kebab-case`，不带编号前缀（编号由板块目录承担） | `affinity-mood/` | `3.2好感度.md` |

函数说明文档（docstring）统一骨架——公开函数必须有，私有函数非平凡逻辑必须有：

```python
def build_xxx(deps: Deps, *, enabled: bool = True) -> Xxx:
    """一句话：造出什么、给谁用。

    口径：（该函数负责的单一事实源是什么、不做什么）
    失败：（异常/降级/静默返回的契约，以及谁兜底）
    配置：bot_xxx_*（缺省值与热更性）
    """
```

## 三、开发约束：先建模块与函数，只调用已登记的（要求 3）

这四条是**硬门**，不是倡议。任一违反 ⇒ 对应测试红 ⇒ 不可合入。

1. **新增一个能力**必须按序完成，缺一步即红：
   ① 在 `domains/<域>/capabilities/` 建函数与文件（先有实现入口）→
   ② 在 `capability_registry.py` 的 `ROUTE_CAPABILITY_DECLARATIONS` 登记一行
   （RouteKind / `capability_id` / priority / label / matcher）→
   ③ 在 `base_router.py` 的字面投影表与 `echo.py` 帮助表按既有一致性门补齐 →
   ④ 在 `board_taxonomy.py` 里它所属二级功能自动获得三级入口（若该 route kind 未有人认领则红）。
2. **不得就地新写已有能力的第二次实现**：需要某功能时先在板块树里找它的三级入口，
   找到就调用其公开函数；找不到就是缺登记——先登记再调用，不允许复制粘贴一份。
   典型反面（历史上真发生过）：触发词字符集六份副本、`pick_variant` 四套互斥实现、
   占卜两套牌算与两颗 `DrawError`。
3. **不得绕过中央件**：出站只准走 `review → renderer → send_queue → sender`；
   投递主动消息只准走 `submit_active_push`（禁直调 `send_queue.submit`）；
   会话键只准走 `domains/core/session_keys.py`；文本边界只准走
   `domains/core/text_boundary.py`；配置读取只准走 `load_runtime_config` 唯一入口。
4. **不得自造 token 与样式**：渲染只准 `theme_tokens.py` 登记族，族外值一票否决。

## 四、自动化变更契约（要求 4）

**一处变更、处处跟随**，靠三层机制，不靠人记得住：

1. **声明源单点**：能力（keystone）、帮助（`_HELP_ENTRIES` + `HELP_TOPIC_DECLARATIONS`）、
   配置（`config.py`）、板块（`board_taxonomy.py`）各自只有一个权威声明处。
2. **生成物投影**：`scripts/board_doc_sync.py`、`doc_sync.py`、`command_catalog.py`、
   `verify_hashes.py` 从声明源机械推导 `docs/boards/**`、`docs/auto-facts.md`、
   `docs/command-catalog.md` 与哈希台账；生成物内**人工正文块**用
   `<!-- BOARD-AUTO:BEGIN --> / <!-- BOARD-AUTO:END -->` 标记包裹，标记外的文字永不覆盖。
3. **常驻门**：`tests/test_board_taxonomy_gate.py` 与既有交叉验证门在每次 `dev.ps1 -Task test`
   实跑比对。改代码不改文档 ⇒ 门红 ⇒ 本地就发现，无需人肉巡检。

因此：**新增一个能力，板块文档树自动多出一张卡**；**改一个 label/优先级/帮助主题，
所有投影自动跟随**；**删一个能力而文档还认领它，直接红**。

## 五、统一口径（要求 2 的"六条尺子"落地）

| 尺子 | 现役唯一真身 | 板块位置 |
|---|---|---|
| 统一消息 | `IncomingMessage` 与段归一层 | B01 |
| 统一协议 | `RouteKind` 枚举 + OneBot V11 段语义 | B02 / B01 |
| 统一架构 | 主链路十六段（ingress→…→audit） | B02 |
| 统一入口 | keystone 声明源 + 中央调度信封 `InvocationResult` | B02 |
| 统一口径 | 机器册 `docs/auto-facts.md` + 板块生成物 | B10 |
| 统一产出 | `review → renderer → send_queue → sender` | B08 |

主链路十六段（所有消息、自动回复、戳一戳、表情、定时任务、通知、文件、错误回复都必须走完）：

```
ingress → normalization → route → feature_state → policy → rate_limit → idempotency
→ capability → persona → knowledge → memory → model_router → review → renderer
→ send_queue → transport → receipt → audit / metrics / trace
```

流程图与分布图统一约定：只用 mermaid `flowchart LR/TD` 与 `sequenceDiagram` 两种；
节点名用稳定 id（`B03.affinity-mood`）不用中文长句；一条主链路一张图，功能卡内只画
自己那一段，禁止每张卡各自重绘全链路（那是漂移之源）。

## 六、问题处理分级（要求 5）

| 级别 | 定义 | 处置时限 |
|---|---|---|
| P0 | 数据丢失/密钥泄漏/进程崩溃/线上静默不干活且无人知晓 | 立即修，修完必须补能杀该行为的用例 |
| P1 | 功能结果错误、口径分叉、两处真身互相打架、门禁假绿 | 本波内修，且必须落一条锁 |
| P2 | 结构混乱、命名不一致、文档重复或失效、缺 docstring、无谓副本 | 整理波内批量清，可留待裁决 |

判据纪律：**存在性锁不算修好**。任何"已处理"必须给能杀行为的证据（变异注毒打红、
或端到端用例真的走通），静态可达性断言只能算辅助。

## 七、代码质量红线（要求 6）

1. 一文件一职责；函数超 120 行必须说明为什么不能拆（注释一行，不写长篇）。
2. 禁止吞异常：`except` 必须记原始异常文本或显式注释为什么可以静默。
3. 禁止未登记的全局可变状态；跨线程共享必须显式锁或不可变快照。
4. 禁止"以后再说"式空壳：宁可不留函数，也不留 `pass` 占位让文档宣称已有能力。
5. 删除即删除：不留 `# removed` 注释、不用 `_unused` 变量占位、不建向后兼容的假导出。
6. 任何"看起来更安全的保守默认值"要与本文件第五节的口径一致，不得私自把放开改回关闭。
