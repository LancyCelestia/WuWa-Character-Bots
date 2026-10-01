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


#: 反照本宣科兜底（2026-09-27 用户裁定）：接地块里搬出来的"词条骨架"。
#: 提示词里已有一道令（chat 的 `_KB_RECITAL_RULE_LINE`），但那是求模型——模型
#: 不听话时不能把「一、 身份与背景来历」这种目录腔原样发给用户。这一腿只做
#: **确定性的结构压平**：剥行首 markdown 序号/项目符号/加粗，绝不删正文里的词。
_ARTICLE_INDEX_HEAD_RE = re.compile(
    r"^\s*(?:[一二三四五六七八九十]{1,3}|[（(][一二三四五六七八九十\d]{1,3}[）)]|\d+[.)、])"
    r"\s*[、．.]?\s*"
)
_BULLET_HEAD_RE = re.compile(r"^\s*(?:[-*•·])[ \t]+")
_BOLD_MD_RE = re.compile(r"\*\*(.+?)\*\*")


def flatten_article_scaffolding(text: str) -> str:
    """把"编号 + 小标题 / 连续 bullet"式词条骨架压成连续口吻；无骨架时逐字节原样返回。

    两腿的保守度不同，各自一条反例锁（``tests/test_batch_cdf_modules.py``）：
    ①编号小标题（``一、`` / ``1.`` / ``（二）``）形态足够特异，单行即压；
    ②bullet 只在**连续两行以上**时才压——中文行文常以"- 那也算…"起头，
      单行判成列表会啃掉正常语气。行首缩进一律保留（剥缩进＝改行文）。
    """
    value = (text or "").strip()
    if not value:
        return text or ""
    raw_lines = (text or "").splitlines()
    bullet_rows = [i for i, line in enumerate(raw_lines) if _BULLET_HEAD_RE.match(line)]
    # 连续两行（行号相邻）才算列表；孤行 bullet 当行文保留。
    list_rows = {
        i for i in bullet_rows if (i - 1) in set(bullet_rows) or (i + 1) in set(bullet_rows)
    }
    lines: list[str] = []
    touched = False
    for index, raw in enumerate(raw_lines):
        line = _BOLD_MD_RE.sub(r"\1", raw)
        if line != raw:
            touched = True
        stripped = _ARTICLE_INDEX_HEAD_RE.sub("", line, count=1)
        if index in list_rows:
            stripped = _BULLET_HEAD_RE.sub("", stripped, count=1)
        if stripped != line:
            touched = True
        lines.append(stripped.rstrip())
    if not touched:
        return text
    return "\n".join(line for line in lines if line.strip())


def humanize_reply(text: str) -> str:
    """剥离聊天回复的 AI 客套开场与总结腔；不改变事实与语义。"""
    value = (text or "").strip()
    if not value:
        return value
    # 结构压平排在客套剥离之前：编号小标题常紧跟开场语，先拿掉骨架才好判开场。
    value = flatten_article_scaffolding(value)
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
_KEYED_LONG_RUN_RE = re.compile(r"[A-Za-z]{1,6}-[A-Za-z0-9]{20,}")
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
_VENDOR_PREFIX_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:"
    r"gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    r"|xox[abposr]-[A-Za-z0-9][A-Za-z0-9\-]{7,}"
    r"|(?:AKIA|ASIA)[0-9A-Z]{16,}"
    r")"
)
# 快路径哨兵（与腿一一对应，宁可多扫不能漏）：纯字母体的 ghp_/纯大写字母的
# AKIA 串**不含数字也不含连字符**，既有哨兵一条都不认——不补这三族，快路径
# 会把它们原样放回（注毒自证见 test_secret_redaction_hardening.py M-2 段）。
_VENDOR_KEY_SENTINELS = (
    "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat",
    "xox", "akia", "asia",
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
# 卷宗点名、上面那张形态表认不出的八类：邮箱 / 11 位手机号 / 内网 IP 字面量 /
# 无盘符 POSIX 路径 / 相对路径（data/x.db 一族）/ UNC（\\host\c$）/ cookie= /
# 非 Bearer 的裸 Authorization: / 非 http 的 URI userinfo（postgres://、mysql://）。
# **QQ 号形态有意不做**：5-11 位纯数字与行情价、国债期限、群号、message_id、时间戳
# 完全同形，判据不可收敛——宁可留缺口，也不吞正常输出（数字类腿只认 1[3-9] 开头的
# 恰 11 位连段，且左右邻位一律收紧，详见 _CN_MOBILE_RE 注）。
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


# 11 位手机号：`1[3-9]` + 恰 9 位，且左右邻位禁数字/字母/`.`/`:`/`-`/`_`/`/`/`*`。
# 三条防误伤牙：①**长度必须恰 11**——10 位群号、10/13 位时间戳、19 位 message_id
# 的任何 11 位窗口都贴着一位数字而落空；②尾邻禁 `.`——行情/市值的
# `19550721080.0` 一类带小数的长数不动；③左邻禁 `:` 与 `/`——ops 文案里
# `session=group:13800000000`、URL 路径段是标识符位不是电话。产物 `138***5678`
# 被 `*` 断连，任何腿（含本腿）都不再命中。
_CN_MOBILE_RE = re.compile(r"(?<![0-9A-Za-z.:_\-/*])1[3-9][0-9]{9}(?![0-9A-Za-z.])")

# 内网 IP 字面量：只认 RFC1918 + 链路本地（169.254/16＝云 metadata 面），
# 每段都过 0-255 值域 ⇒ 四段版本号 `10.0.19045.2` 天然落空。
# **127.0.0.1 有意不做**：本项目运维面/告警面常驻 `http://127.0.0.1:xxxx`（本地
# 网关、Embedding、SnowLuma），回环不泄露任何拓扑，打掉只会打断 grep 契约。
# 网段与末段保留、中间主机位换 ***（`192.168.***.77`），`*` 不进 octet 类 ⇒ 幂等。
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
# opt/proc/srv/mnt/media/tmp/data）且其后还有第二段——`/bot help`、`docs/HANDBOOK.md`
# 里的 `/` 与触发词因此完全碰不到；URL 路径段 `/home/x` 由左邻「字母数字或 /」挡掉。
_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._\-/~*<>])(?:"
    r"/home|/root|/usr|/var|/etc|/opt|/proc|/srv|/mnt|/media|/tmp|/data"
    r")/[^\s，。；！？、）】」”\"'<>*]{1,200}"
)
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



def redact_local_secrets(text: str) -> str:
    """打码回复文本中的本机敏感形态；无命中时原样返回（热路径零成本）。"""
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
    lowered = value.lower()
    if ("BOT_" not in value and "sk-" not in value and ":\\" not in value
            and ":/" not in value and "@" not in value and "eyJ" not in value
            and "-" not in value and not _ASCII_DIGIT_RE.search(value)
            and "/" not in value and "\\" not in value
            and "bearer" not in lowered and "key" not in lowered
            and "token" not in lowered and "secret" not in lowered
            and "passw" not in lowered and "cookie" not in lowered
            and "authorization" not in lowered
            and not any(mark in lowered for mark in _VENDOR_KEY_SENTINELS)):
        return value
    # 顺序：先整段打掉 BOT_XXX=赋值（值里可能含路径/key），再打独立 key 与
    # 嵌词 key（ATK-OUTB 票1 两腿，独立腿在前保证 `sk-` 词根一次吃满整个连段），
    # 接着 M-2 厂商前缀腿（ghp_/github_pat_/xox*/AKIA/ASIA，与 sk 两腿同属
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
    value = _POSIX_PATH_RE.sub(lambda m: _mask_middle(m.group(0), 5, 12), value)
    value = _REL_SENSITIVE_PATH_RE.sub(lambda m: _mask_middle(m.group(0), 4, 12), value)
    value = _KEYED_LONG_RUN_RE.sub(_KEYED_RUN_PLACEHOLDER, value)
    value = _BARE_HEX_RE.sub(_SECRET_VALUE_PLACEHOLDER, value)
    value = _BARE_B64_RE.sub(_SECRET_VALUE_PLACEHOLDER, value)
    value = _CN_MOBILE_RE.sub(lambda m: _mask_middle(m.group(0), 3, 4), value)
    value = _PRIVATE_IP_RE.sub(_mask_private_ip, value)
    value = _EMAIL_RE.sub(_mask_email, value)
    return value
