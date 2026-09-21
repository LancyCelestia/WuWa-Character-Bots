# HTML 渲染模板统一方案（v21r3 · 2026-09-18）

> 对应你的任务 1：「HTML 渲染模板仍未统一——统一」。
> 本文件先给出**现状差异的实测矩阵**与**统一目标形态**，再给分步迁移与验收。
> 涉及你直接看到的卡片外观，故先成文评审，确认后再动代码。

---

## 一、现状：两套机制并存

| 机制 | 载体 | 数量 |
|---|---|---|
| Jinja 模板卡 | `domains/render/card_render/templates/*.html` | 7 张（affinity / error / finance / market / mermaid / song_candidates / universal） |
| f-string 直拼卡 | 见下表 | 4 处 |

**4 处直拼卡真身**（契约测试 `tests/test_mica_builders_contract.py` 的锁定对象）：

| # | builder | 真身位置 |
|---|---|---|
| 1 | `_help_mica_html`（帮助手册卡） | `domains/chat_reply/capabilities/echo.py:3254` |
| 2 | `_llm_setup_mica_html`（LLM 接入检查卡） | `domains/ops/admin/debug.py:714` |
| 3 | `usage_report_mica_html`（用量/账单卡） | `domains/render/card_render/usage_cards.py:69` |
| 4 | `render_media_card_html`（旧媒体卡降级器） | `domains/render/templates.py:191` |

**已统一的部分**：token 的**取值来源**已单源（`theme_tokens.py` 的
`SHADOW_PRIMARY` / `SHADOW_SECONDARY` / `BRAND_THEME.*` / `FONT_FAMILY_STACK`），
由 `test_mica_builders_contract.py` 的 20+ 断言常驻锁定。

**未统一的部分（实测差异）**——四处 `:root` token 块的长度与内容都不同：

| 卡 | `:root` 块长度 | 主色变量名（`--pc` 退役**前**） | 特有 token |
|---|---|---|---|
| echo_help | 672 字符 | `--accent` | — |
| debug | 703 字符 | `--accent` | `--good` / `--bad` |
| usage | 1254 字符 | `--accent` **+ `--pc` 别名双写** | vis4 六键（`--glow-accent` / `--divider-line` / `--surface-a/b/neutral`） |
| media | 1176 字符 | **只有 `--pc`**（无 `--accent`） | `--accent-dark` / `--accent-rgb` |

> 上表是 2026-09-18 `--pc` 退役**之前**的实测快照（保留作证据）。退役后主色名全卡
> 统一为 `--accent`，「usage 别名双写」与「media 只认 `--pc`」两处分叉已消除；
> 第 2-4 步接入 `render_root_tokens` 后，公共子集与声明顺序也已统一（见 §三）。

另有一处**书写风格**差异：media 卡的 CSS 是 `--text-main: #18191c`（冒号后带空格），
其余三处是 `--text-main:#18191c`。→ **第 2-4 步已统一为冒号后无空格**。

复现命令：
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 "$VENV" -B -c "
import re
from plugins.bot_unified_runtime.output.templates import render_media_card_html
h = render_media_card_html({'title':'t','platform':'bilibili','author':'a','stats':{'播放':'1'},
  'summary':'s','footer':'https://e.invalid/1','bot_name':'守岸人','feature_label':'解析'})
print(re.search(r':root\s*\{(.*?)\}', h, re.DOTALL).group(1)[:200])
"
```

---

## 二、目标形态：一个生成器，一处外壳

在 `domains/render/card_render/` 下新增 `mica_shell.py`，对外只暴露两个纯函数：

```python
def render_root_tokens(
    *,
    accent: str,
    accent_ink: str,
    phase: float,
    wash: dict[str, str],
    extras: Mapping[str, str] | None = None,
) -> str:
    """产出统一的 :root 变量块。

    固定包含（全卡一致、顺序一致、空格风格一致）：
      --phase / --accent / --accent-ink
      --wash-1..3 / --wash-mist / --wash-blob-1
      --text-main / --text-sub / --ink / --muted
      --font-family / --r-shell / --r-panel / --r-tile
      --mica-shadow / --mica-shadow-soft
    extras 追加卡特有 token（如 --good/--bad、vis4 六键、--accent-dark/--accent-rgb）。
    """

def render_shell(
    *,
    title: str,
    body_html: str,
    css: str,
    tokens: str,
    width_px: int | None = None,
) -> str:
    """产出完整卡片文档：<!doctype html> + 透明 body + .card 根元素 + 单一 <style>。

    铁律内建：无 <meta viewport>、body background:transparent、
    根元素带 .card、字重 ≤700、阴影只用两枚 token。
    """
```

**统一后的不变量**（由新的契约测试同时约束两套）：

1. 主色变量名统一为 `--accent`，**不再有任何别名**（消除 media 只认 `--pc`、其余卡只认 `--accent` 的分叉；`--pc` 家族已于步 0 彻底退役）；
2. 冒号后统一无空格（消除 media 的风格分叉）；
3. 公共 token 子集与顺序固定；卡特有 token 一律经 `extras` 显式声明；
4. 4 处直拼卡与 7 张模板**共用同一份公共 token 块**。

---

## 三、迁移步骤（每步独立可验证）

| 步 | 内容 | 验证 | 状态 |
|---|---|---|---|
| **0** | **`--pc` 家族彻底退役，全仓统一为 `--accent` 家族**（用户 2026-09-18 裁定） | 全卡种渲染产物零 `--pc`；`test_mica_shell.py` 断言缺席 | **已完成** |
| 1 | 新增 `mica_shell.py`（纯新增，不改任何现有产出） | 新增单元测试断言生成器自身的铁律 | **已完成**（`tests/test_mica_shell.py` 12 passed；渲染契约 254 passed 无回归） |
| **1.5** | **`mica_shell` 扩展为可接入形态**：`render_shell` 改**双层**结构（外层纯容器 `.card` + 内层视觉外壳）、新增 `shell_base_css()`（外壳公共规则，参数化类名/宽度）、`_MICA_DECOR_CSS`（漂移色斑 + `.glass`，四张卡此前逐字各抄一份）、`DRIFT_BLOBS_HTML` | `test_mica_shell.py` 26 passed（新增 9 例） | **已完成** |
| 2 | media 卡接入 `render_root_tokens`（差异最大：原**没有** `--accent-ink`/`--ink`/`--muted`，补齐） | 契约测试 + 端到端 token 比对 | **已完成** |
| 3 | echo / debug 卡接入（debug 的 `--good`/`--bad` 经 `extras`） | 同上 | **已完成** |
| 4 | usage 卡接入（vis4 六键经 `extras`） | 同上 | **已完成** |
| 5 | 7 张模板的 `:root` 块改为引用同一份公共 token | `test_rendering_contract.py` 6 模板断言 | **已完成**（2026-09-18，见下） |
| 6 | 重录渲染 hash 台账 | `tests/verify_hashes.py --write` + 复跑 | **已完成**（19 个交付物） |

**第 1.5 步产出（2026-09-18）**：`render_shell` 原为**单层**设计（视觉挂在外层
`.card` 上），与四张直拼卡的实测结构（外层纯容器 + 内层 `.help-shell`/`.setup-shell`/
`.shell`/`.panel`）不符。改为双层后新增 `stage_class` / `shell_class` /
`shell_width_px` / `decor` 四个参数，并把「雾底 + wash 对角透色 + 1px 内高光描边 +
单枚阴影」抽为 `shell_base_css()`、把漂移色斑与 `.glass` 抽为 `_MICA_DECOR_CSS`。

**第 2-4 步产出（2026-09-18）**：四张直拼卡的 `:root` 改由 `render_root_tokens`
单一产出。实测四卡产出的**公共 token 18 项齐、声明顺序一致、零残留占位符**
（`--phase`/`--accent`/`--accent-ink`/`--wash-1..3`/`--wash-mist`/`--wash-blob-1`
+ 公共十项）；media 卡补上原先缺失的三项（均未被其 CSS 引用，视觉零变化）。
新增 4 门契约测试（`test_mica_builders_contract.py` §10）把「子集齐 / 顺序固定 /
跨卡逐项一致」锁死。渲染相关 37 个测试文件 **927 passed / 2 skipped**。

**回归修复（同批）**：垫片 `output/card_render/usage_cards.py` 是**显式列名转发**
（v21r2 快照），真身删除主题常量 import 后垫片在导入期即断（3 个测试文件收集失败）。
修法：垫片改为直接自 `theme_tokens` 转发那 4 个常量——维持旧路径可见面不变、
真身保持干净。经全量 `--collect-only` 确认无其它同类断点。

**第 5 步方案（已勘察，待执行）**：7 张模板的 `:root` 目前是**硬编码字面量**
（`--text-main: #18191c;` / `--r-shell: 30px;` / `--mica-shadow: 0 12px 32px …`），
值虽与 `theme_tokens` 一致（`test_rendering_contract.py` 逐条锁定），但**改
`theme_tokens` 不会自动同步**——这是真实的分叉风险。改造路径：

1. `bridge.py` 加 `_card_root_tokens()` 薄封装（转调 `render_root_tokens`）；
2. 7 个 render 入口（`render_universal_card_html` / `render_market_card_html` /
   `render_finance_card_html` / `render_song_candidates_html` /
   `render_affinity_card_html` / `render_error_card_html` / `render_mermaid_html`）
   在 `.render(...)` 上下文注入 `root_tokens`；
3. 模板 `:root` 块替换为 `{{ root_tokens }}`，**卡特有 token 经 `extras` 传入**
   （affinity 的 `--accent-soft/-panel/-panel-me/-line/-chip/-light`、market 的
   `--up`/`--down`/`--text-secondary`、各卡的 `--mica-shadow-panel` 等）；
4. **同步 `test_rendering_contract.py:546`** 的 `assert "--r-shell: 30px" in html_text`
   ——形态从「冒号+空格」统一为「冒号无空格」，该断言需改为无空格形态；
5. 同步 `docs/rendering-contract.md` 与 render hash 台账。

**风险提示**：第 5 步会让 7 张模板的渲染产物字节变化（顺序 + 空格），
CSS 语义不变 → 预期视觉零变化，但**建议配截图对比验收**（四张直拼卡已按此标准完成）。

**第 5 步基础设施已就绪（2026-09-18）**——两处零风险前置改动，已过回归（渲染相关
250 passed）：

1. `mica_shell.render_root_tokens` 新增 `wash_blob_mix: int = 35` 参数。**为什么必须
   有**：`error_card` 的 `--wash-blob-1` 历史值是 24%（其余六张 35%），若接入时强行
   拉成 35，色斑浓度会变，直接违反「视觉不变」硬约束。参数默认值 35 保持四张直拼卡
   与其余模板零变化。已加两门测试锁住（默认值 + 24% 可传）。
2. `bridge.py` 新增 `_card_root_tokens(color, *, phase, extras=None, wash_blob_mix=35)`
   薄封装，转调 `render_root_tokens`：`accent_ink` 取 `_rgb_to_hex(_darken(rgb))`
   ——与模板既有的 `platform_color_dark`（`--accent-dark`）**同源同算法**，也与四张
   直拼卡的 `accent_ink` 同语义。7 个 render 入口只需注入它的返回值。

**待用户裁定的分叉点（步 5 执行前必须定）**：`--accent-dark` 与 `--accent-ink`
是**同一语义的两个名字**（都是「深一档主色」，算法同为 `_darken`）。模板侧现有
`var(--accent-dark)` 引用共 36 处（error 4 / finance 3 / market 2 / song 6 /
universal 21）。两条路径：

- **方案 A（保守，零视觉风险）**：统一产出注入 `--accent-ink`，同时把 `--accent-dark`
  原值经 `extras` 一并注入。模板 body **零改动**，产物里留下两个同值 token。
- **方案 B（彻底，产物更干净）**：模板里 36 处 `var(--accent-dark)` 全量改名为
  `var(--accent-ink)`，`--accent-dark` 不再注入。改动面大，需逐模板比对 + 截图验收。

> **裁定结果（2026-09-18 澜汐）：「统一成 dark」**——即采纳「统一命名」的思路，
> 但**统一到 `--accent-dark`**（而非 `--accent-ink`）：模板侧 36 处引用零改动，
> f-string 直拼卡侧 14 处 `var(--accent-ink)` 随改名，`--accent-ink` 全仓退役。
> 本段两条路径的原始记录保留作决策留痕。

---

**第 5 步产出（2026-09-18 已完成）**：7 张模板的 `:root` 公共段全部改为
`{{ root_tokens | safe }}`，卡特有 token 原位保留（不搬 extras，把改动面压到最小）。

**踩到的坑（新增模板必读）**：Jinja 环境是 `autoescape=True`，而 token 块含
`--font-family` 的双引号（`"Segoe UI"`）——直接写 `{{ root_tokens }}` 会被转义成
`&#34;`，而 **`<style>` 内的 HTML 实体不会被解码** → 字体族静默失效。
必须写 `{{ root_tokens | safe }}`。四张 f-string 直拼卡不受影响（不经 Jinja）。

**逐卡差异（决定各自 extras / 参数）**：

| 卡 | 模板变量名 | wash-blob | 备注 |
|---|---|---|---|
| market / finance / song / error / universal | `{{ platform_color }}` | 35%（**error 24%**） | error 经 `wash_blob_mix=24` 保留原值 |
| affinity | `{{ pc }}` | 35% | `pc` 未过 `_safe_css_color`，注入前补校验（模板已改用 `|safe`） |
| mermaid | 硬编码 `#607080` | 35% | 主色恒为 `UNKNOWN_PLATFORM_COLOR` |

**`universal_card` 的双 `:root` 陷阱**：该模板有两个 `:root`，都是全局选择器。
①`test_phase_determinism*.py` 的 `_single_phase()` 断言全页**恰好一处** `--phase`
声明；②渲染契约测试禁止同一 token 族内重复定义。故**公共段只由视频卡块声明一次**，
基础块只出 accent 家族、语义色与尺度 token（`--accent-light`/`--accent-mid`/
`--accent-rgb`/`--blue`/`--amber-*`/`--text-secondary`/`--bg-*`/`--radius-*`/`--font-scale`）。

**契约测试取材变更**：`tests/test_rendering_contract.py` 的 `_css_of(name)` 原本只读
**模板源码**，公共段搬进生成器后会误报「模板缺 --mica-shadow / --r-shell / --wash-*」。
改为「模板源码（剔除 `:root` 块）+ 渲染产物的 `:root` 块」。剔除时**必须先把
`{{ ... }}` 换成占位符**——块内 Jinja 表达式自带 `}`，会让 `[^}]*` 提前收尾、
只删掉半个块（实测残留 `--mica-shadow-panel`）。`test_brand_wash_tokens_injected`
同步改为「值由 bridge 按该卡主色派生」形态（期望值从渲染产物的 `--accent` 反读现算，
不在测试里硬编码第二份主色表）。

**验证**：渲染相关 49 个测试文件 **1182 passed / 4 skipped**；门禁四件全绿；
hash 台账重录 12 项漂移后复检干净。


**第 0 步产出（2026-09-18 已完成）**：`--pc`/`--pc-dark`/`--pc-light`/`--pc-mid`/
`--pc-rgb` 全族改名为 `--accent` 家族，共 26 个文件 310 处；`templates.py` 的
`__PC__`/`__PC_DARK__`/`__PC_RGB__` 占位符同步改为 `__ACCENT__` 系列。
`usage_cards.py` 原有的 `--accent` + `--pc` 别名双写收敛为单写。
**验证**：9 种卡（universal/market/finance/song_candidates/affinity/error/
mermaid/usage/media）实际渲染产物全部含 `--accent`、零 `--pc`；
渲染相关 38 个测试文件 827 passed / 2 skipped；门禁四件全绿。
**保留不动**：Python/Jinja 侧标识符（`pc` 局部变量、`{{ pc }}` 渲染上下文、
`data.get("pc")` 载荷键）属另一层命名，不在 CSS token 退役范围内。

**第 1 步产出**：`plugins/bot_unified_runtime/domains/render/card_render/mica_shell.py`
暴露 `render_root_tokens()`（统一 `:root` 块，冒号后无空格、公共 token 顺序固定、
`extras` 追加卡特有项）与 `render_shell()`（完整卡片文档，铁律内建）。
**纯新增，现有渲染载体产出逐字节不变**。

---

## 四、风险与边界

**风险**

1. **产出 HTML 会变**（空格风格统一 + media 卡补齐三项公共 token），渲染 hash 台账必须重录。
   CSS 语义不变 → **预期视觉零变化**，但需截图对比确认。
2. media 卡原先**没有** `--accent-ink` / `--ink` / `--muted` 三项，补齐是安全的（只新增变量、不删旧变量，且本卡 CSS 未引用它们 → 视觉零变化）；
   但若模板里已有 `--accent` 的其他含义，需先核对（迁移前会先扫一遍）。
3. 7 张模板改动面较大，`test_rendering_contract.py` 与
   `test_universal_card_visual.py` 是硬门，改错会立刻报红。

**边界（本次不做）**

- 不改任何卡片的**视觉设计**（配色、间距、圆角值、布局）；
- 不合并 7 张模板为一张（它们语义不同，合并会降低可读性）；
- 不动 `theme_tokens.py` 的 token **取值**。

---

## 五、确认结论（2026-09-18 用户裁定）

1. **是否执行** → **执行**。原话：「执行：这是一次「结构统一、视觉不变」的重构，
   完成后 4 处直拼卡与 7 张模板共用一套外壳与 token 块。」
2. **主色口径** → **只保留 `--accent`，`--pc` 家族彻底退役**。原话：「希望只保留
   `--accent`、把 `--pc` 彻底退役」。已作为**步 0** 落地：26 个文件 310 处；
   `theme_tokens.GLOW_ACCENT` 等共享 token 的消费点一并收敛，别名双写不再存在。
