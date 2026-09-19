# CAP1 实施台账 — 全站卡片品牌胶囊（2026-09-20）

> 席别：CAP1 实施席。用户需求原话（2026-09-20，权威）：
> 「所有图片都需要加上 bot头像、bot名字、bot英文名（可选：功能名）组起来的**胶囊功能组件**」。
> 范围=机器人发出的卡片渲染产物（11 面中的 8 面本席落地；3 面越界登记待裁，见 §六）。
> 本席禁动 `docs/rendering-contract.md`（契约增量并入本文 §五，由主会话在 DOC1 落地后统一并入）。

## 一、三枚输入的单一来源（结论 + 落点）

| 输入 | 单一来源 | 落点（file:line） | 说明 |
|---|---|---|---|
| 头像 | 既有 `bot_avatar_uri`（**未新建第二份路径逻辑**） | `plugins/bot_unified_runtime/domains/render/bot_avatar.py:133` | 优先级=显式配置 `bot_persona_avatar_url` > 进程内登记（on_bot_connect 拉 qlogo 落 `data/avatar/`）> 磁盘兜底发现 > 空。能力侧经 payload `bot_avatar_url` 传入（11 处既有调用点零改动）；mermaid 卡无 payload 通道，bridge 在 `render_mermaid_html` 内直调 `bot_avatar_uri()`（内存登记命中即有图，离线/未连接时回空串=圆点，属既有语义）。 |
| 中文名 | `theme_tokens.BRAND_THEME.display_name`（值=「守岸人」，既有） | `.../card_render/theme_tokens.py:371`（注释钉死于 :368） | bridge 五处 + templates.py 的 `or "守岸人"` 字面量缺省全部改读此处（值不变、行为逐字节等价）。能力侧显式传入的实例名（config.bot_persona_display_name 链路）优先级不变。 |
| 英文名 | **新建常量** `theme_tokens.BRAND_NAME_EN = "Shorekeeper"` | `.../card_render/theme_tokens.py:42`（入 `__all__` :503） | 权威源检索结论：**仓库不存在英文名单一源**——`personas/shorekeeper/identity.md:7`「外文名：英 The Shorekeeper」是人格语料（禁写、且渲染层不应 IO 解析人格文件）；config.py 无英文名字段（`bot_persona_profile_id="shorekeeper"` 是实例选择 id 非展示名）；`templates.py:204` 与 `universal_card.html:1713` 的 "Shorekeeper" 是散落用法（本次消灭）。住 theme_tokens 的理由=品牌身份 token 与 BRAND_ACCENT/BRAND_THEME 同区、 mica_shell/bridge/templates 三条消费链均已 import 此模块。**卡面值取 "Shorekeeper"（省 The）**：与卡面既有用法一致，中文名在前时 "The" 冗余；人格档案全称差异如实记录于此。 |

## 二、胶囊组件本体（一次实现，全站复用）

- **组件唯一实现**：`mica_shell.brand_capsule_css()` / `brand_capsule_html()`（`.../card_render/mica_shell.py:307 / :334`，缺省 CSS 实例 `BRAND_CAPSULE_CSS` :374）。DOM=`<div class="mica-capsule">` [mc-avatar|mc-dot] + mc-name + mc-en + 可选 mc-feature（`· 功能名`）。全部动态文本 `html.escape`。
- **注入点**：
  - 7 张 Jinja 模板：bridge 新增 `_capsule_context()`（`bridge.py:196`），七个 `render_*` 上下文统一注入 `capsule_css`/`capsule_html` 两键；模板 `<style>` 内 `{{ capsule_css | safe }}`、页脚位 `{{ capsule_html | safe }}`，各面只留**摆位规则**（`.capsule-foot` margin 等），旧 `.bot-foot/.bf-*/.cfb-*/.footer-bot-*` 手抄 CSS+DOM 全部退役。
  - media 直拼卡（`domains/render/templates.py`）：`_CARD_CSS` 尾部拼 `brand_capsule_css()`，`bot_footer = brand_capsule_html(...)`。
  - 共享壳 `render_shell` 增可选参 `capsule_html`（`mica_shell.py:511`）：非空时自动附带组件 CSS 并把胶囊拼进外壳尾部——未来经 render_shell 装配的卡零成本接胶囊（现状四直拼卡不走此函数，故该参数当前无消费者，属接入点预置）。
- **降级裁决（头像缺失）**：选**「守」字圆点**而非整体不渲染。理由：①全仓 11 面既有兜底形态即圆点（台账 #21 同源），零新语义；②胶囊首元素不塌陷、版式不跳变；③「不渲染」会让“所有图片必带署名组件”的用户需求在缺头像期整体落空。
- **功能名缺省省略**：`feature_label` 为空 → mc-feature 段整段不产出（不渲染空胶囊、无「未命名」占位）。旧「feature 空则显 Shorekeeper」占位语义作废（英文名已常驻）。
- **版式 token 合规**：圆角 `var(--r-pill)/var(--r-circle)`、玻璃 `GLASS_FOOT+GLASS_EDGE`（theme_tokens 常量拼入，非手抄字面量）、辉光 `var(--glow-accent)` 只作背景层、阴影仅 `var(--mica-shadow-soft)`（两枚白名单内，原各面 `.bot-foot` 用的 panel 档降为 soft——组件是小件，且这是 echo/debug/usage 直拼卡侧唯一允许的档位，取最严集合）、gap 7px/padding 7·12 在刻度、字号 12/13px ∈ TYPE_SCALE、line-height 1.2 在刻度、字重 ≤700、无动画、无 `<meta viewport>`、body 透明不触碰。
- **明暗与对比**：本卡系**不存在暗色主题机制**（透明截图+本命浅色 wash 全仓唯一，`prefers-color-scheme` 零命中）；「亮/暗两套都要成立」按“胶囊文字压在何种聊天背景上都可读”落实=中文名/圆点字用 `--text-main`、英文名/功能名用 `--text-sub`（vis5 门背书的 ≥4.5:1 次级灰），胶囊自带白玻璃底使其与卡面/聊天底色解耦；样张含深色聊天底复合图（§四）。**刻意不用 `--accent-dark` 做文字色**：bilibili 粉等亮 accent 平台派生值对白玻璃面 ~3.4-4.0:1 不达 AA（旧 `.cfb-name` 即此隐患，本组件顺手收口）。

## 三、改动文件清单（本席全部动作）

1. `plugins/bot_unified_runtime/domains/render/card_render/theme_tokens.py` — +BRAND_NAME_EN、中文名来源注释、__all__。
2. `.../card_render/mica_shell.py` — +brand_capsule_css/brand_capsule_html/BRAND_CAPSULE_CSS、render_shell 增 capsule_html 参、__all__。
3. `.../card_render/bridge.py` — +_capsule_context；market/finance/song/affinity/error/mermaid/universal 七个渲染器接胶囊；`or "守岸人"`→`BRAND_THEME.display_name`；mermaid 首次接 `bot_avatar_uri()` 头像通道。
4. `.../card_render/templates/{universal,finance,market,affinity,error,mermaid,song_candidates}_card.html` — 手抄页脚 CSS/DOM 退役、capsule 两键消费（brief 说六份，目录实存七份 `*.html` 全在可写 glob 内，song_candidates 一并收口）。
5. `plugins/bot_unified_runtime/domains/render/templates.py`（media 直拼卡）— 同上收口。
6. 本台账（新建）。

**零破坏线**：payload 契约未变（bot_name/bot_avatar_url/feature_label 三键语义原样）；渲染失败→纯文本兜底路径零接触（bridge 胶囊组装为纯字符串操作不抛）；无新 config 键、无重启才生效的开关分支。

## 四、样张（改动前后 + 明暗 + 无头像降级）——用户裁定素材

目录根：`C:\Users\LancyCelestia\AppData\Local\Temp\cap1-shot\`（全部在 %TEMP%，源码树零写入）。

| 子目录 | 内容 | 验什么 |
|---|---|---|
| `before\` | 改前全套 19 张（19/19 STABLE，实跑日志 `before_run.log`） | 基线：旧页脚各写各的、无英文名常驻 |
| `after_noavatar\` | 改后全套 19 张，头像=空（19/19 STABLE） | **无头像降级形态**：「守」字圆点+守岸人+Shorekeeper+功能名 |
| `after_avatar\` | 改后全套 19 张，头像=内置示意 PNG | 有头像形态（本地优先链路的卡面等价物） |
| `composited\before_{light,dark}\`、`composited\after_noavatar_{light,dark}\`、`composited\after_avatar_{light,dark}\` | 上述三套 × 浅底(#eef1f5)/深底(#171a21) 聊天背景复合 | 透明 PNG 在明/暗聊天底上的胶囊可读性与观感对比 |

六模板+四直拼卡关键张（绝对路径，after_avatar 集）：
- `...\after_avatar\01_universal_bilibili_video.png`（视频彩脚页：胶囊进 pill 容器、无功能名=整段省略实证）
- `...\after_avatar\03_universal_default_search.png`（generic 页脚位）
- `...\after_avatar\05_market_index.png`（股指页脚+功能名「全球股指」）
- `...\after_avatar\09_finance_stocks.png`（金融壳+「个股行情」）
- `...\after_avatar\10_affinity_private.png` / `11_affinity_group.png`（好感度+「好感度」）
- `...\after_avatar\13_song_candidates.png`（点歌+「点歌」）
- `...\after_avatar\14_mermaid_flow.png`（流程图+**首次带头像通道**，离线=守点）
- `...\after_avatar\19_error_card.png`（诊断胶囊+求助文案并列）
- `...\after_avatar\18_media_archive.png`（media 直拼卡，旧 .cfb-* 换统一组件）
- `...\after_avatar\15_help_index.png / 16_debug_llm_setup.png / 17_usage_report.png`（**改动前形态**——三者在越界名单 §六，恰可对照）

## 五、契约与哈希影响面（只报告，未擅动）

### 5.1 建议新增/调整的契约断言（tests/ 不在本席可写面）
- `tests/test_rendering_contract.py`：①新增「七模板渲染产物各含且仅含一处 `class="mica-capsule"`、含 `Shorekeeper`、模板源文件不含 `bf-avatar|cfb-|footer-bot-`」；②英文名单源锁 `BRAND_NAME_EN=="Shorekeeper"` 且模板/桥层零字面量（grep "Shorekeeper" 只许命中 theme_tokens 与注释）；③功能名省略锁（feature 空 → 产物无 `mc-feature`）。
- `tests/test_mica_builders_contract.py`：media_card builder 产物含 `mica-capsule`+`Shorekeeper`；其余三面（help/debug/usage）待 §六 接入后同锁。
- 既有门两处**以模板源码为取材面**（`test_gaps_use_audited_scale`、`test_font_size_floor_12px`），组件 CSS 运行时注入后 mermaid 源码一度零声明——本席以 `.capsule-foot` 保留真实摆位声明（gap:7px/font-size:12px）过门；建议主会话后续把这两门改以**渲染产物**取材（与 `_root_blocks_of` 同法），否则「组件单源化」与「源码级门」长期互相别扭。
- `test_universal_card_visual.py:146` 的 `footer-bot-pill` 分界锁：本席保留该 wrapper 类名（内容换成胶囊），锁不红。
- `test_mica_builders_contract.py:362` usage 卡 `bot-foot` 断言：usage 未接入（§六），锁不红；接入当日该锁需随 §六 一并改。

### 5.2 哈希/常驻门漂移（**本席禁 --write，全部交回主会话**）
- `tests/verify_hashes.py --check` 实跑 11 项 DRIFT，其中 **CAP1 十件**：7 模板 + `theme_tokens.py` + `bridge.py` + `domains/render/templates.py`（`mica_shell.py` 不在 19 件清单内=无漂移项）。第 11 件 `domains/ops/admin/debug.py` **非本席**（他席在飞）。
- `tests/render_hashes.json` PNG 基线（baseline-20260919-paused 19/19 STABLE 那套）：**全站卡片像素已变，19 张必然全漂移**，需重录新基线目录 + `verify_hashes.py --write`——哈希册是他波地盘，等主会话授权统一执行。
- `doc_sync --check` 红、`command_catalog --check` 状态：`docs/auto-facts.md` 工作树已有他席未合流 diff（RouteKind 34/TTS、config 620、topics 77），**非 CAP1**（本席零 config 键/零 topic 改动）。
- 全树 `dev.ps1 -Task lint` 32 错全在 chat_reply/scripts/tests 他席文件（实跑清单：providers/backend_unit/quiet_hours/rate_limit/injection/extract_trigger_words/test_campus_digest/test_kb_wiki_retriever_wiring/test_webui_labels_backend_parity）；**本席四 py 文件 ruff 单跑 All checks passed**。
- `dev.ps1 -Task typecheck` mypy **Success: no issues found in 629 source files**（全树绿，含本席改动）。
- `dev.ps1 -Task runtime-layout` **PASS**（bytecode=absent、generated_dirs=empty；qx.json 完好）。

## 六、越界登记：三张 f-string 直拼卡不在本席可写清单（未动，交主会话裁定）

| 文件（真身路径） | 函数 | 现状 | 接入方案（各两行） |
|---|---|---|---|
| `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py` | `_help_mica_html` | 头部有头像+bot_name+角色 chip，**无英文名**、非统一组件 | import `brand_capsule_html/BRAND_CAPSULE_CSS`；CSS 拼入 `<style>`；页脚（或头部替代位）插 `brand_capsule_html(bot_name=bot_name, avatar_url=bot_avatar_url, feature_label="帮助手册" if ... else "")` |
| `plugins/bot_unified_runtime/domains/ops/admin/debug.py` | `_llm_setup_mica_html` | **完全无 bot 署名件** | 同上，feature_label="接入检查"；注意该卡 `.setup-shell` 尾插 |
| `plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py` | `usage_report_mica_html` | 自带 `.bot-foot` 手抄（无英文名） | 同上，feature_label 用既有入参；改后 `test_mica_builders_contract.py:357-364` 需同步（§5.1） |

三处均已有 `render_root_tokens/shell_base_css` 消费面，胶囊所需的 `--r-pill/--mica-glass-*/--glow-accent/--text-*` token 全部在位，接入零 token 桥接。

## 七、未做事项与原因

1. 上述三直拼卡接入——可写清单外（硬约束），方案已交。
2. `docs/rendering-contract.md` 契约条文更新（新增「品牌胶囊组件」一节+§五.1 门取材建议）——禁改面，§五 为并入稿。
3. 哈希重录/新基线目录——禁 `--write`，清单已交。
4. 英文名走 config 可配键——未做：加键牵动 catalog/.env.example/doc_sync 三处他席在飞面，且英文名当前是品牌固定身份非实例配置；如主会话要可配，建议键 `bot_persona_display_name_en` 另批走。
5. 真机（生产 bot 重启后）验收——本席纯离线；样张即离线等价物。

## 八、复跑命令（本席完工判据实跑记录）

```
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe \
  -m pytest tests/test_rendering_contract.py tests/test_mica_builders_contract.py \
  -p no:cacheprovider --basetemp=../ChatBot_Runtime/cache/pytest_cap1/bf/t -q
→ 190 passed（exit 0）
扩面（visual/typography/phase/samples 门）：507 passed + samples 61 passed（exit 0）
dev.ps1 -Task typecheck → Success: no issues found in 629 source files（exit 0）
dev.ps1 -Task lint → 32 错全为他席文件（本席四 py 单跑 All checks passed）
dev.ps1 -Task runtime-layout → PASS
样张：python scripts/render_card_samples.py --out %TEMP%/cap1-shot/{before,after_noavatar}
     + %TEMP%/cap1-shot/cap1_shot_extra.py（有头像集+明暗复合，脚本在 %TEMP% 不入树）
```
