# 守岸人全域人格、命令文档、统一卡片与金融能力实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 按本计划逐任务执行；每个任务遵循 TDD：先写失败测试，再实现，再运行专项测试与全量验证。禁止代理写 git commit。

**Goal:** 建立私聊/群聊边界清晰的守岸人人格称谓系统、由代码驱动且可在 help 页查看的完整命令教程、统一釉瑚云母视觉契约，并补齐可验证的金融数据能力与文档事实同步。

**Architecture:** 将称谓上下文、命令目录、渲染主题和金融数据分别抽成稳定契约；保留现有能力入口，通过统一适配层接入，避免一次性重写主运行时。UI 采用统一 Card Shell + Theme Tokens + 内容模块，而不是不可维护的巨型条件模板。金融数据按指数、股票、汇率、图表分层，并对非上市公司与延迟/失败数据显式标注。

**Tech Stack:** Python 3、pydantic、pytest、NoneBot/OneBot V11、Jinja2、Playwright 截图后端、现有 Runtime 路径映射与离线 mock 测试体系。

**Spec:** 本任务的用户确认方案、`AGENTS.md`、`README.md`、`COMMANDS.md`、`docs/HANDBOOK.md`、`docs/route-matrix.md`、现有 card_render 代码与能力实现。

## Global Constraints

- 私聊默认允许把当前用户视为“漂泊者”；群聊普通成员一律视为群友，使用群昵称或平台昵称。
- 群聊仅允许配置的超级管理员以 master/漂泊者例外身份参与主角语境；不得把其他群成员称为漂泊者。
- 性别默认 unknown；明确声明或称谓偏好优先于低置信度推断；不得根据头像或昵称硬判；用户可纠正且纠正需持久化。
- 所有命令必须同时进入代码帮助注册表、用户帮助页、`COMMANDS.md`/命令目录和一致性测试；权限、参数、配置、输出、兜底、示例必须可查。
- UI 统一使用守岸人淡蓝/白/深蓝/星空紫本命色；平台色只能在受控主题 token 中派生；统一圆角、间距、宽度、阴影、viewport 与失败纯文本兜底。
- 不伪造 OpenAI 股票价格；仅展示非上市说明或有来源的公开估值，且明确时间与来源。
- 外部数据必须带 source/timestamp/delayed-or-live 状态；网络测试不得成为离线单测依赖。
- 禁止触碰 `ChatBot_Runtime`、真实密钥、归档；代理不执行 git 写操作、不派生代理。

### Task 0: 基线与事实锁定（主代理）

**Files:**
- Create: `docs/superpowers/plans/2026-09-12-shorekeeper-global-audit.md`
- Modify later: `AGENTS.md`, `README.md`, `WORKSPACE_GUIDE.md`, `COMMANDS.md`, `docs/HANDBOOK.md`
- Test later: `tests/test_documentation_consistency.py`

- [ ] 记录当前 git 状态、命令注册数量、模板文件/调用入口、测试基线。
- [ ] 将文档中互相矛盾的 1761+/1766+/1787+ 基线改为自动生成或注明最近实跑证据。
- [ ] 仅把已验证事实写入文档；未知外部数据保持 unknown。

### Task 1: 称谓/人格上下文（代理 A）

**Files:**
- Modify: `plugins/bot_unified_runtime/contracts/character.py`
- Modify: `plugins/bot_unified_runtime/character/providers.py`
- Modify: `plugins/bot_unified_runtime/character/session_identity.py`
- Modify: `plugins/bot_unified_runtime/character/shared_group.py`
- Modify: `plugins/bot_unified_runtime/capabilities/chat.py`
- Modify: `personas/shorekeeper/knowledge/守岸人_核心知识.md`
- Test: `tests/test_addressing_context.py` and relevant existing character tests

**Produces:** `AddressingContext`（scope、preferred_name、gender_identity、gender_confidence、can_use_wanderer_title、is_master）。

- [ ] 先写私聊、普通群友、群内超级管理员、性别 unknown/explicit、用户纠正称谓的失败测试。
- [ ] 实现 scope-aware 称谓解析；群聊普通成员禁止“漂泊者”；超级管理员例外必须由现有角色配置确认。
- [ ] 将称谓上下文注入 LLM context，并防止群摘要把多个成员合并成主角。
- [ ] 对外输出只使用用户可接受称谓；性别线索低置信度只能影响语气，不得变成事实。
- [ ] 运行专项 character 测试与静态检查。

### Task 2: 命令目录、帮助页和文档自动同步（代理 B）

**Files:**
- Modify: `plugins/bot_unified_runtime/capabilities/echo.py`
- Modify: `plugins/bot_unified_runtime/runtime/base_router.py`（仅补缺的 manifest 元数据）
- Modify: `COMMANDS.md`
- Create: `docs/command-catalog.md`
- Create: `tests/test_documentation_consistency.py`
- Modify: `docs/route-matrix.md`, `docs/README.md`

**Produces:** 从 `_HELP_ENTRIES`/路由 manifest 生成或校验命令目录；help 页与文档共享字段。

- [ ] 先写测试：每个帮助条目有 topic/aliases/trigger/function/args/effect/config/permission/scope/output/fallback/examples；文档数量与注册表一致；路由主题无孤儿。
- [ ] 扩展帮助条目字段，但保持旧 help payload 兼容。
- [ ] 把所有命令教程写入用户可读 `docs/command-catalog.md`，并让 `/bot help <模块>` 显示同一真实数据。
- [ ] 明确自然语言触发、昵称触发、`/bot` 子命令、管理员限制、私聊/群聊差异、图片输出和失败兜底。
- [ ] 修正文档中的数量/状态冲突，增加自动生成/校验说明；禁止手工写死别名总数。
- [ ] 运行命令帮助专项测试。

### Task 3: 统一 UI 主题与卡片契约（代理 C）

**Files:**
- Modify: `plugins/bot_unified_runtime/output/card_render/bridge.py`
- Modify: `plugins/bot_unified_runtime/output/card_render/templates/universal_card.html`
- Modify: `plugins/bot_unified_runtime/output/card_render/templates/market_card.html`
- Modify: `plugins/bot_unified_runtime/output/card_render/templates/affinity_card.html`
- Modify: `plugins/bot_unified_runtime/output/card_render/templates/mermaid_card.html`
- Modify: `plugins/bot_unified_runtime/output/card_render/templates/song_candidates.html`
- Create if needed: `plugins/bot_unified_runtime/output/card_render/theme_tokens.py`, `docs/rendering-contract.md`
- Test: existing render tests plus `tests/test_rendering_contract.py`

- [ ] 先写契约测试：统一 viewport、shell radius/width/gap/shadows/font weight、守岸人本命 token、平台主题映射、body 透明、动画范围、失败兜底。
- [ ] 将平台主题从单一 accent 派生升级为显式可审计 token，未知平台安全 fallback。
- [ ] 统一 shell 与 token 注入；内容模板只负责模块内容，不重复定义品牌规则。
- [ ] 为天气、菜谱、历史、占卜、游戏、usage 等已有图片能力提供统一 payload 适配；没有能力或数据时保持纯文字兜底。
- [ ] 运行渲染专项测试；如 Playwright 可用，做真实截图烟测并检查图片非空。

### Task 4: 金融数据能力（主代理，先契约后接源）

**Files:**
- Modify: `plugins/bot_unified_runtime/capabilities/market.py`
- Modify: `plugins/bot_unified_runtime/sources/market_data.py`
- Create: `plugins/bot_unified_runtime/contracts/finance.py`
- Create: `plugins/bot_unified_runtime/sources/stock_data.py`
- Create: `plugins/bot_unified_runtime/sources/fx_data.py`
- Create: `plugins/bot_unified_runtime/capabilities/stocks.py`
- Create: `plugins/bot_unified_runtime/capabilities/fx.py`
- Create/modify: finance card payload/template and tests

- [ ] 先写离线 fixture 测试：指数数字可见；OHLCV、KDJ K/D/J、market cap、currency quote、history、box plot 数据统计正确。
- [ ] 复用现有市场数据接口；新增 source/timestamp/status 字段和字段缺失安全处理。
- [ ] 上市科技公司使用明确 ticker；OpenAI 标记 non-public，不生成股票 OHLC。
- [ ] 支持主要货币及基准货币明确展示；注明中间价/延迟状态，数据源失败可解释。
- [ ] 折线图用于趋势，箱形图用于分布；不要将单日 OHLC 误画成箱形图。
- [ ] 网络源只做可选集成测试，不阻塞离线全量测试。

### Task 5: 文档总账与集成验证（主代理）

**Files:**
- Modify: `AGENTS.md`, `README.md`, `WORKSPACE_GUIDE.md`, `docs/HANDBOOK.md`, `docs/README.md`
- Modify: `docs/route-matrix.md`, `COMMANDS.md`
- Test: full existing suite and new consistency suites

- [ ] 汇总各代理改动，检查是否越过文件域。
- [ ] 更新功能清单、已知问题、命令目录、人格规则、渲染契约、金融限制和运行方式。
- [ ] 运行 `scripts/dev.ps1 -Task test`、`lint`、`typecheck`、`runtime-layout`；命令失败按 systematic-debugging 定位，不做症状性补丁。
- [ ] 用 git diff、rg 和测试输出逐条核对本计划 AC；未验证项明确列为未完成，不宣称完成。

## ABC 并行执行分工（2026-09-12）

### A：人格称谓与主角边界（主代理负责）

目标：实现私聊漂泊者、群聊群友、群内超级管理员 master 例外，并把性别/称谓偏好以可信上下文注入聊天。

文件域：
- `plugins/bot_unified_runtime/character/addressing.py`
- `plugins/bot_unified_runtime/contracts/character.py`
- `plugins/bot_unified_runtime/contracts/__init__.py`
- `plugins/bot_unified_runtime/character/providers.py`
- `plugins/bot_unified_runtime/capabilities/chat.py`
- `plugins/bot_unified_runtime/character/session_identity.py`
- `personas/shorekeeper/knowledge/守岸人_核心知识.md`
- `tests/test_addressing_context.py` 及人格 Prompt 回归测试

验收：私聊可使用漂泊者；普通群友永不被称为漂泊者；超级管理员按现有角色配置成为 master 例外；性别默认 unknown；明确偏好优先；用户纠正可持久化；Prompt 有明确边界指令；旧 provider/mock 接口不回归。

### B：命令、Help、教程和文档自动同步（后续 Agent B 执行指令）

你是 Agent B，只负责命令/文档文件域，不修改人格、UI、金融代码。读取根目录 `AGENTS.md`、`COMMANDS.md`、`docs/HANDBOOK.md`、`docs/route-matrix.md`、`plugins/bot_unified_runtime/capabilities/echo.py`、`plugins/bot_unified_runtime/runtime/base_router.py` 和 `scripts/command_catalog.py`。

必须完成：
1. 盘点 `_HELP_ENTRIES`、路由 manifest、真实 matcher、`COMMANDS.md` 的差异；以代码事实为准。
2. 为每个命令写清：触发方式、别名、函数/入口、参数、默认值、作用、权限、私聊/群聊差异、配置变量、输出形式、网络依赖、失败兜底、示例、关联测试。
3. 保持 `/bot help`、`/bot help <模块>`、`/bot commands` 与 `docs/command-catalog.md` 共用真实注册表，不复制另一套手工数据。
4. 修复文档中的测试基线、完成状态、旧台账和功能现状冲突；不要写未经实跑验证的数字。
5. 新增/完善 `tests/test_documentation_consistency.py`，至少验证：帮助条目必填字段、文档生成结果一致、路由主题无孤儿、公开帮助不暴露管理员项、命令别名无重复冲突。
6. 运行：
   `& '..\ChatBot_Runtime\venv\Scripts\python.exe' scripts/command_catalog.py --write`
   `& '..\ChatBot_Runtime\venv\Scripts\python.exe' scripts/command_catalog.py`
   `& '..\ChatBot_Runtime\venv\Scripts\python.exe' -m pytest tests/test_documentation_consistency.py -q -p no:cacheprovider --basetemp "$env:TEMP\agent-b-docs"`
7. 禁止 git commit；最终报告来源文件、精确改动、测试真实输出、未覆盖缺口和置信度。

### C：UI、卡片和金融数据（后续 Agent C 执行指令）

你是 Agent C，只负责渲染/金融文件域，不修改人格和命令注册表。读取根目录 `AGENTS.md`、计划文件、`plugins/bot_unified_runtime/output/card_render/bridge.py`、`output/card_render/templates/*`、`capabilities/market.py`、`sources/market_data.py`、`capabilities/eat.py`、`capabilities/weather.py`、`capabilities/today_history.py`、`capabilities/divination.py`、`capabilities/epic.py`。

必须完成：
1. 先盘点所有模板和所有 `render_card_png`/`render_*html` 调用；建立渲染契约测试，禁止只改一个模板后声称全局统一。
2. 抽取守岸人本命色 token：淡蓝、白、深蓝、少量星空紫；建立统一 shell width/radius/gap/shadow/font/viewport/body/animation 契约。
3. 建立显式 `PLATFORM_THEMES`，覆盖社交媒体/点歌/音乐平台；未知平台安全 fallback；平台色不得抹掉守岸人本命色。
4. 为天气、菜谱、历史、占卜/塔罗/八字/金钱卦、Epic/Steam/iPad 免费游戏、usage/钱包提供统一 payload→卡片适配；渲染失败必须保留纯文字。
5. 菜谱图片必须有分辨率、宽高比、来源和缓存校验；禁止把搜索结果第一张图无条件当成可信生产素材。
6. 金融能力分开处理指数、股票、汇率和图表；指数必须保留真实数字、source、timestamp、delayed 状态；股票支持上市科技公司 OHLCV、market cap、可选 KDJ；OpenAI 标记 non-public，不生成股票价格；汇率覆盖 USD/EUR/GBP/JPY/KRW/TWD/CNY/HKD/SGD/MOP/AED，并明确基准货币和中间价/延迟。
7. 图表：折线图用于趋势，箱形图用于多日分布；不把单日 OHLC 误当箱形图；无数据时明确显示状态而非伪造 0。
8. 运行专项渲染/市场测试；网络接口只做可选集成测试，离线测试用 fixture；禁止 git commit；报告来源、精确改动、测试真实输出和不可行项。

### 主代理整合命令

```powershell
$py = (Resolve-Path '..\ChatBot_Runtime\venv\Scripts\python.exe').Path
$env:PYTHONDONTWRITEBYTECODE = '1'
& $py -m pytest tests/test_addressing_context.py tests/test_documentation_consistency.py -q -p no:cacheprovider --basetemp "$env:TEMP\abc-contracts"
& $py -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP\abc-full"
& $py -m ruff check .
& $py -m mypy plugins scripts
```

如某条命令失败，先记录完整错误和最小复现，再按 systematic-debugging 找根因；不得以“跳过测试”代替修复。
