# v21r2 重组 W9 席施工日志（notes + files 域，2026-09-18）

> 席位：RW9（板块重组执行·第 9 波）。施工图：`docs/design/v21r2-reorg-plan.md` §5 W9 行 + §2.3 映射 + §10 W-PA3。
> 认领路径：RW6 meme 在飞未收波、W1b 已被 RW8 认领 → 按认领规则②取序列下一无冲突波 W9。
> 纪律：零 git 写操作、零 dev.ps1、文件系统 mv、固定 venv 解释器、PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0、basetemp=%TEMP%/v21r2-rw9。未 commit。

## 一、移动清单（7 件 + 配套 14 文件）

| 旧路径 | 新路径（真身） |
|---|---|
| `capabilities/notes.py` (637 行) | `domains/notes/capabilities/notes.py` |
| `character/notes_store.py` (498 行) | `domains/notes/store/notes_store.py` |
| `capabilities/download.py` (183 行) | `domains/files/capabilities/download.py` |
| `capabilities/file_exchange.py` (378 行) | `domains/files/capabilities/file_exchange.py` |
| `capabilities/group_files.py` (112 行) | `domains/files/capabilities/group_files.py` |
| `sources/downloader.py` (790 行) | `domains/files/sources/downloader.py` |
| `sources/file_reader.py` (274 行) | `domains/files/sources/file_reader.py` |

配套新建：`domains/notes/{__init__,capabilities/__init__,store/__init__}.py` ×3、`domains/files/{__init__,capabilities/__init__,sources/__init__}.py` ×3（docstring 惯例同既有域）、**W-PA3**：`domains/files/artifacts/__init__.py`（首行 `reserved:` docstring，FILE-002 ArtifactGateway 域内预留槽，零 import 副作用）。

**随迁 WIP 如实登记**：`sources/file_reader.py` 工作树 M 态（FILE-001 功能批 212+/55- 行增强：BadZipFile/扩展名表重构等），按「迁移即搬工作树现态」惯例随迁，内容零改动（mtime 保留 09-17 08:39 原值可证）。

## 二、真身随迁修正（6 处）

- `notes.py`：①docstring L15 `character/notes_store` → `domains/notes/store/notes_store`；②L32 模块级 `from plugins.bot_unified_runtime.character.notes_store import (Note, build_notes_store)` → canonical `domains.notes.store.notes_store`；③L247 函数级 `from ...sources.downloader import check_download_url` → canonical `domains.files.sources.downloader`。
- `download.py`：L23 `from ...sources.downloader import MediaDownloader` → canonical `domains.files.sources.downloader`。
- `notes_store.py`：docstring ×2（L9/L29 的 `capabilities/notes.py` 自指路径 → 新路径）。
- 零改动真身：`file_exchange.py`（capabilities.user_copy 引用 W15e 前不动）、`group_files.py`（纯 stdlib）、`downloader.py`（runtime.cache_policy 引用 W15d 前不动；yt_dlp 模块级 try-import 原样）、`file_reader.py`（纯 stdlib+可选三方）。

## 三、垫片（7 张 re-export 薄壳 + 显式私有转发）

跨界下划线私有名显式转发清单（消费方实据）：

| 垫片 | 私有名 | 消费方 |
|---|---|---|
| `capabilities/notes.py` | `_NOTES_ADD_RE/_BARE/_DELETE/_DONE/_LIST/_UNDO_EXPLICIT/_UNDO_NATURAL/_VIEW` ×8 + `_images_root` | `capabilities/reminder.py:21` 模块级导入 8 正则；notes 单测对象式 patch `_images_root` |
| `capabilities/file_exchange.py` | `_DOCUMENT_PROMPT`、`_safe_file_name` | 根 `__init__.py:5031`；`test_auditfix_wave3_resources.py:12` |
| `sources/downloader.py` | `_find_ffmpeg` | `sources/transcribe.py:45`、`video_understanding.py:85`、`vision_describe.py:388`（函数级） |
| `character/notes_store.py` | 无（`__all__` 5 名已覆盖全部消费面） | reminder/tests |
| `capabilities/download.py`、`capabilities/group_files.py`、`sources/file_reader.py` | 无（消费面全公开名） | root/console_chat/chat/media_archive/file_gateway/eat/ssrf_guard/tests |

ruff 口径注：本项目 ruff 未启用 F403，星号导入行的 `# noqa: F401,F403` 触发 RUF100 → 修后星号行裸写、显式转发行保留 `# noqa: F401`（`--fix` 自动收口 18 处：RUF100+I001，复检 All checks passed；`--fix` 曾触碰 notes.py/download.py 真身，经比对确认仅为本次所改 import 块的 isort 重排，语义等价零越权）。

## 四、测试改写（4 件，波内清零）与垫片保活（12 件零改动）

**改写依据**：对象式模块导入打补丁/`inspect.getsource` 打垫片必失效。

1. `test_notes.py`：`notes_mod` 与 `notes_store_mod` 及 from-import 全改真身路径（`monkeypatch.setattr(notes_mod, "_images_root", ...)` @L51 打旧壳无效）。
2. `test_notes_item_checkoff.py`：同上（setattr @L57）。
3. `test_chat_and_sources_regressions.py`：`from ...sources import downloader as mod` ×2 + `MediaDownloader` ×2 改真身（`setattr(mod, 'yt_dlp', fake)` @L185 打旧壳不打真身全局）。
4. `test_auditfix_wave3_resources.py`：`import ...capabilities.file_exchange as fx` 改真身（`inspect.getsource(fx)` @L85 打垫片拿到 3 行壳源码必炸）+ `_safe_file_name` from-import 同步改真身。

**垫片保活零改动**（纯值导入/函数级重导入语义不变）：test_todo_checkoff / test_reminder / test_batch_cdf_modules / test_file_exchange / test_content_video_auto_send / test_f03_notice_redaction / test_media_archive / test_media_quality / test_phase0_3_features / test_v21_risk_red_tz_and_files。
**关键语义论证两件**：
- `test_runtime_subfeatures.py`（`setattr(旧路径 file_reader, "read_supported_file", ...)`）保活成立：其消费方 root `__init__.py:1218` 与 `control_plane/api/platform.py:356` 均为**函数级** import 旧路径 → 每次调用现读垫片模块属性 → 补丁可见（垫片期两侧同模块对象）。
- `test_parser_ssrf_guard.py`（RW8 域文件，`setattr(旧路径 downloader_module, "check_download_url", boom)`）保活成立：消费方 ssrf_guard 为函数级 import 旧路径，同上。该文件属 RW8 认领域，本席零触碰。

## 五、波前取证与 AST 终验

- 基线（移动前）16 文件 **261 passed** 全绿。
- AST 程序化终验（脚本落 %TEMP%/v21r2-rw9/ast_scan_w9.py，含相对导入解析与字符串常量扫描，补掉「多行括号 from-import」「包入口相对形式」双盲区——首版漏报 root `__init__.py:31/35/206/4581/5031` 与 platform.py 相对形式，修正解析后重跑）：
  - **import 命中 37 处 = 20 插件消费方 + 17 测试，全部为预期垫片覆盖面，零意外残余**；
  - **字符串命中 0**（monkeypatch/mock.patch 字符串式目标对本波 7 模块全零）；
  - 4 个改写测试文件零残余（AST 级确认）。

## 六、回归实跑（全部直跑证据）

| 门 | 结果 |
|---|---|
| 域 16 文件批次（含收敛后 test_reminder） | **261 passed**（追平基线，0 failed） |
| 宽域 `-k "notes or download or downloader or file_reader or file_exchange or group_files"` | **75 passed** / 7694 deselected |
| 插件导入冒烟 + 垫片同一性 | `import plugins.bot_unified_runtime` + `mail_adapter.ResilientMailAdapter` OK + **24 项 shim↔真身 same-object 断言全过**（含全部显式转发私有名） |
| ruff（本波 18 触碰文件） | **All checks passed**（--fix 收 18 处 RUF100/I001）；全树 98 错 **0 命中本波文件**（余量全外部席位在飞） |
| mypy（dev.ps1 同参直跑：--explicit-package-bases --ignore-missing-imports plugins） | **5 错全外部归因**：`control_plane/api/platform.py` ×2（多席在录既有）+ `character/worldbook_service.py` ×3（他席在飞新件，mtime 02:29:41 仍在写入）；本波 18 文件 **0 错** |
| `tests/verify_hashes.py --check` | exit 0 |
| `tests/test_doc_sync_gates.py` | 4 passed |
| 树卫生 | plugins/tests/scripts 零 `__pycache__`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache`、零源码树 `data/`；`domains/weather/assets/qx.json` 完好未触碰 |
| runtime-layout | **2 FAIL = BOT_KNOWLEDGE_FILES 两文件缺失**（指向用户目录 `Documents/AI智能体有关材料/...md`，环境/配置面，与本波移动零关联，如实登记非本波引入） |
| dev.ps1 全量门 | 未跑（席位禁令，与 RW4/RW7 同口径） |

## 七、并发事件台账（多席共享工作树实录，零本波归因）

1. **RW8 cookies 中间态炸插件导入**：本波域测试首跑收集期 `platform_credentials.py:22` 从旧路径导入 `sources.parsers.cookies._resolve_relative_cookie_path` ImportError——RW8 W1b 于 02:18 将 cookies.py 迁走且垫片暂缺显式私有转发（其认领域文件，本席零触碰），**02:22:26 RW8 自愈**（垫片补转发），退避重跑通过。
2. **他席实时改 reminder 族致 4 红瞬态**：批次二跑 4 failed，取证=另一席正实时编辑 `capabilities/reminder.py`（02:23:28）/`character/reminders.py`/`tests/test_reminder.py`（02:25:31），`_match_ordinal` 已从 reminder.py 删除而测试仍引用（rg 实证）；另 3 例单跑即绿。**该席收敛后 test_reminder 29 passed，最终 16 文件批次 261 passed 全绿**。reminder 族=W10 schedule 域，本席零触碰。
3. **mypy 双映射报错**为调用姿势问题（plan §6 ⑥ 缺 `--explicit-package-bases`），按 dev.ps1 同参直跑解决，缓存置 %TEMP% 不入源码树。

## 八、偏差与移交

- 20 处旧路径消费方（root ×6、chat/media_archive/reminder ×3/console_chat ×2/platform/eat/file_gateway/transcribe/video_understanding/vision_describe/ssrf_guard）跨域零改动，全靠垫片覆盖；其中 eat.py:320 直连旧 downloader 真身的收编与 `test_runtime_subfeatures`/`test_parser_ssrf_guard` 的旧路径补丁语义，移交**垫片退役尾声波**统一处理。
- `command_catalog.py --write` 未跑（未触 echo/config，生成物无漂移面）。
- 未 commit（禁 git 写）；提交裁决权在用户。
