"""统一卡片主题契约（C 方向 UI 统一，2026-09-12）。

卡片视觉 token 的**单一事实来源**：守岸人品牌主题（BRAND_THEME）、平台受控
变体（PLATFORM_THEMES，仅收录代码中真实存在的平台 identifier）、以及未知
平台安全兜底（DEFAULT_THEME）。

设计裁定（与 mica-glass v2 一脉相承）：
- 守岸人本命（淡蓝/白/偏深蓝/少量星空紫）是唯一基底；平台品牌色只允许
  落在 ``accent``/``accent_dark``/``accent_light``（徽章/高亮）与 wash-1
  ≤±30° 的轻推两层，永远不覆盖整体品牌。
- 布局/字体/阴影/文本 token 全平台统一（继承品牌值），平台不可改写——
  「统一宽度、间隔、字体和阴影」由本模块强制，模板不得出现表外值。
- steam/epic 在代码中有平台 identifier（见 bridge._RAW_METRIC_PLATFORMS）
  但无登记品牌色 → 按契约落入 DEFAULT_THEME 中性灰，不臆造调用路径。

所有「K」语境说明：本模块只管主题 token；数据层的 K 一律指 K 线（烛台
OHLCV），见 contracts/finance.py 的 docstring。
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field

# ==================== 品牌常量（守岸人本命） ====================
# 色相锚点与 bridge mica-glass v2 完全一致：wash-1 淡蓝 210°、wash-2 星空紫
# 265°、wash-3 深蓝 228°、mist 雾底 214°。品牌 accent 取本命淡蓝 hsl(210,65%,55%)。
BRAND_ACCENT = "#318ce7"
UNKNOWN_PLATFORM_COLOR = "#607080"

_WASH_HUE_SHIFT = 30 / 360      # 平台色相对本命相的最大推幅
_WASH_HUE_PULL = 0.5            # 平台色相 → 推幅的比例（本命相权重 3:1）
_WASH_SAT_RATIO = 0.55          # pastel 化：输入饱和度保留比例
_WASH_LIGHT = 0.88              # 洗色明度
_WASH_MIST_LIGHT = 0.96         # 雾底明度 ≥94%
_WASH_BASE_HUE = 210 / 360      # 守岸人淡蓝本命相
_WASH_PURPLE_HUE = 265 / 360    # 星空紫
_WASH_DEEP_HUE = 228 / 360      # 深蓝
_WASH_MIST_HUE = 214 / 360      # 雾底淡蓝相
_WASH_BASE_SAT = 0.42           # 本命洗基准饱和度（×0.55 后为柔和 pastel）
_WASH_GRAY_THRESHOLD = 0.10     # S 低于此值视为无有效色相的灰阶（推力归零）

FONT_FAMILY_STACK = (
    '"Segoe UI", "Microsoft YaHei", "PingFang SC", -apple-system, '
    "BlinkMacSystemFont, Roboto, sans-serif"
)
# 两枚阴影 token（外壳投影 + 元素柔光），加一枚 --pc 派生内高光：
# 除语义 none 外，模板 box-shadow 只允许 var() 引用这些 token（契约测试锁定）。
SHADOW_PRIMARY = (
    "0 12px 32px color-mix(in srgb, var(--wash-2) 26%, transparent), "
    "0 3px 10px rgba(0, 0, 0, 0.05)"
)
SHADOW_SECONDARY = "0 3px 10px rgba(31, 35, 41, 0.06)"


# ==================== 渲染契约常量（契约测试锁定，2026-09-12） ====================
# 语义化策略常量：所有模板禁止 <meta viewport>（playwright viewport 由
# render_backends 的 new_page viewport 参数控制，meta 只在移动仿真下生效）。
META_VIEWPORT_POLICY = "forbidden"
# 字重上限（AGENTS.md UI 铁律）；与 ThemeTokens.font_weight_max 默认值一致。
FONT_WEIGHT_MAX = 700
# 审计过的间距刻度（px）：模板 gap 只允许取本刻度内的值，
# 防止各内容模块私自发明间距（契约测试锁定）。
GAP_SCALE_PX = frozenset({3, 4, 6, 7, 8, 10, 12, 14, 16})
# 平台页脚展示名（渲染页脚「平台 · 功能」段用）；未登记的平台回退官方名。
PLATFORM_FOOTER_LABELS: dict[str, str] = {
    "bilibili": "哔哩哔哩",
    "xiaohongshu": "小红书",
    "xhs": "小红书",
    "douyin": "抖音",
    "weibo": "微博",
    "youtube": "YouTube",
    "twitter": "Twitter/X",
    "x": "Twitter/X",
    "pixiv": "Pixiv",
    "lofter": "LOFTER",
    "spotify": "Spotify",
    "apple_music": "Apple Music",
    "facebook": "Facebook",
    "instagram": "Instagram",
}

# 卡片外壳宽度登记表：宽度按内容族分化，但任何模板宽度必须出自本表
# （契约测试锁定），禁止模板私有宽度。
CARD_SHELL_WIDTHS: dict[str, int] = {
    "universal": 1440,   # 通用解析卡（宽版双栏）
    "affinity": 1180,    # 好感度卡
    "market": 1080,      # 全球股指卡
    "finance": 1080,     # 股票/汇率金融卡
    "song_panel": 980,   # 点歌候选面板（透明壳内层）
    "mermaid_max": 840,  # mermaid 卡 fit-content 上限
}


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = (color or "").lstrip("#")
    if len(color) != 6:
        return (96, 112, 128)
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (96, 112, 128)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _darken_hex(color: str) -> str:
    return _rgb_to_hex(
        tuple(max(0, min(255, int(c * 0.8))) for c in _hex_to_rgb(color))  # type: ignore[arg-type]
    )


def _lighten_hex(color: str) -> str:
    return _rgb_to_hex(
        tuple(int(c + (255 - c) * 0.12) for c in _hex_to_rgb(color))  # type: ignore[arg-type]
    )


def derive_wash_tokens(hex_color: str) -> dict[str, str]:
    """守岸人本命釉瑚云母洗四 token（wash_1/2/3/mist，#RRGGBB）。

    纯函数不抛异常：非法值经 _hex_to_rgb 回退中性灰（无有效色相，
    推力归零 → 纯本命洗）。平台色仅在有效色相时把 wash-1 淡蓝往
    平台相轻推（≤±30°，比例 0.5），保证基底永远是守岸人渐变。
    """
    red, green, blue = _hex_to_rgb(hex_color)
    hue, _lightness, sat = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    base_hue = _WASH_BASE_HUE
    if sat >= _WASH_GRAY_THRESHOLD:
        delta = ((hue - base_hue + 0.5) % 1.0) - 0.5
        shift = max(-_WASH_HUE_SHIFT, min(_WASH_HUE_SHIFT, delta * _WASH_HUE_PULL))
        base_hue = (base_hue + shift) % 1.0

    def _wash(hue_: float, sat_in: float, light: float) -> str:
        sat = sat_in * _WASH_SAT_RATIO
        r, g, b = colorsys.hls_to_rgb(hue_ % 1.0, light, min(sat, 0.60))
        return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"

    return {
        "wash_1": _wash(base_hue, _WASH_BASE_SAT, _WASH_LIGHT),
        "wash_2": _wash(_WASH_PURPLE_HUE, 0.40, _WASH_LIGHT),
        "wash_3": _wash(_WASH_DEEP_HUE, 0.45, _WASH_LIGHT + 0.01),
        "wash_mist": _wash(_WASH_MIST_HUE, 0.20, _WASH_MIST_LIGHT),
    }


# 未知平台（中性灰）的本命洗四 token——纯守岸人基底（推力为零），
# 模板 --wash-* 注入点的 default 字面量必须与本表逐键一致（契约测试锁定）。
DEFAULT_WASH_TOKENS = derive_wash_tokens(UNKNOWN_PLATFORM_COLOR)

# ==================== 层次化阴影 + 辉光 + 表面/分隔线/字号（vis4）====================
# 用户裁定升级：所有元素都要有层次阴影区分 + 辉光 + 清晰区分线；相邻色块
# 颜色不得过于相似。全部 token 化钉在本模块——模板只允许 var()/常量引用，
# 契约测试锁定；改这里=全部模板自动生效（牵一发自动全改的根）。
# （本段必须在 derive_wash_tokens 定义之后：三档表面用 BRAND_ACCENT 纯本命洗
# 派生固定 hex——用户裁定 2026-09-13：表面 zebra 只用守岸人本命三色
# （淡蓝/星空蓝/星空紫），不用平台 accent，任何平台卡上都保持本命三色。）
SHADOW_LEVELS: dict[str, str] = {
    # L3 外壳：深投影 + wash 染色（原 SHADOW_PRIMARY，兼容名保留）。
    "elev_shell": SHADOW_PRIMARY,
    # L2 面板级：摘要块/页脚胶囊等大件内件——比瓦片深一档，层次可辨。
    "elev_panel": (
        "0 8px 22px color-mix(in srgb, var(--wash-2) 18%, transparent), "
        "0 2px 6px rgba(31, 35, 41, 0.05)"
    ),
    # L1 瓦片级：指标小卡/评论条等小件（原 SHADOW_SECONDARY，兼容名保留）。
    "elev_tile": SHADOW_SECONDARY,
}
# 模板侧阴影 CSS 变量 → token 值的唯一登记处。契约/视觉审计测试从本表动态
# 派生白名单：新增档位先在这里入册（并补 :root 注入点），族外一次性阴影
# 一票否决——只开正门，不留后门。
SHADOW_CSS_VARS: dict[str, str] = {
    "--mica-shadow": SHADOW_LEVELS["elev_shell"],
    "--mica-shadow-soft": SHADOW_LEVELS["elev_tile"],
    "--mica-shadow-panel": SHADOW_LEVELS["elev_panel"],
}
# 辉光 token：作背景层（radial 光晕），不是 box-shadow——不与阴影 token 冲突。
GLOW_ACCENT = (
    "radial-gradient(closest-side, "
    "color-mix(in srgb, var(--pc) 20%, transparent) 0%, "
    "color-mix(in srgb, var(--pc) 8%, transparent) 46%, transparent 74%)"
)
_BRAND_WASH = derive_wash_tokens(BRAND_ACCENT)
# vis5 收官（2026-09-13 用户裁定「区分度拉高」）：三档表面按相邻可辨调参——
# 对称合成 alpha≈0.83（液态玻璃质感与色斑透出保留）， onstage 混色（叠本命
# wash 渐变中部）ΔE(a,b)≈3.8、对 neutral ≥7，text_sub 对比 ≥5:1。
# 机器门：tests/test_template_visual_audit.py::test_zebra_surfaces_distinct。
SURFACE_TINTS: dict[str, str] = {
    "tint_a": (
        f"color-mix(in srgb, {_BRAND_WASH['wash_1']} 75%, rgba(255, 255, 255, 0.35))"
    ),
    "tint_b": (
        f"color-mix(in srgb, {_BRAND_WASH['wash_2']} 80%, rgba(255, 255, 255, 0.20))"
    ),
    "tint_neutral": "rgba(255, 255, 255, 0.92)",
}
# 次级文字统一灰（vis5）：全模板 --text-secondary 单一来源，取值在本批三档
# 表面（含最暗 tint_b）上对比 ≥4.5:1（WCAG AA@12px）。旧散值 #7a828c/#8a919b/
# #66727f/#7a8699 对比 2.8-4.8 不达 AA，全部收编。
TEXT_SECONDARY = "#576272"
# 区分线 token：清晰可见的平台色 22% 细线（替代旧 14% 淡线）。
DIVIDER = "1px solid color-mix(in srgb, var(--pc) 22%, rgba(255, 255, 255, 0.65))"
# 字号阶梯（px）：全模板字号只允许取本表值（契约测试锁定），小件下限 12。
TYPE_SCALE_PX: dict[str, int] = {
    "display": 26,
    "title": 20,
    "body": 15,
    "label": 13,
    "caption": 12,
}


# ==================== 主题 token 结构 ====================
@dataclass(frozen=True)
class ThemeTokens:
    """一张卡片壳的全部主题 token；平台只能差异 accent/wash 两层。"""

    key: str
    display_name: str
    accent: str                       # #RRGGBB 品牌主 accent
    accent_dark: str = ""
    accent_light: str = ""
    wash_1: str = ""
    wash_2: str = ""
    wash_3: str = ""
    wash_mist: str = ""
    # —— 以下布局/排版/阴影 token 全主题统一，平台不可改写 ——
    shell_width: int = 1080
    shell_radius: int = 30            # --r-shell
    tile_radius: int = 14             # --r-tile
    panel_radius: int = 18            # --r-panel
    page_gap: int = 16
    section_gap: int = 10
    card_padding: int = 28
    font_family: str = FONT_FAMILY_STACK
    font_weight_max: int = 700
    shadow_primary: str = SHADOW_PRIMARY
    shadow_secondary: str = SHADOW_SECONDARY
    text_main: str = "#18191c"
    text_sub: str = "#5b6069"
    aliases: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        # accent 派生色与云母洗在构造时补齐（frozen 下用 object.__setattr__）。
        if not self.accent_dark:
            object.__setattr__(self, "accent_dark", _darken_hex(self.accent))
        if not self.accent_light:
            object.__setattr__(self, "accent_light", _lighten_hex(self.accent))
        wash = derive_wash_tokens(self.accent)
        for key, value in wash.items():
            if not getattr(self, key):
                object.__setattr__(self, key, value)


def _make_theme(
    key: str,
    display_name: str,
    accent: str,
    *,
    aliases: tuple[str, ...] = (),
    **overrides: int | str,
) -> ThemeTokens:
    return ThemeTokens(
        key=key, display_name=display_name, accent=accent, aliases=aliases, **overrides  # type: ignore[arg-type]
    )


# ==================== 守岸人品牌主题 ====================
BRAND_THEME = _make_theme("brand", "守岸人", BRAND_ACCENT)

# ==================== 未知平台安全兜底 ====================
# 中性灰 accent 无有效色相 → 云母洗推力归零，呈现纯本命洗（与 v2 裁定一致）。
DEFAULT_THEME = _make_theme("default", "通用", UNKNOWN_PLATFORM_COLOR)

# ==================== 平台受控变体 ====================
# 仅收录代码中真实存在的平台 identifier；accent = 现行 PLATFORM_COLORS 品牌色
# （保持逐字节一致，渲染零变化）。steam/epic 有 identifier 无登记色 → 不在此
# 表臆造，get_platform_theme 落 DEFAULT_THEME。
_PLATFORM_ACCENTS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    # key, 展示名, accent, 别名
    ("bilibili", "Bilibili", "#fb7299", ()),
    ("xiaohongshu", "Xiaohongshu", "#ff2442", ("xhs",)),
    ("douyin", "Douyin", "#111111", ()),
    ("weibo", "Weibo", "#e6162d", ()),
    ("youtube", "YouTube", "#ff0000", ()),
    ("twitter", "Twitter/X", "#1d9bf0", ("x",)),
    ("pixiv", "Pixiv", "#0096fa", ()),
    ("lofter", "LOFTER", "#3fa1ad", ()),
    ("allcpp", "AllCPP", "#2f6bff", ("cpp",)),
    ("netease", "NetEase Cloud Music", "#c20c0c", ("ncm", "netease_music")),
    ("qqmusic", "QQ Music", "#00c853", ("qq_music",)),
    ("kugou", "KuGou Music", "#ff5722", ()),
    ("kuwo", "Kuwo Music", "#ff6f00", ()),
    ("apple_music", "Apple Music", "#fa243c", ()),
    ("spotify", "Spotify", "#1db954", ()),
    ("facebook", "Facebook", "#1877f2", ()),
    ("instagram", "Instagram", "#d62976", ()),
)

PLATFORM_THEMES: dict[str, ThemeTokens] = {
    key: _make_theme(key, display, accent, aliases=aliases)
    for key, display, accent, aliases in _PLATFORM_ACCENTS
}

# 别名 → 主题 key（get_platform_theme 的第二跳）。
THEME_ALIASES: dict[str, str] = {
    alias: key
    for key, theme in PLATFORM_THEMES.items()
    for alias in theme.aliases
}

# 代码中存在 identifier 但未登记品牌色的平台（安全兜底，记录不臆造）。
UNKNOWN_THEME_KEYS: tuple[str, ...] = ("steam", "epic")


def get_platform_theme(platform: str) -> ThemeTokens:
    """平台 identifier → 主题 token；未知平台安全兜底 DEFAULT_THEME。"""
    key = (platform or "").strip().lower()
    theme = PLATFORM_THEMES.get(key)
    if theme is not None:
        return theme
    alias = THEME_ALIASES.get(key)
    if alias is not None:
        return PLATFORM_THEMES[alias]
    return DEFAULT_THEME


def platform_accent(platform: str) -> str:
    """平台 identifier → 品牌 accent（未知回中性灰）。"""
    return get_platform_theme(platform).accent


def theme_to_css_vars(theme: ThemeTokens) -> dict[str, str]:
    """主题 token → CSS 变量字典（金融卡等新模板直接消费）。"""
    return {
        "--pc": theme.accent,
        "--pc-dark": theme.accent_dark,
        "--pc-light": theme.accent_light,
        "--wash-1": theme.wash_1,
        "--wash-2": theme.wash_2,
        "--wash-3": theme.wash_3,
        "--wash-mist": theme.wash_mist,
        "--r-shell": f"{theme.shell_radius}px",
        "--r-panel": f"{theme.panel_radius}px",
        "--r-tile": f"{theme.tile_radius}px",
        "--page-gap": f"{theme.page_gap}px",
        "--section-gap": f"{theme.section_gap}px",
        "--card-padding": f"{theme.card_padding}px",
        "--font-family": theme.font_family,
        "--shadow-card": theme.shadow_primary,
        "--shadow-soft": theme.shadow_secondary,
        # vis4 层次化阴影/辉光/表面/分隔线（值出自本模块常量，非平台可写层）。
        "--shadow-elev-panel": SHADOW_LEVELS["elev_panel"],
        "--glow-accent": GLOW_ACCENT,
        "--divider": DIVIDER,
        "--surface-a": SURFACE_TINTS["tint_a"],
        "--surface-b": SURFACE_TINTS["tint_b"],
        "--surface-neutral": SURFACE_TINTS["tint_neutral"],
        "--text-main": theme.text_main,
        "--text-sub": theme.text_sub,
    }


# 平台官方展示名（渲染页脚/徽章用；与旧 bridge 字面量逐键一致）。
PLATFORM_OFFICIAL_NAMES: dict[str, str] = {
    key: theme.display_name for key, theme in PLATFORM_THEMES.items()
}
PLATFORM_OFFICIAL_NAMES.setdefault("generic", "Web")

__all__ = [
    "BRAND_ACCENT",
    "BRAND_THEME",
    "CARD_SHELL_WIDTHS",
    "DEFAULT_THEME",
    "DEFAULT_WASH_TOKENS",
    "FONT_WEIGHT_MAX",
    "GAP_SCALE_PX",
    "META_VIEWPORT_POLICY",
    "PLATFORM_FOOTER_LABELS",
    "PLATFORM_OFFICIAL_NAMES",
    "PLATFORM_THEMES",
    "SHADOW_PRIMARY",
    "SHADOW_SECONDARY",
    "SURFACE_TINTS",
    "TEXT_SECONDARY",
    "THEME_ALIASES",
    "UNKNOWN_PLATFORM_COLOR",
    "UNKNOWN_THEME_KEYS",
    "ThemeTokens",
    "derive_wash_tokens",
    "get_platform_theme",
    "platform_accent",
    "theme_to_css_vars",
]
