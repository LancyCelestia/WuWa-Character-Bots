# 事故卷宗 · 2026-09-30 源码树清空与恢复方案

> 状态：**未恢复**。本卷宗只出方案与判据，**不执行任何 git 写、不重启、不杀进程**（AGENTS.md 规则 4/7 + 常令：提交、推送、重启归用户）。
> 所有事实均为本席或席位**实跑取证**，命令可复跑。不确定处标「待验」。

## 一、事故事实（实测）

| 项 | 事实 | 取证方式 |
|---|---|---|
| 损伤 | 项目根只剩 12→41 枚文件、**2244 个空目录壳**；`plugins/**/*.py`=0、`tests/*.py`=0、`AGENTS.md`/`bot.py`/`.env`/`.env.prod`/`.git`指针/`docs/HANDBOOK.md`/`scripts/dev.ps1`/`personas/**` 全不在盘 | `find . -type f \| wc -l` |
| 时刻 | 逐层触碰窗口 **本地 15:22:38.17 → 15:23:19**，稳定 ~50 目录/秒，深度级联（`plugins/**` 深叶 15:22:57 → 其直属文件 15:23:10 → `tests/` 15:23:11）；`data/` 目录 birth **15:21:44**（⇒ 此前已有一次连目录一起删） | 目录 mtime 分布 |
| 范围特征 | 连 `.venv`/`.mypy_cache`/`.ruff_cache`/`.s249mypy_tmp`/`egg-info`/`node_modules`/`third_party` 一起清空 ⇒ **git 绝不碰 ignored 路径** | mtime + 内容普查 |
| git 侧 | HEAD 仍 `8ad03e4`（分支 `heads/v0.0.1-alpha.2`）、2285 枚 tracked、对象库完好；`logs/HEAD`、`refs/heads/*`、`index`、`COMMIT_EDITMSG` **全停在 03:46:45**；15:22 之后对象库**零写入**；无 `index.lock`/`HEAD.lock`/`MERGE_HEAD`/`refs/stash` | `git --git-dir=... rev-parse`、`ls` |
| index | **主 index 未损坏**（2285 条与 HEAD 逐条同 sha）。`fsck` 报的 `bad signature 0x00000000` 属 `git/worktrees/s58-baseline-wt/index` | 手工解析 DIRC v2 头 + `ls-files` |
| 现役进程 | 4 枚 `python.exe bot.py`（14:42 起，PID 14180 占 3.3 GB）仍在跑**事故前内存代码**；15:27:52/15:36:22 报 `bot.chat:CapabilityTimeout`，往 `data/cards/` 落了 4 张 error 卡 | 进程与日志普查 |
| venv | 生产 venv 在 `ChatBot_Runtime/venv`（**完好**，`Scripts/python.exe` 在）；源码树内那枚 `.venv` 是历史残留，与生产无关 | `ls` |
| 磁盘 | C 盘剩 126 GB ⇒ 非 ENOSPC；回收站无相关条目 | `df`/回收站普查 |

### 成因判定（席位取证，置信度标注）

- **①「某次以源码树为根的批量删除」＝高置信 ~85%**。判据：范围含 ignored 路径（git 不可能碰）、形态是「逐层 unlink + rmdir 被中断」、窗口内 `%TEMP%` 生成 ~45 枚 `qoder-*-cwd`（＝同时段有 Bash 工具调用在跑）。**具体命令原文与执行者：待验，未臆断**。
- ②外部还原失败 ~12%：无 reflog/对象/锁痕迹 ⇒ 排除 git 侧动作。
- ③磁盘异常 ~3%：骨架完好、无 IO 错误。
- **hooks 不是执行者**：`post-checkout`/`post-commit` 是 14:27:32 写的 **10 字节空 stub**（`#!/bin/sh`），无删除能力，且 `post-checkout` 在 checkout **之后**才跑。
- ⚠ 触发路径**仍然成立**（席位以工作树为 cwd 跑批量删除）。恢复后必须先立席位硬规（见第四节），否则还会再来一次。

## 二、可恢复性账（逐源实测）

| 内容 | 源 | 实测证据 | 可恢复度 |
|---|---|---|---|
| **2285 枚 tracked 全量** | `ChatBot_Runtime/git` HEAD `8ad03e4` | `git archive HEAD \| tar -t` = **2539 条目**，抽查 `AGENTS.md`/`bot.py`/`.env.example`/`config.py`/`__init__.py`/`docs/HANDBOOK.md`/`scripts/dev.ps1`/`personas/shorekeeper/identity.md`/`tests/conftest.py` **全在** | **100%** |
| **生产 `.env`**（368 键，含真实 key） | 六份逐字节相同副本，md5 `b0a66d1d…`／27,988 B。首选 `AppData/Local/Temp/bot-head-baseline/.env`（mtime 09-30 04:51）；次选 `AppData/Roaming/Code/User/History/-766d3dec/0O82`（VS Code 本地历史，**不受 Temp 清理影响**） | 键数与指纹实测一致；`.gitignore:23-25` 排除 ⇒ git 里永不可能有 | **100%**（但**必须今天就搬出 Temp**） |
| **`.env.prod`**（NoneBot 框架键 + **SnowLuma WS token**） | `AppData/Local/qoder-m2-02/ChatBot/.env.prod`（1,530 B／7 键／09-29 04:16）——**全网唯一一份** | 逐源普查确认唯一 | **单点，最高优先抢救** |
| **台账 #71 波未提交 WIP** | `Temp/r101/wt2`（8 件 +1475/−196：`.env.example +276`、`__init__.py +786`、`config.py +122`、`meme/reactions/engine.py +249`、`ops/smoke/diagnostics.py +182`、`user_copy.py +21`、`vision_describe.py ±11`）+ 2 枚未跟踪新件 `domains/ops/network_patrol.py`(6907 B)、`tests/test_network_patrol.py`(5812 B)；**并用** `Temp/r101/wt`（`media/digest.py +22`、未跟踪 `meme/capabilities/randpic_timing.py` 7748 B） | `git diff --stat 8ad03e4` 现算；两支文件集**互不覆盖，必须并用** | **可复原**（#68 三源法） |
| **AGENTS.md 台账 `| 71 |` 行** | `.qoder-cn/file-history/1dfa5538-9d75-4540-b4a6-57aca5733b5a/4a1e60a0-d5ae-4f7e-b50d-f9a540299ed1@v1`（mtime 15:19，含 #70/#71 终态） | grep `71 |` 命中 | **可复原** |
| 其余未提交 WIP（约 507 条中的非 #71 部分） | 对象库 315 枚孤儿 blob **全部比 HEAD 旧** ⇒ 无货；只能走 file-history（`.qoder-cn` 4242 条，末段 15:19；`.qoder` 543 条）＋ VS Code/编辑器历史 ＋ 会话 transcript ＋ `ChatBot_Archive/2026-09-29/wip-snapshot/*.zip`（241 件，本地 09-29 07:52，**偏旧且不能当还原前基线**） | `cat-file --batch-all-objects` 全库探针 | **部分**（file-history 约覆盖 155/507 ≈ 31%，按最后编辑日代理尺） |
| `probes/`（gitignored） | `Temp/bot-gates/probes`、`Temp/wave30/probes` | 副本普查 | 可复原 |

**已灭失（checkout 回不来，须重建）**：`security/injection.py` 内的 `strip_injection_instruction_spans`/`_injection_match_view` 合并（**注意**：同名函数在 HEAD 的 `capabilities/chat.py:823/1026` 活着 ⇒ 这是「接线/合并」不是从零重写）；`bot_affinity_v8_*`/`bot_affinity_goodwill_band_*` 的 config 字段与读点（HEAD 全树零命中，只存在于 `docs/affinity-design.md:352,427-429` 的规格文字 ⇒ 文档虚报在册，违反规则 10）。

## 三、恢复动作序列（**由用户执行**；每步都有前置判据）

```bash
# 变量（先贴这一段）
ROOT="C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
G="C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/git"
SAFE="$TEMP/chatbot-restore-20260930"        # 仓库外，绝不落在源码树里
mkdir -p "$SAFE"
```

**第 0 步 · 先抢救单点，再谈恢复**（`.env.prod` 与 Temp 里的 WIP 副本都随时可能被清理）
```bash
cp -a "$G" "$SAFE/git-mirror"                        # 整份 gitdir 镜像（objects+index+worktrees+logs）
cp -a "C:/Users/LancyCelestia/AppData/Local/qoder-m2-02/ChatBot/.env.prod" "$SAFE/"
cp -a "C:/Users/LancyCelestia/AppData/Local/Temp/bot-head-baseline/.env"   "$SAFE/env-prod-copy"
cp -a "C:/Users/LancyCelestia/AppData/Local/Temp/r101"                     "$SAFE/r101-worktrees"
cp -a "C:/Users/LancyCelestia/.qoder-cn/file-history"                      "$SAFE/file-history"   # 4242 条，体积大，可先只挑 09-30 的
```
**绝对禁止**（一次就永久清零）：`git gc`、`git prune`、`git worktree prune`、`git fsck --lost-found`、`git expire-ref`、清 `%TEMP%`。315 枚孤儿 blob + 45 枚悬挂 stash 提交 + `r101/wt*` 是仅存副本。

**第 1 步 · 补回 `.git` 指针**（被删的是工作树里那枚指针文件，gitdir 本体完好）
```bash
printf 'gitdir: %s\n' "$G" > "$ROOT/.git"
git -C "$ROOT" rev-parse HEAD          # 期望 8ad03e4…；若失败则全程改用 --git-dir/--work-tree 形式
```

**第 2 步 · 还原 2285 枚 tracked（只写工作树，不动 HEAD/index）**
```bash
git --git-dir="$G" archive --format=tar HEAD | tar -x -C "$ROOT"
git -C "$ROOT" status --porcelain | head        # 期望：只剩少量 ?? 与 1-2 枚 M（config-catalog 等）
ls "$ROOT/AGENTS.md" "$ROOT/bot.py" "$ROOT/plugins/bot_unified_runtime/config.py"
```
> 不要 `checkout -f`/`reset --hard`：那会顺手动 index 与 reflog，且当前 index 与 HEAD 同 sha，没必要冒风险。

**第 3 步 · 落回配置**
```bash
cp "$SAFE/env-prod-copy" "$ROOT/.env"
cp "$SAFE/.env.prod"     "$ROOT/.env.prod"
md5sum "$ROOT/.env"      # 期望 b0a66d1d…（与事故前生产件同指纹）
```
待办：`.env` 相对 `.env.example`（678 键模板，最全的一份在 `Temp/r101/wt2/.env.example`）**缺 330 枚**，其中 60 枚走代码默认、需在恢复后显式表态：`BOT_NETWORK_PATROL_{ENABLED,DOMAINS,INTERVAL_MINUTES}`、`BOT_FILES_WRITE_*`、`BOT_STICKER_PRIVATE_*`、`BOT_REPLY_DEFAULT_DIRECTIVES`、`BOT_SAFETYEXEC_ENABLED`、`BOT_PROTOCOL_CLIENT_DIR`。上游 18 枚模型 token 不在 `.env`（名册存证在 `ChatBot_Runtime/config/env-upstream-tokens-20260928.txt` + AxonHub 自带库）。

**第 4 步 · 按 #68 三源法并回 #71 波 WIP**（wt2 与 wt **并用**，逐文件按内容认领，禁整树覆盖）
```bash
# 只读开差异账，再逐件决定取谁
git --git-dir="$G" --work-tree="$SAFE/r101-worktrees/wt2" diff 8ad03e4 -- plugins/bot_unified_runtime/__init__.py
# 未跟踪新件直接按路径落回（这两枚 HEAD 没有）
cp "$SAFE/r101-worktrees/wt2/plugins/bot_unified_runtime/domains/ops/network_patrol.py" "$ROOT/plugins/bot_unified_runtime/domains/ops/"
cp "$SAFE/r101-worktrees/wt2/tests/test_network_patrol.py"                              "$ROOT/tests/"
cp "$SAFE/r101-worktrees/wt/plugins/bot_unified_runtime/domains/meme/capabilities/randpic_timing.py" "$ROOT/plugins/bot_unified_runtime/domains/meme/capabilities/"
```
台账行复原：从 `$SAFE/file-history/1dfa5538-9d75-4540-b4a6-57aca5733b5a/4a1e60a0-d5ae-4f7e-b50d-f9a540299ed1@v1` 取 `| 71 |` 行贴回 `AGENTS.md` 第六部分（**编号不许删不许重排**）。

**第 5 步 · 四道门复跑**（`BOT_AUTOSYNC=0` 是硬要求，否则生成物被悄悄 `--write` 洗绿）
```bash
BOT_AUTOSYNC=0 powershell -NoProfile -EP Bypass -File scripts/dev.ps1 -Task runtime-layout
BOT_AUTOSYNC=0 powershell -NoProfile -EP Bypass -File scripts/dev.ps1 -Task typecheck
BOT_AUTOSYNC=0 powershell -NoProfile -EP Bypass -File scripts/dev.ps1 -Task test     # 预期非零，取末行计数与 HEAD 基线比
```
基线：全量 pytest 事故前最近一次 **398 failed / 19,893 passed**；判红归属按 #68★ 方法（`git archive HEAD` 抽到仓库外同尺复跑、按节点 ID 分桶）。

**第 6 步 · 重启归你**：源码 + `.env` + 四道门三者齐了再重启。在那之前**现役 bot 是 QQ 唯一在线通路，禁杀禁重启**——它一退就再也起不来（第 2 步之前尤甚）。

## 四、防复发（恢复后立刻做，按序）

1. **席位硬规**：删除类命令一律显式指向 `%TEMP%` 下的独立目录、必须先 `--dry-run` 出清单；**禁止以工作树为根**的 `Remove-Item -Recurse`/`find -delete`/`rm -rf`。已确认 `runtime_layout_smoke.py:115-116` 只扫 `pyc/pycache` ⇒ 门抓不到 `.mypy_cache`/`.ruff_cache`，"清理这两类"是合法需求但不能裸跑。
2. **给 bot 上解耦保险**：在 `ChatBot_Runtime/` 建一份 `git archive HEAD` 出的**可启动镜像**，让源码树再被清也能重启。
3. **快照节拍**：每小时 `git archive HEAD`（tracked）+ `git diff`（未提交 WIP）**双份出机**；`.env`/`.env.prod` 纳入出机面。
4. **台账登记**：本次两条时刻（15:21:44 连目录删、15:22:38–15:23:19 逐层 unlink）登记为新台账行，`AGENTS.md` 只留一行指针（规则 10）。
5. 别清 `%TEMP%`：`bot-probe-W12`（2288 枚 ≈ HEAD）、`bot-head-baseline`、`r101/wt*`、`bot-gates/probes`、`wave30/probes` 现在都是证据与恢复源。

## 五、恢复后立刻要打的补丁（P0，已按 **HEAD 实测行号** 校正）

| 缺陷 | HEAD 真身 | HEAD 行号 | 补丁落点 |
|---|---|---|---|
| 渲染回源图零咽喉 + 默认跟随重定向 | `domains/render/render_backends.py` | `_ORB_FETCH_OPENER` 43；`_fetch_image_bytes` 89-112（`.open` 98）；`_orb_route` 617-630 | 98 前插逐跳复查 handler，**复用** `link_parse/parsers/http_util.py:472 _GuardedShortLinkRedirectHandler` |
| 重定向落点「事后」复查（盲 SSRF） | `domains/food/capabilities/eat.py` | 344 `geturl()` → 345 复查（在 343 `urlopen` **之后**） | 339-343 换 `_guarded_image_opener()` 形态（同 vision 腿） |
| 无头浏览器 goto 无闸 | `domains/link_parse/fetchers/playwright_backend.py` | 76、130（全文 142 行） | 54/86 入口各加 `guard_user_url`（`ssrf_guard.py:159`） |
| DNS 判后即弃（rebinding） | `domains/files/sources/downloader.py` | `check_download_url` 363-414，`getaddrinfo` 406，残余自陈 373-375 | 406 起把 `resolved` 传出并钉 connect hook |
| 本地路径无域门 → 任意文件读+外发 | `domains/media/ingest/vision_describe.py` | `_local_path_from_value` 183-206（只 `is_file()`）；`_image_file_to_data_url` 314-355；`_encode_image_bytes` 209-210 | 183-206 加 `path_gate.is_within_registered`(`domains/media/path_gate.py:224`) 或 `safety_exec/paths.py:317 check_sendable`；消费方 `transcribe.py:34,81,107`、`video_understanding.py:35,165`、`video/video_pipeline.py:81,93` 同刀 |
| 同名第二 def 未收敛 | `domains/media/registry/vision_caption_cache.py` | 87-104（第二份 `_local_path_from_value`） | 与上条合并为单一带门判据（禁第三套） |
| 规则匹配吃原始文本 | `domains/chat_reply/security/injection.py` | `_rule_hit` 210-223；调用 463 | 接 `chat.py:823` 的归一视图，210 改吃视图 |
| 裸拼注入五腿 | `memory_extract.py` 66/233；`reflection.py` 721/724；`schedule/llm_draft.py` 295 + `_build_actions` 261-277 | 见左 | 套 `injection.py:295 guard_secondhand_text`；llm_draft 273 前加动作白名单 |
| 打码形态缺口 | `domains/render/plain_text.py` | `redact_local_secrets` 340-364，形态表 303-337（7 条） | 303-337 增表 + 348-352 哨兵同步 |
| 未列名群 + 命令态一律放行 | `policy/gate.py` | 351-356、404-413（fall-through `allowed=True`） | 282 后加「群不在四册 ⇒ 拒」 |
| 安静时段旁路过宽 | `policy/quiet_hours.py` | 111-116、117-122、123-128（私聊全排除）、135-140（`@` 或非 bot.chat **任一**即旁路） | 135 改 `∧`；123 会话册默认含私聊 |
| 命令腿零限流 | `policy/rate_limit.py` | InMemory 478/508-512、SQLite 1179/1206-1210、`CHAT_CAPABILITY_IDS` 25；调用侧 `runtime/pipeline.py` 1101-1107/1112 | 508/1206 改为仅「@bot 或显式命令」 |
| 完成链同步阻塞事件循环 | `runtime/pipeline.py` | `_complete` 1203；同步调用 1722、**1911**（缺省 `enricher=None` ⇒ 循环线程跑渲染+sqlite）；渲染 1293 | 1911 一律 `to_thread` |
| 渲染 20s 超时不取消 + 单工作线程头阻塞 | `domains/render/renderer.py` | 244 `_MERMAID_CALL_TIMEOUT_S=20.0`、273-276 `max_workers=1`、296-297 `future.result` | 297 后 `future.cancel()` + 池换代；或把总预算上提为总闸 |
| async 内同步 sqlite | `domains/transport/sender/worker.py` | `drain_send_queue_once` 256 async；269 `_claim_or_list_due`、290 `_has_more_due` | 269/290 包 `to_thread` |
| 写腿 `BEGIN` 与 `_transaction_immediate` 双标 | `domains/transport/sender/queue.py` | 367-370 `RLock`、397-401 `check_same_thread=False,timeout=5.0`、417-436 `_transaction`、439-468 | 417 统一 IMMEDIATE 或改 per-call 连接 |
| 影子竞速裸起线程（无界） | `chat_reply/llm_engine/model_router.py` | `_launch` 1575-1593（`threading.Thread(daemon=True)` 1579/1593），候选数无上限 1595-1607 | 1579 换有界池 + 上限 |
| 审计库无 timeout + 每 append 跑 prune | `domains/ops/audit/logger.py` | `_connect` 204-205；`append` 107-152（152 `_prune`） | 205 加 `timeout=`；152 摊销 |
| 超时预算每腿一份（最坏 2×600s） | `runtime/capability_protocols.py` | 479 `_MAX_TIMEOUT_SECONDS`、482-500 `_attempt_budget`、**858**（降级腿再取一份，825 自陈不减已烧） | 858 改剩余预算，或与 `pipeline.capability_hard_timeout_seconds`(429) 取 min |
| error 卡向群内非管理员泄露栈帧与配置键 | `domains/ops/monitor/error_report.py` + `card_render/templates/error_card.html` | 栈摘录 369-384（默认 8 帧，`config.py:1074`）、`config_pairs/env_pairs/version_pairs` 全渲染（`error_card.html:200-202`）；群态只做了联系方式分级（1100-1148） | 新建**受众分级裁剪门**：群态不吐栈帧/模块名/配置键 |
| 能力自述越册（假手册真因） | `capabilities/chat.py` → `character/temporal.py` | `_system_readout_section_text` 2304-2331 → `capability_index_lines` **677**（裸主题名列举）；软提示 721；`/bot help` 全确定性（`echo.py` 零 LLM import） | 新 `tests/test_capability_self_description_gate.py`（出站文本能力名 ⊆ 在册集，注毒自证 + 在册名放行防恒红）；裸主题名改「主题名 + `/bot help <主题>` 指路」 |
| 文档虚报 v8 键在册 | `docs/affinity-design.md` 352,427-429 vs `character/affinity.py` 读点 914-925（12 枚全为 `bot_affinity_*`/`_v7_`） | 见左 | 三面补（config + `settings.py` 热改登记 + `.env.example`）**或**改文档；`_PASSIVE_DECAY_ENABLED` 由硬常量升配置键 |

**不需重建**（HEAD 已具备，别当 WIP 产物找回）：`vision_describe._guarded_image_opener` 380-396 + `_download_image_bytes` 406-444 的逐跳复查；`eat.py:345` 落点复查；`ssrf_guard` 整型 IP 归一 48-116 与「解析失败=拒绝」；`queue.py` 认领台账 476-569；`capability_protocols` 的 `_attempt_budget` 单一出处 629 纪律。
