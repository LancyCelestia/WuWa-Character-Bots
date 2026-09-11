# 主代理实证原始记录（评审线：主代理 §2.4）

> 记录时间：2026-09-11 18:2x~19:xx（+0800）· 分支 `v0.0.1-alpha.2` · HEAD `cbb5161`（2026-09-11 16:50:33 +0800）
> 所有命令在仓库根 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot` 实跑，输出逐字摘录。
> 证据分级：【已复现】= 实跑命令看到输出；【推演】= 仅阅读推断。

## E-1 三门禁实跑（工作树）

命令：
```
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
```

结果【已复现】：

| 门禁 | 结果 | 摘录 |
|---|---|---|
| test | **1312 passed, 1 warning in 61.66s**（exit 0） | `collected 1312 items` / `================= 1312 passed, 1 warning in 61.66s =================` |
| lint | **FAILED（exit 1）** | `Found 2 errors.`：`I001 [*] Import block is un-sorted or un-formatted --> plugins\bot_unified_runtime\__init__.py:1:1`；`UP012 [*] Unnecessary UTF-8 encoding argument to encode --> plugins\bot_unified_runtime\character\reminders.py:189:13` |
| typecheck | **Success（exit 0）** | `Success: no issues found in 222 source files` |

说明：lint 的 2 条错误均落在**工作树未提交内容**上（`__init__.py` 的 randpic/reminder import 顺序、`character/reminders.py` 为 untracked 新文件）。
文档声称对比：`docs/handoff-2026-09-10-full.md:1295` 声称「lint All checks passed」；`docs/handoff-MASTER-2026-09-11.md:38` 声称「1033 passed + lint 全绿」。实测 lint 不过 → 声称与实现不符。

## E-2 bot.py 事件循环处理器（HEAD 坏、工作树修、未提交）

`git show HEAD:bot.py`【已复现】：
```
 149: driver = nonebot.get_driver()
 150: import asyncio as _asyncio
 151: 
 152: _asyncio.get_event_loop().set_exception_handler(_quiet_loop_exception_handler)
```

工作树 `bot.py:159-173`【已复现】已改为：
```python
@driver.on_startup
async def _install_quiet_loop_exception_handler() -> None:
    ...
    asyncio.get_running_loop().set_exception_handler(_quiet_loop_exception_handler)
```

`git status --short` 显示 ` M bot.py` → **HEAD 与工作树不一致，修复未入库**。

机制实证（Python 3.12.10，Runtime venv）【已复现】：
```
loop1 id: 2177924797056 running: False
deprecation warnings at get_event_loop: ['There is no current event loop']
loop2 id: 2177961200672 same object as loop1: False
after asyncio.run, is loop1 closed? False
```
结论：import 期 `get_event_loop()` 取到的循环与运行期循环**不是同一对象** → HEAD 上该降噪处理器**从未生效**（且触发 "There is no current event loop" 弃用告警；`pyproject.toml:6` `requires-python = ">=3.10, <4.0"`，3.14 下该写法将直接报错）。

覆盖缺口【已复现】：`grep -E "import bot\b|from bot import|on_startup|_quiet_loop_exception_handler" tests/` → **无匹配**。即 bot.py 启动路径**零测试覆盖**，故 1312 passed 无法证明该修复有效。

## E-3 已跟踪文件未提交规模

`git status --short --untracked-files=no` → 63 个已跟踪文件被修改；`git diff --stat` 尾行【已复现】：
```
 63 files changed, 2426 insertions(+), 414 deletions(-)
```
`git diff --cached --stat` 为空（暂存区干净）。

未提交内容中**包含 09-10 审计修复主体**（抽查 3 个文件的工作树 diff，均含修复码）【已复现】：

| 文件 | 工作树新增的修复码 | 审计编号 |
|---|---|---|
| `audit/file_logger.py` | `self._lock = threading.Lock()` 包住「检查大小→rename 轮转→追加」；rename 失败降级续写 | B11 |
| `policy/rate_limit.py` | `import threading/time`、`_SWEEP_INTERVAL_SECONDS = 600.0`、`_maybe_sweep()` 清扫空/过期桶 | B5（含 B4） |
| `runtime/disconnect_notice.py` | `await asyncio.to_thread(push_serverchan/push_pushplus, ...)` + 显式 `bool` 局部变量 | B1 |

这三个文件的 HEAD 版本最后一次被改动分别为 `d19d4c2 2026-08-21`、`683ea06 2026-09-07`、`a27c289 2026-09-08`，即 **09-10 审计修复从未入库这些文件**。

## E-4 回归测试只在工作树（26 个测试文件不在 HEAD）

【已复现】
```
HEAD test files: 115
worktree test files: 141
absent-at-HEAD count: 26
```
缺失清单（26）：`test_asr_transcribe.py`、`test_auditfix_main_character.py`、`test_auditfix_parsers.py`、`test_auditfix_sender_queue.py`、`test_auditfix_subscriptions_capabilities.py`、`test_auditfix_wave3_logic.py`、`test_auditfix_wave3_resources.py`、`test_llm_error_classification.py`、`test_llm_httpx_client.py`、`test_media_registry.py`、`test_meme_domain_fixes.py`、`test_meme_image_input.py`、`test_parser_multipage_quote.py`、`test_perf_final.py`、`test_perf_forward.py`、`test_perf_hotpath.py`、`test_perf_p1.py`、`test_perf_p3.py`、`test_pipeline_review_fixes.py`、`test_temporal_http_client.py`、`test_video_progress_ack.py`、`test_video_reply_flow.py`、`test_video_seam.py`、`test_video_understanding.py`、`test_vision_local_media.py`、`test_youtube_subtitle_regression.py`

对比：6 个 09-10 审计回归文件中，`test_auditfix_runtime_policy.py`、`test_auditfix_llm_route.py` 在 HEAD，其余 4 个不在。
手册 §13.0/§13.7 声称「96 用例 ×6 文件」已交付、§17 声称「全部代码交付已入库」→ 与 HEAD 事实不符。
门禁 1312 passed 是**工作树数字**；从 HEAD 干净检出无法复现该数字（26 个测试文件不存在）。

## E-5 文档与评审产物不完整

【已复现】`git ls-files --error-unmatch` 逐个判定：
```
TRACKED     docs/handoff-2026-09-10-full.md
UNTRACKED   docs/handoff-MASTER-2026-09-11.md
TRACKED     docs/code-reaudit-2026-09-11.md
UNTRACKED   docs/handoff-final-2026-09-10.md
UNTRACKED   docs/handoff-session-2026-09-11-bgroup-verify.md
TRACKED     AGENTS.md
```
`docs/handoff-MASTER-2026-09-11.md` 自称「所有交接文档的单一入口」却**未被版本控制跟踪**。文档提交 `cbb5161`/`c7f7fbc`/`e973a6c` 的实际文件集各只有 `docs/handoff-2026-09-10-full.md` 一个文件（`git show --stat`），即 MASTER/verify 两份文档从未入库。

字节/行数（python 读字节，避免控制台编码干扰）【已复现】：
```
  170458 bytes   1334 lines  handoff-2026-09-10-full.md
   48735 bytes   2132 lines  handoff-comprehensive-2026-09-05.md
   41697 bytes    244 lines  handoff-final-2026-09-07.md
   47193 bytes    371 lines  handoff-final-2026-09-10.md
    9962 bytes     82 lines  handoff-MASTER-2026-09-11.md
    8542 bytes     62 lines  handoff-session-2026-09-11-bgroup-verify.md
```
被 MASTER §一 判定「已被超越、降级为历史存证」的 `handoff-final-2026-09-10.md` 仍以「唯一活文档」口吻写在正文（`docs/handoff-final-2026-09-10.md` 第 3 行），且**未入库**→ 静默的权威冲突来源。

## E-6 卫生与工作区边界

【已复现】仓库根存在 `.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`（`.gitignore:8-10` 已忽略）+ `.playwright-mcp/`；另有 `.pytest-final-temp/`（`2026/9/7 17:10:50`，`Get-Item -Force` 显示为普通目录且目标为空、无 LinkType），`git status` 反复报 `warning: could not open directory '.pytest-final-temp/': Permission denied`，且它**未被 .gitignore 忽略**（`git check-ignore -v` 无输出）却也不出现在 untracked 列表——ACL 拒绝使 git 无法枚举。
该目录不属于 AGENTS.md 允许的源码树内容，属门禁噪声来源（每次 git 操作打 warning），建议在确认其内容后移除。

## E-7 A9「sender 代理残留」复核（抽查声称）

【已复现】`sender/nonebot.py:43-70`：`_download_proxy_provider` 注入 getter 存在，解析链 = 注入 getter > `bot.config`（`bot_download_proxy`/`BOT_DOWNLOAD_PROXY`）> `os.environ`。
【已复现】`plugins/bot_unified_runtime/__init__.py:2291-2296` 实调 `set_download_proxy_provider(...)`。
→ 手册 §13.10「A9 代理解析：sender 层拿不到运行时 Config，走 bot.config→env 探测」为**过时残留声明**，B-12 已闭环（登记为文档漂移，非代码缺陷）。

## E-7b 提交树 vs 工作树：功能级分叉（影响「提交即可）判断

【已复现】HEAD 与工作树在**同一文件**上有方向性分歧（不只是增量）：

| 探针 | HEAD | 工作树 | 判定 |
|---|---|---|---|
| `.env.example` 的 15 个 `BOT_VIDEO_*` 键在 `config.py` 的字段存在性 | **15/15 缺失** | 0 缺失 | HEAD 上这些 env 键无对应 Config 字段 |
| `__init__.py` 的 `soft_name_mention` | 2 处 | **0 处** | 工作树用另一种表达实现同一分层语义 |
| `OFFLOADED_CAPABILITY_IDS` 是否含 `bot.eat` | **不含**（AST 解析 HEAD 得 14 项） | 含 | C3 修复未入库 |
| `_passive_affinity_perception` | **0 处** | 1 处（含 mood 钩子） | C6 + mood 事件源只在工作树 |
| `__init__.py` 行数 | 5385 | 5798 | 工作树 +413 行（+471/−58） |

关键差别在语义（不全是"优劣"）：HEAD `__init__.py:807/836-840` 把 `persona_name_mention or affinity_nickname_mention` 合成 `soft_name_mention` **并计入 `mentions_bot`**；工作树 `:906-929` 让 `affinity_nickname_mention` **不计入 `mentions_bot`**、只置 `name_mention_only`。
→ 即：**按文档「以 HEAD 为准」清理工作树该区，会丢失 mood 事件源（工作树独有）；反之整文件按工作树提交，会丢掉 HEAD 的「误学小名=真点名」语义**。`docs/handoff-2026-09-10-full.md:1297` 的「全部被 HEAD 取代、不会丢失任何交付」只对**该会话自己的交付**成立。

## E-7c 工作树新增的两处内容损失回归（主代理独立复现）

用文件中同一正则字面量在纯内存复现（`python -B`，未落盘、未改文件）：

**F1 `sources/web_search.py:38-41` + `:249`（void `<embed>` 吃掉后文）**【已复现】
```
  void <embed> mid   -> '<p>FIRST paragraph text here</p> '     ← SECOND 段消失
  void <embed> head  -> '<header> '                             ← 正文全空
```
`embed` 是 HTML void element（无 `</embed>`），成对正则 `_HTML_HIDDEN_BLOCK_RE`(:247) 必然失配 → 兜底正则 `.*\Z`(:249) 从该标签剥到文末。**注意**：`web_search.py:33-36` 的注释已把「残段之后的合法正文丢失」声明为**有意的安全侧倾斜**，故这是**已声明取舍的放大**而非纯疏忽；但把 void 标签放进该组使其从"截断兜底"变成"常见页面常态触发"。

**F2 `output/plain_text.py:210-215`（行内 `$…$` 守卫 Unicode 化）**【已复现】
```
  CJK '是' (U+662F) matches \w : True
  '质能方程 $E=mc^2$是爱因斯坦提出的'   matches=[]        ← 不转换，TeX 原文漏进回复
  '$E=mc^2$ 是公式'                   matches=['$E=mc^2$']  ← 有空格则正常
```
闭 `$` 后紧邻汉字即不匹配（中文行文普遍不加空格）；相对 HEAD 的 `\$([^$\n]+)\$` 属**行为收窄**。修复：守卫 ASCII 化 `(?![A-Za-z0-9_$])`。

## E-7d 死配置字段与错误用户指令（主代理独立复现）

【已复现】`config.py:257 bot_group_digest_enabled` 与 `:260 bot_group_digest_llm_enabled`/`:261 ..._ttl_seconds` 的读取情况：
- `bot_group_digest_enabled`：**除定义行外全库零读取**（死字段）
- 真开关：`config.py:256 bot_shared_group_context_enabled` ← `character/shared_group.py:276` 读取
- `.env`：`BOT_GROUP_DIGEST_ENABLED=false` 与 `BOT_SHARED_GROUP_CONTEXT_ENABLED=false` 均为 false
→ `docs/handoff-2026-09-10-full.md:1332` 的「用户操作项：`BOT_GROUP_DIGEST_ENABLED=true`（如需"总结今日通讯"立即生效）」是**照做无效的错误指令**。

## E-7e 未受管理员门保护的下载能力（越权 + SSRF 面）

【已复现】`plugins/bot_unified_runtime/__init__.py:4504-4513`：`elif command_text == "download"` 分支的 `capability()` **没有任何 actor_roles 校验**；紧邻的 `reply`(`:4526`)、`群文件`(`:3432`)、`cookie`(`:3339`) 都有门。
`capabilities/download.py` 全文（121 行）**零 admin 校验**，`BotDecision.actor_roles` 从未被读；`downloader` 按 `bot_download_max_bytes` 默认 1GB 落盘、`bot_download_timeout_seconds` 默认 120s。
→ 任意普通用户可让 bot 拉取任意 URL（内网 SSRF 探测面 + 1GB 磁盘 + 长任务占池），重审计报告 §2「download.py SSRF 面 P3」在当前配置（`bot.download` 已在 `OFFLOADED_CAPABILITY_IDS:254`、命令 matcher 可达）下**真实可达**。

## E-9 C1[P0] 投递缺口在 HEAD 仍然存在（最严重功能性后果）

【已复现】对 HEAD 与工作树的 `__init__.py` 分别做窗口探测：
```
HEAD       _handle_image_search (line 3133): _find_sent_request=False  _deliver_transport_send_request=False
WORKTREE   _handle_image_search (line 3347): _find_sent_request=True   _deliver_transport_send_request=True
HEAD       parrot 投递标记 ('parrot_request = _find_sent_request') count: 0
WORKTREE   parrot 投递标记 count: 1
```
手册 §13.3 把该修复记为 **C1[P0]**：「搜图与群复读投递缺口……此前 pipeline 只入队、InMemory 队列回假 sent 回执，**默认配置下这两类消息永不发出**」。
→ **HEAD 上「搜图」与「群复读」两类消息依然永不送达**（用户侧表现为"没反应"）。

## E-10 审计脱敏正则漏 `*_token=` 形态（线4 发现，主代理独立复跑）

【已复现】`plugins/bot_unified_runtime/audit/logger.py:14-16`：
```python
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)\b(token|cookie|authkey|password|secret|api[_-]?key)\s*[:=]\s*[^\s;]+")
```
`\b` 要求关键字前为非单词字符，而 `access_token` 中 `token` 前是 `_`（单词字符）→ 不匹配。
主代理直接 `from plugins.bot_unified_runtime.audit.logger import redact_private_debug` 实跑 11 个真实形态：
```
[** LEAKED **] ws://127.0.0.1:3001/?access_token=ShoreKeeperSecretValue
[** LEAKED **] https://api.example.com/v1?refresh_token=rt_ABCDEFGHIJKLMNOP
[** LEAKED **] x-csrf_token=abcd1234efgh
[REDACTED] ?token= / api_key= / Authorization: Bearer / password= / cookie= / secret= / authkey= / sk-…
LEAKED count: 3 / 11
```
该函数是审计 private_debug、JSONL 文件日志（`audit/file_logger.py:34`）与 nonebot 日志桥（`sources/runtime_event_log.py:44`）的唯一屏障；`?access_token=` 正是本仓库 NapCat OneBot WS 的真实形态（`docs/napcat-setup.md:60`）。

## E-11 发送队列毒行「半修」（线2 发现，主代理读码复核）

【已复现】`sender/queue.py`：
```
440: def _finalize_expired_lease(...)   ← 90f590e 只给这里加了 try/except
438: return [self._entry_from_row(row) for row in refreshed]   ← claim_due 批量重读，无隔离
831: return self._entry_from_row(row) if row is not None else None   ← find_request，无隔离
833: def _entry_from_row(self, row): ... SendRequest.model_validate_json(str(row["request_json"]))  ← 无隔离
```
新增回归 `tests/test_bgroup_sender_delivery.py:233` 把毒行 `retry_count` 预置为 `max_attempts`，只覆盖终态化分支 → 首次认领路径无覆盖。手册/提交信息「queue 毒行 P1 已由 90f590e 修掉」为过度结论。

## E-12 未提交改动的域分布

【已复现】`git status` + `git diff --numstat`：63 个已跟踪 dirty 文件 = sources/ 18、capabilities/ 12、runtime/ 7、插件根 4、tests/ 4、policy/ 3、audit/ 2、character/ 2、contracts/ 2、output/ 2、docs/ 1、security/ 1、sender/ 1、scripts/ 1、仓库根 3。
增量最大：`__init__.py` +471、`runtime/pipeline.py` +147、`policy/rate_limit.py` +137、`capabilities/meme.py` +132、`sources/parsers/http_util.py` +123、`runtime/settings.py` +115、`config.py` +87、`sources/parsers/wbi.py` +74。
**15 个文件各新增 ≥50 行、55 个文件 ≥5 行**。

## E-13 死配置字段（主代理独立复现）

【已复现】全库扫描读取点：
- `config.py:257 bot_group_digest_enabled` → **除定义行外零读取**（死字段）
- 真开关 `config.py:256 bot_shared_group_context_enabled` → 唯一读取点 `character/shared_group.py:276`
- `.env` 两者均为 `false`
→ 手册 `:1332`「用户操作项：`BOT_GROUP_DIGEST_ENABLED=true`（如需"总结今日通讯"立即生效）」照做无效。

## E-8 第三方/声称抽查

- ffmpeg 依赖【已复现】：`grep -in ffmpeg plugins/**` 命中 74 处，定位逻辑在 `sources/downloader.py:283-298 _find_ffmpeg()`（显式配置 → `shutil.which` → winget 目录 `rglob("ffmpeg.exe")`）；`sender/nonebot.py:125-148` 用 `shutil.which("ffmpeg")` 转 OGG/OPUS。
- BOT_DOWNLOAD_PROXY 兜底代理【已复现】：全库仅剩注释/文档/测试中的 `127.0.0.1:7890`，无生产代码硬编码兜底（E1-9 修复成立）。
- randpic / reminder 接线【已复现】：`runtime/base_router.py:415-416` RouteRule + `__init__.py:3792-3793` matcher + `__init__.py:5602-5611` handler + `__init__.py:2682-2683` 调度注册 + `capabilities/echo.py:728/738-746` 帮助条目 + `config.py:231-238` 字段齐全。
