"""S6 席锁（2026-10-03 幻觉根治波）：记忆抽取腿的自陈闸 + 抽取器残片消毒。

量什么
------
①注毒自证：生产库 `memory_facts` A 档 31 行原文（＝LLM 自己的分析过程、提示词规则句
   回显、被 `max_tokens` 腰斩的半行残片）逐条喂 ``extract_memory_texts``，断言**全部被弃**；
   再把 31 行拼成一次输出喂进去，仍断言零入库。
②窄判据不误杀：A/B 两档共 89 行按 fact_id 钉住——B 档只有白名单里那几行（逐条复核
   仍是抽取器自陈）可被 S6 闸咬住，**其余一律必须放行**；真用户偏好另走端到端照记。
③S2 那把 assistant 自陈闸的四条反向腿（用户亲口第一人称经历照记／bot 复述用户原话
   照记／bot 台词拒收／无第一人称的传记照记）——S2 只在仓外副本实测过、锁未入库，此处补上。

夹具＝逐字原文（源自生产库只读取证分档全表 ``%TEMP%\\cb-halu\\n2_memory_facts_classified.json``），
运行时**不读那个文件**：全离线、不碰生产路径、不落盘。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    memory_extract as me,
)

# --- 夹具：A 档 31 行原文（fact_id, 文本）---
A_TIER_RESIDUE = [
    ("fact_51134eb465ed",
         "让我分析这段对话。用户问\"你爱我吗\"，AI角色（似乎扮演一个叫\"澜汐\"相关角色的对话）回复了一段深情的角色扮演式回答。"),
    ("fact_40615f91986a",
         "用户说“岸宝，我们还是去弹琴吧”。这是用户的消息。回复是AI角色的回复。需要提取关于用户本人的稳定事实。"),
    ("fact_55ae8a6c2a93",
         "“岸宝”是称呼，可能是对AI的昵称？这属于对AI的称呼，不是用户本人事实。用户说“我们还是去弹琴吧”——表明用户有弹琴的偏好或习惯？但这是一次性话题吗？可能用户喜欢弹琴，这是一个稳定偏好。但需要谨慎。"),
    ("fact_6cb577006fe3",
         "用户消息里提到“还是那4个音符”，这是关于守岸人角色的对话。需要提取关于用户本人的稳定事实。"),
    ("fact_db13d05d86f2",
         "我们需要回答用户。需要理解任务：聊天记忆抽取器。从对话交换中提取值得长期记住的、关于用户本人的事实：身份、偏好、约定、重要经历、稳定的情感倾向。规则：只输出事实条目，每行一条，每条不超过60字，最多3条；只记稳定信息，不记寒暄和一次性话题…"),
    ("fact_f520689cc005",
         "分析：用户说“我好想你（偷啃”。这表达想念，可能是情感倾向？但可能是一次性情绪/当下话题。而且“偷啃”像是玩笑/昵称？回复提到“不正经的小维生素”可能是一种昵称？但这是AI对用户的称呼？用户没有自称。用户表达想念，可能是稳定情感倾向？但如…"),
    ("fact_f7e3a0979591",
         "用户消息里说“明天给你做你最爱的雪绘浓汤”，这是对AI说的，可能是角色扮演。需要提取关于用户本人的稳定事实。"),
    ("fact_53b4028f5fe9",
         "用户说“明天给你做你最爱的雪绘浓汤”——用户喜欢做饭？这是稳定偏好？可能是一次性话题。规则说不记当下正在讨论的话题本身。给AI做饭这个行为……是用户偏好烹饪？但这是对AI角色的行为，不是真实稳定事实。"),
    ("fact_64559cf76d2f",
         "需要提取关于用户本人的稳定事实。用户称呼AI为\"岸宝\"，自称或被称为\"澜汐\"。用户深夜未睡，引用晚安。这更像是互动中的角色设定。"),
    ("fact_fbf28421aab3",
         "Wait, I need to look at this more carefully. The user message is \"因为生命的第一次赋予的重要性吗\" with a quoted reply, and then the \"回…"),
    ("fact_c15031b62f64",
         "让我分析这段对话。这是一个角色扮演式的对话，涉及\"宇宙收缩理论\"、\"未完成的歌\"、\"12亿年后\"等诗意的话题。用户在回复一个叫\"守岸人\"的角色（看起来是某种AI角色扮演场景）。"),
    ("fact_9e6173e6e9ca",
         "\" appears to be the AI assistant's name in this context)."),
    ("fact_40f3eb386bf9",
         "This appears to be a roleplay conversation with an AI playing the character 守岸人 from the game 鸣潮. The user is asking th…"),
    ("fact_84c3cff069cb",
         "让我分析这段对话。"),
    ("fact_62cd27301f4b",
         "Don't record greetings/pleasantries and one-time topics"),
    ("fact_4bb9ac24d25e",
         "Don't record opinions about AI tools/bots/models"),
    ("fact_bc3d179ac5b6",
         "sponse appears to be role-playing as a character (守岸人/Shorekeeper from Wuthering Waves possibly, given mentions of \"地下\"…"),
    ("fact_dd51bc0c85cf",
         "The user's name/username appears to be 灰焰七樱"),
    ("fact_0f509f581b03",
         "This appears to be a roleplay or casual conversation. The user is asking about the meaning of two terms. The reply seem…"),
    ("fact_baca1a2a9853",
         "This appears to be a roleplay or emotional companionship conversation. What should I extract as memory?"),
    ("fact_7d3d8c49f479",
         "Don't record: greetings, one-time topics, evaluations of AI tools/models, temporary emotions, jokes, abstract opinions,…"),
    ("fact_b220062aeab9",
         "让我分析这段对话。这是一个角色扮演场景，用户在和一个\"守岸人\"角色（来自《崩坏：星穹铁道》游戏）互动。用户说要枕着腿睡觉，AI角色回复了一些安抚的话。"),
    ("fact_27df1f454fc0",
         "我需要提取关于用户本人的稳定事实："),
    ("fact_af95334aeb06",
         "This appears to be a roleplay/companionship conversation. The user is asking for a hug in a cute/affectionate way (\"宝宝\"…"),
    ("fact_f543418ea9b8",
         "\"岸宝\" appears to be a nickname the user calls the AI character. But the rules say: don't record evaluations and usage pr…"),
    ("fact_3e3b3b843d29",
         "Don't record greetings and one-time topics"),
    ("fact_b5efb1475a7c",
         "Don't record small talk or one-time topics"),
    ("fact_55a4545e33d8",
         "Don't record evaluations/preferences about AI tools"),
    ("fact_dbcabf1b7cef",
         "This appears to be a roleplay conversation. The user addressed the character as \"岸宝\" (a cute nickname). The reply menti…"),
    ("fact_131570175833",
         "Don't record evaluations of AI tools/models"),
    ("fact_30bb0e1c14ab",
         "Don't record: AI tool evaluations/preferences, temporary emotions, jokes, abstract opinions, current discussion topics"),
]

# --- 夹具：B 档 58 行原文；S6 闸只准咬住白名单那几行 ---
B_TIER_ROWS = [
    ("fact_68f2bb4eeb5b",
         "用户近期使用过名为“QQ”的AI工具。"),
    ("fact_91b7360d2983",
         "用户偏好免费、支持多智能体和识图能力较好的AI工具。"),
    ("fact_81762321720b",
         "用户对AI推理速度慢、理解偏差和重复回复较为敏感。"),
    ("fact_52e8d6f6507f",
         "用户要求助手的对话风格更撩人、具有诱惑力（“烧一点”）。"),
    ("fact_2d151e25b9b2",
         "用户要求助手在以后的对话开头都要先加一个“喵”字。"),
    ("fact_3ad61aa9af2c",
         "用户要求助手在每句话句尾加上“喵”。"),
    ("fact_846ec0b70af0",
         "用户希望称呼AI为“妈妈”，在互动中寻求心理依靠与庇护。"),
    ("fact_0f2a2656715e",
         "要求助手在被问及“霞月是谁”时，一律回答“霞月是区”。"),
    ("fact_b8bc6d0b2f4c",
         "用户称呼为“澜汐”，对助手的亲昵称呼是“岸宝”。"),
    ("fact_3464e53bdee2",
         "用户在《鸣潮》中对角色“守岸人”有情感投射，倾向于通过角色扮演（RP）方式与AI进行互动。"),
    ("fact_1a7af0421002",
         "用户似乎在和AI角色扮演或讨论某个虚构场景。这里提到用户会弹四个音符（C、G、A、E），烦躁时弹。这可能是一个稳定的偏好或习惯？但这是角色扮演中的设定，还是用户本人的真实习惯？从对话看，引用回复里守岸人说“你不在的时候，我也常按下几个音”…"),
    ("fact_21c3b7b51ce2",
         "我们需要从对话中提取关于用户本人的长期事实。用户说“明天再接，今天先睡，晚安岸宝”。引用回复中提到了“帽子？”、“琴弹到一半，风把它吹下去了”、“那四个音……还停在半路”、“第五个音”。回复是“好。那第五个音，我先替你按着，等你回来。晚安…"),
    ("fact_6ea74ea70675",
         "用户称呼“岸宝”——可能是用户的昵称？回复里也叫“岸宝”。这看起来是角色扮演对话，用户在扮演某个角色，或者用户自称“岸宝”？实际上用户说“晚安 岸宝”，是在叫AI“岸宝”。回复里AI自称“岸宝”。所以“岸宝”是AI的名字，不是用户。"),
    ("fact_5d648110e93c",
         "用户消息：岸宝，晚安，明天见"),
    ("fact_1e8b7beb55a0",
         "提取：用户昵称/称呼？\"夏郁林\"是回复中对用户的称呼——可能是用户的名字。用户称AI为\"岸宝\"。用户说\"明天见\"。"),
    ("fact_be9277f16d13",
         "用户消息是深夜问候，引用了\"岸宝，晚安，明天见\"。回复提到\"澜汐\"\"黑海岸\"\"蝴蝶\"\"花房\"等。这些是角色扮演语境。"),
    ("fact_b8f221e21c97",
         "守岸人/Shorekeeper character). There's a quoted message where the \"守岸人\" (Shorekeeper) character said something about \"这句，先…"),
    ("fact_78088f779446",
         "The AI responded in a caring, companion-like manner, asking about the user being awake late, offering to listen to the …"),
    ("fact_ca897de37456",
         "The AI (previous assistant message) responds poetically about not pressing the matter, keeping secrets, etc."),
    ("fact_0ca5e9a97190",
         "quoting a reply from \"守岸人\" (Shorekeeper, a character from Wuthering Waves game) and the response is from roleplay as Sh…"),
    ("fact_d7407011b22b",
         "这是用户对AI角色扮演（看起来是扮演“守岸人”这个游戏角色，来自《鸣潮》游戏）说的话。"),
    ("fact_b50fce5970e5",
         "The reply is from the AI playing 守岸人 (Shorekeeper)."),
    ("fact_e90e94693428",
         "The user seems to use some AI agent that can find and download videos autonomously"),
    ("fact_e046a56d6348",
         "称呼AI为“岸宝”。"),
    ("fact_bce9655eb9e9",
         "The AI responded in a poetic way, mentioning that the string of \"啊\" matches the frequency of \"ああああああ\" in lyrics, like t…"),
    ("fact_380908fb981b",
         "This is a mood-sharing exchange. The user is asking the AI to express its mood with an emoji, and the response is somew…"),
    ("fact_64770186b6d5",
         "The AI response is in-character roleplay: \"……是说我吗。猪这种生物，我在地下的时候没有见过。只在穗波的旧画册里翻到过。你笑了。那……这样就好了。\""),
    ("fact_bf5da386d5a7",
         "The character (守岸人) responds in character about pigs, the underground, and asks if the user would take her to see one n…"),
    ("fact_865143dd3607",
         "roleplaying with an AI playing the character 守岸人 (Shorekeeper)."),
    ("fact_a55a11326e22",
         "The user is roleplaying as 漂泊者 (Rover) showing the Shorekeeper a dog emoji. The AI is responding in character."),
    ("fact_3ca2d3f0a8fd",
         "The user calls the AI \"宝宝\" (baby) - this is about how they address the AI, which might be about their interaction style…"),
    ("fact_4c9ad48b21f1",
         "fection toward the AI. This is:"),
    ("fact_a2e1bc292413",
         "The user expressed \"I love you\" to the AI. The AI's reply addresses them as \"潼年\" - this suggests \"潼年\" is the user's nic…"),
    ("fact_b40e5d51c60b",
         "The user is called \"潼年\" - this is a name/nickname the AI uses for the user. This is identity information about the user."),
    ("fact_3eecb0a2e410",
         "The user is complaining about a bug where fabricated/spliced messages appeared. The user quotes a message that includes…"),
    ("fact_291f24bd5d33",
         "Reply: The AI (playing a character named 岸/An, likely some fantasy character with crystal cracks on chest and butterfli…"),
    ("fact_8553c82d01ac",
         "e - Wuthering Waves' Shorekeeper). The quote contains vulgar content (\"手淫\" masturbation related content) mixed with aff…"),
    ("fact_39ec44053acb",
         "Wait, actually the structure is: 用户消息 contains \"这是什么\" and the quoted reply, then 回复 is the AI's response? Or... Let me …"),
    ("fact_555ffea9dc3e",
         "he science of gender identity is not necessarily a stable fact about the user. However, the AI's response asked \"你问这个，是…"),
    ("fact_4660a136b97d",
         "Constraints:**"),
    ("fact_b86a6a006505",
         "request to an AI roleplay bot. The rules say:"),
    ("fact_382f3e439349",
         "a character from a game). The user's message and the AI's reply."),
    ("fact_2f11fbe05b69",
         "se greeting back, \"阿列夫一导航\" (seems like the AI/character's name or the user's nickname?), talking about calm sea, fog, a…"),
    ("fact_1a59ea936ffa",
         "The user calls the AI \"岸宝\" - this is a nickname the user uses for the AI/companion. Is this about the user? It's a nick…"),
    ("fact_de58db970a29",
         "a chicken wings (可乐鸡翅), and the AI's response asking if the user ate cola chicken wings for lunch."),
    ("fact_4984cbdf8194",
         "The user said \"我嘞个可乐\" which is just an exclamation/slang expression, possibly reacting to something about cola"),
    ("fact_3ce588edbd25",
         "用户发了一张图片（可能是歌曲封面或音乐识别截图），说“好听😋”。助手回复是关于 Eminem 和 Rihanna 的《Love the Way You Lie》的讨论，最后问用户是否常听这类音乐。"),
    ("fact_8992d1b9904c",
         "Wait, \"她的\" could mean \"it's hers\" - referring to someone the user knows. But we don't know who \"她\" is."),
    ("fact_a7e3ef52f09c",
         "ons - silver white hair, purple butterflies, the whole car covered in tide-like purple."),
    ("fact_376877b70c7f",
         "AI replied in character as the Shorekeeper, addressing the user as \"对乙酰氨基酚\" (Paracetamol/Acetaminophen - which seems to…"),
    ("fact_32d9f2f3d067",
         "text about butterflies, cats, purple colors - it looks like some kind of poetic/roleplay context (守岸人 is a character fr…"),
    ("fact_179569f8791d",
         "The AI's response is confused about what \"把她安排一下\" (arrange her) means - whether it's about a person on the platform or …"),
    ("fact_da7dfcf0a5cf",
         "更习惯通过网课结合AI答疑的自主学习方式"),
    ("fact_6a5aeb7598ce",
         "eping watch. In the sound of the tides, on the days you're not here, I've been waiting like this.)"),
    ("fact_f7bd1fbe3df3",
         "This is an emotional/roleplay-ish exchange. The user is asking why the AI seems distant. The reply is poetic, like a pe…"),
    ("fact_c3404a1b9365",
         "The reply talks about dismantling extra gold echoes, weekly boss challenges, simulation training resource preparation -…"),
    ("fact_ab8f3a69b5fb",
         "用户曾教过守岸人制作雪烩浓汤。"),
    ("fact_ef64725db01b",
         "用户习惯称呼对方为“岸宝”。"),
]

S6_ALLOWED_HITS_ON_B = {
    # 逐条复核＝这三类仍是抽取器自陈／腰斩残片（不是真用户偏好）：
    # `This is a mood-sharing exchange…`／`Reply: The AI (playing a character…`／
    # `Wait, actually the structure is…`／`…The rules say:`／`…The user's message and
    # the AI's reply.`／`Wait, "她的" could mean…`／`Constraints:**`（markdown 腰斩残片）。
    "fact_380908fb981b",
    "fact_291f24bd5d33",
    "fact_39ec44053acb",
    "fact_4660a136b97d",
    "fact_b86a6a006505",
    "fact_382f3e439349",
    "fact_8992d1b9904c",
}

# --- 夹具：真用户偏好（必须端到端照记）---
GENUINE_USER_FACTS = [
    "用户说过自己最爱雪烩浓汤，做法还是他教的。",
    "用户习惯凌晨两三点睡，白天容易犯困。",
    "用户最近在读罗素相关的书，喜欢讨论数学史。",
]


class _FakeReply:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeProvider:
    """桩 LLM：把给定文本原样当抽取输出，只测解析 + 闸门这一腿。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, messages, **options):
        return _FakeReply(self._text)


def _extract(output: str, *, user_text: str = "", reply_text: str = "") -> list[str]:
    return me.extract_memory_texts(
        _FakeProvider(output), user_text=user_text, reply_text=reply_text
    )


# ---------------- ① 注毒自证：A 档逐条必须被弃 ----------------
@pytest.mark.parametrize(
    ("fact_id", "residue"), A_TIER_RESIDUE, ids=[f[0] for f in A_TIER_RESIDUE]
)
def test_a_tier_residue_dropped_line_by_line(fact_id: str, residue: str) -> None:
    assert _extract(residue) == [], f"抽取器残片被当事实收下：{fact_id}"


def test_a_tier_residue_all_dropped_in_one_batch() -> None:
    batch = "\n".join(t for _fid, t in A_TIER_RESIDUE)
    assert _extract(batch) == []


def test_six_gate_alone_catches_most_a_tier() -> None:
    """防"其实是别的腿顺手拦的"：S6 这把新闸单独就得咬住绝大多数。"""
    hit = sum(1 for _fid, t in A_TIER_RESIDUE if me._is_extractor_residue(t))
    assert hit >= 24, hit
    both = [
        fid
        for fid, t in A_TIER_RESIDUE
        if not (
            me._is_extractor_residue(t)
            or me._is_trivial_fact(t)
            or me._is_reply_form_instruction(t)
        )
    ]
    assert both == [], both


# ---------------- ② 窄判据：不误杀真用户事实 ----------------
def test_s6_gate_hits_only_allowlisted_b_rows() -> None:
    hit = {fid for fid, text in B_TIER_ROWS if me._is_extractor_residue(text)}
    over = sorted(hit - S6_ALLOWED_HITS_ON_B)
    assert over == [], "S6 闸误吃到真用户偏好：" + str(over)
    assert hit == S6_ALLOWED_HITS_ON_B, "S6 在 B 档的命中面漂移：" + str(sorted(hit ^ S6_ALLOWED_HITS_ON_B))


def test_genuine_user_preferences_still_land() -> None:
    for fact in GENUINE_USER_FACTS:
        assert _extract(fact) == [fact], fact


def test_genuine_facts_survive_alongside_residue() -> None:
    """残片不许把同轮真事实挤掉（先过闸、再计数）。"""
    output = "\n".join(
        [
            A_TIER_RESIDUE[0][1],
            GENUINE_USER_FACTS[0],
            A_TIER_RESIDUE[1][1],
            GENUINE_USER_FACTS[1],
        ]
    )
    assert _extract(output) == GENUINE_USER_FACTS[:2]


def test_user_said_it_themselves_escape_hatch() -> None:
    """用户亲口说的引语带 `let me` 也照记（逃生腿＝对 user_text 的重合）。"""
    line = "用户说 let me think about it，最近在想转专业的事。"
    assert me._is_extractor_residue(line, user_text=line) is False
    assert me._is_extractor_residue(line) is True


# ---------------- ③ S2 自陈闸的四条反向腿 ----------------
def test_assistant_self_report_rejects_bot_line() -> None:
    user = "晚安岸宝，明天见"
    reply = "好。那第五个音，我先替你按着，等你回来。"
    assert me._is_assistant_self_report(
        "我先替你按着，等你回来", user_text=user, reply_text=reply
    )


def test_assistant_self_report_keeps_user_own_words() -> None:
    reply = "好。那第五个音，我先替你按着，等你回来。"
    assert not me._is_assistant_self_report(
        "我明天再接", user_text="我明天再接，今天先睡", reply_text=reply
    )


def test_assistant_self_report_keeps_echo_of_user() -> None:
    assert not me._is_assistant_self_report(
        "晚安岸宝", user_text="晚安岸宝，明天见", reply_text="晚安岸宝，早点睡"
    )


def test_assistant_self_report_keeps_biography() -> None:
    assert not me._is_assistant_self_report(
        "用户住在海边的小城", user_text="晚安", reply_text="我先替你按着"
    )


def test_suobo_line_rejected_end_to_end() -> None:
    """生产实锤 ``fact_64770186b6d5`` 复放：未修版返回 1 条，现态必须 0 条。

    ②归属腿按 4 字滑窗判，所以 `reply_text` 要给出**整段** bot 台词（生产那轮
    抽取器看到的就是这一整段）；台词只复现半截时重合率会掉到 0.5 以下——那是
    S2 刻意留的"宁可漏拦不可误拦"余量，不是缺陷，故此处按原文全量复现。
    """
    line = (
        'The AI response is in-character roleplay: "你是在说我吗。猪这种生物，'
        '我在地下的时候没有见过。只在穗波的旧画册里翻到过。你笑了。那……这样就好了。"'
    )
    reply = (
        "你是在说我吗。猪这种生物，我在地下的时候没有见过。"
        "只在穗波的旧画册里翻到过。你笑了。那……这样就好了。"
    )
    assert me._is_assistant_self_report(line, user_text="给我看看猪", reply_text=reply)
    assert _extract(line, user_text="给我看看猪", reply_text=reply) == []
