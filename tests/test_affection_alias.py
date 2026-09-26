"""角色爱称映射回归（审查 O-07，2026-09-14）。

覆盖三面：
① 映射查询正反例 + 反查索引完整性（键全局唯一、爱称闭合回源角色）；
② 与小名自学零互抢——extract_learned_nickname 行为不受映射影响，
   「叫我龙哥」仍学本人小名，不解析成忌炎；
③ 纪律边界锁死——泛称（老公/老婆/媳妇）不落表；谐音未证实写法不落表；
   本名本身不是爱称。
"""

from plugins.bot_unified_runtime.domains.chat_reply.character.affinity import (
    _CHARACTER_AFFECTION_ALIASES,
    extract_learned_nickname,
    resolve_affection_alias,
)


def test_alias_resolution_positive() -> None:
    assert resolve_affection_alias("龙哥") == "忌炎"
    assert resolve_affection_alias("羊咩") == "安可"
    assert resolve_affection_alias("小道士") == "鉴心"
    assert resolve_affection_alias("芝士雪豹") == "凌阳"
    assert resolve_affection_alias("小汐子") == "今汐"
    assert resolve_affection_alias("离妃") == "长离"
    assert resolve_affection_alias("女特务") == "吟霖"
    assert resolve_affection_alias("大傻椿") == "椿"
    assert resolve_affection_alias("小西王") == "丹瑾"
    assert resolve_affection_alias("小卡") == "卡提希娅"
    assert resolve_affection_alias("大卡") == "卡提希娅"
    assert resolve_affection_alias("水母姐") == "坎特蕾拉"
    assert resolve_affection_alias("家主大人") == "坎特蕾拉"
    assert resolve_affection_alias("船长") == "布兰特"
    assert resolve_affection_alias("小狼") == "露帕"


def test_alias_resolution_negative() -> None:
    assert resolve_affection_alias("忌炎") is None  # 本名不是爱称
    assert resolve_affection_alias("椿") is None
    assert resolve_affection_alias("老婆") is None  # 泛称不落表（依玩家而定）
    assert resolve_affection_alias("老公") is None
    assert resolve_affection_alias("媳妇") is None
    assert resolve_affection_alias("三花") is None  # 谐音写法未证实，宁缺毋滥
    assert resolve_affection_alias("") is None
    assert resolve_affection_alias("   ") is None
    assert resolve_affection_alias("今天天气不错") is None


def test_alias_tolerates_surrounding_whitespace() -> None:
    assert resolve_affection_alias(" 龙哥 ") == "忌炎"
    assert resolve_affection_alias("大傻椿\t") == "椿"


def test_alias_index_integrity() -> None:
    """反查索引与源表闭合：源表展开条目与索引完全一致且键全局唯一。"""
    all_aliases = [
        alias
        for alias_tuple in _CHARACTER_AFFECTION_ALIASES.values()
        for alias in alias_tuple
    ]
    assert len(all_aliases) == len(set(all_aliases)), "爱称键必须全局唯一（防静默覆盖）"
    for character, alias_tuple in _CHARACTER_AFFECTION_ALIASES.items():
        for alias in alias_tuple:
            assert resolve_affection_alias(alias) == character, alias
    # 源表值必须是合法角色名集合（无非空约束外的脏数据）。
    for character in _CHARACTER_AFFECTION_ALIASES:
        assert character and character.strip() == character


def test_zero_interference_with_nickname_learning() -> None:
    """「叫我+爱称字样」仍是本人小名学习；含爱称但无触发词不学小名。"""
    assert extract_learned_nickname("以后叫我龙哥吧") == "龙哥"
    assert extract_learned_nickname("你可以叫我大傻椿哦") == "大傻椿"
    # 抽卡/第三人称语境：无「叫我」触发词 → 不学小名（爱称解析不得改变此行为）。
    assert extract_learned_nickname("我抽了个龙哥") is None
    assert extract_learned_nickname("大傻椿什么时候复刻") is None
    assert extract_learned_nickname("龙哥强还是小汐子强") is None


def test_alias_lookup_does_not_swallow_nickname_sentences() -> None:
    """整句/触发语不是爱称：查询返回 None，两条路径各管各的。"""
    assert resolve_affection_alias("叫我小岸吧") is None
    assert resolve_affection_alias("以后叫我龙哥吧") is None
