# v21r2 板块重组 · W13 render 域施工日志（RW14 重派席）

> 日期：2026-09-18。席位：RW14 重派席（render 渲染域；前任认领 14 分钟撞 1302 阵亡、零文件改动，开工复核 output/ 原样、domains/render 未建属实）。按 `v21r2-reorg-plan.md` §5 五步模板 + §3 line 226 映射表施工。
> **文件名偏差**：简报指定 `v21r2-reorg-w14-log.md` 已被 RW15 席（W14 transport）占用、`w13-log.md` 已被 RW13 席（W12 assistant）占用；本席波次=方案书 W13，改落本文件。
> 固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=$TEMP/v21r2-rw14b -p no:cacheprovider`；禁 dev.ps1；无 git 写操作；未再派代理。

## §1 波前取证（实跑）

**移动面（方案书名义 13 py / 实迁 11 py + 7 html；2 个 `__init__` 原位保留即成垫片中继）**：
- output 根 7 件 → `domains/render/`：`render_backends.py renderer.py plain_text.py templates.py roleplay.py reviewer.py bot_avatar.py`
- card_render 4 件 → `domains/render/card_render/`：`bridge.py theme_tokens.py usage_cards.py models.py`
- `card_render/templates/*.html` ×7 → `domains/render/card_render/templates/`（保内部结构）
- 新建：`domains/render/__init__.py`、`domains/render/card_render/__init__.py`（一行 docstring，house style）
- `output/__init__.py`、`output/card_render/__init__.py` **零改动**：本就是 `from .renderer/.bridge import` 形态，迁后指向同位垫片中继即垫片

**随迁 WIP（零内容改动随迁）**：`output/renderer.py`(+9/-2)、`output/roleplay.py`(+20/-2，rp-style 席)；`tests/render_hashes.json` rp 席已重录态。波前 `verify_hashes --check` 实跑 **EXIT=0**（基线绿）。

**引用面（AST 全仓扫描 plugins/scripts/tests）**：
- 符号式 `from …output(.card_render)?.X import name`：72 文件 → 垫片覆盖零改动
- 字符串式 patch 串 `setattr("…output…")`/`patch("…output…")`：全仓 **0 命中**
- 模块对象式导入 **22 处 21 文件**（补丁/`__file__` 锚打壳打不进真身，波内必改指真身）：
  - `import …output.render_backends as render_backends_module`：test_browser_ctx_leak:26、test_render_launch_backoff:28
  - `from …output import <模块>`：test_bot_avatar:21、test_mermaid_reply_render:17(renderer)、test_mermaid_local_asset:23(rb)、test_mermaid_shared_backend:29(rb)、test_render_phase2_env_keys:27、test_render_image_cache:18(rb)、test_music_candidates_card:14(templates)、test_p1_hotspot_hygiene:19(plain_text)、test_thread_pool_atexit_hooks:20(renderer)
  - `from …output.card_render import bridge`：test_rendering_contract:25、test_bridge_icon_cache:21、test_e02_stardust:21、test_e03_typography:22、test_error_card_contract:13、test_fmt_count_units:15、test_mermaid_reply_render:18、test_mermaid_retry_budget:21、test_mermaid_shared_backend:30、test_template_visual_audit:25、test_universal_card_projection:21、test_universal_card_visual:23、scripts/render_card_samples.py:49
- 对象式 setattr（模块绑定改真身后自动修复）：test_bot_avatar（_LOCAL_AVATAR_URI/_DISCOVER_MISS_TS/_MONOTONIC×3）、test_bridge_icon_cache（_ICON_ASSET_ROOT×5）、test_browser_ctx_leak、test_render_launch_backoff
- 禁触文件对 output 的依赖（垫片覆盖，零触碰）：根 `__init__.py:106/2030/2051`、`control_plane/workspaces.py:25`、`domains/transport/sender/nonebot.py:24`（RW15 移交注记）

**四重机器门现状**：
1. `tests/verify_hashes.py` TRACKED_FILES 19 项，12 项在移动面（7 html+theme_tokens+bridge+usage_cards+renderer+templates.py）；echo/debug/4 份 docs 不动。覆盖门 `tests/test_verify_hashes_coverage.py` 三处同波同步：BUILDER_SOURCES 4 项路径、`_DRILL_TARGET`、`len==19`（计数不变仅换路径）
2. 渲染契约：`Path(bridge.__file__)/"templates"` 锚 6 文件——bridge 走垫片则锚到旧位空目录，全部改指真身
3. DESIGN-SPEC.md：无内嵌哈希表，内容零改动
4. mermaid/iconfont 资产根：祖先目录搜索（`ChatBot_Runtime/card_render_assets` 标记）深度无关，迁移安全；`BOT_CARD_ASSET_DIR` 显式配置优先

**迁移文件内部导入（机读清单直驱改写）**：renderer.py:18 `.plain_text`；bridge.py:35/36/50 `..render_backends`/`.models`/`.theme_tokens`；templates.py:16-34 七处旧绝对；usage_cards.py:23 旧绝对；bot_avatar.py:103 `parents[3]`→`parents[4]`（仓库根锚随深度+1）；reviewer.py contracts 绝对导入不动；plain_text/roleplay/render_backends/models/theme_tokens 无包内导入。

**垫片策略**：house style 同 W2/W3/W14（`from <真身> import *` + 消费面下划线名显式转出 `# noqa: F401`）。下划线转出清单（AST 名字级）：bridge←_MERMAID_READY_JS/_darken/_derive_wash_tokens/_hex_to_rgb/_rgb_to_hex；theme_tokens←_darken_hex/_hex_to_rgb/_rgb_to_hex；render_backends←_MERMAID_CDN_URL/_RENDER_READY_SIGNALS/_wait_render_budget；reviewer←_unsafe_output_reasons；其余 7 模块消费面全公开名（bot_avatar 私名仅被模块绑定测试 patch，绑定已改真身）。

**conftest**：autosync 联动无路径锚、`BOT_AUTOSYNC=0` 零写入、零改动。`tests/_autosync_fixture.py` 模板 glob 同波改新路径。

## §2 移动与垫片（第 2/3 步）

- mv 11 py + 7 html（保内部结构；renderer/roleplay 的 rp 席 WIP 零内容改动随迁）；新增 `domains/render/__init__.py`、`domains/render/card_render/__init__.py`（一行 docstring）
- 真身内部导入绝对化 15 处：renderer.py ×2（顶层 `.plain_text` + 函数级 `.card_render.bridge`）、bridge.py ×3（`..render_backends`/`.models`/`.theme_tokens`）、templates.py ×7、usage_cards.py ×2（顶层+函数级）、bot_avatar.py ×1（`parents[3]`→`parents[4]` 仓库根锚）
- 旧位垫片 11 张（house style `from 真身 import *` + 消费面显式转出）。**机核抓漏**：bridge/theme_tokens/usage_cards/models 四真身有 `__all__`（星号只转 `__all__` 名单），且 `__all__` 缺 UNKNOWN_PLATFORM_COLOR/render_error_card_html（bridge）、DIVIDER/FONT_FAMILY_STACK/GLOW_ACCENT/SHADOW_CSS_VARS（theme_tokens）等消费名——星号垫片会 ImportError → 四张升级**全命名空间显式转出**（bridge 123 名/theme_tokens 53/usage_cards 19/models 7），垫片与真身非 dunder 命名空间完全同一
- `output/__init__.py` 与 `output/card_render/__init__.py` **零改动**：本就是 `from .renderer/.bridge import` 形态，迁后中继即垫片

## §3 同波改写（第 3 步，机读清单直驱）

- **26 文件 40 处**：模块对象绑定 22 处改指真身（`import …render_backends as` ×2、`from …output import <模块>` ×9、`from …card_render import bridge` ×11 含 scripts/render_card_samples）——对象式 patch（test_bot_avatar ×3、test_bridge_icon_cache ×5、test_browser_ctx_leak、test_render_launch_backoff）与 `bridge.__file__` 模板锚（6 文件）随绑定自动修复；字符串式 patch 串全仓 0 命中
- 门禁同步：`tests/verify_hashes.py` TRACKED_FILES 12 路径；`test_verify_hashes_coverage.py` BUILDER_SOURCES 4 路径 + `_DRILL_TARGET`；`_autosync_fixture.py` 模板 glob；`scripts/doc_sync.py` 模板路径（**门禁红抓出**：`_tpl_list()` 旧路径致 auto-facts 漂移 1 红）；契约测试导入（rendering_contract/mica_builders）
- `docs/auto-facts.md` --write 重生成：模板/哈希清单路径换新 + **吸收并行 WIP 代码事实计数**（RouteKind 33→34 增 TTS、topics 75→77、tests 326→394、config 529→599）——机器确定性派生自当前树、非本波改动面，后续席重生成字节一致零冲突

## §4 回归实跑（第 4 步；venv 固定解释器，PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0，basetemp=$TEMP/v21r2-rw14b，-p no:cacheprovider）

| 门 | 结果 |
|---|---|
| verify_hashes --write → --check | **exit 0**（19 项计数不变仅换路径；--write ×2：第二次吸收 ruff --fix 对 bridge/renderer 的 I001 导入序——时序教训：--fix 后必终检 --check） |
| 渲染契约族+覆盖门+交叉验证+doc_sync（终密封批） | **181 passed** |
| 关键词全库扫（render/card/roleplay/template/plain_text/reviewer/avatar/mermaid/bridge/theme/mica/plain） | 终轮 **867 passed / 3 skipped / 0 failed**，**7781 收集零错**；3 轮中前 2 轮各 1 红且红不同（test_quirks_scope / test_bgroup_llm_route），均**单跑即过**+文件均他席 M 态 WIP（quirks 批 / R1 llm-route 在飞）→ 顺序型 flake 外部归因，render 面 3 轮零红 |
| ruff（波面 28 文件） | --fix 6（全 I001）→ **All checks passed** |
| mypy（dev.ps1 口径 --explicit-package-bases --ignore-missing-imports plugins） | 4 错**全外部**：creation/tts 新保留域 WIP ×2 + control_plane/api/platform.py 既有 ×2（台账 #36）；**本域 0 错** |
| 垫片同一性 | **11/11** 公开名 hasattr + `is` 同一性全过；锚点：模板 7 html（真身 `bridge.__file__`）、mermaid_asset_dir→ChatBot_Runtime 真路径、bot_avatar 仓库根锚 OK |
| 插件冒烟 | `import plugins.bot_unified_runtime` + `mail_adapter.ResilientMailAdapter` OK |
| runtime-layout | 2 处 BOT_KNOWLEDGE_FILES 环境缺失（RW15 同款既有）+1 外域残留 `__pycache__`（transport/extensions，备份 %TEMP%/chatbot-stray-cache-rw14 后清除） |
| 树卫生 | 终态源码树零 `__pycache__`/`.pytest_cache`/`*.pyc`/`data/`；旧路径残留三类扫（模块式绑定/斜杠路径/缓存）全空 |
| log_collectors | `_SUBSYSTEMS` 无 output/render 前缀锚（实读确认），render 族 logger（仅 bot_avatar/render_backends 两处 getLogger）事件源迁移前后同为 bot，零影响零改动 |

## §5 偏差与移交

1. **日志文件名**：简报指定 `v21r2-reorg-w14-log.md` 已被 RW15 席（W14 transport）占用、`w13-log.md` 已被 RW13 席（W12 assistant）占用 → 改落本文件（波次号 b 版），COORDINATION 行注明
2. **实迁计数**：11 py + 7 html（简报/方案书名义 13 py 含 2 个 `__init__`——原位零改动即垫片中继，不迁）
3. **域清单外最小触碰 4 件**（门禁/命中随波同步，§5 模板第 3/4 步授权）：`scripts/doc_sync.py`、`scripts/render_card_samples.py`、`tests/_autosync_fixture.py`、`tests/test_verify_hashes_coverage.py`
4. `test_mica_builders_contract.py:38` 的 `output.templates` 符号式导入保持旧位垫片中继（真身无 `__all__`、star 全公开名覆盖），垫片退役尾声波一并收
5. 未跑 dev.ps1 全量门、未 commit（席位禁令；工作树多席共享，提交裁决权在用户）；禁触面（RW12/13/15 认领、S9 control_plane、根 `__init__.py`、bot.py、sender、llm、capabilities/chat、personas、qx.json）全程零触碰
6. **移交尾声波**：垫片退役时需统计旧路径 import 残留（72 文件符号式经垫片，含 root `__init__.py:106/2030/2051`、control_plane/workspaces.py:25、domains/transport/sender/nonebot.py:24）
