"""Deterministic chat presentation; never applied to admin/config or media payloads.

No model calls. Preserve words, URLs, numbers and paragraph boundaries while
removing presentation syntax. Common TeX is verbalized, not evaluated; unknown
commands remain named rather than being silently discarded.
"""
from __future__ import annotations

import html
import re

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


def _redact_inner_state_number(match: re.Match[str]) -> str:
    name = match.group(1) or "内心状态"
    return f"{name}…保密"


def humanize_reply(text: str) -> str:
    """剥离聊天回复的 AI 客套开场与总结腔；不改变事实与语义。"""
    value = (text or "").strip()
    if not value:
        return value
    value = _HUMANIZE_OPENING_RE.sub("", value).strip()
    value = _HUMANIZE_CLOSING_RE.sub("", value).strip()
    value = _INNER_STATE_NUM_RE.sub(_redact_inner_state_number, value)
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
_API_KEY_RE = re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,})")
_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9:])([A-Za-z]):[\\/][^\s，。；！？、）】」”\"'<>]{0,200}"
)
_LOCAL_PATH_PLACEHOLDER = "<本机路径已隐藏>"
_SECRET_VALUE_PLACEHOLDER = "<已隐藏>"
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


def redact_local_secrets(text: str) -> str:
    """打码回复文本中的本机敏感形态；无命中时原样返回（热路径零成本）。"""
    value = text or ""
    # 快路径哨兵与新正则一一对应，宁可多扫一遍也不能漏（漏=泄漏）：
    # 原三条：BOT_ / sk- / 盘符（:\ 与 :/）；F-01 四条：@（userinfo）、
    # eyJ（JWT，base64 大小写敏感固定前缀）、bearer/key/token/secret/passw
    # （Bearer 与裸键值对的词干，lowered 后扫描）。
    lowered = value.lower()
    if ("BOT_" not in value and "sk-" not in value and ":\\" not in value
            and ":/" not in value and "@" not in value and "eyJ" not in value
            and "bearer" not in lowered and "key" not in lowered
            and "token" not in lowered and "secret" not in lowered
            and "passw" not in lowered):
        return value
    # 顺序：先整段打掉 BOT_XXX=赋值（值里可能含路径/key），再打独立 key，
    # 然后 F-01 四形态（userinfo → JWT → Bearer → 裸键值对；JWT 先于 Bearer，
    # 整条 JWT 一次打掉），最后打剩余的盘符绝对路径。
    value = _BOT_ENV_ASSIGN_RE.sub(r"\1=" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _API_KEY_RE.sub("sk-" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _URL_USERINFO_RE.sub(r"\1" + _SECRET_VALUE_PLACEHOLDER + "@", value)
    value = _JWT_RE.sub(_SECRET_VALUE_PLACEHOLDER, value)
    value = _BEARER_TOKEN_RE.sub("Bearer" + r"\1" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _BARE_KEY_VALUE_RE.sub(r"\1=" + _SECRET_VALUE_PLACEHOLDER, value)
    value = _LOCAL_PATH_RE.sub(_LOCAL_PATH_PLACEHOLDER, value)
    return value
