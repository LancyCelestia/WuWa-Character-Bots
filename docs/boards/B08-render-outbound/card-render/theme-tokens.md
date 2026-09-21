# 卡片渲染 · token 单一事实源与阴影族

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.card-render · token 单一事实源与阴影族

- 层级：一级 B08 → 二级 card-render → 三级 `theme-tokens`
- 实现落点：`plugins/bot_unified_runtime/domains/render`、`docs/rendering-contract.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`domains/render/card_render/theme_tokens.py` 是全项目视觉数值的**唯一登记处**。输入是一个品牌色/平台标识/数值档位，输出是一张 CSS 自定义属性表；卡片模板与 f-string 直拼卡都只消费这张表，自己不许写数值。

它登记的东西大致分五族：本命色与派生洗色（`BRAND_ACCENT`、`derive_wash_tokens`、`SHELL_WASH_GRADIENT`）、平台主题（`PLATFORM_THEMES` + `THEME_ALIASES` + `get_platform_theme`）、层次与表面（`SHADOW_LEVELS` / `SHADOW_CSS_VARS` 三级族 shell·panel·tile、`GLOW_ACCENT`、`GLASS_MAIN`/`GLASS_FOOT`/`GLASS_EDGE`、`SURFACE_TINTS`、`OVERLAY_SCRIMS`、`SEMANTIC_COLORS`）、几何与排印刻度（`RADIUS_INNER_PX`、`CARD_SHELL_WIDTHS`、`GAP_SCALE_PX`、`TYPE_SCALE_PX`、`FONT_FAMILY_STACK`、`MONO_FONT_STACK`、`FONT_WEIGHT_MAX`、`META_VIEWPORT_POLICY`）、装饰层参数（`BLOB_COUNT`、`BLOB_DURATIONS`；平台色混入比 `wash_blob_mix` 不在此表，它是注入参数——缺省 35、error 卡按登记豁免传 24）。

守岸人本命色（淡蓝/白/深蓝/少量星空紫）是**基底**：平台色只允许在两个位置出场（accent 徽章高亮、`--wash-blob-1` 有限混入色斑），永远不做底色；灰阶与未知平台的色相推力归零，落回纯本命洗。

## 怎么调用

模板侧不 import Python，值靠注入：`domains/render/card_render/mica_shell.py:render_root_tokens` / `shell_base_css` / `render_shell` 与 `domains/render/card_render/bridge.py:_card_root_tokens`（配 `_vis4_context`）是两条同源供给口，产出同一批 `--var`。能力层要一张卡的完整上下文时用 `theme_to_css_vars(theme)`；要某个平台的主题时用 `get_platform_theme(platform)`（未登记平台返回 `DEFAULT_THEME`，不臆造配色）。

禁止的用法：在模板或 f-string 里写自造阴影值、自造圆角、自造间距、手抄 145deg 壳底渐变色标、把 `--accent` 当底色。装饰层三段（DOM 色斑、`@keyframes`、`prefers-reduced-motion` 关停）必须来自 `mica_shell` 生成器，不许再抄一份。

## 开关与参数

本入口没有运行期开关——它是编译期常量表，改一次全卡生效（这正是它的目的）。热改与权限的口径是：**没有热改路径**，改 token 必须改代码并重启 bot；能改的人是过契约门的人，不是配置面。

需要知道的取值约束（逐值以 `theme_tokens.py` 与 `docs/rendering-contract.md` 为准，本处不复制数值表）：阴影只准 `none` 或 `var()` 引用 `SHADOW_CSS_VARS` 成员，白名单从登记表**动态派生**，所以「新增一个档位」的正门是先入册再用；平台新 identifier 先入 `_PLATFORM_ACCENTS` 再补图标；宽度新档先进 `CARD_SHELL_WIDTHS`。

## 失败时看到什么

这一层的失败**不长成运行异常**，而长成门禁红：族外阴影、脱刻度行高、低于下限的字号、色斑数量或时长不符、`--accent` 当底色，都会在 `tests/test_rendering_contract.py` / `test_mica_builders_contract.py` / `test_template_visual_audit.py` / `test_v21r3_visual_gates.py` 当场打回，改不进树。

真正会影响运行期的是取值缺失：payload 缺字段时桥层按区块隐藏处理，脏值（`None`、字符串当数字、越界百分比）在桥层归一，模板不再抛 `TypeError`；这是铁律 7「渲染失败也只回退外观」的前置保证。

## 测试与验收

`tests/test_rendering_contract.py`（铁律逐条 + 本命色取相锁 `test_pc_never_paints_brand_base` 等）、`tests/test_mica_builders_contract.py`（直拼卡公共段，含阴影档位数断言）、`tests/test_template_visual_audit.py`（`test_zebra_surfaces_distinct`、`test_secondary_gray_single_source`、对比度与玻璃档位）、`tests/test_v21r3_visual_gates.py`（gate01–gate09 ×11 面）。登记族清单本身由 `scripts/doc_sync.py` 派生进 `docs/auto-facts.md`，只读校验用 `--check`。

真机侧不需要单独验收：token 生效与否体现在 [模板页](templates.md) 与 [后端页](render-backend.md) 的出图上，按 `docs/acceptance-manual.md` §6.6.10 的观察点①②④⑥逐卡过即可。
