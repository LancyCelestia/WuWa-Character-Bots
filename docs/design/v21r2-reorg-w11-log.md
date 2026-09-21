# v21r2 板块重组 W11 media 域施工日志（RW11 席，2026-09-18）

> 认领依据：`v21r2-COORDINATION.md` 实时核查——RW5=divination（在飞收尾）、RW8=W1b link_parse、RW9=W9 notes+files，RW10 无占域记录；W11 media 未被认领，按席位序认领并即时声明占域（占域行与本收口行同文件可溯）。热区 transport/chat_reply/ops/core 与 W1b 零触碰。

## 1. 移动清单（11 件，§2.3 映射逐条对齐）

| 旧路径 | 新路径（真身） |
|---|---|
| capabilities/media_archive.py | domains/media/capabilities/media_archive.py |
| capabilities/tts.py（untracked settled WIP，09-17 20:26 生成，按 RW6 先例随迁零内容改动） | domains/media/capabilities/tts.py |
| capabilities/image_search.py | domains/media/capabilities/image_search.py |
| character/media_registry.py | domains/media/registry/media_registry.py |
| sources/media_archive.py | domains/media/archive/media_archive.py |
| sources/vision_describe.py | domains/media/ingest/vision_describe.py |
| sources/video_understanding.py | domains/media/ingest/video_understanding.py |
| sources/transcribe.py | domains/media/ingest/transcribe.py |
| sources/telegram_media.py | domains/media/ingest/telegram_media.py |
| sources/sauce_search.py | domains/media/search/sauce_search.py |
| runtime/video_pipeline.py | domains/media/video/video_pipeline.py |

新骨架：`domains/media/{__init__,capabilities,registry,archive,ingest,search,video}` 7 个包 init。文件系统 mv（代理禁 git 写）；contracts/media.py 按 §2.3 W11 注留守 core（W16）。

## 2. 真身随迁修正（兄弟直连 canonical；跨域旧路径经垫片保持）

- capabilities/media_archive.py：sources.media_archive→domains.media.archive.media_archive；sources.vision_describe→domains.media.ingest.vision_describe（×2 处）。
- capabilities/image_search.py：sources.sauce_search→domains.media.search.sauce_search。
- ingest/video_understanding.py、ingest/transcribe.py：vision_describe 兄弟引用切 canonical。
- video/video_pipeline.py：vision_describe/transcribe/video_understanding/character.media_registry 四处切 canonical（ingest 为 transcribe._download_audio 私有名直连）。
- 刻意保留旧路径（跨域、随对应波迁移，垫片稳定覆盖）：sources.downloader（W9 files，4 处）、sources.search_api（W16 core）、llm/llm.model_router（W15b）、capabilities.user_copy（W15e）。
- capabilities/tts.py、character/media_registry.py、sources/media_archive.py、sources/telegram_media.py：零插件内引用，零修正。

## 3. 垫片：11 张，形态从「快照 re-export」升级为「PEP 562 活转发」

首版按前波先例写 `import *` + 下划线显式转发；域测试轮暴露**快照垫片的时序分裂缺陷**（本方案 §3.1 Critical R1 的变体，前六波未触发）：

- 场景：驻留热区模块（capabilities/chat.py:322，W15e 禁碰域）在**调用期**做函数级 `from ...sources.video_understanding import build_video_brief`（经垫片），而测试按纪律改打 canonical 模块——快照垫片在首次 import 时绑定当时值，若垫片先于 patch 被 import，调用方永远拿到旧函数，补丁静默失效且随测试执行顺序非确定（dom2 轮 video_seam 恰为会话内首个触发垫片 import 的测试而侥幸通过，全量序必炸）。
- 解法：全 11 张垫片改为 PEP 562 `__getattr__` 活转发（`getattr(import_module(_CANONICAL), name)` + `__dir__`），旧路径一切属性访问（含下划线私有名、含 `from 旧 import 名` 的调用期解析）实时解析到 canonical 当前值——**单一补丁靶点=canonical，两路消费全通**，且天然覆盖根 `__init__.py:167-183` 对 video_pipeline 的 10 个下划线再导出（快照形态需手工枚举，活转发免维护）。
- 前提实证：全树 rg 证明 11 条旧路径**零 `import *` 消费**（活转发唯一破坏面），`from X import *` 在垫片自身指 canonical 不受影响。
- 同一性实证：插件冒烟 11 垫片 × 24 探针名（公开+下划线）`is` 断言全同对象；根 `_VIDEO_ACK_THROTTLE`/`_prepare_video_understanding_message` 与 canonical 同一性保持（依赖测试既有「原地表清空不换绑」纪律）。
- 移交建议：后续波次的垫片建议直接采用活转发形态（快照形态对「调用期函数级 import + canonical 补丁」组合不安全）；W15e chat.py 丢开垫片直连 canonical 时本垫片零改动退役。

## 4. 测试改写（AST 名字级终验清零）

- 12 文件 import 重定向指真身：test_asr_transcribe、test_telegram_media、test_vision_and_failover、test_vision_local_media、test_vision_remote_data_url、test_video_progress_ack、test_video_seam（video_pipeline+vu 双别名）、test_bgroup_chat_pipeline、test_media_archive（多行括号盲区 1 处，sed 不跨行由 Edit 单独处理）、test_tts、test_auditfix_parsers（函数级局部 import ×2）、test_video_reply_flow。
- **正则法漏网 3 文件 8 处**（W1a 教训复现）：首轮 rg 清单未含 test_auditfix_parsers/test_video_reply_flow/test_vision_remote_data_url，AST 终验脚本（别名绑定→setattr 首参归因，覆盖 Name/Attribute 链/字符串三形态）抓到后改写，复检 SETATTR_PATCH_HITS=0。
- 文本路径锚（RW6 同款，user_copy 门 3 锚）：Q03_SCOPE_FILES 的 media_archive 条目改指 domains/media/capabilities/ 真身（附 W11 注记）；test_q03_gate_detects_regression 合成 rel_path 实参同步；:507 read_text 锚改真身路径。
- 零改动证明：test_tts_outbound_chain/test_media_rejection_retry_and_fallback（untracked，仅 contracts/renderer/sender 引用）、test_auditfix_wave3_logic（from-import 经垫片）、test_media_registry/test_subscription_vision/test_voice_media_routing/test_batch_cdf_modules（纯调用无补丁）。

## 5. 回归实证（固定解释器 + PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 + --basetemp=$TEMP/v21r2-rw11 -p no:cacheprovider）

| 门 | 命令 | 结果 |
|---|---|---|
| 域关键词轮 | pytest tests -k "media or vision or video or tts or transcribe or voice or asr or sauce" | **424 passed** + 9 failed（见 §6 归因，非本波产物）+ 1 skipped |
| 显式文件轮（18 文件） | 改写 12 + 相邻 6 + user_copy 门 | **275 passed, 1 skipped, 0 failed** |
| AST 终验 | $TEMP/rw11_ast_check.py | SETATTR_PATCH_HITS=0 |
| 插件冒烟+垫片同一性 | nonebot.init+导入+24 名 is 断言 | plugin import OK / identity OK / 根下划线再导出同一 OK |
| 哈希门 | verify_hashes.py --check | exit=0 |
| 事实册门 | pytest tests/test_doc_sync_gates.py | 4 passed |
| 数据写守卫 | pytest tests/test_no_source_tree_data_writes.py | 5 passed |
| ruff | 本波面 26 文件（10 处 I001 --fix 后） | All checks passed |
| mypy | --explicit-package-bases --ignore-missing-imports plugins | 2 errors in 1 file = control_plane/api/platform.py 既有基线，488 文件本波零新增 |
| 树卫生 | find __pycache__/*.pyc/.pytest_cache/.ruff_cache/.mypy_cache | 零残留；qx.json 在 weather/assets 完好（e8285e77） |
| runtime-layout | scripts/runtime_layout_smoke.py | **FAIL（环境面在先，非本波）**：仅 BOT_KNOWLEDGE_FILES 两条「工作区外用户文件缺失」（鸣潮/战双库街区百科.md，.env 配置指向 AI智能体有关材料 目录），零源码树/边界违规；文件在席外且属用户环境配置漂移，本席无权处置，移交用户 |
| command_catalog --write | 未触发 | 未触 echo/_HELP_ENTRIES/config，按前波先例免跑 |
| dev.ps1 全量门 | 席位禁令未跑 | — |

## 6. 9 红在先归因（零交集移交，不 revert）

9 失败（test_video_reply_flow ×7 + test_video_seam ×2）全部同一断言形态：`assert "[视频档案" in llm.messages[0][-1]["content"]`，实际 messages[0][-1] = RP 席 09-18 注入的【日常对话的叙述】文风指令（chat.py WIP）。

归因链三点实证：
1. 断言靶位是 chat.py 消息组装产物，与媒体模块所在路径零因果；本波职责链（canonical 补丁→桩被调→calls/registry/video_source 断言）已全过（活转发垫片修复后 calls 断言稳定通过）。
2. `git show HEAD:chat.py` 中 `_VIDEO_BRIEF_TAG` 本就注入 composed_query（用户消息内容，HEAD:2618/WIP:2860），从不在 messages[0][-1]；该断言在 RP 席把文风指令追加为末位 system message 后必红——红点产生于本波开工前（RP 席 09-18 落盘、其 190 passed 回归清单未含这两个文件）。
3. chat.py 为 W15e 禁碰域（RP/R1 在飞 WIP 357 insertions），修测试期望需以 RP 席最终消息装配契约为准，本席不越域猜测。
→ 移交：RP 席（或 W15e 波）收口时统一更新 video_reply_flow/video_seam 的断言靶位（建议按其最终装配取 composed user message 或显式定位 brief 段）。

## 7. 偏差与纪律声明

- W-PA2 tts.py 归属：按推荐 a 案（§2.3 原映射落 media/capabilities/，creation 激活时再议），未改 RO 映射。
- W-PA5 每域 extensions/ 占位：本波未建（PA 自述可并入尾声波批量建），留尾声统一。
- 文件系统 mv 替代 git mv（代理禁 git 写，方法学⑦）；未 commit（多席共享工作树，提交裁决权在用户）。
- 顺带观察：git status 中 tests/test_media_quality_port.py、telegram 族 3 件的 M 为他席 WIP（零 media 旧路径引用实证）；scripts/telegram_resilience.py 等 untracked 同为席外在飞。
