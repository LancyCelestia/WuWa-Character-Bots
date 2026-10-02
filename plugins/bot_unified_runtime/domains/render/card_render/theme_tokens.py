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
from dataclasses import dataclass, field, replace

# ==================== 品牌常量（守岸人本命） ====================
# 色相锚点与 bridge mica-glass v2 完全一致：wash-1 淡蓝 210°、wash-2 星空紫
# 265°、wash-3 深蓝 228°、mist 雾底 214°。品牌 accent 取本命淡蓝 hsl(210,65%,55%)。
BRAND_ACCENT = "#318ce7"
UNKNOWN_PLATFORM_COLOR = "#607080"

# 品牌英文名（CAP1 胶囊组件 2026-09-20）：卡片品牌胶囊
# 「头像 + 中文名 + 英文名（可选功能名）」的英文名唯一来源。
# 事实出处 = personas/shorekeeper/identity.md 硬档案「外文名：英 The Shorekeeper」
# （人格语料只读，渲染层不在运行期解析人格文件——耦合 IO 且措辞会变）；
# 卡面沿用既有口径省 "The" 前缀（historical: templates.py/ universal_card.html
# 页脚已有 "Shorekeeper" 用法，本次收敛为单一常量，各面不再各写字面量）。
# 中文名同源 = BRAND_THEME.display_name（「守岸人」，见下方品牌主题节）。
# 为什么住 theme_tokens 而不是 config.py：bot_persona_display_name 是实例
# 可配的面貌字段（缺省 "报存"，语义=中文名）；英文名是当前品牌的固定
# 身份 token，与 BRAND_ACCENT/BRAND_THEME 同区登记，由 mica_shell/bridge/
# templates 三条消费链共同 import，天然满足「单一事实来源」。
BRAND_NAME_EN = "Shorekeeper"


def brand_name_en_for(persona_id: str) -> str:
    """按**当前生效人格**派生卡面英文署名（2026-09-28 用户裁定：卡面身份跟人格外壳走）。

    英文署名此前无人格源（全仓只有上面那枚常量）。人格册的 ``persona_id`` 本身就是
    拉丁 slug（``shorekeeper`` / ``danya``），首字母大写即得正确署名——零新配置键、
    零改册形态。拿不出可用 slug（空、``default``、含非 ASCII）时回落品牌常量，
    **绝不渲染空署名段**（胶囊侧的省略逻辑只管功能名，英文名不许空）。
    """
    slug = str(persona_id or "").strip()
    if not slug or slug.lower() == "default":
        return BRAND_NAME_EN
    skeleton = slug.replace("_", "").replace("-", "").replace(" ", "")
    if not skeleton.isascii() or not skeleton.isalnum():
        return BRAND_NAME_EN
    return slug.replace("_", " ").replace("-", " ").title()

def brand_display_name_for(persona_id: str = "") -> str:
    """按**当前生效人格**派生卡面中文署名（S5 多人格隔离波 单元 1）。

    与 :func:`brand_name_en_for` 同一形态、同一条裁定（卡面身份跟人格外壳走），
    中文腿此前没有人格源：``BRAND_THEME.display_name`` 是渲染契约钉住的品牌缺省
    （改它的**值**会动三族契约门的哈希册），所以这里加的是"按格取值"的读法，
    品牌缺省只在册里查不到这一格时兜底——绝不反过来让人格名写死在代码里。

    取法＝人格册热读（``(mtime,size)`` 签名，改册即生效，不重启）；拿不到人格册
    或该格无 display_name ⇒ 回落 ``BRAND_THEME.display_name``，**绝不渲染空署名**。
    渲染层不在运行期解析人格**正文**（本模块裁定：耦合 IO 且措辞会变）——这里只读
    注册表那一枚 JSON 的一个字段，与"解析语料"不同事，见 persona_profile 的裁定。
    """
    wanted = str(persona_id or "").strip()
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character.persona_profile import (
            get_shared_registry,
            resolve_persona_id,
        )

        registry_persona = resolve_persona_id(None, wanted)
        if registry_persona:
            record = get_shared_registry().get(registry_persona)
            name = str(getattr(record, "display_name", "") or "").strip()
            if name:
                return name
    except Exception:  # noqa: S110, BLE001 - 册读不出来不等于卡不能画
        pass
    return BRAND_THEME.display_name


def brand_theme_for(persona_id: str = "") -> ThemeTokens:
    """品牌主题按人格换**署名**，配色一律不换（守岸人本命蓝是产品视觉基线）。

    返回与 ``BRAND_THEME`` 同 token、仅 ``display_name`` 随格的副本；生效人格就是
    主人格时**返回 BRAND_THEME 本体**（``is`` 同一枚），这样既有按对象身份比对的
    渲染锁与哈希册逐字节不变。
    """
    name = brand_display_name_for(persona_id)
    if name == BRAND_THEME.display_name:
        return BRAND_THEME
    return replace(BRAND_THEME, display_name=name)


_WASH_HUE_SHIFT = 30 / 360      # 平台色相对本命相的最大推幅
_WASH_HUE_PULL = 0.5            # 平台色相 → 推幅的比例（本命相权重 3:1）
# 2026-09-25 澜汐点名「背景现在是灰色的，要在守岸人蓝标志色上做釉瑚飘逸渐变」。
# 现算根因：守岸人蓝 #318ce7 的相**恰等于** _WASH_BASE_HUE(210°)，平台推力恒为 0，
# 而 pastel 保留比 0.55 + 明度 0.88 把四支洗色压到 S≈3–11% ⇒ 全卡壳底读起来就是灰。
# 所以动的是饱和度与明度（不是再新增一条渐变、更不是逐卡手抄色标）。
_WASH_SAT_RATIO = 0.72          # pastel 化：输入饱和度保留比例（原 0.55＝压成近灰）
_WASH_LIGHT = 0.852             # 洗色明度（原 0.88；降 0.028 换可见彩度）
_WASH_MIST_LIGHT = 0.96         # 雾底明度 ≥94%
_WASH_BASE_HUE = 210 / 360      # 守岸人淡蓝本命相
_WASH_PURPLE_HUE = 265 / 360    # 星空紫
_WASH_DEEP_HUE = 228 / 360      # 深蓝
_WASH_MIST_HUE = 214 / 360      # 雾底淡蓝相
_WASH_BASE_SAT = 0.55           # 本命洗基准饱和度（×0.72 后为淡彩，原 0.42×0.55）
_WASH_GRAY_THRESHOLD = 0.10     # S 低于此值视为无有效色相的灰阶（推力归零）

FONT_FAMILY_STACK = (
    '"Segoe UI", "Microsoft YaHei", "PingFang SC", -apple-system, '
    "BlinkMacSystemFont, Roboto, sans-serif"
)
# 两枚阴影 token（外壳投影 + 元素柔光），加一枚 --accent 派生内高光：
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
    "error": 1080,       # 运行异常诊断卡（error_card.html）
    "news_digest": 1080, # 新闻摘要卡（news_digest_card.html，B05 快讯域紧凑摘要）
    # v21r3 统一收尾波（C10 裁决）：四处直拼卡宽度入册（此前是卡内私有
    # 字面量，与值册脱钩；值与现行卡面逐字节一致，接入由直拼卡席执行）。
    "help": 940,         # 帮助手册卡（echo 直拼卡 .help-shell）
    "usage": 900,        # 模型用量/账单卡（usage_cards .shell）
    "debug": 880,        # LLM 接入检查卡（debug .setup-shell）
    "media": 640,        # 媒体解析卡（templates.py .panel）
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

# ==================== 壳层釉瑚渐变（VIS1 多色交织波 2026-09-20） ====================
# 用户裁定：背景釉瑚渐变色「颜色太单一，需多色交织；不透明度全部调高」；
# 不透明度设计以 06_market_commodities 为基准=「wash 色与雾底按混入比互调」
# 的既有语言（06 原档 55/48/40），本值在该锚点上整体上浮 ~1.2–1.3×（55→72 /
# 48→62 / 40→55）并把色标 4→7、色相 3→4（新增 --wash-blob-1 平台混色斑做
# 回绕交织）。硬约束三条：
# ①首色标保持 `linear-gradient(145deg, var(--wash-mist) 0%` 形态——
#   test_pc_never_paints_brand_base（雾底打底锁）与 test_mica_shell
#   （shell_base_css 字面锁）都按该前缀取相；
# ②只用 --wash-* 四键与 --wash-blob-1（平台色唯一受控背景通道，定义内
#   accent ≤35% 数值锁不动；本表把它当色标消费，等效 accent 覆盖
#   0.35×0.62≈21.7% ≤35%，--accent 本体仍永不作底色）；
# ③全 11 面唯一来源——mica_shell.render_root_tokens 公共段注入
#   --mica-shell-wash、shell_base_css 内插本常量、7 张模板改 var() 消费，
#   模板/直拼卡侧手抄 145deg 副本退役（DESIGN-SPEC §一.11「手抄副本=0」
#   目标态的壳层收口，本席落地）。
SHELL_WASH_GRADIENT = (
    "linear-gradient(145deg, var(--wash-mist) 0%, "
    "color-mix(in srgb, var(--wash-blob-1) 78%, var(--wash-mist)) 15%, "
    "color-mix(in srgb, var(--wash-1) 96%, var(--wash-mist)) 32%, "
    "color-mix(in srgb, var(--wash-3) 88%, var(--wash-mist)) 50%, "
    "color-mix(in srgb, var(--wash-2) 62%, var(--wash-mist)) 64%, "
    "color-mix(in srgb, var(--wash-1) 94%, var(--wash-mist)) 82%, "
    "color-mix(in srgb, var(--wash-3) 80%, var(--wash-mist)) 100%)"
)

# ==================== 壳层渐变·按面派生（goal-7 二波 2026-09-28，澜汐需求 7）====
# 用户明令「背景釉瑚渐变漂移彩色中颜色的布局不得完全一样」。旧态：SHELL_WASH_GRADIENT
# 单源 ⇒ 11 个面逐字节共用同一份色标布局，差异只来自 --phase 色斑相位——只满足
# "飘逸"不满足"布局各面不同"。本段把**色标布局**改为按 face 派生：
# - 色板不变（同族 --wash-mist/1/2/3/blob-1，全部本命蓝派生 ⇒ 同一角色本命色不跨面变味）；
# - 变的是**停点位置 + 哪支洗色落在哪一档**（rotation），两两组合使任意两面逐字节不同；
# - face="" 恒返回 SHELL_WASH_GRADIENT（旧缺省路径逐字节不变，兼容未入册面与样张基线）；
# - 首色标恒 `linear-gradient(145deg, var(--wash-mist) 0%` 形态（雾底打底锁 +
#   test_pc_never_paints_brand_base 按该前缀取相，任何面不得改写）。
# 面序唯一（_WASH_FACE_ORDER 里每个已登记面占唯一索引）+ 取模周期（10 布局 × 6 rotation，
# lcm=30）⇒ 索引 < 30 的面彼此布局必互异；机器门
# tests/test_template_visual_audit.py::test_shell_wash_layout_pairwise_distinct 现算兜底。
_WASH_STOP_PALETTE: tuple[tuple[str, int], ...] = (
    ("--wash-blob-1", 78),
    ("--wash-1", 96),
    ("--wash-3", 88),
    ("--wash-2", 62),
    ("--wash-1", 94),
    ("--wash-3", 80),
)
# 六档尾停的位置骨架（0% 雾底 + 这五个内停 + 100% 末停）；每档一种疏密节奏。
# 首档刻意不等于 canon 的 (15,32,50,64,82)——face 索引 0（universal）若同时命中
# rotation=0 与 canon 位置就会复现 canon（"布局各面不得雷同"当场破功）。
_WASH_POS_LAYOUTS: tuple[tuple[int, int, int, int, int], ...] = (
    (14, 31, 52, 66, 84),
    (12, 34, 46, 68, 84),
    (18, 30, 54, 62, 86),
    (10, 28, 48, 70, 80),
    (20, 36, 52, 66, 88),
    (14, 26, 44, 60, 78),
    (16, 40, 56, 72, 84),
    (8, 30, 42, 66, 90),
    (22, 38, 58, 74, 82),
    (12, 26, 50, 62, 78),
)
# 消费壳层釉瑚渐变的**唯一面序**（新增壳面在此登记一枚索引，不得重复）。
_WASH_FACE_ORDER: tuple[str, ...] = (
    "universal",
    "market",
    "finance",
    "song",
    "news_digest",
    "affinity",
    "error",
    "mermaid",
    "media",
    "usage",
    "help",
    "debug",
)
_WASH_STOP_COUNT = len(_WASH_STOP_PALETTE)
_WASH_LAYOUT_COUNT = len(_WASH_POS_LAYOUTS)


def shell_wash_for_face(face: str) -> str:
    """face → 该面的壳层釉瑚渐变串（色板同族、色标布局按面互异）。

    缺省 ``face=""`` 与历史 ``SHELL_WASH_GRADIENT`` 逐字节一致；已登记面按其
    ``_WASH_FACE_ORDER`` 索引确定性派生（rotation 换洗色落位、layout 换停点疏密）；
    未登记面落回 canon（保持向后兼容，不臆造新布局）。纯函数、无随机、跨进程稳定。
    """
    if not face:
        return SHELL_WASH_GRADIENT
    try:
        index = _WASH_FACE_ORDER.index(face)
    except ValueError:
        return SHELL_WASH_GRADIENT
    rotation = index % _WASH_STOP_COUNT
    layout = _WASH_POS_LAYOUTS[(index // _WASH_STOP_COUNT) % _WASH_LAYOUT_COUNT]
    stops = [_WASH_STOP_PALETTE[(j + rotation) % _WASH_STOP_COUNT] for j in range(_WASH_STOP_COUNT)]
    # 前五档用 layout 疏密，末档钉 100%（保雾底↔本命洗收尾）。
    positions = (*layout, 100)
    body = ", ".join(
        f"color-mix(in srgb, var({key}) {mix}%, var(--wash-mist)) {pos}%"
        for (key, mix), pos in zip(stops, positions)
    )
    return f"linear-gradient(145deg, var(--wash-mist) 0%, {body})"


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
    "color-mix(in srgb, var(--accent) 20%, transparent) 0%, "
    "color-mix(in srgb, var(--accent) 8%, transparent) 46%, transparent 74%)"
)
_BRAND_WASH = derive_wash_tokens(BRAND_ACCENT)
#: 釉瑚渐变的**唯一派生锚点**＝守岸人本命蓝（2026-09-25 澜汐：背景要在守岸人
#: 的蓝色标志色上做飘逸渐变彩色处理）。此前各卡 ``--wash-1..3`` 按各自
#: ``--accent`` 派生，红系平台卡（点歌/账单）整张壳底被推成粉灰——平台身份
#: 只应留在 accent 强调线与 ≤35% 的漂移色斑里，不该决定底色色相。
#: 消费点：``bridge._card_root_tokens`` 与 ``usage_cards`` 直拼卡。
BRAND_WASH_TOKENS: dict[str, str] = _BRAND_WASH
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
# 次级文字灰：壳底洗色加深后，直接落在壳上的次级文字（卡头副标题、分区线旁
# 的小注）对比会掉到 AA 以下——旧值 #576272 对**改版前**最深壳 stop 就只有
# 4.37:1（本来就没过 4.5）。这里连同洗色一起下一档，把 AA 补回来而不是
# 靠"次级文字别放壳上"绕过去。
TEXT_SECONDARY = "#4e5866"
# 区分线 token：清晰可见的平台色 22% 细线（替代旧 14% 淡线）。
DIVIDER = "1px solid color-mix(in srgb, var(--accent) 22%, rgba(255, 255, 255, 0.65))"
# 字号阶梯（px）：全模板字号只允许取本表值（契约测试锁定），小件下限 12。
# goal-7 统一波（2026-09-25）：把各面**实际在用**的档位一次收编成单一阶梯，
# 每一档一个角色名、一次定死；一次性孤值（18/19/21/22/23/28/30/44）全部向
# 就近档位收敛（18→lead 17、19/21/22→title 20、23→heading 24、28→display 26、
# 30→heading 24、44→hero 46），不在任何面留下表外字面量。新增的三档不是
# 发明新字号——field 14 / metric 16 / hero 46 是既有面里已存在的最大副本值/
# 钉过样张基线的展示值，登记即执法（门：tests/test_template_visual_audit.py
# ::test_owned_faces_font_size_within_type_scale）。
TYPE_SCALE_PX: dict[str, int] = {
    "caption": 12,   # 最小注记/角标（下限档）
    "label": 13,     # 徽章/胶囊/英文署名等标签件
    "field": 14,     # 键值节字段名与次级正文（诊断/金融/宽卡通用字段档）
    "body": 15,      # 正文
    "metric": 16,    # 行内强调数字（tabular 小计/涨跌值）
    "lead": 17,      # 人话主句/序号大字/汇总数字（诊断卡 2026-09-25 重排档）
    "title": 20,     # 标准卡标题与统计大字
    "heading": 24,   # 宽壳卡主标题（诊断卡 heading / 好感度卡头题，2026-09-25 由 30 收敛）
    "display": 26,   # 展示大字（账单合计题等）
    "hero": 46,      # 单卡一件的旗舰数字（好感度分值；媒体封面占位符由 44 并入）
}
# 字重档位（goal-7 统一波 2026-09-25）：全渲染面只允许取本表值。
# 650 的 15 处手抄副本全部收敛为 semibold 600（本波退役账，门执法后不可回潮）；
# 上限 FONT_WEIGHT_MAX=700 铁律不变。
FONT_WEIGHT_STEPS: dict[str, int] = {
    "regular": 400,
    "semibold": 600,
    "bold": 700,
}
# 边框粗细合法集（goal-7 统一波 2026-09-25，RADIUS_INNER_PX 同先例=「合法集」
# 而非 CSS 变量）：hairline 1px 是全仓唯一描边/分隔线档（DIVIDER/GLASS_EDGE/
# .glass 边框都是 1px）；ring 2px 只放行头像/图标高亮环这一种用途
# （universal 视频壳头像环 3 处在册），其余粗细一票否决。
BORDER_WIDTH_PX = frozenset({1, 2})

# 诊断卡专用洗色（2026-09-25 澜汐点名，同日二轮收口）：只有**运行时告警卡**
# 需要一条自有壳层渐变——语义就是"出事了"，收尾必须压到红。
# 能力异常诊断卡不再另抄一支：它改用公共 SHELL_WASH_GRADIENT（多段彩漂），
# 只把派生锚点搬到本命蓝（bridge._card_root_tokens 的 wash_color 形参）。
# 旧 CARD_WASH_CALM 是一支四段直线蓝→蓝，把"釉瑚飘逸"做成了加深色块，已退役。
CARD_WASH_ALERT = (
    "linear-gradient(150deg, #e6f1fc 0%, #cfe3f8 24%, "
    "color-mix(in srgb, #318ce7 30%, #ffffff) 48%, "
    "color-mix(in srgb, #d54941 34%, #ffffff) 78%, "
    "color-mix(in srgb, #d54941 56%, #ffffff) 100%)"
)

# 诊断卡色斑（``--wash-blob-1``）同批登记：``render_root_tokens`` 里这一枚恒与
# ``var(--accent)`` 混（契约"平台色斑"的定义），而两档诊断卡的 accent 都是语义
# 红——不覆盖就会在左上角顶出一块灰粉，正是她点名的"背景现在是灰色的"。
# 两档都仍走「登记色 ≤24% 混白」，与 ``wash_blob_mix≤35%`` 的旧上限同口径。
CARD_WASH_BLOBS: dict[str, str] = {
    "calm": "color-mix(in srgb, #318ce7 24%, #f2f8ff)",
    "alert": "color-mix(in srgb, #d54941 24%, #eaf2fb)",
}


# ==================== CORE 值册扩充（v21r3 统一收尾波 2026-09-18，C1-C13 裁决）====================
# 背景：token 层统一（render_root_tokens 面单源注入）后，外壳 CSS/色斑/玻璃仍
# 有 12 份手抄副本。本节把裁决基线 C1-C13 的全部登记项钉进值册——模板/直拼卡
# 只准 var()/常量引用，改这里=全卡自动生效（与 vis4 阴影族同一「只开正门」哲学）。

# C3 液态玻璃三背景层：面板主档（.glass）= MAIN+EDGE、页脚档（.glass-foot）=
# FOOT+EDGE。无 backdrop-filter（透明截图无物可糊）；值与现行各卡逐字符一致。
GLASS_MAIN = (
    "linear-gradient(150deg, rgba(255, 255, 255, 0.66) 0%, "
    "rgba(255, 255, 255, 0.44) 100%) padding-box"
)
GLASS_FOOT = (
    "linear-gradient(150deg, rgba(255, 255, 255, 0.66) 0%, "
    "rgba(255, 255, 255, 0.46) 100%) padding-box"
)
GLASS_EDGE = (
    "linear-gradient(150deg, rgba(255, 255, 255, 0.95) 0%, "
    "rgba(255, 255, 255, 0.35) 55%, rgba(255, 255, 255, 0.72) 100%) border-box"
)

# C4 语义色五枚：不随 --accent 派生（金融卡 --up/--down 与前两枚同值，语义
# 「红涨绿跌」；warning 取暗琥珀，浅底上 ≥4.5:1）。
SEMANTIC_DANGER = "#d54941"    # 危险/异常/涨
SEMANTIC_SUCCESS = "#2e9e6b"   # 成功/正常/跌
SEMANTIC_WARNING = "#b07d1a"   # 警告/降级
SCORE_HOT = "#157347"          # 热评/热榜正向
SCORE_COLD = "#b42334"         # 冷榜/负向
SEMANTIC_COLORS: dict[str, str] = {
    "danger": SEMANTIC_DANGER,
    "success": SEMANTIC_SUCCESS,
    "warning": SEMANTIC_WARNING,
    "score_hot": SCORE_HOT,
    "score_cold": SCORE_COLD,
}

# C5 深色遮罩四员（语义不同分别登记、值不改）：徽章底/横幅压暗/代码块底/
# 媒体占位。遮罩是暗色系，直接登记 rgba、不进 wash/accent 派生体系。
OVERLAY_SCRIMS: dict[str, str] = {
    "scrim_badge": "rgba(10, 12, 16, 0.72)",
    "scrim_banner": "rgba(15, 18, 24, 0.10)",
    "scrim_code": "rgba(28, 30, 38, 0.94)",
    "scrim_media": "rgba(38, 46, 56, 0.75)",
}

# C9 等宽字体栈单一登记（代码/模型名/ID 等宽场景；与 FONT_FAMILY_STACK 并列）。
MONO_FONT_STACK = '"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace'

# C1 半径：内径合法表（瓦片内小件）；pill/正圆作为登记特例。主族 30/18/14
# （shell/panel/tile，ThemeTokens 三字段）不动。
RADIUS_INNER_PX = frozenset({4, 6, 8, 12, 16})
RADIUS_INNER_SCALE_PX: dict[str, int] = {
    "xs": 4,
    "sm": 6,
    "md": 8,
    "lg": 12,
    "xl": 16,
}
RADIUS_PILL = "999px"    # 胶囊（badge/command pill）
RADIUS_CIRCLE = "50%"    # 正圆（头像/圆点）
# 内径刻度 + 特例的 CSS 变量投影（theme_to_css_vars 与 render_root_tokens 共用）。
RADIUS_INNER_CSS_VARS: dict[str, str] = {
    "--r-inner-xs": "4px",
    "--r-inner-sm": "6px",
    "--r-inner-md": "8px",
    "--r-inner-lg": "12px",
    "--r-inner-xl": "16px",
    "--r-pill": RADIUS_PILL,
    "--r-circle": RADIUS_CIRCLE,
}

# C2 色斑常量：漂移色斑数量 + 三档漂移周期（秒，升序登记）。逐斑分配是历史
# CSS 的交错顺序 drift-a=46s / drift-b=58s / drift-c=52s，由 mica_shell 的
# 位次索引表从升序登记值映射（_BLOB_DURATION_INDICES），登记值本身保持升序。
BLOB_COUNT = 3
BLOB_DURATIONS = (46, 52, 58)


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
    # 与 TEXT_SECONDARY 同批下一档（2026-09-25 洗色加深后 tint_b 掉到 4.45:1，
    # 没过 AA）。两枚同语义 token 并轨是契约 §八 D-4 的待裁项，本行**不**合并
    # 两 token，只把两枚都拉到合格对比。
    text_sub: str = "#545b66"
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
# BRAND_THEME.display_name（「守岸人」）= 卡片品牌中文名的单一来源
# （CAP1 2026-09-20：bridge 各渲染函数的 bot_name 缺省值改读此处，
# 不再各写「"守岸人"」字面量；能力侧显式传入的实例名优先，语义不变）。
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


# ==================== 系统主题（非平台，独立于平台注册表） ====================
# 运行异常诊断卡（error_card.html）专用：强调色=语义红（与金融卡 --up 同源
# 红系，红=异常语义），走独立 ERROR_THEME 注入 --accent，**不进 PLATFORM_THEMES**
# ——平台注册表只收「内容来源平台」，系统态不污染该命名空间。云母洗仍由
# derive_wash_tokens 从红色 accent 派生（wash-1 轻推向暖相，mist 保持本命
# 打底），满足「本命 wash 打底 + 红强调」的视觉裁定。
ERROR_ACCENT = "#d54941"
ERROR_THEME = _make_theme("system_error", "运行异常", ERROR_ACCENT)


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
        "--accent": theme.accent,
        "--accent-dark": theme.accent_dark,
        "--accent-light": theme.accent_light,
        "--wash-1": theme.wash_1,
        "--wash-2": theme.wash_2,
        "--wash-3": theme.wash_3,
        "--wash-mist": theme.wash_mist,
        # VIS1（2026-09-20）：壳层釉瑚渐变单源（与 render_root_tokens 公共段
        # 同值；theme_to_css_vars 是「新模板直消费」旁路，两路同源不手抄）。
        "--mica-shell-wash": SHELL_WASH_GRADIENT,
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
        # CORE 值册（2026-09-18 C1-C13）：玻璃两档+描边/遮罩四员/语义五色/
        # 等宽字体/内径刻度。命名与 --mica-shadow-* 同风格：玻璃与遮罩挂
        # --mica- 前缀（工艺 token），语义色/等宽/内径按语义裸名。
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
        "--font-mono": MONO_FONT_STACK,
        **RADIUS_INNER_CSS_VARS,
    }


# 平台官方展示名（渲染页脚/徽章用；与旧 bridge 字面量逐键一致）。
PLATFORM_OFFICIAL_NAMES: dict[str, str] = {
    key: theme.display_name for key, theme in PLATFORM_THEMES.items()
}
PLATFORM_OFFICIAL_NAMES.setdefault("generic", "Web")

# FIX8（2026-09-21）：本表补齐 6 枚既有公开符号（DIVIDER / FONT_FAMILY_STACK /
# GLOW_ACCENT / SHADOW_CSS_VARS / SHADOW_LEVELS / TYPE_SCALE_PX）。此前它们
# 只在显式具名 import 与垫片显式重列两条通道上可用，星号导出与 __all__ 承重面
# 不含它们——机器门 tests/test_fix8_render_gaps.py::test_all_covers_every_public_binding
# 现把「模块级公开绑定 ⊆ __all__」钉死，新增公开符号不入册即红。
__all__ = [
    "BLOB_COUNT",
    "BLOB_DURATIONS",
    "BORDER_WIDTH_PX",
    "BRAND_ACCENT",
    "BRAND_NAME_EN",
    "BRAND_THEME",
    "BRAND_WASH_TOKENS",
    "CARD_SHELL_WIDTHS",
    "CARD_WASH_ALERT",
    "CARD_WASH_BLOBS",
    "DEFAULT_THEME",
    "DEFAULT_WASH_TOKENS",
    "DIVIDER",
    "ERROR_ACCENT",
    "ERROR_THEME",
    "FONT_FAMILY_STACK",
    "FONT_WEIGHT_MAX",
    "FONT_WEIGHT_STEPS",
    "GAP_SCALE_PX",
    "GLASS_EDGE",
    "GLASS_FOOT",
    "GLASS_MAIN",
    "GLOW_ACCENT",
    "META_VIEWPORT_POLICY",
    "MONO_FONT_STACK",
    "OVERLAY_SCRIMS",
    "PLATFORM_FOOTER_LABELS",
    "PLATFORM_OFFICIAL_NAMES",
    "PLATFORM_THEMES",
    "RADIUS_CIRCLE",
    "RADIUS_INNER_CSS_VARS",
    "RADIUS_INNER_PX",
    "RADIUS_INNER_SCALE_PX",
    "RADIUS_PILL",
    "SCORE_COLD",
    "SCORE_HOT",
    "SEMANTIC_COLORS",
    "SEMANTIC_DANGER",
    "SEMANTIC_SUCCESS",
    "SEMANTIC_WARNING",
    "SHADOW_CSS_VARS",
    "SHADOW_LEVELS",
    "SHADOW_PRIMARY",
    "SHADOW_SECONDARY",
    "SHELL_WASH_GRADIENT",
    "SURFACE_TINTS",
    "TEXT_SECONDARY",
    "THEME_ALIASES",
    "TYPE_SCALE_PX",
    "UNKNOWN_PLATFORM_COLOR",
    "UNKNOWN_THEME_KEYS",
    "ThemeTokens",
    "brand_display_name_for",
    "brand_name_en_for",
    "brand_theme_for",
    "derive_wash_tokens",
    "get_platform_theme",
    "platform_accent",
    "shell_wash_for_face",
    "theme_to_css_vars",
]
