"""群/私聊「按条件订阅紧急信息」的规则层（WIRE-SUB，2026-09-20 用户裁定 1.C/2/3.B/4.B/5.A/6）。

为什么存在：用户裁定投递条件**不许写在 `.env`**（"太僵硬"），要在群里一条命令说好，
并且要能「某个群只播报特定地点的特定等级/警情」。四源地点口径不一致（本波实测）：
`nmc` 只有标题里的地名文字（`qx.json` 码表**无经纬度**），`gdacs`/`icl`/`usgs` 只有经纬度
⇒ 单靠文字匹配会让后三类**永远不命中**，故地点判定是「文字匹配 ∨ 半径圈」两路（裁定 4.B）。

三条纪律：
1. **认不出就报错给候选，绝不静默收下**——本波被「填了但不生效」烧过两次
   （死配置键 `auto_approve_sources`、`nmc_alarm` 写成模块名）。所以 `area=` 必须在
   `qx.json` 2527 区县码表里解析得到，否则整条规则不成立（`RuleError` + 候选词）。
2. **不造第二载体**：等级用既有 `EmergencyLevel`（D-3），坐标用契约正经字段
   （`EmergencyItem.latitude/longitude`），不塞 `body`/`audit_tags`。
3. **规则即刻生效**：投递侧现读本表，装配期冻结的只有总闸——否则群里设完要重启，
   等于把这条功能的意义抹掉。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    EmergencyLevel,
)
from plugins.bot_unified_runtime.domains.emergency_info.service import (
    alert_taxonomy as taxonomy,
)

#: 用户裁定 4.B：半径默认 200km，可逐条覆盖。
DEFAULT_RADIUS_KM = 200.0
#: 半径上下限：再小会漏掉省级预警的落点误差，再大等于不过滤（不如直接订全部）。
MIN_RADIUS_KM = 10.0
MAX_RADIUS_KM = 3000.0
#: 单条规则最多几个等级/几个类型，防"把整个词表抄进一行"这种没法解释的规则。
MAX_TERMS = 8

VALID_SCOPES = frozenset({"group", "private"})

_QX_ASSET = "weather/assets/qx.json"
_LEVEL_WORDS = {
    "红色": "P0", "橙色": "P1", "黄色": "P2", "蓝色": "P3",
    "红": "P0", "橙": "P1", "黄": "P2", "蓝": "P3",
    "p0": "P0", "p1": "P1", "p2": "P2", "p3": "P3",
}
_ABOVE_SUFFIXES = ("及以上", "以上")


class RuleError(ValueError):
    """规则不成立。`candidates` 非空即代表"认不出但附近有这些可选"，直接回给用户。"""

    def __init__(self, reason: str, *, candidates: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.candidates = candidates

    def __str__(self) -> str:  # pragma: no cover - 只给人看
        if not self.candidates:
            return self.reason
        return f"{self.reason}（可选：{'、'.join(self.candidates)}）"


def subscription_key(target_scope: str, target_id: str) -> str:
    """库内唯一身份拼法（`group:123` / `private:3865067623`）——唯此一处，禁副本。"""
    return f"{target_scope}:{str(target_id or '').strip()}"


@dataclass(frozen=True)
class SubscriptionRule:
    """一个投递目标（群或私聊对象）当前生效的唯一一条规则（裁定 5.A：永久直到退订）。"""

    target_scope: str
    target_id: str
    levels: frozenset[str] = frozenset()
    kinds: frozenset[str] = frozenset()
    #: WP3：注册表派生的类别 id（`taxonomy.category_id_for_term` 认出来的那些词）。
    #: 与 `kinds` 的分工——`categories` 是**精确命中**（订阅「风暴潮」就只中风暴潮，
    #: 不会再被"标题里碰巧有这两个字"骗到），`kinds` 是**开放词表兜底**
    #: （用户写的词不在注册表里时不拦、按原文子串匹配，策略与 WIRE-SUB 一致）。
    categories: frozenset[str] = frozenset()
    area_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float = DEFAULT_RADIUS_KM
    created_by: str = ""
    #: 坐标是否由地名解析得来（仅回显用）；半径匹配实际生效与否看 lat/lon 是否成对。
    coord_resolved: bool = False
    #: 观测面（只读自库）：`match_count=0` 就是「配了从没命中过」，`订阅 看` 必须说出来。
    last_matched_at: datetime | None = None
    match_count: int = 0

    @property
    def target_key(self) -> str:
        return subscription_key(self.target_scope, self.target_id)

    @property
    def has_area(self) -> bool:
        return bool(self.area_name) or (self.latitude is not None)

    @property
    def has_point(self) -> bool:
        """半径匹配真正可用的判据：规则侧必须**成对**坐标。"""
        return self.latitude is not None and self.longitude is not None

    @property
    def has_kind_filter(self) -> bool:
        """类型维度是否生效（注册表类别 ∨ 开放词表杂词，任一即算）。"""
        return bool(self.categories or self.kinds)

    @property
    def referenced_categories(self) -> tuple[str, ...]:
        """这条规则点名的类别 id（含从开放词表里事后能认出来的那些）。"""
        found = set(self.categories)
        for token in self.kinds:
            hit = taxonomy.category_id_for_term(token)
            if hit:
                found.add(hit)
        return tuple(sorted(found))

    def unsourced_terms(self) -> tuple[str, ...]:
        """点名的类别里**当前无源**的那些（帮助/回显必须直说，不许静默收下）。"""
        return tuple(
            taxonomy.label_of(category_id)
            for category_id in self.referenced_categories
            if (taxonomy.category(category_id) or None) is not None
            and not taxonomy.category(category_id).is_sourced
        )

    def describe(self) -> str:
        """人读回显（`紧急信息 订阅 看` 用）；空段不写，别输出"等级：全部"这种废话串。"""
        parts = [f"范围={'群' if self.target_scope == 'group' else '私聊'}"]
        parts.append("等级=" + ("、".join(sorted(self.levels)) if self.levels else "P0-P3 全部"))
        # `kinds` 自 WP3 起含"注册表已认出的那些原文词"（`categories` 是它们的 id 形态），
        # 回显照原文说，用户写什么就看到什么；id 只参与命中与校验，不进人话。
        parts.append("类型=" + ("、".join(sorted(self.kinds)) if self.kinds else "不限"))
        if self.area_name:
            where = self.area_name
            if self.has_point:
                where += f"（{int(self.radius_km)}km 内）"
            else:
                # 没坐标就只有地名文字一条路——不写出来，用户会以为半径在生效。
                where += "（按地名文字匹配）"
        elif self.has_point:
            where = f"坐标点（{int(self.radius_km)}km 内）"
        else:
            where = "不限"
        parts.append(f"地点={where}")
        return "｜".join(parts)


# ------------------------------------------------------------------ 码表（地点）


_QX_CACHE: dict[str, tuple[str, str]] | None = None


def _area_index() -> dict[str, tuple[str, str]]:
    """`qx.json` → {地点名: (省, 市)}，进程内缓存一次。

    码表**没有经纬度**（本波实测 keys=code/province/city/url），所以它只能回答
    "这个地名是不是我们认识的地方"，不能回答"它在哪"⇒ 半径圈需要用户给坐标或
    由装配侧注入解析器（`resolver`），两者都没有时规则仍成立、只是退化成文字匹配。
    """
    global _QX_CACHE
    if _QX_CACHE is None:
        index: dict[str, tuple[str, str]] = {}
        path = Path(__file__).resolve().parent.parent.parent / _QX_ASSET
        if path.is_file():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                rows = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                province = str(row.get("province") or "").strip()
                city = str(row.get("city") or "").strip()
                for name in (city, province, province.rstrip("省区市") if province else ""):
                    if name:
                        index.setdefault(name, (province, city))
        _QX_CACHE = index
    return _QX_CACHE


def _candidates(name: str, limit: int = 5) -> tuple[str, ...]:
    """从码表里挑最像的几个给用户看——"认不出"必须可行动，不然等于报错不说人话。"""
    index = _area_index()
    if not index:
        return ()
    scored: list[tuple[float, str]] = []
    for key in index:
        if name and (name in key or key in name):
            scored.append((1.0 + len(key) / max(len(name), 1), key))
    if not scored:
        try:
            import difflib

            close = difflib.get_close_matches(name, list(index), n=limit, cutoff=0.4)
        except Exception:  # noqa: BLE001 - 建议项失败不该把主路径带崩
            close = []
        return tuple(dict.fromkeys(close))
    scored.sort(key=lambda item: -item[0])
    return tuple(key for _, key in scored[:limit])


# ------------------------------------------------------------------ 各项解析


def _as_level(word: str) -> str | None:
    """一个词 → 等级字面（`P0..P3`）；认不出返回 None（不猜、不上抬）。"""
    text = str(word or "").strip()
    return _LEVEL_WORDS.get(text) or _LEVEL_WORDS.get(text.lower())


def normalize_levels(raw: Iterable[str]) -> frozenset[str]:
    """等级：认 `P0..P3` 与中文色词（红/橙/黄/蓝）。"""
    out: set[str] = set()
    for token in raw:
        text = str(token or "").strip()
        if not text:
            continue
        mapped = _as_level(text)
        if mapped is None:
            raise RuleError(f"等级无法识别：{text}", candidates=("P0", "P1", "P2", "P3"))
        out.add(mapped)
    if len(out) > MAX_TERMS:  # pragma: no cover - 色词只有四档，防御性
        raise RuleError(f"等级最多 {MAX_TERMS} 个")
    return frozenset(out)


def levels_from_ceiling(anchor_word: str) -> frozenset[str]:
    """"橙色以上"→ {P0,P1}：锚点档及其之上（rank 越大越高，P0 最高）。"""
    anchor = _as_level(anchor_word)
    if anchor is None:
        raise RuleError(
            f"档位词无法识别：{anchor_word}", candidates=("红色", "橙色", "黄色", "蓝色")
        )
    wanted = EmergencyLevel(anchor)
    return frozenset(
        level.value for level in EmergencyLevel if level.rank >= wanted.rank
    )


def _ceiling_anchor(word: str) -> str | None:
    """"湘潭 橙色以上"里的尾巴：命中「X以上/X及以上」则返回锚点词 X。"""
    for suffix in _ABOVE_SUFFIXES:
        if word.endswith(suffix):
            return word[: -len(suffix)]
    return None


def normalize_kinds(raw: Iterable[str]) -> frozenset[str]:
    """类型=**开放词表**（WP3 起在注册表之外仍保留这一层，策略一寸未收）。

    注册表（`service/alert_taxonomy.py`）认得的词由 `split_kind_terms` 搬进
    `SubscriptionRule.categories` 走精确命中；认不出的词**照旧收下**进 `kinds`，
    这里只拦"结构性垃圾"（空、超长、逗号糊成一坨、数量爆炸）。
    拼错类型的代价由观测面兜：命中数恒 0 会在 `紧急信息 订阅 看` 里直说"从没命中过"
    （`match_count`/`last_matched_at`），不是静默失效。
    """
    out: set[str] = set()
    for token in raw:
        text = str(token or "").strip()
        if not text:
            continue
        if len(text) > 12 or re.search(r"[\s,;，、]", text):
            raise RuleError(f"警情类型要逐个写（不含空格/标点，≤12 字）：{text}")
        out.add(text)
    if len(out) > MAX_TERMS:
        raise RuleError(f"警情类型最多 {MAX_TERMS} 个")
    return frozenset(out)


def split_kind_terms(
    param_terms: Iterable[str], free_terms: Iterable[str]
) -> tuple[frozenset[str], frozenset[str], tuple[str, ...]]:
    """把两处来源的类型词分成（注册表类别 id，原文词表，被结构规则拒掉的词）。

    `param_terms` 来自 `kinds=` 参数式，`free_terms` 来自自然语序 —— 两者同等对待，
    **不存在"参数式才认类别"**这种二等公民口径。识别口径唯一 = 注册表别名表。

    注册表认得的词**同时**留在 `kinds`（原文子串这条老路一寸没减）与 `categories`
    （新增的精确/别名维度），命中判定走「∨」：WP3 只做加法，不做替换——
    替换会让 WIRE-SUB 那批「开放词表」锁集体失义，也会让老库里已有的规则突然变哑。
    """
    categories: set[str] = set()
    kinds: set[str] = set()
    rejected: list[str] = []
    for token in (*param_terms, *free_terms):
        text = str(token or "").strip()
        if not text:
            continue
        hit = taxonomy.category_id_for_term(text)
        if hit:
            categories.add(hit)
        if len(text) > 12 or re.search(r"[\s,;，、]", text):
            if not hit:  # 注册表里的词天然合规，不再走一遍结构判据
                rejected.append(text)
            continue
        kinds.add(text)
    if len(kinds) > MAX_TERMS:
        raise RuleError(f"警情类型词最多 {MAX_TERMS} 个")
    return frozenset(categories), frozenset(kinds), tuple(rejected)


def validate_levels_against_categories(
    levels: Iterable[str], terms: Iterable[str]
) -> None:
    """色档按族校验（WP3 交付⑤）：不许把「红色以上」用在一个根本出不了红色的族上。

    判据唯一来自注册表的族色档（`AlertFamily.color_tiers`），实测依据写在各族注释里：
    目前**唯一**被收窄的族是 `global_disaster`（GDACS 只映射 Red/Orange，
    `sources/gdacs.py:54`），给它写「蓝色」会被当场点名，而不是留下一条永不命中的规则。
    未登记类别（开放词表杂词）不参与校验——它们什么都能匹配。
    """
    wanted = {str(value or "").strip() for value in levels if str(value or "").strip()}
    if not wanted:
        return
    for term in terms:
        category_id = taxonomy.category_id_for_term(term)
        if not category_id:
            continue
        tiers = taxonomy.color_tiers_for(category_id)
        legal = {str(level.value) for level in taxonomy.levels_of_tiers(tiers)}
        illegal = sorted(wanted - legal)
        if illegal:
            family = taxonomy.family_for(category_id)
            raise RuleError(
                f"「{taxonomy.label_of(category_id)}」属于{family.label}族，"
                f"这一族只有 {'、'.join(tiers)} 档，没有 {'、'.join(illegal)} 档"
                f"（{family.note or '族内色档见注册表'}）",
                candidates=tiers,
            )


def parse_radius(raw: str, *, default: float = DEFAULT_RADIUS_KM) -> float:
    text = str(raw or "").strip().rstrip("kKmM").strip()
    if not text:
        return default
    try:
        value = float(text)
    except ValueError as exc:
        raise RuleError(f"半径要写数字（km）：{raw}") from exc
    if not MIN_RADIUS_KM <= value <= MAX_RADIUS_KM:
        raise RuleError(f"半径得在 {MIN_RADIUS_KM:.0f}–{MAX_RADIUS_KM:.0f}km 之间：{value}")
    return value


def parse_coord(raw: str) -> tuple[float, float]:
    parts = [p.strip() for p in re.split(r"[,，;；]", str(raw or "")) if p.strip()]
    if len(parts) != 2:
        raise RuleError("坐标要写成 纬度,经度（例：27.87,112.94）")
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise RuleError(f"坐标不是数字：{raw}") from exc
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise RuleError("坐标越界（纬度 -90..90，经度 -180..180）")
    return lat, lon


# ------------------------------------------------------------------ 语法（裁定 1.C）


_PARAMS = re.compile(r"(area|levels?|kinds?|radius|coord)\s*=\s*([^\s|]+)", re.IGNORECASE)
_SPLIT = re.compile(r"[\s,，、;；|]+")


def _split_terms(raw: str | None) -> list[str]:
    return [token for token in _SPLIT.split(str(raw or "")) if token]


def parse_subscription(
    text: str,
    *,
    target_scope: str,
    target_id: str,
    created_by: str = "",
    default_radius_km: float = DEFAULT_RADIUS_KM,
    resolver: Callable[[str], tuple[float, float] | None] | None = None,
) -> SubscriptionRule:
    """把用户那句话变成规则：**参数式为主干，自然语序作别名**（裁定 1.C）。

    支持形态举例：
      `area=湘潭 kinds=暴雨 levels=P0,P1 radius=150`
      `湘潭 暴雨 橙色以上`
      `coord=27.87,112.94 radius=200 kinds=台风`
      （空文本＝"不限"，等价于订全部，仍要显式说一句"订阅"才生效）

    `resolver` 由装配层注入（地名→坐标，跨域取数只在装配层做，本层保持零 IO）：
    解析成功才启用半径匹配；失败或没注入时规则依然成立，只是退化成地名文字匹配，
    并由 `coord_resolved` 如实回显，绝不含糊地说"已按 200km 过滤"。
    """
    if target_scope not in VALID_SCOPES:
        raise RuleError(f"订阅范围只能是 group 或 private：{target_scope}")
    target = str(target_id or "").strip()
    if not target:
        raise RuleError("订阅目标为空——群内取本群号、私聊取你的 QQ 号（绝不猜）")

    body = str(text or "").strip()
    params = {key.lower(): value for key, value in _PARAMS.findall(body)}
    leftovers = _PARAMS.sub(" ", body)

    levels = normalize_levels(_split_terms(params.get("levels") or params.get("level")))
    kinds = normalize_kinds(_split_terms(params.get("kinds") or params.get("kind")))
    area_name = str(params.get("area") or "").strip()
    latitude: float | None = None
    longitude: float | None = None
    if params.get("coord"):
        latitude, longitude = parse_coord(params["coord"])

    # 自然语序兜底：参数式没写到的维度才从剩余词里认——顺序=档词 > 地名 > 类型词。
    for word in _split_terms(leftovers):
        ceiling = _ceiling_anchor(word)
        if ceiling is not None:
            levels |= levels_from_ceiling(ceiling)
        elif _as_level(word) is not None:
            levels |= normalize_levels([word])
        elif not area_name and word in _area_index():
            area_name = word
        else:
            # 先进开放词表，稍后 `split_kind_terms` 把注册表认得的搬进 `categories`——
            # 顺序不能反：反了就把"用户点名的一个类别"降级成子串匹配了。
            kinds |= normalize_kinds([word])

    if area_name and area_name not in _area_index():
        raise RuleError(
            f"地名「{area_name}」不在气象码表里（也可改写 coord=纬度,经度）",
            candidates=_candidates(area_name),
        )
    # WP3：把两类"类型词"分流——注册表认得的进 `categories`（精确命中），
    # 认不出的**保留**在 `kinds`（开放词表，只拦结构性垃圾，策略与 WIRE-SUB 一致）。
    categories, kinds, extra = split_kind_terms(
        _split_terms(params.get("kinds") or params.get("kind")), kinds
    )
    if extra:
        raise RuleError(
            "这些词不是一个已登记的警情种类，也不是可匹配的杂词（≤12 字、不含空格标点）："
            + "、".join(extra)
        )
    # 色档按族校验：点了名却没有那个档，就是用户说了一句永远不可能成立的话。
    validate_levels_against_categories(levels, categories | kinds)
    coord_resolved = False
    if area_name and latitude is None and resolver is not None:
        spot = resolver(area_name)
        if spot is not None:
            latitude, longitude = float(spot[0]), float(spot[1])
            coord_resolved = True

    return SubscriptionRule(
        target_scope=target_scope,
        target_id=target,
        levels=levels,
        kinds=kinds,
        categories=categories,
        area_name=area_name,
        latitude=latitude,
        longitude=longitude,
        radius_km=parse_radius(params.get("radius", ""), default=default_radius_km),
        created_by=str(created_by or "").strip(),
        coord_resolved=coord_resolved,
    )


# ------------------------------------------------------------------ 匹配判定


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """球面距离（km）。形态同 `sources/open_data_quakes.py` 的震级-距离换算处。"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def item_text(item: EmergencyItem) -> str:
    return " ".join(
        str(value or "")
        for value in (item.title, item.body, item.source_kind, item.color_label)
    )


def matches_subscription(item: EmergencyItem, rule: SubscriptionRule) -> bool:
    """这条条目要不要投给这个目标。三个维度是 **AND**，缺省维度视为放行。

    地点走「文字命中 ∨ 半径命中」：文字命中对气象预警有效，半径命中对震情/GDACS 有效；
    两边都拿不到（条目无坐标 + 规则只有地名）时**不放行**——宁可漏投也不要把
    "湘潭"这种规则误投给全国地震，那是把用户信任花掉的最快方式。

    类型维度（WP3 重做）＝「注册表类别精确命中 ∨ 开放词表原文子串命中」：
    前者让「订阅 风暴潮」只中风暴潮，后者保住 WIRE-SUB 的开放词表策略不变。
    条目的类别优先取库里已回写的 `category_id`，为空则按标题/正文现算（纯文本、零 IO）。
    """
    if rule.levels and (item.level is None or item.level.value not in rule.levels):
        return False
    if not rule.levels and item.level is None:
        return False  # 未定级一律不投（D-1），与投递侧 skip_ungraded 同向
    if not (rule.has_kind_filter or rule.has_area):
        return True
    text = item_text(item)
    if rule.has_kind_filter:
        category_id = str(getattr(item, "category_id", "") or "").strip() or (
            taxonomy.category_of_item(item)
        )
        by_category = bool(category_id) and category_id in rule.categories
        # 历史行（WP3 之前入库、`categories` 为空）仍走原文子串，绝不让老规则突然失配。
        by_text = any(kind in text for kind in rule.kinds) or any(
            taxonomy.label_of(cid) in text for cid in rule.categories
        )
        if not (by_category or by_text):
            return False
    if rule.has_area:
        by_text = bool(rule.area_name) and rule.area_name in text
        by_radius = False
        # 逐边显式判空（等价于 `rule.has_point and …`，但那样类型收窄不了）：
        # 规则侧与条目侧必须**各自**凑成一对坐标才谈距离，半边一律不投。
        if (
            rule.latitude is not None
            and rule.longitude is not None
            and item.latitude is not None
            and item.longitude is not None
        ):
            by_radius = (
                haversine_km(
                    rule.latitude, rule.longitude, item.latitude, item.longitude
                )
                <= rule.radius_km
            )
        if not (by_text or by_radius):
            return False
    return True


def summarize(rules: Iterable[SubscriptionRule]) -> str:
    return "｜".join(rule.describe() for rule in rules) or "（无生效订阅）"


__all__ = [
    "DEFAULT_RADIUS_KM",
    "MAX_RADIUS_KM",
    "MIN_RADIUS_KM",
    "VALID_SCOPES",
    "RuleError",
    "SubscriptionRule",
    "haversine_km",
    "item_text",
    "levels_from_ceiling",
    "matches_subscription",
    "normalize_kinds",
    "normalize_levels",
    "parse_coord",
    "parse_radius",
    "parse_subscription",
    "split_kind_terms",
    "subscription_key",
    "summarize",
    "validate_levels_against_categories",
]
