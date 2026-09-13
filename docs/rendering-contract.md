# 渲染契约（Card Rendering Contract）

> 适用于 `plugins/bot_unified_runtime/output/card_render/` 全部卡片模板。
> 单一事实来源：`theme_tokens.py`（守岸人品牌主题 + 平台受控变体 + shell 常量）。
> 契约的机器可执行形态：`tests/test_rendering_contract.py`（全离线，字符串/Jinja2/纯函数断言）。
> 任何 AI 或人，改模板前先读完本页；违反任意一条都会被契约测试拦下。

## 一、铁律（所有模板，无例外）

| # | 规则 | 原因 / 实现要点 |
|---|------|----------------|
| 1 | **无 `<meta viewport>`**（`META_VIEWPORT_POLICY = "forbidden"`） | 截图走 playwright `new_page(viewport=...)`，meta viewport 仅移动仿真生效，只会造成双宽度来源 |
| 2 | **body 透明**（`body { background: transparent; ... }`） | 截图 `omit_background=True` 依赖透明底出圆角卡 |
| 3 | **字重 ≤ 700**（`FONT_WEIGHT_MAX = 700`） | 中文粗体渲染发糊，700 封顶 |
| 4 | **动画元素必须在 `.card` 子树内** | 截图目标是 `.card`（`render_backends` 固定 `query_selector(".card")`）；色斑可走 `.card::before/::after` 伪元素或 `.card` 内 `.drift-blobs` 容器 |
| 5 | **光晕 alpha ≥ 0.05** | 低于该阈值的柔光在生产裁剪后不可见却增加合成开销 |
| 6 | **阴影只准用登记族**（vis4 分级）：`theme_tokens.SHADOW_CSS_VARS` 为唯一登记处——`--mica-shadow`(L3 外壳) + `--mica-shadow-panel`(L2 面板大件) + `--mica-shadow-soft`(L1 瓦片小件)；`box-shadow` 只允许 `none` / `var()` 引用登记表成员，**禁止表外值（含 inset 内高光、光晕）**；契约/审计测试白名单从登记表动态派生，新增档位先入册再使用 | 统一投影体系 + 层次可辨；内高光语言由 1px 渐变描边（padding-box/border-box 双背景）承担，不走阴影 |
| 7 | **渲染失败 → 纯文本兜底，契约零破坏** | 后端 `render_card` 失败返回 `None`；各能力收到 `None`/空 PNG 必须回退纯文本（如点歌候选列表、mermaid 代码块原样保留）；bridge 各 `render_*_html` 对 `None`/`{}` payload 不抛异常 |

## 二、守岸人本命色（品牌基底，不可被平台色覆盖）

淡蓝 / 白 / 深蓝 / 少量星空紫。实现为釉瑚云母洗四 token（`theme_tokens.derive_wash_tokens`）：

| token | 色相锚点 | 用途 |
|-------|---------|------|
| `--wash-1` | 淡蓝 210°（可被平台色相 ±30° 内轻推，比例 0.5） | 主透色 |
| `--wash-2` | 星空紫 265°（固定） | 次透色 + 外壳投影染色 |
| `--wash-3` | 深蓝 228°（固定） | 第三色透底 |
| `--wash-mist` | 雾底淡蓝 214°（固定，明度 ≥94%） | 打底 |

- 外壳底色**只能**是 `linear-gradient(145deg, var(--wash-mist) 0%, ...)` 这条 wash 渐变；`--pc` 永远不做底色。
- 平台色只允许两层受控出场：accent（徽章/高亮/链接）与 `--wash-blob-1`（≤35% 混入主色斑）。
- 灰阶 / 未知平台推力归零 → 纯本命洗。模板 `--wash-*` 注入点写法（兜底字面量必须与
  `DEFAULT_WASH_TOKENS = derive_wash_tokens('#607080')` 逐键一致，契约测试锁定；
  值随派生算法单一来源，勿手改）：

  ```css
  --wash-1: {{ wash_1 | default('#d9e0e7') }};
  --wash-2: {{ wash_2 | default('#dfdae7') }};
  --wash-3: {{ wash_3 | default('#dcdfea') }};
  --wash-mist: {{ wash_mist | default('#f4f5f6') }};
  ```

## 三、平台主题注册表 `PLATFORM_THEMES`

- 定义在 `theme_tokens.py`：每平台一条 `ThemeTokens`（accent / accent_dark / accent_light / wash 四 token / 统一布局 token / 展示名 / 别名）。
- **只收录代码中真实存在的平台 identifier**；别名（xhs→xiaohongshu、x→twitter、cpp→allcpp、ncm→netease）走 `THEME_ALIASES` 第二跳。
- 社交媒体（bilibili/小红书/抖音/微博/YouTube/Twitter·X/pixiv/LOFTER/AllCPP/Facebook/Instagram）与音乐平台（网易云/QQ 音乐/酷狗/酷我/Apple Music/Spotify）各自独立、accent 互不相同（可辨认）。
- 未知平台：`get_platform_theme(未知) → DEFAULT_THEME`（中性灰 `#607080`，安全 fallback，不臆造）。steam/epic 有 identifier 无登记色，同样落 DEFAULT_THEME。
- `bridge.py` 消费注册表派生 `PLATFORM_COLORS` / `PLATFORM_OFFICIAL_NAMES` / `_PLATFORM_FOOTER_LABELS`（历史导出名保持不变，`_derive_wash_tokens` 为 `derive_wash_tokens` 的兼容别名，echo/debug/usage_cards/templates 依赖它，勿删）。

## 四、统一 Shell 常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `--r-shell` | `30px` | 外壳圆角（五模板一致） |
| `--r-panel` / `--r-tile` | `18px` / `14px` | 面板 / 瓦片圆角 |
| 阴影 | `SHADOW_CSS_VARS`（= SHADOW_LEVELS 三级族） | 阴影档位的唯一登记处：shell/panel/tile 三级；模板内字面量必须与登记值逐字符一致（或引用 bridge 注入的同名上下文键） |
| 字体 | `FONT_FAMILY_STACK` | 五模板同栈；模板内硬编码（CSS 不能吃 HTML 转义），契约测试锁一致 |
| 次级文字 | `TEXT_SECONDARY`（`#576272`，vis5） | 全模板 `--text-secondary` 单一来源；对三档 zebra 表面对比 ≥4.5:1（WCAG AA@12px），机器门 `test_template_visual_audit.py`；旧散值 #7a828c/#8a919b/#66727f/#7a8699 已收编（market/finance 已同步收编） |
| 字号下限 | `12px` | UI 铁律；机器门锁可编辑 4 模板 + usage/media f-string 卡；`TYPE_SCALE_PX` 为新增/改版模板选用阶梯，既有卡实弹验收字号不受追溯 |
| zebra 表面 | `SURFACE_TINTS` 三档 | vis5 数值门：onstage 相邻 ΔE(a,b)≥3.0、对 neutral ≥2.5；text_sub 对每档 ≥4.5:1 |
| 间距 | `GAP_SCALE_PX = {3,4,6,7,8,10,12,14,16}` | 模板 `gap` 只允许取刻度内值，禁止发明新间距 |
| 宽度 | `CARD_SHELL_WIDTHS` | 宽度按内容族登记：universal 1440（payload `card_width` 驱动）/ affinity 1180 / market·finance 1080 / song_panel 980 / mermaid_max 840（fit-content 上限）；新模板宽度必须先进本表 |

## 五、新增模板接入步骤（checklist）

1. 复制 `market_card.html` 的 `:root` 结构作为起点（它是最小完整样例：wash 注入 + 两枚阴影 token + drift 色斑 + bot 页脚）。
2. 根元素**必须**带 `card` 类（`<div class="shell card">` 或 `<div class="card">`）——截图选择器契约。
3. 无 `<meta viewport>`；`body { background: transparent; }`；字重 ≤700。
4. 底色只用 wash 渐变；`--pc` 只做 accent；`--wash-blob-1` 混入 ≤35%。
5. 阴影只用 `var(--mica-shadow)` / `var(--mica-shadow-soft)` / `none`，两枚 token 定义与 `SHADOW_PRIMARY`/`SHADOW_SECONDARY` 逐字符一致。
6. 动画元素全部放 `.card` 子树内；`@keyframes` 只允许 `mica-drift-a/b/c`；提供 `prefers-reduced-motion` 关停。
7. gap 取自 `GAP_SCALE_PX`；宽度先进 `CARD_SHELL_WIDTHS` 登记。
8. 新平台先在 `theme_tokens._PLATFORM_ACCENTS` 登记（含展示名与别名），再在 `bridge._PLATFORM_LOGO_FILES`（可选）补图标。
9. 跑契约测试：

   ```bash
   PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_rendering_contract.py -q --basetemp="$TEMP/c1-contract" -p no:cacheprovider
   ```

10. 渲染失败路径（后端缺失/超时/异常 → `None`）必须由调用方回退纯文本；新增 `render_*_html` 对 `None`/`{}` payload 不抛异常。

## 六、payload 接线（bridge 层通用契约）

- `render_universal_card_html(payload)`：通用解析卡，接受 PlatformParse 投影 / 部分 RenderPayload 字典 / `None`；缺字段 → 对应区块整体隐藏，不抛异常（详见 bridge 模块 docstring）。
- `render_market_card_html(payload)`：股指卡（groups/rows/trend/trend_note/source_note/updated_at/delayed_note）。
- `render_finance_card_html(payload)`：股票/汇率金融卡（stocks/fx 共用壳；主题取 `BRAND_THEME` 本命基底）——属金融任务文件域，契约规则与本页一致。
- `render_affinity_card_html` / `render_song_candidates_html` / `render_mermaid_html`：各自能力域；同样遵守本页全部铁律。
- **好感度卡脏数据归一**（vis5 加固，2026-09-13）：rows/steps/tiers/bot_to_user/user_to_bot 逐字段桥层归一——score None/字符串/缺键 → 0.0（双向面板缺省 50.0）、bar 钳 0-100、cls 白名单 {up,down,flat}、None 值显示 "—"；模板 `%.1f` 格式化不再可能抛 TypeError（铁律 7 的前置保证），回归 `test_rendering_contract.py::test_affinity_card_never_raises_on_dirty_payload`。
- 逐能力接线（天气/菜谱/历史/占卜/游戏/usage → 统一 payload）由各能力调用既有 `render_*_html`；bridge 层不感知能力业务。
