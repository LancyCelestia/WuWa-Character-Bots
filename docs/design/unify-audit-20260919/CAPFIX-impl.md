# CAPFIX — 品牌胶囊契约锁（补真锁席）

Status: STARTED
Date: 2026-09-21
Seat: CAPFIX (tests-only; no implementation changes)

## 任务（简报）
评审席判「卡片品牌胶囊」= Critical：零契约覆盖。本席只补测试锁，不改实现。

- 新建 `tests/test_brand_capsule_contract.py`：把四态锁成有杀伤力断言（落在渲染产物，不落源码字符串）。
- 变异实证四例：①组件返回空 ②丢英文名 ③丢头像腿 ④写死「守岸人」字面量塞回实现。变异只在 %TEMP% 副本上做，绝不动工作树实现。
- 改写 `docs/design/unify-audit-20260919/CAP1-impl.md:66` 虚报句（按实相，不删历史）。
- 登记评审发现的非本席缺陷（I-1/I-3/I-4/I-7），标明归 FIX-CAP-B 席。

## 硬约束回执
- 可写：本文件、`tests/test_brand_capsule_contract.py`。
- 禁写：test_rendering_contract.py、test_mica_builders_contract.py、domains/render/** 实现、webui/**、echo.py、personas/**、ChatBot_Runtime/**、.env、verify_hashes.py、render_hashes.json（禁 --write）、doc_sync.py/command_catalog.py（禁 --write）。
- 禁 git 写操作。禁派子代理。
- 跑测试带零缓存三件套 + basetemp 落仓库外。

## 进度日志
（每完成一节立即 append）

## 1. 评审复核（不照抄，逐条亲验）
- `grep -rn -i capsule tests/`（工作树）→ 仅命中 test_rendering_contract 之外 **0 处**；`git grep -n -i capsule HEAD -- tests/` → 0 命中；`test_mica_builders_contract.py`/`test_rendering_contract.py` 中 `mica-capsule`/`Shorekeeper`/`BRAND_NAME_EN` 计数全 0。**评审 C-1 成立**。
- `CAP1-impl.md:66` 声称的 `mica-capsule`+`Shorekeeper` 锁：提交态/HEAD/工作树三处 grep 均 0。**C-2（台账虚报）成立**。
- 实现核实（工作树对 HEAD 干净，`git status --porcelain -- domains/render/` 空）：
  - `mica_shell.py`：`brand_capsule_css()`=318、`brand_capsule_html()`=345（约 :307/:334/:374 系简报旧坐标，已漂移，以真身为准）；`BRAND_CAPSULE_CSS`=385。
  - `card_render/bridge.py:195 _capsule_context()`；消费面 7 处：universal(:1439)/market(:1553)/finance(:1634)/song(:1696)/affinity(:1786)/error(:1858)/mermaid(:1997)。
  - `theme_tokens.py:42 BRAND_NAME_EN="Shorekeeper"`、`:397 BRAND_THEME.display_name="守岸人"`（frozen dataclass → 单源测试用「模块属性替换 + copy+object.__setattr__」而非 setattr）。
- 渲染产物实跑探针（`%TEMP%/capfix/probe{1,2,3}.py`，零缓存）：7 面 `dom=1 css=1 en_count=1 mc-name=1 mc-en=1`；
  universal 空载荷 feature 段省略 ✓；market/finance/song/affinity/error/mermaid 功能名默认=全球股指/金融/点歌/好感度/诊断/流程图；
  affinity 全页 `守岸人` 计数=3（胶囊+两处 `bot_name | default('守岸人')` 摆位文案）→ **中文名整页计数不可作锁，必须用 `mc-name` 计数**。
  patch `bridge/mica_shell.BRAND_THEME` 与 `mica_shell.BRAND_NAME_EN` 后 market 面产物随哨兵（`mc-dot` 字=哨兵首字）✓；
  **universal 面不随**（models.py:150 硬默认经 _DEFAULT_CONTEXT 恒注入）=评审 I-3 亲验成立 → 本席以 `xfail(strict)` 挂账，修复归 FIX-CAP-B。

## 2. 锁已成文 + GREEN 基线（2026-09-21）
- 新建 `tests/test_brand_capsule_contract.py`：**87 passed**（26 个测试函数，面级 7×参数化）。
  复跑命令（零缓存三件套 + basetemp 落仓库外）：
  `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_brand_capsule_contract.py -p no:cacheprovider --basetemp="$TEMP/capfixt" -q`
  → `87 passed in 2.59s`
- 断言全部落在**渲染产物**（`bridge.render_*_html` / `bridge._capsule_context` / `mica_shell.brand_capsule_html` 真函数返回值），
  零模板源码取材；组件 CSS 计数用整串 `BRAND_CAPSULE_CSS` 计数（模板本地摆位规则 `.footer-bot-pill .mica-capsule {` 会污染选择器计数，实测 universal=2 → 已避坑）。
- 中文名单一来源探针细节：affinity 卡整页 `守岸人`=3（胶囊+两处 `bot_name|default('守岸人')` 摆位文案）→ 中文名锁走 `mc-name` 计数与哨兵跟随，不走整页字串计数。
- **共享树盘中变动（如实记录）**：本席写锁期间 **CAPFIX-B 席**在工作树修掉评审 I-3
  （`models.py:150 bot_name: str = "守岸人"` → `""` 回落单一来源；`git status` 现见
  `M domains/render/card_render/models.py` + `M .../templates.py`，HEAD 仍是旧值）。
  实证：`_DEFAULT_CONTEXT['bot_name']` 由 `"守岸人"` 变 `''`，universal 卡产物随名字哨兵。
  本席原以 `xfail(strict=True)` 挂 I-3 账，据此**摘牌并入正向 7 面参数化锁**
  （`test_face_names_follow_single_source_tokens`）；若该修复被回退，此锁对 universal 变红如实报警。
  → 登记项 I-3 状态由「待 FIX-CAP-B」改记「CAPFIX-B 已在飞修（未 commit），锁由本文件守住」。

## 3. 杀伤力实证（变异四例，2026-09-21）
方法：`%TEMP%/capfix/mut_probe.py <tag>` —— 把 `mica_shell.py`（或 `bridge.py`）**复制到 %TEMP%/capfix/mut/ 后在副本上改**，
经 `importlib` 以真实模块名注入 `sys.modules`（`__file__` 仍指真身，模板目录可达），再 `pytest.main` 跑**真测试文件**并逐条收集 failed nodeid。
工作树实现文件全程只读（探针自带锚点命中数断言，未命中即报错）。复跑：
`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe "$TEMP/capfix/mut_probe.py" M1`

GREEN 基线：**87 passed**。变异结果（FAILED 数=本锁变红的用例数；评审席旧门同类破坏=全绿）：

| 变异 | 破坏内容 | 结果 | 抓住它的测试（函数×命中面数） |
|---|---|---|---|
| **M1** `brand_capsule_html` 返回空（胶囊整枚被删） | 67F/20P | `test_face_has_exactly_one_capsule`×7、`test_face_capsule_dom_equals_component_output`×7、`test_face_empty_payload_never_raise_keeps_capsule`×7、`test_face_avatar_leg_when_url_present`×7、`test_face_dot_leg_when_avatar_absent`×7、`test_face_names_follow_single_source_tokens`×7、`test_face_english_name_appears_exactly_once`×6、`test_capsule_context_empty_inputs_keep_all_legs`、`test_capsule_context_does_not_hardcode_brand_names`、组件级 9 条全红 |
| **M2** 丢英文名腿（`mc-en` 不再产出） | 29F/58P | `test_face_names_follow_single_source_tokens`×7、`test_face_english_name_appears_exactly_once`×7、`test_face_has_exactly_one_capsule`×7、`test_face_default_feature_label`×4、`test_face_capsule_dom_equals_component_output`×4、`test_component_english_name_defaults_to_brand_name_en`、`test_component_empty_inputs_never_raise_and_never_collapse`、`test_capsule_context_does_not_hardcode_brand_names`、`test_component_feature_segment_renders_after_names` |
| **M3** 丢头像腿（有头像也只出圆点） | 14F/73P | `test_face_avatar_leg_when_url_present`×7、`test_face_default_feature_label`×4、`test_face_capsule_dom_equals_component_output`×4、`test_component_with_avatar_emits_img_leg_and_no_dot`、`test_component_feature_segment_renders_after_names`、`test_component_escapes_all_dynamic_slots` |
| **M4a** 组件写死「守岸人」（名字不再读单一来源） | 6F/81P | `test_component_chinese_name_defaults_to_brand_theme_display_name`、`test_degraded_dot_glyph_shares_brand_name_source`、`test_face_capsule_dom_equals_component_output`×4 |
| **M4b** 桥层写死「守岸人」（8 处回落全砍） | 12F/75P | `test_face_names_follow_single_source_tokens`×7、`test_face_default_feature_label`×5、`test_capsule_context_does_not_hardcode_brand_names` |

对照评审席的反向实跑（旧门同类破坏 **全绿**）：本锁对四例破坏各自有 6–67 条红，其中「组件返回空」在旧门下**一条不响**、在本锁下 67 条响。

## 3b. 杀伤力终值（更正版，覆盖 §3 中途数；GREEN 基线=88 passed）
§3 表写于本席锁的早期版本（当时 `test_face_capsule_dom_equals_component_output` 与
`test_face_default_feature_label` 依赖「各面功能名缺省字符串」）。本席在飞期间
**FIX-CAP-B 席正在摘 bridge.py 六处功能名硬编码**（I-4 收编，`git status` 见
`M card_render/bridge.py`），那两处锁因他席施工转红 12 条——属**锁错对象**（把
施工中的实现细节当契约），本席据此把两锁改为版本无关不变式：

- `test_face_capsule_dom_equals_component_output`：改用**显式输入**逐项比字节
  （mermaid 无 payload 通道→去 `</div>` 前缀比，不依赖缺省功能名）；
- 新增 `test_face_feature_segment_omitted_or_wellformed`×7：空载荷出卡时功能名段
  要么不存在、要么必为「· 非空文本」（禁空段/裸点占位）+
  `test_universal_face_empty_payload_omits_feature_segment`（态④硬实例）。

终值（复跑=`%TEMP%/capfix/mut_probe.py <tag>`，副本改、真身只读）：

| 变异 | 破坏 | 变红 | 抓住它的锁 |
|---|---|---|---|
| M1 | `brand_capsule_html` 返回空（胶囊整枚删） | **62F/26P** | 面级 7 组锁全响（`exactly_one_capsule`/`dom_equals_component_output`/`empty_payload_never_raise`/`avatar_leg`/`dot_leg`/`names_follow_single_source`/`english_name_exactly_once`）+ 桥 2 条 + 组件级 9 条 |
| M2 | 丢英文名腿（`mc-en` 不产出） | **25F/63P** | `test_face_names_follow_single_source_tokens`×7、`test_face_english_name_appears_exactly_once`×7、`test_face_has_exactly_one_capsule`×7、`test_component_english_name_defaults_to_brand_name_en`、`test_component_empty_inputs_never_raise_and_never_collapse`、`test_component_feature_segment_renders_after_names`、`test_capsule_context_does_not_hardcode_brand_names` |
| M3 | 丢头像腿（有头像也只剩圆点） | **10F/78P** | `test_face_avatar_leg_when_url_present`×7、`test_component_with_avatar_emits_img_leg_and_no_dot`、`test_component_feature_segment_renders_after_names`、`test_component_escapes_all_dynamic_slots` |
| M4a | 组件内写死「守岸人」（不再读 `BRAND_THEME.display_name`） | **2F/86P** | `test_component_chinese_name_defaults_to_brand_theme_display_name`、`test_degraded_dot_glyph_shares_brand_name_source` |
| M4b | 桥层写死「守岸人」（8 处回落全砍） | **8F/80P** | `test_face_names_follow_single_source_tokens`×7、`test_capsule_context_does_not_hardcode_brand_names` |
| M5 | **评审 sabotage2 原样复刻**：英文名+头像腿+降级圆点三条腿全砍 | **44F/44P** | 上述面级/组件级组合全响 |

对照评审席实录：同类破坏在旧门下「好感度卡全绿 / 所有面全绿」→ 本锁分别 62/44 条红。
**评审 C-1 关闭**（锁已入库且经变异证明有牙）。

## 4. 台账虚报改写（C-2）
- `CAP1-impl.md:66`（`tests/test_mica_builders_contract.py`：media 卡产物「已含」`mica-capsule`+`Shorekeeper`）
  → 原文保留、下附【2026-09-21 CAPFIX 席按实相改写】引用块：本波未立任何锁（提交态/HEAD/工作树三处 grep=0 亲验），
  按铁律 5 当时记**未完成**；现行真相=锁由 `tests/test_brand_capsule_contract.py` 于 2026-09-21 补上（88 例 + 变异实证）。
- media 直拼卡一面（该文件主场）因 I-1 双重转义在飞，仍归 FIX-CAP-B 同锁 → 已写明。
- 新增 `CAP1-impl.md` §九：评审 I-1/I-3/I-4/I-7 四条**代登不修**，逐条标 `责任席=FIX-CAP-B` 与本锁现状（未锁/已锁/版本无关锁）。

## 5. 并发席位事件（共享树，如实记账）
- CAPFIX-B/FIX-CAP-B 席在本席运行中先后改动工作树 `models.py`（I-3：`bot_name` 默认 `"守岸人"`→`""`）
  与 `bridge.py`（I-4：摘功能名硬编码）、`templates.py`（疑 I-1）。本席**未改任何实现**，
  仅两次把锁从「依赖实现现状」重锚到「依赖承诺契约」；每次变动都有实跑证据（§2/§3b）。
- HEAD 侧实况：`models.py` 仍旧值 → 若他席改动被回退，本锁对 universal 变红如实报警（锁的设计意图）。

## 6. 终局跑与卫生自证
- 本锁：`88 passed`；复跑命令见 §2。
- 连旧契约面复跑（未碰坏存量门）：
  `tests/test_brand_capsule_contract.py + test_rendering_contract.py + test_mica_builders_contract.py + test_error_card_contract.py`
  → **292 passed**（旧三面单跑基线亦 200 passed，与本席零冲突）。
- ruff（缓存落 %TEMP%，不污染树）：`All checks passed!`；mypy 门禁范围=`plugins`（本席零实现改动，不含 tests）。
- 卫生：`git status --porcelain` 中本席产物仅 3 件 =
  `?? tests/test_brand_capsule_contract.py`、`?? docs/.../CAPFIX-impl.md`、`M docs/.../CAP1-impl.md`；
  零 `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`、源码树无 `data/`、`qx.json` 完好（362774B）。
  `tests/render_hashes.json`(M) 与 `tests/verify_hashes.py`(M) 的脏改动 mtime=09-18/09-20 05:01 早于本席首跑，
  属他席在飞——**本席从未运行任何 `--write`**（verify_hashes/doc_sync/command_catalog 三令皆禁）。
- 零 git 写操作、零子代理派遣。

Status: DONE（2026-09-21）
