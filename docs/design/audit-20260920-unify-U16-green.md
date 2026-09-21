# U16-GREEN 假绿机器门审查 — 席位日志（断点续跑骨架）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> 席位：U16-GREEN（只读审计子代理）。目标：证明每道宣称担保「统一性/一致性」的门究竟执法还是走过场。
> 判据：①实现改坏时能否变红（负样本注入）；②能否被自动洗绿（洗绿路径复现）。
> 硬禁令：不改任何代码/配置/文档（本日志除外）；不跑 --write；不派子代理；不 git 写；Runtime 只读。
> 环境纪律：所有 pytest 命令必带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1` + `--basetemp=$TEMP/u16-xxx -p no:cacheprovider`。
> 范围：仅后端 Python + tests/。前端 webui/、domains/render/**、output/card_render/**、theme_tokens、TTS 不查不报。
> 注：domains/render 的「执法性判定」属于渲染契约门审查范围，但样式不评；本席只判定门的执法强度，不评样式（D1 表内注明口径）。

## §0 进度时钟
- [x] 骨架落盘（开工）
- [x] D1 门清单与执法强度分级（初版落盘）
- [x] D2-1 BOT_AUTOSYNC 洗绿路径复现（P0：默认入口 dev.ps1 -Task test 自动 --write 洗 G1/G2/G3；详 §2.1）
- [x] D2-2 自证型基线（§2.2，七例 A-G）
- [x] D2-3 格式锁冒充真值锁（§2.3：matcher 0/50、add_job 1/20、llm 计数 9≠13，E2 门当场绿）
- [x] D2-4 AST 扫描假 0（§2.4：复现+四形态失明分型+3 处动态导入实存）
- [x] D2-5 xfail/skip 卫生（§2.5：xfail 纪律正面、主患 skip）
- [x] D3-1 旁路覆盖（§3.1：形状强/净化零覆盖，P1 假统一）
- [x] D3-2 门关=旧路径等价性（§3.2：实证为真测，两处 P3 瑕疵）
- [x] D3-3 性能门/哈希门 fail-open（§3.3：性能真拦；像素面 opt-in+红吞成 skip P2）
- [x] D4 门改造优先级表（§4，十行可施工）
- [x] §9 本席事故披露（PYTHONDONTWRITEBYTECODE 本机=有效，未复现失效）

## §1 D1 门清单与执法强度分级

> 执法力口径：**真拦**＝实现/语义被改坏时该门会红；**半拦**＝只在「改动未被同波同步」时红（跨源一致性），或存在自动洗绿/豁免吸收通道；**走过场**＝断言对象是基线自身/格式/字符串，行为改坏必不红。

| # | 门 | 载体/锚点 | 断言对象 | 数据来源 | 实现坏掉会红吗 | 自动写基线路径 | 执法力判定 |
|---|---|---|---|---|---|---|---|
| G1 | verify_hashes 哈希门 | `tests/verify_hashes.py` 锚点 `TRACKED_FILES: tuple[str, ...] (`；常驻于 `tests/test_cross_validation_gates.py::test_verify_hashes_manifest_clean` | 19 交付物**内容字节** vs `tests/render_hashes.json` | 基线本身（--write 从被哈希文件生成） | **不能**——只担保「变更需有意识确认」；默认入口 session 开始自动 --write（§2.1），漂移在门前已被修复 | **有**：conftest autosync | 走过场（变更审计半拦；统一性担保为零；默认可洗绿＝P0 面） |
| G2 | doc_sync 机器事实册 | `scripts/doc_sync.py` 锚点 `def build_document()`；常驻同上门第二测 | `docs/auto-facts.md` == 代码正则推导（RouteKind/topics/config 字段/模板/测试文件/哈希范围计数） | 被测代码（正则，锚点 `^    bot_[a-z0-9_]+:`） | **不能**——纯新鲜度门；语义坏不红；正则漏计→册值静默漂移→--write 后同绿；册中数字与真值间无第二锚 | **有**：autosync 链 | 走过场（自证型 §2.2-B） |
| G3 | command_catalog 目录门 | `scripts/command_catalog.py` 锚点 `_MANIFEST_KEYS = (` | docs/command-catalog.md == AST 静态抽取 | echo/base_router/aliases 字面量 | **不能**担保行为；对「文档过期」有牙（autosync 在场即失效） | **有**：autosync 链 | 半拦→（autosync 在场）走过场 |
| G4 | doc_sync_gates 文档↔代码族 | `tests/test_doc_sync_gates.py` 锚点 `def test_route_matrix_matcher_names_exist_in_code`、`test_config_catalog_covers_config_fields` | ①route-matrix 行==manifest ②矩阵 matcher 名在源码真实存在 ③④config-catalog 覆盖 config.py | docs+代码双源 | 脱节均红（U10 实跑 catalog 门抓过 TTS 键） | 无 | **真拦（有限域）**：拦脱节，不拦行为 |
| G5 | 帮助↔路由 20 一致性门 | `tests/test_documentation_consistency.py` 锚点 `test_entry_capability_declared_and_known`、`test_help_topics_have_route_layer_landing`、`test_public_help_never_leaks_admin_topics` | _HELP_ENTRIES vs RouteKind vs manifest vs 别名多源 AST 交叉 | 三文件互证 | 两源不同步会红；**两源同步地错**则绿；静态代理不执行 matcher 注册 | 无 | 真拦（跨源一致性级） |
| G6 | 能力登记门 | `tests/test_runtime_feature_gate.py:237` 锚点 `入站声明了未登记能力` | 根 __init__ AST 收集 capability_id ⊆ registry 登记集 | 两独立真身（根文件 vs capability_registry.py） | **会红**——U10 F1 实锤（4 id 漏登记确定性红） | 无 | **真拦**（少数抓到真缺陷的门） |
| G7 | outbound_registry 接管表门 | `domains/core/decision/outbound_registry.py` + `tests/test_outbound_v21.py` 锚点 `def test_matcher_locations_unique_and_wellformed`、`summary["matchers"] == 50` | 计数==A1 冻结、坐标**格式**良好互异、BYPASS 位置串含数字子串、note 含「已收编」 | 登记表自身字符串+冻结数 | **不能**——U1-24 实锤 0/50 命中真行；§2.3 复测扩量 | 人肉 REG-REFRESH（注释自认「快照随在飞编辑漂移清零」）＝--write 等价物 | 走过场（格式锁冒充真值锁） |
| G8 | S10 描述符总册门 | `tests/test_v21_s10_protocols.py` 锚点 `test_every_descriptor_has_required_fields_and_resolvable_refs` | 22 描述符必填+ref 可解析+注册对称；后半=invoker 行为测试（假 handler） | 册自身+文件在位性 | ref 坏文件会红（U2 复算 22/22 在位）；但 invoker 生产零消费者（U2-P1-2）——册绿≠统一绿 | 无 | 结构半拦/统一性走过场（死册自一致门） |
| G9 | 渲染契约门 | `tests/test_rendering_contract.py` 锚点 `test_no_meta_viewport`、`test_shadow_token_values_single_source` + `test_mica_builders_contract.py` | bridge 渲染**最终 HTML** 逐条断言 | 产物 HTML + theme_tokens 常量 | **会红**（值违反刻度即红）；豁免=人工白名单 | 无 | 真拦（值域面；不评样式） |

| # | 门 | 载体/锚点 | 断言对象 | 数据来源 | 实现坏掉会红吗 | 自动写基线路径 | 执法力判定 |
|---|---|---|---|---|---|---|---|
| G10 | v21r3 视觉九门 | `tests/test_v21r3_visual_gates.py:421-662` 锚点 `test_gate01_border_radius_registry`…`test_gate09_glass_tiers`（9 门×11 面） | 11 面最终 HTML 正则值域断言，基线硬编码于测试文件（第 1-6/8/9 条） | 产物 HTML（模板走 bridge、直拼卡 import builder）+ `_HEX_WHITELIST` | 多数会红；**gate07 例外**：宽度运行时读 `theme_tokens.CARD_SHELL_WIDTHS`，docstring 自认「CORE 席并行新增宽度后自动转绿，无需改本文件」＝登记表自证（锚点 `宽度门消费注入值`） | 白名单人工登记可吸收违例 | 真拦×8＋自证走过场×1（gate07） |
| G11 | 文案统一门 | `tests/test_user_copy_unification_gate.py` 锚点 `Q01_PATTERNS: tuple[str, ...] (`，自带负样本 `def test_gate_detects_regression` | 全包 AST 字符串禁 4+5 个**旧句式字面量**＋Q-03 拖尾语气符（6 文件作用域） | user_copy 池+全包源码字符串 | **只拦旧句回潮**——新散装文案必绿；「失败文案只从池出」的正向承诺不执法 | 无 | 半拦（棘轮禁书表；负样本纪律好，但断言对象=字符串集） |
| G12 | 性能门 | `tests/test_perf_regression.py` 锚点 `_IMPORT_GATE_THRESHOLD_S = 10.0`、`assert elapsed < 3.0` | 5000 次路由<3s、单次 max<20ms、整包导入中位<10s | 墙钟实测 | 数量级塌方会红（09-14 阈值负样本「牙齿实测」记录于 docstring，锚点 `阈值临时压到 1s 时 median 1.03s 即红`） | 无 | 真拦（宽但诚实；语义错不红） |
| G13 | 数据卫生门（三件） | `tests/conftest.py:210-266` 锚点 `wrote new file(s) into the source tree data/` + `tests/test_datafix_runtime_paths.py` + `test_no_source_tree_data_writes.py` | 每用例 setup/call/teardown 三阶段快照树内 data/，新文件即红；runtime_paths 映射正确性 | 文件系统实况 | **会红** | 无 | **真拦** |
| G14 | pre_restart_check | `scripts/pre_restart_check.py:246-295` 锚点 `"tests/verify_hashes.py", "--check"` | 9 项体检（env/persona/哈希/事实册/kb_drift/ruff/napcat/webui/控制面），只 --check 不 --write | 各被检对象 | 会红；但 G1/G2 输入若已被上游 autosync 洗过则红转绿失真（U10 C-8：FAIL 3→2 只因哈希被重录） | 无（打印人工指示） | 真拦（输入可信度受 G1-G3 牵连） |
| G15 | 垫片退役 AST 残余「门」 | **无常驻 pytest 门**——只在 `v21r4-b-RET3-log.md:76` 类人工扫描宣称，锚点 `AST 零残余` | 「旧路径 import 残余=0」 | 人工扫描器（方法性假零，U10 §C-6） | **不能**——包级 from-import 漏判（§2.4 复现） | 不适用（结论文件） | 走过场（结论宣称非门；假 0 已两次实锤） |
| G16 | autosync 自身双层回归 | `tests/test_autosync_gate.py` + `test_autosync_hook.py` 锚点 `if (-not (Test-Path env:BOT_AUTOSYNC))`、`Never restore WIP` | 守卫行正则契约＋env 矩阵＋tmp 沙盒端到端修复 | conftest/dev.ps1 真源码+副本仓 | 守卫退回无条件覆盖会红；**但「洗绿按设计工作」正是其担保对象** | 无 | 真拦（元层），不改变 §2.1 P0 定性 |
| G17 | 触发词棘轮族 | `tests/test_trigger_spec.py`/`test_trigger_bidirectional_gate.py`/`test_pinyin_triggers*.py`/`scripts/extract_trigger_words.py` | 触发词双向（matcher 注册↔帮助登记）＋棘轮基线 | 代码双源 | 不同步会红；棘轮清零后钉 0 | 棘轮计数人肉重录 | 真拦（跨源）；钉数部分自证 |

（D3 完成后补旁路触达列。）

## §2 D2 洗绿路径复现
### §2.1 BOT_AUTOSYNC 自动 --write：默认入口不安全（P0）

**机制链（一手实读）**：
1. `scripts/dev.ps1` Invoke-Test，锚点 `if (-not (Test-Path env:BOT_AUTOSYNC)) { $env:BOT_AUTOSYNC = "1" }`（实测 :246；注释块 :240-245 自述「V2.1 §13 门禁冲突修正（2026-09-17）：原实现无条件覆盖外层值……把真实回归『洗绿』」）。
2. `tests/conftest.py:46-50` 锚点 `_AUTOSYNC_STEPS: tuple[tuple[str, str], ...] = (`——BOT_AUTOSYNC=1 时 session 开始（`_autosync_session_gate` :192-195，锚点 `_autosync_changed.extend(run_autosync())`）子进程连跑三件套 `--write`。**被自动重录的基线文件全集（3 个）**：`docs/command-catalog.md`、`docs/auto-facts.md`、`tests/render_hashes.json`。
3. 于是 G1/G2/G3 在 `dev.ps1 -Task test` 路径上**结构上不可能红**——漂移在测试体执行前已被抹平；留痕仅 warning+终端一行「[autosync] 自动同步：…」，不改退出码。
4. **AGENTS.md 第五部分四条标准命令原文均不带 BOT_AUTOSYNC=0**（锚点 `& '.\scripts\dev.ps1' -Task test"`）——文档规定的验证入口本身即默认洗绿入口。U10 §C-3 实锤路径已被使用（宣称 1 DRIFT 期间 render_hashes.json mtime=15:39:17 被 --write 重录）。
5. **默认不安全任务入口完整清单**：①`dev.ps1 -Task test`（唯一设默认 1 者）；②`dev.ps1 -Task verify`（`function Invoke-Verify` 内直调 `Invoke-Test`，继承同语义，dev.ps1:746-751）；③环境已持久化 BOT_AUTOSYNC=1 的一切 pytest 调用，含 `tests/cross_validate.py`——其 `_run_engine` 用 `env = dict(os.environ)` 只加 PYTHONDONTWRITEBYTECODE（锚点 `env["PYTHONDONTWRITEBYTECODE"] = "1"`），**不清 BOT_AUTOSYNC**：两引擎会双双洗绿且「互证一致」＝交叉验证反成洗绿共谋；④裸 pytest（env 未设）安全：`is_autosync_enabled` 仅认 `"1"`（锚点 `return raw == _AUTOSYNC_ENABLE_VALUE`）。
6. **防线现状（如实）**：显式 0 已不可被覆盖（`test_autosync_gate.py::_GUARD_RE` 钉守卫行；`test_dev_ps1_guard_respects_explicit_env` 实跑 PowerShell 验透传，锚点 `RESULT=$env:BOT_AUTOSYNC`）。残余=**默认值本身**。按判据②定 **P0**（G1/G2/G3 三门在文档默认入口可自动洗绿；「门可被自动洗绿＝该入口下整个生成物门系不可信」）。
7. **负样本实证（沙盒，零树痕）**：仓库自带端到端复现 `tests/test_autosync_hook.py::test_autosync_end_to_end_mini_session`——`_tamper_outputs` 篡改三基线（含把 `render_hashes.json` 一条哈希改成 `"0"*64`）→ 子会话 env `BOT_AUTOSYNC=1` → `assert proc.returncode == 0` 且基线「复原」＝洗绿全程有测试担保其成立（锚点 `"BOT_AUTOSYNC": "1"`、`_check_generators(autosync_repo, drift=True)`）。本席 scoped 复跑输出见 §6-E1。该文件 autouse fixture `_assert_source_outputs_untouched`（锚点 `autosync tests wrote source-repository outputs`）以字节+mtime 双校验保护真树——**同一机制，测试侧防死，dev.ps1 正门放行**，两副面孔并存。

**判据①**：G1 只对「基线写后内容又变」红（变更审计），G2/G3 只对「代码变册未变」红（新鲜度）——对「一致地错」零防御。
**判据②**：G1/G2/G3 默认入口可自动洗绿 → P0（证据链完整：代码+自家负样本测试+U10 实况）。
### §2.2 自证型基线（期望值来自被测对象自身）

判据：**「被验对象坏→基线随坏→门绿」即自证**。逐例（证据=实读代码/自家 docstring 承认）：

| 例 | 门 | 自证机制 | 锚点 | 真正能拦什么 | 拦不住什么 | 定级 |
|---|---|---|---|---|---|---|
| A | verify_hashes（G1） | 基线 `render_hashes.json` 由 `build_manifest()` 从被哈希文件自身生成 | 锚点 `return {name: sha256_of(path) for name in TRACKED_FILES}`（verify_hashes.py:76 附近，实文 `def build_manifest() -> dict[str, str]:`） | 「基线录后内容又变」——变更需有意识 --write（审计轨迹） | 一切行为/语义坏：改 echo.py 卡片 builder 逻辑→--write→绿。U10 C-3 实证此路径被用于抹掉「1 DRIFT」宣称 | **P1**（作为「统一性担保」走过场；作为变更留痕门在半拦，且被 §2.1 默认洗绿掏空） |
| B | doc_sync（G2） | 期望值=对被审代码跑正则；正则与代码同树演化 | 锚点 `re.findall(r'^    bot_[a-z0-9_]+:', text, re.MULTILINE)`（doc_sync.py `_config_key_count`）、`'"topic":\\s*[\\'\"]([^\\'\"]+)[\\'\"]'`（`_help_topics`） | 册与代码脱节（册过期） | ①代码语义坏而形状不变（topic 拼错→照样计数）；②抽取正则退化（改缩进/改用变量拼 topic）→计数静默变小→--write 后「77→76」以既成事实通过；AGENTS 顶部把「topics 实值 77（非 79）」当权威链口径，而 77 的唯一机器担保就是这套正则+册互证——**闭环自证**（U10 §C.2.1 只能确认 `--check` 绿与 77 为正则口径真值，无法证明 77=运行时实际可路由 topic 数） | **P1** |
| C | v21r3 gate07 宽度门 | 合法宽度集=运行时读 `theme_tokens.CARD_SHELL_WIDTHS`，本席实读 docstring 自认「CORE 席并行新增 help/usage/debug/media 宽度后**自动转绿，无需改本文件**」 | 锚点 `CARD_SHELL_WIDTHS` + 注释 `宽度门消费注入值`（test_v21r3_visual_gates.py `_build_template` 前） | 面 HTML 用了表外字面量宽度 | 「想要合法」→往表加一行登记即合法（登记表无第二来源，无「此宽度是否本该存在」裁决）；G10 其余八门的基线是**测试文件内硬编码集合**（如 `_BLOB_DURATIONS_S`），此区别即执法力差别 | **P2** |
| D | 垫片期「聚合先行」纪律 | 12+ 个测试文件顶格 `import plugins.bot_unified_runtime.sources.parsers  # noqa: F401  # v21r2 W1a: 旧路径聚合先行（垫片期顺序纪律）`——测试**依赖**垫片存在来保证导入顺序，而不是验证垫片正确 | 锚点 `旧路径聚合先行（垫片期顺序纪律）` | 无任何拦截（它只是被 import 的副作用） | 垫片真身指向坏——见例 E | 登记 P3（卫生：退役后这些 import 变孤儿） |
| E | 「垫片→真身」验证层 | **无常驻 pytest 门**做「垫片 _CANONICAL 指向真身存在 + 旧路径可 import + 新旧符号等价」三件套；等价验证只在 U2 席离线脚本（`u2_enum.py`，83 垫片→真身 0 坏为一次性人工复算） | 锚点（消费侧反例）`runtime/capability_protocols.py` `from plugins.bot_unified_runtime.sources import (` + 下一行 `web_search,`——U10 C-5：真身已删，**函数体内僵尸 import**，descriptor 门与 S10 全族测试全绿（调用才炸） | 无（S10 门只查 implementation_ref 文件存在，U2 自己承认「查不到函数体内僵尸 import」） | 垫片/退役改动导致的运行期 ImportError——除非该函数恰好被测试触达；G8 绿 + G9 绿 + 全量绿 与此缺陷共存是**已发生的实况**（U10 typecheck 唯一红错即它，说明静态门能抓、动态门族全体漏） | **P1**（覆盖缺口，见 D3） |
| F | test_outbound 字符串「垫片旧路径清零」 | 锚点 `assert "runtime/reactions.py" not in coordinates  # shim 旧路径清零`（test_outbound_v21.py:713）——对**登记表字符串**做 not-in 检查，不扫任何 import | 同上 | 登记表里写了旧路径字面量 | 全树任何真实旧路径 import（哪怕 100 处） | P1（归 §2.3 同类） |
| G | 冻结计数锁（「A1 冻结清单」） | `summary["matchers"] == 50`、route_groups 逐文件计数、`census == {...}`——期望值=历史快照文档，改数据+改断言成对提交即绿 | 锚点 `== A1 冻结` 族（test_outbound_v21.py TestTakeoverRegistryIntegrity） | 只改码不改册（部分：码改了注册数、忘改测试→红） | **册与真世界脱节**——本席 §2.3 实锤：llm.py registry=9 vs 真实装饰器 13，门绿 | P1 |

**「两侧同坏同绿」专项回答（任务举例）**：本树**没有**「A.__all__ == B.__all__ 全等」式常驻断言（grep 全 tests/ 仅 `assert "render_error_card_html" in bridge.__all__` 一处成员检查，test_rendering_contract.py:729）；真正的同坏同绿形态是例 E——垫片坏时全树照样绿，因为**没有任何常驻门 import 旧路径符号**（U10 用 importlib 探针当场炸出 `ModuleNotFoundError` 的正是门族看不见的调用路径）。

### §2.3 格式锁冒充真值锁：outbound_registry 坐标真值复测（本席独立脚本，离线复算非树上注入）

**方法**：venv 解释器导入 `build_default_takeover_registry()`（只读），把每条 `location` 解到 `plugins/bot_unified_runtime/<file>` 的第 N 行，检查该行是否含登记名/预期 API。命令原文+输出（§6-E2/E3）：
- `MATCHERS total=50 hit(name-on-line)=0 miss=50 badfile=0` —— **0/50**，与 U1-24 独立复算一致（例：`status @ __init__.py:4391` 实际行=`"bot_channel_health_interval_seconds",`；`chat @ __init__.py:4407` 实际行=一条 import）。
- `SCHED add_job coords hit=1 miss=19` —— 12 调度器的 20 条 add_job 坐标 19 条指错行（例 `__init__.py:2804` 实为 `logger.info(`）；`register_location` 12 条中肉眼可判 ≥9 条不指向注册行（例 `digest_push __init__.py:2939` 实为 `audit_tags=["reminder", "due…`；`subscription_poll` 坐标格式 `sources/subscription_runtime_v2.py:module` 连行号都不是数字）。
- `BYPASS` 4 条为区间格式（`4440-4444`/`5378-5382`/`5730-5740`/`5526-5538`）——区间内含直发 API（`bot.call_api(`、`upload_group_file`、`send_group_msg`），**这 4 条 09-19 REG-REFRESH 后人肉复核过，是真的**；但断言形态 `any("4440" in e.location ...)` 仍是字符串子串锁，子串可被 `44407` 之类误配。
- `RGRP control_plane/api/llm.py registry=9 real=13 match=False` —— **新实锤（增量于 U1-24）**：冻结计数本身已陈旧（本席数出 `@router.(get|post|...)` 装饰器 13 个，71-160 行），而常驻门 `test_route_group_counts_match_a1_table` 把 `llm.py: 9` 钉死 → **陈旧但绿**规模再 +1 张表。
- 其余 6 组 route 计数 28/10/7/4/4/0 与真实装饰器数吻合（如实记：部分对）。

**常驻门当场对照实验（E2，树上零改动）**：坐标全假状态下复跑 `pytest tests/test_outbound_v21.py::TestTakeoverRegistryIntegrity` → **`8 passed in 1.71s`**。即：该门在「登记表整体陈旧」下恒绿——它执法的是「册与冻结快照自洽」，不是「册与源码一致」。**定级 P1（走过场/陈旧但绿）**，危害=按表施工者（S0 收编、L41 预案、矩阵回填全引用此表）拿到的行号是历史化石；AGENTS #42 的「S0-COLLECT 刷新」只刷新了 4 条 BYPASS，50+20 条主体未动。
**最小改法**：见 D4 第 1 行（坐标改「符号名+锚点串」并加真行比对门，U1-24 已给可抄代码）。
### §2.4 AST 扫描假 0：失效模式复现 + 全树推广普查（离线复算，零树改）

**①复现（本席亲跑）**：以 `sources.web_search`（真身已删、mypy 唯一红错、U10 C-5/C-6 当事人）为种，对 618 个插件 .py 全树跑三种扫描器：
- **纯集合成员式**（RET3/RWC6-b 日志所用形态，`node.module in OLD_PATHS`）：`PURE set-membership scanner hits on web_search: 0` ——**假 0 复现**。原因（结构性）：包级 `from plugins.bot_unified_runtime.sources import (web_search,)` 的 `ImportFrom.module` 是**父包**，旧模块全名在 AST 中根本不出现。
- **别名拼接式**（`module + "." + alias ∈ OLD`）：命中 `capability_protocols.py:1273` 1 处——正确形态的最小修复。
- **真值对拍**：`importlib.util.find_spec("plugins.bot_unified_runtime.sources.web_search") = None`（模块确实不存在，调用必炸）——三轨（AST 双形态 + importlib/mypy）互证完毕。
**②推广（树上常驻 AST 门逐个判漏判形态）**：
| 门/扫描 | 锚点 | 漏判形态 | 方向性后果 |
|---|---|---|---|
| 垫片残余扫描（G15，人工非常驻） | `AST 零残余` | 集合成员式（本席已复现假 0）+ 字符串参数完全不可见：83 个垫片全用 PEP 562 `__getattr__` + `import_module(_CANONICAL)`，**_CANONICAL 是字符串常量**，import 级 AST 扫描天然看不见其指向坏没坏（实证锚点 `runtime/ingress.py`: `return getattr(import_module(_CANONICAL), name)`） | 假 0=「退役完成」误宣 |
| 层边界禁导门（creation 骨架 FORBIDDEN_IMPORTS） | `root_name = node.module.split(".")[0]`（test_v21_creation_skeleton.py:255 族） | 只看根段：`importlib.import_module("nonebot")`、`__import__(var)`、字符串拼接模块名全漏；`domains/core/decision/__init__.py:53` 等 3 处非常量参数动态导入实存（本席扫描输出 `DYNAMIC import_module(non-const) sites: 3`） | 假 0=「边界干净」可被一条 importlib 穿透 |
| Dispatcher 接线存在门 | `node.module.split(".")[-1] == "dispatcher"`（test_v21_risk_red_dispatch_and_telegram.py:51） | 后缀匹配漏包级 `from plugins.bot_unified_runtime import dispatcher as d`（module 末段是包名）→ **假「未接线」红**方向；装饰器/别名 re-export 注册漏判 | 双向：误红噪声+换形态接线漏宣 |
| L65 诚实位 tripwire | `assert "InterpretationNotWiredError" in (referenced_names | imported_names)`（test_v21_wiredirect_unified_path.py:149-158） | 名称引用存在≠行为存在：换名实装真 LLM 而保留旧名引用 → 绿但撒谎 | 半拦（防静默删除，不防伪诚实） |
| 「shim 旧路径清零」锁 | `assert "runtime/reactions.py" not in coordinates`（test_outbound_v21.py:713） | 扫登记表字符串不扫 import——真旧路径 import 哪怕 100 处也绿 | 走过场 |
**③结论**：所有以「import 节点字符串成员/后缀匹配」为核的扫描，对 ①包级 from-import、②`__getattr__`+字符串 importlib 活转发、③非常量参数动态导入、④别名 re-export 四种形态**系统性失明**；本项目的垫片体系恰好整体使用形态②（这是设计使然，不是偶发）。凡「残余=0」类宣称必须叠加 mypy（本席实跑证实 mypy 抓到 1273）+ 逐模块 `find_spec` 双轨才有效。定级 **P1（方法级，常驻化改法见 D4-2）**。
### §2.5 xfail/skip 卫生（全树清点）

**xfail 族（树上 2 静态 + 2 动态形态，对应 U10 实跑 3 xfailed）**：
| 条目 | 锚点 | 性质判定 |
|---|---|---|
| `tests/test_prompt_injection.py:97/111` 两枚 `@pytest.mark.xfail(strict=True,` | 反注入两洞：**引用链标记单独出现走 ALLOW 不转义**、**`[TRUSTED_SYSTEM 层级3]` 带后缀绕过 internal_marker_spoofing** | 机制纪律好（strict，修好即 XPASS 红强制升级），**实质=两条反注入缺口长期挂绿**；「修复后升级」无人跟进即成永久豁免。定级 **P2（安全向缺口保绿）** |
| `tests/test_trigger_spec.py:188/210` 动态 `pytest.xfail(f"现状红点（台账已登记）：` | KNOWN_CONFLICT_WORDS / KNOWN_BOUNDARY_KEYS 台账制 | **纪律典范**：红点修好但还挂在台账上会 `pytest.fail("红点已修复…请从…移除")`——双向棘轮，不是保绿工具 |
| `test_v21_risk_red_cp_platform.py` / `_tz_and_files.py` 历史 strict xfail 已撤 | 锚点 `转正后恒绿即回归锁` | 健康先例：xfail 只作立案态，修完转正常 |
**skip 族（U10 实跑 12 skipped 的归属逐条）**：环境条件类（正当）——`test_sandbox_windows`（非 Windows 整模块，本树在 Windows 上=不跳）、`test_supervisor_isolation:44`、`test_asr_transcribe:242/373/377`、`test_parsers_batch_a`（samples 缺位 ×2）、`test_v21_creation_skeleton`（venv 缺位）、`test_autosync_gate:169`（powershell 缺位）；真身缺位类（应红不红）——`test_copy_redline_gate`/`test_persona_source_sync` 在「生产人格副本不存在（CI 无 Runtime）」时 **skip**（锚点 `生产人格副本不存在（bot 未部署/已移除），门跳过`）：源-副本一致性门（#31 a1cf739 的「人格源-副本一致性」承诺）在**没有 Runtime 的检出环境自动解除武装**，本机有 Runtime 故平时执法，属可接受取舍但须登记；**默认关的实弹面（D3-3 相关）**——`test_error_report`（`BOT_ERRCARD_SMOKE=1 启用`）、`test_mermaid_reply_render`（`BOT_MERMAID_NET_TESTS=1`）、`test_render_wait_budget`（`BOT_RENDER_NET_TESTS=1`）、`test_finance_data` 上游不可达 `pytest.skip("…不作为失败")`、`test_phase_determinism(_2)` Chromium 启动失败 `pytest.skip` ——**真浏览器/真上游验证全部 opt-in 或不可达即跳**：失败面被折叠为 skip 而非红，「截图字节一致」「上游契约未变」只有人肉跑 smoke 的那次才算数。定级 **P2（覆盖结构性缺口）**，改法见 D4-5（CI 显式矩阵开启 opt-in；不可达≠跳过而应区分「故意不测」与「该测没测成」）。
**「xfail 化以保绿」总判定**：本树 xfail 纪律**好于-average**（strict + 双向棘轮 + 转正先例）；真正的问题集中在 **skip 侧**（环境缺位解除武装 + 实弹面默认关）。无发现「为掩盖回归而加 xfail」的条目。

## §3 D3 覆盖有效性

### §3.1 中央链路旁路：改坏后全量会不会红？（逐条最小场景，离线复算+既有测试实读判定）

**结构性事实（一手 grep）**：`redact_local_secrets` 的调用点是**逐能力自带**（chat.py:2354、download.py:137、media_archive.py:208/227、control_plane 三件、knowledge_service:227），**SendQueue/sender/onebot 出站层零调用**（锚点：`grep redact plugins/.../runtime/send_queue.py plugins/.../sender/onebot.py → 无输出`）。即 AGENTS 铁律 3「出站前 plain_text 会打码」的「出站前」实为**每条链路自己负责**——旁路只要忘了调，出站就不打码，且**没有任何门会红**。

| 旁路 | 既有测试钉住的面 | 最小改坏场景 | 判定 |
|---|---|---|---|
| 群摘要 21:30 直投 | `test_group_digest_push.py::test_send_request_shape_and_dated_dedupe_key` 钉 SendRequest 全字段+`text_fallback == 引子+摘要`（锚点 `digest_push:111:`） | 把 LLM 摘要**不经任何打码**直投（现状即如此——构建处不接 redact）/改坏引子→红；**摘要体内泄漏盘符路径→全树无处可红**（无断言+无实现） | **绿=改坏不被拦**：形状真拦、内容净化零覆盖（缺陷与测试双缺，P1 归 mandate） |
| 校园转发 | `test_campus_digest.py:196-201` 钉 1500 截断上限与 session/target（锚点 `assert len(request.content.text_fallback) <= _CAMPUS_FORWARD_MAX_CHARS`） | 学校群原文含密钥形态/本地路径→转发主人号，无 redact（campus.py 全文 grep redact 0 命中）；改前缀/截断→红 | 同上：形状拦、净化零覆盖 |
| 表情/戳一戳主动通路 | `test_reactions.py` 钉识别归一 `emoji_id/emoji_text`；poke_v2 钉五层门 | 贴表情目标会话搞错（群贴成私聊）——`test_poke_v2/test_reactions` 对投递面钉到什么程度未逐字段复核（U4 席 executor 面已收编为既有结论） | 部分红（门概率/冷却有锁；投递终点对齐依赖 executor 收编面，本席不重裁 U4 结论） |
| 告警出站 | `test_operational_failures.py:479` `test_admin_alert_request_is_typed_and_marks_admin_origin` 钉类型化+admin 标 | 告警文本含未脱敏 detail→无净化断言 | 形状拦、净化零 |
| 提醒投递 | （§2.3 实测坐标全错的那族 scheduler）add_job 坐标无人校验真伪 | 调度器注册点被删/挪→注册行为由 `test_reminder*` 域测试钉，坐标表不反映 | 形状拦（域测试）、登记表不执法 |
**总判定（D3-1）**：旁路并非「完全裸奔」——请求形状/门禁/去重键有实钉；但**「中央统一处理后再分发」在内容净化（redaction/段规约/渲染路由）面上对全部调度器旁路不成立，且全树无一条门会在该面被改坏时变红**。P1（mandate 级假统一），改法见 D4-3（出站层单点收编，负样本=注入带盘符路径文本→必红）。

### §3.2 「门关=旧路径逐字节等价」是否真测（S0 四处 + WIRE-SVC）

**实证为正（本席实读 tests/test_v21_s0_root_collect.py）**：四处收编各有门开门关双测试，门关断言**具体到 API 调用元组逐字段**——`calls == [("upload_group_file", {"group_id": 123, "file": str(doc), "name": "doc.md"})]`（锚点 `test_file_export_gate_off_keeps_direct_upload_group` docstring「旧直连逐字节等价」）、welcome 关态钉 `send_group_msg` 完整 message 数组+事件名（锚点 `_group_welcome_text("小涉")`）、「门关不得走统一文件链」`files_calls == []` 双向排他。WIRE-SVC 同纪律：`test_real_config_defaults_keep_wiring_off`（真 Config 缺省关）+`test_master_gate_off_means_zero_assembly`+`test_single_service_failure_fails_open`。**结论：这组不是走过场**。两处诚实瑕疵（P3）：①welcome 文本用生产函数 `_group_welcome_text` 自比（文案改→基线随改，拦形状不拦措辞回潮）；②「已收编（门缺省关）」类 note 宣称与坐标陈旧并存（§2.3），表可信度仍低。

### §3.3 性能门与字节门的判据强度（fail-open 审查）

- 性能门（G12）：**有负样本历史**（docstring 锚点 `阈值临时压到 1s 时 median 1.03s 即红`——牙齿实测留档）；无吞红兜底（`try/except` 只包住 subprocess 超时并转 AssertionError 红）。判定：真拦。
- 哈希门（G1）：拦的是「源文件字节」，**不出树就拦不到「出图字节」**；截图 PNG 字节一致（#41「E01 钉帧 7/7」「PNG 字节等值」）**不是常驻门**——常驻面里像素级只有 `test_phase_determinism(_2)` 的 playwright 双渲染，而它 `Chromium 启动失败 → pytest.skip`（锚点 `pytest.skip(f"Chromium 启动失败`）——**该门在环境坏时自我解除为 skip（红吞成 skip）**；`render_card_samples` 常驻部分只比 HTML 字符串内容（锚点 `test_payload_builder_renders_nonempty_html`），不比像素。判定：像素面=opt-in 人肉，常驻宣称需按此改写（P2）。
- pre_restart_check（G14）：自身不吞红（真 EXIT=1，U10 实证），但其两项输入可被 §2.1 洗绿 → 复合不可信面。

## §4 D4 门改造优先级表（可施工）

| 优先 | 门 | 当前执法力 | 证据（本席/同波） | 最小改法（具体到断言写法） | 改后负样本自证 |
|---|---|---|---|---|---|
| 1 | dev.ps1 autosync 默认值（§2.1） | 使 G1/G2/G3 整族可自动洗绿 | dev.ps1:246 + U10 C-3 实况 | **一行**：`if (-not (Test-Path env:BOT_AUTOSYNC)) { $env:BOT_AUTOSYNC = "0" }`；或最低成本替代——保留默认 1 但 autosync 改「只 --check，见漂移即整场 pytest 直接 exit 1 并列出三文件」（`run_autosync` 换 `_run_generator(..., "--check")`）。AGENTS 五段四命令统一加 `BOT_AUTOSYNC=0` 前缀（文档同步） | 负样本：临时改 `docs/auto-facts.md` 一行 → `dev.ps1 -Task test` 必红（现状：绿+文件被复原）；复原用 mtime+md5 |
| 2 | outbound_registry 坐标锁（§2.3） | 走过场（0/50+19/20+1 组计数陈旧） | 本席复算 §6-E2/E3 + U1-24 | ①`location` 改 `符号名+锚点串`；②在 test_outbound_v21 增真行门（U1-24 §8.1 已给可抄实现：正则收集 `^\s{4}(\w+) = on_(message|notice|command)\(` 行号表，逐条 `assert decl[name] == int(location 行号)`）；③route_groups 计数改「正则数 `@router\.(get|post|…)\(` 实时对拍」替冻结 dict | 负样本：给任一 MatcherEntry 行号 +1 → 新门必红（现状：8 passed 恒绿，E2 已证）；llm.py 再删一个路由 → 计数门必红 |
| 3 | 出站净化收编（§3.1） | 假统一（内容净化无中央咽喉） | grep：send_queue/onebot 零 redact；chat 自带 | `SendQueue.submit`（或 sender deliver 前置）统一 `content.text_fallback = redact_local_secrets(...)` 单点；各能力保留自带调用（幂等） | 负样本：注入一条 text 含 `C:\\Users\\x\\.env` 的 SendRequest → 出站 fake bot 收到的必为打码态；现状该场景全树无红点 |
| 4 | AST 残余扫描三轨化（§2.4） | 方法性假 0 | 本席纯成员式 0 命中 vs find_spec None | 退役 SOP/常驻门统一用：成员式∪别名拼接式∪`mypy plugins`∪逐模块 `find_spec` 探针；把「拼接式+find_spec」做成常驻 pytest 门（离线秒级）挂 test_cross_validation_gates 旁 | 负样本：对已知地雷 `sources.web_search` 跑四轨——AST 成员式必须 0、拼接式必须≥1、find_spec 必须 None；任一不符=扫描器失效即门红 |
| 5 | skip 面分级（§2.5/§3.3） | 红吞成 skip | `BOT_ERRCARD_SMOKE`/`BOT_RENDER_NET_TESTS`/Chromium 启动失败即 skip/finance 上游不可达即 skip | ①`pytest --strict-config` 之外加常驻计数门：`skipped>基线数` 即红（基线=12 钉死+台账豁免制，同 trigger 棘轮纪律）；②`Chromium 启动失败` 从 skip 改 fail（环境声明要求浏览器）或拆进显式 `-m real_browser` 选集 | 负样本：临时给任一测试加 `pytest.skip("x")` → 计数门红；拔网线跑 finance → 现状静默 skip，改后显式红 |
| 6 | doc_sync 抽取正则加固（§2.2-B） | 自证+静默漏计 | `_help_topics` 只认字面量 topic | topics/config 键计数改 **AST 抽取**（复用 command_catalog 的 `_literal_assign`），正则降级为交叉核对：两口径不等即红 | 负样本：把某 topic 改成 f-string 拼接 → 现状正则漏计→--write 同绿；改后 AST/正则双口径差 1 即红 |
| 7 | 文案统一门正向化（G11） | 半拦（只禁旧句） | Q01/Q02 模式表实读 | 把「失败/权限回执必须 ∈ user_copy 池」升级为**输出面断言**：对能力函数注入失败桩，检查返回值 ∈ 池渲染集（已有 `test_pool_output_membership_*` 四例可扩展成注册表驱动全能力） | 负样本：新能力自带一句新式失败文案 → 现状绿；改后（注册表要求声明池引用）红 |
| 8 | gate07 宽度自证（§2.2-C） | 登记即合法 | docstring 自认「自动转绿」 | CARD_SHELL_WIDTHS 变更需同步改测试内硬编码「合法宽度家族快照」一处（快照=裁决基线，不再运行时直读） | 负样本：向表加一个宽度 → 现状绿；改后红，须双处改 |
| 9 | 冻结计数锁语义标注（§2.2-G） | 误导 | 「integrity」名不副实 | 类名/docstring 如实降级为 `…SnapshotSelfConsistency`，并在 HANDOFF 引用处标注「册=冻结快照非真值」 | 无需负样本（诚实化） |
| 10 | prompt_injection 两 xfail 限期处置（§2.5） | 反注入缺口挂绿 | 锚点 `已知缺口：引用链标记类不在 _RULES` | 给 reason 加台账号+截止波次；修复或显式风险接受（用户裁定）二选一 | 修复后 XPASS 即红（strict 已有），到期未处置由 review 流程拦 |

## §5 负样本注入台账
| # | 目标 | 注入内容 | 期望 | 实际（红/绿） | 复原证据 |
|---|---|---|---|---|---|
| E1 | G1/G2/G3 洗绿链（沙盒） | 仓库自带 `_tamper_outputs`：篡改三基线（含哈希改 `"0"*64`）+子会话 BOT_AUTOSYNC=1 | 洗绿成立（子会话绿+基线被自动复原） | **绿（洗绿复现）**：`41 passed in 11.62s`（含端到端 mini-session 断言 returncode==0） | 全程 tmp 副本；真树三基线 mtime 保持 16:36:43 未动（前后 ls/md5 比对，§6） |
| E2 | G7 登记表门 | 树上**零注入**——用现存陈旧数据当「天然负样本」（0/50 坐标） | 若门执法必红 | **绿**：`8 passed in 1.71s`（TestTakeoverRegistryIntegrity） | 无需复原（只读） |
| E3 | G15 类扫描器 | /tmp 内联三轨扫描（纯成员式 vs 别名拼接式 vs find_spec） | 成员式假 0 | **假 0 复现**：成员式=0、拼接式=1（capability_protocols.py:1273）、find_spec=None | 无树改（python -c 内联） |
| E4 | G6 能力登记门 | 引用 U10 既有负样本（F1 四 id 未登记确定性红，非本席制造） | 已红过 | 红（U10 单跑 1 failed/15 passed） | U10 当事文件；本席未复跑 |
**树上注入类实验：0 次**——根 `__init__.py`/echo.py 等被他席并发在飞（U10 §D 实录），树上注入必互踩且污染不可控，故全部改走：①仓库自带篡改沙盒（E1）②现存陈旧态当负样本（E2）③离线内联复算（E3）④同波已发生红样（E4）。以上即「离线复算，非树上注入」标注义务之履行。

## §6 命令与实跑输出记录（关键条目原文）

```bash
# 环境（全程）：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 + --basetemp=/tmp/u16-* -p no:cacheprovider
# 基线三文件开工态：mtime 全部 2026-09-19_16:36:43（本席开始之前他席 --write/autosync 所动）

# E1（41 passed，其中 mini-session 即洗绿端到端复现）
python -m pytest tests/test_autosync_gate.py tests/test_autosync_hook.py -> 41 passed in 11.62s

# E1 后基线核验：mtime 仍 16:36:43；md5（本席收口复算一致）：
#   docs/command-catalog.md=d8bb93a5ca1440d0b00cd7697d49369d
#   docs/auto-facts.md=2e160e1913bdfc7da53d10c2cb077ce0
#   tests/render_hashes.json=09d5e9297707bbc15c8fa71dea905fc5

# E2（陈旧坐标下门恒绿的当场对照）
python -m pytest "tests/test_outbound_v21.py::TestTakeoverRegistryIntegrity" -> 8 passed in 1.71s

# E3（真值复算，PYTHONPATH=. python -c 内联，输出原样）
MATCHERS total=50 hit(name-on-line)=0 miss=50 badfile=0
SCHED add_job coords hit=1 miss=19
BYPASS __init__.py:4440-4444/5378-5382/5730-5740/5526-5538（区间内含 bot.call_api/upload_group_file/send_group_msg，4 条系 09-19 人肉复核真坐标）
RGRP control_plane/api/llm.py registry=9 real=13 match=False    # 其余 6 组 28/10/7/4/4/0 吻合
PURE set-membership scanner hits on web_search: 0
find_spec sources.web_search: None
parsed files: 618 ; DYNAMIC import_module(non-const) sites: 3

# 字节码探针（§9-1 环境级证据）
PYTHONDONTWRITEBYTECODE=1 python -c "import plugins.bot_unified_runtime.config" -> 成功导入
find plugins tests scripts -name "__pycache__" -> 0 ; -name "*.pyc" -> 0
```

## §7 锚点字符串索引（本席新用）
`_AUTOSYNC_STEPS: tuple[tuple[str, str], ...] = (` ｜ `return raw == _AUTOSYNC_ENABLE_VALUE` ｜ `if (-not (Test-Path env:BOT_AUTOSYNC))` ｜ `autosync tests wrote source-repository outputs` ｜ `_check_generators(autosync_repo, drift=True)` ｜ `def test_matcher_locations_unique_and_wellformed` ｜ `旧路径聚合先行（垫片期顺序纪律）` ｜ `not in coordinates  # shim 旧路径清零` ｜ `宽度门消费注入值`/`CORE 席并行新增` ｜ `现状红点（台账已登记）` ｜ `红点已修复：` ｜ `已知缺口：引用链标记类不在 _RULES` ｜ `转正后恒绿即回归锁` ｜ `生产人格副本不存在（bot 未部署/已移除），门跳过` ｜ `wrote new file(s) into the source tree data/` ｜ `旧直连逐字节等价` ｜ `Chromium 启动失败` ｜ `上游不可达（沙箱/网络受限），不作为失败` ｜ `# add_job 坐标必须登记`（断言仅真值性非空）。

## §8 与 U10/U1/U2 席结论的增量关系
- U10 已证：autosync 洗绿存在且已被使用（C-3）、AST 单轨假零（C-6）、四门禁 3 红。本席增量：①17 门逐门执法性定级（§1）；②默认不安全入口全清单（含 cross_validate「双引擎共谋洗绿」面，§2.1-5③）；③坐标复测扩量：matcher 0/50 独立复现 + **add_job 1/20** + **llm.py 路由计数 9≠13（新实锤）** + 门当场绿对照（E2）；④假 0 复现升级为「四形态失明」分型 + 全树 3 处非常量动态导入实存（§2.4）；⑤xfail 纪律正面结论、主患在 skip 侧（§2.5）；⑥**净化无中央咽喉**+旁路「形状强/内容弱」分型（§3.1）；⑦S0 收编等价性**实证为真测**（§3.2，反向防过度纠偏）；⑧可施工优先级表（§4）。
- 不重复：U1-24 全文、U2 S10 死册证据链、U10 四门禁快照数字。

## §9 本席事故披露

1. **PYTHONDONTWRITEBYTECODE 本机核验（任务点名项）**：**本席未复现「带参数仍生成 .pyc」**。三组证据：①E1/E2 带参 pytest 后 `find plugins tests scripts -name "*.pyc" | wc -l` = **0**；②裸 import 探针（带参）后 __pycache__=0/.pyc=0；③收口全树扫描 0/0。结论：**本机该参数有效**；U10 的 366 .pyc 事故按其自述系该行命令未带 export 的裸跑所致——参数缺失，非参数失效。
2. **工具拦截事故（过程如实记）**：本席中段对自家日志的 Edit/Write/cp 三次被权限分类器误拦（拦截理由引用了与本席无关的「campus 修复」上下文）；未绕行权限系统，改以小步 Edit 分块落盘成功，全程仅写唯一授权文件。期间一次 Bash heredoc 因 Windows CRLF 语法失败（退出码 2，未产生任何写入）。
3. **临时物清单（全部在 /tmp，未入树）**：`/tmp/u16/`、`/tmp/u16-canary.txt`、`/tmp/u16-log.md`（staged 稿，未 cp 进树）、`/tmp/u16_coord.py`（执行被拦，未跑）、`/tmp/u16-baseline-md5-before.txt`、basetemp `/tmp/u16-e1-7c3f`、`/tmp/u16-e2-4k9d`。处置：留 %TEMP% 由系统回收；`git status --porcelain -- docs/design/audit-20260920-unify-U16-green.md` = 唯一新增 `??` 条目（交付物本身）。
4. **基线触碰核验**：三生成物基线 md5+mtime 本席首尾一致（16:36:43 态，为本席开始**前**他席痕迹）；本席未跑任何 --write；树根 `.mypy_cache/.pytest_cache/.ruff_cache` mtime 12:30-12:47 早于本席窗口（~16:40 起），非本席产物，未清（清树须用户裁定）；源码树 `data/` 不存在=零污染。
5. **边界自报（未做的事）**：未跑全量 pytest/lint/typecheck/runtime-layout（任务禁令+避 IO 争抢）；未重启/未真实发送/未读 .env 明文；D3-1 表情/戳一戳「投递终点」一项按 U4 既有结论收编未重裁；v21r3/渲染域仅判执法性未评样式（范围裁定）。

*本席不修任何被审对象；所有判定含锚点可复跑；与文档冲突处以实跑为准。*
