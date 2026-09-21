# 席位 U6-CONFIG：统一变量（配置单一 schema）取证审计（2026-09-20）

> **性质**：只读审计席位。零代码/配置改动、零 git 写、零子代理、零真实发送、零重启。
> **对象**：配置面统一性——「配置只有一个 schema 源、一套命名法、一处校验、一个生效时机」。
> **纪律**：`.env` 真实密钥值一律不摘录（只看键名与存在性；值语义取自 `.env.example` / `config.py`）。
> **方法**：五道机器门实跑 + AST 全字段枚举 + 全树标识符索引用法 + 装载实弹探针（合成载荷，不读 `.env`）。
> **快照口径**：行号 = 2026-09-20 本席位取证时刻。每条发现附**锚点字符串**，行号漂移时以锚点重定位，**禁止按行号盲改**。
> **上轮审计关系**：`docs/design/audit-20260919-unify-wave.md` 对象=渲染收口 + WebUI 前端，与本席配置面零重叠；本席仅在 §1.5 引用其 P0-2 复核结果。
> **取证产物**（全部落 `%TEMP%`，源码树零残留）：`u6_inventory.py`/`u6-config-inventory.json`（616 字段全清单 + 交叉表）、`u6_getattr_check2.py`/`u6-config-getattr2.json`（873 处 getattr 比对）、`u6_timing_check.py`/`u6-timing.json`（热更/重启白名单）、`u6_naming_check.py`/`u6-naming.json`（命名族 + 校验覆盖）、`u6-ruff.txt`、`u6-mypy.txt`。

---

## §0 取证计划与进度

| 项 | 范围 | 状态 |
|---|---|---|
| 1 | 五道机器门实跑 + 逐条归因（在飞面 vs 本域真缺陷） | ✅ §1 |
| 2 | config.py 全字段清单化 + 四张交叉表 | ✅ §2 |
| 3 | 命名族一致性 | ✅ §3 |
| 4 | 生效时机统一 + validator 覆盖面 | ✅ §4 |
| 5 | 门控层级统一（主门∧分门 / 缺省 True 的门） | ✅ §5 |
| 6 | 环境装载链与 int/str 装载陷阱全族 | ✅ §6 |
| 7 | 打码与安全配置面 | ✅ §7 |
| 8 | 配置与运行时状态边界（路径重映射） | ✅ §8 |
| 9 | 源码树零残留自查 + 单一 schema 收口清单 | ✅ §9/§10 |

**总判定**：配置面**不是单一 schema**。实测同时存在七套「值来源」：①`Config` 字段（616，唯一有登记门的一层）②下游嵌套 pydantic 模型的影子缺省（`RateLimitSettings`/`QuietHoursSettings` 等，键名另起一套，§4.1/§4.4）③`getattr` 兜底字面量（873 处，其中 **168 处 ≠ 声明缺省**，§4.2）④`os.environ` 直读（插件内 23 键 31 处，**NoneBot 不把 `.env` 写进 `os.environ` → 这条通道对 `.env` 恒空**，§6.0）⑤driver config 直读旁路键（`BOT_MUSIC_MODE`）⑥生产 `.env` 里 6 个无字段幻影键（§2.2a）⑦代码里硬编码的本机绝对路径缺省（`kb_wiki.py:58`）。
四条 mandate 的当前成立度：**「一个 schema 源」不成立（七源）；「一套命名法」有 9 类违例（§3）；「一处校验」不成立（65/616 有校验、`Field(` 全树仅 1 处，§4.3）；「一个生效时机」不成立（72/616 有声明，同键还出现三种优先级序，§4.4/§6.0）**。
**严重度分布**（口径=本文件内逐条标记实数，一条可涵盖多键；`grep -o '\*\*P1\*\*' 本文件 | wc -l` 等三条命令可复算）：**P0 = 0｜P1 = 13 条｜P2 = 17 条（含 §3 命名族 4 条）｜P3 = 13 条（含 §3 命名族 5 条）**。P1 全部具备「实跑输出或全树索引」级证据；本席未跑生产真机，凡「现网未见实害」均标注为**证据缺失**而非判定通过。

---

## §1 机器门实跑与逐条归因

固定前缀：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，解释器 `../ChatBot_Runtime/venv/Scripts/python.exe`（3.12.10）。

### 1.1 三门（原文输出）

```
$ python scripts/doc_sync.py --check            # 无输出
EXIT=0
$ python scripts/command_catalog.py --check
command catalog is current (77 topics)
EXIT=0
$ python tests/verify_hashes.py --check         # 禁 --write
EXIT=0
```

判定：三门全绿。`docs/auto-facts.md` 机器口径（实读）：模板 7 / RouteKind 34 / 帮助 topic 77（重名 0）/ 测试文件 423 / **config.py `bot_*` 字段 616** / 哈希清单 19 项。
**与交接书差异（如实记录，不判定归属）**：`HANDOFF-V21R5-20260920.md` §二/§六 记「verify_hashes 1 DRIFT（echo.py=TTS 在飞）」，本席 09-20 实跑为 **0 DRIFT**；`AGENTS.md` 头部口径「529 字段」为旧值（机器册 616）。→ **AGENTS.md 正文与机器册互相矛盾且无门覆盖**（收口清单第 14 条）。

### 1.2 ruff（dev.ps1 同口径，缓存出树）

```
$ ruff check --cache-dir ../ChatBot_Runtime/cache/ruff-u6 --no-cache --output-format=concise .
...
Found 51 errors.
[*] 31 fixable with the `--fix` option (11 hidden fixes can be enabled with the `--unsafe-fixes` option).
```

分布归因（53 行原文已存 `%TEMP%/u6-ruff.txt`）：

| 归属 | 数量 | 明细 |
|---|---|---|
| `.tmp-test/` 源码树基座残留 | **33** | I001/F821/F841/ISC004/PLW1510 + 2 条 invalid-syntax（`test_run_code_debug_reports_sy0/bad.py` 是测试故意造的坏样本）。= `HANDOFF-V21R5` §五「`.tmp-test` 清理待占用进程释放」+ 上轮审计 P2-16（`.gitignore` 与 ruff exclude 双漏）**仍未修** |
| `plugins/**` 真文件 | **9** | 全为 I001 import 排序：`control_plane/dispatcher.py:157`、`domains/chat_reply/capabilities/chat.py:1`、`domains/chat_reply/pipeline/backend_unit.py:3`、`domains/chat_reply/policy/{quiet_hours,rate_limit}.py:1`、`domains/chat_reply/security/injection.py:1`、`domains/link_parse/capabilities/content_parser.py:7`、`domains/music/capabilities/music.py:262`、`sources/__init__.py:1` → 归属 v21r4 垫片退役/迁移波（RWC5-b/RWC6-b 改 import 路径后未复跑 `ruff --fix`），**非配置域** |
| `tests/**` | **9** | 全 I001（同波次改 import 的测试件），**非配置域** |
| `plugins/bot_unified_runtime/config.py` | **0** | 本域零 ruff 债 |

### 1.3 mypy（dev.ps1 同口径）

```
$ python -m mypy --cache-dir ../ChatBot_Runtime/cache/mypy-u6 --explicit-package-bases --ignore-missing-imports plugins
plugins\bot_unified_runtime\runtime\capability_protocols.py:1273: error: Module "plugins.bot_unified_runtime.sources" has no attribute "web_search"  [attr-defined]
Found 1 error in 1 file (checked 618 source files)
```

唯一红 = 上轮审计 **P0-2 至今未闭环**（锚点 `from plugins.bot_unified_runtime.sources import (` + 注释 `RET2B-PREP: web_search 垫片挂起`）。本席补**运行期实弹证据**（上轮只证到 mypy）：

```
$ python -c "from plugins.bot_unified_runtime.sources import web_search"
IMPORT FAIL -> ImportError cannot import name 'web_search' from 'plugins.bot_unified_runtime.sources'
```

可达性：`capability_protocols.py:1874` 注册 `handlers.register("search.web", _handle_search_web)`，`:1230` 在无注入 provider 时构造 `_WebChainAsSearchProvider`，其 `.search()` 在 `:1273` 触发上述 ImportError。**非配置域缺陷，移交后端席**（本席只登记不修）。全树 618 文件中 `config.py` 零 mypy 错。

### 1.4 dev.ps1 四门禁与 scoped 门实跑

`tests/test_doc_sync_gates.py`（catalog 覆盖 + route-matrix）与 `tests/test_cross_validation_gates.py`（doc_sync/哈希/性能常驻门）是本席主责门禁，实跑（仅 scoped 件，禁全量）：

```
$ python -m pytest tests/test_doc_sync_gates.py tests/test_cross_validation_gates.py \
    -p no:cacheprovider --basetemp="$TEMP/u6-audit-gates1" -q
......                                                                   [100%]
6 passed in 2.05s
```

判定：门禁本身**全绿且与代码实况一致**（本席实测 catalog 漏登记 = 0，与 `KNOWN_MISSING=∅` 相符）。但门的执法面只覆盖「正向登记」，§1.5 列出四处它管不到的缺口。

### 1.5 门禁自身的执法面缺口（本域真缺陷，非在飞）

`tests/test_doc_sync_gates.py::test_config_catalog_covers_config_fields` 只做**单向**覆盖（`config.py 字段 − 已登记 − KNOWN_MISSING`），且 `KNOWN_MISSING = frozenset()`（`:53`）：

- ✅ 方向一（有字段未登记）被守：本席实跑 ①表 = **0 漏登记**，与门禁一致。
- ❌ 方向二（登记/拨键却无字段）**完全无门**：`stale` 断言只核 `KNOWN_MISSING − fields − registered`，对「catalog/`.env` 有而 Config 无」零检查。本席实测 catalog 侧 32 条（多为 A25/§D 提取伪影 + 1 条真旁路键）、**`.env` 侧 6 条真幻影键**（见 §2.2）。
- ❌ `.env.example` 与 Config 的双向一致性**无任何门**（本席实测 110 字段在模板中零出现，见 §2.1）。
- ❌ `_normalize_catalog_key`（`:266`）把 A25 的第三方键 `MAIL_BOTS`/`TELEGRAM_BOTS`/`MCP_SERVERS` 归一成 `bot_mail_bots`/`bot_telegram_bots`/`bot_mcp_servers`，人为造出「Config 不存在的键」——同一函数被本席复用，故 §2.2 的 catalog 侧 32 条中 25 条是该算法伪影，**已在下表逐条区分**（诚实口径）。

---

## §2 配置键全量清单化与四张交叉表

**基数（脚本实跑，非人工清点）**：`config.py` 注解字段 **616**；`path_fields` 重映射元组 **55**（去重 55，**零拼写错误、零幻影条目**）；文件列表二次解析循环 4 项；catalog 表内可识别键 **648**；`.env.example` 生效键 514 + 注释键 6；生产 `.env` 生效键 345（去重后 `BOT_*` 唯一键 336）；`.env.prod` 生效键 6；被扫描 `.py` 文件 **1079**。

### 2.1 表①：config.py 有 → 登记面缺

| 交叉 | 数量 | 判定 |
|---|---|---|
| 有字段 → **catalog 未登记** | **0** | ✅ 门禁守住（`KNOWN_MISSING` 空） |
| 有字段 → **`.env.example` 未出现（含注释形态）** | **110** | ❌ 模板不是完整 schema 镜像；无门 |

110 条整表在 `%TEMP%/u6-config-inventory.json → table1_missing_from_env_example`。族内分布（脚本实测，**同族一半在模板一半不在** = 漂移实锤）：

| 族 | 族内键数 | 模板缺 | 缺的具体键 |
|---|---|---|---|
| campus | 6 | **6（整族零登记）** | `bot_campus_{enabled,self_ids,group_whitelist,notify_qq,push_bot_id,db_path}` —— 生产 `.env` 却已拨 5 条（实测 `grep -o "^BOT_CAMPUS_[A-Z_]*" .env`） |
| media_archive | 9 | 6 | `_db_path/_dir/_max_file_mb/_per_message_limit/_summary_enabled/_video_frames`（台账 #28 声称「config.py+catalog+.env.example 同步」，**六键不成立**） |
| poke | 13 | 8 | `_enabled/_probability/_private_cooldown_seconds/_group_cooldown_seconds/_group_text/_private_text/_reply_enabled/_admin_bypass`（台账 #35 声称「catalog+env.example 同步」，**八键不成立**；同族 `_reply_mode/_poke_back/_affinity_*` 在模板内 = 族内不一致） |
| subscribe | 20 | 8 | `_global_concurrency/_jitter_ratio/_lease_seconds/_min_interval_seconds/_outbox_interval_seconds/_platform_concurrency/_retry_base_seconds/_retry_cap_seconds` |
| master_love | 2 | **2（整族零登记）** | `_enabled/_admins`（生产 `.env` 已拨 2 条） |
| api_key 槽位 | 18 | 10 | `_aiprc_gemini/_aiprc_grok/_axonhub/_qianqianye_night/_starapi/_toolcode_{gemini,gpt,grok}/_umi_claude/_umi_group3` |
| daily_assist | 6 | 1 | `bot_daily_assist_enabled`（台账 #32 声称「6 键入 config.py+catalog+SETTABLE+.env.example」，**该键不成立**） |
| 其余 | 41 | 41 | affinity/mood/quirks/reflection/reminder/news/notes/market 与 finance、digest、decision_engine_mode、saucenao、vision、randpic、reactions 相关键 |

**改法（收口动作，见 §10 第 9 条）**：`.env.example` 由 `Config.model_fields` 机械生成「全键 + 代码缺省 + 一行作用」，人工维护降为只写作用说明；新增门 `test_env_example_covers_config_fields`（双向，含注释形态豁免清单）。

**验证命令**：
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe \
  /c/Users/LancyCelestia/AppData/Local/Temp/u6_inventory.py
# 输出行：table1_missing_from_env_example: 110 / table1_missing_from_catalog: 0
```

### 2.2 表②：登记面/环境面有 → config.py 无（幻影键，拨了不生效）

**(a) 生产 `.env` 幻影键 6 条——最高危，全部实跑取证（只看键名）**

| 键（`.env` 生效行，实测 `grep -c "^K=" .env` = 1） | 语义 | 根因 | 严重度 |
|---|---|---|---|
| `BOT_GROUP_DIGEST_ENABLED` | 群摘要总开关 | `config.py:357` 注释自认：该字段**已作为死字段删除**，真开关是 `bot_shared_group_context_enabled`；**但 `.env` 里那一行从未清理** → 管理员照册/照旧笔记拨它 = 零效果 | **P1** |
| `BOT_SUBSCRIBE_DIGEST_HOUR` | 订阅摘要时刻 | v2 订阅改造后旧旋钮残留，Config 无字段 | P2 |
| `BOT_SUBSCRIBE_DIGEST_MINUTE` | 同上 | 同上 | P2 |
| `BOT_SUBSCRIBE_LIVE_POLL_SECONDS` | live 轮询 | 同上（现役等价键 `bot_subscribe_poll_interval_seconds`） | P2 |
| `BOT_SUBSCRIBE_PLAYWRIGHT_POLL_SECONDS` | playwright 轮询 | 同上 | P2 |
| `BOT_POTCCV_API_KEY` | 09-17 上车渠道的 key 槽 | **18 个 `bot_api_key_*` 槽位里唯独 potccv 没有字段**：`.env.example` 亦无（实测 0 命中）。解析链 `model_router.py:482` `environ.get(env_name) or getattr(config, env_name.lower(), "")` → 只有 `os.environ` 已装载的路径能取到；**smoke/离线装配/任何不经 dotenv 注入 `os.environ` 的装载路径恒取空** = H3 事故（「registry 引用 env:X 但字段缺失 → 恒判 config_missing」）的同族第四次复发 | **P1** |

**(b) catalog 侧 32 条命中，逐类区分（诚实口径）**

- **25 条 = 提取器算法伪影**：A25「非 Config 键」与 §D「校验规则码」表的第 1 列被 `_normalize_catalog_key` 强加 `bot_` 前缀，例 `MAIL_BOTS→bot_mail_bots`、`MCP_SERVERS→bot_mcp_servers`、`LOCALSTORE_USE_CWD→bot_localstore_use_cwd`、`BOT_PERSONA_FILE_MISSING→bot_persona_file_missing`。这些**不是缺陷**，但暴露门禁函数会把「非 Config 键」伪装成 Config 键 → 反向（stale）门一旦上线必须先排除 A25/§D 两表（收口清单第 9 条）。
- **6 条 = 设计上的非-Config 键，已在 A25 正确登记**：`TELEGRAM_{PROXY,WEBHOOK_URL,BOTS}`、`SQLALCHEMY_DATABASE_URL`、`MCP_{CACHE_TTL,TOOL_TIMEOUT}`。
- **1 条 = 真旁路旋钮**：`BOT_MUSIC_MODE`——A20 已注明「运行时专属键」，`config.py:485` 注释「运行时 `BOT_MUSIC_MODE` 覆盖此处」，SETTABLE_KEYS 里也是它（唯一幻影热更键）。→ 一个能改生产行为的键**只活在 driver config，不在 pydantic schema 里**：无类型、无缺省、无校验、不进 `--check` 面。判定 **P2（schema 旁路）**。

**验证命令**：
```
../ChatBot_Runtime/venv/Scripts/python.exe -c "
import json;d=json.load(open(r'C:/Users/LancyCelestia/AppData/Local/Temp/u6-config-inventory.json',encoding='utf-8'));print(d['table2_phantom_dotenv'])"
# ['bot_group_digest_enabled','bot_potccv_api_key','bot_subscribe_digest_hour','bot_subscribe_digest_minute','bot_subscribe_live_poll_seconds','bot_subscribe_playwright_poll_seconds']
```

### 2.3 表③：路径语义键未进 `path_fields`（台账 #1 写源码树事故的根因面）

正则 `(^|_)(db_path|dir|file|path|root)($|_)` + 缺省以 `"data/` 开头 双条件命中 13 条，剔除 6 条正则伪命中（`bot_file_export_via_queue`、`bot_file_read_max_chars`、`bot_{media_archive_max_file_mb,meme_library_max_file_bytes,randpic_max_file_mb}`、`bot_runtime_data_dir`=根本身），**真路径语义 7 + 幻影路径键 1 + 列表型路径 1**：

| 键 | 声明缺省 | 消费点（锚点） | 是否落源码树 | 判定 |
|---|---|---|---|---|
| `bot_card_asset_dir` | `""` | **字段零消费**；真消费点 `card_render/bridge.py:234` 与 `render_backends.py:135` 各写 `os.getenv("BOT_CARD_ASSET_DIR")` | 不落树，但**Config 完全管不到** | **P2**（双源 + 幻影字段；render 域=前端在飞独占面，本席只读登记） |
| `bot_daily_assist_dir` | `"data/daily_assist"` | `domains/assistant/daily/store/daily_assist.py:38` → `build_runtime_data_path(config, raw)` | 生产安全（消费点二次兜底），**schema 层不兜底** | **P2**（同类两制） |
| `bot_credentials_file` | `""` | `domains/core/credentials/credentials.py:218` → `FileCredentialStore(file_path)` 裸字符串 | **按项目惯例填 `data/credentials.json` 即写源码树** | **P1**（台账 #1 第 4 次复发根因，且是**凭据文件**） |
| `bot_user_profiles_file` | `""` | `domains/chat_reply/character/relationship.py:169` 裸字符串 | 同上（写读用户档案） | **P1**（同类） |
| `bot_holidays_file` | `""` | `domains/chat_reply/character/temporal.py:378` `load_holiday_table(...)` | 只读，但 CWD 依赖 | P3 |
| `bot_kb_wiki_root` | `""` | `domains/location/knowledge/kb_wiki.py:57-58`：`or r"D:\Coding\Crawl Wiki"` | 不落树，但**代码里硬编码本机绝对路径当缺省**，绕开 schema | **P2**（配置值住在代码里；非可移植 + 「一处缺省」违例） |
| `bot_tts_gptsovits_dir` | `""` | `domains/media/capabilities/tts.py`（在飞禁改面） | 只读基准目录 | 只登记（归属 TTS 席） |
| `bot_food_image_dir`（**幻影键，Config 无字段**） | — | `domains/food/capabilities/eat.py:219` 与 `scripts/clean_food_gallery.py:204` 各自 `getattr(config,...)` 兜底 `"data/food_images"`，docstring 自认「失败退回相对路径」 | 兜底路径 = 源码树 | **P1**（写盘点实锤 + 两处兜底各写一份） |
| `bot_randpic_dirs`（`list[str]`，`_parse_id_list` 解析但**不重映射**） | `[]` | `domains/meme/capabilities/randpic.py:125` 裸字符串 | 只读图库目录，CWD 依赖 | P3 |

### 2.4 表④：全树零静态消费方的键（58 条，三分类）

脚本口径 = AST 属性名 + `"bot_*"`/`"BOT_*"` 字符串常量在 1079 个 `.py` 中的命中（排除 `config.py` 自身）。**58 条全部已登记在 catalog**（即册上「可配」而代码不读）。

| 类 | 数 | 清单 | 判定 |
|---|---|---|---|
| **A. `env:` 引用槽位**（按名动态 getattr，静态不可见） | 18 | `bot_api_key_{qianqianye,qianqianye_night,deepseek_qian,deepseek_official,axonhub,aiprc,aiprc_gemini,aiprc_grok,umi_group1,umi_group2,umi_group3,umi_claude,hcn,zhipu,toolcode_gpt,toolcode_gemini,toolcode_grok,starapi}` | 机制在 `model_router.py:483`；**缺不变量校验**（§4.3）→ 槽位族本身不算死键 |
| **B. 动态拼名消费**（f-string 造键） | 15 | `bot_subscribe_platform_*`×7（`subscription_store_v2.py:69` `getattr(config, f"bot_subscribe_platform_{name}", True)`）、`bot_web_search_{you,tinyfish,langsearch}_{api_key,endpoint}`×6（`search_api.py:462/467` f-string）、`bot_search_acg_{bangumi,moegirl,bilibili}_enabled`×3（`webui_knowledge.py:513` f-string） | 不算死键，但**静态审计不可见 + 兜底即语义**：新平台名拼错/未建键 = 静默 `True`（该平台开关永不可关）→ **P2** |
| **C. 真死键（无任何消费路径，含动态）** | **25** | ①多实例共享整族 3：`bot_share_{enabled,groups,read_only}`（AGENTS 第二部分仍描述「`bot_share_groups` 用 "A and B" 名字」，实际零消费 = **文档宣称的能力不存在**）②prompt audit 族 6：`bot_prompt_{audit_enabled,audit_include_messages,audit_include_untrusted_context,audit_retention_days,execution_mode,approval_digest}`（`config.py:815` 注释称「仅 prompt_preview CLI 使用」，实测该 CLI 只读 `bot_prompt_audit_dir` 一键）③`bot_runtime_alias_enabled`、`bot_runtime_default_persona` ④`bot_poke_admin_bypass`、`bot_moegirl_max_candidates`、`bot_randpic_max_file_mb`、`bot_search_acg_max_per_source`、`bot_subscribe_card_enabled`、`bot_subscribe_jitter_ratio`、`bot_card_asset_dir` ⑤别名三胞胎 `bot_search_{you,tinyfish,langsearch}_api_key`（与 `bot_web_search_*` 同义双键，只有 tavily 那份有消费点 `eat.py:283`）⑥**门控类 3**：`bot_schedule_enabled`（主门零消费）+ `bot_schedule_{timetable,delivery}_enabled` ⑦**行为类 1**：`bot_rate_limit_chat_sender_min_interval_seconds`（升 P1，见 §4.1） | **P1×2 / P2×7 / P3×16** |

**关键交叉证据（⑦ 与 ⑥）**：见 §4.1、§5.2——「主门零消费而分门有消费」= 层级倒挂。

---

## §3 命名族一致性（一套命名法）

基数（脚本 `%TEMP%/u6-naming.json`）：`_enabled` 后缀 **120** 键；布尔字段共 **156**（缺省 True 93 / False 63）；即 **36 个布尔开关不叫 `_enabled`**；`_seconds` 38 + `_timeout_seconds` 24；`_db_path` 28 + `_path` 2 + `_dir` 14 + `_file` 12；`_max_*` 家族散成 **34 种不同后缀形态**。

| # | 严重度 | 坐标 | 锚点 | 根因 | 证据 | 改法 | 验证 |
|---|---|---|---|---|---|---|---|
| U6-P2-N1 | P2 | `config.py:530-531`、`:1182-1190`、`:712-713`、`:59` | `bot_meme_library_group_allowlist` / `bot_meme_library_group_denylist` | 「名单」两套词并存：`_whitelist/_blacklist`（campus、group_digest、content_route、daily_assist 四族）vs `_allowlist/_denylist`（meme_library 一族）+ `_host_allowlist`（control_plane） | 脚本枚举 8 键命中，语义完全同类（群/主机准入名单） | 新键一律 `_allowlist/_denylist`（或直接 `_include/_exclude`），存量两两配对处加别名读取器 + 一次改名波（属命令/键改名，需用户裁决，见 §10 第 15 条） | `python …u6_naming_check.py` 复跑，命中族数应 2→1 |
| U6-P2-N2 | P2 | `config.py:76`、`:406` | `bot_gscore_max_retry: int = 5` / `bot_schedule_delivery_max_retries: int = 3` | 「重试上限」单复数分裂 | 全树仅此二键分别命中 `_max_retry`/`_max_retries` 后缀 | 统一 `_max_attempts`（与既有 `bot_send_queue_max_attempts` 同族同义，该族已是第三种写法）→ 三写法收一 | 同上脚本，`_max_retry*`/`_max_attempts` 族计数 |
| U6-P2-N3 | P2 | `config.py:599` 与全树 | `bot_media_archive_min_role: str = "super_admin"` | 「角色门槛」只此一键立了 `_min_role` 名；同类语义散落成 名单键（campus/daily_assist/content_route）、`bypass_roles`（rate_limit/quiet_hours）、硬编码（media_archive 之外的归档面） | `_min_role` 族计数=1；`_ids`/`whitelist` 族承载同一意图 | 定 `_min_role` 为标准形，新能力一律用它；存量登记进「语义同族对照表」（catalog §0 增一节） | `grep -rn "_min_role" plugins/bot_unified_runtime/config.py` 计数上升即收口进行中 |
| U6-P3-N4 | P3 | `config.py:34-977`（族清单见 §2.4 表 B） | `bot_search_{tavily,you,tinyfish,langsearch}_api_key` vs `bot_web_search_{…}_api_key` | 同一凭据两套前缀（`search_` 与 `web_search_`），仅 tavily 的 `search_` 形态有消费点（`eat.py:283`），另三键零消费 | §2.4 C 类 ⑤ 三条 | 保留 `bot_web_search_*`（引擎实际读取族），`bot_search_*` 三键删除或降级为「注册表 env: 槽位」并进 A25 型专表 | 复跑 inventory，C 类计数应下降 |
| U6-P3-N5 | P3 | `config.py:44-45`、`:113`、`:82` | `bot_runtime_group_command_prefix` / `bot_runtime_admin_prefix`；`bot_admin_user_ids` / `bot_super_admin_user_ids` | 前缀两键值恒同（都 `/bot`）却各自漂移；`_user_ids`（QQ 号）与 `bot_telegram_admin_chat_ids`（会话号）同后缀混装两类 ID | 声明缺省同为 `"/bot"`；`_ids` 族 10 键跨 QQ/群/chat 三种域 | ID 族按平台分段（`bot_qq_*_ids` / `bot_tg_*_ids`）或至少在 catalog 标注域；前缀合并为 `bot_command_prefix`（改动=破坏性，需裁决） | inventory 交叉表 |
| U6-P3-N6 | P3 | `config.py:179-183`、`:907-913`、`:856-867` | `bot_tone_*`、`bot_reply_*`、`bot_chat_fast_*` | 表达长度旋钮三套前缀：`bot_tone_message_count_limit`、`bot_reply_*_max_messages`、`bot_chat_fast_max_*`；其中 5 个 `bot_reply_*_max_messages` 缺省全 `0`（=未启用）却无一处说明 0 的语义 | `lit` 比对脚本命中；catalog 对 0 语义无描述 | 统一 `bot_reply_*` 一族并在 catalog §0 增「0=关闭/0=不限」的族级约定表 | `grep -n "max_messages" docs/config-catalog-full.md` |
| U6-P2-N7 | P2 | `config.py:271`、`:272`、`:936-939`、`:672-678` | `bot_temporal_enabled` / `bot_timezone` / `bot_quiet_hours_timezone` | 时区两套键（全局 `bot_timezone` 与安静时间专用 `bot_quiet_hours_timezone`，缺省都是 `Asia/Hong_Kong`）；台账 #6 已记「cron 用系统本地时区」= 第三套时区来源 | AGENTS 台账 #6 + 两键并存 | 收口为「单一 `bot_timezone` + 例外键显式注明覆盖理由」，并把 cron 面纳入同一 tz（原台账 #6 的修法） | `grep -rn "tzlocal\|astimezone()" plugins | wc -l` 与文档口径核对 |
| U6-P3-N8 | P3 | 概率族 6 键（`_probability`） | `bot_group_chat_auto_reply_probability: float = 0.004` 与 `bot_poke_probability: float = 1.0` | 同后缀跨三个数量级（0.004/0.05/0.15/0.2/1.0/1.0）且**全无 [0,1] 校验**（§4.2 探针：`BOT_MARKET_TIMEOUT_SECONDS=-5` 之类照样通过） | 脚本枚举 + §4.2 实弹 | 族级 `Field(ge=0, le=1)` 或统一校验器 | §4.2 探针命令 |
| U6-P3-N9 | P3 | `config.py:115-120` | `bot_persona_display_name: str = "报存"` | schema 缺省是**错字/无意义串**（应为「守岸人」）；14 个消费点各自兜底成 `''` 或 `'守岸人'`（§4.2 漂移表最长行） | `config.py:114` 声明 + getattr 比对 14 处 | 缺省改 `"守岸人"`（人格资产，改前读 AGENTS 第 8 条），消费点兜底全部删净只留 schema 一处 | §4.2 命令复跑应零命中该键 |

**正面记录（勿再怀疑）**：`_via_queue` 四键（`bot_cookie_expiry_reminder_via_queue`/`bot_cookie_qr_via_queue`/`bot_file_export_via_queue`/`bot_group_welcome_via_queue`）**同后缀、同缺省 `False`、同语义（旧直连↔统一管线）**，是本波唯一成套一致的开关族；`_db_path` 28 键命名一致且全部在 `path_fields`。

---

## §4 生效时机与校验覆盖面（一处校验 / 一个生效时机）

### 4.1 P1：R3 防刷屏键零映射——「登记了但生产读不到」

- **严重度**：P1（用户可见行为面 + 台账 #22 声称已交付）。
- **坐标**：声明 `config.py:927`；影子缺省 `domains/chat_reply/policy/rate_limit.py:39`；映射函数同文件 `:1217-1251`。
- **锚点**：`chat_sender_min_interval_seconds: int = 45`（policy 侧）/ `bot_rate_limit_chat_sender_min_interval_seconds: int = 45`（schema 侧）/ `def build_rate_limit_settings(config: object) -> RateLimitSettings:`。
- **根因**：同一旋钮存在**两个 schema 源**（Config 字段 + `RateLimitSettings` 模型字段），`build_rate_limit_settings()` 逐字段搬运时**漏掉这一个**，policy 侧自带缺省 45 当家 → 行为看似正确纯属两值巧合相等。
- **证据**：`grep -rn bot_rate_limit_chat_sender_min_interval_seconds --include=*.py plugins tests scripts bot.py` 除 `config.py` 外 **零命中**（本席全树 AST 索引同样 0 消费）；`build_rate_limit_settings` 12 个 kwargs 中无此项（实读 :1218-1251）。
- **改法**：`build_rate_limit_settings()` 增 `chat_sender_min_interval_seconds=int(getattr(config, "bot_rate_limit_chat_sender_min_interval_seconds", 45))`，并删除 `RateLimitSettings` 侧的独立缺省（改 `Field(...)` 必填或同值并注明单源）。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 …python.exe -m pytest tests/test_policy_sender_interval.py -p no:cacheprovider --basetemp="$TEMP/u6-audit-r3" -q`；再加一条负锁：构造 `Config(bot_rate_limit_chat_sender_min_interval_seconds=0)` → `build_rate_limit_settings(cfg).chat_sender_min_interval_seconds == 0`。

### 4.2 P1/P2：`getattr` 兜底字面量与声明缺省不一致（168 处 / 71 键）

三参 `getattr(config, "bot_*", 兜底)` 全树 **873 处**；其中 **168 处兜底值 ≠ `config.py` 声明缺省**（None 哨兵 39 处、真值不等 129 处）。这不是风格问题：兜底值在传入对象不是 `Config`（control plane / smoke / 测试替身 / `SimpleNamespace`）时**就是实际缺省**，于是「一处缺省」变成 N 处。高危样本（全表 `%TEMP%/u6-config-getattr2.json → default_drift`）：

| 键 | 声明 | 兜底 | 坐标（锚点=键名同行） | 后果 | 严重度 |
|---|---|---|---|---|---|
| `bot_chat_failover_max_seconds` | `120.0` | **`0.0`（=不限）** | `control_plane/llm_admin.py:109,357`、`llm_engine/model_router.py:2323` | 非 Config 传入路径下故障转移失去总时限，正是 09-15「预算烧穿慢回复」的反向复发面 | **P1** |
| `bot_request_budget_seconds` | `300.0` | `0.0` | `__init__.py:4702`、`pipeline/backend_unit.py:117` | 同上（请求级 deadline 消失） | **P1** |
| `bot_quiet_hours_start/_end` | `00:00`/`06:00` | `23:00`/`07:00` | `policy/quiet_hours.py:156-158` | 免打扰窗在旁路装载下**整段位移**（多静默 1 小时、少静默 1 小时） | **P1** |
| `bot_poke_affinity_delta`/`_daily_max` | `0.1`/`0.5` | `0.5`/`5.0` | `__init__.py:5147,5149` | 好感增益 5×/10×（好感度是用户可感数值，v5 算法单一口径被破） | **P2** |
| `bot_vision_mode` | `"direct"` | `"relay"` | `__init__.py:4688`、`admin/runtime_admin.py:1422` | 识图链路整条换形（多一跳 VLM 成本） | **P2** |
| `bot_persona_display_name` | `"报存"` | `''`×12 / `"守岸人"`×2 | 14 处（见 §3 N9） | 卡面署名来源不唯一 | **P3** |
| `bot_web_search_timeout_seconds` | `3.0` | `6.0`×3 | `pipeline/backend_unit.py:95`、`search/{search_smoke,web_search}.py` | 超时预算双值 | P3 |
| `bot_web_search_max_results` | `20` | `12` | `__init__.py:6862` | 条数上限双值 | P3 |
| `bot_download_timeout_seconds` | `600` | `300`/`120`/`60` | `__init__.py:4582`、`files/capabilities/download.py:101`、`music/capabilities/music.py:345` | **同键三套兜底**（含 60 vs 600 的 10 倍差） | **P2** |
| `bot_download_max_bytes` | `1<<30` | `209715200`(=200MB) | `music/capabilities/music.py:344` | 上限双值 | P3 |
| `bot_card_ui_scale` | `1.25` | `1.0` | `link_parse/capabilities/content_parser.py:423` | 出图尺寸双源（渲染契约面） | P3 |
| `bot_download_cache_max_{bytes,age_days}` | `2147483648`/`7` | `0`/`0` | `__init__.py:4583-4584` | 0 语义=「不清理」vs「立即清空」不明 | P3 |
| `bot_timezone` | `"Asia/Hong_Kong"` | `''` | `control_plane/_app.py:310`、`domains/schedule/store/reminders.py:603` | 空 tz 进 `ZoneInfo('')` 即抛（提醒解析路径） | **P2** |
| `bot_*_db_path`/`_dir`/`_file` 8 键 | `data/...` | `''` | `webui_stats.py:366`、`database_broker.py:468/474`、`usage_monitor.py:523`、`reflection.py:944/983`、`__init__.py:2852`、`timesync` 等 | `''` 在消费侧通常=「关闭该功能」，与「未设置」同形 → 旁路装载下功能静默消失 | P3 |

**根因（统一表述）**：项目惯例是「消费点用 `getattr(config, K, 兜底)` 做防御」，而 `Config` 是 pydantic 全字段必有缺省的模型 → 兜底值**在正常路径永不可达**，只在旁路路径成为真缺省，于是每个兜底字面量都是一个影子 schema。**改法（一条全局规则）**：`Config` 字段是唯一缺省源；消费侧一律 `config.field`（属性直取）或 `getattr(config, K)`（无第三参）；需要旁路兼容的对象（control plane / smoke / 测试）改注入真 `Config` 实例。存量迁移建议加机器门：AST 检 `getattr(*, "bot_*", <literal>)` 且字面量 ≠ 声明缺省 → 红（本席脚本已可直接改造成门）。
**验证**：`…python.exe /c/Users/LancyCelestia/AppData/Local/Temp/u6_getattr_check2.py`（输出行 `three-arg getattr sites: 873 | default drift: 168`）。

### 4.3 校验覆盖面：65/616（10.6%）

| 面 | 实测 | 实弹探针证据（离线合成载荷，`Config.model_validate(translate_env_keys({...}))`） |
|---|---|---|
| 数值键无界 | `int/float` 且无 validator 且非 `Field()` 共 **221**；全树仅 `bot_control_plane_port` 用 `ge/le` | `BOT_MARKET_TIMEOUT_SECONDS=-5`→**通过**(-5.0)；`BOT_RENDER_MAX_CONCURRENCY=0`→通过；`BOT_MEDIA_ARCHIVE_DAILY_LIMIT=-1`→通过；`BOT_EMBEDDING_DIMENSIONS=0`→通过；`BOT_CHAT_MAX_INPUT_TOKENS=-1`→通过；`BOT_REFLECTION_HOUR=99`→通过 |
| 枚举键无白名单 | **12-15** 个 `_mode/_scope/_preset/_provider/_min_role/_lang/_backend` 键无校验（唯一例外 `bot_decision_engine_mode` 有 fail-closed 归一） | `BOT_MEDIA_ARCHIVE_MIN_ROLE=superadmin`→**通过**（少下划线即静默改变权限门槛判定输入）；`BOT_POKE_REPLY_MODE=ramdom`→通过；`BOT_TTS_AUTO_REPLY_SCOPE=everywhere`→通过；`BOT_GROUP_DIGEST_LIST_MODE=allow`→通过 |
| 时钟键不统一 | `bot_group_digest_push_time` **有** HH:MM 校验（`config.py:1256`，注释自陈「与 `policy/quiet_hours.QuietHoursSettings.validate_clock_time` 同款」）= 同一段 HH:MM 逻辑的两份实现；`bot_quiet_hours_start/_end` 在 Config 层**无**校验（校验住在下游模型） | `BOT_QUIET_HOURS_START=25:99`→Config 层**通过**（错误推迟到装配期由下游抛出，或按下游兜底位移） |
| ID 列表族未全覆盖 | `_parse_id_list` 覆盖 22 键；**`list[str]` 却无解析器的 2 键全是 ID 语义**：`bot_daily_assist_push_user_ids`、`bot_daily_assist_meal_times` | **`BOT_DAILY_ASSIST_PUSH_USER_IDS=1001,1002` → ValidationError 启动崩**；`BOT_DAILY_ASSIST_MEAL_TIMES=11:15,17:15` 同样崩。而 `catalog §0.2` 明文承诺「ID 列表键：JSON 数组 或 `,` `;` 分隔」→ **册承诺的语法 schema 拒收** |
| 密钥形态 | 43 个 `api_key/token/secret/sendkey` 键，**0 个** validator；`env:变量名` 约定只靠人读（仅 `bot_saucenao_api_key` 用了 `"env:…"` 形态缺省） | 见 §7 |
| `env:` 引用不变量 | registry 里 `"env:X"` → `getattr(config, "x")`；**无门保证 X 有小同名字段**（H3 已三次事故，`config.py:835-838` 注释自陈） | §2.2(a) `BOT_POTCCV_API_KEY` 即活体缺口 |

**改法（收口清单第 3、13 条）**：①`_parse_id_list` 的目标清单扩到「所有 `list[str]` 字段」并以 AST 门反向检查「存在 `list[str]` 字段不在任一解析器内」；②时钟族共用一个 `parse_clock_str()`（Config 层调用，删下游副本）；③数值键按「timeout/limit/seconds/bytes」四类上统一 validator（`gt=0`/`ge=0`/`le=` 上限）；④枚举键族加 `Literal[...]`（pydantic 原生，零额外代码）；⑤新增门：遍历 `bot_model_registry`/`bot_vision_model_registry`/`bot_asr_model_registry` 全部 `env:NAME`，断言 `NAME.lower()` ∈ Config 字段（`BOT_POTCCV_API_KEY` 立即红）。
**验证**：§4.2 同一条 python 探针块 + `…python.exe -m pytest tests/test_doc_sync_gates.py tests/test_config_contract_gates.py -p no:cacheprovider --basetemp="$TEMP/u6-audit-valid" -q`（后者为拟新增门件）。

### 4.4 生效时机只有 72/616 有声明

`SETTABLE_KEYS` **41** 键（可热改）+ `RESTART_REQUIRED_KEYS` **31** 键（明文标注需重启，理由齐全）；其余 **545 键（88.5%）无任何时机标注**。抽验两条声明与代码一致（口径诚实）：`build_shared_group_context_provider` 在 `domains/chat_reply/character/shared_group.py:359/372` 把 `enabled`/`mode`/`whitelist` 烘进对象 → 热改不可达，与 `RESTART_REQUIRED` 理由相符；写面门纪律**成立**——`control_plane/config_store.py:42-51` `normalize_key(..., writable=True)` 对重启键显式 `raise ValueError("该配置尚无安全热更新路径，请修改 .env 并重启")`，未登记键 `raise KeyError`（正面记录）。残余缺陷仅一处：同文件 `:259-261` 的 legacy 覆盖导入循环对「非 SETTABLE 或属 RESTART」键 `continue` **静默丢弃**（迁移历史覆盖时既不报错也不计数）→ 判定 **P3**。
两处口径缺陷：①`RESTART_REQUIRED_KEYS` 的理由串里 10 组模块坐标是 **v21r2 重组前旧路径**（`character/shared_group.py`、`sources/web_search.py`、`sources/telegram_media.py`、`runtime/pipeline.py`、`runtime/model_schedule.py`、`capabilities/{content_parser,poke,chat}.py`、`policy/rate_limit.py`、`runtime/video_pipeline.py`）——真身已在 `domains/**`，其中 `sources/web_search.py` **文件不存在**（§1.3 实证），按坐标找会空跑；②`SETTABLE_KEYS` 含唯一旁路键 `BOT_MUSIC_MODE`（§2.2(b)）。
**改法**：为「装配期快照」建机读登记表（`key → 消费装配点 module.func`），由 catalog 与 `RESTART_REQUIRED_KEYS` 双侧引用同一份；时机标注从 72 扩到全量（未标注即红）；legacy 覆盖导入循环对跳过键至少计数/记一行审计，不再静默丢弃。
**验证**：`…python.exe /c/Users/LancyCelestia/AppData/Local/Temp/u6_timing_check.py`（输出行 `SETTABLE_KEYS=41 RESTART_REQUIRED_KEYS=31 config fields=616`、`无任何时机标注的字段数: 545`）。

---

## §5 门控层级统一（主门 ∧ 分门）

### 5.1 现状三族对照（脚本实测缺省）

| 族 | 主门 | 分门缺省 | 层级是否可枚举 | 判定 |
|---|---|---|---|---|
| v21 服务装配 | `bot_v21_service_wiring_enabled=False`（唯一消费 `runtime/service_wiring.py:66` + 根 `__init__.py:4252`） | teaching `True` / broker `True` / worldbook `False` / knowledge `False` | ✅ 四门全在 `service_wiring.py:69-76` 同处集中判定 | **P3**：主门关时分门 True 不生效（代码注释 `:15` 已自陈），但**同族四门两真两假**，catalog 无「为何这两个既有键保留 True」的族级说明；建议分门全缺省 False（拨主门即"要开"，再逐个放行） |
| schedule（V2.1 §4） | `bot_schedule_enabled=False` —— **零消费**（§2.4 C 类⑥） | `llm_draft False` / `timetable False` / `delivery False`；`db_path`、`exceptions_path`、`delivery_max_retries` 有消费 | ❌ 主门不存在 | **P1**：层级倒挂——分门能开，主门拨不动任何东西；「未接线前各开关缺省关」的交接书口径对 `*_enabled` 三键成立，但 `llm_draft_enabled` **已被 `domains/schedule/llm_draft.py:464` 真实读取**，即该子服务已可达而总门不可达 |
| ACG 检索 | `bot_search_acg_enabled=False`（真消费 `capability_protocols.py:1181/1403`，且登记在描述符 `config_keys=(…)` `:1636`） | bangumi/moegirl/bilibili 三门缺省全 `True`，但**只有 WebUI 读它们**（`control_plane/webui_knowledge.py:513`，兜底写 `False`），真引擎 `acg_search.search_acg_verticals(query, intent, timeout_seconds=…)` **不接收分门**（实读 `:1199-1203`） | ❌ | **P1**：三门「只改显示不改行为」，且 schema 缺省 `True` 与 UI 兜底 `False` 相反 → 主门一开三源全量并发，UI 却报「未启用」 |
| S0 出站收编 | 无主门（四门各自独立） | 四门全 `False`，同后缀同语义 | ✅（形态齐但缺「统一出站总门」） | **P3**：与 `outbound_registry.py` 登记面对应，缺一个能一键回滚全部四门的主门（回滚需拨四条） |

### 5.2 缺省 True 的门（行为风险面）与「有兜底/无兜底」二分

156 个布尔中 93 个缺省 True。按「是否有第二道收窄」分：

- **有兜底（设计自洽，勿误判为缺陷）**：`bot_media_archive_enabled`(+`min_role=super_admin`)、`bot_group_digest_push_enabled`(+`list_mode` 非 whitelist 则零推送)、`bot_reactions_enabled`/`bot_reactions_meme_enabled`(+概率/冷却/每小时/每日四门)、`bot_master_love_enabled`(+名单空即不生效)、`bot_content_route_enabled`(+群白名单空=群面关闭；私聊放开是 09-17 用户裁定，**不算漂移**)、`bot_memory_extract_enabled`/`bot_tts_cache_enabled`/`bot_kb_wiki_sync_on_startup`（子门 True 但父门 False，注释已声明依赖）。
- **无第二道收窄（默开且会对外发声/发图）**：**`bot_group_welcome_enabled = True`**（`config.py:657`，注释 `审查 B-05`）——任意新成员入群即向群内发言，且该面同时是 §5.1 第四行 `bot_group_welcome_via_queue=False` 的旧直连路径（无幂等/无回执）。判定 **P2**（与全项目「名单为空=整链不注册、绝不猜群」的纪律相反）。
- **文档称已接线但门值与宣称冲突**：`AGENTS.md` 第四部分把 SendQueue 画为主链路必经，而 `bot_send_queue_enabled=False` + `bot_send_queue_db_path=""` 双缺省下 `build_send_queue`（`domains/transport/sender/queue.py:1840-1858`）返回 `InMemorySendQueue`——机制成立（**非缺陷**，本席实读确认，特此正面登记防下轮误判）；真正的矛盾是 catalog/A10 未写明「enabled=是否持久化」而非「是否使用队列」。判定 **P3（文档口径）**。

---

## §6 环境装载链（双源冲突与 int/str 陷阱）

### 6.0 前提实证：`.env` 的值**不进** `os.environ`

生产装载由 NoneBot 完成，其 config 用 `dotenv_values(...)` **纯读文件、绝不写 `os.environ`**（实证 `ChatBot_Runtime/venv/Lib/site-packages/nonebot/config.py:25` 的 `from dotenv import dotenv_values`、`:115` 的 `file_vars = dotenv_values(file_path, …)`；`:188` 的 `_parse_env_vars(os.environ)` 是另一个独立更高优先级源）。全树 `grep -rn "load_dotenv" plugins bot.py` 仅命中 `domains/food/capabilities/eat.py:735-737`（CLI 侧；同文件 `:287` 注释自陈「库代码不做 `load_dotenv()`——运行时读 `.env` 会把生产开关泄进…」）。
**推论（本席判据基础）**：`os.getenv("BOT_*")` 在生产进程内**看不见 `.env`**，只看得见启动器真实环境 → 「代码读 env」的键对 `.env` 配置不是优先级低，而是**恒不生效**。

**插件内 `os.environ`/`os.getenv` 直读 `BOT_*`：23 键 / 31 处，四类形态**

| 形态 | 键与坐标（锚点=同行键名） | 后果 | 严重度 |
|---|---|---|---|
| **只生效不登记**（Config 无字段 + catalog 无 + `.env.example` 无，三票全缺） | `BOT_BILIBILI_AI_SUMMARY`（`domains/link_parse/parsers/platforms_bilibili.py:294`，缺省 `"1"`=开）、`BOT_CHANNEL_HEALTH_LATENCY_FIRST`（`domains/chat_reply/llm_engine/channel_health.py:402`）、`BOT_TWITTER_BEARER_TOKEN`（`domains/subscribe/adapters/social_v2.py:101`）、`BOT_TWITTER_QUERY_IDS`（同 `:82`） | 四个「只能靠启动器环境变量」的旋钮，登记面完全不可见（`/bot runtime`、catalog、模板三处都查不到）；其中两键决定 Twitter 订阅适配器能否工作 | **P1** |
| **仅 env 通道 + 硬编码相对兜底**（重映射被绕开） | `platforms_epic.py:65` 与 `platforms_steam.py:77`：`os.getenv(_COOKIES_ENV, "").strip() or "data/platform_cookies.txt"` | `.env` 里的 `BOT_COOKIES_FILE`（是字段、且在 `path_fields`）对这两个解析器不可见 → 静默改用**相对** `data/platform_cookies.txt`（按 CWD 解析、可指源码树）→ Epic/Steam 登录态恒不生效；同键正道在 `domains/core/credentials/platform_credentials.py:110/179/440`（读 config），**两制并存** | **P1**（台账 #1 家族的读面同型根因） |
| **同键三套优先级** | `bot_download_proxy`：`domains/transport/sender/nonebot.py:74-80`（provider → config → env 末位）/ `domains/media/ingest/telegram_media.py:107-113`（`TELEGRAM_PROXY` → adapter_config → **env 先于 config**）/ `domains/link_parse/parsers/platforms_{epic,facebook,steam}.py`（**仅 env**） | 一个键三种生效序，且「仅 env」路对 `.env` 免疫；`RESTART_REQUIRED_KEYS` 给它的理由「半接线，热改仅部分通道生效」与实读互证，但未写明「`.env` 值对其中三路不可见」 | **P1** |
| **config 优先、env 兜底**（方向正确，双源仍在） | `control_plane/{__init__.py:90-131,factory.py:62}` 8 键（`:88` 注释自陈「os.environ 兜底服务于裸脚本与测试」）、`domains/ops/monitor/error_report.py:232-234`、`channel_health.py:384/740`、`model_router.py:627/643`、`domains/finance/data/market_data.py:184` | 无实害，但每键仍是两个源，`Config` 非唯一真相。收口：注入 `Config`，裸脚本另直构 `Config` 实例（本席实测离线可直构，成本零） | P3（正面记录方向正确） |


**实测装载路径共 5 条，语义互不兼容**：

| # | 装载点 | 形态 | 差异 |
|---|---|---|---|
| 1 | `plugins/bot_unified_runtime/__init__.py:3647` | `Config.model_validate(translate_env_keys(driver_config))` | 生产主链（driver config 已由 NoneBot 从 `.env`+`.env.prod` 装入） |
| 2 | `domains/ops/smoke/smoke.py:246` | `Config.model_validate(translate_env_keys(_json_decode_env_values(values)))` | **自带 JSON 解码补层**；`:213` 注释自陈「否则 `Config.model_validate` 直接 `list_type` 崩溃，故 smoke 装载必须补齐」= schema 缺容错、由调用方各自补 |
| 3 | `domains/core/decision/shadow.py:108` | `Config.model_validate(translate_env_keys(driver_config.model_dump()))` | 又一条独立链 |
| 4 | `scripts/clean_food_gallery.py:71`、`scripts/e2e_acceptance.py:1919` | `Config(**translate_env_keys(vals))` / kwargs 直构 | 不走 `model_validate` 的构造面 |
| 5 | `runtime_paths._dotenv_value`（`scripts/runtime_paths.py:34-49`） | 自己按行解析 `.env` → `.env.prod`（后者覆盖）→ `os.environ` 优先 | **完全绕开 Config**，只为拿 `BOT_RUNTIME_DATA_DIR` 一个键 |

- **`.env` / `.env.prod` 优先级**：生产显式 `nonebot.init(_env_file=(".env", ".env.prod"))`（`bot.py:255`），`.env.prod` 覆盖 `.env`；`runtime_paths` 的 last-wins 循环与之同向（`os.environ` 最高），**两侧优先级一致但逻辑各写一份**。判定 **P3（双实现，非冲突）**。实测 `.env.prod` 只有 6 个生效键（SnowLuma WS 3002/campus 相关），无与 `.env` 同名冲突项 → 当前无实害，风险在「未来同名键无测试锁定」。
- **真实盘符第 4 源**：`bot.py:260` `_install_crash_guards(getattr(_driver_config, "bot_runtime_data_dir", None))` —— 取 **driver 原始值**（未过 `_resolve_runtime_data_paths`），相对性由 `bot.py:171-174` 自己按 `Path(__file__).parent` 拼；`crash.log`/`faulthandler.log` 落点与其余路径键**不走同一解析器**。判定 **P3**（顺序正确、实害未见，但同一 root 四个解析器）。
- **int/str 陷阱族（793e647 类）覆盖不全**：`_coerce_scalar_id_to_str`（`config.py:1213-1230`）只覆盖 3 个标量键；`_parse_id_list` 覆盖 22 个列表键（元素 `str()` 宽容，实测 `BOT_SUPER_ADMIN_USER_IDS='[10000000001, 10000000002]'` 与 `'1001,1002'` 均通过）。**未覆盖**：
  - `bot_daily_assist_push_user_ids` / `bot_daily_assist_meal_times`（`list[str]` 无解析器）—— 实测逗号裸串 **ValidationError**（§4.3）。
  - `bot_admin_profiles: list[dict[str, str]]` 的**内层值**——实测 `{"qq": 10000000001}`（数字未加引号）→ `ValidationError: bot_admin_profiles.0.qq` = **启动崩**。生产 `.env` 当前写的是带引号字符串（形态核验：`"qq":"<NUM-ID>"`），**故现网未踩雷**，但一次手改去引号即整插件加载失败；同型风险 `bot_mail_sender_aliases: dict[str, str]`（实测内层 int → `ValidationError`）。
  - `BOT_*_API_KEY` 明写变量名而 `.env` 未加引号的纯数字 key（`translate_env_keys` 只改键名不改值）。
  **改法（收口清单第 3、13 条）**：`_parse_id_list` 扩到全 `list[str]`；`list[dict[str,str]]`/`dict[str,str]` 族统一「叶子值 `str()` 收编（bool 除外）」；补门：`Config.model_validate({合成载荷})` 的**语法矩阵回归**（逗号裸串 / 裸 JSON / 数字 ID 三形态 × 每族一键）。
  **验证**：`PYTHONDONTWRITEBYTECODE=1 …python.exe -c "…见 §4.3 探针块…"`（本席已实跑，输出逐行在 §4.3 表）。

---

## §7 打码与安全配置面

| 项 | 实测 | 判定 |
|---|---|---|
| `.env` 是否入库 | `.gitignore:23-26` 覆盖 `.env`、`.env.*`，否定 `!.env.example`/`!.env.sample`；`git ls-files` 中唯一 `.env*` 跟踪件 = **`.env.example`**；`git ls-files --error-unmatch .env` → 未跟踪 | ✅ 合规 |
| 可 commit 面密钥泄漏 | 全跟踪树按 `sk-/SCT/ghp_/xoxb-/AKIA` 形态扫描：**唯一命中 `tests/test_secret_redaction_hardening.py:72,74`，是该测试自造的合成样本**（正是打码面的正/负样本）；`.env.example`/`config-catalog`/`COMMANDS.md` **零命中** | ✅ 零真实密钥 |
| `env:变量名` 约定是否被 schema 强制 | **否**：43 个密钥形键 0 validator；`bot_saucenao_api_key = "env:SAUCENAO_API_KEY"`（`config.py:104`）是唯一把约定写进缺省的键，其余 42 个为 `""`；明文密钥与 `env:` 形态在 schema 层完全不可区分 | **P2**：违背「配置用 `env:变量名` 引用」（AGENTS 铁律 3）的正向可执行化——明文进了 `BOT_MODEL_REGISTRY` JSON 就永远躺在 `.env`（可接受）还是被粘进可 commit 面（不可接受）无人拦 |
| 解析失败的日志是否可能带值 | `config.py:1292-1298`、`:1328-1334`、`:1352-1358`、`:1397-1403` 四处 JSON 解码失败路径：只打 `info.field_name` + 异常类型摘要，注释自陈「禁止打出配置内容防密钥泄漏」 | ✅ 已收口（正面记录） |
| 错误卡配置快照 | `domains/ops/monitor/error_report.py:143` 注释：「`bot_credentials_file` 等真实字段此前能进白名单但值打不掉」→ 白名单制 | ✅ 白名单制在位（本席未见回归） |
| 幻影/旁路密钥面 | `bot_potccv_api_key` 无字段（§2.2a）；`bot_divination_fortune_secret` 被 `domains/divination/api/facet.py:339` 读取却**不是字段**；`bot_control_plane_token_sha256`/`bot_control_plane_super_admin_token_sha256` 存 sha256 而非明文（好形态，**但无 hex 长度/字符集校验**，填错=鉴权恒失败） | **P2**（三处：槽位缺失 / 幻影密钥键 / 无格式校验） |
| 可 commit 面硬编码本机绝对路径 | 插件内 1 处：`domains/location/knowledge/kb_wiki.py:58` `or r"D:\Coding\Crawl Wiki"`（配置缺省住在代码里，绕开 schema）；维护脚本 **4 个文件共 8 处**硬编码 `ChatBot_Runtime` 全路径：`scripts/{apply_config_batch,configure_axonhub_registry,consolidate_model_registry,scrub_history_credentials}.py`（各 2 处，未走 `scripts/runtime_paths`，与 AGENTS 铁律「全部相对路径统一走 runtime_paths 解析」不符） | **P2**（只报键名/文件:行，不含任何密钥值） |

---

## §8 配置与运行时状态边界

- **重映射覆盖实况（脚本逐后缀核验，非抽样）**：`_db_path` 结尾 **28 键 → 28 在册（100%）**；`_path` 结尾 30 键 → 30 在册（含 `bot_media_registry_path`、`bot_schedule_exceptions_path`）；`_file` 结尾 12 键 → **9 在册、3 缺**（`bot_{holidays,credentials,user_profiles}_file`）；`_dir` 结尾 14 键 → **10 在册、4 缺**（`bot_runtime_data_dir`=根本身、`bot_tts_gptsovits_dir`、`bot_daily_assist_dir`、`bot_card_asset_dir`）。全树 `Field(` 用量 **仅 1 处**（`bot_control_plane_port` 的 `ge/le`）→ 「一处校验」在 schema 层等于未开工。
  → 「配置指源码树」的**默认值面**不成立：`path_fields` 55 项把 `data/...` 一律钉到 `BOT_RUNTIME_DATA_DIR`；生产显式设置该键（`grep -c "^BOT_RUNTIME_DATA_DIR=" .env` = 1，值未摘录），外置数据根实存（`../ChatBot_Runtime/data/` 计 105 项）。
- **现网可复现的源码树写面**（三处，全部为「未进重映射」或「幻影键」类）：
  1. `bot_credentials_file` / `bot_user_profiles_file` / `bot_holidays_file`：三键**生产 `.env` 均已设置**（登记面核验：`in_dotenv=True`），而三者在 `path_fields` 之外、消费点直取裸字符串（`FileCredentialStore(裸串)` @`domains/core/credentials/credentials.py:218`、`FileRelationshipProvider` @`domains/chat_reply/character/relationship.py:169`、`load_holiday_table(...)` @`domains/chat_reply/character/temporal.py:378`）。本席按纪律**未读值**，故不断言现网是否落树；可断言的是：同一份 `.env` 若按 catalog §0.3 的项目惯例写成 `data/...` 相对形态，这三路就会按 CWD 解析（其余 55 键则被 schema 强制重映射）——**语义只取决于书写形态，schema 未提供保护**。源码树今日无 `data/` 目录（`ls -d data` 不存在）= 未见实害证据。判定 **P1（保护缺失，非现网事故）**。
  2. 幻影键 `bot_food_image_dir`：`eat.py:215-224` docstring 自陈「失败退回相对路径」，`scripts/clean_food_gallery.py:204` 兜底 `'data/food_images'` → 该图库在无 Config 环境（独立脚本入口）写源码树。台账 #1 的 **第 4 次复发根因同型**。
  3. `scripts/runtime_paths._dotenv_value` 只认 `.env`/`.env.prod` 两个文件 + `os.environ`：**任何经 driver config / `/bot runtime set` / 测试夹具设置的 `BOT_RUNTIME_DATA_DIR` 都到不了 `runtime_path()`** → 同一进程内「Config 重映射面」与「runtime_path 消费面」可以指向两个数据根（例：`bot_daily_assist_dir` 走后者、`bot_affinity_db_path` 走前者）。判定 **P1（边界不统一，静默分裂）**。
- **`data/` 残留现状（本席开工基线自查）**：`ls -d data` → 不存在；`__pycache__` 0、`*.pyc` 0；但树根存在 `.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`（mtime 09-19 12:37/12:47，**非本席产物**，dev.ps1 用的是 `../ChatBot_Runtime/cache/*`）与空目录 `%TEMP%/`（mtime 09-18 03:37，疑似某会话把 cmd 风格 `%TEMP%` 当重定向目标）→ 与铁律 6「源码树零缓存」不符，且 `.tmp-test/`（33 条 ruff 错来源）仍在树内。判定 **P2 树卫生**（登记归属：上轮审计 P2-16 + HANDOFF §五 待清理项）。

---

## §9 源码树零残留自查（本席责任）

- 本席全部直跑命令带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；ruff/mypy 缓存重定向到 `../ChatBot_Runtime/cache/{ruff-u6,mypy-u6}`；pytest 只跑 §1.4 的 scoped 两件（6 passed），带 `--basetemp="$TEMP/u6-audit-gates1" -p no:cacheprovider`（基座落在 `%TEMP%`，未进源码树）；未跑全量套件。
- 产物全部在 `%TEMP%`：`u6-{ruff,mypy}.txt`、`u6_inventory.py`、`u6_getattr_check.py`、`u6_getattr_check2.py`、`u6_timing_check.py`、`u6_naming_check.py`、`u6-config-{inventory,getattr,getattr2,timing}.json`、`u6-naming.json`、`u6-dotenv-keys.txt`。
- 收尾复核（本席写盘后执行）：`find . -name "__pycache__" | wc -l` = **0**、`find . -name "*.pyc" | wc -l` = **0**、`ls -d data .pytest_cache .ruff_cache .mypy_cache` 与 §8 基线一致（三项为 09-19 存量，非本席生成，本席不删除他席产物）；`docs/design/audit-20260920-unify-U6-config.md` 为本席唯一新增文件。
- 本席零 git 写、零子代理、零重启、零真实发送、`.env` 值未摘录。

---

## §10 配置单一 schema 收口清单（按解锁顺序）

> 前置事实：全 616 字段登记面完整（表① catalog = 0 漏），**缺的不是登记，是「一个源/一处校验/一个时机」**。以下每条都可独立验收。

**A 类：立刻可修，不动键名（P1 优先）**
1. `build_rate_limit_settings()` 补 `chat_sender_min_interval_seconds` 映射并删 policy 侧独立缺省（§4.1）。
2. 删除/改名 `.env` 六个幻影键：`BOT_GROUP_DIGEST_ENABLED`、`BOT_SUBSCRIBE_{DIGEST_HOUR,DIGEST_MINUTE,LIVE_POLL_SECONDS,PLAYWRIGHT_POLL_SECONDS}` 从生产 `.env` 摘除（值语义迁移到现役等价键）；补 `bot_api_key_potccv: str = ""` 槽位字段（§2.2a）。**（`.env` 是用户文件，本席未改，只登记）**
3. `_parse_id_list` 目标清单扩至全部 `list[str]` 字段（至少 `bot_daily_assist_{push_user_ids,meal_times}`）；`bot_admin_profiles`/`bot_mail_sender_aliases` 增加叶子值 str 收编（§6）。
4. `acg_search.search_acg_verticals(...)` 接收三个分门（或删三键、UI 改读引擎实际源列表）；`bot_schedule_enabled` 接进 schedule 族装配点（§5.1）。
5. 三处「只登记不生效」补消费或删键：`bot_{share_enabled,share_groups,share_read_only}`、`bot_prompt_{audit_enabled,audit_include_messages,audit_include_untrusted_context,audit_retention_days,execution_mode,approval_digest}`、`bot_runtime_{alias_enabled,default_persona}`、`bot_poke_admin_bypass`、`bot_moegirl_max_candidates`、`bot_randpic_max_file_mb`、`bot_subscribe_{card_enabled,jitter_ratio}`、`bot_search_acg_max_per_source`、`bot_card_asset_dir`（改由 Config 注入，替掉两处 `os.getenv`）（§2.4 C 类）。
6. 补 `path_fields`：`bot_credentials_file`、`bot_user_profiles_file`、`bot_holidays_file`、`bot_daily_assist_dir`、`bot_randpic_dirs`（列表侧）；新增 `bot_food_image_dir` **字段**并把两处兜底改指它（§2.3/§8）。
7. 高漂移 `getattr` 兜底清零（第一批 6 键）：`bot_chat_failover_max_seconds`、`bot_request_budget_seconds`、`bot_quiet_hours_{start,end}`、`bot_poke_affinity_{delta,daily_max}`、`bot_download_timeout_seconds`、`bot_timezone`、`bot_persona_display_name`（§4.2）。
8. **env 通道收口（§6.0，本席认为与第 1 条同批最高优先）**：①四个「只生效不登记」键补正式字段 + catalog + 模板（`BOT_BILIBILI_AI_SUMMARY`、`BOT_CHANNEL_HEALTH_LATENCY_FIRST`、`BOT_TWITTER_{BEARER_TOKEN,QUERY_IDS}`）或明确删除；②`platforms_epic.py:65`/`platforms_steam.py:77` 的 `os.getenv(_COOKIES_ENV) or "data/platform_cookies.txt"` 改注入 `Config`（复用 `platform_credentials.py` 既有读取器），删相对兜底；③`bot_download_proxy` 三处生效序统一为「config 优先、env 末位兜底」（对齐 `sender/nonebot.py:74-80` 现有正确形态），并在 catalog 注明「`.env` 不经 `os.environ`」；④`RESTART_REQUIRED_KEYS` 的旧模块坐标全量改指 `domains/**` 真身（10 组，§4.4）。

**B 类：需要新增机器门（防复发）**
9. 反向覆盖门：`catalog 键 − Config 字段 − A25/§D 豁免表 == ∅`、`.env.example ⊆ Config`、**`.env` 键 ⊆ Config**（对本席 6 条立即红）。
10. 时机标注门：每字段必须属 `SETTABLE_KEYS ∪ RESTART_REQUIRED_KEYS ∪ ASSEMBLY_SNAPSHOT` 之一（当前 545 红，分批收）。
11. 兜底一致性门：AST 检 `getattr(obj,"bot_*",literal)` 且 literal ≠ 声明缺省 → 红（脚本已成型：`u6_getattr_check2.py`）。
12. `env:NAME` 不变量门：三个 registry 字段内所有 `env:NAME` 必须有小同名字段（`BOT_POTCCV_API_KEY` 立即红）。
13. 数值/枚举校验族门：`*_timeout_seconds/*_seconds/*_max_*/*_limit` 必须有界；`_mode/_scope/_preset/_provider/_min_role` 必须 `Literal`；语法矩阵回归（逗号裸串/裸 JSON/数字 ID × 每族一键）（§4.3/§6）。
14. 文档数字一致性门：`config-catalog` 自述「485 字段 / 39 路径字段」（`:4`/`:19`）与机器册 616、实 `path_fields` 55 冲突 → 由 `doc_sync` 一并生成，`AGENTS.md` 头部「529 字段」同步；另加「`os.getenv("BOT_*")` 白名单门」（新增 env 直读必须显式登记豁免理由，防 §6.0 复发）。

**C 类：需用户裁决（破坏性/命名法）**
15. 键改名波：`_whitelist/_blacklist` ↔ `_allowlist/_denylist`（§3 N1）、`_max_retry` → `_max_attempts`（N2）、`BOT_MUSIC_MODE` 收编为 `bot_music_mode` 正式字段（§2.2b）。
16. `bot_group_welcome_enabled` 缺省 True 是否降为 False（§5.2）；`bot_media_archive_min_role` 值是否加角色枚举校验（错值 = 全员不可用）。
17. `.env` 与 `.env.prod` 双文件制度是否保留（若保留：补同名键优先级测试；若合并：一次性迁移动作）。

---

*本席位取证完。所有结论均有可复跑命令或全树脚本索引支撑；未跑的（生产真机、重启后 live）一律标注为未生效面。前端渲染域 / TTS 域 / `echo.py` 为在飞禁改面，本席仅只读登记，未判定归属、未触碰。*
