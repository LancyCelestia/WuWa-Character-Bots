# v21r3 渲染统一收口规格（render-closing-spec）

> **身份**：本文件是 2026-09-18 渲染统一收尾大波次（wave-2）的**唯一施工规格**。
> 上游输入：`docs/design/v21r3-render-unification-plan.md`（六步方案，已完成：mica_shell 生成器
> + `:root` token 11/11 面单源）与 2026-09-18 三席渲染一致性审计（漂移 8 类 + 机器门缝隙）。
> 裁决基线 C1-C13 由用户裁定，已同源同步至 CORE/GATES/SPECS 三席简报；本文负责把它落成
> wave-2 四席可逐条执行的工单。细节口径以本文为准；主波次占位见
> `.superpowers/sdd/2026-09-18-unify-wave/master-plan.md`。
>
> **路径口径**：v21r2 板块重组后卡渲染真身在
> `plugins/bot_unified_runtime/domains/render/card_render/`（`output/card_render/` 为兼容垫片，
> 一一对应）。本文一律写真身路径；`domains/chat_reply/capabilities/echo.py`、
> `domains/ops/admin/debug.py`、`domains/render/templates.py`、`domains/render/render_backends.py`
> 同理（各自根目录同名路径为垫片）。
>
> **行号口径**：file:line 为 2026-09-18 取证时点（CORE 席并行改值册后可能漂移）；
> 施工时以「锚点」列的 selector/字面量检索为准，行号仅作定位起点。

---

## 〇、背景与证据

### 0.1 现状一句话

7 张 Jinja 模板 + 4 张 f-string 直拼卡（echo 帮助 / debug 检查 / usage 账单 / media 媒体）共
**11 面**，六步方案后 `:root` token 已由 `mica_shell.render_root_tokens` 单源；但**壳层 CSS、
漂移色斑、玻璃面板仍有 12 份手抄副本**，且机器门枚举存在系统性缺口——值漂移与门缝隙互相
掩护，漂移无法被门禁现形。

### 0.2 漂移 8 类（file:line 证据）

| # | 漂移类 | 证据（file:line @2026-09-18，锚点加粗） | 归属裁决 |
|---|--------|----------------------------------------|----------|
| A | **圆角漂移** | universal_card.html:63-65 私设 `--radius-lg:24px/--radius-md:16px/--radius-sm:8px`（引用点 :404/:532/:589）；:94 `border-radius: 28px`（外壳级）；:181 `7px`；:574/:614 `3px`；:920 `50px`（胶囊形）；:1138 quality-pill `11px`；echo.py:3420 `border-radius:11px` | C1 |
| B | **玻璃档位漂移** | song_candidates.html:133 玻璃起点 **0.68**；universal_card.html:1159 footer-colored `.68→.52`（描边 .98/.60/.88）；:188 面板 `.60→.30`；:437/:586/:721/:1710 平面 `0.55`；:473 `0.60`；:861 页脚 `0.50`；echo.py:3417/:3420 行面 `.62`；affinity_card.html:180-181 `.62`/描边 `.98/.55` | C3 |
| C | **语义色并存** | 红三：`#d54941`（market_card.html:23、finance_card.html:21 `--up`）≠ `#d64545`（usage_cards.py:273、debug.py:759 `--bad`）≠ `#b42334`（affinity_card.html:38 `--score-cold`）；绿三：`#2e9e6b`（market:24/finance:22 `--down`）≠ `#1a9e6c`（usage:271、debug:759 `--good`）≠ `#157347`（affinity:37 `--score-hot`）；黄两：`#b07d1a`（usage:272、debug:805）与 universal amber 装饰族（:54-59 `#ff9800/#e65100/#f5b83b/#f0b429/#b77900`）并存 | C4 |
| D | **行高漂移** | `1.55`：echo.py:3400/:3420、debug.py:806；`1.65`：templates.py:154、error_card.html:110——四处全部位于 E03 门枚举之外（见 0.3-G2） | C7 |
| E | **字号漂移** | `<12px`：echo.py:3398 `11px`、:3424 `11.5px`；`12.5px`×5：echo.py:3400、usage_cards.py:285、song_candidates.html:254、market_card.html:112、finance_card.html:109；脱阶值：echo.py:3417 `14.5px`、universal_card.html:1108/:1114/:1115/:1118 `13.5px`×4、:1161 `14.5px`；配套：echo.py:3398 `letter-spacing:.14em`（刻度仅 {0.02,0.06}）、:3420 `gap:9px`（刻度无 9） | C8 |
| F | **mono 字体四处各写** | error_card.html:28 `--mono-family` 全栈 / usage_cards.py:53、:287 `Consolas,monospace` / debug.py:813 `Consolas,monospace`——四处互不一致；sans 栈字面量脱钩 FONT_FAMILY_STACK：mermaid_card.html:24（JS `fontFamily` 缺后四段）、universal_card.html:915 `.source-badge`（缺后四段） | C9 |
| G | **色斑漂移** | finance_card.html:54-69、market_card.html:~54-71、error_card.html:48-63 只有 drift-a/b **两枚**（无 52s 的 drift-c）；echo 帮助卡**零色斑**；universal_card.html 双份手抄（:126-135 主层 + :1040-1065 视频区块内层）——合计 **12 份手抄副本**（11 面 + universal 内层 1 份） | C2/C13 |
| H | **宽度漂移** | echo.py:3364 `width:940px`、usage_cards.py:236 `width:900px`、debug.py:769 `width:880px`、templates.py:67 `width: 640px`——四值均不在 `CARD_SHELL_WIDTHS`（theme_tokens.py:85-93） | C10 |

### 0.3 机器门缝隙 9 项

| # | 缝隙 | 证据 | 归属 |
|---|------|------|------|
| G1 | vis5 三门（zebra 可辨/文字可读/次级灰单源）与字号下限门只枚举 7 张 Jinja 模板，**4 张直拼卡全被排除** | test_template_visual_audit.py:124-132 `_EDITABLE_TEMPLATES` | GATES-E2 |
| G2 | E03 行高/字距/动画门枚举缺 error_card.html（`1.65` 在枚举外通行） | test_e03_typography.py:25-32（仅 6 张） | GATES-E1/C7 |
| G3 | 相位确定性门缺 **error/usage/echo/debug 四入口** | test_phase_determinism.py:112-123 `_RENDERERS` 仅 7 面 | GATES-E1 |
| G4 | 半径字面量**无门**（28/24/16/11/7/3/50px 任通行） | 全仓无 radius 断言 | GATES-门4 |
| G5 | 宽度登记表不盖直拼卡 940/900/880/640 | theme_tokens.py:85-93 缺 4 键 | C10/GATES-E3 |
| G6 | 色斑**数量与时长无门**（2 枚/0 枚卡通行） | 全仓无 blob count/duration 断言 | GATES-门2 |
| G7 | 兜底截图不带 `omit_background` | render_backends.py:649 `full_page` 兜底 vs :646 元素截图（带） | C12 |
| G8 | `bridge.__all__` 缺 `render_error_card_html` | bridge.py:1712 定义 vs :1921-1945 导出面 | C11 |
| G9 | reduced-motion 特异性缺陷：finance_card.html:83 / market_card.html:85 手写 `.card .drift-blob { animation:none }` 与动画声明 `.drift-blob.drift-a`（(0,2,0) 同特异性）竞争，实测关停不可靠（test_phase_determinism.py:242-243 已登记「另行登记」） | 同左 | C13 |

---

## 一、裁决基线 C1-C13（逐字）与实施口径

> 每条先**逐字**引用裁决原文（与 CORE/GATES 席同源），再给值册登记、迁移映射与理由。
> 标注「规格细化」的行是为可执行性由本规格推导的补全，与裁决原文不冲突；如与后续用户
> 裁断冲突，以用户为准并回改本文。

### C1 圆角
> **【裁决原文】** 外壳圆角只允许 var(--r-shell)=30px；废除 universal 私设 --radius-lg/md/sm=24/16/8；内径合法集 {4,6,8,12,16}；pill=999px、圆=50% 登记特例；迁移映射：28→30、20/24→18、11→12。

- **值册登记**（CORE 席）：`RADIUS_SHELL_PX=30`（既有 `--r-shell`）、`RADIUS_PANEL_PX=18`（既有 `--r-panel`）、`RADIUS_TILE_PX=14`（既有 `--r-tile`）、新增 `RADIUS_PILL_PX=999` 与 `RADIUS_INNER_PX=frozenset({4,6,8,12,16})`。
- **迁移映射**（规格细化：对 0.2-A 全部证据行）：
  | 现值 | 目标 | 证据锚点 |
  |------|------|----------|
  | `28px`（壳级） | `var(--r-shell)` | universal:94 |
  | `--radius-lg:24px` 及其引用 | `var(--r-panel)`（24→18） | universal:63/:532/:589 |
  | `--radius-md:16px` / `--radius-sm:8px` 及其引用 | 废除变量，引用点改**合法内径字面量** `16px`/`8px`（零视觉变化） | universal:64-65/:404 |
  | `11px` | `12px` | universal:1138、echo.py:3420 |
  | `7px` | `6px`（就近收敛，规格细化） | universal:181 |
  | `3px` | `4px`（内径下限，规格细化） | universal:574/:614 |
  | `50px`（胶囊形） | `999px`（pill 特例） | universal:920 |
  | `20px`（如检索再现） | `18px`（=var(--r-panel)） | 裁决映射原文 |
- **理由**：外壳 30px 是全卡统一的第一识别符；平行刻度三兄弟是六步方案前历史残留，与 `--r-*` 家族语义重复。合法集之外的奇数值（3/7/11）无设计意图记录，按就近收敛后由门禁锁死。
- **门**：见 §三-门4。

### C2 色斑
> **【裁决原文】** 全部 11 面恒 3 枚、时长集合恰 {46,52,58}s（a/b/c）；error 卡 wash_blob_mix=24 既有豁免保持。

- **值册登记**（CORE 席）：`BLOB_COUNT=3`、`BLOB_DURATIONS_S={"a":46,"b":58,"c":52}`（与 mica_shell.py `_MICA_DECOR_CSS` 逐字一致）、`WASH_BLOB_MIX_DEFAULT=35`、`WASH_BLOB_MIX_ERROR=24`（豁免项显式登记）。
- **实施**：finance/market/error 三卡补第三枚 drift-c（52s，DOM 加 `<span class="drift-blob drift-c">`，CSS 随通水由生成器产出）；echo 零色斑经通水补齐；universal 双份收敛为单层（见 §二-2.1 任务 5）。
- **理由**：三枚交错是「釉瑚云母」质感的核心语言；两枚/零枚卡在视觉节奏上明显掉队。时长集合门禁杜绝逐卡私自调参。

### C3 玻璃两档
> **【裁决原文】** 玻璃两档：GLASS_MAIN rgba(255,255,255,0.66)→rgba(255,255,255,0.44)；GLASS_FOOT 0.66→0.46；边缘描边 0.95/0.35/0.72；归一映射：0.68→0.66、0.55/0.60→0.66、0.68→0.50(脚)→0.66→0.46。

- **值册登记**（CORE 席）：`GLASS_MAIN="linear-gradient(150deg, rgba(255,255,255,.66) 0%, rgba(255,255,255,.44) 100%)"`、`GLASS_FOOT="linear-gradient(150deg, rgba(255,255,255,.66) 0%, rgba(255,255,255,.46) 100%)"`、`GLASS_STROKE="linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%)"`（=mica_shell `.glass`/`shell_base_css` 现值单源化）。
- **归一映射**（规格细化：对 0.2-B 全部证据行）：
  | 现值 | 档位 | 目标 | 证据锚点 |
  |------|------|------|----------|
  | `0.68→0.44` | 主档 | `0.66→0.44`（GLASS_MAIN） | song:133 |
  | `.60→.30` | 主档 | `0.66→0.44`（GLASS_MAIN） | universal:188 |
  | 平面 `0.55` | 主档起点 | `0.66` | universal:437/:586/:721/:1710 |
  | 平面 `0.60` | 主档起点 | `0.66` | universal:473 |
  | 行面 `.62` | 主档起点 | `0.66` | echo.py:3417/:3420、affinity:180 |
  | 平面 `0.50`（页脚带） | 脚档 | `0.46` | universal:861 |
  | footer `.68→.52` | 脚档 | `0.66→0.46`（GLASS_FOOT） | universal:1159 |
  | `0.66→0.46` | 脚档 | 已合规，改消费 token | affinity:234、mermaid:141 |
  | `0.66→0.44` | 主档 | 已合规，改消费 token | error:94、affinity:132、market:99、finance:99 |
  - **着色玻璃面**（footer-colored/affinity 面板等带 accent/wash color-mix 着色者）：**白玻璃 alpha 按上表归档，着色 color-mix 层保留**——即 alpha 归一、色调不丢（规格细化）。
- **理由**：两档制让「面板」与「脚带」层次一眼可辨；0.68/0.55/0.50 等无意图散值是逐卡手抄的噪声。

### C4 语义色
> **【裁决原文】** DANGER=#d54941/SUCCESS=#2e9e6b/WARNING=#b07d1a/SCORE_HOT=#157347/SCORE_COLD=#b42334 单源；finance/market --up/--down、usage/debug good/bad 改消费语义 token。

- **值册登记**（CORE 席）：`SEMANTIC={"danger":"#d54941","success":"#2e9e6b","warning":"#b07d1a","score_hot":"#157347","score_cold":"#b42334"}`（+对应 CSS var 注入 `--danger/--success/--warning/--score-hot/--score-cold`）。
- **实施**：market:23-24 / finance:21-22 `--up:var(--danger)`、`--down:var(--success)`（A股红涨绿跌语义不变，只换值的来源）；usage:271-273 ok/warn/bad 与 debug:759/:805 good/warn/bad 改 `var(--success)/var(--warning)/var(--danger)`；affinity:37-38 `--score-hot/--score-cold` 改消费 token（值本已合规）。error 卡 `ERROR_ACCENT=#d54941` 与 DANGER 同值，维持 `ERROR_THEME` 注入链路不动（登记注释互相引用即可）。
- **理由**：三红三绿并存导致「跌」在不同卡上颜色不同（#1a9e6c vs #2e9e6b vs #157347）；语义色单源后改一处全卡生效。
- **边界**：universal amber 装饰族（:49-59，哔哩哔哩置顶/装扮徽章琥珀）**不属语义色**，本批不改值、不并入 SEMANTIC（登记为装饰 token 即可，规格细化裁定）。

### C5 深色遮罩 OVERLAY 四员
> **【裁决原文】** OVERLAY 四员登记：scrim_badge rgba(10,12,16,0.72)/scrim_banner rgba(15,18,24,0.10)/scrim_code rgba(28,30,38,0.94)/scrim_media rgba(38,46,56,0.75)。

- **值册登记**（CORE 席）：`OVERLAY_SCRIMS={"scrim_badge":"rgba(10, 12, 16, 0.72)","scrim_banner":"rgba(15, 18, 24, 0.10)","scrim_code":"rgba(28, 30, 38, 0.94)","scrim_media":"rgba(38, 46, 56, 0.75)"}`。
- **实施**（值已合规，改消费）：universal:176（置顶横幅=bnarner? 否——:147 为 banner 0.10、:176 为 badge 0.72）、:1138 quality-pill（0.72）、error:109 代码块（0.94）、templates.py:143 media 徽章（0.75）。
- **理由**：深色遮罩是「白玻璃体系」的反相 token，散值会让暗部层次失控。

### C6 legacy 灰
> **【裁决原文】** legacy 灰 #555/#444/#999 全部改消费 var(--text-main)/var(--text-secondary)，黑名单门加这三值。

- **实施**：universal:745 `#555`（转发头 15px 粗体文字）→`var(--text-main)`；:750 `#444`（转发正文）→`var(--text-main)`；:1583/:1600 `#999`（UID/时间戳元数据）→`var(--text-secondary)`（规格细化：按内容角色分派，元数据一律 secondary）。
- **门**：`_LEGACY_SECONDARY_GRAYS` 黑名单（test_template_visual_audit.py:134）追加 `("#555","#444","#999")`。

### C7 行高
> **【裁决原文】** 1.55→1.5、1.65→1.6。

- **实施**：echo.py:3400/:3420、debug.py:806 `1.55`→`1.5`；templates.py:154、error_card.html:110 `1.65`→`1.6`。E03 刻度 `{1.0,1.1,1.15,1.2,1.4,1.5,1.6}`（test_e03_typography.py:99）**不变**——四处全是脱刻度值，收敛即合规。
- **门**：E03 枚举扩展覆盖后（§三-E1）这四处不可能再脱刻度。

### C8 字号
> **【裁决原文】** 字号≥12px：echo 11/11.5→12、12.5×4→12、universal 13.5/14.5→14；echo letter-spacing .14em→.06em、gap 9px→8px。

- **实施**（审计实测 12.5px 共 **5 处**，比裁决计数多 1 处 echo.py:3400，全部收敛，规格细化注记）：
  | 锚点 | 现值 | 目标 |
  |------|------|------|
  | echo.py:3398 | `11px` + `letter-spacing:.14em` | `12px` + `.06em` |
  | echo.py:3424 | `11.5px` | `12px` |
  | echo.py:3400 / usage_cards.py:285 / song:254 / market:112 / finance:109 | `12.5px` | `12px` |
  | echo.py:3417 | `14.5px` | `14px` |
  | universal:1108/:1114/:1115/:1118 | `13.5px`×4 | `14px` |
  | universal:1161 | `14.5px` | `14px` |
  | echo.py:3420 | `gap:9px` | `gap:8px`（GAP_SCALE_PX 合法值） |
- **规格细化**：`14px` 建议由 CORE 席增补进 `TYPE_SCALE_PX`（如 `"body_sm": 14`），使收敛值入册可引；`TYPE_SCALE_PX` 维持「新增/改版模板选用阶梯」定位，本批**不**强制存量字号全量接线（追溯成本高、收益低），零消费者问题以定位钉死 + 增补成员方式收口。
- **理由**：11/11.5px 在 QQ 客户端缩略图分辨率下不可读；12.5px 属刻度外自创值。

### C9 mono 字体
> **【裁决原文】** MONO_FONT_STACK='"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace' 单源；mermaid:24/universal:915 字体栈字面量改 FONT_FAMILY_STACK 逐字一致。

- **值册登记**（CORE 席）：`MONO_FONT_STACK='"Cascadia Mono", Consolas, "JetBrains Mono", "Courier New", monospace'`（与 error_card.html:28 现值逐字一致，该卡即单源锚点）。
- **实施**：error:28 `--mono-family` 改由 bridge 注入 `MONO_FONT_STACK`；usage_cards.py:53/:287、debug.py:813 `Consolas,monospace` → `var(--mono-family)`；mermaid_card.html:24（JS `mermaid.initialize({fontFamily})`）与 universal:915 `.source-badge` 的 sans 栈字面量改逐字引用 `FONT_FAMILY_STACK`（前者由 bridge 注入模板变量——JS 上下文不吃 CSS var，规格细化）。
- **理由**：四处 mono 各写导致代码/模型名/键名的等宽字形逐卡不同；sans 栈缺段导致回退链静默变短。

### C10 宽度登记
> **【裁决原文】** 宽度登记 += help:940/usage:900/debug:880/media:640。

- **值册登记**（CORE 席）：`CARD_SHELL_WIDTHS` 增 `"help":940, "usage":900, "debug":880, "media":640`（四值=现状值，宽度零视觉变化，只补登记）。
- **实施**：直拼卡壳改 `shell_base_css(shell_class, width_px=CARD_SHELL_WIDTHS["help"|...])`，手写 width 字面量删除（echo:3364/usage:236/debug:769/templates.py:67）。

### C11 bridge 导出面
> **【裁决原文】** bridge.__all__ += render_error_card_html。

- **实施**：bridge.py `__all__`（:1921-1945）追加 `"render_error_card_html"`（:1712 已定义）。error 卡从此与其它 render_* 同为公开契约面（GATES 加导出面断言）。

### C12 兜底截图
> **【裁决原文】** render_backends 兜底 full_page 截图补 omit_background=True。

- **实施**：render_backends.py:649 `page.screenshot(type="png", full_page=True)` → 追加 `omit_background=True`，与 :646 元素截图分支对齐。理由：`.card` 选择器失配走兜底时，透明 body 会被渲染成白底方块，圆角卡变白角——兜底路径恰恰是最需要透明底的路径。

### C13 外壳通水
> **【裁决原文】** 外壳通水：11 面的壳层 CSS/色斑/玻璃全部改消费 mica_shell 生成器（shell_base_css/_MICA_DECOR_CSS/DRIFT_BLOBS_HTML/render_root_tokens），消灭 12 份手抄副本；reduced-motion 规则由生成器统一产出正确特异性。

- **实施**：
  - **4 张直拼卡**（echo/debug/usage/media）：`render_root_tokens` 已接入（echo:3350/debug:754/usage:214/media templates.py:209），本批补完剩余三件——`shell_base_css`（替换 :3364/:769/:236/:67 手写壳）、`_MICA_DECOR_CSS + DRIFT_BLOBS_HTML`（替换 debug:778-805/usage:241-283/media:79-100 手抄层；echo 补齐缺失的色斑层）、最终收敛为 `render_shell(...)` 整文档产出。
  - **7 张 Jinja 模板**：bridge 渲染上下文注入生成器产物（壳 CSS/装饰 CSS/DOM/`render_root_tokens` 输出），模板内手抄的 `.shell` 壳规则、`.drift-*` 块、`.glass` 规则删除；universal 双 `:root` 结构用 `include_phase/include_wash=False` 基础块（生成器已参数化，见 mica_shell.py:150-155 docstring）。
  - **12 份手抄副本清零口径**：7 模板各 1 份装饰层 + universal 视频区块内层 1 份 + 4 直拼卡（echo 现状 0 份，通水后直接消费）= 12 → 0。验收=§四 INTG-2。
  - **reduced-motion**：唯一实现=mica_shell `_MICA_DECOR_CSS` 内 `@media (prefers-reduced-motion: reduce)` 规则（选择器与动画声明同构 `.drift-blob.drift-a/b/c`，同特异性且源序在其后——正确特异性即由此结构性保证）；finance:83/market:85 手写规则随通水删除。
- **通水的视觉不变承诺**：壳层/色斑/玻璃的 canonical 值与手抄份逐字节一致（生成器即从手抄份提取），C1-C8 的**值修正**才产生预期视觉变化；逐面预期变化清单见 §二各席「预期视觉变化」行，INTG 样张 diff 按此豁免/拦红。

---

## 二、Wave-2 逐席工单

> 四席文件域互斥（master-plan Wave 2），本文工单为唯一施工依据。共同验收：本席文件域内
> §三相关机器门转 GREEN + 既有五族契约测试不红 + 改动只落本域文件。禁 git 写、禁再派代理。

### 2.1 universal 席（文件域：`domains/render/card_render/templates/universal_card.html`）

| # | 任务 | 锚点 → 动作 |
|---|------|-------------|
| 1 | 圆角（C1） | :63-65 删 `--radius-lg/md/sm` 三兄弟；:404→`8px`；:532/:589→`16px`；:94 `28px`→`var(--r-shell)`；:181 `7px`→`6px`；:574/:614 `3px`→`4px`；:920 `50px`→`999px`；:1138 `11px`→`12px` |
| 2 | 平行刻度废除 | 即任务 1 前半（三兄弟变量+引用全清，模板内不得再现 `--radius-` 私名） |
| 3 | legacy 灰（C6） | :745 `#555`→`var(--text-main)`；:750 `#444`→`var(--text-main)`；:1583/:1600 `#999`→`var(--text-secondary)` |
| 4 | 字体栈（C9） | :915 `.source-badge` sans 字面量→`var(--font-family)` |
| 5 | 三色斑（C2/C13） | 全页收敛为恰一层 `DRIFT_BLOBS_HTML`（3 枚）；:1040-1065 视频区块内层手抄份删除 |
| 6 | 玻璃（C3） | :188→GLASS_MAIN（.60/.30→.66/.44）；:437/:586/:721/:1710 `0.55`→`0.66`；:473 `0.60`→`0.66`；:861 页脚 `0.50`→`0.46`；:1159 footer-colored→GLASS_FOOT alpha（.68→.66/.52→.46，描边→0.95/0.35/0.72，accent/wash color-mix 着色层保留） |
| 7 | 字号（C8） | :1108/:1114/:1115/:1118 `13.5px`→`14px`；:1161 `14.5px`→`14px` |
| 8 | 通水（C13） | 壳层 CSS/装饰层/`:root`（基础块 `include_phase=False, include_wash=False`）全部改消费 bridge 注入的生成器产物 |
| — | 预期视觉变化 | 内径 7→6/3→4/11→12/50→999、行面 0.55/0.60→0.66、页脚 0.50→0.46、字号 13.5/14.5→14、视频区块色斑由内层改透外层——样张 diff 按此豁免 |

### 2.2 finance+market 席（文件域：`templates/finance_card.html` + `templates/market_card.html`）

| # | 任务 | 锚点 → 动作 |
|---|------|-------------|
| 1 | 两斑改三斑（C2） | 两卡 DOM 各补 `<span class="drift-blob drift-c">`（finance:135 附近/market 对应处）；52s 定义随通水由 `_MICA_DECOR_CSS` 供给 |
| 2 | 字号（C8） | finance:109 / market:112 `12.5px`→`12px` |
| 3 | 语义色（C4） | finance:21-22 / market:23-24 `--up:#d54941`→`var(--danger)`、`--down:#2e9e6b`→`var(--success)` |
| 4 | reduced-motion 修复（C13/G9） | 删除 finance:83 / market:85 手写 `.card .drift-blob` 规则，由生成器单源产出 |
| 5 | 通水（C13） | 壳层/装饰层/玻璃（:99 已是 0.66→0.44 合规值，改 token 消费）/`:root` 全部改生成器产物 |
| 6 | 行高核对（C7） | 两卡现无 1.55/1.65，通水后由 E03 扩展门锁死即可（无需改值） |
| — | 预期视觉变化 | +第三枚色斑（52s drift-c）、12.5px→12px——样张 diff 按此豁免 |

### 2.3 misc 模板席（文件域：`templates/{mermaid,song,affinity,error}_card.html` 四张）

| 卡 | 任务 | 锚点 → 动作 |
|----|------|-------------|
| mermaid | C9 | :24 JS `fontFamily` 字面量→bridge 注入的 `FONT_FAMILY_STACK` 逐字值 |
| mermaid | C13 通水 | 壳/装饰/玻璃（:141 已合规 0.66→0.46，改 token 消费） |
| song | C3 | :133 `0.68`→`0.66`（GLASS_MAIN） |
| song | C8 | :254 `12.5px`→`12px` |
| song | C13 通水 | 壳/装饰/`:root` 改生成器产物 |
| affinity | C3 | :180-181 行面 `.62`→`.66`、描边 `.98/.55`→`0.95/0.35/0.72`（accent 着色保留）；:132/:234 已合规改 token 消费 |
| affinity | C4 | :37-38 `--score-hot/--score-cold` 改消费语义 token（值不变） |
| affinity | C13 通水 | 壳/装饰/`:root` 改生成器产物 |
| error | C7 | :110 `1.65`→`1.6` |
| error | C2 | 补第三枚 drift-c（:48-63 现两枚）；`wash_blob_mix=24` 豁免保持（bridge:1752 不动） |
| error | C9 | :28 `--mono-family` 改 bridge 注入 `MONO_FONT_STACK`（值逐字不变） |
| error | C13 通水 | 壳/装饰/玻璃（:94 合规，改 token）/`:root` 改生成器产物；`ERROR_THEME` 注入链路不动 |
| — | 预期视觉变化 | song 玻璃 0.68→0.66、affinity 行面 0.62→0.66、error +第三枚色斑、行高/字号微调——样张 diff 按此豁免 |

### 2.4 直拼卡席（文件域：`domains/chat_reply/capabilities/echo.py` + `domains/ops/admin/debug.py` + `domains/render/card_render/usage_cards.py` + `domains/render/templates.py`）

| 卡 | 任务 | 锚点 → 动作 |
|----|------|-------------|
| echo（help） | C8 | :3398 `11px`→`12px` + `.14em`→`.06em`；:3400 `12.5px`→`12px`；:3417 `14.5px`→`14px`；:3424 `11.5px`→`12px`；:3420 `gap:9px`→`8px` |
| echo | C1/C7 | :3420 `border-radius:11px`→`12px`、`line-height:1.55`→`1.5`；:3400 `1.55`→`1.5` |
| echo | C3 | :3417/:3420 行面 `.62`→`.66` |
| echo | C13 通水（收官） | :3273-3364 手写壳（`width:940px`）→`shell_base_css("help-shell", width_px=CARD_SHELL_WIDTHS["help"])`；**补齐色斑层**（现 0 枚→生成器 3 枚，`decor=True`）；收敛为 `render_shell(...)` 整文档产出 |
| debug | C4 | :759 `extras={"--good":"#1a9e6c","--bad":"#d64545"}`→`SEMANTIC` 值；:805 `#b07d1a` 字面量→`var(--warning)` |
| debug | C7 | :806 `1.55`→`1.5` |
| debug | C9 | :813 `Consolas,monospace`→`var(--mono-family)` |
| debug | C13 通水 | :769 手写壳（`width:880px`）→`shell_base_css`（`CARD_SHELL_WIDTHS["debug"]`）；:778-805 手抄色斑层→`_MICA_DECOR_CSS+DRIFT_BLOBS_HTML`；收敛 `render_shell` |
| usage | C4 | :271-273 ok/warn/bad 三色→`var(--success)/var(--warning)/var(--danger)` |
| usage | C8 | :285 `12.5px`→`12px` |
| usage | C9 | :53/:287 `Consolas,monospace`→`var(--mono-family)` |
| usage | C13 通水 | :236 手写壳（`width:900px`）→`shell_base_css`（`CARD_SHELL_WIDTHS["usage"]`）；:241-283 手抄装饰层→生成器；收敛 `render_shell` |
| media（templates.py） | C7 | :154 `1.65`→`1.6` |
| media | C13 通水 | :67 `width:640px`→`shell_base_css`（`CARD_SHELL_WIDTHS["media"]`）；:79-100 手抄装饰层→生成器（`:root` 已在 :209 消费生成器，本席收官其壳与装饰） |
| — | 预期视觉变化 | echo +三枚色斑（从无到有，最显著）、11/11.5/12.5px→12、14.5→14、行高/圆角微调、usage/debug/media 色值换源不变色——样张 diff 按此豁免 |

---

## 三、机器门验收清单（GATES 席对齐）

> GATES 席产出 `tests/test_v21r3_visual_gates.py`（8 门）+ 4 项既有测试扩展。wave-2 施工期间
> RED，逐席完工转 GREEN；全部 GREEN 是 INTG 启动的前置条件。

### 3.1 八门（test_v21r3_visual_gates.py）

| 门 | 断言口径 | 覆盖面 |
|----|----------|--------|
| 门1 圆角 | `border-radius` 值 ⊆ 合法集：`{0}` ∪ `RADIUS_INNER_PX{4,6,8,12,16}` ∪ `{999px,50%}` ∪ `var(--r-shell/--r-panel/--r-tile)` 引用；`--radius-*` 私名变量=0 处 | 11 面全量 |
| 门2 色斑 | 每面 `.drift-blob.drift-[abc]` 恰 3 枚；`animation` 时长集合恰 `{46,52,58}s`；keyframes ⊆ `{mica-drift-a/b/c}`；`@media (prefers-reduced-motion: reduce)` 关停规则存在且选择器与动画声明同构 | 11 面 |
| 门3 玻璃 | 白玻璃渐变/平面 alpha 只允许取 `{0.66,0.44,0.46}`（GLASS 两档）与描边 `{0.95,0.35,0.72}`；着色 color-mix 层的 rgba 白底 alpha 同口径 | 11 面 |
| 门4 语义色 | `#d64545/#1a9e6c` 等 SEMANTIC 五色之外的红绿黄字面量=0（universal amber 装饰族白名单豁免）；`--up/--down/--good/--bad/--score-hot/--score-cold` 均为 `var()` 消费 | 11 面 |
| 门5 OVERLAY | 深色遮罩 rgba 只允许四员登记值 | 11 面 |
| 门6 legacy 灰 | `#555/#444/#999` =0（并入既有 `_LEGACY_SECONDARY_GRAYS` 黑名单） | 11 面 |
| 门7 mono/sans 栈 | 裸 `Consolas`/`Cascadia`/`JetBrains`/`Courier` 字面量=0（mono 一律 `var(--mono-family)` 或生成器注入）；sans `font-family` 字面量必须与 `FONT_FAMILY_STACK` 逐字一致或为 `var(--font-family)` | 11 面 |
| 门8 宽度 | 渲染产出的壳宽度值 ∈ `CARD_SHELL_WIDTHS.values()`；模板/直拼卡源内手写 `width:<int>px` 壳声明=0 | 11 面 |

### 3.2 四扩展（既有测试文件）

| 扩展 | 文件 | 动作 |
|------|------|------|
| E1 行高/字距/动画门 + 相位确定性入口 | test_e03_typography.py + test_phase_determinism.py | E03 `CARD_TEMPLATES` += `error_card.html` 并新增 4 直拼卡面覆盖（读生成/源文件文本断言）；相位确定性 `_RENDERERS` += `error_card/usage_card/echo_help/debug_setup` 四入口（error 走 `render_error_card_html`，usage/echo/debug 以固定 payload 调渲染函数） |
| E2 vis5 三门+字号下限门覆盖直拼卡 | test_template_visual_audit.py | `_EDITABLE_TEMPLATES` 口径扩至 11 面（直拼卡以源文本参与 zebra/文字可读/次级灰/字号下限断言） |
| E3 宽度登记完整性 | test_rendering_contract.py（或门8 内） | `CARD_SHELL_WIDTHS` 含 11 键断言（7 既有 + help/usage/debug/media） |
| E4 兜底截图透明底 | 新增于 GATES 文件或 render_backends 相关测试 | 静态断言 render_backends 兜底分支 `screenshot(...)` 调用含 `omit_background=True`（两分支一致） |

### 3.3 附加导出门（C11）

- `bridge.__all__` 含 `render_error_card_html`（可并入 test_rendering_contract 既有导出面断言）。

---

## 四、收尾验收（INTG 席）

1. **通水实证**：生产导入面 `render_shell`/`shell_base_css`/`_MICA_DECOR_CSS`/`DRIFT_BLOBS_HTML`/`render_root_tokens` 消费点计数 >0 且分布于 11 面（echo/debug/usage/media/bridge 装配处 grep 实证）；**12 份手抄副本=0**（按 §0.2-G 的副本清单逐条 grep 反证）。
2. **机器门全绿**：`tests/test_v21r3_visual_gates.py` 8 门 + 4 扩展 + 3.3 附加门全 GREEN；五族既有契约（rendering_contract / mica_builders / visual_audit / e03 / phase_determinism）全绿。
3. **哈希与机器册**：`python tests/verify_hashes.py --write`（本批改动了 DESIGN-SPEC.md、docs/rendering-contract.md 等清单内文件）；`python scripts/doc_sync.py --write`；如帮助/触发词受影响（本批不应受影响）才跑 `command_catalog.py --write`。
4. **四门禁全量**：`dev.ps1 -Task test / lint / typecheck / runtime-layout` 全绿（解释器 `../ChatBot_Runtime/venv/Scripts/python.exe`，`PYTHONDONTWRITEBYTECODE=1` + `--basetemp` + `-p no:cacheprovider`）。
5. **样张 diff**：SAMPLES 席 11 面 baseline vs 收口后逐面 diff；预期视觉变化按 §二各席「预期视觉变化」行豁免，**清单外变化=拦红回查**。error 卡 `wash_blob_mix=24` 豁免在 diff 备注中显式核对。
6. **事实同步移交**：INTG 出总收尾报告（带实跑证据），主会话据此更新 HANDBOOK/AGENTS.md（SPECS 席不碰这两文件）。

## 五、回滚说明

- **性质**：本批是纯展示层批改，无行为开关、无数据迁移、无协议变更；渲染失败链路已有「纯文本兜底零破坏」铁律（rendering-contract §一-7）兜底，最坏情况=卡片外观回退。
- **回滚单位**：按席位 commit 粒度 `git revert`（INTG 收尾时每席独立成 commit 是回滚前提，主会话收尾时统一提交——各席本身禁 git 写）。回滚顺序与施工顺序相反：先直拼卡/Jinja 模板席，再 CORE 值册，最后 GATES 测试（测试先于实现回滚会让门禁红屏误导排查）。
- **哈希联动**：revert 后必须再跑一次 `verify_hashes.py --write`（清单内文件的字节随 revert 变化），否则 `--check` 常驻门红屏。
- **样张护栏**：baseline 样张与 sha256 清单（SAMPLES 席产出）在回滚后可复跑 diff，证明视觉回到 baseline。
- **局部回滚**：单条 C 裁决回滚（如 C8 字号被用户否决）=只改该条映射的目标值 + 值册同步 + 对应门常量改回，不牵连其它条目——C1-C13 每条独立可执行是本规格的结构性要求。

## 六、边界与非目标

- universal amber 装饰族（:49-59）与平台蓝（:49 `--blue`/:270 `#1d9bf0`）**不改**（装饰/平台 token，非语义色，C4 边界）。
- 存量展示级字号（echo:3399 27px、debug:800 28px、universal 大数字等）**不追溯**（DESIGN-SPEC §一-7 既有口径）；C8 只收敛裁决点名的值。
- `TYPE_SCALE_PX` 全量接线（11 面字号全部对阶梯）**不做**，仅增补 14px 成员并钉死定位（C8 规格细化）。
- WebUI 侧 token 消费口径归 `docs/design/webui-*.md`（WEBUI 席），本文只约束 HTML 卡渲染 11 面。
- 本规格不改任何代码/测试文件（SPECS 席纯文档域）；值册登记的具体代码形态（常量名/结构）以 CORE 席实现为准，本文登记的是**值与口径**。
