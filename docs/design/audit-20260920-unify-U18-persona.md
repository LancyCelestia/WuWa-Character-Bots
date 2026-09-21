# 审计日志 U18-PERSONA —— 人格与上下文注入统一（2026-09-20 统一波）

> 席位：U18-PERSONA（只读审计子代理）
> 范围：后端 Python。**不查**：webui/、domains/render/**、output/card_render/**、theme_tokens.py、TTS/语音链路。
> 人格**文本内容本身**不作评判（personas/ 只读），本席审**注入链路的统一性与边界安全**。
> 硬禁令：无子代理、无 git 写、无代码/配置/文档修改（除本文件）、无 `--write`、无真实 LLM/发送/重启、不读 .env 明文、Runtime 只读。
> 状态图例：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 已落盘

## 0. 取证环境

- 工作区：`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot`
- 解释器：`../ChatBot_Runtime/venv/Scripts/python.exe`
- 注入 env：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`
- pytest：`--basetemp="$TEMP/u18-*" -p no:cacheprovider`（禁全量）
- **本席取证方式**：`Read/Grep/Glob` + 只读 `sed/grep/find/wc` Bash；比对脚本用 stdlib 读源码文本，**全程不 import 项目包**（因此不存在 .pyc 产生面）；唯一写入 = 本文件 + `%TEMP%` 下脚本。若后续偏离本行即更正。
- 字节码/源码树残留自查：见文末「自查与残留」节。

### 装配咽喉的真实坐标（先定锚，后续引用）

- 中央装配器（状态→bundle）：`plugins/bot_unified_runtime/domains/chat_reply/character/providers.py:350 FileCharacterContextProvider.build_context`（锚点 `# 用户显式偏好（调用方参数）优先于持久化偏好`）。旧路径 `plugins/bot_unified_runtime/character/providers.py` 是 20 行 PEP 562 活垫片（锚点 `"""Compat shim: moved to plugins.bot_unified_runtime.domains.chat_reply.character.providers`）。
- 中央提示词装配器（bundle→messages）：`domains/chat_reply/capabilities/chat.py:1462 build_chat_prompt_with_diagnostics`（锚点 `# 动态分区：只有确实有内容时才输出，空分区整块不出现`）。
- 结论：**「装配器」实际是两个咽喉**（bundle 装配 + prompt 装配），二者都是单一实现；缺陷全部来自「旁路」而不是「重复实现」。

---

## D1 上下文装配中央化取证 — `[x]`

### D1-1【P1】六条通路绕过中央装配器自拼提示词，其中三条产出「守岸人语气」的用户可见文本

**坐标 + 锚点（逐条）**

| # | 通路 | 坐标 | 锚点字符串 | 自拼了什么 | 丢了哪些分区/规则 |
|---|---|---|---|---|---|
| 1 | 戳一戳 LLM 话术 | `plugins/bot_unified_runtime/__init__.py:5189` | `"你是守岸人。有人刚刚在QQ上戳了你一下。"` | 手写 system+user 两条，仅带 `attitude_hint`（好感档定性文本） | 称谓与主角边界、管理团队/权限、心情、怪癖、会话身份、表情回应、记忆、安全边界全文、反注入包裹、`assess_public_content` 红线门 |
| 2 | 收件箱早报/晚报「划重点」 | `domains/assistant/daily/store/daily_assist.py:345 summarize_with_llm` | `router.generate([{"role": "user", "content": f"{instruction}\n\n{stripped[:4000]}"}]` | 单条 user 消息，无 system | 全部人格分区；**且无 `_SAFETY_BOUNDARY_TEXT`**：`stripped` = 收件箱正文（用户手输/手机同步进来的任意文本）未过 `check_prompt_injection`、未过 `_sanitize_untrusted_context_text` |
| 3 | 群摘要 LLM 压缩 | `domains/chat_reply/character/shared_group.py:299` | `"你是群聊话题摘要助手。"` | 自带 system+user 两条；群内任意成员消息进 prompt | 未过 `check_prompt_injection`（该函数唯一消费者=chat/debug/smoke 三点，见 D3-3），未过内部标记全角化 → 群消息里的 `[UNTRUSTED_USER_TEXT]`/`[/引用回复]` 原样进模型 |
| 4 | 日程结构化草稿 | `domains/schedule/llm_draft.py:294`（提示词 `:196 _DRAFT_SYSTEM_TEXT`） | `"你帮用户把一句话安排整理成结构化清单。只输出 JSON"` | 任务型提示词，自称「守岸人口径」但无人格注入 | 任务型可接受；缺项=外部文本未包裹（用户输入直进 user 消息，风险等同 #2） |
| 5 | 课表解析 | `domains/schedule/timetable.py:320` | `_LLM_TIMETABLE_PROMPT` | 同上，任务型 | 同上 |
| 6 | 文档导出 | `__init__.py:5480` | `{"role": "system", "content": _DOCUMENT_PROMPT}` | 管理员命令面直连 `_build_chat_llm_provider(config).generate` | 绕过 `model_router`（无故障转移/无 `content_route`/无账本归因），管理员门槛内、非人格面 |

**判定为「过中央装配器」的通路（正证）**：chat 主链与主动搭话（`chat.py:3010` 唯一生产 `build_context` 调用点）；`chat.py:2122` 唯一生产 `build_chat_prompt_with_diagnostics` 调用点。提醒督促投递、笔记、占卜、错误卡、校园（U17 在改）为**确定性文案模板**，不调 LLM，故不在「自拼提示词」名单内（`grep -rn "llm\|model_router\|prompt" domains/schedule/*.py` 除 #4/#5 零命中）。

**根因**：中央装配器只对 `bot.chat` 能力开放；不存在「任何要进模型的文本必须过装配器」的结构锁。`check_prompt_injection` 与 `assess_public_content` 同样只挂在 chat 能力内（D3-2/D3-3），因此旁路同时缺三道门：红线、反注入、人格分区。

**改法 before→after（只复用既有咽喉，不新建第三套；取舍留用户裁决）**
- before：6 处各自 `generate([...])`，人格与边界规则按通路离散。
- after：
  - #1 戳一戳：删掉本地手写的 `"你是守岸人。"` 字面，改由既有公共件产出这两条消息——候选 A：`build_chat_prompt_with_diagnostics(provider.build_context(...))`（同主链，含人设原文与全部分区）；候选 B：复用既有 `build_addressing_context` + `_SAFETY_BOUNDARY_TEXT` 两个现成件拼精简版。
  - #2 划重点 / #3 群摘要：入模文本先过既有 `_sanitize_untrusted_context_text`，尾部拼既有 `_SAFETY_BOUNDARY_TEXT` 常量。
  - #4/#5 任务型：复用既有 `check_prompt_injection` 做输入侧门。
  - 本席不自建中央件：若要「一处生效」级别的收口，缺的机制=「分区/边界的可复用出口」，现成候选已列（重=chat 提示词装配器，轻=addressing + injection 两函数），**选哪个属用户裁定**。

**验证命令**
```bash
# 旁路清点（期望：除 chat 主链外命中数只降不升）
grep -rn '"role": *"system"' --include=*.py plugins/ | grep -v domains/render | wc -l
grep -rn "check_prompt_injection(" --include=*.py plugins/ | grep -c "sanitized_text\|InjectionCheckInput"
```
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_poke_v2.py tests/test_daily_assist.py \
  --basetemp="$TEMP/u18-d1" -p no:cacheprovider -q
```

### D1-2【P1】五条二级装配路径整体丢失 5 个分区 + 群/私聊身份判定退化

**坐标**：`domains/chat_reply/pipeline/backend_unit.py:85`、`domains/chat_reply/runtime/prompt_preview.py:48`、`domains/ops/admin/debug.py:444`、`domains/ops/smoke/smoke.py:285 / :586 / :820 / :984`、`domains/ops/smoke/console_chat.py:232`。

**证据（kwargs 差分，实读）**：生产唯一正确装配 `__init__.py:4643` 传 `runtime_settings + shared_group_llm_provider + mood_describe + quirks_describe + identity_describe + reactions_describe`，并给 `build_chat_capability` 传 `admin_roster_text=_build_admin_roster_text_for_chat(config)` 与 `affinity_store`。二级路径差分：

| 路径 | mood | quirks | identity | reactions | admin_roster | affinity_store | group_id/称谓入参 |
|---|---|---|---|---|---|---|---|
| backend_unit:85 | 丢 | 丢 | 丢 | 丢 | 丢 | 丢（走 relationship_provider 默认档案） | 传（chat 能力内） |
| prompt_preview:48 | 丢 | 丢 | 丢 | 丢 | 丢 | 丢 | 硬编码 `private:prompt-preview` |
| debug.py:444 | 丢 | 丢 | 丢 | 丢 | 丢 | 丢 | **`build_context` 不传 group_id/sender_display_name/sender_roles/sender_profile_note** |
| smoke.py:820/984 | 丢 | 丢 | 丢 | 丢 | 丢 | 丢 | 同 debug |
| console_chat:232 | 丢 | 丢 | 丢 | 丢 | 丢 | 丢 | 控制台会话 |

**关键退化（不只是"少几行"）**：`providers.py:370/375` 的会话口径是 `session_type="group" if group_id else "private"`，debug/smoke 不传 `group_id` → 对**群消息**的诊断输出把称谓分区算成 private（`addressing.py:82` 分支 → 「对方可视为漂泊者」），并丢掉 【当前群成员身份事实】【当前群聊】【管理团队】三块。锚点：`sender_profile_note="；".join(` 仅出现在 `chat.py:3023` 生产调用点。

**后果**：`/bot logs`/上下文诊断/smoke 预检/`prompt_preview` 是重启验收的**证据来源**（AGENTS 第五部分、acceptance-manual §6.6 系列），它们看到的 system prompt 与生产实际发送的 system prompt 不是同一个文本 → 以旁路证据判定人格面属实的验收结论不可信。

**改法 before→after**：before 各路径 `build_character_context_provider(config)` 裸调；after 抽 `build_default_character_provider_kwargs(config, runtime_settings)` 单一工厂（`__init__.py:4643` 与五处共用），`build_context` 的 `group_id/sender_*` 入参同样抽一个 `context_kwargs_from_message(message)` helper（`chat.py:3010-3037` 与 debug/smoke 共用）。验证：`grep -rn "build_character_context_provider(config)" plugins/` 命中数应为 0（全部带 kwargs）。

### D1-3【P2】分区清单：代码一份（21 个挂载点）、文档四份（陈旧计数 13）、测试零枚举、无契约门

- 代码唯一清单：`chat.py:1551-1618` 的 21 个 `dynamic_parts += [` 挂载点（`grep -c 'dynamic_parts += \[' = 21`，实跑输出）。
- 文档四份口径 = 13：`AGENTS.md:97`、`docs/HANDBOOK.md:1489`、`docs/HANDOVER-2026-09-15.md:70 / :114`。
- 测试面：`grep -rho "【[^】]*】" tests/*.py` 显示逐标签断言存在（【世界观】9 次、【当前群聊】7 次…），**无任何「分区全集/顺序」枚举断言** → 新增/删除分区不会触发文档与测试红。
- 「空分区不渲染」：唯一实现在 `chat.py:1551` 起的 `if … .strip()` 门，生产与全部二级路径共用同一函数 → **该项一致（无缺陷）**，quirks/identity 两块自带标签（分区文本由 store 侧 `render_prompt_section` 生成，标签在 store 里，挂载在 1558/1560 → 标签来源分裂：19 块标签在 chat.py，2 块在 `quirks.py`/`session_identity.py`）。
- 顺序稳定性：追加顺序=源码顺序，确定；**但内容每轮漂移**——`chat.py:1428 runtime_parts.append(_danger_style_line())` → `pick_variant("chat_danger_comfort", …)`（`daily_assist.py:332`，**进程级全局游标 `_VARIANT_CURSORS`，非会话级**）。同一条示例句写在 **system 提示词**里，每轮 +1 → 与 `chat.py:819-823` 声明的「system 不再承载对话正文/前缀缓存」意图直接冲突（system 每轮必变），且跨会话互相推进游标。锚点：`example = pick_variant("chat_danger_comfort", _DANGER_COMFORT_EXAMPLES)`。
  - 附带确定性缺陷：全局单游标下，若并发会话数 n 与池长 m 不互质，某会话将**周期性看到同一句**（m=10、两会话交错 → 各自固定看到奇/偶位）。这属 U9「选择机制」面，此处只登记人格面后果：安抚示例的本意是"逐轮漂移防复读"，交错场景下失效。

### D1-4【P2】system 提示词两分支语义不同源：字段重组分支丢 `_RUNTIME_CONTEXT_USAGE`

- `chat.py:1624 if raw_persona:` → `_compose_persona_verbatim_prompt`（`:1422-1440`）注入 `_RUNTIME_CONTEXT_HEADER` + `_RUNTIME_CONTEXT_USAGE`（「情绪/心情只调语气…不汇报数值」）+ `_SAFETY_BOUNDARY_TEXT`。
- `else` 分支（`:1632-1669`）只拼 `parts += dynamic_parts` + `_SAFETY_BOUNDARY_TEXT`，**不含 `_RUNTIME_CONTEXT_USAGE`**。
- 生产可达性：`persona_context_preflight_errors`（`domains/core/config/config_readiness.py:125`）在人格文件为空/缺失时返回 `persona_files_empty` → `chat.py:2891 if context_preflight_errors: return _context_error_result(...)` 提前拦，故正常配置下 else 分支不可达；但 `NullCharacterContextProvider`（`providers.py:138-158`，`raw_text` 缺省空）与 `backend_unit/prompt_preview` 类旁路会走 else 分支 → 旁路与生产的「行为约束总说明」不一致，且无门锁定「两分支必须同清单」。
- 改法：把 `_RUNTIME_CONTEXT_USAGE` 提到 `build_chat_prompt_with_diagnostics` 主体拼接（两分支共用），或加契约测试断言两分支都含 `_RUNTIME_CONTEXT_USAGE` 首句。验证：`python -c` 直调 `build_chat_prompt(ContextBundle(persona=…raw_text=""))` 断言含「以下【】块为运行时注入的实时信息」。

### D1-5【无缺陷，取证清单】四类状态读取 owner 唯一性

逐个实证「只有一个 owner、一处读」：

- 好感度：`providers.py:1022 _shared_affinity_store` → 委托 `plugins.bot_unified_runtime.build_character_affinity_store`（注释自证"此前自建实例"已收编）；被动感知侧 `__init__.py:7350` 同调该工厂 → **同源**。异常回退分支（`providers.py:1034 DynamicAffinityStore(...)`）是唯一第二实例路径，仅在共享工厂抛异常时出现（fail-open 方向正确，登记为观察项）。
- 心情：`__init__.py:2677 _build_mood_describe` → `build_character_mood_store`；其余消费者 `_mood_valence`/`_mood_willingness_factor` 同调该工厂（不另开连接）→ **同源**。
- 怪癖：`__init__.py:2717 build_character_quirk_store`（进程级 `_QUIRK_STORES` 缓存），注入面唯一读者 `_build_quirks_describe` → **同源**。
- 会话身份：`__init__.py:2752 build_session_identity_store`（`_IDENTITY_STORES` 缓存），唯一注入读者 `_build_identity_describe` → **同源**（注：`_build_identity_describe` 无 enabled 门，而 mood/quirks/reactions 三者各有开关——门数不等，登记 Minor，非缺陷）。
- 称谓偏好：`providers.py:657 _shared_addressing_preferences` + 公开入口 `build_addressing_preference_store`，命令面 `echo.py:3700` 经同一入口读写 → **同源**。

### D1-6【Minor】跨域反向依赖：chat 提示词装配从 assistant 域借话术轮换函数

`chat.py:23 from plugins.bot_unified_runtime.character.daily_assist import pick_variant`（垫片 → `domains/assistant/daily/store/daily_assist.py:332`）。人格主链的提示词装配依赖「每日助理」域的工具函数 = 域边界倒置；池子选择机制因此没有独立归属（与 U9「5 套选择机制」同根，此处只登记归属面）。收口建议：`pick_variant` 迁 `output/user_copy`（或新 `character/copy_rotation`）并由 assistant/chat 两域同向消费。

## D2 称谓与身份的判定统一 — `[x]`

> 本节的一条硬证据是 AST 探针 + 只读 SQL 实跑输出，命令与原文如下（可复跑）：
> ```bash
> # 探针：全量列出装配器/提示词构建的调用点与 kwargs 差分（stdlib AST，不 import 项目包）
> cd ChatBot && ../ChatBot_Runtime/venv/Scripts/python.exe - <<'PY'
> # …见本文末「附录 C：探针脚本原文」
> PY
> # 实测输出（604 文件扫描，24 个调用点）关键行：
> #   build_context  …/capabilities/chat.py:3010  MISSING=['gender_identity','addressing_preference']
> #   build_context  …/runtime/prompt_preview.py:64  MISSING=['group_id','sender_display_name','sender_roles','gender_identity','addressing_preference','sender_profile_note']
> #   build_context  …/domains/ops/admin/debug.py:444  MISSING=[同上六项]
> #   build_context  …/domains/ops/smoke/smoke.py:820 / :984  MISSING=[同上六项]
> #   build_character_context_provider …/pipeline/backend_unit.py:85 MISSING=['mood_describe','quirks_describe','identity_describe','reactions_describe','shared_group_llm_provider']
> #   build_chat_capability …/__init__.py:4642 MISSING=none （唯一生产完整装配）
> #   build_chat_prompt_with_diagnostics …/smoke.py:839 等 MISSING=['admin_roster_text','time_window_section','group_id']
> ```
> ```bash
> # 只读 SQL（mode=ro，不写 Runtime）：会话键形态
> ../ChatBot_Runtime/venv/Scripts/python.exe - <<'PY'
> # SELECT session_id, COUNT(*) FROM conversation_turns GROUP BY …; LIKE 'group:%' / 'group_%'
> PY
> # 实测：conversation_turns rows=4386；LIKE 'group:%' -> 0；LIKE 'group_%' -> 2447
> # 群内真实存在 2447 条发言（例：'group_1076073471_3865067623' 840 条），但没有一行以 'group:' 存储
> ```

### D2-1【P1】称谓规则实现一份、生效一处：五条旁路连判定入参都不给，导致同一消息在旁路被判定成另一种身份

- **实现份数 = 1（正证）**：`build_addressing_context`（`domains/chat_reply/character/addressing.py:41`，锚点 `is_master = scope == "group" and "super_admin" in roles`）是唯一实现；`grep -rn "build_addressing_context" plugins/` 显示调用点只有 `providers.py:131`（Null 装配器）与 `providers.py:374`（File 装配器）两处，均经同一函数 → **规则没有第二份拷贝**（AGENTS #26「chat 链一份/被动好感一份/摘要链一份」的担忧在本域不成立）。
- **缺陷在覆盖面**：AST 探针实跑证明生产之外的 4 个 `build_context` 调用点全部**不传** `group_id / sender_display_name / sender_roles / sender_profile_note`（见上表）。由于 `providers.py:370/375` 的口径是 `session_type="group" if group_id else "private"`：
  - 分歧样本（同一群消息）：生产 → `addressing.py:65` 分支「当前是多人群聊；对方是群友…**禁止称其为漂泊者**」；`/bot` 上下文诊断与 smoke 上下文预检 → `addressing.py:82` 分支「当前是私聊；**对方可视为漂泊者**」。两份 system prompt 的称谓事实直接相反，而这两个分支正是**重启验收清单里被当作证据的输出**（AGENTS 第五部分 + `docs/acceptance-manual.md` §6.6 系列）。
  - 二级路径同时丢 【当前称谓与主角边界】以外的全部身份分区（见 D1-2 表）。
- **偏好读写键同源（正证）**：写侧 `echo.py:3720-3722`（锚点 `session_type = "group" if str(group_id or "").strip() else "private"`）与读侧 `providers.py:369-373`（锚点 `stored_preference, stored_gender = self.addressing_preferences.get(`）键位完全一致（群=群号、私聊=空），并有注释自证。
- **消毒规则的不对称（=「同类未抽干」的那一只）**：用户自设称谓走 `echo.py:3727-3745` 的消毒（锚点 `if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_name):` + `len(name) > _ADDRESSING_NAME_MAX_CHARS`，拒绝控制字符并限长），但
  - 同一 store 的另一写入口 `SessionIdentityStore.set`（管理员 `/bot identity set <昵称>`，`runtime_admin.py:1755-1757`，锚点 `nickname = command_text.removeprefix("set").strip()`）**只有 `.strip()`**，无控制字符拒绝、无长度上限；渲染出口 `session_identity.py:138 render_prompt_section`（锚点 `大家习惯称呼你为「{identity.nickname}」`）原样拼进 system 提示词的【会话身份】分区，**既不 `_sanitize_untrusted_context_text` 也不 `_wrap_untrusted_context_block`**（挂载点 `chat.py:1560-1561`）。
  - 平台侧来源（`sender_card/sender_nickname/sender_title`，`__init__.py:1460-1463` 仅 `str(...).strip()`）同样未过消毒 → 见 D3-3。
  - 结论：**同一条「称谓文本必须先消毒」的边界规则只在用户自设路径生效**（管理员路径与平台路径不生效）。权限门槛降低了可利用性（管理员路径需 admin 角色），但按本席 mandate（「凡某类边界规则一处生效即缺陷」）记账为 P1。
- 改法（复用既有件）：把 `echo.py` 的消毒抽成 `addressing` 模块的公共函数（现成候选：把 `if any(ord(ch) < 32 …)` 两行提为 `sanitize_addressing_text()`），三处写入口共用；渲染侧在 `chat.py:1561/1569` 复用既有 `_sanitize_untrusted_context_text`。
- 验证命令：
  ```bash
  grep -rn "removeprefix(\"set\")" plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_addressing_context.py tests/test_group_context_b03.py \
    --basetemp="$TEMP/u18-d2" -p no:cacheprovider -q
  ```

### D2-2【P1】群摘要「隔离双处」是两份手抄文案，且整条群摘要在生产恒空（分区 0 命中）

- 两份手抄（**不同源**）：
  - 确定性头 `shared_group.py:216-218`，锚点 `发言成员均为群友，不存在唯一主角，不要称任何成员为漂泊者`；
  - LLM 提示词 `shared_group.py:293-296`，锚点 `不得把任何成员塑造成唯一主角或称为漂泊者`。
  - 语义一致但字面两份，无常量、无门；改一处漏一处（与 AGENTS #36「抽 `explicit_allowed_for_session` 单一事实源」同类，那一只已抽、这一只未抽）。
- **实测整条通路 0 命中**：`_fetch_group_rows` 用 `session_id = 'group:<群号>'` 查（`shared_group.py:243-266`，锚点 `WHERE session_id = ?` + `_group_session_id`），而摄取侧写入 `session_id = event.get_session_id()`（`__init__.py:1288`）＝ NoneBot OneBot V11 的 `group_<群号_<发送者>`（同项目自证镜像 `domains/meme/reactions/engine.py:330-334`，锚点 `群=f"group_<gid>_<uid>"`）。只读 SQL 实跑：`LIKE 'group:%' -> 0`、`LIKE 'group_%' -> 2447`（总 4386 行）。
  - 人格面后果（AGENTS #33 只登记了 21:30 推送空转，本席补注入面）：
    1. 【共同会话】分区在生产的**每一次**对话都不渲染（`chat.py:1605-1610` 的 `enabled` 门永假，锚点 `and context.shared_group_context.summary.strip()`）；
    2. 上述两份「群摘要隔离」文案**从未真正生效过一次**——群内容既进不了注入，也就谈不上泄漏，但同样谈不上保护被验证；
    3. 结构性次级问题：`conversation_turns` 的群会话键是 **(群, 发送者) 粒度**，而摘要需求是「忽略发送者的群级公共投影」——即便把键前缀改对，`WHERE session_id = 'group:<gid>'` 也没有对应行，**必须有群级投影键或按 group 前缀聚合查询**才成立。
- **第三条通路核查（用户 mandate 点名的 daily_assist / 提醒督促）**：
  - `daily_assist`（`__init__.py:3401 / :3448` → `summarize_with_llm`）读的是**用户自己的收件箱/清单文件**，不读群历史 → 无「群内容进私聊上下文」的泄漏路径；但它**也没有任何隔离/包裹**：正文 `stripped[:4000]` 原样拼进 user 消息（`daily_assist.py:355`），若用户把群聊内容粘进收件箱，则群内容会以「无群友边界说明」的口径进模型（与两份隔离文案的口径不衔接）。
  - 提醒督促（`domains/schedule/*`）为确定性文案，不调 LLM、不读群历史 → 无泄漏（正证：`grep -rn "llm|model_router|prompt" domains/schedule/*.py` 仅命中 `llm_draft.py` / `timetable.py`）。
  - 21:30 推送与注入共用同一 provider（`__init__.py:3231-3234`，锚点 `build_shared_group_context_provider(config)`）→ **同源 ✓**，但同源同死（见上），并且该调用**不传 `llm_provider`** → 推送侧 LLM 压缩永不启用（AGENTS #33 已登记的存量缺陷，本席复核**仍在**，锚点 `build_shared_group_context_provider(config)` 与 `providers.py:830 shared_group_provider=build_shared_group_context_provider(config, llm_provider=shared_group_llm_provider)` 的参数差）。
- 改法：①两处隔离文案提为模块级常量 `_GROUP_ISOLATION_NOTE` 单点引用；②读侧键改群级（或 `session_id LIKE 'group_<gid>_%'` 聚合，注意需转义群号），并补一条「注入与推送同 provider 同参数」的契约测试；③`daily_assist` 入模文本复用既有 `_wrap_untrusted_context_block`。
- 验证命令：
  ```bash
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_group_digest_push.py tests/test_shared_group_context.py \
    --basetemp="$TEMP/u18-d2b" -p no:cacheprovider -q   # 若测试用同名 'group:' 造数据，即为「测试自证、生产不成立」的实证
  ```

### D2-3【P1】管理员/超管判定：中央 resolver 一份，人格注入面一份，但命令/订阅面存在三份直读 config 的旁路判定

- 唯一 resolver：`domains/chat_reply/policy/roles.py:25 resolve_roles`（锚点 `# 超管自动叠加 admin 角色`），六集合并 + `ROLE_ORDER` 归一；`build_role_settings`（`:53`）把 `bot_admin_user_ids + bot_telegram_admin_user_ids` 合并成 admin 集。写入消息：`runtime/pipeline.py:524`（锚点 `update={"sender_roles": self.role_settings.resolve_roles(message)}`）。
- 人格注入面判定份数 = **1**：`addressing.is_master`（由 `sender_roles` 推）与 `chat.build_admin_roster_text`（`:1353`，只读 `bot_super_admin_user_ids` + `bot_admin_profiles`，**不接受任何用户输入**）→ 【管理团队】分区本身**不可被普通用户伪造（正证）**；`sender_profile_note` 的伪造面已由 `chat.py:1568` 护栏句处理（锚点 `不等同于权限；权限以系统角色为准`），但该句只护「权限」语义，护不住「分区文本注入」（见 D3-3）。
- 旁路直读 config 的三份（角色语义与 resolver 不一致）：
  | 坐标 | 锚点 | 与 resolver 的差 |
  |---|---|---|
  | `__init__.py:4938-4943` | `return user_id in {str(item).strip() for item in config.bot_admin_user_ids}` | 不含 `bot_telegram_admin_user_ids`；不含「超管自动叠加 admin」→ 超管若未同时写进 admin 名单，则被这些命令门拒 |
  | `domains/subscribe/capabilities/subscribe.py:169-172` | `admin_ids = {str(value) for value in (getattr(config, "bot_admin_user_ids", []) or [])}` | 同上 |
  | `domains/subscribe/capabilities/subscribe_v2.py:62-67` | `str(value) for value in (getattr(config, "bot_admin_user_ids", []) or [])` | 同上 |
  - 另有 3 份等价谓词拷贝（同源但重复实现）：`echo.py:53`、`domains/ops/admin/debug.py:1671`、`domains/ops/admin/runtime_logs.py:18` 的 `_is_admin(actor_roles)`。
- 人格面后果：`/bot identity set`（会话身份）等管理员写入口与「管理团队」分区所宣称的权威，和实际命令门**用的是两套判定** → 同一用户在人格上下文里被登记为管理员（config 名单）却在命令面被拒（或反之），bot 说出来的权威关系与真实门不符。收口只需把三处旁路改调 `resolve_roles`（现成中央入口，非新建）。
- 验证命令：
  ```bash
  grep -rn 'config.bot_admin_user_ids' --include=*.py plugins/ | grep -v "roles.py\|config.py" | wc -l   # 期望收口后 0
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_admin_roster_and_roles.py \
    --basetemp="$TEMP/u18-d2c" -p no:cacheprovider -q
  ```

## D3 红线与内容边界的后端执行统一（重点） — `[ ]`

- [ ] D3-1 content_safety / memory_sanitize / affinity 态度文本 / Runtime 人格副本 四处口径同源性与差集
- [ ] D3-2 session_type 必填实传核查 + 群会话键群级语义第二处不一致
- [ ] D3-3 反注入包裹唯一咽喉核查 + 外部内容未过包裹进模型的路径清单
- [ ] D3-4 memory_sanitize 覆盖的写入口清单与漏网入口

## D4 话术池与语气统一（补 U9，不重复） — `[ ]`

- [ ] D4-1 裸 random.choice 的人格面后果：哪些池子「同会话连发不重复」不成立
- [ ] D4-2 人格源 vs Runtime 副本一致性门执法力实证

## 附录 A：引用不重复的上游结论

- U9（`audit-20260920-unify-U9-function.md`）：话术池 5 套选择机制、user_copy 三池 30+ 消费点裸 random.choice —— 本席只补人格面后果。
- U1（`audit-20260920-unify-U1-invest.md`）：摄取面结论直接引用。
- campus 域：U17 在改，本席只读、不下「应如何改」结论。

## 附录 B：发现总表（收口时回填）

| # | 严重度 | 标题 | 坐标 |
|---|---|---|---|
| — | — | 待回填 | — |

## 人格上下文单一装配咽喉收口清单（收口时回填）

- 待回填。
