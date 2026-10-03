# B1 · TTS 合成缓存缺省面 + yt-dlp 落盘名消毒（P3.8 / P3.9）

席 B1 · 波次 `2026-10-02-fixwave` · 开工 2026-10-02 01:0x–01:4x（本地，UTC+8）
起点 HEAD `5d581b2`（全程零 git 写、零进程动作、零外发、零配置改）

配套件：`patches/B1-CONFIG-REQUEST.md`（两枚配额缺省的四面需求）

---

## §1 现状核实（带 file:line；行号按本席现算，会漂 ⇒ 定位优先按符号名）

### ① TTS 合成缓存

**简报那句「TTS 合成缓存开关缺省为 `0`（关）」与现算不符，方向相反。** 住 `0` 的是**配额**，不是开关：

| 事实 | 真身 | 现值 |
|---|---|---|
| 缓存开关 | `plugins/bot_unified_runtime/config.py:589` `bot_tts_cache_enabled` | `True`＝**默认就缓存** |
| 字节配额 | `config.py:593` `bot_tts_cache_max_bytes: Field(default=0, ge=0)` | `0` |
| 天数配额 | `config.py:594` `bot_tts_cache_max_age_days: Field(default=0, ge=0)` | `0` |
| `0` 的语义 | `domains/chat_reply/runtime/cache_policy.py:23` 文件句 + `:54/:58` 两条腿 | `<=0`＝**不限制** |

⇒ 现网形态＝**默认在缓存、默认不收盘**。`docs/HANDBOOK.md:5725` 那行「TTS 缓存缺省 0」记的就是配额两枚，
措辞容易被读成开关（本席禁写 HANDBOOK，纠偏口径以本件为准，请主会话落账）。

消费点（六枚字面 `getattr` 读点，全在 `domains/media/capabilities/tts.py`）：

- 开关：`cache_enabled=bool(getattr(config, "bot_tts_cache_enabled", True))` 三枚调用路各一次
  （命令路 `capability`、自动配音 `synthesize_autodub`、富化钩子 `maybe_attach_voice`；现算行 1241 / 1615+ / 1747+）。
- 配额：同一批行 `quota_max_bytes=int(getattr(config, "bot_tts_cache_max_bytes", 0) or 0)`
  + `quota_max_age_days=…`（现算 1246-1247 / 1620-1621 / 1752-1753）。
- 唯一落盘出口：`tts.py:synthesize`——产物过「结构体检 + 静音指纹 + 字节顶（`bot_tts_max_audio_bytes` 缺省 8 MiB）」
  之后才写 `tts-<uuid4hex>.wav`（M-39 随机名，**不留内容指纹名**），落盘点顺带算 `media_digest`。
- 目录真身：`tts.py:_output_dir` → `config.bot_tts_output_dir`（在 `config.py` 的 PATH 重映射名册里）
  → 空值兜底 `scripts/runtime_paths.runtime_path("data/tts_output")` ⇒ 生产落 `ChatBot_Runtime/data/tts_output/`。
- 内存索引：`tts.py:169 _CACHE_LRU_CAP = 512`、`_lookup_cache` / `_store_cache`（:581 / :593）
  ⇒ **键数封顶，文件不封顶**。
- 热改档：`domains/chat_reply/runtime/settings.py:595-603` 三枚均登记「读装配期 config、覆盖不可达」
  ⇒ 拨这三枚要改 `.env` + 重启（台账 #3★ / #10★ 同族）。
- 覆盖册有没有罩住缺省（台账 #50★ 那一咬要排除）：read-only 连 `ChatBot_Runtime/data/control_plane_config.sqlite3`
  的 `config_overrides` ⇒ 总 9 行、**TTS 键 0 行**（复跑命令见 §3）。生产 `.env` 只设了 `BOT_TTS_ENABLED=true`（:431），
  `BOT_TTS_CACHE_*` 三枚未设 ⇒ 生效值＝代码缺省。

「打开后落哪、会不会涨爆」——现盘只读取证（`du` + python 现算，@2026-10-02 01:3x 本地）：

```
files 24  total_bytes 30927136  total_MiB 29.49
min 107564  median 1589804  max 2406444  avg 1288630
uuid_named 23  legacy 1        ← e0dc91675ec1f1e5f733.wav（M-39 之前「内容指纹名」那一代的遗留）
first 2026-09-18 11:15  last 2026-09-27 19:18  span_days 9
per_day_files 2.67  per_day_bytes 3.28 MiB
by_day [('2026-09-18',1) ('2026-09-24',14) ('2026-09-25',2) ('2026-09-26',3) ('2026-09-27',4)]
```

**判定：会涨，且今天没人收。** 三格证据：① 缺省 0/0 ⇒ `synthesize` 里 `if quota_bytes > 0 or quota_age_days > 0`
永假（`tests/test_tts_contract_layer.py::test_quota_off_by_default_is_no_call` 在册）；② 缓存身份是**内存** LRU
⇒ 重启即冷，同一句话重启后再合成会写**第二枚** uuid 文件，前一枚当场成孤儿（盘上那枚 legacy 名文件＝24 枚里
的 4% 已经无人可寻，`docs/boards/B06-media-entertainment/tts/README.md:119-120` 早把这笔记成 P2）；
③ LRU 淘汰只踢索引、不删盘。**⇒ 无上界**（`8 MiB/枚 × 无界枚数`）。

### ② yt-dlp 落盘名未消毒

全树 `outtmpl` 只有一枚（`grep -rn "outtmpl" --include=*.py plugins tests scripts` 现算＝1 命中，另有文档 1 命中）：

- `domains/files/sources/downloader.py:944` `"outtmpl": str(self.download_dir / "%(id)s.%(ext)s")`。**本席禁写面。**
- **关键纠偏（实测，不是推测）**：yt-dlp `2026.08.19` 自己已经把模板值里的分隔符折成单段名——
  `prepare_filename` 离线读数：`'../../evil' → '..⧸..⧸evil.mp4'`、`'..\..\evil' → '..⧹..⧹evil.mp4'`、
  `'a/b' → 'a⧸b.mp4'`、`'x:' → 'x：.mp4'`、`'' → 'NA.mp4'`（复跑 `python patches/…` 见 §3 命令）。
  ⇒ **写盘那一腿被库兜住**，本仓没消毒但也不是当前那条腿在漏。真洞在同文件里**本仓自己拼**的两枚名字：
  - `downloader.py:959-961`：`path = str(Path(self.download_dir) / f"{info.get('id','video')}.{info.get('ext') or 'mp4'}")`
    —— raw，不经库消毒；只有在 `ydl.prepare_filename(info)` 的结果**不在场**时它才会被替换掉（:962-968），
    而 `download()`（:1028）拿 `Path(outcome.path).exists()` 一判就把它当成品返回 ⇒ 一枚「prepared 缺席、
    raw 命中已存在文件」的 id 就是容器外路径。
  - `downloader.py:984`：`self.download_dir.glob(f"{stem}*")`，`stem` 兜底取 `str(info.get("id"))`
    —— 把远端 id 当**glob 模式**。实测（`tempfile` 造容器 + 容器外一枚 `notes/private.srt`）：
    `downloads.glob("../notes/private*")` 与 `downloads.glob("../*/priv*")` **都命中容器外那枚**，
    且 `[ ] * ?` 被当模式解释。⇒ 这条路把容器外文件的**字节读成字幕文本**进 `meta`（`domains/files/capabilities/download.py`
    再把它交给模型），比外发文件段更安静。
- 第二枚消费者（**本席未动**）：`domains/link_parse/capabilities/content_parser.py:906` 同样把 `outcome.path`
  直接构 `video` 部件随卡片发送（`/bot download` 之外的自动腿）。
- `is_file(` 那格：本席新增代码零 `is_file()` 直呼、零 `Path(外来串).is_file()`，AST 禁词表（
  `tests/test_vision_local_path_domain_gate.py::_is_file_sites`）不适用也不绕。

---

## §2 改法与理由（本席真正动了的两处）

1. **`domains/media/capabilities/tts.py`：配额形态闸 `_quota_bound`**（新增 1 枚私有函数 + `synthesize` 清理腿改 2 行）。
   非负整数之外的形态（`bool` / 负数 / 浮点 / 字符串 / `None`）一律当「未设」＝0，绝不触达 `enforce_quota`。
   理由（实测前提）：`pydantic 2.13.4` 的 `int` 字段在 lax 模式吃布尔（`True → 1`，同尺复跑见 §3），
   于是 `int(True)==1` 把「字节上限」执行成「把 `data/tts_output` 清空」，**一路删到刚写下的那一枚**为止，
   调用方返回的 `target` 当场成死引用（发送侧 M-38 摘段＝整段语音消失）。真中央件重现＝
   `test_one_byte_quota_really_does_empty_the_directory`（`max_bytes=1` ⇒ 3 枚全删）。
   刻意**不做**的两件事：① 「读不出键即回落 `Config` 缺省」（`music.py::_music_cache_quota_bytes` 的 W7 同形）
   —— 那要把 6 枚字面 `getattr` 读点重排成 2 枚，动的是别席在飞的**直读维台账**，见 §5；
   ② 「LRU 淘汰即删盘」—— 发送队列可能还引用那枚路径，且那是第二把尺。
   **`0/0＝不限制` 的 U-04 语义一字未动**（管理员显式设 0 仍受尊重）。
2. **`domains/files/capabilities/download.py`：消费侧落点门**（+78 行 −9 行）。
   `outcome.path` / `outcome.subtitle_path` 先过 `domains/media/path_gate.contain_within`（容器门唯一真身，
   判据零副本、转调），过门后**只用折算后的路径**去回显、去 `video.file`、去读字幕文本；
   拒时只交代号（`audit_tags` 带 `gate_code=<代号>`），**不回显路径原文**。容器根只取下载器自己那枚
   `download_dir`（装配点已按 `bot_download_dir` 折进 Runtime），读不出＝空根 ⇒ 真身自己判「越界」＝fail-closed。
   降级是「只回文字、不发文件」，不阻断聊天。
3. 新建两把锁（43 格，全离线）：`tests/test_tts_cache_quota_shape_guard.py`（22 格）、
   `tests/test_download_artifact_container_gate.py`（21 格，含装配侧存量的**零余量棘轮**与两把尺的注毒自证）。

---

## §3 判据读数（实跑末行原样；卫生前缀一字未改）

新增两把锁（注毒腿 + 反向不误伤腿齐）：

```
$ … -m pytest -p no:cacheprovider --basetemp="$TEMP/qoder-B1/bt" -q \
    tests/test_download_artifact_container_gate.py tests/test_tts_cache_quota_shape_guard.py
43 passed in 22.14s
```

关键格（标题逐枚）：`test_bool_quota_never_reaches_the_sweeper` /
`test_int_quota_is_forwarded_verbatim` / `test_one_byte_quota_really_does_empty_the_directory` /
`test_default_quota_leaves_every_artifact_on_disk` / `test_lru_eviction_bounds_memory_only_not_the_disk` /
`test_synthesize_callsite_roster_matches_the_tree_exactly` / `test_callsite_scan_has_teeth`；
`test_hostile_derived_name_is_refused_before_any_byte_is_read[…7 形参各一]` /
`test_subtitle_outside_container_refuses_the_whole_artifact` / `test_unreadable_container_root_fails_closed` /
`test_ordinary_artifact_is_gated_and_returned_resolved` / `test_nested_but_inside_name_is_contained_not_rejected` /
`test_derived_name_sites_match_the_baseline_exactly` / `test_derived_name_scan_has_teeth` /
`test_derived_name_scan_does_not_flag_gated_code`。

起点读数（本席动任何代码之前，同一把尺）：

```
tests/test_tts_contract_layer.py tests/test_tts_presets.py tests/test_f03_notice_redaction.py \
tests/test_content_video_auto_send.py tests/test_media_path_gate.py
1 failed, 88 passed, 2 warnings in 4.53s      ← 那一枚红＝test_media_path_gate.py::test_single_containment_judgement_site
                                                 （randpic 里有 is_relative_to，别席 meme 面，HEAD 既存）
```

取证脚本（只读，可复跑；仓外 `$TEMP/qoder-B1/` 下）：
`probe_db.py`（覆盖册 TTS 键 0 行）、`probe_ydl2.py`（yt-dlp `prepare_filename` 折叠读数）、
`probe_glob.py`（`glob("../notes/private*")` 打到容器外）、配额分布统计（§1 那份 24 枚/29.49 MiB 现算）。

三门读数（`scripts/dev.ps1`；全树计数随并发在飞漂移 ⇒ 一律按**当时值**记，判据只认「本席四枚文件」那一格）：

```
lint        ：本席四枚文件单独跑「All checks passed!」（复跑命令＝ruff check <四枚路径>，见下）；
              全树当时值 45 红（@01:36），逐枚点名全在别席在飞件
              （tests/test_store_write_trace_d2.py、plugins/…/runtime/db_backup.py、tests/test_error_copy_pool_gate.py …）
typecheck   ：当时值「Found 6 errors in 3 files (checked 608 source files)」——三枚文件
              core/contracts/errors.py、runtime/db_backup.py、character/quirks.py，**零枚属本席**
runtime-layout：当时值 FAIL「source workspace contains 2 Python cache path(s)」
              ＝ plugins/bot_unified_runtime/runtime/__pycache__ 与其内 db_backup.cpython-312.pyc（01:20 落地，
                属席 X1b 的新件，非本席产物）。收工时同一把尺已变成三枚 .pyc 在长（02:03，见 §4 末自查段）
```

本席四枚文件的单独复跑（这条才是本席能签的）：

```
$ PYTHONDONTWRITEBYTECODE=1 RUFF_CACHE_DIR="$TEMP/qoder-B1/ruffcache" ruff check \
    plugins/bot_unified_runtime/domains/media/capabilities/tts.py \
    plugins/bot_unified_runtime/domains/files/capabilities/download.py \
    tests/test_download_artifact_container_gate.py tests/test_tts_cache_quota_shape_guard.py
All checks passed!
```

---

## §4 净新增红 A/B（`git archive HEAD` 仓外副本，同一把尺，按 node ID 分桶）

| 尺（测试集合） | HEAD 副本 `$TEMP/qoder-B1/head` | 工作树（含本席改动 + 别席在飞） | 红差 |
|---|---|---|---|
| 本席域八枚既存件（`test_tts{,_contract_layer,_presets}`、`test_f03_notice_redaction`、`test_content_video_auto_send`、`test_media_path_gate`、`test_vision_local_path_domain_gate`、`test_safety_exec_paths`） | `1 failed, 222 passed, 2 warnings in 18.83s` | 同一把尺加本席两枚新件后 `1 failed, 265 passed, 2 warnings in 44.17s` | **同一枚 node ID**：`tests/test_media_path_gate.py::test_single_containment_judgement_site`（randpic 的 `is_relative_to`，meme 面属别席）。265−222＝43＝本席新增格数 ⇒ 既存格一枚没少、一枚没多红 |
| 外扩六枚（`test_orchestration_callsite_wave3_c`、`_wave_media`、`test_descriptor_wiredness_ledger`、`test_file_gateway_phase1`、`test_media_registry`、`test_voice_outbound_contract`） | `116 passed in 74.89s` | `1 failed, 115 passed, 1 warning in 59.30s` | 新红 node ID：`test_descriptor_wiredness_ledger.py::test_funnel_arm_lock_has_teeth`。**非本席**：失败原因是 conftest 的源码树 `data/` 卫生门逮到该测试**在自己 call 阶段**往 `ChatBot/data/control_plane_config.sqlite3` 写文件（台账 #1 复发；`control_plane` 写侧属席 D2/G1 面）；单跑该格 `1 passed in 15.05s`（同一次复跑后 `ChatBot/data/` 那枚残留随之消失，本席**未删任何东西**）⇒ 别席在飞件的隔离/顺序问题，非本席判据 |

### 4b 归属实验（把「是不是我造成的」做成读数，不做成说法）

`cp -a plugins scripts tests bot.py pyproject.toml → $TEMP/qoder-B1/preB1`，再把**本席两枚生产件回写成
`git show HEAD:<path>`**、删掉本席两枚新测试 ⇒ 得到「别席在飞 + 本席未改」的对照树，同一把尺复跑三本台账门：

```
（pre-B1 对照树）24 failed, 122 passed in 483.58s (0:08:03)
  与本席工作树同名的红逐枚复现：
  test_config_key_registration_ledger.py::test_poison_11_new_field_floor_tracks_the_field_set
  test_config_key_registration_ledger.py::test_poison_14_direct_read_floor_biteth_both_ways
  test_config_key_registration_ledger.py::test_poison_15_py_file_floor_biteth_both_ways
  test_config_key_registration_ledger.py::test_poison_16_floor_boundary_shape_lock
  test_capability_manifest_gate.py::test_leg7_coverage_ratchet_never_rises
  test_capability_manifest_gate.py::test_leg8_direct_callsites_declared_match_census
  test_capability_manifest_gate.py::test_poison_callsite_new_site_not_followed_is_red
  test_board_taxonomy_gate.py::test_r0_registered_columns_stay_wired_to_the_scan
```

⇒ 这些红**与本席改动无关**（回写掉本席改动照样红；成因＝别席在飞的生产件 + 对照树缺 `docs/` 与 `.env`）。
`test_ssrf_throat_coverage.py::test_meme_listener_allows_public_redirect_chain` 同格归 meme 面（别席，本席禁写面）。

⚠ 本席为此把 `getattr` 只打在 `downloader` 接收者上（不新增 `config` 字面读点），正是为了不动直读维账；
上面 poison_14（直读维地板）在对照树里同样红 ⇒ 现账被别席的在飞件改动，非本席。

**本席结论（只签这一句）**：`本波域（TTS 缓存 + 视频入站落点门）净新增红 0`。**不签「全绿」**——
HEAD 基线自身在红（`test_media_path_gate` 那枚 + 全量 149 枚既存红，#72★ 同口径）。

源码树卫生自查（规则 6）：本席全程带 `PYTHONDONTWRITEBYTECODE=1` + `-p no:cacheprovider` + 仓外
`--basetemp`，直跑 `ruff` 另指 `RUFF_CACHE_DIR=$TEMP/qoder-B1/ruffcache` ⇒ 本席**没有**往源码树新增
`__pycache__`/`*.pyc`/`data/` 件（`ChatBot/data/` 那枚瞬时残留＝别席测试自写自清，本席未删任何文件；
`dev.ps1` 的 typecheck 会把 `.mypy_cache` 外置到自己管的目录，本席没动它）。

⚠ **runtime-layout 此刻仍 FAIL，成因不在本席**：`plugins/**` 里正在**持续**长出字节码件——本席收工时现算
`runtime/__pycache__/capability_protocols.cpython-312.pyc` mtime `02:03:15`，另有
`domains/chat_reply/runtime/__pycache__/deadline.pyc`、`domains/media/__pycache__/voice_enricher.pyc`
同批落地；而本席最后一次 pytest 收尾在 `01:56`，且全程带禁写字节码的环境变量 ⇒ 判为**并发别席直跑
python/pytest 未带卫生前缀**所致（本波已两次同类事故：433 枚 `.pyc` 那笔，台账 #72★ 同族）。
更早那一次 FAIL 读数是 `runtime/__pycache__/db_backup.cpython-312.pyc`（01:20，属席 X1b 新件）。
处置归主会话：按规则 6「先备份 `%TEMP%`、再逐枚点名清」，本席不删非本席产物，只留时刻与读数。

---

## §5 未尽事项与原因

1. **配额缺省**＝本席禁写 `config.py` ⇒ 精确需求 + 阈值依据 + 四面清单 + 同批要跟的锁，全在
   `patches/B1-CONFIG-REQUEST.md`（A 案 256 MiB/30 日，B 案 512 MiB/60 日，两案都「落地当天零删除」；
   保守两步＝先只开天数档）。**没开配额之前，`data/tts_output` 仍是无上界目录**——这一格只能由主会话落。
2. **装配侧三枚存量未修**（`domains/files/sources/downloader.py`＝本席禁写面，实锤一次越界读取形态见 §1②）。
   棘轮 `DERIVED_NAME_BASELINE` 现录 3 格（`(file, 函数, 形态代号)`，**不写行号**）。提案改法，逐枚：
   - `_download_once`（`outtmpl-literal`）：模板本身**可以留**（库已折叠分隔符，§1 实测），
     但落点名必须**只认** `ydl.prepare_filename(info)`；取不到即 `DownloadOutcome(error="落盘名不可确认")`，
     **删掉 :959-961 那枚 raw 自拼**。随后 `path_gate.contain_within(prepared, [self.download_dir])` 复核一次，
     过门后的**折算路径**才进 `outcome.path`（判定与执行同形态）。
   - `_download_once`（`derived-name-literal`）：同上——raw 拼名整腿消失即该格清零。若因合并产物（`.mp4` 替身那腿）
     必须保留自拼，名字先过中央消毒口 `domains/transport/sender/file_gateway.py:sanitize_file_name`
     （取 basename、剥控制字符与显示伪装），再过容器门：两把尺各管一段（形态 vs 归属），与 `path_gate` 文件头口径一致。
   - `_locate_subtitle_file`（`derived-name-var`）：模式串**不许吃远端 id**。改 `download_dir.iterdir()` +
     `name.startswith(literal_stem)` 字面比（`literal_stem` 先过 `sanitize_file_name`），或 `glob.escape(stem)`；
     命中结果仍过一次容器门。
   - 落地判据：本席棘轮会从 3 格掉到 0 格；**同批把 `DERIVED_NAME_BASELINE` 改成空表**并留本件指针
     （台账 #68★：退役要「文件 + 账本行」同批动，只动一边必红另一边）。
3. **第二枚消费者未修**（`domains/link_parse/capabilities/content_parser.py:906` 自动随卡发视频）：
   link_parse 属热面、卡片主链路归主会话，本席不动。改法与 `download.py` 那两处同形
   （`_download_container_root` + `_gate_artifact` 两枚薄壳可由本席件转调，或把同判据在 link_parse 侧转调一次），
   落地时请把 `bot.download` 的 audit 代号 `artifact_refused_by_container_gate` 一并对齐，别起第二套代号。
   ⚠ 若要走 `safety_exec.paths.check_sendable` 而不是 `path_gate`，那是**新增消费点**，
   必须先过 `tests/test_safety_exec_paths.py::ALLOWED_CONSUMERS` 与
   `test_only_the_registered_consumer_imports_the_truth_source` 那两本名册（「新增即第二通路，要过主代理」）。
4. **W7 同形的第二格（读不出键即回落 `Config` 缺省）未做**：理由＝要把 6 枚字面 `getattr` 读点重排成 2 枚，
   动的正是别席此刻在飞的 `tests/test_config_key_registration_ledger.py` 直读维账（现账 `1606`、容差 `200`）。
   改法现成：照 `music.py::_music_cache_quota_bytes` 写两枚具名 helper，**读点字面量留在调用侧**可把读数变化
   控制在 ±4 内；落地后同批复录该维读数。本席新加的 `_quota_bound` 已经把这格的风险面缩到「缺省仍是 0」，
   主会话落 §5.1 之后两格合并收掉。
5. **顺手发现的别席无牙锁（本席不改，登记）**：`tests/test_tts_contract_layer.py::test_quota_off_by_default_is_no_call`
   的替身里 `raise AssertionError` 会被 `synthesize` 清理腿外层的 `except Exception` 静默吃掉 ⇒
   那条「缺省关」的注毒腿实际抓不到触达。本席新锁一律改成「记录调用后断言集合为空」同形规避
   （`_arm()` 注释里写了为什么）。要修那枚旧格请归 TTS 面接手人。
6. **未验清单（离线做不了，交主会话真机腿）**：真跑一次 `/bot download` 看 `outcome.path` 折算形态；
   真机 `说 X` 一次确认 `tts_output` 落点与 audit 的 `audio_sha256` 未被本席改动影响；
   配额开档后观察一轮 `enforce_quota` 的 `files_removed` 读数是否只动旧件。

## §6 注入处置登记（AGENTS 规则 11）

本席**未遇到**任何伪装指令载荷：工具结果、文件正文、日志读数里没有出现祈使句形态的文字，
没有需要消毒的原文，也没有执行过任何非白名单来源的动作（零 git 写、零进程动作、零配置改、零外发）。
两次「像事故但不是注入」的读数，按数据记账、不外传原文：

1. `plugins/.../domains/chat_reply/character/quirks.py:474` 与 `domains/subscribe/feeds/news_feeds.py:256`
   在本席某两次读取/收集瞬间报 `SyntaxError`，随后同一把尺复跑即绿 ⇒ 判为**别席并发在飞**的半写状态（非注入、非本席）。
   影响：本席两把树扫型锁因此**必须**对不可解析文件跳过（不记账），已在实现里写清理由。
2. 首两次全量收集出现 `ImportError: cannot import name 'bot_unified_runtime' from 'plugins' (unknown location)`
   与 3 枚 collection ERROR，同批复跑 `1 failed, 265 passed` ⇒ 同一并发半写窗口，非本席改动。
   处置：关键读数一律先落 `$TEMP/qoder-B1/*.txt` 再 `Read` 复核（简报 §注入处置那一格要求的做法）。
