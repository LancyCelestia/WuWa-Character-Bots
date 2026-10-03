"""出站危险命令审查（安全与文档波 · 施工席7 · 2026-10-02）。

定位
----
既有九层防线（``injection.py`` 检测/包裹、``trust.py`` T0-T3、``policy/roles.py``
六级、``render/plain_text.py::redact_local_secrets`` 打码）里**没有**一条管
「bot 教用户执行破坏性命令」的输出形态——注入内容或模型幻觉完全可以让回复
以守岸人口吻递出一行 ``rm -rf /``。本件补这条腿：对**即将出站**的纯文本做
窄形态匹配，命中即产出一句话术替换文本（人话警告，**不含**可复制的命令原文）。

接线（席16 · 需求17 · 2026-10-03 已接）
----
挂点在 ``chat.py`` 出站审查（``_unsafe_output_reasons`` 一带）：
``verdict = screen_dangerous_command_output(reply.text)``，``verdict.hit`` 为真时把
``reply.text`` 换成 ``verdict.replacement`` 并落 audit 标签 ``dangerous_command_output``
（命中族以 ``dangerous_command_output:<family>`` 进审计）；与既有
``artifact_review_blocked`` 语义**并列不互斥**——两腿都基于替换前原文现算，本腿
hit 只换文不阻断，artifact 腿照旧全拦。

分层分工：本件＝**chat 层裁决＋审计（主）**；``render/plain_text.py::
redact_destructive_commands``＝**渲染层出站咽喉的行内兜底**（打码不换全文、
围栏豁免，罩 chat 之外的其余能力出站与 chat 漏网面）。两层腿册差异＝分层分工，
不是第二真身，不做腿册合并。

形态纪律（窄尺，防误伤正常教学/财经内容）
----
* 文件删除族（``rm`` / ``del`` / ``rd`` / ``Remove-Item``）必须**同时**满足
  「递归+强制旗标」与「危险目标」（盘符根 / 系统目录 / ``~`` / ``$HOME`` /
  全盘通配）才命中——``rm -rf node_modules``、``Remove-Item .\\logs\\a.log -Force``
  这类日常教学一律放行。
* ``format`` 只认「format + 盘符」；``mkfs`` 只认带 ``/dev/`` 目标；``dd`` 只认
  ``of=`` 直写块设备（``/dev/null`` 除外）；``reg delete`` 只认机器级蜂巢
  （HKLM/HKCR/HKCC）且带 ``/f`` 免确认旗标；``shutdown`` 只认带执行旗标
  （``/s`` ``-r`` ``-h now`` 一类）的形态——裸词「shutdown」在叙述里出现不命中。
* 本件只做**出站面**审查：入站教用户「怎么防误删」的提问不受本件影响；
  拦的是「劝人跑」的建议文本，不是知识本身。

失败面
----
纯函数、零 IO、零配置读、零网络；任何输入（含空串/非字符串退化形态）都不抛——
审查器自身故障绝不能把出站链路打挂（与 ``settings_gate._redact`` 的 fail-open
同一哲学：安全话术宁可缺席，不可阻断主链路）。

注入处置令兼容（AGENTS 规则 11）
----
命中时产出的 ``replacement`` 是**固定模板**，不回显命中原文、不携带命令形态——
「关于危险命令的报告」本身不得成为新的命令载体。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "REPLACEMENT_TEXT",
    "DangerousCommandVerdict",
    "screen_dangerous_command_output",
]

#: 命中后的话术替换文本（唯一真身；固定模板，不含任何命令形态）。
#: 接线方拿它整体替换出站正文，禁止拼接命中片段（防二次传播）。
REPLACEMENT_TEXT = (
    "这句回复我拦下来了：里面混着会抹盘、清系统或者动引导级设置的破坏性命令，"
    "我不能把这类内容原样递出去。如果你确实要做这类操作——先完整备份，"
    "再对照官方文档逐条核对，或者请超级管理员本人来操作；网上来路不明的命令，"
    "一条都不要直接粘进终端。"
)

#: 「危险目标」谓词：盘符根/系统目录/家目录/全盘通配。删除族必须再命中这里才算。
#: 边界类含全角标点——中文叙述「rm -rf ~，保证干净」的顿号/逗号边界也要看得见。
_B = r"[\s，。；：！？、（）【】《》「」『』\"'…,;:!?)\]]"
_DANGEROUS_TARGET_RE = re.compile(
    r"(?:"
    rf"(?:^|[\s\"'])/(?:{_B}|$|\*)"                     # Unix 根 / 全盘通配 /*（/tmp 不算）
    rf"|(?:^|[\s\"'])~(?:/\*)?(?:{_B}|$)"               # ~ 或 ~/*（~/.ssh 不算）
    rf"|(?:^|[\s\"'])\$HOME(?:/\*)?(?:{_B}|$)"
    rf"|[a-zA-Z]:[\\/](?:\*|{_B}|$)"                    # 盘符根 C:\ C:/ C:\*
    rf"|[a-zA-Z]:[\\/](?:Windows|windows|System32|system32"
    rf"|Program\s+Files(?:\s+\(x86\))?|Users)(?:[\\/].*)?(?:{_B}|$|\*)"
    rf"|(?:^|[\s\"'])/(?:etc|usr|bin|sbin|var|boot|dev|proc|sys|lib)(?:/|{_B}|$)"
    rf"|%(?:WinDir|SystemRoot|SystemDrive)%"
    r")"
)

#: rm / del 一族的命令定位与旗标切分。
#: 定位只取词边界（中文叙述「先执行/试试 rm -rf /」也要看得见）；窄度由
#: 「递归+强制旗标 ∧ 危险目标」双条件保住，裸命令词不构成命中。
_RM_INVOCATION_RE = re.compile(r"\brm\s+([^\n;|&]*)", re.IGNORECASE)
_WIN_RECURSE_DELETE_RE = re.compile(
    r"\b(?:rd|rmdir|del|erase)\s+([^\n;|&]*)", re.IGNORECASE
)
_PS_REMOVE_ITEM_RE = re.compile(r"\bRemove-Item\s+([^\n;|]*)", re.IGNORECASE)

#: 单命令段内旗标判定（对捕获组现算，不进大正则——可读可测）。
_FLAG_TOKEN_RE = re.compile(r"(?:^|\s)(-{1,2}[A-Za-z-]+)(?=\s|$)")
_LONG_FLAG_ALIASES = {
    "recursive": "recursive",
    "recurse": "recursive",
    "force": "force",
}

#: 无目标族（命令形态本身就足够危险）。
_FORMAT_DRIVE_RE = re.compile(r"\bformat(?:\.com)?\s+(?:/[a-z]\s+)*[a-zA-Z]:", re.IGNORECASE)
_MKFS_RE = re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\s+[^\n;|&]{0,60}/dev/", re.IGNORECASE)
_DD_TO_DEVICE_RE = re.compile(
    r"\bdd\b[^\n;|&]{0,120}\bof=/dev/(?!null\b)(?:sd|hd|nvme|vd|mmcblk|disk|rdisk)", re.IGNORECASE
)
_REG_DELETE_MACHINE_RE = re.compile(
    r"\breg\s+delete\s+hk(?:lm|cr|cc|ey_local_machine|ey_classes_root|ey_current_config)"
    r"[^\n]{0,120}/f\b",
    re.IGNORECASE,
)
_SHUTDOWN_RE = re.compile(
    r"(?:\bshutdown\s+(?:/|-)(?:s|r|h|p|g)\b|\bshutdown\s+now\b"
    r"|\bStop-Computer\b[^\n;]{0,60}-Force\b|\bRestart-Computer\b[^\n;]{0,60}-Force\b)",
    re.IGNORECASE,
)
_FORK_BOMB_RE = re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;?\s*:")
_DISKPART_CLEAN_RE = re.compile(
    r"\bdiskpart\b[^\n]{0,80}\bclean(?:\s+all)?\b|\bclean(?:\s+all)?\b[^\n]{0,80}\bdiskpart\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DangerousCommandVerdict:
    """一次出站审查的结论：``hit`` 为真时调用方应整体替换正文为 ``replacement``。"""

    hit: bool
    families: tuple[str, ...] = ()
    replacement: str = ""


def _short_flags_contain(flag_tokens: tuple[str, ...], wanted: str) -> bool:
    """旗标串里是否含某个语义旗标（``wanted`` 取 ``recursive``/``force``）。

    短旗标按单字符判（``-rf``/``-Rf``/``-Recurse`` 的首字母即语义）；长旗标
    （``--recursive``/``--force``）按词表判。词表外长旗标一律不猜。
    """
    for token in flag_tokens:
        if token.startswith("--"):
            if _LONG_FLAG_ALIASES.get(token[2:].lower()) == wanted:
                return True
        elif wanted[0] in token[1:].lower():
            return True
    return False


def _split_flags(args: str) -> tuple[tuple[str, ...], str]:
    """把参数串粗分为（旗标, 其余目标区）——够窄尺判定用，不做真 shell 解析。"""
    tokens = _FLAG_TOKEN_RE.findall(" " + args)
    rest = _FLAG_TOKEN_RE.sub(" ", " " + args)
    return tuple(tokens), rest


def _match_rm_family(text: str) -> str | None:
    for m in _RM_INVOCATION_RE.finditer(text):
        flags, target_zone = _split_flags(m.group(1) or "")
        if not (_short_flags_contain(flags, "recursive") and _short_flags_contain(flags, "force")):
            continue
        if _DANGEROUS_TARGET_RE.search(target_zone):
            return m.group(0)
    return None


def _match_win_recurse_delete(text: str) -> str | None:
    for m in _WIN_RECURSE_DELETE_RE.finditer(text):
        args = m.group(1) or ""
        lowered = args.lower()
        if "/s" not in lowered.replace("\\", "/"):
            continue
        if "/q" not in lowered and "/f" not in lowered:
            continue
        if _DANGEROUS_TARGET_RE.search(args):
            return m.group(0)
    return None


def _match_ps_remove_item(text: str) -> str | None:
    for m in _PS_REMOVE_ITEM_RE.finditer(text):
        args = m.group(1) or ""
        flags, target_zone = _split_flags(args)
        if not (_short_flags_contain(flags, "recursive") and _short_flags_contain(flags, "force")):
            continue
        if _DANGEROUS_TARGET_RE.search(target_zone) or _DANGEROUS_TARGET_RE.search(args):
            return m.group(0)
    return None


def _match_diskpart(text: str) -> str | None:
    for line in text.splitlines():
        if _DISKPART_CLEAN_RE.search(line):
            return line
    return None


def screen_dangerous_command_output(text: str) -> DangerousCommandVerdict:
    """出站纯文本的窄形态审查（唯一入口；纯函数，任何输入不抛）。

    返回 ``DangerousCommandVerdict``；``hit=True`` 时 ``replacement`` 是固定话术
    （不含命中原文），``families`` 给 audit 用。非字符串一律按无命中放行——
    审查器故障不许阻断出站链路。
    """
    if not isinstance(text, str) or not text:
        return DangerousCommandVerdict(hit=False)
    families: list[str] = []
    if _match_rm_family(text) is not None:
        families.append("unix_rm_rf_wildcard")
    if _match_win_recurse_delete(text) is not None:
        families.append("windows_recursive_delete_drive_target")
    if _match_ps_remove_item(text) is not None:
        families.append("powershell_remove_item_recursive_force")
    if _FORMAT_DRIVE_RE.search(text):
        families.append("format_drive")
    if _MKFS_RE.search(text):
        families.append("mkfs_device")
    if _DD_TO_DEVICE_RE.search(text):
        families.append("dd_write_block_device")
    if _REG_DELETE_MACHINE_RE.search(text):
        families.append("reg_delete_machine_hive_force")
    if _SHUTDOWN_RE.search(text):
        families.append("shutdown_system")
    if _FORK_BOMB_RE.search(text):
        families.append("fork_bomb")
    if _match_diskpart(text) is not None:
        families.append("diskpart_clean")
    if not families:
        return DangerousCommandVerdict(hit=False)
    return DangerousCommandVerdict(hit=True, families=tuple(families), replacement=REPLACEMENT_TEXT)
