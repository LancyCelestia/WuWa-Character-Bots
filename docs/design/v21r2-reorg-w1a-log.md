# v21r2 重组 W1a 波日志（link_parse/parsers 平台适配器 28 件，机制验证波）

> 席位：RW1a。日期：2026-09-17。施工图：`docs/design/v21r2-reorg-plan.md` §2/§3/§5-W1a/§6。
> 状态：**完成**（波内全门禁绿）。未 commit（禁 git 写操作；提交裁决权在用户）。

## 一、移动清单（28 件）

`plugins/bot_unified_runtime/sources/parsers/platforms_*.py` → `plugins/bot_unified_runtime/domains/link_parse/parsers/`（28 个，保原名）：
acfun, allcpp, bilibili, bilibili_goods, community, discourse, douban, epic, facebook, generic, github, huajia, kuaishou, kurobbs, lofter, media_share, mihuashi, miyoushe, moegirl, music, pixiv, skland, steam, taptap, telegram, weibo, xiaoheihe, zhihu。

新增包链：`domains/__init__.py`、`domains/link_parse/__init__.py`、`domains/link_parse/parsers/__init__.py`（后两者占位 docstring，不做平台 re-export——聚合入口仍由旧位 `sources/parsers/__init__.py` 提供，W1b 再动基建 9 件）。

移动方式偏差：指令纪律「禁止 git 写操作」优先于方案书 R8「全程 git mv」——用文件系统 `mv`（git 语义=D+??，rename 检测留给 commit 时相似度判定）。已记录为偏差 ①。

## 二、真身内部引用改写（绝对导入，同波）

- 15 个真身文件内 `from ...sources.parsers.platforms_generic import ...` → `from ...domains.link_parse.parsers.platforms_generic import ...`（acfun/bilibili/bilibili_goods/huajia/kuaishou/media_share/kurobbs/mihuashi/lofter/pixiv/miyoushe/skland/weibo/xiaoheihe/steam）。
- 28 件内**零相对导入**（全绝对导入，方案书 §3.1 相对导入风险 R3 本波不适用）。
- 保留不动：`platforms_bilibili.py:32` `from ...sources.parsers import wbi as _wbi`（wbi 属 W1b 基建，仍在旧位真身，无垫片分裂）；generic→`contracts.media`（W16 域）、→`http_util/image_stitch/ssrf_guard/context`（W1b 域）路径不变。

## 三、垫片清单（28 个，旧位 re-export 薄壳）

- 26 个纯转发：`from ...domains.link_parse.parsers.platforms_X import *`（ruff 规整后无 noqa——项目 ruff 配置下 `import *` 不触发 F401/F403）。
- **下划线符号显式转发 5 处**（`import *` 不带下划线，不转发会 AttributeError）：
  | 垫片 | 转发符号 | 消费者 |
  |---|---|---|
  | platforms_generic | `_douyin_from_router_data` | tests/test_douyin_topics.py:51（只读） |
  | platforms_generic | `_twitter_large_url`、`_xhs_best_stream_url` | tests/test_media_quality_port.py（只读） |
  | platforms_music | `_qqmusic_cover` | **生产** sources/parsers/__init__.py:738（函数内 import） |
  | platforms_epic | `_cookie_file_candidates` | tests/test_datafix_runtime_paths.py（动态 `__import__` 旧路径） |
  | platforms_steam | `_cookie_file_candidates` | 同上 |

## 四、monkeypatch 同波改写清单（13 个测试文件，波内清零）

垫片陷阱形态：测试经旧路径拿**模块对象**再 `setattr` → 打在垫片上，真身无效（假绿/假红/真网络泄漏）。

| 文件 | patch 数 | 形态 |
|---|---|---|
| tests/test_auditfix_parsers.py | 16+ | 顶部 import 块 6 平台 + 函数内 steam/epic/facebook |
| tests/test_parser_ssrf_guard.py | 2 | generic.http_get_text |
| tests/test_music_parser_metadata_v2.py | 4 | music.http_get_json/_netease_audio_url |
| tests/test_chat_and_sources_regressions.py | 1 | generic._og_scrape |
| tests/test_market_github.py | 4 | 字符串路径 platforms_github._github_get_json |
| tests/test_music_provider_projection_v2.py | 1 | music._qqmusic_vkey_url |
| tests/test_parser_multipage_quote.py | 6 | bilibili(B)×4 + generic(G)×2 |
| tests/test_parsers_batch_a.py | 3 | zhihu/douban/taptap |
| tests/test_parsers_batch_a2.py | 4 | discourse/community |
| tests/test_platform_deepening_b7_fixtures.py | 8 | telegram/generic/weibo |
| tests/test_platform_field_deepening_v2.py | 4+ | bilibili/generic |
| tests/test_telegram_parser_v2.py | 多行 setattr | telegram.http_get_text（真网络 404 泄漏现行犯） |
| tests/test_youtube_subtitle_regression.py | 3 | generic._youtube_* |

未改写（只读消费者，靠垫片转发）：test_douyin_topics.py、test_media_quality_port.py（其 patch 全打 http_util——W1b 前不动）。

**清零验证**：AST 程序化终验（解析全部 tests/scripts 的 ImportFrom/Import+setattr/patch 调用图）→ `CLEAN: zero legacy-path platforms targets`。正则法三轮共漏 8 文件（`from pkg import mod` 模块对象形式 + 多行 setattr 形态是检索盲区）——**建议方案书 §3.1 波前检索补 AST 法**（偏差改善 ②）。

## 五、垫片期顺序纪律（本波推演结论，后续波必须遵守）

循环导入推演：`import a.b.c` 必先完整导入父包链 → 旧位垫片链工作正常；但**「裸新路径子模块作进程内首个 plugin import」会炸**（真身 X 执行中 → 触发旧包 __init__ → 垫片 X `import *` 从半成品真身取符号 → ImportError）。现状等价场景不存在，垫片期纪律：**任何文件的新路径 import 之前必须有旧路径 import 先行**（触发 sources.parsers 聚合完整执行）。13 个改写测试全部满足（自带触发行或既有旧路径 import 在前）。

## 六、实跑命令与输出摘要

解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=$TEMP/v21r2-rw1a*` `-p no:cacheprovider`。

| # | 门禁 | 结果 |
|---|---|---|
| 1 | 受影响 13 测试文件直跑 | **225 passed** |
| 2 | 解析域广域轮 `-k "parse or parser or douyin or … or youtube or cookie"`（ruff fix 后终跑） | **698 passed** / 1 skipped / 3 xfailed |
| 3 | AST monkeypatch 清零终验 | CLEAN |
| 4 | 插件导入冒烟（§6⑦：根包 + mail_adapter.ResilientMailAdapter + sources.parsers 聚合符号） | plugin import OK / final smoke OK |
| 5 | `tests/verify_hashes.py --check` | exit=0 |
| 6 | `scripts/runtime_layout_smoke.py` | source_generated_dirs=empty / bytecode=absent |
| 7 | `tests/test_no_source_tree_data_writes.py` | 5 passed |
| 8 | `tests/test_doc_sync_gates.py` | 4 passed（--write 收口后复跑仍绿） |
| 9 | ruff 本波面（domains/ + sources/parsers/ + 13 测试文件） | **All checks passed**（--fix 收口 58 错=I001/RUF100，全为本波移动/垫片引发） |
| 10 | mypy 标准参数（--explicit-package-bases --ignore-missing-imports plugins） | 本波面 **0 错**；全仓 5 错全他席存量（见偏差⑤） |
| 11 | 树卫生 find 缓存/字节码 | 干净（中途直跑曾落 .mypy_cache/.ruff_cache，已清并改带 --cache-dir） |

## 七、偏差与风险登记

1. **未用 `git mv`**：遵指令「禁止 git 写操作」，文件系统移动，rename 检测留待 commit。
2. **monkeypatch 检索法升级建议**：方案书 §3.1 的 rg 模式漏「包入口模块对象 + 多行 setattr」8 文件，靠广域轮真网络 404 泄漏现行暴露后 AST 终验清零。后续波波前取证建议直接用本波日志 §四 的 AST 脚本。
3. **command_catalog --write 顺带收口他席漂移**：并行席位在 echo.py 新增 2 topic（功能管理/语音，75→77 模块）未重录生成物；本波 §6④ 例行 --write 显性化之。条目完整非半成品，doc_sync_gates 复跑绿，保留。
4. **qx.json（W3 席）**：波内发现 `sources/data/qx.json` → `domains/weather/assets/qx.json` 已由并行 W3 席随迁（git D + 门禁绿），非本波文件域，未触碰。
5. **静态门存量红（他席在飞域，本波不碰）**：ruff 15 错（decision×4、test_outbound_v21×4、test_v21_risk_red_cp_platform×2、control_plane/platform×1、kb_wiki×1、timesync×1、loop_watchdog×1、test_sandbox_windows×1）；mypy 5 错（timesync×2=R3b 域、kb_wiki×1=R2 域、control_plane/api/platform×2=#36 记载既有）。
6. **瞬时跨席中间态一例**：复验时撞上 W4 席 eat.py 移动窗口（根包 import 崩 1 次），等待其垫片落位后复跑全绿——多席并行共享工作树的固有抖动，记录在案。
7. **回滚说明**（本波无 commit，回滚=恢复文件原位）：`mv domains/link_parse/parsers/platforms_*.py sources/parsers/` + 真身内 generic 引用 sed 回旧路径 + 删 28 垫片内容（从 git HEAD 恢复）+ 删 domains/ 三 __init__ + 还原 13 测试文件（git HEAD 版本）+ 复跑 §六 门禁。
