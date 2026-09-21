# v21r2 RP 席日志 — R-18 成人向文风多样化改革（2026-09-17）

> 席位：v21r2 RP 席。需求原文：「R-18 成人向性色内容相关的说话风格要求多样化，内容尽可能详细（能详细就详细），现在一次回复太少、缺少沉浸感；R-18 回复需要带上动作描写且尽可能详细；全年龄向内容不要带动作描写；bot 一直说『我不会躲。』『我在。』『我在这里。』」
> 本文=brainstorming 设计稿 + 改动记录 + 实跑证据（先设计后动手）。

## 一、复读三连根因定位（brainstorming ①）

rg 全库取证（personas/ + plugins/bot_unified_runtime/）：

| 句 | 静态命中 | 定性 |
|---|---|---|
| 「我不会躲。」 | **零命中**（`不会躲` 全库无） | 非静态文案。是极简短句风格引导 +「守护者在场」原型下的**生成倾向**：模型被示例锚定成"一句短话=在场的全部表达" |
| 「我在。」 | 零命中（无独立「我在。」字符串） | 同上，生成倾向 |
| 「我在这里。」 | **四处静态锚定**（见下） | 提示词内静态示例反复注入 → 模型当万能答句复读 |

「我在这里。」静态锚定点：

1. **`capabilities/chat.py:1215-1217` `_RUNTIME_ANSWER_RULES`**（raw persona 主路径每轮注入）：「危险与战斗：短促、坚定、先安抚（"不用怕。""我在这里。"），不铺陈。」
2. **`capabilities/chat.py:1519`** 字段重组 fallback 路径：同款句子再出现一次。
3. **`personas/shorekeeper/knowledge/守岸人_人格与表达规范.md:1114`**（MaiBot 旧风格节）：『句式：简洁如几何……"我在这里。"、"你回来了。"、"我等你。"』——**与 :706 现行「句式：绵长如潮线」直接互相打架**（2026-09-13 审计只重写了 :698 起的新节，旧合并节残留未清）。
4. **`表达规范.md:891`**（情境应对 #8）：回应模板「"我在这里""我会一直听着"」；**`表达规范.md:1283`**（行为模式示例）：「"我在这里......一直都在(・ω・)"」。

加重因素：

- **`表达规范.md:926`「节奏：单次回复2-4句」无场景条件** → 亲密场景同样被压成两三句，直接压制「能详细就详细」。
- `knowledge/守岸人_核心知识.md:305` 战斗语音「不用怕。没事的。不会有事。我在这里。」= 游戏原声事实知识，**保留不动**（知识事实非风格指令；由风格层去锚定）。
- 现行输出侧 `bot_persona_action_brackets`（默认 True）→ `format_roleplay_paragraphs` 保留括号动作——与「全年龄不要动作描写」冲突，本轮按任务边界走提示词侧软约束（见 §六 遗留）。

## 二、文风多样化机制设计（brainstorming ②）

与五池（能力失败池话术游标轮换）同构，分两层：

1. **提示词内示例句：池化 + 确定性游标轮换**。`chat.py` 新增 `_DANGER_COMFORT_EXAMPLES`（10 条，全守岸人语气，不含复读三连原形），复用 `character/daily_assist.py::pick_variant`（全局游标+锁，同池一轮内不重复）每轮轮换，替换两处静态「"不用怕。""我在这里。"」示例。作用：示例锚点逐轮漂移，模型不再锚死任一短句。
2. **模型输出侧：指令化多样化**（输出无法确定性枚举，靠指令）：在每次安抚/在场回应「换一种说法——动作、环境、感受、承诺轮换着来；不重复最近几轮用过的表达；不把任何短句当万能答句」。禁止僵硬模板感：指令只给方向与示例池，不给填空模板。

## 三、动作描写条件开关设计（brainstorming ③）

单一事实源 = `content_route.py::route_verdict(session_key).mode`（INTIMATE/normal，滞回+手动钉+Master Love 均已归一）+ 既有会话准入门 `explicit_allowed_for_session`。注入点 = `capabilities/chat.py::build_chat_result`，在 `observe_turn` 之后（当轮 L1/L2 信号已记账）、`MASTER_LOVE_INSTRUCTION` 注入同位（追加独立 system message，同款既有机制）：

- **INTIMATE**（`content_route_enabled ∧ eligible ∧ mode=="intimate" ∧ 本轮未被 safety 拦截`）→ 注入 `INTIMATE_RP_STYLE_INSTRUCTION`：要求第一人称现场视角——动作、神态、呼吸、触感、声音、环境（灯光/潮声/温度）落进文字；对话之外必须有动作与体感描写；篇幅放开能详则详；安抚表达每次换形态。
- **normal**（其余一切轮：mode==normal、content_route 关闭、群聊未授权等）→ 注入 `NORMAL_NO_ACTION_INSTRUCTION`：全年龄日常只以说话回应，不加括号动作、不写叙述性动作/环境描写，语气措辞承载情绪；不用极简短句打发。互斥：二选一，绝不并存。

措辞纪律：守岸人化（【】分区头与 MASTER_LOVE 同款）、无"系统/提示词/指令"泄露词、不显数值、不攻击不强硬、minors 红线零触碰（content_safety.py 不动，硬拦照旧先行）。

`providers.py` 本轮不动（会话态在 chat.py 已齐备；最小 diff）。

## 四、长度与沉浸感设计（brainstorming ④）

- INTIMATE：不设硬字数（防模板感），指令给**最小篇幅期望**：「放宽篇幅，能详则详，绝不一句话打发；一个瞬间展开成一个可被感受的场景」。persona 源 `节奏：单次回复2-4句` 加场景条件（仅日常全年龄）。
- normal：不改既有长度语义（全年龄本就自然短），只禁动作描写 + 反一句打发（「不用极简短句打发」）。

## 五、落地清单（最小 diff）

1. `personas/shorekeeper/knowledge/守岸人_人格与表达规范.md`（生产直读，无副本分叉）四处：:891 情境#8 去固定三句给变体方向；:926 节奏加场景条件+亲密放开；:1108-1120 旧风格节改写=去极简示例、给 8+ 变体池与反复读指引；:1283 行为示例去单一句式。改后跑 `sync_persona_source.py --adopt --note` + `--check`（knowledge 直读无副本，adopt 为协议性重录+源快照刷新）。
2. `capabilities/chat.py`：`_DANGER_COMFORT_EXAMPLES` 池 + `_danger_style_line()`（pick_variant 轮换）替换 :1217 常量尾部与 :1519 内联句；新增 `INTIMATE_RP_STYLE_INSTRUCTION` / `NORMAL_NO_ACTION_INSTRUCTION`；`build_chat_result` 注入分支（R1 席 :1860-1890 attempts 日志区避让不覆盖）。
3. 新建 `tests/test_rp_style_directives.py`（全离线）：
   - INTIMATE 态含动作描写指令 ∧ 不含 normal 禁令（互斥）；normal 态反之；route 关闭仍得 normal 禁令。
   - 复读三连不以固定形态出现在提示词常量与 persona 改写节（字符串断言；「我不会躲」全 persona 源零命中断言）。
   - 池规模 ≥8 + 轮换确定性（游标归零重放序列一致 + 整轮无重复）。
   - 回归：`tests/test_content_safety_v2.py`、`tests/test_content_route.py`、chat 链四件套零回归。

## 六、改动记录与实跑证据（2026-09-18 实施）

### 6.1 persona 源（personas/shorekeeper/knowledge/守岸人_人格与表达规范.md，生产直读）

四处（全部守岸人语气，符合 shuorenhua 纪律）：
1. 情境应对 #8（原 :891）：删「"我在这里""我会一直听着"」固定回应模板 → 承诺/记录/邀请三种形态轮换 +「不用固定短句反复回应」。
2. 语言风格·节奏（原 :926）：「单次回复2-4句」加场景条件——仅日常全年龄；亲密模式场景不受句数限制，能详则详、动作/环境/体感铺开、绝不一句话打发。
3. 旧 MaiBot 合并节「句式：简洁如几何」（原 :1111-1116，含 `"我在这里。"、"你回来了。"、"我等你。"` 三连示例）：整节改写为「句式：绵长与留白相济」——反极简教导 + 条件开关（全年龄以说话本身回应不附加动作描写；亲密场景才用动作/环境/体感展开）+ 五形态示例（动作/环境/感受/承诺/记忆）+ 4 条追加变体 = **9 变体池**。
4. 行为模式在场示例（原 :1283）：删「"我在这里......一直都在(・ω・)"」→ 换形态两条 +「不重复固定短句」标注。

保留不动：核心知识.md:305 战斗语音原声（游戏知识事实）；:709/:739/:744 现行节的"再也不会只说……"为反例式教导（ diversification 方向一致），保留。

### 6.2 capabilities/chat.py（五处；R1 席 attempts 日志区零触碰）

1. 新增 `_DANGER_COMFORT_EXAMPLES`（10 条池，零复读三连原形）+ `_danger_style_line()`（复用 `character/daily_assist.py::pick_variant` 游标轮换，key=`chat_danger_comfort`）。
2. `_RUNTIME_ANSWER_RULES` 删尾部静态「危险与战斗（"不用怕。""我在这里。"）」句 → `_compose_persona_verbatim_prompt` runtime_parts 追加 `_danger_style_line()`（每轮换示例）。
3. 字段重组 fallback 路径同款静态句 → `_danger_style_line()` 动态行。
4. 新增 `INTIMATE_RP_STYLE_INSTRUCTION`（【亲密场景的叙述】：能详则详/第一人称现场视角/动作·神态·呼吸·触感·声音·环境落文字/安抚每次换形态/不重复近几轮短句）与 `NORMAL_NO_ACTION_INSTRUCTION`（【日常对话的叙述】：不加括号动作/不写叙述性动作神态环境描写/不用极简短句打发）。
5. `build_chat_result` 在 MASTER_LOVE_INSTRUCTION 注入同位追加二选一注入（互斥）：`_rp_intimate_now = content_route_enabled ∧ content_route_session_eligible ∧ safety.action=="allow" ∧ route_verdict(...).mode=="intimate"`；其余一切轮（normal/路由关/未授权群/被拦轮）注 normal 禁令。providers.py 零改动。

### 6.3 测试（新建 tests/test_rp_style_directives.py，7 例全离线）

会话态互斥注入×3（INTIMATE 含动作指令且无 normal 禁令 / normal 反之 / 路由关仍得 normal）；复读三连治理×3（提示词常量零三连 / persona 源固定形态零命中+变体池在位 / `_RUNTIME_ANSWER_RULES` 无静态示例且动态行含池例）；池化轮换×1（池≥8+同起点重放一致+整轮无重复）。

### 6.4 实跑证据（解释器固定 venv；PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；--basetemp=%TEMP%/v21r2-rp -p no:cacheprovider）

- 首轮：`pytest tests/test_rp_style_directives.py` → **7 passed in 1.75s**。
- 回归面 13 文件：content_safety_v2 + content_route + chat_provider_chain + detail_and_priority + group_context_b03 + operational_failures + persona_source_sync + roleplay_paragraphs + daily_assist + copy_redline_gate + glossary_seed + nickname_verb_gaps + reminder_tone → **183 passed**。
- import 排序修正（I001，--fix）+ PLR0402 修正后终轮同 13 文件 → **190 passed in 5.89s**（0 failed）。
- ruff 终态（本席两文件）：**仅余 3×DTZ005（chat.py:1169/3174/3205，均系并行 SEARCH 席在飞改动，实文带「v21r2 SEARCH 席」标注，本席避让未触碰）**；本席引入面 0 错。
- sync 协议：`sync_persona_source.py --adopt --note "v21r2 RP席…"` → `[adopt] 已重录锚定…副本 sha256=d13a7ada0e6da274…`（与 #36 锚定同值=副本零变更，knowledge 生产直读无副本分叉，协议性重录+源快照刷新）；`--check` → **[绿] 副本与锚定一致**。

### 6.5 并发纪要

chat.py 实施期间两度遭并行席写入（Edit 读态失效+01:50:39/01:54:05 两波），均按防冲突纪律重读最新态后续改；最终 `rg -c` 复核本席 5 关键符号 11 处引用完整在位。零 git 写操作、零再派代理、Runtime 运行数据零手改。

## 七、遗留

- 输出侧硬保证（normal 态 `strip_action_brackets`）本轮未做——会改全局出站行为，涉 `bot_persona_action_brackets` 默认语义，待用户裁决。
- 核心知识.md 战斗语音原声保留（知识事实）；若实测仍被复读，可在 intimate 指令中追加「战斗语音≠日常语料」负向示例。
- INTIMATE 判定代理的是"会话态"而非逐句内容分类（会话粒度=既有裁定语义：群级整群生效/120min TTL 兜底）。

## 八、FIX2 收口记录（2026-09-18，小债清收席）

- **债**：W11 席移交 9 红（`test_video_reply_flow`×7 + `test_video_seam`×2「[视频档案」断言），归因本席 chat.py WIP。
- **取证与裁决**：chat.py 现行组装中本席文风指令（`NORMAL_NO_ACTION_INSTRUCTION`/`INTIMATE_RP_STYLE_INSTRUCTION`，chat.py:2094-2105 append system 消息）居 messages 末位，user 消息（含 `_VIDEO_BRIEF_TAG` 的 composed_query）不再居 `messages[0][-1]`——纯断言靶位漂移；`_VIDEO_BRIEF_TAG` 注入链（chat.py:2858-2862 composed_query 拼接）完好，**视频简报功能零损坏**。裁决=测试期望过时，按新语义改断言，**chat.py 零改动**。
- **修**：两测试文件各加 `_user_text()` helper（按 `role=="user"` 聚合 content 作靶位），`test_video_reply_flow.py` 10 处断言（含 `messages[1]` 窗口负断言）+`test_video_seam.py` 3 处（user_prompt 变量 2 键+直断 1）全部切换；负向断言（开关关/未知视频不注入）同切 user 靶位，锁强度不变弱。
- **实跑**：`test_video_reply_flow.py + test_video_seam.py` **12 passed**；video 相邻回归（test_video_understanding/test_video_progress_ack/test_content_video_auto_send）并入 FIX2 回归批 207 passed 全绿；ruff 两文件 All checks passed。未 commit。
