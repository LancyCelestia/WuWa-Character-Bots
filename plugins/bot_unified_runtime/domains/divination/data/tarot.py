"""塔罗牌（纯计算，零第三方依赖）：78 张标准韦特牌堆 + 抽牌 + 牌阵。

- 22 张大阿卡纳：正位/逆位关键词 + 一句话释义（手写表）。
- 56 张小阿卡纳（权杖/圣杯/宝剑/星币 × 数字牌 Ace-10 + 侍从/骑士/王后/
  国王）：以「数字牌弧 + 花色领域」组合出关键词式释义，标志性牌
  （如宝剑三、星币四等）用手写覆盖，避免逐张机械拼接的呆板感。
- ``draw_cards(n, rng)``：不放回抽样，逆位概率约 0.5；传入同一个
  已播种 ``random.Random`` 结果可复现。
- 牌阵：单张指引、三张牌阵（过去/现在/未来）。
- 「每日一抽」：对 (日期, 用户标识) 做 SHA-256 派生种子，同一天同一
  用户永远抽到同一张牌。
- 文案为中性温暖向的娱乐指引；人格化包装由上层能力负责。
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date

__all__ = [
    "DECK",
    "DrawnCard",
    "TarotCard",
    "daily_card",
    "draw_cards",
    "format_single_text",
    "format_three_text",
    "single_guidance",
    "three_card_spread",
]

_SUITS: tuple[str, ...] = ("权杖", "圣杯", "宝剑", "星币")
_NUMBER_RANKS: tuple[str, ...] = (
    "Ace", "二", "三", "四", "五", "六", "七", "八", "九", "十",
)
_COURT_RANKS: tuple[str, ...] = ("侍从", "骑士", "王后", "国王")


@dataclass(frozen=True)
class TarotCard:
    """一张塔罗牌：名称 + 正逆位关键词与一句话释义。"""

    name: str
    arcana: str  # "大阿卡纳" 或花色名（权杖/圣杯/宝剑/星币）
    rank: str
    upright_keywords: str
    reversed_keywords: str
    upright_hint: str
    reversed_hint: str


# 22 张大阿卡纳：(名称, 正位关键词, 逆位关键词, 正位一句话, 逆位一句话)。
_MAJOR_ARCANA: tuple[tuple[str, str, str, str, str], ...] = (
    ("愚者", "新开始、纯真、冒险", "鲁莽、犹豫、不设防",
     "带着信任迈出第一步，路会为你展开。", "出发前先看看脚下的路，别把冲动当勇气。"),
    ("魔术师", "行动力、资源、显化", "操控、空谈、心口不一",
     "你手里的牌够用了，把它们用起来。", "先对齐动机，再谈技巧。"),
    ("女祭司", "直觉、静默、内在智慧", "忽视直觉、秘密、疏离",
     "答案在你心里安静地放着，去听它。", "别让喧嚣盖过心底那个小声音。"),
    ("皇后", "丰饶、滋养、感官之美", "过度付出、控制、停滞",
     "温柔地照料生活，丰盛自然会来。", "先把自己照顾好，再谈照顾别人。"),
    ("皇帝", "秩序、权威、稳固", "僵化、专断、失序",
     "搭好框架和边界，事情就稳了。", "松一松手里的缰绳，别让规则吃掉人。"),
    ("教皇", "传统、指引、学习", "教条、反叛、盲从",
     "向有经验的人请教，少走弯路。", "别人的答案未必是你的答案。"),
    ("恋人", "结合、选择、心意相通", "失衡、诱惑、分歧",
     "认真的选择本身就是承诺。", "先诚实面对自己想要什么。"),
    ("战车", "意志、胜利、前进", "失控、蛮干、方向迷失",
     "握紧缰绳，胜利属于坚持的人。", "停下来校准方向，不丢人。"),
    ("力量", "勇气、柔和的力量、耐心", "自我怀疑、失控、急躁",
     "温柔而坚定，比用力更长久。", "善待内心的那只狮子，也善待自己。"),
    ("隐士", "内省、独处、寻求真理", "孤立、逃避、过度封闭",
     "给自己一段安静时光，光会从裂缝进来。", "偶尔走出来，让别人看见你。"),
    ("命运之轮", "转机、循环、顺势而为", "抗拒变化、时运不济、反复",
     "轮子转起来了，搭上它。", "低谷也是轮的一部分，稳住。"),
    ("正义", "公正、因果、清晰的判断", "偏颇、逃避责任、失衡",
     "坦诚地权衡，答案会清晰起来。", "该认的账认了，心就轻了。"),
    ("倒吊人", "暂停、换个视角、臣服", "僵持、无谓牺牲、拖延",
     "暂时悬停不是停滞，是换一个角度看世界。", "别把等待熬成自我消耗。"),
    ("死神", "结束与新生、放下、蜕变", "抗拒结束、拖延、原地踏步",
     "让该结束的结束，新的才能开始。", "紧紧抓着的，正把你拖住。"),
    ("节制", "平衡、调和、耐心流动", "极端、失衡、内耗",
     "慢慢调和，水到渠成。", "别在两个极端之间来回荡。"),
    ("恶魔", "束缚、欲望、成瘾模式", "挣脱、觉察、断舍离",
     "看清那条锁链，松开它就在一念之间。", "你比自己以为的更自由。"),
    ("塔", "突变、旧结构崩塌、真相", "逃避剧变、延迟崩塌、惊魂未定",
     "塌下来的是靠不住的，留下来的是真地基。", "与其等雷劈，不如自己拆。"),
    ("星星", "希望、疗愈、灵感", "失望、信心不足、雾里看花",
     "雨停了，抬头就能看见星星。", "允许自己慢慢恢复，别急着发光。"),
    ("月亮", "潜意识、不安、迷雾", "迷雾散去、真相浮现、情绪缓释",
     "走夜路时慢一点，但别停。", "天快亮了，很多担心其实不会发生。"),
    ("太阳", "活力、成功、喜悦", "暂时的阴天、过度乐观、迟到的认可",
     "大大方方地晒太阳，你值得。", "乌云只是路过，别关上窗。"),
    ("审判", "觉醒、召唤、重新出发", "自我批判、逃避呼唤、停滞",
     "听到内心的召唤了，就回应它。", "别再用旧账审判现在的自己。"),
    ("世界", "完成、圆满、整装待发", "未竟之事、收尾拖延、意难平",
     "一个圆满的句号，也是新旅程的起点。", "把最后一小块拼图放上去再庆祝。"),
)

# 数字牌通用弧线：(正位关键词, 逆位关键词, 正位一句话, 逆位一句话)。
_RANK_ARCS: dict[str, tuple[str, str, str, str]] = {
    "Ace": ("开端、火花、潜力", "错失时机、潜能未燃、犹豫",
            "一粒种子落在你手上了。", "别让这颗新芽等太久。"),
    "二": ("权衡、伙伴、双向流动", "犹豫、失衡、貌合神离",
           "两个选择之间，藏着你的优先级。", "先摆平内心，再摆平事情。"),
    "三": ("协作、初见成效、扩展", "三角难题、插手过多、小挫折",
           "人多力量大，让合适的人进来。", "把话摊开说，误会就散了。"),
    "四": ("稳固、休整、守成", "不安于室、守过头、倦怠",
           "稳稳捧住手里的，歇口气。", "握得太紧的东西，会从指缝漏走。"),
    "五": ("冲突、失落、磨合", "和解、走出低谷、释怀",
           "这段坡有点陡，但不是绝路。", "回头看看，援手一直都在。"),
    "六": ("馈赠、过渡、善意往来", "旧账、不平衡的给予、怀旧",
           "有人朝你伸出手，接住它。", "翻篇不是遗忘，是轻装。"),
    "七": ("评估、耐心、谋定后动", "急功近利、自我怀疑、半途而废",
           "果实快熟了，再等等。", "别在浇了三个月的树底下换坑。"),
    "八": ("加速、精进、专注推进", "用力过猛、方向跑偏、自我设限",
           "加速的时机到了，全神贯注。", "快不等于对，校准再踩油门。"),
    "九": ("接近达成、自足、守候", "警觉过度、孤独、勉强硬撑",
           "离终点只差最后一步。", "你已走得够远，值得被支持。"),
    "十": ("圆满、收尾、承上启下", "过载、尾声的杂音、家族旧题",
           "这一章圆满了，值得好好收尾。", "卸下不属于你的行李再上路。"),
    "侍从": ("学习、试探、新消息", "三分钟热度、幼稚、消息延误",
             "以学习者的姿态入场，进步最快。", "慢慢来，别急着当大人。"),
    "骑士": ("追逐、推进、鲜明的姿态", "冒进、绕路、心浮气躁",
             "认准方向就策马向前。", "偶尔勒马看看地图。"),
    "王后": ("涵容、内掌、成熟的力量", "过度操劳、情绪淹没、越界",
             "把柔软活成一种力量。", "先接住自己，再接住别人。"),
    "国王": ("掌控、外掌、定盘星", "僵化、强势、失焦",
             "稳坐中军帐，把局面立起来。", "权威不是音量，是分寸。"),
}

# 花色领域：权杖-行动事业、圣杯-情感关系、宝剑-思维沟通、星币-物质实务。
_SUIT_DOMAINS: dict[str, tuple[str, str]] = {
    "权杖": ("事业与行动", "热情耗散"),
    "圣杯": ("情感与关系", "情绪淤积"),
    "宝剑": ("思维与沟通", "思绪纠缠"),
    "星币": ("物质与实务", "现实动摇"),
}

# 标志性小阿卡纳手写覆盖：(花色, 牌名) -> (正位关键词, 逆位关键词, 正位句, 逆位句)。
_MINOR_OVERRIDES: dict[tuple[str, str], tuple[str, str, str, str]] = {
    ("权杖", "三"): ("远见、拓展、船已启航", "视野受限、计划搁浅",
                     "把旗插到更远的海岸。", "先看清风向再扬帆。"),
    ("权杖", "十"): ("负重前行、责任成山", "放下、分担、卸载",
                     "你扛的太多了，理一份清单。", "允许别人替你拿一些。"),
    ("圣杯", "二"): ("互相奔赴、心意相通", "失衡的关系、错位的表达",
                     "两颗心好好对了个暗号。", "把话说开，别靠猜。"),
    ("圣杯", "十"): ("情感圆满、其乐融融", "貌合神离、理想化",
                     "彩虹下的一家人，好好珍惜。", "幸福不必完美才作数。"),
    ("宝剑", "三"): ("心碎、言之伤人", "疗愈、原谅、雨过天晴",
                     "这句话很疼，但它会过去。", "把剑拔出来，伤口开始愈合。"),
    ("宝剑", "十"): ("谷底、尘埃落定", "恢复、最坏的已过去",
                     "夜再长，也已经到最深处了。", "天光就在身后，起身吧。"),
    ("星币", "四"): ("守住成果、安全感", "守财、僵化、怕失去",
                     "稳稳握住属于自己的。", "抓太紧的沙，漏得更快。"),
    ("星币", "九"): ("从容自足、自己挣来的优雅", "依赖、虚饰、透支",
                     "你亲手打理的花园正开花。", "别让面子透支里子。"),
}


def _build_deck() -> tuple[TarotCard, ...]:
    """构建 78 张标准韦特牌堆（22 大阿卡纳 + 56 小阿卡纳）。"""
    cards: list[TarotCard] = []
    for name, u_kw, r_kw, u_hint, r_hint in _MAJOR_ARCANA:
        cards.append(
            TarotCard(
                name=name,
                arcana="大阿卡纳",
                rank=name,
                upright_keywords=u_kw,
                reversed_keywords=r_kw,
                upright_hint=u_hint,
                reversed_hint=r_hint,
            )
        )
    for suit in _SUITS:
        domain, domain_rev = _SUIT_DOMAINS[suit]
        for rank in _NUMBER_RANKS + _COURT_RANKS:
            override = _MINOR_OVERRIDES.get((suit, rank))
            arc = _RANK_ARCS[rank]
            if override is not None:
                u_kw, r_kw, u_hint, r_hint = override
                u_kw, r_kw = f"{u_kw}（{domain}）", f"{r_kw}（{domain_rev}）"
            else:
                u_kw = f"{arc[0]}·{domain}"
                r_kw = f"{arc[1]}·{domain_rev}"
                u_hint, r_hint = arc[2], arc[3]
            cards.append(
                TarotCard(
                    name=f"{suit}{rank}",
                    arcana=suit,
                    rank=rank,
                    upright_keywords=u_kw,
                    reversed_keywords=r_kw,
                    upright_hint=u_hint,
                    reversed_hint=r_hint,
                )
            )
    return tuple(cards)


DECK: tuple[TarotCard, ...] = _build_deck()


@dataclass(frozen=True)
class DrawnCard:
    """一次抽牌结果：牌 + 是否逆位 + 位次标签（如「过去」）。"""

    card: TarotCard
    is_reversed: bool
    position: str = ""

    @property
    def orientation(self) -> str:
        return "逆位" if self.is_reversed else "正位"

    @property
    def keywords(self) -> str:
        return self.card.reversed_keywords if self.is_reversed else self.card.upright_keywords

    @property
    def hint(self) -> str:
        return self.card.reversed_hint if self.is_reversed else self.card.upright_hint


def draw_cards(
    n: int, rng: random.Random, *, allow_reversed: bool = True
) -> list[DrawnCard]:
    """从 78 张牌堆不放回抽 ``n`` 张，逆位概率约 0.5。"""
    if n < 1 or n > len(DECK):
        raise ValueError(f"抽牌数量需在 1-{len(DECK)} 之间，收到 {n}")
    picked = rng.sample(DECK, n)
    return [
        DrawnCard(card=card, is_reversed=allow_reversed and rng.random() < 0.5)
        for card in picked
    ]


def single_guidance(rng: random.Random) -> DrawnCard:
    """单张指引牌阵。"""
    return draw_cards(1, rng)[0]


_THREE_CARD_POSITIONS: tuple[str, str, str] = ("过去", "现在", "未来")


def three_card_spread(rng: random.Random) -> list[DrawnCard]:
    """三张牌阵：过去 / 现在 / 未来。"""
    drawn = draw_cards(3, rng)
    return [
        DrawnCard(card=item.card, is_reversed=item.is_reversed, position=position)
        for position, item in zip(_THREE_CARD_POSITIONS, drawn)
    ]


def daily_card(day: date, user_id: str) -> DrawnCard:
    """每日一抽：同一天同一用户永远同一张牌（含正逆位）。

    种子由 SHA-256("tarot-daily|日期|用户标识") 派生，与请求顺序无关。
    """
    seed_material = f"tarot-daily|{day.isoformat()}|{user_id}".encode()
    digest = hashlib.sha256(seed_material).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    return draw_cards(1, rng)[0]


def _render_card(drawn: DrawnCard) -> str:
    prefix = f"【{drawn.position}】" if drawn.position else ""
    return (
        f"{prefix}{drawn.card.name}（{drawn.orientation}）\n"
        f"关键词：{drawn.keywords}\n"
        f"{drawn.hint}"
    )


def format_single_text(drawn: DrawnCard) -> str:
    """单张指引的聊天文本渲染。"""
    return f"🔮 为你抽到的指引牌：\n\n{_render_card(drawn)}\n\n愿这张牌陪你走今天这一段。"


def format_three_text(spread: list[DrawnCard]) -> str:
    """三张牌阵（过去/现在/未来）的聊天文本渲染。"""
    if len(spread) != 3:  # pragma: no cover - 内部约定固定三张
        raise ValueError("三张牌阵需要恰好三张牌")
    lines = ["🔮 三张牌阵（过去 · 现在 · 未来）：", ""]
    lines.extend(_render_card(item) for item in spread)
    lines.append("")
    lines.append("过去的伏笔铺成现在，未来还在你手里。")
    return "\n".join(lines)
