"""Deterministic chat presentation; never applied to admin/config or media payloads.

No model calls. Preserve words, URLs, numbers and paragraph boundaries while
removing presentation syntax. Common TeX is verbalized, not evaluated; unknown
commands remain named rather than being silently discarded.
"""
from __future__ import annotations

import html
import re

from plugins.bot_unified_runtime.domains.core.search.source_authority import (
    sanitize_src_markers,
)

PLAIN_TEXT_VERSION = "chat_plain_text:v1"
# TeX token 提阶为模块级编译（热路径压榨项）：_math_text 逐字符循环内此前
# 每次 re.match 都要过 re 模块缓存查找；长公式一段上百次。
_TEX_TOKEN_RE = re.compile(r"\\([A-Za-z]+|.)", re.DOTALL)
_TEX_COMMAND_NAME_RE = re.compile(r"\\([A-Za-z]+)")
_QUOTES = str.maketrans("", "", '"“”„‟「」『』«»‹›')
_COMMANDS = {
    "alpha": "阿尔法", "beta": "贝塔", "gamma": "伽马", "theta": "西塔",
    "pi": "圆周率", "infty": "无穷大", "epsilon": "艾普西隆",
    "delta": "德尔塔", "Delta": "德尔塔", "lambda": "拉姆达",
    "times": "乘以", "cdot": "乘以", "div": "除以", "pm": "加或减",
    "le": "小于或等于", "leq": "小于或等于", "ge": "大于或等于",
    "geq": "大于或等于", "neq": "不等于", "approx": "约等于",
    "to": "趋向", "rightarrow": "指向", "Rightarrow": "推出",
    "in": "属于", "notin": "不属于", "cup": "并集", "cap": "交集",
    "sin": "正弦", "cos": "余弦", "tan": "正切", "log": "对数", "ln": "自然对数",
    "forall": "对于所有", "exists": "存在", "partial": "偏微分",
    "ldots": "……", "cdots": "……", "quad": " ", "qquad": " ",
}
_OPERATORS = {"+": " 加 ", "-": " 减 ", "=": " 等于 ", "*": " 乘以 ",
              "/": " 除以 ", ">": " 大于 ", "<": " 小于 ", "&": "，"}


def _group(text: str, start: int) -> tuple[str, int]:
    while start < len(text) and text[start].isspace():
        start += 1
    if start == len(text):
        return "", start
    if text[start] != "{":
        return text[start], start + 1
    depth = 1
    end = start + 1
    while end < len(text):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:end], end + 1
        end += 1
    return text[start + 1:], end


def _math_text(text: str, depth: int = 0) -> str:
    if depth > 20:
        return "公式嵌套过深，无法可靠转换"
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            match = _TEX_TOKEN_RE.match(text[i:])
            if match is None:
                out.append("反斜线")
                i += 1
                continue
            command = match[1]
            i += len(match[0])
            if command in {"frac", "dfrac", "tfrac"}:
                numerator, i = _group(text, i)
                denominator, i = _group(text, i)
                out.append(f"分子为（{_math_text(numerator, depth + 1)}）、分母为（{_math_text(denominator, depth + 1)}）的分数")
            elif command == "sqrt":
                order = ""
                if i < len(text) and text[i] == "[":
                    end = text.find("]", i + 1)
                    if end >= 0:
                        order, i = text[i + 1:end], end + 1
                value, i = _group(text, i)
                label = "平方根" if not order else f"{_math_text(order, depth + 1)}次方根"
                out.append(f"（{_math_text(value, depth + 1)}）的{label}")
            elif command in {"sum", "prod", "int", "lim"}:
                bounds = []
                while i < len(text) and (text[i].isspace() or text[i] in "_^" ):
                    if text[i].isspace():
                        i += 1
                        continue
                    label = "下界" if text[i] == "_" else "上界"
                    bound, i = _group(text, i + 1)
                    bounds.append(label + "为" + _math_text(bound, depth + 1))
                label = {"sum": "求和", "prod": "连乘", "int": "积分", "lim": "取极限"}[command]
                out.append(label + ("（" + "，".join(bounds) + "）" if bounds else "") + "：")
            elif command in {"text", "mathrm", "mathbf", "operatorname", "mathit", "mathbb"}:
                value, i = _group(text, i)
                out.append(value if command == "text" else _math_text(value, depth + 1))
            elif command in {"left", "right", "big", "Big", "displaystyle"}:
                continue
            elif command in {",", ";", "!", " ", "\\"}:
                out.append(" ")
            else:
                out.append(_COMMANDS.get(command, f"公式命令 {command}"))
        elif char in "_^":
            value, i = _group(text, i + 1)
            value = _math_text(value, depth + 1)
            if char == "_":
                out.append(f"（下标为{value}）")
            else:
                out.append({"2": "的平方", "3": "的立方"}.get(value, f"的（{value}）次方"))
        elif char == "{":
            value, i = _group(text, i)
            out.append("（" + _math_text(value, depth + 1) + "）")
        else:
            out.append(_OPERATORS.get(char, "）" if char == "}" else char))
            i += 1
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


# Markdown 表格分隔行（---|---）判定：热路径压榨项，提为模块级编译，
# 出站归一每条文本都会进 _table_text。
_TABLE_SEP_RE = re.compile(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*")


def _table_text(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        if (index + 1 < len(lines) and "|" in lines[index]
                and _TABLE_SEP_RE.fullmatch(lines[index + 1])):
            headers = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if len(cells) != len(headers):
                    result.append("；".join(cells))
                else:
                    result.append("；".join(f"{key}：{value}" for key, value in zip(headers, cells, strict=True)))
                index += 1
        else:
            result.append(lines[index])
            index += 1
    return "\n".join(result)


# 行级 TeX 兜底规则只命中这几种带参数的算子命令；转换时只替换命令 token，
# 行内其余文字原样保留（整行跑 _math_text 会把普通数学词句一起改写）。
_LINE_TEX_COMMAND_RE = re.compile(r"\\(?:frac|dfrac|sqrt|sum|int|prod|lim)\b")
_TEX_OPERATOR_LABELS = {"sum": "求和", "prod": "连乘", "int": "积分", "lim": "取极限"}


def _convert_single_tex_command(text: str) -> tuple[str, int]:
    """转换行首的一个 TeX 命令 token（含参数组），返回 (转换文本, 消费长度)。"""
    match = _TEX_COMMAND_NAME_RE.match(text)
    if match is None:
        return text, 0
    command = match[1]
    index = match.end()
    if command in {"frac", "dfrac"}:
        numerator, index = _group(text, index)
        denominator, index = _group(text, index)
        return (
            f"分子为（{_math_text(numerator)}）、分母为（{_math_text(denominator)}）的分数",
            index,
        )
    if command == "sqrt":
        order = ""
        if index < len(text) and text[index] == "[":
            end = text.find("]", index + 1)
            if end >= 0:
                order, index = text[index + 1 : end], end + 1
        value, index = _group(text, index)
        label = "平方根" if not order else f"{_math_text(order)}次方根"
        return f"（{_math_text(value)}）的{label}", index
    # sum / prod / int / lim：带上/下界算子；算子体不在此转换。
    bounds: list[str] = []
    while index < len(text) and (text[index].isspace() or text[index] in "_^"):
        if text[index].isspace():
            index += 1
            continue
        label = "下界" if text[index] == "_" else "上界"
        bound, index = _group(text, index + 1)
        bounds.append(label + "为" + _math_text(bound))
    head = _TEX_OPERATOR_LABELS[command]
    return head + ("（" + "，".join(bounds) + "）" if bounds else "") + "：", index


def _convert_line_tex_tokens(line: str) -> str:
    pieces: list[str] = []
    consumed = 0
    for match in _LINE_TEX_COMMAND_RE.finditer(line):
        start = match.start()
        if start < consumed:
            continue
        pieces.append(line[consumed:start])
        converted, length = _convert_single_tex_command(line[start:])
        pieces.append(converted)
        consumed = start + length
    pieces.append(line[consumed:])
    return "".join(pieces)


def naturalize_chat_text(text: str) -> str:
    """Idempotent presentation conversion for natural chat, not arbitrary code."""
    value = html.unescape(text or "").replace("\r\n", "\n").replace("\u200b", "")
    # Keep link destinations exactly; markdown labels become readable text.
    value = re.sub(r"!?\[([^\]\n]*)\]\((https?://[^\s]+?)\)", r"\1（\2）", value)
    value = re.sub(r"<(https?://[^<>\s]+)>", r"\1", value)
    urls: list[str] = []
    def protect(match: re.Match[str]) -> str:
        urls.append(match[0])
        return f"\ue000{len(urls) - 1}\ue001"
    value = re.sub(r"https?://[^\s<>\"“”）]+", protect, value)
    # Remove fences, retaining their contents. Explicit TeX fences are verbalized.
    value = re.sub(r"```(?:latex|tex|math)\s*\n(.*?)```", lambda m: _math_text(m[1]), value, flags=re.DOTALL)
    value = re.sub(r"(?m)^\s*(?:```|~~~)[^\n]*$", "", value)
    # 行内 $...$ 公式：两侧禁邻字母/数字，避免把“价格 $5 和 $10”这类
    # 货币写法误判成公式（开 $ 后不得紧跟空白，闭 $ 后不得紧跟字母/数字）。
    # 守卫必须写成 ASCII 类 `[A-Za-z0-9_]` 而**不是** `\w`：Python 的 `\w` 对
    # str 是 Unicode 语义，汉字本身就是 `\w`，于是「$E=mc^2$是爱因斯坦…」
    # 这类**中文行文里最常见的写法**（闭 $ 紧邻汉字、无空格）会被误判成
    # 货币而跳过转换，LaTeX 原文直接漏进回复（评审 M2 回归）。
    value = re.sub(
        r"\$\$(.*?)\$\$|\\\[(.*?)\\\]|\\\((.*?)\\\)|(?<![\\$A-Za-z0-9_])\$(?!\s)([^$\n]+?)(?<!\s)\$(?![A-Za-z0-9_$])",
        lambda m: _math_text(next(g for g in m.groups() if g is not None)),
        value,
        flags=re.DOTALL,
    )
    value = re.sub(
        r"(?m)^.*\\(?:frac|dfrac|sqrt|sum|int|prod|lim)\b.*$",
        lambda m: _convert_line_tex_tokens(m[0]),
        value,
    )
    value = _table_text(value)
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s+|(?m:^\s*(?:>\s*)+)", "", value)
    value = re.sub(r"(?m)^\s*[-+*]\s+(?:\[[ xX]\]\s*)?", "", value)
    value = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$", "", value)
    value = re.sub(r"\*\*(.*?)\*\*|__(.*?)__|~~(.*?)~~|`([^`]+)`", lambda m: next(g for g in m.groups() if g is not None), value, flags=re.DOTALL)
    value = re.sub(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)", r"\1", value)
    value = re.sub(r"</?(?:b|strong|i|em|code|p|br|div|span)\b[^>]*>", lambda m: "\n" if m[0].startswith(("<br", "</p", "</div")) else "", value)
    value = value.translate(_QUOTES)
    # Apostrophes inside English words (don't / I'm) remain meaningful.
    value = re.sub(r"(?<![A-Za-z])['‘’]|['‘’](?![A-Za-z])", "", value)
    value = re.sub(r"\\([*_`#\[\]])", r"\1", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    for index, url in enumerate(urls):
        value = value.replace(f"\ue000{index}\ue001", url)
    return value

# 去 AI 味（说人话）：聊天回复里高频的开场白/收尾客套/总结腔，确定性剥离。
_HUMANIZE_OPENING_RE = re.compile(
    r"^(?:好的[！，,。~ ]*|当然[！，,。~ ]*(?:可以|没问题)[！，,。~ ]*|以下是|这是一份|没错[！，,。~ ]*|嗯[！，,。~ ]*|明白了[！，,。~ ]*)+"
)
_HUMANIZE_CLOSING_RE = re.compile(
    r"(?:希望(?:这|以上)(?:些)?(?:内容)?(?:能)?(?:帮|对你有所)(?:到)?(?:助)?(?:你)?[！。~\s]*)+$|"
    r"(?:以上(?:就是|是).{0,12}全部内容[。！~\s]*)+$|"
    # 「总之…」只剥离**纯收尾客套**。不得把后面的实质指令一起吃掉（评审 M19）：
    # 旧写法 `(?:…|记得|欢迎|祝|喜欢的话|一起)[\s\S]{0,40}$` 会把
    # 「总之记得明天早上八点叫我，别睡过头」整段删除 → 时间点与动作丢失。
    # 收窄为：只认「希望/以上就是/喜欢的话」这类无信息量的收尾语；且其后
    # 40 字内不得出现时间/数字/动作宾语等可执行信息。
    r"(?:总之|综上所述|总结一下|总的来说)[，,：:]?"
    r"(?:希望|以上就是|喜欢的话)"
    r"(?![^。！？\n]{0,40}(?:\d|点|明天|后天|早上|中午|晚上|叫我|提醒|别忘|记得|一起|帮我))"
    r"[^。！？\n]{0,40}[。！~\s]*$|"
    r"(?:如果还有(?:其他)?(?:问题|疑问)[，,]?.{0,20}(?:问我|告诉我|联系我|随时)[。！~\s]*)+$"
)

# 内心状态保密红线：LLM 偶尔会把好感度/心情的内部数值当聊天说出口，数值
# 泄漏瞬间机器感拉满——态度只能通过行为体现，数值一律打码（拟人化整合报告裁决）。
# 连接词用有界枚举而非通配，避免误伤"好感度排行榜前3名"这类正常表述。
_INNER_STATE_NUM_RE = re.compile(
    r"(好感度|亲密度|信任度|趣味相投|心情值|affinity|valence|arousal)"
    r"\s*(?:值|分数|分)?\s*"
    r"(?:(?:已经|已|至少|只有|才|高达|达到|达|是|为|现在|[+加:：=]){1,2})?\s*"
    r"[-+]?\d+(?:\.\d+)?(?:\s*分|\s*%|%)?"
)

# 句中 AI 味短语替换（2026-10-06 补：用户实锤"结论是/接住你/给出一个结论"等）：
# 提示词面已加禁令（chat._RUNTIME_ANSWER_RULES），本件是出站侧兜底——LLM 偶发
# 绕不过禁令时在这里洗掉。顺序：长模式先匹配，避免被短模式截断。
_AI_FLAVOR_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "给出一个结论" → 直接去掉，后面通常跟 "：" 或 "是" 自成句。
    (re.compile(r"给出\s*一个\s*结论[，,：:]?\s*"), ""),
    # "结论是" → "答案是"（去掉报告体，保留语义）。
    (re.compile(r"结论是"), "答案是"),
    # "接住你" 族（情感语境高频，字面"接住物体"罕见）→ 去掉 AI 治疗腔。
    (re.compile(r"被你接住"), "被你理解"),
    (re.compile(r"稳稳接住"), "好好接住"),
    (re.compile(r"一起接住"), "一起感受"),
    (re.compile(r"接住你"), ""),
    # 报告体/论文腔连接词。
    (re.compile(r"值得注意的是[，,]?\s*"), ""),
    (re.compile(r"需要指出的是[，,]?\s*"), ""),
    (re.compile(r"从[某种这]+意义上[来说来讲来看]*[，,]?\s*"), ""),
    # 客服腔收尾（行锚 _HUMANIZE_CLOSING_RE 漏掉的句中形态）。
    (re.compile(r"希望(?:这|以上)?(?:些)?(?:能)?帮到你"), ""),
    (re.compile(r"如果还有(?:其他)?问题[，,]?随时问我"), ""),
)


def _redact_inner_state_number(match: re.Match[str]) -> str:
    name = match.group(1) or "内心状态"
    return f"{name}…保密"


# 已退役（2026-09-30 W3 出站打码扩谱收尾席）：本件此前被夹带过一枚
# ``flatten_article_scaffolding``（剥行首编号/项目符号的「词条骨架压平」），
# 与打码无关、判据不可收敛，实测四类误伤全在人格回复的必经路上：
# ①``一切都会好的`` → ``切都会好的``、``二十三日见`` → ``日见``
#   （行首那一段字符类不要求后接分隔符，第一个汉字就被吃掉）；
# ②``1.5 倍速`` → ``5 倍速``；③排行榜行首名次 ``1. 张三`` 被剥；
# ④命中骨架时**整片空行被吞**（``\n\n`` → ``\n``）。
# 第④条与本件的段落契约面重叠：出站段间换行的唯一真身是
# ``domains/render/roleplay.py:normalize_paragraph_breaks``（B08
# outbound-copy/paragraph-breaks 在册承诺「段间恒定单换行」），骨架压平在
# ``humanize_reply`` 里另起一本空行账＝同一件事两处实现、且它先跑，
# 于是「谁折叠空行」按输入形态漂移。它该在的地方是**知识库接地块的产出侧**
# （提示词腿 ``chat._KB_RECITAL_RULE_LINE`` 已在册，HANDBOOK「反照本宣科令」条目
# 记的是「只验不建」），不是出站咽喉。无处可迁 ⇒ 整块撤销，
# 反例锁随件同批撤（退役要文件＋账本行同批）。
def humanize_reply(text: str) -> str:
    """剥离聊天回复的 AI 客套开场与总结腔；不改变事实与语义。

    只做**行内**改写：不删行、不折叠空行、不改行首序号（段间换行归
    ``roleplay.normalize_paragraph_breaks``，行首 markdown 归 ``naturalize_chat_text``）。
    """
    value = (text or "").strip()
    if not value:
        return value
    value = _HUMANIZE_OPENING_RE.sub("", value).strip()
    value = _HUMANIZE_CLOSING_RE.sub("", value).strip()
    value = _INNER_STATE_NUM_RE.sub(_redact_inner_state_number, value)
    for pattern, replacement in _AI_FLAVOR_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    return value or (text or "").strip()


# --- 本机信息外泄红线（输出侧） -----------------------------------------------
# 模型被诱导复述 .env / 本机文件路径 / 凭据时，在发送前做确定性打码。
# 审查 F-01（2026-09-14）：原版只覆盖三种高置信形态（BOT_XXX= 赋值 / sk- 类
# key / Windows 盘符绝对路径），URL userinfo、Bearer token、JWT 三段式、
# 裸键值对（sendkey=x / token=x / key=值）全部漏网，以下逐形态补齐；
# 每条都带防误伤边界，函数幂等，替换产物不会被二次匹配。
_BOT_ENV_ASSIGN_RE = re.compile(
    r"\b(BOT_[A-Z0-9_]{1,64})\s*=\s*[^\s，。；！？、）】」”\"'<>]{1,200}"
)
# ATK-OUTB 票1/票6（2026-09-27 复查升格）：`\b`→`(?<![A-Za-z0-9_])`、{8,}→{4,}。
# 原 \b 把 CJK 也算词义字符，紧贴中文的 `试sk-…` 不构成边界而存活；短密钥
# （sk- 后 <8 字符）整段漏网。邻字母的 `desk-12345678`/`task-123` 一族**不许**
# 被本腿误伤——嵌词形态归下面的嵌词腿与长段腿按更严判据处理（防误伤锁见
# test_secret_redaction_hardening.py 票1 段）。
_API_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{4,}")
# 嵌词密钥（visk-/xsk-/_sk- 这类 `sk-` 前有字母数字下划线）：阈值仍取 ≥8，
# 且值必须**同时含字母与数字**——纯数字段（desk-12345678 / task-20260927）是
# 日常编号，纯字母长段少见于真 key，两类都不许动；两条前瞻先行判类，主体
# 贪婪吃掉整个连段，产物 `…sk-<已隐藏>` 不再被任何腿二次命中（幂等）。
_EMBEDDED_API_KEY_RE = re.compile(
    r"(?<=[A-Za-z0-9_])sk-"
    r"(?=[A-Za-z0-9_\-]{8,}(?![A-Za-z0-9_\-]))"
    r"(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*[0-9])"
    r"[A-Za-z0-9_\-]+"
)
# 全局第二形态尺（原 alerts._ALERT_SECRETISH_RE 升格，票1「并入同一咽喉」）：
# 短词干 + 连字符 + ≥20 位字母数字长段（ah-/xproj- 这类非 sk 词根的嵌 key）。
# 产物占位符与告警面原样一致（‹…›），既有告警显示形态零漂移。
# 🔴 升格为全局咽喉后必须带边界（W3 收尾）：这枚尺原先只喂
# ``alerts._alert_token`` 的**清洗后单代号**（非代号字符已被剥光，词干天然在串首），
# 现在喂的是自然行文，无边界版会在词干内部起匹配、把整段咬掉只剩首字母：
# ``session-<hex32>`` → ``s‹…›``、``feature-<digits21>`` → ``f‹…›``、
# ``anti-disestablishmentarianism`` 整词被吞、URL 路径段被吞后链接直接失效。
# 三条牙：①左邻禁 ``[A-Za-z0-9_./\]`` ＝词干不许从词**内部**起算（7 字母以上的词
# 天然落空，``{1,6}`` 够不到后面的连字符）；``-`` **不进**左禁类——#55★ 与告警面的
# ``kind=server-xsk-<24 大写字母>`` 那一形就长在连字符右侧，禁了它＝把老锁的覆盖面
# 拆了（实测三条反向锁不依赖禁 ``-``）；②尾段须「含数字 / 大小写混排 / 整段全大写」
# 三者之一＝真 key 的必要成分，纯小写长段是英文复合词不是凭据；③右界不许再贴字母
# 数字（整段收尾，防半截吞）。
# 在册代价：紧贴 ``/`` ``.`` 的 key（URL 路径段里的 ``…/ah-<hex>``）不再由本腿接管
# ——换「链接与代号不被咬断」；赋值/键值/Bearer 形态仍由前序腿整段接管，
# 厂商前缀族另有 ``_VENDOR_PREFIX_KEY_RE`` 独立腿。
_KEYED_LONG_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9_./\\])"
    r"[A-Za-z]{1,6}-"
    r"(?=[A-Za-z0-9]{20,}(?![A-Za-z0-9]))"
    r"(?:(?=[A-Za-z0-9]*[0-9])"
    r"|(?=[A-Z0-9]{20,}(?![A-Za-z0-9]))"
    r"|(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z]))"
    r"[A-Za-z0-9]{20,}"
)
# 裸高熵串（无词干上下文）：两条都要**字符类别混合**才打——
# hex：≥40 位且必须同时含 a-f 字母与数字（纯数字长编号不动）；
# b64：≥40 位连段且必须同时含大写、小写、数字（`AAAA…` 复读/分隔文本不动）。
# 词边界两侧禁止再贴字母数字（b64 腿还禁贴 +/=/_/-），URL/路径段由前后腿先吃。
_BARE_HEX_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?=[0-9A-Fa-f]{40,}(?![0-9A-Fa-f]))"
    r"(?=[0-9A-Fa-f]*[A-Fa-f])(?=[0-9A-Fa-f]*[0-9])"
    r"[0-9A-Fa-f]{40,}"
    r"(?![A-Za-z0-9])"
)
_BARE_B64_RE = re.compile(
    r"(?<![A-Za-z0-9+/=_\-])"
    r"(?=[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=_\-]))"
    r"(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[0-9])"
    r"[A-Za-z0-9+/]{40,}={0,2}"
)
_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:])([A-Za-z]):[\\/][^\s，。；！？、）】」”\"'<>]{0,200}"
)
_LOCAL_PATH_PLACEHOLDER = "<本机路径已隐藏>"
_SECRET_VALUE_PLACEHOLDER = "<已隐藏>"
_KEYED_RUN_PLACEHOLDER = "‹已隐藏密钥形态›"
_ASCII_DIGIT_RE = re.compile(r"[0-9]")
# M-2（S-ATK-RENDER 2026-09-28）：厂商固定前缀 key 族。sk-/嵌词/长段/hex/b64
# 五把尺都不认这类形态——GitHub PAT（ghp_+36 混合段：词干无连字符、尾段
# <40 两头落空）、fine-grained PAT（github_pat_ 前缀，体内可含下划线）、
# Slack（xox[baprs]- 多段、每段 <20）、AWS AccessKeyId（AKIA/ASIA+16 大写
# 字母数字，无词干腿）。四类前缀本身即身份，日常行文里不存在「词+下划线
# 直贴这些串」的歧义写法，故不再叠类别混合守卫；贪婪体吃满整个合法字符集，
# 产物为占位符、不再命中任何腿（幂等）。
# W3 收尾追加第五族 ``ah-``＝本机 AxonHub 网关 key 的真实形态（``ah-`` + 64 位
# 十六进制，实测长度 67）。它原先**只被 `_KEYED_LONG_RUN_RE` 顺带罩住**，而那把
# 尺本席刚补了边界与混合性牙齿——纯字母尾、紧贴 `/` 的形态从此落空；网关 key 是
# 「bot 把自己配置里的凭据念进聊天/告警卡」的头号面，不能挂在一把启发式尺上，
# 故给它一枚独立的厂商前缀腿（判据＝词干 + ≥40 位十六进制 + 左右不贴字母数字）。
# 左邻 ``(?<![A-Za-z0-9_])`` 让 ``hah-…``/``duh-…`` 一类感叹词尾巴天然落空。
_VENDOR_PREFIX_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:"
    r"gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    r"|xox[abposr]-[A-Za-z0-9][A-Za-z0-9\-]{7,}"
    r"|(?:AKIA|ASIA)[0-9A-Z]{16,}"
    r"|ah-[0-9a-fA-F]{40,}(?![A-Za-z0-9])"
    r")"
)
# 快路径哨兵（与腿一一对应，宁可多扫不能漏）：纯字母体的 ghp_/纯大写字母的
# AKIA 串**不含数字也不含连字符**，既有哨兵一条都不认——不补这三族，快路径
# 会把它们原样放回（注毒自证见 test_secret_redaction_hardening.py M-2 段）。
# ``ah-`` 的词干本身含连字符、体段必为十六进制，``-`` 与「含 ASCII 数字」两条
# 旧哨兵已覆盖绝大多数现值；仍登记在册＝腿与哨兵一一对应的口径不许破。
_VENDOR_KEY_SENTINELS = (
    "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat",
    "xox", "akia", "asia", "ah-",
)
# F-01 ①URL userinfo：必须 scheme:// 打头且「user:pass@」两段齐全（无密码的
# user@host 不动，普通 URL 无 @ 更不动）；只打码凭据段，保留 host:port/路径，
# 人类仍能看出泄漏发生在哪个服务。
_URL_USERINFO_RE = re.compile(
    r"\b(https?://)"
    r"([^\s/@，。；！？、）】」”\"'<>:]{1,64})"
    r":([^\s/@，。；！？、）】」”\"'<>:]{1,200})@"
)
# F-01 ②JWT 三段式：eyJ 是 base64('{"') 的固定开头（JWT header 必是 JSON），
# 加上三段 base64url 特征足够特异；整体打码——三段任何一段都可参与重放，
# 只打 signature 治标不治本。
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}"
)
# F-01 ③Bearer token：保留「Bearer」前缀（大小写不敏感，RFC 7235 scheme 本就
# 不区分大小写），只打码 token 本体；token 少于 8 字符视为示例/占位不打。
_BEARER_TOKEN_RE = re.compile(r"\b(?i:Bearer)([ \t]+)([A-Za-z0-9._\-]{8,})")
# F-01 ④裸键值对：键名限定密钥词干；词干左侧禁邻字母（monkey= 不命中）、
# 右侧禁邻字母数字下划线（keyword= / tokens= 不命中，access_token= 借
# 「_ 前缀」仍命中）；值 ≥8 字符才打（短值多为示例），分隔符含全角冒号。
_BARE_KEY_VALUE_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(sendkey|api_?key|secret|passw(?:or)?d|token|key)"
    r"(?![A-Za-z0-9_])\s*[:=：]\s*"
    r"([^\s，。；！？、）】」”\"'<>]{8,200})"
)

# --- E-04 打码形态表缺口波（INCIDENT-20260930 §五「打码形态缺口」）----------------
# 卷宗点名、上面那张形态表认不出的几类：邮箱 / 11 位手机号 / 内网 IP 字面量 /
# 无盘符 POSIX 路径 / 相对路径（data/x.db 一族）/ UNC（\\host\c$）/ cookie= /
# 非 Bearer 的裸 Authorization: / 非 http 的 URI userinfo（postgres://、mysql://）。
# （逐类腿名以本段的 ``_*_RE`` 定义为准，本处不写「几类」这种会漂移的数。）
# **QQ 号形态有意不做**：5-11 位纯数字与行情价、国债期限、群号、message_id、时间戳
# 完全同形，判据不可收敛——宁可留缺口，也不吞正常输出（手机号那条腿同理，W3 收尾
# 后只认「通话类上下文词 + 恰 11 位 1[3-9] 连段」，判据详见 _CN_MOBILE_RE 注）。
# 掩码取向：新增 PII 形态一律**保守掩码**（留首尾若干字符 + 中间 ``***``，不整段吞）；
# 凭据本体仍走既有 ``<已隐藏>``，但键名/scheme/host 逐字保留（与 F-01 四腿同形）。
# 幂等口径：``***`` 与被吃掉的占位符字符一律**不进**任何新腿的字符类与左邻判定，
# 故产物不会被任何腿二次命中（与既有各腿一致）。
_PII_MASK_MARK = "***"


def _mask_middle(value: str, head: int, tail: int) -> str:
    """保守掩码：留首 ``head`` 个与尾 ``tail`` 个字符，中间换成 ``***``。

    整段太短（掩不出信息量又不留残余）时只出 ``***``，绝不「留首尾」把整枚放开。
    """
    if len(value) <= head + tail:
        return _PII_MASK_MARK
    return f"{value[:head]}{_PII_MASK_MARK}{value[-tail:]}"


# 邮箱（PII）：域名整段保留（人仍看得出是哪家），本地段只留首尾各一字符。
# 左邻多禁 ``/ : * < > @`` 四种——DSN/URL 里的 ``user@host`` 归结构性腿管（禁这里
# 二次掩出碎相），``mailto:x@y`` 因紧跟冒号而放行＝已知缺口，换取「连接串主机名
# 不被当邮箱洗掉」；顶级域必须是 ``.`` + 2-24 字母，故 ``user@host``、``@所有人``
# 一类无域后缀的写法一律不动。
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-/:*<>@])"
    r"([A-Za-z0-9._%+\-]{1,64})"
    r"@([A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,24})"
    r"(?![A-Za-z0-9\-])"
)


def _mask_email(match: re.Match[str]) -> str:
    return f"{_mask_middle(match.group(1), 1, 1)}@{match.group(2)}"


# 11 位手机号：**必须带通话类上下文词**才掩（W3 收尾，原判据不可收敛已收窄）。
# 无条件版实测吞掉两类核心业务输出——``市值 19550721080 元`` → ``195***1080``、
# ``群号：13800000000`` → ``138***0000``（QQ 群号 9-11 位、完全可能落在 1[3-9] 段，
# 而 ``group_info.py`` 的「群号：{group_id}」正是直送本腿的行文；全角 ``：`` 当时
# 不在左禁类里）。这类数字是 bot 的**主业务面**，每轮都可能出，误伤不可接受；
# 反过来「上下文明明是别的东西、却恰好贴着 11 位 1[3-9] 数字」的手机号极罕见。
# 故按项目裁定「误伤不可控就收窄并说明」：判据＝通话词 + 至多 3 个非字母数字的
# 过渡字符 + 恰 11 位 ``1[3-9]`` 连段。通话词表是**封闭名册**（扩一个＝扩一次
# 误伤面）；「号码」在册而「群号/编号/订单号」不在册，正是靠整词不相交把群号那一形
# 挡在外面。左邻禁字母让 ``hotel`` 认不到 ``tel``。三条老牙保留：①长度恰 11
# （10 位群号、13/10 位时间戳、19 位 message_id 的任何窗口都贴着一位数字而落空）；
# ②右邻禁 ``.``（行情 ``19550721080.0`` 不动）；③产物 ``138***5678`` 被 ``*`` 断连
# ⇒ 任何腿不再命中（幂等）。
# **在册缺口（本席主动放弃的一半）**：无通话上下文的裸号（转发的联系人卡、
# 一串数字独占一行）今天不掩；掩码取向仍是保守掩码（留 3 前缀 + 4 尾号）。
_CN_MOBILE_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?P<head>(?i:手机号码|手机号|联系电话|联系方式|电话|手机|致电|拨打|联系|号码"
    r"|phone|mobile|tel|call)[^\n0-9A-Za-z]{0,3})"
    r"(?P<num>1[3-9][0-9]{9})(?![0-9A-Za-z.])"
)


def _mask_cn_mobile(match: re.Match[str]) -> str:
    return match.group("head") + _mask_middle(match.group("num"), 3, 4)

# 内网 IP 字面量：只认 RFC1918 + 链路本地（169.254/16＝云 metadata 面），
# 每段都过 0-255 值域 ⇒ 四段版本号 `10.0.19045.2` 天然落空。
# **127.0.0.1 有意不做**：本项目运维面/告警面常驻 `http://127.0.0.1:xxxx`（本地
# 网关、Embedding、SnowLuma），回环不泄露任何拓扑，打掉只会打断 grep 契约。
# 网段与末段保留、中间主机位换 ***（`192.168.***.77`），`*` 不进 octet 类 ⇒ 幂等。
# **IPv6 整族有意不做（W3 收尾补记的在册缺口，原先连这句都没写）**：`::1` 与
# 127.0.0.1 同理＝回环，不泄露拓扑；ULA（fc00::/7）与链路本地 fe80:: 在本项目现网
# 零出现（运维面全是 `127.0.0.1:端口`，代理链走本机 Clash 的 HTTP 口）。要把 IPv6
# 判对必须处理 `::` 零压缩、前缀长度 `/64`、zone id `fe80::1%eth0`——词面正则做出来
# 的只会是「看着像」的尺，而误伤代价落在一切含 `::` 的正常行文（Rust/C++ 的 `a::b`
# 作用域分隔符、CSS 的 `::before`、代码里的 `Foo::new()`）。等真出现内网 IPv6 拓扑外泄再补，不预先上
# 不可收敛的判据（与下方 QQ 号那一条同一口径）。
_IP_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_PRIVATE_IP_RE = re.compile(
    r"(?<![0-9A-Za-z.:_\-*])(?:"
    r"(?P<net_a>10)\.(?P<host_a>" + _IP_OCTET + r"\." + _IP_OCTET + r"\." + _IP_OCTET + r")"
    r"|"
    r"(?P<net_b>192\.168|169\.254|172\.(?:1[6-9]|2[0-9]|3[01]))"
    r"\.(?P<host_b>" + _IP_OCTET + r"\." + _IP_OCTET + r")"
    r")(?![0-9A-Za-z.])"
)


def _mask_private_ip(match: re.Match[str]) -> str:
    net = match.group("net_a") or match.group("net_b")
    octets = (match.group("host_a") or match.group("host_b")).split(".")
    return net + "." + ".".join([_PII_MASK_MARK] * (len(octets) - 1) + octets[-1:])


# UNC 共享（`\\host\share\...`，含 `c$` 管理共享）：主机名必掩（拓扑面），
# 末段文件名保留。左邻禁 `\` 以外的字母数字，避免把已掩产物的尾巴再吃一次。
_UNC_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9.*<>])\\\\[A-Za-z0-9.$_\-]{1,63}\\"
    r"[^\s，。；！？、）】」”\"'<>*]{1,200}"
)
# 无盘符 POSIX 绝对路径：首段必须是**文件系统根目录名**（home/root/usr/var/etc/
# opt/proc/srv/mnt/media/tmp/data，W3 收尾补 ``/Users``＝macOS 家目录，实测原样存活）
# 且其后还有第二段——`/bot help`、`docs/HANDBOOK.md`
# 里的 `/` 与触发词因此完全碰不到；URL 路径段 `/home/x` 由左邻「字母数字或 /」挡掉。
# 掩码取向 W3 起改为**留根段与末段文件名、中间整段换 ***（原先是定长留 5 字符，
# 对 `/Users` `/media` 会把根名自己截断）。隐私本体是中间的用户名/项目名。
_POSIX_ROOTS = (
    "home|Users|root|usr|var|etc|opt|proc|srv|mnt|media|tmp|data"
)
_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._\-/~*<>])(?P<root>/(?:" + _POSIX_ROOTS + r"))"
    r"/(?P<rest>[^\s，。；！？、）】」”\"'<>*]{1,200})"
)


def _mask_posix_path(match: re.Match[str]) -> str:
    root, rest = match.group("root"), match.group("rest")
    _, sep, last = rest.rpartition("/")
    if not sep:
        return f"{root}/{_mask_middle(rest, 2, 2)}"
    return f"{root}/{_PII_MASK_MARK}/{last}"
# 相对路径只认**在册敏感后缀**（库文件/私钥/凭据册），且必须带目录段：
# `data/chat_memory.sqlite3` 命中，`docs/HANDBOOK.md`、`config.py`、`data/cards/`
# 这些正常行文与目录名不动（后缀名册是这把尺的全部判据，扩一个就扩一次误伤面）。
_REL_SENSITIVE_PATHS = r"db|sqlite3?|env|pem|key|p12|pfx|kdbx"
_REL_SENSITIVE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._\-/~*<>])(?:[A-Za-z0-9._\-]+[/\\])+?"
    r"[A-Za-z0-9._\-]*\.(?:" + _REL_SENSITIVE_PATHS + r")"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# 非 http 的 URI userinfo：scheme 名册枚举（禁通配——通配会把任意 `x://a:b@host`
# 的行文一起吃掉），值段与 `https?` 腿同字符类；产物 `scheme://<已隐藏>@host:port/path`
# 与 F-01 ①逐字同形，host 保留以便定位是哪个服务漏的。
_DB_URI_SCHEMES = (
    r"postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss"
    r"|amqps?|s?ftp|ftps|smtp|smtps|imaps?|jdbc(?::[A-Za-z0-9_]+){1,3}"
)
_DB_URI_USERINFO_RE = re.compile(
    r"\b((?i:" + _DB_URI_SCHEMES + r")://)"
    r"([^\s/@，。；！？、）】」”\"'<>:]{1,64})"
    r":([^\s/@，。；！？、）】」”\"'<>:]{1,200})@"
)
# 非 Bearer 的裸 Authorization 头（Basic/Digest/Token/ApiKey/裸值）：Bearer 腿排在
# 前面，其产物 `<已隐藏>` 不在本腿值类内 ⇒ 不叠第二层掩码。值类**只收 ASCII 凭据
# 字符集**——中文行文（`authorization: 请管理员确认后再放行`）因此绝不会被当成凭据；
# 再加「值里至少一位非字母」的牙齿，把 traceback 里 `authorization=TypeName`
# 这类纯字母标识符形放过去（代价＝纯字母口令形漏网，已知取舍）。
_AUTH_SCHEMES = r"basic|digest|token|apikey|api_key"
_AUTH_HEADER_RE = re.compile(
    r"(?<![A-Za-z])((?i:authorization))(\s*[:=：]\s*)"
    r"((?i:" + _AUTH_SCHEMES + r")\s+)?"
    r"(?=[A-Za-z0-9+/=._~%\-]{8,200}(?![A-Za-z0-9+/=._~%\-]))"
    r"(?=[A-Za-z0-9+/=._~%\-]*[^A-Za-z])"
    r"[A-Za-z0-9+/=._~%\-]{8,200}"
)
# cookie 对（`Cookie: k=v; ...` / `cookie=v`）：键名与 `Set-Cookie` 头名保留、
# 值段整枚换成占位符（同 F-01 ④ 口径）。值类同样只收 ASCII 凭据字符集，中文行文
# （「Cookie 里存的是你的登录态」）碰不到；词干右邻禁 `_`/字母 ⇒ `cookie_header`
# `cookies.py` 一类变量名与文件名不动。
_COOKIE_PAIR_RE = re.compile(
    r"(?<![A-Za-z])((?i:set[-_]?cookie|cookie))(\s*[:=：]\s*)"
    r"[A-Za-z0-9+/=._~%\-]{8,200}"
)



# 出口标源（``SRC=``）的消毒腿（2026-10-11 裁定接线）：判定行加字段必同批补消毒
# （台账 #67★ 的旧病），真身＝``source_authority.sanitize_src_markers``——闭集外的任何
# 取值（上游写错、或外部内容伪造出一枚 ``SRC=ORG-PRIMARY``）在出站闸一律涂成
# ``SRC=UNVERIFIED``，绝不认「长得像标」就当标。幂等：闭集值原样放回。
# 哨兵登记：``src=``（小写后扫）＝本腿唯一入口，宁可多扫不能漏。
# 排在**全链最后**：前面的结构性腿（路径/键值/凭据）先收干净，本腿只认 ``SRC=`` 词形，
# 不与任何占位符字符重叠 ⇒ 产物不会再被别的腿二次命中（也不被自己二次命中）。
_SRC_MARKER_SENTINEL = "src="


def redact_local_secrets(text: str) -> str:
    """打码回复文本中的本机敏感形态；**只有快路径哨兵全部落空时**才原样返回。

    口径（W3 收尾改写：旧版把这件事说成「不花钱」，是假话）：成本按**输入字符里有
    没有标记**算，不按**有没有命中形态**算。哨兵名册见下，``-`` 与「含 ASCII 数字」
    两条几乎覆盖一切真实回复（行情价、时间戳、代号、URL、日期），所以「一条腿都不
    跑」的情形只在纯汉字短句出现。现算当时值（2026-09-30，本席位实跑 ``timeit``，
    随腿数漂移不作承诺）：无标记短句 ≈1.4µs，带一个数字或连字符的常规句 ≈15-18µs，
    全链二十来枚腿。相对一次模型往返（秒级）可忽略，但**不得再宣称热路径不要钱**。
    要压成本的正道是给慢路径再加一层按腿分组的前置判定，别改哨兵名册的覆盖面
    （宁可多扫不能漏）。
    """
    value = text or ""
    # 快路径哨兵与新正则一一对应，宁可多扫一遍也不能漏（漏=泄漏）：
    # 原三条：BOT_ / sk- / 盘符（:\ 与 :/）；F-01 四条：@（userinfo）、
    # eyJ（JWT，base64 大小写敏感固定前缀）、bearer/key/token/secret/passw
    # （Bearer 与裸键值对的词干，lowered 后扫描）；ATK-OUTB 票1 两条例：
    # 「-」（长段腿的词干分隔，值段必含）与「含 ASCII 数字」（hex/b64 腿都
    # 强制数字；sk 两腿另有 "sk-" 哨兵）。嵌词腿同样以 "sk-" 为必要成分。
    # E-04 缺口波补四条：`/`（POSIX 与相对路径腿）、单个 `\`（UNC 腿——原哨兵只认
    # `:\` 组合，`\\host\share` 整条不含冒号）、`cookie`、`authorization`（两条新
    # 词干腿；Bearer 腿只认 bearer，认不到 `Authorization: Basic`）。手机号与内网 IP
    # 由既有的「含 ASCII 数字」覆盖，邮箱由 `@` 覆盖，DSN userinfo 由 `:/` 覆盖。
    # W3 收尾未新增哨兵字符（一条腿没删、只收窄与加边界），但把 `ah-` 登进
    # `_VENDOR_KEY_SENTINELS`：它的词干含 `-`、体段是十六进制，旧两条本就覆盖，
    # 登记是为了「哨兵名册与腿一一对应」这条口径不许悄悄破功。
    lowered = value.lower()
    if ("BOT_" not in value and "sk-" not in value and ":\\" not in value
            and ":/" not in value and "@" not in value and "eyJ" not in value
            and "-" not in value and not _ASCII_DIGIT_RE.search(value)
            and "/" not in value and "\\" not in value
            and "bearer" not in lowered and "key" not in lowered
            and "token" not in lowered and "secret" not in lowered
            and "passw" not in lowered and "cookie" not in lowered
            and "authorization" not in lowered and _SRC_MARKER_SENTINEL not in lowered
            and not any(mark in lowered for mark in _VENDOR_KEY_SENTINELS)):
        return value
    # 顺序：先整段打掉 BOT_XXX=赋值（值里可能含路径/key），再打独立 key 与
    # 嵌词 key（ATK-OUTB 票1 两腿，独立腿在前保证 `sk-` 词根一次吃满整个连段），
    # 接着 M-2 厂商前缀腿（ghp_/github_pat_/xox*/AKIA/ASIA/ah-，与 sk 两腿同属
    # 「词形家族」层，先于结构性腿接管 key 本体），
    # 然后 F-01 四形态（userinfo → JWT → Bearer → 裸键值对；JWT 先于 Bearer，
    # 整条 JWT 一次打掉），最后打剩余的盘符绝对路径；路径之后再上新三腿
    # （长段词干尺 → hex → b64），让路径/URL 区域先被既有腿整段接管，
    # 减少占位符叠占位符的碎相。各腿产物均不再命中任何腿（幂等）。
    #
    # E-04 新腿的插入位点都是**贴着同族旧腿**放的，不改任何既有腿的相对次序：
    # 非 http 的 DSN userinfo 紧跟 http 腿（同形同产物）；裸 Authorization 排在
    # Bearer 之后（Bearer 先行，本腿看到占位符不再叠二层）；cookie 排在裸键值对
    # 之前（同为「键名 + 值」结构腿）；三条路径腿排在盘符腿之后（`C:\...\data\x.db`
    # 先被盘符腿整段接管，免得占位符叠占位符）；数字与邮箱三条放在**全链最后**
    # （手机号/内网 IP 是最容易撞到别的腿产物碎相的形态，让结构性腿先收干净）。
    value = _BOT_ENV_ASSIGN_RE.sub(r"\1=" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _API_KEY_RE.sub("sk-" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _EMBEDDED_API_KEY_RE.sub("sk-" + _SECRET_VALUE_PLACEHOLDER, value)
    # M-2 厂商前缀族并入同一咽喉：排在 sk 两腿之后、结构性腿（userinfo/JWT/
    # Bearer/裸键值对）之前——`token=ghp_xxx` 一类先被本腿打掉 key 本体，
    # 裸键值腿随后看到的是占位符（`<` 在其值类之外）不再重复动作，产物同形。
    value = _VENDOR_PREFIX_KEY_RE.sub(_SECRET_VALUE_PLACEHOLDER, value)
    value = _URL_USERINFO_RE.sub(r"\1" + _SECRET_VALUE_PLACEHOLDER + "@", value)
    value = _DB_URI_USERINFO_RE.sub(r"\1" + _SECRET_VALUE_PLACEHOLDER + "@", value)
    value = _JWT_RE.sub(_SECRET_VALUE_PLACEHOLDER, value)
    value = _BEARER_TOKEN_RE.sub("Bearer" + r"\1" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _AUTH_HEADER_RE.sub(r"\1\2\3" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _COOKIE_PAIR_RE.sub(r"\1\2" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _BARE_KEY_VALUE_RE.sub(r"\1=" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _LOCAL_PATH_RE.sub(_LOCAL_PATH_PLACEHOLDER, value)
    value = _UNC_PATH_RE.sub(lambda m: _mask_middle(m.group(0), 2, 12), value)
    value = _POSIX_PATH_RE.sub(_mask_posix_path, value)
    value = _REL_SENSITIVE_PATH_RE.sub(lambda m: _mask_middle(m.group(0), 4, 12), value)
    value = _KEYED_LONG_RUN_RE.sub(_KEYED_RUN_PLACEHOLDER, value)
    value = _BARE_HEX_RE.sub(_SECRET_VALUE_PLACEHOLDER, value)
    value = _BARE_B64_RE.sub(_SECRET_VALUE_PLACEHOLDER, value)
    value = _CN_MOBILE_RE.sub(_mask_cn_mobile, value)
    value = _PRIVATE_IP_RE.sub(_mask_private_ip, value)
    value = _EMAIL_RE.sub(_mask_email, value)
    value = sanitize_src_markers(value)
    return value


# --- 破坏性命令出站打码（席7 安全与文档波，2026-10-03）------------------------
# 模型被诱导复述「可复制即执行」的破坏性命令行（rm -rf / mkfs / dd 写设备 /
# fork 炸弹 / Remove-Item -Recurse / del /s /q / format 盘 / reg delete /
# shutdown / vssadmin 清卷影）时，出站前把命中的命令**整段**换成人话占位。
# 与上面密钥打码同一层、同一纪律：
# - 形态名册**封闭**（扩一个＝扩一次误伤面；新形态要有实据再进册）；
# - 每条腿带防误伤边界（反向锁 tests/test_destructive_command_redaction.py）；
# - 幂等：占位话术不进任何腿的形态，两种链式次序终态一致。
# - 教学语境豁免只认**围栏代码块**（``` 与 ~~~）——围栏内一字不动；行内反引号
#   不豁免（单反引号包一层就把 payload 洗白＝旁路通道，有意不做）。
# 已知缺口（在册）：PowerShell 的 rm/rd/ri 别名形（``rd -Recurse``）不在册——
# cmd 形 ``rd /s`` 与 PS 形 ``Remove-Item -Recurse`` 已覆盖主流写法，别名形
# 等有实据再收；SQL DROP/TRUNCATE 不属 shell 命令行，不在本腿。
_DESTRUCTIVE_COMMAND_PLACEHOLDER = "（这类命令我不能原样提供）"
#: 完整话术（守岸人语气、人格中性——不写死任何人格意象名词，切人格不跟着换）。
#: 调用方（chat.py 回复链）命中后可把这句附在回执尾；本函数只做行内整段替换。
DESTRUCTIVE_COMMAND_NOTICE = (
    "这类命令会直接抹掉数据，我不能原样提供。"
    "你想做成的是什么？告诉我，我们一起找个稳妥的办法。"
)
# 快路径哨兵（宁可多扫不能漏；小写后扫描）：与下面各腿的词根一一对应，
# 纯汉字/普通英文句一条都不含 ⇒ 快路径零腿。
_DESTRUCTIVE_SENTINELS = (
    "rm", "mkfs", "dd", ":(", "remove-item", "/s", "format",
    "reg delete", "shutdown", "vssadmin",
)
_RM_RECURSIVE_RE = re.compile(
    r"\brm\s+"                                    # rm 本尊（\b 挡 confirm/firm）
    r"(?:-[A-Za-z]*r[A-Za-z]*\s+|--recursive\s+)" # 必须有递归旗标（-rf/-fr/-r/--recursive）
    r"(?:-[A-Za-z]+\s+)*\S+"                      # 其余旗标 + 目标 token（整段吃满）
)
_MKFS_RE = re.compile(r"\bmkfs(?:\.[A-Za-z0-9]+)?\b")
_DD_TO_DEVICE_RE = re.compile(r"\bdd\s+(?:if=\S+\s+)?of=/dev/")
_FORK_BOMB_RE = re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
# 旗标必须**紧邻**命令词（中间只许别的旗标）——「Remove-Item 单个文件、不带
# -Recurse」这类否定句行文不得被咬（反向锁在册）。
_REMOVE_ITEM_RECURSE_RE = re.compile(
    r"\bRemove-Item\s+(?:-[A-Za-z0-9]+\s+){0,4}-Recurse\b", re.IGNORECASE
)
_CMD_TREE_DELETE_RE = re.compile(r"\b(?:rd|rmdir|del|erase)\s+/s\b", re.IGNORECASE)
_FORMAT_DRIVE_RE = re.compile(r"\bformat\s+[A-Za-z]:", re.IGNORECASE)
_FORMAT_VOLUME_RE = re.compile(r"\bFormat-Volume\b", re.IGNORECASE)
_REG_DELETE_RE = re.compile(r"\breg\s+delete\b", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(
    r"\bshutdown\s+(?:-[hrp]\s*now\b|-[hrp]\b|/[srg]\b|now\b)", re.IGNORECASE
)
_VSSADMIN_WIPE_RE = re.compile(r"\bvssadmin\s+delete\s+shadows\b", re.IGNORECASE)
_DESTRUCTIVE_LEGS: tuple[re.Pattern[str], ...] = (
    _RM_RECURSIVE_RE, _MKFS_RE, _DD_TO_DEVICE_RE, _FORK_BOMB_RE,
    _REMOVE_ITEM_RECURSE_RE, _CMD_TREE_DELETE_RE, _FORMAT_DRIVE_RE,
    _FORMAT_VOLUME_RE, _REG_DELETE_RE, _SHUTDOWN_RE, _VSSADMIN_WIPE_RE,
)
_FENCE_MARKS = ("```", "~~~")


def _split_fenced(text: str) -> list[tuple[str, bool]]:
    """按围栏代码块切段：返回 ``(段文本, 是否在围栏内)`` 有序表。

    围栏判定按行首（至多 3 个空白后跟 ```/~~~）翻转围栏态——与
    ``naturalize_chat_text`` 对围栏的行级认知一致；未闭合围栏按「此后全在围栏内」
    处理（尾部内容豁免，宁可少打不误伤教学块）。
    """
    segments: list[tuple[str, bool]] = []
    in_fence = False
    buffer: list[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip(" \t")
        if any(stripped.startswith(m) for m in _FENCE_MARKS):
            if buffer:
                segments.append(("\n".join(buffer), in_fence))
                buffer = []
            buffer.append(line)
            in_fence = not in_fence
            continue
        buffer.append(line)
    if buffer:
        segments.append(("\n".join(buffer), in_fence))
    return segments


def redact_destructive_commands(text: str) -> str:
    """打码回复文本中的破坏性命令行；围栏代码块（教学语境）豁免。

    分层分工（需求17，2026-10-03）：chat 回复的危险命令**主裁决**在 chat 层
    （``chat_reply/security/dangerous_command.py``：全文替换＋审计标签，与
    artifact_review_blocked 并列不互斥）；本件是**渲染层出站咽喉的行内兜底**
    （唯一接线点＝``renderer._redact_outbound_text``，罩其余能力出站与 chat
    漏网面）。两层腿册差异＝分层分工，不是第二真身。

    口径与 ``redact_local_secrets`` 同族：只做行内整段替换（不吞句、不动前后文），
    幂等，占位符 ``（这类命令我不能原样提供）`` 不进任何腿的形态。命中后的
    人话补充句在 :data:`DESTRUCTIVE_COMMAND_NOTICE`，由调用方决定是否附在回执尾。
    快路径：哨兵名册全部落空时原样返回（纯汉字短句零腿）。
    """
    value = text or ""
    lowered = value.lower()
    if not any(mark in lowered for mark in _DESTRUCTIVE_SENTINELS):
        return value
    out_parts: list[str] = []
    for segment, fenced in _split_fenced(value):
        if fenced:
            out_parts.append(segment)
            continue
        for leg in _DESTRUCTIVE_LEGS:
            segment = leg.sub(_DESTRUCTIVE_COMMAND_PLACEHOLDER, segment)
        out_parts.append(segment)
    return "\n".join(out_parts)
