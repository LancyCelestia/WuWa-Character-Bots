"""六十四卦金钱卦（纯计算，零第三方依赖）。

模拟传统金钱卦起卦：三枚铜钱掷六次，自下而上成六爻。
- 铜钱以「背面」计数：每枚背面记 3、字面记 2，三枚之和为爻值。
  9 = 三背（老阳，动）、8 = 两背一字（少阴）、7 = 一背两字（少阳）、
  6 = 三字（老阴，动）。
- 三爻成卦：下卦（初二三爻）与上卦（四五上爻）各按 8 卦二进制
  （爻自下而上，阳=1）映射乾兑离震巽坎艮坤，64 卦名按上×下 8×8 表。
- 有老爻（6/9）时阳变阴、阴变阳得到变卦。
- 卦辞一句话与吉凶倾向为娱乐级概括，不作严肃解读。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

__all__ = [
    "CastResult",
    "HexagramInfo",
    "cast_hexagram",
    "format_cast_text",
    "hexagram_of",
    "toss_yao",
]

# 八经卦：二进制（自下而上，阳=1）-> 卦名与自然象。
_TRIGRAM_BITS: tuple[str, ...] = ("坤", "艮", "坎", "巽", "震", "离", "兑", "乾")
_TRIGRAM_SYMBOL: dict[str, str] = {
    "乾": "天", "兑": "泽", "离": "火", "震": "雷",
    "巽": "风", "坎": "水", "艮": "山", "坤": "地",
}


@dataclass(frozen=True)
class HexagramInfo:
    """一卦：名称（含上下卦象）、卦辞一句话与吉凶倾向。"""

    name: str
    upper: str
    lower: str
    gist: str
    tendency: str


# 64 卦表：(上卦, 下卦, 卦名, 卦辞一句话, 吉凶倾向)。
# 覆盖全部 8×8 组合；卦名按《周易》通行本（乾为天/天泽履/水火既济……）。
_HEXAGRAM_TABLE: tuple[tuple[str, str, str, str, str], ...] = (
    ("乾", "乾", "乾为天", "元亨利贞，刚健进取自有天时。", "吉"),
    ("乾", "兑", "天泽履", "履虎尾而不咬，谨慎前行有惊无险。", "中吉"),
    ("乾", "离", "天火同人", "志同道合，同心之力可以涉川。", "吉"),
    ("乾", "震", "天雷无妄", "守正则无妄之福，失正则有眚。", "平"),
    ("乾", "巽", "天风姤", "不期而遇，遇合之中暗藏提防。", "小凶"),
    ("乾", "坎", "天水讼", "争讼不宜久，得中道而止为上。", "小凶"),
    ("乾", "艮", "天山遁", "退避不是败，顺势而退保有余。", "平"),
    ("乾", "坤", "天地否", "天地不交闭塞，否极自有泰来。", "凶"),
    ("兑", "乾", "泽天夬", "刚决果断，宣示之后再行动。", "中吉"),
    ("兑", "兑", "兑为泽", "朋友讲习，和悦之气利涉大川。", "吉"),
    ("兑", "离", "泽火革", "巳日乃孚，顺时而变革得吉。", "中吉"),
    ("兑", "震", "泽雷随", "随时而动，随顺得当自有功。", "吉"),
    ("兑", "巽", "泽风大过", "栋桡之象，非常之举须量力。", "小凶"),
    ("兑", "坎", "泽水困", "困而不失其所，困境亦是磨砺。", "小凶"),
    ("兑", "艮", "泽山咸", "二气感应，以诚相感万事通。", "吉"),
    ("兑", "坤", "泽地萃", "聚人以正，聚合之时见亨通。", "吉"),
    ("离", "乾", "火天大有", "应有尽有，大收获源于柔德。", "大吉"),
    ("离", "兑", "火泽睽", "同而异，背离之时宜小事相求。", "小凶"),
    ("离", "离", "离为火", "重明以丽正，附丽光明养中虚之心。", "中吉"),
    ("离", "震", "火雷噬嗑", "咬而合之，除障后方可通行。", "中吉"),
    ("离", "巽", "火风鼎", "鼎新之象，去故取新自大吉。", "吉"),
    ("离", "坎", "火水未济", "事未竟成，蓄势之中辨物居方。", "平"),
    ("离", "艮", "火山旅", "旅途中小事可亨，行止贵柔。", "平"),
    ("离", "坤", "火地晋", "日出地上，晋升进取如日方升。", "吉"),
    ("震", "乾", "雷天大壮", "阳气壮盛，壮而守礼方为正。", "中吉"),
    ("震", "兑", "雷泽归妹", "位不当则凶，进退须守其正。", "小凶"),
    ("震", "离", "雷火丰", "明动相资大丰亨，盛极更须守。", "吉"),
    ("震", "震", "震为雷", "雷声震动，临危守定笑言哑哑。", "平"),
    ("震", "巽", "雷风恒", "恒久其道，立不易方则亨。", "吉"),
    ("震", "坎", "雷水解", "雷雨作而险散，赦过宥罪开新局。", "吉"),
    ("震", "艮", "雷山小过", "小事可过从，大事宜守中。", "平"),
    ("震", "坤", "雷地豫", "雷出地奋，顺势而豫喜相从。", "吉"),
    ("巽", "乾", "风天小畜", "柔畜其刚，力量尚小蓄养待发。", "平"),
    ("巽", "兑", "风泽中孚", "中心诚信，豚鱼可感天下应。", "吉"),
    ("巽", "离", "风火家人", "家人内正，家道正而天下定。", "吉"),
    ("巽", "震", "风雷益", "损上益下，益动而巽其进无疆。", "吉"),
    ("巽", "巽", "巽为风", "随风相济，谦顺而入事可行。", "中吉"),
    ("巽", "坎", "风水涣", "风行水上涣然而散，聚之以诚。", "小凶"),
    ("巽", "艮", "风山渐", "山上有木循序渐进，进以正则吉。", "吉"),
    ("巽", "坤", "风地观", "风行地上，观仰大德以化人。", "平"),
    ("坎", "乾", "水天需", "云上于天需以待时，有孚光亨。", "中吉"),
    ("坎", "兑", "水泽节", "节以制度，甘节则吉苦节则穷。", "中吉"),
    ("坎", "离", "水火既济", "水火相济功已成，守成防变是关键。", "大吉"),
    ("坎", "震", "水雷屯", "云雷屯难，万事起头难守正待时。", "小凶"),
    ("坎", "巽", "水风井", "井养不穷，往来井井改邑不改井。", "中吉"),
    ("坎", "坎", "坎为水", "重险叠至，守正涉险心有常。", "凶"),
    ("坎", "艮", "水山蹇", "前行有险跛足难行，反身修德。", "凶"),
    ("坎", "坤", "水地比", "水上于地相亲相辅，后夫凶早亲吉。", "吉"),
    ("艮", "乾", "山天大畜", "山中藏天大蓄积，养贤利涉大川。", "吉"),
    ("艮", "兑", "山泽损", "损下益上，先损后得贵中有实。", "平"),
    ("艮", "离", "山火贲", "山下有火文饰，质素为本文明为用。", "平"),
    ("艮", "震", "山雷颐", "山下有雷颐养，慎言语节饮食。", "中吉"),
    ("艮", "巽", "山风蛊", "山下有风积弊生蛊，革故方可鼎新。", "平"),
    ("艮", "坎", "山水蒙", "山下出泉蒙以养正，启蒙之功。", "中吉"),
    ("艮", "艮", "艮为山", "兼山而止，知止而后有定。", "平"),
    ("艮", "坤", "山地剥", "山附于地剥落，防衰消息盈虚。", "凶"),
    ("坤", "乾", "地天泰", "天地交而万物通，小往大来泰运开。", "大吉"),
    ("坤", "兑", "地泽临", "泽上有地君临，刚浸而长至于八月。", "吉"),
    ("坤", "离", "地火明夷", "明入地中晦其明，内明外顺守正艰。", "凶"),
    ("坤", "震", "地雷复", "一阳来复，出入无疾七日来复。", "中吉"),
    ("坤", "巽", "地风升", "地中生木循序上升，积小成大。", "吉"),
    ("坤", "坎", "地水师", "地中有水行险而顺，兴师慎战。", "平"),
    ("坤", "艮", "地山谦", "山藏地中谦谦君子，谦尊而光。", "大吉"),
    ("坤", "坤", "坤为地", "厚德载物，柔顺相承利牝马之贞。", "吉"),
)

# (上卦, 下卦) -> HexagramInfo；构建时校验恰好 64 组合且无重复。
HEXAGRAMS: dict[tuple[str, str], HexagramInfo] = {}
for _up, _low, _name, _gist, _tend in _HEXAGRAM_TABLE:
    HEXAGRAMS[(_up, _low)] = HexagramInfo(
        name=_name,
        upper=_up,
        lower=_low,
        gist=_gist,
        tendency=_tend,
    )
assert len(HEXAGRAMS) == 64, "六十四卦表必须恰好覆盖 8×8 组合"

_YAO_POSITIONS: tuple[str, ...] = ("初", "二", "三", "四", "五", "上")


def hexagram_of(lines: tuple[int, ...]) -> HexagramInfo:
    """六爻（自下而上，1=阳 0=阴）-> 本卦信息。"""
    if len(lines) != 6 or any(bit not in (0, 1) for bit in lines):
        raise ValueError("需要自下而上的六爻，每爻为 0（阴）或 1（阳）")
    lower = lines[0] * 4 + lines[1] * 2 + lines[2]
    upper = lines[3] * 4 + lines[4] * 2 + lines[5]
    return HEXAGRAMS[(_TRIGRAM_BITS[upper], _TRIGRAM_BITS[lower])]


def toss_yao(rng: random.Random) -> tuple[int, tuple[bool, bool, bool]]:
    """掷一次三枚铜钱：返回 (爻值 6-9, 三枚是否背面)。

    背面记 3、字面记 2；9 老阳、8 少阴、7 少阳、6 老阴（6/9 为动爻）。
    """
    coins = tuple(rng.random() < 0.5 for _ in range(3))
    value = sum(3 if back else 2 for back in coins)
    return value, coins  # type: ignore[return-value]


def _yao_label(value: int, position: int) -> str:
    """爻名：初九/九二/……/上九（阳称九，阴称六；初、上位次在前）。"""
    yin_or_yang = "六" if value in (6, 8) else "九"
    if position == 0:
        return f"初{yin_or_yang}"
    if position == 5:
        return f"上{yin_or_yang}"
    return f"{yin_or_yang}{_YAO_POSITIONS[position]}"


def _yao_bar(value: int, is_moving: bool) -> str:
    bar = "━━━━━" if value in (7, 9) else "━　━"
    return f"{bar}（动）" if is_moving else bar


@dataclass(frozen=True)
class CastResult:
    """一次金钱卦结果：六爻值（自下而上）+ 本卦 + 可选变卦。"""

    yao_values: tuple[int, int, int, int, int, int]
    original: HexagramInfo
    changed: HexagramInfo | None

    @property
    def moving_positions(self) -> tuple[int, ...]:
        """动爻位次（0 为初爻）。"""
        return tuple(i for i, value in enumerate(self.yao_values) if value in (6, 9))

    @property
    def lines(self) -> tuple[int, ...]:
        """本卦六爻二进制（自下而上，1=阳）。"""
        return tuple(1 if value in (7, 9) else 0 for value in self.yao_values)

    @property
    def changed_lines(self) -> tuple[int, ...]:
        """变卦六爻二进制（老阳变阴、老阴变阳）；无动爻时与本卦相同。"""
        return tuple(
            (0 if value in (7, 9) else 1) if value in (6, 9)
            else (1 if value in (7, 9) else 0)
            for value in self.yao_values
        )


def cast_hexagram(rng: random.Random) -> CastResult:
    """金钱卦起卦：掷六次铜钱自下而上成卦，动爻翻转得变卦。"""
    rolled: list[int] = [toss_yao(rng)[0] for _ in range(6)]
    yao = (
        rolled[0], rolled[1], rolled[2], rolled[3], rolled[4], rolled[5],
    )
    probe = CastResult(yao_values=yao, original=HEXAGRAMS[("乾", "乾")], changed=None)
    original = hexagram_of(probe.lines)
    changed: HexagramInfo | None = None
    if any(value in (6, 9) for value in yao):
        changed = hexagram_of(probe.changed_lines)
    return CastResult(yao_values=yao, original=original, changed=changed)

def format_cast_text(cast: CastResult) -> str:
    """把一次起卦渲染成聊天友好的中文文本（含爻象与变卦）。"""
    lines = ["🔮 金钱卦 · 诚心默念所问之事，六掷成卦：", ""]
    lines.append(f"本卦：{cast.original.name}")
    lines.append(f"卦意：{cast.original.gist}")
    lines.append(f"吉凶倾向：{cast.original.tendency}")
    lines.append("")
    lines.append("爻象（自下而上）：")
    for position, value in enumerate(cast.yao_values):
        lines.append(f"{_yao_label(value, position)}　{_yao_bar(value, value in (6, 9))}")
    if cast.changed is not None:
        lines.append("")
        lines.append(f"动爻化出变卦：{cast.changed.name}")
        lines.append(f"卦意：{cast.changed.gist}")
        lines.append(f"吉凶倾向：{cast.changed.tendency}")
        lines.append("（本卦示当下之势，变卦示事态去向）")
    lines.append("")
    lines.append("卦象仅供娱乐参考，路还是你自己走出来的～")
    return "\n".join(lines)
