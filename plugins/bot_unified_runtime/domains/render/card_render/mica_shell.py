"""釉瑚云母卡外壳单一生成器（v21r3 渲染统一，任务 1 第一步）。

背景：4 处 f-string 直拼卡（echo 帮助卡 / debug 检查卡 / usage 账单卡 / media
媒体卡）各自手写完整 HTML 外壳与 ``:root`` token 块，导致**同名 token 在不同卡
里名字、书写风格、子集都不一致**（实测差异矩阵见
``docs/design/v21r3-render-unification-plan.md`` §一）：

- media 卡只有 ``--pc``、没有 ``--accent``；其余三处反之（**该分叉已消除**：
  2026-09-18 用户裁定 ``--pc`` 家族彻底退役，全仓统一为 ``--accent`` 家族）；
- media 卡写作 ``--text-main: #18191c``（冒号后带空格），其余三处无空格；
- 公共 token 子集各不相同（debug 多语义色、usage 多 vis4 六键）。

本模块把「公共 token 块」与「卡片文档外壳」收敛为唯一实现，供两套渲染机制
（Jinja 模板卡与 f-string 直拼卡）共用。**第一步只新增、不接入**——现有产出
逐字节不变；接入在后续步骤分卡进行（每步以契约测试 + 截图对比验收）。

铁律（AGENTS.md UI 铁律，本模块内建并在测试中常驻锁定）：
无 ``<meta viewport>``；``body`` 透明；根元素带 ``.card``；字重 ≤ 700；
阴影只允许两枚 token；光晕 alpha ≥ 0.05。
"""

from __future__ import annotations

import html as _html
from collections.abc import Mapping

from plugins.bot_unified_runtime.domains.render.card_render.theme_tokens import (
    BLOB_COUNT,
    BLOB_DURATIONS,
    BRAND_NAME_EN,
    BRAND_THEME,
    FONT_FAMILY_STACK,
    GLASS_EDGE,
    GLASS_FOOT,
    GLASS_MAIN,
    MONO_FONT_STACK,
    OVERLAY_SCRIMS,
    RADIUS_INNER_CSS_VARS,
    SCORE_COLD,
    SCORE_HOT,
    SEMANTIC_DANGER,
    SEMANTIC_SUCCESS,
    SEMANTIC_WARNING,
    SHADOW_PRIMARY,
    SHADOW_SECONDARY,
)

# 公共 token 的固定声明顺序（全卡一致）。新增公共 token 只在此处加一行，
# 所有卡自动同步——这正是「改一处全项目自动同步」的落点。
# 2026-09-18 统一收尾波（CORE 值册 C1/C3/C4/C5/C9）：尾部扩入玻璃两档+描边/
# 遮罩四员/语义五色/等宽字体/内径刻度——直拼卡与 7 张模板的 :root 同步获得
# 全套 var() 可消费 token，wave-2 迁移手抄副本时零桥接改动。
_PUBLIC_TOKEN_ORDER: tuple[str, ...] = (
    "--text-main",
    "--text-sub",
    "--ink",
    "--muted",
    "--font-family",
    "--font-mono",
    "--r-shell",
    "--r-panel",
    "--r-tile",
    "--r-inner-xs",
    "--r-inner-sm",
    "--r-inner-md",
    "--r-inner-lg",
    "--r-inner-xl",
    "--r-pill",
    "--r-circle",
    "--mica-shadow",
    "--mica-shadow-soft",
    "--mica-glass-main",
    "--mica-glass-foot",
    "--mica-glass-edge",
    "--mica-scrim-badge",
    "--mica-scrim-banner",
    "--mica-scrim-code",
    "--mica-scrim-media",
    "--semantic-danger",
    "--semantic-success",
    "--semantic-warning",
    "--score-hot",
    "--score-cold",
)

# 卡片默认外壳宽度：与 theme_tokens.CARD_SHELL_WIDTHS 同源，未登记时用兜底值。
_DEFAULT_SHELL_WIDTH_PX = 880

# 统一注释（此前四张卡各写一份、措辞互有出入）。刻意不写任何 ``--token:`` 形态，
# 免得注释文本被契约测试的 token 位置检索误命中。
_TOKENS_COMMENT = (
    "/* 釉瑚云母底主题 token：全卡统一由 mica_shell.render_root_tokens 产出"
    "（wash 由 bridge 按主色派生；工艺出处=用户裁定）。 */"
)

# 渐变漂移装饰层：四张直拼卡与多张模板此前逐字各抄一份（含 keyframes 与降级
# 媒体查询）。v21r3 统一收尾波（C2）提取为**参数化生成器**：色斑数量、逐斑
# 漂移时长、phase 兜底全部可注入——finance/market 等两斑卡迁三斑、模板换血
# 时零手抄。模块常量 = 缺省实例（与历史 CSS 逐字节一致）。
#
# 逐斑登记表（C2：BLOB_COUNT=3 + BLOB_DURATIONS=(46,52,58) 升序登记）：
# (key, 几何行, 渐变变量, 渐变 stop 百分比对, BLOB_DURATIONS 位次, 交错延迟秒)。
# 位次索引把升序登记值映射回历史交错顺序：drift-a=46s / drift-b=58s / drift-c=52s。
_BLOB_SPECS: tuple[tuple[str, str, str, tuple[tuple[int, int], ...], int, int], ...] = (
    (
        "a",
        "width:58%; aspect-ratio:1; left:-14%; top:-22%;",
        "--wash-blob-1",
        ((0, 50), (46, 28), (70, 6)),
        0,
        0,
    ),
    (
        "b",
        "width:52%; aspect-ratio:1; right:-16%; bottom:-24%;",
        "--wash-2",
        ((0, 30), (48, 16), (72, 5)),
        2,
        9,
    ),
    (
        "c",
        "width:64%; aspect-ratio:1; left:22%; top:34%;",
        "--wash-3",
        ((0, 26), (48, 14), (72, 5)),
        1,
        21,
    ),
)
_BLOB_KEYS: tuple[str, ...] = tuple(spec[0] for spec in _BLOB_SPECS)

_BLOB_KEYFRAMES: dict[str, str] = {
    "a": (
        "@keyframes mica-drift-a {\n"
        "  0% { transform:translate3d(-4%,-2%,0) scale(1); }\n"
        "  50% { transform:translate3d(7%,9%,0) scale(1.18); }\n"
        "  100% { transform:translate3d(-3%,14%,0) scale(.92); }\n"
        "}"
    ),
    "b": (
        "@keyframes mica-drift-b {\n"
        "  0% { transform:translate3d(3%,4%,0) scale(1.05); }\n"
        "  50% { transform:translate3d(-8%,-6%,0) scale(.9); }\n"
        "  100% { transform:translate3d(-2%,-12%,0) scale(1.2); }\n"
        "}"
    ),
    "c": (
        "@keyframes mica-drift-c {\n"
        "  0% { transform:translate3d(-5%,4%,0) scale(1.1); }\n"
        "  50% { transform:translate3d(9%,-7%,0) scale(.88); }\n"
        "  100% { transform:translate3d(2%,-3%,0) scale(1.16); }\n"
        "}"
    ),
}


def mica_decor_css(
    *,
    blob_count: int = BLOB_COUNT,
    durations: tuple[int, ...] | None = None,
    phase_default: float | str = 0.2,
) -> str:
    """渐变漂移色斑层 CSS 生成器（C2：三枚色斑 + 时长 + phase 全参数化）。

    - ``blob_count``：色斑数量（默认登记值 ``BLOB_COUNT``=3；取前 N 个登记斑，
      几何/渐变/keyframes 取自 ``_BLOB_SPECS`` 登记表）。
    - ``durations``：逐斑漂移秒，按 drift-a/b/c 位次；缺省从登记值
      ``BLOB_DURATIONS``（升序 46/52/58）按位次索引表分配 → a=46/b=58/c=52，
      与历史 CSS 逐字节一致。
    - ``phase_default``：``var(--phase, 兜底)`` 的兜底值（默认 0.2 历史值；
      卡面 :root 已注入真实 --phase 时兜底不生效，仅 reduced-motion 外的
      防御缺省）。
    """
    if not 1 <= blob_count <= len(_BLOB_SPECS):
        raise ValueError(
            f"blob_count 必须在 1..{len(_BLOB_SPECS)}（登记表上限），收到 {blob_count}"
        )
    # 逐斑秒数：缺省从升序登记值按位次表分配（a=46/b=58/c=52，历史交错序）；
    # 显式 durations 按 drift-a/b/c 位次直取。
    if durations is None:
        per_blob = {spec[0]: BLOB_DURATIONS[spec[4]] for spec in _BLOB_SPECS}
    else:
        if len(durations) < blob_count:
            raise ValueError("durations 长度不得少于 blob_count")
        per_blob = {
            spec[0]: durations[position]
            for position, spec in enumerate(_BLOB_SPECS)
        }
    phase_token = f"var(--phase, {phase_default})"
    header = "/".join(f"{value}s" for value in sorted(per_blob[key] for key in _BLOB_KEYS[:blob_count]))
    parts: list[str] = [
        f"/* 渐变漂移色斑（wash 三色半透明互相透过，{header} 交错漂移+呼吸）。 */",
        (
            ".drift-blobs { position:absolute; inset:0; z-index:0; overflow:hidden;\n"
            "  pointer-events:none; border-radius:inherit; }"
        ),
        (
            ".drift-blob { position:absolute; display:block; border-radius:50%; "
            "will-change:transform; }"
        ),
    ]
    for key, geometry, css_var, stops, _slot, delay_offset in _BLOB_SPECS[:blob_count]:
        seconds = per_blob[key]
        stop_lines = ",\n".join(
            f"    color-mix(in srgb, var({css_var}) {alpha}%, transparent) {pct}%"
            for pct, alpha in stops
        )
        delay_suffix = f" - {delay_offset}s" if delay_offset else ""
        parts.append(
            f".drift-blob.drift-{key} {{\n"
            f"  {geometry}\n"
            "  background:radial-gradient(closest-side,\n"
            f"{stop_lines}, transparent 100%);\n"
            f"  animation:mica-drift-{key} {seconds}s ease-in-out infinite alternate;\n"
            f"  animation-delay:calc({phase_token} * -{seconds}s{delay_suffix});\n"
            "}"
        )
    for key in _BLOB_KEYS[:blob_count]:
        parts.append(_BLOB_KEYFRAMES[key])
    reduced_selectors = ", ".join(
        f".drift-blob.drift-{key}" for key in _BLOB_KEYS[:blob_count]
    )
    parts.append(
        "@media (prefers-reduced-motion: reduce) {\n"
        f"  {reduced_selectors} {{ animation:none; }}\n"
        "}"
    )
    return "\n".join(parts)


def glass_rules_css() -> str:
    """液态玻璃两档 + 1px 内高光描边规则（C3：值出自 theme_tokens.GLASS_*）。

    ``.glass``=面板主档（MAIN+EDGE）、``.glass-foot``=页脚档（FOOT+EDGE）。
    无 backdrop-filter——透明截图无物可糊；阴影只经 --mica-shadow-soft token。
    """
    return (
        "/* 液态玻璃面板：半透明白 + 1px 内高光渐变描边"
        "（无 backdrop-filter，透明截图无物可糊）。 */\n"
        f".glass {{ background:{GLASS_MAIN},\n"
        f"    {GLASS_EDGE};\n"
        "  border:1px solid transparent; box-shadow:var(--mica-shadow-soft); }\n"
        f".glass-foot {{ background:{GLASS_FOOT},\n"
        f"    {GLASS_EDGE};\n"
        "  border:1px solid transparent; box-shadow:var(--mica-shadow-soft); }"
    )


# 模块常量 = 缺省实例（历史字节形态：前导换行分段、三斑、46/58/52 交错）。
_MICA_DECOR_CSS = "\n" + mica_decor_css()
_GLASS_RULES_CSS = "\n" + glass_rules_css()


def drift_blobs_html(
    *,
    blob_count: int = BLOB_COUNT,
    phase: float | str | None = None,
) -> str:
    """漂移装饰层 DOM 片段生成器（外壳内首个孩子；卡同构）。

    ``blob_count`` 取前 N 个登记斑；``phase`` 非 None 时在容器上内联注入
    ``--phase``（直拼卡不经 :root 钉帧的备用通道，页面零 JS 不变）。
    """
    if not 1 <= blob_count <= len(_BLOB_KEYS):
        raise ValueError(
            f"blob_count 必须在 1..{len(_BLOB_KEYS)}（登记表上限），收到 {blob_count}"
        )
    spans = "".join(
        f'<span class="drift-blob drift-{key}"></span>' for key in _BLOB_KEYS[:blob_count]
    )
    style = f' style="--phase:{phase}"' if phase is not None else ""
    return f'<div class="drift-blobs" aria-hidden="true"{style}>{spans}</div>'


# 漂移装饰层的 DOM 片段缺省实例（三斑、无内联 phase，与历史逐字节一致）。
DRIFT_BLOBS_HTML = drift_blobs_html()


# ==================== 品牌胶囊组件（CAP1 2026-09-20，用户裁定） ====================
# 「所有图片都需要加上 bot头像、bot名字、bot英文名（可选：功能名）组起来的
# 胶囊功能组件」——本段是该组件的唯一实现：CSS 一份、HTML 片段生成器一份，
# 7 张 Jinja 模板经 bridge 注入的 ``capsule_css`` / ``capsule_html`` 消费，
# f-string 直拼卡（templates.py 媒体卡，及 echo/debug/usage 接入时）直接
# import ``brand_capsule_html`` / ``brand_capsule_css``。各面禁止手抄第二份
# 胶囊 DOM/文案（此前 universal/market/finance/affinity/song/mermaid/error/
# media 各写一份 .bot-foot/.cfb-*/.footer-bot-* 即本次收口的对象）。
#
# 三枚输入的单一来源：
# - 头像 = ``domains/render/bot_avatar.py::bot_avatar_uri`` 既有口径（能力侧
#   经 payload ``bot_avatar_url`` 传入），缺失时胶囊内头像位降级为「守」字
#   圆点（沿用全仓 11 面既有兜底形态，不整段消失、无布局跳变，见台账
#   #21「未配头像 → 页脚守字圆点」）；
# - 中文名 = 调用方传入 ``bot_name``（缺省 ``BRAND_THEME.display_name``）；
# - 英文名 = ``theme_tokens.BRAND_NAME_EN``（新增品牌身份 token）；
# - 功能名 = 可选参数，空串时**整段省略**（不渲染空胶囊段、不显示占位文案）。
#
# 版式全部消费既有 token（无新造字面量）：圆角 var(--r-pill)/var(--r-circle)、
# 玻璃 var(--mica-glass-foot)+var(--mica-glass-edge)、阴影仅
# var(--mica-shadow-soft)（两枚 token 白名单内）、辉光 var(--glow-accent)
# 只作背景层（其色值 alpha≥0.05 由 GLOW_ACCENT 登记值保证）、gap 7px 与
# padding 取既有刻度、字号 12px 下限、字重 ≤700、line-height 1.2 在刻度内。
# 无动画（胶囊是静态署名件，动画元素禁令与其无涉）；文字只压白玻璃面，
# 中文名/圆点字用 --text-main、英文名/功能名用 --text-sub——两者对
# SURFACE_TINTS 三档表面的 ≥4.5:1 对比由既有 vis5 数值门背书。


def brand_capsule_css() -> str:
    """品牌胶囊组件 CSS（单一产出；经 bridge 注入或直拼卡拼入 ``<style>``）。"""
    return (
        "/* 品牌胶囊（CAP1 单一来源=mica_shell）：头像+中文名+英文名+可选功能名。 */\n"
        ".mica-capsule { display:inline-flex; align-items:center; gap:7px;\n"
        "  padding:7px 12px; border-radius:var(--r-pill); border:1px solid transparent;\n"
        "  background:\n"
        "    var(--glow-accent) right center / 62% 190% no-repeat,\n"
        f"    {GLASS_FOOT},\n"
        f"    {GLASS_EDGE};\n"
        "  box-shadow:var(--mica-shadow-soft);\n"
        "  font-size:12px; line-height:1.2; color:var(--text-sub); }\n"
        ".mica-capsule .mc-avatar { width:22px; height:22px; flex-shrink:0;\n"
        "  border-radius:var(--r-circle); object-fit:cover;\n"
        "  border:1px solid #fff; box-shadow:var(--mica-shadow-soft); }\n"
        ".mica-capsule .mc-dot { width:22px; height:22px; flex-shrink:0;\n"
        "  border-radius:var(--r-circle); display:inline-flex; align-items:center;\n"
        "  justify-content:center; font-size:12px; font-weight:650;\n"
        "  color:var(--text-main); background:color-mix(in srgb, var(--accent) 14%, #fff); }\n"
        ".mica-capsule .mc-name { font-size:13px; font-weight:700;\n"
        "  color:var(--text-main); white-space:nowrap; }\n"
        ".mica-capsule .mc-en { color:var(--text-sub); white-space:nowrap;\n"
        "  letter-spacing:0.02em; }\n"
        ".mica-capsule .mc-feature { color:var(--text-sub); white-space:nowrap; }"
    )


def brand_capsule_html(
    *,
    bot_name: str = "",
    bot_name_en: str = "",
    avatar_url: str = "",
    feature_label: str = "",
    extra_class: str = "",
) -> str:
    """品牌胶囊 DOM 片段（头像 → 中文名 → 英文名 → 可选「· 功能名」）。

    - 全部动态文本 ``html.escape``（quotes=True，属性位与文本位同一把锁）；
      ``avatar_url`` 既有卡面直进 ``src=""`` 属性（能力侧给 file/data URI），
      此处同样 escape 防属性逃逸。
    - 头像缺失 → ``mc-dot`` 首字圆点（中文名首字；中文名为空回落品牌名
      首字「守」），整枚胶囊照常在场，不塌陷。
    - ``feature_label`` 为空 → 功能名段整段省略（铁律：无能力语境不渲染
      空胶囊段、不显示「未命名」占位）。
    - ``extra_class`` 仅供卡面**摆位**微调类（如直拼卡内联 margin 宿主），
      不得用于复制组件样式本体。
    """
    name = (bot_name or BRAND_THEME.display_name).strip() or BRAND_THEME.display_name
    name_en = (bot_name_en or BRAND_NAME_EN).strip() or BRAND_NAME_EN
    avatar = (avatar_url or "").strip()
    feature = (feature_label or "").strip()
    head = (
        f'<img class="mc-avatar" src="{_html.escape(avatar)}" alt="" '
        "onerror=\"this.style.display='none'\"/>"
        if avatar
        else f'<span class="mc-dot">{_html.escape(name[:1] or name_en[:1])}</span>'
    )
    parts = [head, f'<span class="mc-name">{_html.escape(name)}</span>']
    if name_en:
        parts.append(f'<span class="mc-en">{_html.escape(name_en)}</span>')
    if feature:
        parts.append(f'<span class="mc-feature">· {_html.escape(feature)}</span>')
    cls = "mica-capsule" + (f" {extra_class}" if extra_class else "")
    return f'<div class="{cls}">' + "".join(parts) + "</div>"


# 缺省实例：CSS 单份（内容只依赖登记 token，全卡同文共享）。
BRAND_CAPSULE_CSS = brand_capsule_css()


def render_root_tokens(
    *,
    accent: str,
    accent_dark: str,
    phase: float | str = 0.2,
    wash: Mapping[str, str] | None = None,
    extras: Mapping[str, str] | None = None,
    wash_blob_mix: int = 35,
    include_phase: bool = True,
    include_wash: bool = True,
) -> str:
    """产出统一的 ``:root`` 变量块（不含花括号，供调用方包进 ``:root { ... }``）。

    固定段（顺序固定、冒号后无空格、全卡一致）：
    ``--phase`` / ``--accent`` / ``--accent-dark`` /
    ``--wash-1..3`` / ``--wash-mist`` / ``--wash-blob-1`` / 公共 token 三十项
    （原十项 + 2026-09-18 CORE 值册廿项：玻璃两档+描边/遮罩四员/语义五色/
    等宽字体/内径刻度五档+pill+圆，值全部出自 theme_tokens 单一登记）。

    ``extras`` 追加卡特有 token（如 ``--good``/``--bad``、vis4 六键、
    ``--accent-rgb``），按传入顺序追加在末尾，保持各卡自有的扩展面。

    ``wash_blob_mix`` 是 ``--wash-blob-1`` 里 ``--accent`` 的混入百分比，
    默认 35（四张直拼卡与 7 张模板中的六张一致）；``error_card`` 历史值为
    24，经此参数保留原值（**视觉不变**是本次重构的硬约束）。

    ``include_phase`` / ``include_wash`` 供 ``universal_card`` 的**基础块**使用：
    该模板有两个 ``:root``（基础块 + 视频卡区块块），而
    ``tests/test_phase_determinism*.py`` 的 ``_single_phase()`` 断言全页
    **恰好一处** ``--phase`` 声明——基础块必须关掉 phase，否则两处声明直接判红。
    基础块的 wash 同理关掉：两个 ``:root`` 都是全局选择器，wash 由视频卡块
    提供（同值），基础块重复声明只是噪音。

    命名注记（2026-09-18 用户裁定「统一成 dark」）：本 token 此前在 f-string
    直拼卡侧叫 ``--accent-ink``、在 7 张模板侧叫 ``--accent-dark``，**同一语义
    两个名字**（都是「深一档主色」，算法同为 ``_darken``）。裁定统一到
    ``--accent-dark``——模板侧 36 处引用零改动，直拼卡侧 14 处 CSS 引用随本次
    改名，`--accent-ink` 全仓退役。

    历史注记（2026-09-18 用户裁定）：``--pc`` 家族（``--pc``/``--pc-dark``/
    ``--pc-light``/``--pc-mid``/``--pc-rgb``）**已彻底退役**，全仓统一为
    ``--accent`` 家族。此前 media 卡只认 ``--pc``、其余卡只认 ``--accent``，
    是两套渲染机制唯一的 token 分叉点；退役后不再存在别名双写。
    """
    parts: list[str] = []
    if include_phase:
        parts.append(f"--phase:{phase}")
    parts.append(f"--accent:{accent}")
    parts.append(f"--accent-dark:{accent_dark}")
    if include_wash:
        if not wash:
            raise ValueError("include_wash=True 时必须提供 wash 映射")
        parts.extend(
            [
                f"--wash-1:{wash['wash_1']}",
                f"--wash-2:{wash['wash_2']}",
                f"--wash-3:{wash['wash_3']}",
                f"--wash-mist:{wash['wash_mist']}",
                f"--wash-blob-1:color-mix(in srgb, var(--accent) {int(wash_blob_mix)}%, var(--wash-1))",
            ]
        )
    public_values: dict[str, str] = {
        "--text-main": BRAND_THEME.text_main,
        "--text-sub": BRAND_THEME.text_sub,
        "--ink": "var(--text-main)",
        "--muted": "var(--text-sub)",
        "--font-family": FONT_FAMILY_STACK,
        "--font-mono": MONO_FONT_STACK,
        "--r-shell": f"{BRAND_THEME.shell_radius}px",
        "--r-panel": f"{BRAND_THEME.panel_radius}px",
        "--r-tile": f"{BRAND_THEME.tile_radius}px",
        **RADIUS_INNER_CSS_VARS,
        "--mica-shadow": SHADOW_PRIMARY,
        "--mica-shadow-soft": SHADOW_SECONDARY,
        "--mica-glass-main": GLASS_MAIN,
        "--mica-glass-foot": GLASS_FOOT,
        "--mica-glass-edge": GLASS_EDGE,
        "--mica-scrim-badge": OVERLAY_SCRIMS["scrim_badge"],
        "--mica-scrim-banner": OVERLAY_SCRIMS["scrim_banner"],
        "--mica-scrim-code": OVERLAY_SCRIMS["scrim_code"],
        "--mica-scrim-media": OVERLAY_SCRIMS["scrim_media"],
        "--semantic-danger": SEMANTIC_DANGER,
        "--semantic-success": SEMANTIC_SUCCESS,
        "--semantic-warning": SEMANTIC_WARNING,
        "--score-hot": SCORE_HOT,
        "--score-cold": SCORE_COLD,
    }
    for token in _PUBLIC_TOKEN_ORDER:
        parts.append(f"{token}:{public_values[token]}")
    for token, value in (extras or {}).items():
        parts.append(f"{token}:{value}")
    return f"{_TOKENS_COMMENT} " + "; ".join(parts) + ";"


def shell_base_css(
    shell_class: str,
    *,
    width_px: int = _DEFAULT_SHELL_WIDTH_PX,
    glass: bool = True,
) -> str:
    """视觉外壳的完整公共段（雾底打底 + wash 对角透色 + 1px 内高光描边 + 单枚阴影
    + 可选液态玻璃两档规则）。

    四张直拼卡此前逐字各写一份，只有**类名与宽度**不同——故此处参数化这两项，
    其余规则单一来源。``glass=True``（缺省）追加 ``.glass``/``.glass-foot``
    两档玻璃规则（值出自 theme_tokens.GLASS_*，C3）——单独消费本函数的卡
    （不经 ``render_shell`` 装配 decor 段）也能拿到完整公共段；
    ``glass=False`` 供 ``render_shell`` 使用（玻璃规则由 decor 段统一携带，
    避免同一规则定义两次）。``shell_class`` 为空串时返回空串（无外壳层的卡）。
    """
    if not shell_class:
        return ""
    rules = f""".{shell_class} {{ position:relative; width:{int(width_px)}px; overflow:hidden;
  border-radius:var(--r-shell); border:1px solid transparent;
  background:linear-gradient(145deg, var(--wash-mist) 0%, color-mix(in srgb, var(--wash-1) 55%, var(--wash-mist)) 30%,
    color-mix(in srgb, var(--wash-2) 48%, var(--wash-mist)) 64%, color-mix(in srgb, var(--wash-3) 40%, var(--wash-mist)) 100%) padding-box,
    linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box;
  box-shadow:var(--mica-shadow); }}
.{shell_class} > :not(.drift-blobs) {{ position:relative; z-index:1; }}"""
    if glass:
        rules += "\n" + _GLASS_RULES_CSS
    return rules


def render_shell(
    *,
    title: str,
    tokens: str,
    css: str,
    body_html: str,
    stage_class: str = "",
    shell_class: str = "",
    shell_width_px: int = _DEFAULT_SHELL_WIDTH_PX,
    decor: bool = True,
    capsule_html: str = "",
) -> str:
    """产出完整卡片文档：``<!doctype html>`` + 透明 body + 外层纯容器 + 可选视觉外壳。

    结构与四张直拼卡实测结构对齐（**双层**）：外层 ``.card`` 是纯容器
    （透明、无圆角、无阴影，``width:fit-content``），视觉外壳在内层
    ``.{shell_class}``；``stage_class`` 为外层附加类（如 ``help-stage``）。
    ``shell_class`` 为空串时退化为单层（``body_html`` 直接挂在外层）。

    铁律内建：不写 ``<meta viewport>``；``body`` 透明；外层根元素带 ``card`` 类；
    阴影只经 ``--mica-shadow`` / ``--mica-shadow-soft`` 两枚 token；
    ``decor=True`` 时注入统一的漂移装饰层与 ``.glass`` 规则。
    ``title`` 仅用于 ``<title>`` 与可访问性，不参与视觉。

    ``capsule_html``（CAP1 接入点）：非空时把 ``brand_capsule_html`` 产出的
    品牌胶囊拼进视觉外壳尾部，并自动附带 ``BRAND_CAPSULE_CSS``——新直拼卡
    接胶囊只传片段，不再手写第二份样式。
    """
    classes = f"card {stage_class}".strip()
    # 玻璃规则随 decor 段携带（decor=False 时整卡无玻璃，铁律开关语义不变）；
    # shell_base_css 的 glass 段在此关闭，避免同一规则定义两次。
    shell_css = shell_base_css(shell_class, width_px=shell_width_px, glass=False)
    decor_css = _MICA_DECOR_CSS + _GLASS_RULES_CSS if decor else ""
    if capsule_html:
        # 胶囊样式与装饰层同段携带（CAP1）：调用方零样式改动即得统一胶囊。
        decor_css = f"{decor_css}\n{BRAND_CAPSULE_CSS}" if decor_css else BRAND_CAPSULE_CSS
    shell_open = f'<section class="{shell_class}">' if shell_class else ""
    shell_close = "</section>" if shell_class else ""
    return (
        "<!doctype html>\n"
        '<html><head><meta charset="utf-8">'
        f"<title>{title}</title><style>\n"
        f":root {{ {tokens} }}\n"
        "* { box-sizing:border-box; }\n"
        "body { margin:0; padding:0; font-family:var(--font-family); background:transparent; "
        "color:var(--ink); display:flex; align-items:flex-start; justify-content:center; "
        "-webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }\n"
        ".card { width:fit-content; margin:0; padding:0; background:transparent; "
        "border:0; border-radius:0; box-shadow:none; }\n"
        f"{shell_css}\n"
        f"{decor_css}\n"
        f"{css}\n"
        "</style></head>\n"
        f'<body><div class="{classes}">{shell_open}{body_html}{capsule_html}{shell_close}</div></body></html>'
    )


__all__ = [
    "BRAND_CAPSULE_CSS",
    "DRIFT_BLOBS_HTML",
    "brand_capsule_css",
    "brand_capsule_html",
    "drift_blobs_html",
    "glass_rules_css",
    "mica_decor_css",
    "render_root_tokens",
    "render_shell",
    "shell_base_css",
]
