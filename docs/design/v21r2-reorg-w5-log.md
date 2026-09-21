# v21r2 板块重组 W5 — divination 域施工日志（RW5 席）

> 波次：§5 波次表 W5（divination，10 件）。执行席：RW5。日期：2026-09-18（凌晨）。
> 施工图：`docs/design/v21r2-reorg-plan.md` §2.3 映射表 / §3 兼容策略 / §6 门禁 / §8.1 域 9 行（DIVINATION-001/002/003@L64-L66）。
> 纪律：零 git 写操作（plain mv，重命名检测留给提交方）、禁 dev.ps1、固定解释器 ChatBot_Runtime venv、`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`、pytest `--basetemp=$TEMP/v21r2-rw5 -p no:cacheprovider`。

## 1. 波前取证（rg 全量扫描记录）

**移动清单（10 件，§2.3 → domains/divination/）**：

| 旧路径 | 新路径 |
|---|---|
| `capabilities/divination.py` | `domains/divination/capabilities/divination.py` |
| `sources/ganzhi.py` | `domains/divination/data/ganzhi.py` |
| `sources/tarot.py` | `domains/divination/data/tarot.py` |
| `sources/iching.py` | `domains/divination/data/iching.py` |
| `sources/multi_calendar.py` | `domains/divination/data/multi_calendar.py` |
| `sources/draw_store.py` | `domains/divination/data/draw_store.py` |
| `character/draw_store.py` | `domains/divination/store/draw_store.py` |
| `runtime/divination_service.py` | `domains/divination/service/divination_service.py` |
| `runtime/fortune.py` | `domains/divination/service/fortune.py` |
| `runtime/tarot_draw.py` | `domains/divination/service/tarot_draw.py` |

占域核对：R3b（pipeline/timesync/loop_watchdog）、RW1a（parsers+link_parse）、RW4（W4 food 已完成）、SEARCH（sources 搜索面）、RP（personas+chat/providers 注入段）——与本波 10 件零交集。
波前 git status：本波 10 件中 5 件为未跟踪新文件（v21 占卜批 WIP：character/draw_store、runtime/{divination_service,fortune,tarot_draw}、sources/draw_store、tests/test_divination_service_v21），capabilities/divination.py 带 M（同批 WIP 修改）——均无在飞席认领，按现内容整体 mv。

**引用面清单（plugins+tests+scripts+bot.py 全量 rg）**：

- 插件内导入（随迁重定向）：`capabilities/divination.py`→sources.{draw_store,ganzhi,iching,tarot}（4 处）+ 函数级 contracts(L415, 不动) + 函数级 capabilities.content_parser(L595, **保持旧路径**——W1b 在飞、canonical 位不存在，垫片期两态皆兼容)；`sources/draw_store.py`→sources.tarot（1 处）；`runtime/divination_service.py`→character.draw_store+runtime.fortune+runtime.tarot_draw（3 处，contracts.errors/request 2 处不动）；`runtime/tarot_draw.py`→character.draw_store+runtime.fortune+sources.tarot（3 处）。其余 6 件（ganzhi/tarot/iching/multi_calendar/character.draw_store/fortune）零插件内部导入。
- 跨界消费者（走垫片零改动）：根 `__init__.py:30`（`.capabilities.divination` 相对导入 build_divination_capability）；`runtime/base_router.py:41`（is_divination_command，W15d/R3b 热区零触碰）；`scripts/e2e_acceptance.py:72`（build_divination_capability+is_divination_command，§1.3 脚本零改动纪律）。
- 测试引用（14 文件）：test_card_prune / test_divination / test_divination_hijack_guard / test_divination_service_v21 / test_finance_routing / test_feature_cards / test_help_deep_teaching_n2re / test_multi_calendar / test_pinyin_triggers_3 / test_production_wiring / test_sdd7_n4 / test_traditional_triggers_2 / test_trigger_english（+子进程字符串内嵌 import ×2 @test_divination_service_v21:269-270——非 monkeypatch 陷阱，跨进程黄金值语义经垫片不受影响，零改动保留）。
- monkeypatch 扫描（setattr/patch 行 × 模块名过滤）：**唯一真陷阱 = tests/test_card_prune.py:157**（`monkeypatch.setattr(divination_module, "_prune_card_dirs", _boom)` 对象式打壳模块，真身内部解析不受影响）→ 同波改写。test_feature_cards（patch random.Random 标准库）、test_sdd7_n4:273（patch character/providers，RP 域）、test_production_wiring 均不命中本波模块。
- 门禁锚定：verify_hashes TRACKED_FILES 零 divination 锚 ✓；doc_sync/config-catalog 零涉（本波文件无 config 字段）✓；无 test_domain_layout.py（§6.1 未建）✓。

**跨界符号 ≠ `__all__` 清单（垫片必须显式补名，naive `import *` 会炸）**：

| 模块 | 补名 | 跨界引用方 |
|---|---|---|
| capabilities/divination | `is_divination_command` | base_router:41、e2e_acceptance、test_divination_hijack_guard/pinyin_triggers_3/traditional_triggers_2/trigger_english |
| sources/ganzhi | `CST` | test_divination、test_sdd7_n4 |
| sources/iching | `HEXAGRAMS` | test_divination |
| runtime/divination_service | `build_interpretation_context` | test_divination_service_v21 |
| runtime/tarot_draw | `_compute_deck_revision`（私有） | test_divination_service_v21:169 函数级 |
| sources/multi_calendar | 无 `__all__` → `import *` 全公有名即覆盖 | test_multi_calendar |

## 2. 移动与垫片

- `mkdir -p domains/divination/{capabilities,data,store,service}` + 域根/四子包 `__init__.py`（单行 docstring，沿 W2/W3 房式）；10 件 plain mv（§4.2-R8 git mv 让位于「禁 git 写操作」任务纪律，保历史交提交方 rename 检测）。
- 真身导入重定向 11 处 + 1 处 docstring（sources.draw_store.DrawStore → domains.divination.data.draw_store.DrawStore）；contracts 与 content_parser 旧路径保持（见 §1）。
- 10 张 re-export 薄壳落旧位：`import *` + `import (__all__, <补名>)  # noqa: F401`；ruff 房式修正后与 W3 垫片同构（F403 未启用故星号行无需 noqa）。
- 同波测试改写 1 文件：`tests/test_card_prune.py` 两条 divination 导入改指真身新路径（垫片陷阱唯一命中，加注释说明）。
- §10 W-PA5 每域 extensions/ 占位：本波未建（RW2/RW3 先例均未建，留尾声波批量建，任务五步模板外）。

## 3. 回归（§6 直跑）

- ③ verify_hashes --check：exit 0 ✓（19 项零 divination 锚，预期内）
- ⑤ runtime_layout_smoke：PASS ✓（source_generated_dirs=empty / python_bytecode=absent）
- ⑥ ruff 本波 12 文件：19 处（RUF100 多余 noqa ×10 + I001 isort ×9）→ `--fix` 后 **All checks passed** ✓
- ⑥ mypy（dev.ps1 权威口径 `--explicit-package-bases --ignore-missing-imports plugins`）：**2 errors in 1 file（control_plane/api/platform.py 既有基线）, checked 424 files** — 本波零新增 ✓（注：单文件传参或不带 explicit-package-bases 会报 dual-module-name 假错，与既有配置口径不符，不采用）
- ⑦ 插件导入冒烟 + 垫片同一性 ×8：见 §4 时序记录
- ① 域测试：见 §4 时序记录

## 4. 并行席时序记录（如实留痕）

1. 首次冒烟：根 `__init__.py:34` `capabilities.fx` ModuleNotFoundError —— W7 finance 席 mv 已做、垫片未落的瞬态（本波零交集）。
2. 退避轮询 ~1 分钟后 W7 垫片落地（fx/market/stocks/meme 族齐）；二次冒烟前进至 `domains/finance/data/market_data.py:40` → `domains.link_parse.parsers.http_util` ModuleNotFoundError —— W7 真身导入重定向到 W1b 的 canonical 未来位，而 W1b（RW1a）基建 9 尚未迁移：跨席时序竞态，插件根导入被 W7→W1b 链阻断，非本波产物。
3. 本波域内门禁不依赖根导入的部分已先行全绿（见 §3）；依赖插件根导入的 ① 域测试 13 文件 + ⑦ 冒烟在 W1b 落地后补跑（见 §5 终态）。

## 5. 终态（补跑结果，W1b/RW8 落地后）

- **W1b 时序**：02:05 COORDINATION 见 RW8 席认领 W1b（16 件，含 RW7 移交 http_util 直连）；约 02:40 前后 parsers 基建落地、sources/registry 垫片回补完成（期间 root import 二次瞬态断裂，均退避轮询自愈，未越域触碰）。
- **⑦ 插件导入冒烟 + 垫片同一性 ×10**：OK（根 `__init__` 全量装载 + mail_adapter.ResilientMailAdapter + divination/ganzhi/iching/tarot/multi_calendar/character·sources·双 draw_store/fortune/tarot_draw/divination_service 垫片 re-export 与真身 `is` 同一性，含 5 个显式补名逐一断言）。
- **① 域测试 13 显式文件**：**743 passed, 1 skipped**（13.62s；含 test_divination_service_v21 跨进程黄金值子进程用例——字符串内嵌旧路径经垫片导入成功，零改动假设得证；含 test_card_prune 改真身后 monkeypatch 陷阱解除验证）。
- **① 关键词全库扫**（`-k "divination or tarot or ganzhi or iching or multi_calendar or draw_store or fortune or card_prune"`）：**538 passed, 1 skipped, 7197 deselected**。`--ignore` 两文件=test_asr_transcribe/test_voice_media_routing——收集期 ImportError 源于 W11 media 席在飞将 sources/vision_describe 转垫片未转出私有名 `_IMAGE_SEGMENT_TYPES`（RW6 日志「垫片私有名转出清单」同款系统性盲区，非本波产物）；rg 实证两文件零 divination/ganzhi/tarot/iching/multi_calendar/draw_store/fortune 引用后排除。
- **③ verify_hashes --check**：exit 0 ✓（终态复跑仍绿）。
- **⑤ runtime-layout**：首跑（≈01:45）PASS；终态复跑 FAIL——唯一失败项=`BOT_KNOWLEDGE_FILES` 两配置指向 `C:\Users\LancyCelestia\Documents\AI智能体有关材料\...` 下两份库街区百科 .md 缺失（窗口期内被外部移走/改名；脚本自 8 月 28 日未改、git 干净；源码树各面 source_generated_dirs=empty / python_bytecode=absent 首跑全过）。**外部环境漂移，非 W5 产物，提请用户补回知识文件或改配置**。
- **④ doc_sync 门**：9 passed（与树卫生同批）✓；`command_catalog.py --write` 再生：`docs/command-catalog.md`/`COMMANDS.md` 与当前 echo.py 一致——diff 归因=并行帮助批 echo.py 在途改动（75→77 模块/495→501 别名）被再生吸收，本波未触 echo/config，零 W5 引入漂移。
- **⑥ ruff 本波 12 文件**：All checks passed（终态复跑仍绿）✓；**⑥ mypy**（dev.ps1 权威口径）：424 files checked, 2 errors 全在 control_plane/api/platform.py 既有基线 ✓。
- **树卫生**：源码树零 `__pycache__/*.pyc/.pytest_cache`；qx.json 完好在 `domains/weather/assets/`（362774 字节未动）；`$TEMP/v21r2-rw5` basetemp 隔离；全程零 git 写操作。
- ② 渲染契约：未跑——本波未触 plain_text/roleplay/模板（§6 ② 适用面外）。
- ⑧ dev.ps1 全量门：席位禁令未跑（多席共享工作树全量门由主会话/收尾波裁决）。

## 6. 偏差与移交

1. **运行时边界（§8.1 域 9 契约注记）**：DivinationService/DrawStore 生产 wiring 未接（装配属后续席位），本波只搬家不改行为。
2. **runtime-layout 外部漂移**：BOT_KNOWLEDGE_FILES 两份知识文件缺失，需用户处理（非代码问题）。
3. **W11 席移交提醒**：sources/vision_describe 垫片需显式转出 `_IMAGE_SEGMENT_TYPES`（当前已致 test_asr_transcribe/test_voice_media_routing 收集红）——RW6 §六教训同款，望波内清零。
4. **§10 W-PA5**：extensions/ 占位未建（留尾声波批量建，与 RW2/RW3/RW6 口径一致）。

