# 代码库规模审计与精简方案（提案，未实施）

> **身份**：只读审计 + 精简提案。本文件不包含任何已执行的代码改动；执行属大改动，走「先报后动」——本文件即报审件，待用户裁决后按 §四 提示词交给主 Agent 执行。
> **数据**：2026-09-13 实跑统计，复跑命令见 §五，全部可验证。分支 `v0.0.1-alpha.2`。
> **维护**：执行完成后由主 Agent 更新 HANDBOOK（新增小节记 commit 哈希），本文件归档或标记「已实施」。

---

## 一、规模统计（verified，实跑 wc）

### 1.1 总量

| 类别 | 行数 | 文件数 | 说明 |
|---|---:|---:|---|
| Python 合计 | **162,302** | 507 | git 入库 + 未跟踪源码，排除 gitignore |
| ├ 主包 `plugins/bot_unified_runtime/` | 103,630 | 249 | 生产代码 |
| ├ `tests/` | 53,250 | 238 | 测试:源码 ≈ 0.51；4523 用例（数字来自台账 #27 记录，非本次实跑） |
| ├ `scripts/` | 5,211 | — | e2e/生成器/测量脚本 |
| └ `bot.py` | 211 | 1 | 启动 + 崩溃守卫 |
| md 文档 | 16,442 | 45 | HANDBOOK 体系 + 规格 |
| `sources/data/qx.json` | 15,163 | 1 | 天气 2527 区县码表，**数据资产非代码** |
| HTML 卡片模板 | 2,873 | 6 | output/card_render Jinja 模板 |
| PowerShell | 1,029 | 2 | dev.ps1 等 |
| 入库文件总数 | — | 566 | |

### 1.2 主包子模块分布（103,630 行）

| 子模块 | 行数 | | 子模块 | 行数 |
|---|---:|---|---|---:|
| sources（解析器/订阅/数据源） | 31,753 | | output（渲染/出站文案） | 4,238 |
| capabilities（29+ 能力） | 20,079 | | llm（路由/计费） | 3,794 |
| **包根（`__init__`+smoke+config 等）** | **15,754** | | contracts | 2,413 |
| character（人格/好感/记忆） | 9,575 | | policy | 1,911 |
| runtime | 6,408 | | decision（shadow 未接管） | 917 |
| sender | 5,039 | | control_plane（默认关） | 896 |
| | | | security / audit | 492 / 361 |

### 1.3 超 1000 行的源码文件（17 个，占主包约 40%）

| 文件 | 行数 | | 文件 | 行数 |
|---|---:|---|---|---:|
| **`__init__.py`** | **6,682** | | sender/queue.py | 1,683 |
| **`smoke.py`** | **3,831** | | output/card_render/bridge.py | 1,667 |
| **`capabilities/echo.py`** | **3,335** | | sources/subscriptions/social_v2.py | 1,370 |
| capabilities/chat.py | 2,895 | | config.py | 1,183 |
| sources/parsers/platforms_bilibili.py | 2,136 | | diagnostics.py | 1,171 |
| sources/parsers/platforms_generic.py | 1,979 | | sources/stock_data.py | 1,120 |
| character/vector_knowledge.py | 1,867 | | policy/rate_limit.py | 1,018 |
| capabilities/debug.py | 1,802 | | （tests 另计） | |
| llm/model_router.py | 1,795 | | capabilities/runtime_admin.py | 1,761 |

---

## 二、审计结论

### 2.1 总判断

**总量大但不属于失控膨胀**：规模与功能面成正比。本项目实际是「20 多个小产品捆在一个进程」（29+ 能力、37+ 平台解析器、4 适配器、卡片渲染引擎、LLM 故障转移、订阅管线、人格/好感/心情子系统），平摊每能力约 4k 行（含数据源与测试），功能密度正常。行数不是当前瓶颈，**热点文件的认知负担与「一功能五处登记」的结构税才是**。

### 2.2 不是肥肉的部分（不要动）

- **tests 53k 行**：4523 用例是敢于继续重构的前提，是资产。
- **qx.json 15k 行**：数据码表（曾三次被误清，见台账 #27①，已随包入库根治）。
- **文档 16k 行**：有意为之的交接体系，doc_sync_gates 强制文档-代码同步。
- **休眠子系统**：decision/（917，shadow 未接管）、control_plane（896，M1 默认关）、ledger（默认关）≈ 2.7k 行前置建设，均有 B2/B4/B5 规格与台账裁定，属「已建待启用」而非死代码。
- parsers 双平台大文件（bilibili 2.1k / generic 2.0k）：平台解析天然按平台聚拢，拆了反而增加跳转成本。

### 2.3 真正的冗杂热点（按收益排序）

**H1 `__init__.py` 神模块（6,682 行，76 个顶层符号）**——verified：摄取段处理（`_onebot_segments_*`/`contains_*_segments`/`_forward_*` 引用链/提及检测）、发送装配（`_select_credential_bot`/`_select_queue_bot`/`_queue_bot_unavailable_receipt`）、调度器注册家族（`_register_*_scheduler`）、事件模型（`PrivateFileNoticeEvent`）混居一个文件。任何功能接线都可能碰它 = 合并冲突与回归风险的头号来源。**全项目收益最高的一次重构。**

**H2 结构税（认知层面）**——加一个功能要动 config.py（470 字段）+ echo.py help 注册（67 topics）+ route-matrix + command-catalog + 文档门禁，五处登记。已有生成器与 doc_sync_gates 自动化兜底，方向正确，不另立工程，仅靠 H3/H4 缓解。

**H3 `smoke.py` 3,831 行诊断 CLI 住生产包**——verified 引用面：`console_chat.py:101` **顶层导入**、`route_demo.py:212`/`backend_unit.py:27`/`capabilities/debug.py`（5 处延迟导入）引用 `load_smoke_config`/`run_persona_smoke`/`run_readiness_smoke`/`run_dialogue_smoke`/`run_llm_setup`，另有 `tests/test_smoke_config.py`（108 行）。**不是孤儿文件，出包必须连动 5 处。**注意区分：`config_readiness.run_config_smoke` 是另一个函数，不在本热点内。

**H4 `echo.py` 3,335 行 help 数据与逻辑混居**——`_HELP_ENTRIES`（67 topics）数据与渲染逻辑同文件；`scripts/command_catalog.py` 从它生成目录，多个契约测试断言覆盖。数据外置后 help 维护变成改数据。

---

## 三、精简方案（按执行顺序；与 §2.3 收益排序不同，先易后难，大动作放最后）

> 总铁律：**零行为变更**。`/bot help` 输出、路由行为、包导入面（`from plugins.bot_unified_runtime import X`）三者字节级/语义级不变。每 Phase 独立 commit，四门禁全绿才进下一阶段。

### Phase 0：基线（不动代码）

实跑四门禁记录基线：`test`（用例数/耗时）、`lint`、`typecheck`（文件数）、`runtime-layout`。产出数字写入执行记录，作为各 Phase 对比锚点。

### Phase 1：echo.py 帮助数据/逻辑分离（低风险，先跑通流程）

- **改前**：echo.py 3,335 行，`_HELP_ENTRIES` 数据 + 渲染/分发逻辑混居。
- **改后**：新增 `capabilities/echo_help_data.py`（纯数据），echo.py 顶部 `from .echo_help_data import _HELP_ENTRIES, ...` **re-export 保号**——外部引用（command_catalog 生成器、help 契约测试）零改动。
- **收益**：echo.py 减约 1.5-2k 行；help 文案维护不再触碰逻辑代码。
- **风险**：低。数据是纯常量；help 输出有契约测试（test_help_entries_coverage 等）锁死。
- **回滚**：单 commit revert。
- **验收 AC**：四门禁全绿；`python scripts/command_catalog.py` 重生成后 `docs/command-catalog.md` **零 diff**；help 相关契约测试全过。

### Phase 2：smoke.py 收纳（中低风险）

- **改前**：smoke.py（3,831）与同类 dev CLI（console_chat/route_demo/backend_unit）散在包根，顶层导入拖累生产包命名空间。
- **改后（推荐 b 案）**：包内新建 `devtools/` 子包归拢 `smoke.py`（可选连带 console_chat/route_demo/backend_unit），原路径留薄 shim re-export，5 处引用点逐步切换后删 shim；`capabilities/debug.py` 的 4 处延迟导入改为指向新位置。
- **收益**：包根职责变纯；诊断工具集中一处。
- **风险**：中低——`console_chat.py` 是顶层导入，shim 期必须保留；导入链需 typecheck 验证。
- **回滚**：单 commit revert。
- **验收 AC**：四门禁全绿（含 test_smoke_config）；`python -m plugins.bot_unified_runtime.smoke --help` 等入口行为不变；runtime-layout 体检通过。

### Phase 3：`__init__.py` 三步拆分（高风险高收益，压轴）

- **改前**：6,682 行神模块（见 H1）。
- **3a 准备步**：产出 **76 个顶层符号去向映射表**（附录 A 起草，执行时补全），作为 3b/3c 的依据写入 commit message。
- **3b 摄取域拆出**：段归一/引用链/提及检测/语音转码/事件模型 → `runtime/ingestion.py`（过大再分 ingest_onebot/ingest_forward）。
- **3c 发送装配 + 调度器注册拆出**：`runtime/dispatch.py` + `runtime/scheduler_registry.py`。
- **改后**：`__init__.py` 收缩为 **≤500 行薄门面**，全部 re-export 保号。
- **收益**：神模块消失；冲突域分离；摄取/发送/调度可独立测试。
- **风险**：高——NoneBot matcher 注册时机与导入顺序敏感、循环导入风险。**触发条件**：任一子步 typecheck/test 红 → 停在该子步，修复后才继续；同一步两次失败 → 停止并报告，禁止第三次盲试。
- **回滚**：3b/3c 各自独立 commit，可单独 revert。
- **验收 AC**：四门禁全绿；映射表内 76 符号在新家可导入（门面 re-export 等价）；`test_production_wiring`/`test_bgroup_chat_pipeline` 等接线测试全过。

### 3.5 明确不做（防执行走样）

- ❌ 不拆 config.py（1,183 行、470 字段密度合理，且热改/快照敏感，台账 #3 在案）。
- ❌ 不删休眠子系统（decision/control_plane/ledger，等 B2/B4/B5 裁决）。
- ❌ 不动 parsers 大文件、不动渲染契约锁定面（theme_tokens/6 模板/4 f-string 卡）、不动 personas 与任何用户可见文案。
- ❌ 不做全局重命名/目录大迁移式的「美化重构」。
- ❌ 本报告不要求压缩总行数 KPI——目标是热点分散与结构税缓解，行数下降是副产品。

---

## 四、交给主 Agent 的提示词（复制即用）

```text
【任务】按 docs/codebase-slim-plan.md 执行代码库精简（Phase 0→3，纯结构重构，零行为变更）。

【上下文】方案全文（统计、热点、逐 Phase 改前/改后/风险/回滚/验收）都在该报告中，先通读再动手。
工作区规则以根目录 AGENTS.md 为准（自动加载），与本提示冲突时以 AGENTS.md 为准并明确指出。

【总原则】
1. 零行为变更：/bot help 输出、路由行为、包导入面三者不变；
   `from plugins.bot_unified_runtime import X` 的全部既有用法必须继续可用。
2. 每 Phase（含 Phase 3 的 3b/3c）独立 commit，四门禁全绿才进下一步；不 squash，保持逐段可回滚。
3. 顺序固定：Phase 0 基线 → Phase 1 echo 拆分 → Phase 2 smoke 收纳 → Phase 3 __init__ 三步拆。
   任一门禁红 → 当步停止修复后才继续；同一步两次失败 → 停下向用户报告，禁止第三次盲试。

【硬约束（AGENTS.md 细则重申，违反即事故）】
- git：逐文件显式 add，禁 git add -A / git add .；提交后 git show --stat HEAD 核对；不 push（等用户明确指示）。
- 验证只认 dev.ps1 四门禁：test / lint / typecheck / runtime-layout 全绿才算过（命令见报告 §五）。
- 禁触：personas/、ChatBot_Runtime/、sources/data/qx.json、渲染契约锁定面（theme_tokens.py、6 模板、4 f-string 卡）、.env；
  不改 config.py 字段语义；不改任何用户可见文案与人格话术。
- 源码树零缓存：不绕开 dev.ps1 裸跑 python/pytest；确需直跑按 AGENTS.md 第一部分第 6 条加参数。

【各 Phase 验收（细则以报告 §三为准）】
- Phase 0：四门禁基线数字落盘（写入执行记录）。
- Phase 1：拆出 capabilities/echo_help_data.py，echo.py re-export 保号；
  scripts/command_catalog.py 重生成后 docs/command-catalog.md 零 diff；help 契约测试全绿。
- Phase 2：按报告 Phase 2 的 b 案执行，5 处引用点连动（console_chat 顶层导入须留 shim），
  tests/test_smoke_config.py 全绿，工具入口行为不变。
- Phase 3：3a 先产出 76 符号去向映射表（报告附录 A 起草版补全）；
  3b/3c 各一 commit；终态 __init__.py ≤500 行纯 re-export 门面；test_production_wiring 等接线测试全绿。

【收尾】全部完成后一次性汇报：每阶段 commit 哈希 + 四门禁实跑输出摘要（用例数/耗时）；
更新 HANDBOOK（新增小节记录本批）、AGENTS.md 受影响章节（目录地图/台账）、docs/README.md 索引；
报告 §五 基线数字与本批终态对比。

【禁止】不 push；不改测试预期来「让测试变绿」；不跳过门禁；不顺手修本任务外的 bug
（发现新问题写入执行记录「新发现」节，另行报告）。
```

---

## 五、证据与边界

### 5.1 复跑命令（Git Bash）

```bash
# 总量与分布（-z 防中文文件名转义漏算）
git ls-files -z --cached --others --exclude-standard -- '*.py' | xargs -0 wc -l \
  | awk '$NF=="total"{next}{tot+=$1; if($2~/^tests\//)t+=$1; else if($2~/^scripts\//)s+=$1; else if($2=="bot.py")b+=$1; else o+=$1}
         END{printf "py=%d main=%d tests=%d scripts=%d bot=%d\n",tot,o,t,s,b}'
# 子模块分布 / 最大文件 / 非代码资产：同一 ls-files 管道换 awk 分组即可（见审计会话记录）
```

### 5.2 验证门禁（执行期唯一口径）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
```

### 5.3 置信度与边界

- §一 全部数字、§2.3 热点符号与 smoke 引用面、`__init__.py` 前 40 个顶层符号：**verified**（2026-09-13 实跑）。
- `__init__.py` 后 36 个符号未逐个列举（76 个仅见前 40）→ Phase 3a 补全映射表，**unknown → 届时 verified**。
- 4523 用例数引自台账 #27（2026-09-13 批次记录），本次未实跑测试。
- 「规模与功能面成正比」的判断为基于上述数据的工程判断（high），非机械结论。

### 附录 A：`__init__.py` 76 符号去向映射表（起草，前 40 符号）

| 去向 | 符号（前 40 个中） |
|---|---|
| → runtime/ingestion.py（3b） | `_onebot_segments_from_message_payload`、`_extract_onebot_raw_segments`、`contains_visual/forward/audio_message_segments`、`_urls_from_message_segments`、`_detect_text_at_mention`、`_detect_onebot_direct_mention`、`_mentioned_by_affinity_nickname`、`_refresh_affinity_nicknames`、`set_runtime_mention_terms`、`_effective_route_text`、`_transcode_record_segments`、`_forward_segment_id`、`_forward_message_text_sync`、`_forward_message_text`、`_incoming_from_nonebot_event`、`_PrivateOfflineFile`、`PrivateFileNoticeEvent` |
| → runtime/dispatch.py（3c） | `_normalize_adapter_name`、`_bot_adapter_name`、`_select_credential_bot`、`_select_queue_bot`、`_queue_bot_unavailable_receipt`、`_transport_audit_event`、`_runtime_tag_values`、`_send_queue_is_drainable`、`_log_runtime_event`、`_config_with_runtime_overrides` |
| → runtime/scheduler_registry.py（3c） | `_register_send_queue_scheduler`、`_register_credential_check_scheduler`、`_register_today_history_scheduler`、`OptionalSubscriptionRegistration`、`defer_optional_subscription_registration` |
| → 待定（3a 裁决） | `_runtime_scripts_path`、`_build_chat_llm_provider`、`_build_memory_writer`、`_is_plain_chat_text`、`_make_onebot_reply_lookup`、`_cached_route_decision` + 后 36 个未列举符号 |
