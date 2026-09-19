# F5 卡片渲染/Token 统一性审计报告（unify-audit-20260919）

> 席位：F5（前端审计·卡片渲染与 token 单一来源）。审计日：**2026-09-19 16:07**（`date` 实跑：`Sat Sep 19 16:07:41 2026`）。
> 权限：只读审计。除本文件外**零修改**；禁 `--write`；禁 playwright 真渲染；全部行为判定=静态实读+离线定向 pytest。

## 0. 快照声明（在飞证据）

- git HEAD=`56d1461`（2026-09-15 文档批）。**整个 `plugins/bot_unified_runtime/domains/` 树为 `??`（未跟踪）**——v21r2 板块重组与 v21r3/v21r4 渲染波全部产出至今未 commit（提交裁决权在用户，与 AGENTS #35/#36/#41/#42 口径一致）。`output/` 下 7 张模板呈 `D`（未提交删除）、垫片呈 `M`、`output/card_render/mica_shell.py` 与 `tests/test_mica_shell.py` 为 `??`。
- 渲染域真身 mtime（ls 实取）：`domains/render/templates.py` **Sep 19 16:03**（审计开始前 4 分钟）、`render_backends.py` 01:36、`card_render/bridge.py` 01:40、`card_render/mica_shell.py` 01:10、`card_render/theme_tokens.py` 00:44、`card_render/usage_cards.py` 02:37、模板 7 张 02:17–02:37。**全部为前端波在飞中间态**，本文所有行号/字面量都是快照，收口波可能已移动它们。
- `tests/render_hashes.json` mtime Sep 19 15:39（前端波 28 分钟前刚重录）。`verify_hashes.py --check` 本次实跑 **exit=0（0 漂移）**。
- 观察到的树卫生现状（非本席产生、本席未动）：`domains/render/__pycache__/*.pyc`、`output/__pycache__` 存在（16:06，疑在飞进程/直跑解释器产物）；根目录存在 `?? %TEMP%/`、`.tmp-test/`、`.cp-test-output.txt` 等杂物与 `affinity-page.png` 等截图件。

## 1. 真身与双份判定

- **真身 = `plugins/bot_unified_runtime/domains/render/**`**（含 `card_render/` 子包与 7 张模板）。
- **旧路径 = 纯转发垫片**：`output/` 8 个 .py（含 `__init__.py` 中继面）+ `output/card_render/` 6 个 .py + `output/card_render/templates/` **空目录**（7 张 html git 呈 D 态）= **15 .py + 1 空目录**。逐文件实读证实零第二实现、零陈旧副本（`theme_tokens.py`/`bridge.py`/`models.py`/`usage_cards.py`/`mica_shell.py` 垫片均为 `from …domains.render…import` 转发）。与只读预研 `docs/design/v21r2-shim-retirement-inventory.md` §一、`docs/design/v21r3-render-shim-retirement.md`（SHIMRET 席 09-19）独立复核一致。
- **「改 A 生效、线上跑 B」型分裂：不存在**（无行为分叉；模板目录解析锚定真身 `Path(bridge.__file__).parent/templates`，`bridge.py:49`）。
- **真实分裂风险在「名单面」**：①`bridge` 垫片显式列名 ~130 个、`theme_tokens` 垫片 ~60 个——真身任何改名会在 import 期断链（先例：09-18 `usage_cards` 垫片因此断裂过，其垫片 docstring 自证）；②`usage_cards` 垫片**跨模块补转发**（从 `theme_tokens` 真身补 `BRAND_THEME/SHADOW_*` 等真身已不导入的符号）= 旧路径导出面与真身 import 面**已经分叉**，属「垫片比真身更宽」的隐藏面；③消费路径分裂：生产侧 22 文件 33 处仍走旧路径、`tests/` 34 个文件 import 旧路径（`grep -rln 'bot_unified_runtime\.output' tests/ | wc -l` = 34），而新门禁测试（`test_rendering_contract`/`test_v21r3_visual_gates` 等）走新路径——**同一个函数内混用两套路径**（echo.py:3283 新路径 `mica_shell` + :3287 旧路径 `bridge`；debug.py:727-740 同）。
- 「v21r2 留 275 垫片、当前挂起 4 张」：275 全树计数未复核（非渲染域）；渲染相关**实盘 15 .py+1 空目录**；「挂起 4 张」在 `v21r2-shim-retirement-inventory.md` 与 `.superpowers/sdd/2026-09-18-unify-wave/` 中**未找到对应落盘记录**，不采信也不否证。

## 2. 硬编码字面量计数表（「单一来源」P0 检验）

计数命令：`grep -oE '#[0-9a-fA-F]{3,8}\b' | wc -l` 等，对 11 面全量（非抽样）；快照 16:0x。

| 面 | hex 字面量 | 其中登记表值(#fff族/576272/18191c/607080) | 未登记散值 hex | rgba 总数 | 表外白 alpha | px 字面量 | var() |
|---|---|---|---|---|---|---|---|
| universal_card.html | **61** | 41 | **18 种 20 处**（#23ade5、#1d9bf0、amber 族 7、#e4e6eb×2、#8a8f98×2、#f1f2f3、#eef0f9、#f7f4fa、#fffbf0×2、#fff3e0×2、#fff7d6、#000） | 55 | **19** | 523 | 261 |
| affinity_card.html | 15 | 14 | 0 | 50 | 2 | 77 | 81 |
| error_card.html | 7 | 5 | 2（#f2b8b5、#e6e8ee） | 11 | 2 | 58 | 54 |
| finance_card.html | 7 | 7 | 0 | 19 | 0 | 53 | 40 |
| market_card.html | 6 | 6 | 0 | 19 | 0 | 48 | 40 |
| mermaid_card.html | 4 | 4（含 #607080 兜底） | 0 | 3 | 0 | 15 | 30 |
| song_candidates.html | 5 | 5 | 0 | 22 | 4 | 58 | 47 |
| echo `_help_mica_html` | 0 | — | 0（但 color-mix `#fff`×6） | ~10 | **8**（.48/.62×2/.78/.80×2/.82/.85/.90） | 65 | — |
| debug `_llm_setup_mica_html` | **1**（#b07d1a=SEMANTIC_WARNING 值直写） | — | 0（但同左散值 2 处） | 5 | **3**（.42/.78/.80） | 36 | — |
| usage_cards.py | **3**（#2e9e6b/#b07d1a/#d54941=语义三色直写） | — | 0（同上） | 8 | 0 | 67 | — |
| templates.py（media 卡） | **4**（#607080/#4a5866 兜底 + #ffffff×2） | 兜底三兄弟=UNKNOWN_PLATFORM_COLOR/_darken_hex/rgb 三元组的**第二份字面量**（:143-145） | 2 | 6 | 0 | 39 | — |
| bridge.py | 1（注释） | — | **0**（纯数据层，px=0） | 0 | 0 | **0** | — |
| mica_shell.py | 1（docstring） | — | 0 | 3（=GLASS 值本体） | 0 | 6 | — |
| theme_tokens.py（值册本体） | 32 | 本体 | — | 18 | — | 18 | — |

**模板层小计：hex 105 处（未登记散值 22 处/19 种）、rgba 179 处、px 832 处、var() 553 处。**

### 「双处同值」（token 在册、面上仍写死）四类实锤

1. **`--text-secondary: #576272` 在 7/7 模板 :root 逐处直写**（affinity:40、error:34、finance:36、market:38、mermaid:56、song:38、universal:60），值=theme_tokens.TEXT_SECONDARY。契约 §四宣称「单一来源」，实为**字面量+测试等值锁**，改 `TEXT_SECONDARY` 一处不会全卡同步。且与注入的 `--text-sub:#5b6069`（BRAND_THEME.text_sub）**同语义两个 token 两个值**并存——`--text-sub`（root_tokens 公共段第 2 键）vs `--text-secondary`（模板私设），后者不在值册注入面、前者在契约 §四却无消费锁。
2. **状态语义色直写**：usage_cards.py:255-257（`.status.ok/warn/bad` 硬写 #2e9e6b/#b07d1a/#d54941）、debug.py:795（`.setup-status.warn color:#b07d1a`+color-mix 一份）——同一函数上面 `extras={"--good":SEMANTIC_SUCCESS,"--bad":SEMANTIC_DANGER}` 已注入，warn 色却不消费 `--semantic-warning`。supply 门自证：`--semantic-warning` 列入「已定义未消费」WARN。
3. **内径刻度全表空转**：`--r-inner-*/--r-pill/--r-circle` 经 `render_root_tokens` 注入全部 11 面 :root，但 universal 仍写 `border-radius:12px/6px/4px/8px/16px/999px` 字面量约 34 处；supply 信息性 WARN 实跑原文列出 23 个定义未消费 token：`--accent-line --accent-panel --accent-panel-me --accent-rgb --bg-body --bg-card --card-padding --divider --font-scale --mica-scrim-media --page-gap --r-circle --r-inner-lg --r-inner-md --r-inner-sm --r-inner-xl --r-inner-xs --r-pill --section-gap --semantic-warning --shadow-card --shadow-elev-panel --shadow-soft`——**门只 warn 不拦**（test_token_supply_chain.py::test_informational_definitions_unconsumed）。
4. **垫片藏旧常量**：`output/card_render/theme_tokens.py` 显式转发 `_WASH_*` 私有派生参数 12 枚与 `DEFAULT_WASH_TOKENS` 等；`output/card_render/usage_cards.py` 补转发真身已不导出的 `BRAND_THEME/FONT_FAMILY_STACK/SHADOW_*`——历史可见面本身即第二处「名字表」，改真身命名需两处同步（无锁，靠 import 断裂暴露）。

### 裁决：「token 单一事实来源」成立度

**部分成立（约六成）**：公共 token 段（accent/wash/阴影/玻璃/遮罩/语义/内径/mono 共 30+8 键）确由 `mica_shell.render_root_tokens` 单源注入 11 面（步 2-5 已通水，实测 root_tokens 上下文 `bridge.py:1405/1519/1595/1652/1743/1806/1933` 七模板全接线）；装饰层 `decor_css/blobs_html` 双键真单源（见 §4）。但**壳层渐变、玻璃描边、页脚玻璃、次级灰、状态色、内径、宽度、字号**仍是「面上字面量 + 等值测试锁」：改值册不会全卡自动生效，须逐面手改后过门+重录哈希——「改一处全项目自动同步」对这些面**不成立**；且 gate08 使「禁表外 hex」的宣称只覆盖了 8 个历史散值（见 §5）。

## 3. 结构一致性：7 模板 + 4 直拼卡（宣称「6+4」已过时）

- Jinja 模板实盘 **7 张**（error_card.html 为 09-13 后新增；AGENTS.md 第三部分与 `docs/rendering-contract.md` 抬头「适用于 output/card_render/」均为**旧口径**）。f-string 直拼卡 **4 处**成立：echo `_help_mica_html`（domains/chat_reply/capabilities/echo.py:3261）、debug `_llm_setup_mica_html`（domains/ops/admin/debug.py:717）、`usage_report_mica_html`（card_render/usage_cards.py:71）、`render_media_card_html`（domains/render/templates.py:123）。全树 `<!doctype html>`/`<html>` 卡面构建者仅此 5 处（4 直拼 + mica_shell.render_shell），无第五处直拼卡、无 `render_template_string` 绕道（grep 实证）。
- DOM 骨架对照（快照）：

| 件 | 7 模板 | 4 直拼卡 | render_shell（规格件） |
|---|---|---|---|
| 截图根 | `.card` 或 `.shell.card` 混用：universal/market/finance/affinity/error/mermaid=`<div class="shell card">`-形态各文（mermaid=单层 .card）；song=`.card>.panel` | 各文：`.help-stage.card>.help-shell`、`.setup-stage.card>.setup-shell`、`.stage.card>.shell`、`.card>.panel`（media 单层无 stage 类） | `.card(+stage)>.{shell_class}` 双层 |
| 壳层渐变 | **各模板手抄**（145deg wash + 150deg 描边；universal 内含 4 份 145deg、43 处 150deg 计数含内联） | 统一走 `shell_base_css`（**生成器单源**） | `shell_base_css` 内同一渐变又手抄一份 rgba .95/.35/.72（未引用 GLASS_EDGE 常量，mica_shell.py:393） |
| 装饰层 | `{{ decor_css }}`+`{{ blobs_html }}`（6 模板双键；mermaid 只 decor 不 blobs=登记特例；universal 双伪元素+第 3 斑 DOM 混合=登记特例） | `mica_decor_css()`+`drift_blobs_html()` 直调，同源 | 同 |
| 玻璃 `.glass` | finance/market/mermaid/error/universal=类不存在或经 decor?——`.glass` 规则**只定义于 affinity/song** 两处且为手抄副本（affinity:90、song:91），usage/debug 走 decor 段生成器版；affinity 另有 7+ 处 **inline `style="background:var(--surface-a) padding-box, linear-gradient(150deg,…)"` 逐行重复描边字面量**（affinity:251-281） | — | `glass_rules_css()` 单源 |
| 页脚 | 4 套写法：universal `.footer.footer-colored`、templates.py `.card-footer-bot`、usage `.bot-foot`、echo `.help-bot-pill`；mermaid/song/affinity 各异文 | debug 卡**无署名页脚**（F11 契约未覆盖它，无断言） | 无 |
| 阴影档位 | 3 枚（含 `--mica-shadow-panel`，经注入键） | **2 枚**（`test_exactly_two_shadow_token_definitions` 强制 builders 阴影集=={--mica-shadow,--mica-shadow-soft}）——三级族与两级面**结构性不对称，且被测试钉死** | 同 builders |

- `docs/design/fstring-card-dom-spec.md` 判定：**「未实施」还剩整文档装配**——`mica_shell.render_shell()` 在 `plugins/**` 内消费数 **0**（grep 实证，仅 tests/test_mica_shell.py 与 docs 引用；`docs/design/v21r3-render-closing-spec.md:179` 明文「最终收敛为 render_shell(...) 整文档产出」未执行）。代价评估：4 卡 × 每卡约 15-25 行外壳（doctype/body/stage/`*{box-sizing}`/`.card` 容器五段各文，已实测 5 个容器变体、`body` 规则 3 种书写微差：media 有 `align-items:flex-start`、echo/debug 无 padding:0 一致但 `.setup-stage` 无 `width` 次序不同）。类名统一（`.card/.shell/.glass/.foot` 语义对齐）未做。

## 4. 注入面统一性（SWITCH 双键核实）

- 双键真单源：`_DECOR_CSS = mica_decor_css()`、`_BLOBS_HTML = drift_blobs_html()`（bridge.py:172-173）经 `_vis4_context()`（:177-190）注入——**7 个模板渲染入口全部命中**（market:1519、finance:1595、song:1652、affinity:1743、error:1806、universal:1405、mermaid:1922 `**_vis4_context()`）；4 直拼卡经同参缺省调用生成器，等价同源。
- **手抄副本仍存量**（字符串聚类实据）：①壳 wash 渐变 145deg 五段式：7 模板各 1 份 + universal 内第 2 份（`.video-card-shell`:1025）+ `mica_shell.shell_base_css` 1 份 ≈ **10 份**；②150deg 描边三层：**43 处**（模板 grep `'150deg'` 求和）+ usage/templates.py/echo foot 3 处 + shell_base_css 1 份；③`.glass` 手抄 2 份（affinity/song）；④universal/mermaid 伪元素 drift `animation`+`animation-delay` 手抄 4 行（时长与登记值 46/58s 一致但几何与登记表**不同**——universal ::before=62%/-16%/-24%，_BLOB_SPECS a=58%/-14%/-22%，属「登记名同源、参数私调」的半豁免形态，注释以「通水注」自辩，契约文档未收录该几何偏差）；⑤theme_tokens 内 GLASS_EDGE 与 mica_shell 壳层内联描边双处同值（书写风格一空格一紧凑）。
- 「24 段手抄副本消灭」判定：**装饰层维度成立**（DOM/CSS/相位/关停四处入册），**壳层维度未做**（见 §3/§5 P1-2）。

## 5. UI 铁律「契约条款 vs 机器断言」映射与差集

| # | 契约条款 | 断言位置 | 判定 |
|---|---|---|---|
| 1 | 无 meta viewport | 模板 contract:167 + builders mica_builders:186 | 有牙（两机制全覆盖）|
| 2 | body 透明 | contract:175 + builders:192 + C12 兜底截图 omit_background:786 | 有牙；漏洞=选择器 fullmatch 只认 `body`/`html body`，`body.xxx` 规则不查 |
| 3 | 字重≤700 | contract:190 + builders:212 | 有牙；只匹配数字，`font-weight:bold` 可绕（当前面内 0 处，grep 实证） |
| 4 | 动画在 .card 内 | 模板 contract:440（selector 正则白名单 `\.(card|shell|panel|drift-blob)`）+ DOM 解析:421 | 模板有牙；**4 直拼卡无作用域断言**（keyframes 白名单 e03 也只扫 6 模板）——直拼卡加 `animation:weird 1s` 无人拦 |
| 5 | 光晕 alpha≥0.05 | contract:455 + builders:296 | 有牙；可绕面=`rgb(0 0 0 / 4%)` 新语法、hex8 alpha、color-mix 尾参非 `transparent` 形态 |
| 6 | 阴影登记族 | contract:206（动态白名单）+ builders:229（两级钉死）| 有牙；**不对称**=模板 3 枚/直拼 2 枚被测试固化 |
| 7 | 失败→纯文本 | contract:539（None/{} 不抛）+ 14 调用点逐点核 | 成立（见 §6）|
| 8 | 色斑恒 3 枚/时长 {46,52,58} | gate02（11 面）| 半牙：正则要求 `animation:mica-drift-x Ns` 连写，拆 `animation-name`+`animation-duration` 即逃；DOM 枚数在 gate 层未计（仅 universal/video、affinity 等 contract blob_count≥1）|
| 9 | 行高刻度 | gate03（11 面）| 有牙 |
| §二 | --accent 不作底色/色斑≤35% | contract:348 正则锁 145deg+wash-blob ≤35 | 有牙（但 error 卡 24 为「小于上限」天然过，「豁免」实为无锁差值）|
| §四 | 内径 {4,6,8,12,16} | gate01 | **半牙：var(任意) 全放行**——私设 `--foo-radius:27px` 再 `var(--foo-radius)` 无门可抓（私名检查仅 --radius-lg/md/sm 三串）|
| §四 | 宽度∈CARD_SHELL_WIDTHS | gate06 + contract:272 | 有牙；盲区=`min-width`/`flex-basis`/`calc()`/`@media` 整块剥离（559px/720px 断点天然不入册）；直拼卡 `width_px=940` 等以**入参字面量**传入，改登记表值→gate 红→手改实参（非引用）|
| §四 | mono/sans 两栈逐字 | gate07（含 JS fontFamily 字面量）| 有牙 |
| §四 | 玻璃两档+描边三档 | gate09 | 半牙：只查**渐变附着层**的纯白标；平面填充 `rgba(255,255,255,.78)` 类 38 处不经管；染色层（含 footer-colored .98/.88）整层放行；affinity 二标描边（仅 .95/.35 两档无 .72）以「alpha ⊆ 集」过门 |
| §四 | 遮罩四员表外禁止 | **无断言** | 纸面（任意暗 rgba 散值不触任何门，仅光晕下限）|
| §四 | 语义五色一律 var() | **无 var 消费断言**；gate08 只拦 5 个旧散值 | 纸面+（usage/debug 直写现行值即为反例，见 §2-2）|
| §四 | 字号下限 12 | gate04/builders:323 | 有牙；「TYPE_SCALE 只准取表」**自认不适用存量**（契约原文「既有卡实弹验收字号不受追溯」）——纸面半豁免；且树内现存 help 卡 `font-size:12.5px/14.5px`（echo.py 快照 :3393/:3402 区段）与 C8「12.5→12/14.5→14 已收口」口径不符——或收口只覆盖模板面，或文档先行（在飞中间态，如实记录不定性）|
| §五.2 | 根元素带 .card | contract:421 + builders:203 | 有牙 |
| §六 | 脏数据不抛 | affinity 10 例:561-593 | 有牙（好感度卡专属；其它卡只测 None/{}）|

**「契约宣称任何违反必被拦」的证伪点（核心 P0）**：gate08 名为「禁表外 hex」实为 **8 值黑名单**，且其中 3 值（#b07d1a/#157347/#b42334）已登记进 theme_tokens → 被 `_theme_registered_hexes()` 动态白名单**自我中和**（`reason and normalized not in _REGISTRY_HEXES` 永假），有效黑名单仅剩 #d64545/#1a9e6c/#555/#444/#999 五值。universal 20 处、error 2 处未登记 hex 全部零锁通过；「豁免唯一途径=登记进 theme_tokens」（gate 自述）等价于**登记即豁免**——任何新散值先塞进值册即可永久免检。

## 6. 失败兜底契约

- 14 个 `render_card(` 调用点逐一读码：music:655、content_parser:449、market:249/740、stocks:448/490、fx:147、usage_cards:338、error_report:860、affinity:278、debug:844、echo:3471、bridge(mermaid):1966/1970——**全部** `None/空 bytes/异常 → 返回 None 或 ""`，由能力侧回退文本；未发现「渲染异常即静默丢消息」的能力。mermaid 额外有「失败块原样保留代码文本」路径（renderer.py:apply_mermaid_blocks docstring + 实读）。NullRenderBackend/空 payload 契约锁在 test_rendering_contract:596-605,539。
- **钉帧判定**（render_backends.py:233-278 实读）：`document.getAnimations()` 过滤 `.card` 子树后逐个 `pause()+currentTime=0`；fail-open 三层——page 无 `evaluate`（测试假页面）→静默跳过；`evaluate` 抛异常→`except: pass`；**单动画 pause 抛错→JS 内 catch 后继续**。返回值 `pinned` 计数被 Python 侧**丢弃**：即使 0 枚钉上，截图照常出（不稳定 PNG 静默出厂，无日志无告警）。生产面**无任何断言/观测点**验证「钉帧成功率」——19/19 STABLE 是样张脚本（%TEMP% 基线）的历史结论，非常驻门。
- `animations="disabled"` 排除论证复核：**仍成立**——色斑姿态由 `animation-delay:calc(--phase*-Ns)` 负延迟表达，`disabled` 语义取「动画应用前的基底状态」，与钉帧位不同，证据链（progress-CORE §SAMPLES）方向正确。
- 现值清单（快照）：`set_content` 页超时 8000ms（:422）、img 解码等 8000ms（:664）、`wait_js` 缺省 6000ms（:674-678）、缺省固定 `wait_ms=1500` 地板（:585）、mermaid 重试门 5.5s（bridge:1833）、`renderer._MERMAID_CALL_TIMEOUT_S=20`/`_MERMAID_TOTAL_BUDGET_S=22`、并发缺省 1/预算缺省关（config/env `BOT_RENDER_MAX_CONCURRENCY/_WAIT_BUDGET_MS`；AGENTS #31 称生产 .env=2/1500，.env 禁读未证）。

## 7. 哈希门与样张锁强度

- `verify_hashes.py` 跟踪 **19 件**：7 模板+theme_tokens+3 文档+DESIGN-SPEC+bridge/renderer/templates/echo/debug/usage_cards。当前真值：**`--check` exit=0，0 漂移**（16:08 与 16:2x 两跑；manifest 15:39 刚被在飞波重录）。
- **跟踪集缺口**：`mica_shell.py`（单源生成器本体！）、`render_backends.py`（钉帧/预算/路由拦截本体）、`plain_text/roleplay/models/reviewer`、全部垫片、全部**门测试文件自身**均不入门——改门断言零哈希成本（「门与产物同源同改」自指风险成立：同波会话改 theme_tokens+模板+`--write` 三步即可无痕换值，`--write` 无审批面）。test_verify_hashes_coverage.py 存在但未扩此二类（未细读，按文件清单判定）。
- 哈希口径=LF 归一内容哈希（防检出形态误报，09-14 审查 K 教训已吸收）——**可归因性弱**：清单无时间戳/owner/事由字段，旁车只有 `{path:sha}`；漂移时无法机械回答「谁的锅」，靠人读 wave 日志。
- **PNG 样张锁脆弱性**：基线目录 `%TEMP%/shorekeeper-samples/baseline-20260919-paused`——①不在库不在 Runtime，TEMP 清理即永久失锁（源码树零缓存纪律反使基线无处安放，制度性矛盾）；②字体/驱动/DPI/Chromium 版本任一变化即全表假红，manifest 未记浏览器 build 指纹→不可归因；③`test_render_card_samples.py` 用 FakeBackend，**常驻 pytest 并不真比 PNG**——字节判据只活在手工脚本跑动里。
- 九门实质举例（能抓什么）：gate01 抓 `border-radius:20px`（迁移映射 20→18 的历史实锤类）；gate06 抓新卡私宽 960px；supply S-A 抓 `var(--r-inner-xx)` 拼写错→定义并集缺失；e03 抓新 keyframes 私名；contract:206 抓 `box-shadow:0 0 6px #000` 一次性阴影。**并非自指空转**：断言对象=渲染产物文本+动态读值册，改 CSS 不改册即红；风险面集中于 §5 所列旁路与「登记即豁免」。

## 8. 豁免总册（P2-17 核销）——「豁免登记表」草案（未落盘，供 docs/rendering-contract.md 吸收）

实盘穷举（渲染域，grep「豁免/特例/例外/register 注记」+门源码逐条）：

| # | 豁免点 | 位置（快照） | 登记处 | 契约文档在册？ |
|---|---|---|---|---|
| X1 | error 卡 `wash_blob_mix=24` | bridge `_card_root_tokens` 通道 | 契约铁律 8+§四色斑 | 是 |
| X2 | mermaid 无 DOM 斑（伪元素双斑+decor keyframes） | mermaid_card.html:13-20；contract:418 `expect_dom_blobs=False` | 测试参数+模板注 | **否** |
| X3 | universal 非 video 布局「双伪元素+DOM 第 3 斑」混合体、几何私调 | universal:100-141 | 模板注+phase_det2 守卫 | **否** |
| X4 | universal amber 装饰族 7 hex+3 wash 底 | universal:50-58 | 契约 §四语义色行 | 是（一句）|
| X5 | universal `--blue #23ade5`+X 认证徽 `#1d9bf0` | universal:47,276 | 模板注「语义色豁免」 | **否** |
| X6 | `.footer-colored` 描边白 0.98/0.88 | universal:1141 | gate09 docstring GLASS3 裁定 | **否**（仅门注）|
| X7 | affinity 二标描边（.95/.35 无 .72）+7 处内联 style 描边副本 | affinity:115,251-281 | 无 | **否** |
| X8 | mermaid JS `fontFamily`/模板 `<script>` CDN URL（route 拦截本地化） | mermaid:28-37；render_backends:640-651 | 契约 §四字体行 | 半（字体在、CDN 形态不在）|
| X9 | 存量字号不受 TYPE_SCALE 追溯 | 契约 §四字号行 | 契约 | 是 |
| X10 | 直拼卡阴影两级（无 panel 档） | test_mica_builders:229 | 无文档 | **否** |
| X11 | 宽度门 `@media` 块整体剥离（559/720 断点不入册） | gates:309-313 | 协调裁定注 | **否** |
| X12 | media 卡沿用后端缺省视口（样张测试注记） | test_render_card_samples:67 | 测试注 | **否** |
| X13 | supply「定义未消费」23 token 只 warn 不拦 | test_token_supply_chain（实跑 WARN 原文） | 测试自述 | **否** |

**计数裁决**：豁免实盘 **13 项**（8 项未进契约文档）；断言面：七门文件 **435 passed**（16:1x 实跑，含参数化展开）。门**未被掏空**——值域/供给/字节确定性三门仍实质咬合；但 gate08 半无牙、gate02/01/09 各有旁路、X13 使 token 空转合法化。「豁免条数 vs 断言条数」= 13 : 435（项:用例），比例健康；问题在**豁免登记制度缺失**（X2-X7、X10-X13 均只在代码注释/门 docstring 里自辩），正是旧审计 P2-17 的复现。

## 9. 新发现台账（七要素；行号=2026-09-19 16:0x 快照，前端波在飞、坐标可能漂移）

| # | 严重度 | 坐标 | 锚点字符串 | 根因 | 建议改法 before→after（不落盘） | 验证命令 | 回归锁 |
|---|---|---|---|---|---|---|---|
| F5-1 | **P0** | tests/test_v21r3_visual_gates.py:363-372,566-572 | `#b07d1a": "旧状态琥珀散值"` | 「禁表外 hex」=8 值黑名单；其中 3 值已被自家登记表白名单中和；未登记新散值（universal 20 处/error 2 处）零拦截，契约「任何违反都会被契约测试拦下」不实 | 黑名单制→白名单制：面上 hex ∉ `theme_registered_hexes ∪ 豁免册` 即红（豁免册先建，见 §8） | `pytest tests/test_v21r3_visual_gates.py -q …` | 无（需新建）|
| F5-2 | **P1** | 7 模板 `.card/.shell` 渐变段（affinity:63-71、mermaid:77-84、error:44-52、universal:86-95,1020-1030 等）+ mica_shell.py:389-394 | `color-mix(in srgb, var(--wash-1) 55%, var(--wash-mist)) 30%` | 壳层渐变 10 份手抄（decor/blobs 通水了，shell 没通水）；改壳=改 10 处+重录哈希 | `shell_base_css` 已能产同文 CSS → 模板 :root 外新增上下文键 `shell_css`（`_vis4_context` 注入）或 `{{ shell_base_css("shell", width_px=…, glass=False) }}` 等价件；shell_base_css 内描边串改 f"{GLASS_EDGE}" 引用 | 同上+gate09/contract 全绿 | 部分（gate 锁值不锁份数）|
| F5-3 | **P1** | test_token_supply_chain.py 信息性 WARN（23 token）＋universal 内径字面量约 34 处、usage_cards.py:255-257、debug.py:795 | `--semantic-warning`, `--r-inner-lg` | 定义已注入、消费未迁移；WARN 不拦=漂移温床；状态色直写与 extras 注入并存（同文件自我矛盾） | `.status.ok` 等 `color:#2e9e6b`→`var(--semantic-success)`；`border-radius:12px`→`var(--r-inner-lg)`；把该 WARN 升为硬门（先清 23 项再锁）| `pytest tests/test_token_supply_chain.py -q …` | 有（升硬门前无）|
| F5-4 | **P1** | mica_shell.py:401-447（render_shell 零生产消费）；echo.py/debug.py/usage_cards/templates.py 各手拼文档层 | `def render_shell(` | 规格件（整文档装配、铁律内建）建好未接入；`docs/design/fstring-card-dom-spec.md` 状态仍「未实施」；4 卡容器/body/*{box-sizing} 5 变体各文 | 四卡 return 段改调 `render_shell(title=…, tokens=root_tokens, css=…, stage_class="help-stage", shell_class="help-shell", shell_width_px=CARD_SHELL_WIDTHS["help"])`；宽度入参由字面量 940→查表 | 域回归 mica_builders+gates | 有（builders 契约）|
| F5-5 | **P1** | tests/verify_hashes.py:34-60 + scripts/render_card_samples.py:42（%TEMP% 基线） | `"plugins/…/bridge.py",`（清单缺 mica_shell/render_backends） | 单源生成器与钉帧本体不入门禁哈希；PNG 基线随 TEMP 清理永久失锁、环境漂移即假红、无 owner/事由/环境指纹字段 | TRACKED_FILES += `domains/render/card_render/mica_shell.py`、`domains/render/render_backends.py`；样张基线迁 `ChatBot_Archive` 或 Runtime 受保护目录+manifest 增记 chromium build/字体清单摘要 | `python tests/verify_hashes.py --check` | 有（test_cross_validation_gates 常驻）|
| F5-6 | **P2** | render_backends.py:254-278 | `return pinned;`（Python 侧丢弃） | 钉帧成功率不可观测：0 钉上也静默出图；字节不稳定只在人工样张跑里暴露 | `_pin_card_animations` 读返回值，`pinned==0 且页面含 mica-drift` 时 `warnings/logger` 记一次；样张脚本加断言 | 域测试 test_render_backends/test_render_launch_backoff | 无 |
| F5-7 | **P2** | output/card_render/bridge.py:4-128、usage_cards.py:9-15 | `_ERROR_CARD_TEMPLATE,` 等 ~130 具名 | 名单转发=改名即断（先例 09-18）；usage_cards 垫片补转发使旧路径导出面>真身 import 面，退役判定复杂化 | 退役执行（方案已在 v21r3-render-shim-retirement §五 B 档 33 处机械改道），或垫片统一改 `*` 转发+mica_shell 式说明；消费面（生产 33 处+tests 34 件）迁新路径 | runtime-layout 门+全量 | 部分（test_v21 族守旧路径存在性，反成退役阻力）|
| F5-8 | **P2** | AGENTS.md 第三部分「6 Jinja 模板」、docs/rendering-contract.md:3「适用于 output/card_render/」 | `6 Jinja 模板` | 模板 7 张/真身搬家后口径未同步（§8 X 项同缺）——权威文档三处过时 | 「6 Jinja」→「7 Jinja（error_card 09-13 增）」；契约抬头改 `domains/render/card_render/`+注明垫片 | 人工 diff | 无（verify_hashes 锁该文档字节——改需 --write 仪式）|
| F5-9 | **P2** | echo.py 快照 :3393（`.help-subtitle … font-size:12.5px`）/:3402（`h2 … font-size:14.5px`） | `font-size:12.5px` | AGENTS #41 C8 记「12.5px→12、14.5px→14 已收口」，直拼卡面现值仍 12.5/14.5；门只设 ≥12 下限故不红——文档宣称强于锁与实态 | 改 12/14（像素微差走样张复核）或 C8 口径改注「仅模板面收口」 | 域回归 echo+gates；样张双渲 | 无（scale 门不存在）|
| F5-10 | **P3** | 本审计 §1 观察 | `domains/render/__pycache__`、`?? %TEMP%/`、`.cp-test-output.txt` | 在飞波直跑解释器残留+杂物件；铁律 6 树卫生 | 收口波统一清（备份 %TEMP% 规程），非他席禁触 | `dev.ps1 -Task runtime-layout` | 有（runtime-layout 门）|
| F5-11 | **P3** | affinity_card.html:115,251-281 | `rgba(255, 255, 255, 0.35)) border-box` 二标变体 | 描边两标变体+内联 style 副本 7 处未入豁免册（X7），gate09 按 alpha 集放行=语义漂移但字节合规 | 入册 X7 或改 `var(--mica-glass-edge)` 消费+zebra 只覆 padding 层 | gate09 | 有（但按现口径为「合规」）|

## 10. 复跑命令（本审计实跑记录）

```bash
# 哈希门（只读）
PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe tests/verify_hashes.py --check   # exit=0
# 七门文件（离线，435 passed 全绿，4.55s）
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_rendering_contract.py tests/test_mica_builders_contract.py tests/test_v21r3_visual_gates.py \
  tests/test_token_supply_chain.py tests/test_e03_typography.py tests/test_template_visual_audit.py \
  tests/test_mica_shell.py -p no:cacheprovider --basetemp="$TEMP/f5-rendergates-20260919" -q
# 计数类命令见 §2 表头原文（grep -oE … | wc -l），对 11 面全量非抽样
```

树卫生自查：本席全程 `PYTHONDONTWRITEBYTECODE=1` + `-p no:cacheprovider` + `$TEMP` basetemp，未新建任何 `__pycache__/pytest_cache`（§0 所列残留为在飞他席产物，快照时间早于本席首跑）。
