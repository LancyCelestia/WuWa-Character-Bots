"""出站侧破坏性命令打码（席7 安全与文档波，2026-10-03）。

背景：模型被诱导复述「可复制即执行」的破坏性命令行（``rm -rf``／``mkfs``／
``Remove-Item -Recurse -Force``／``del /s /q``／``reg delete``／``shutdown`` 一族）
时，出站侧此前零过滤——密钥有 ``redact_local_secrets`` 打码，危险命令没有任何层。
本波落 ``domains/render/plain_text.py::redact_destructive_commands``：命中即整段
换成人话占位，围栏代码块（教学语境）豁免，与密钥打码同层不互踩（双向链式幂等）。

形态名册是**封闭名册**（与 plain_text 既有各腿同一纪律：扩一个＝扩一次误伤面，
新形态必须有实据再进册）；每条腿都带防误伤边界，反向锁见 ``test_benign_lookalikes_pass``。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.render.plain_text import (
    DESTRUCTIVE_COMMAND_NOTICE,
    redact_destructive_commands,
    redact_local_secrets,
)

DESTRUCTIVE_COMMANDS: tuple[str, ...] = (
    # POSIX rm 递归/强删族（含 sudo 前缀与 --recursive 长形）
    "rm -rf /tmp/build",
    "sudo rm -rf /",
    "rm -fr ~/.ssh",
    "rm -r -f ~/.config",
    "rm --recursive /home/x/data",
    # mkfs 家族
    "mkfs /dev/sda1",
    "mkfs.ext4 /dev/sdb",
    # dd 写设备
    "dd if=/dev/zero of=/dev/sda",
    "dd of=/dev/nvme0n1 bs=1M",
    # fork 炸弹
    ":(){ :|:& };:",
    # PowerShell 递归删
    "Remove-Item -Recurse -Force C:\\\\temp\\\\x",
    "remove-item -recurse ./build",
    # cmd 删树族
    "rd /s /q C:\\\\temp",
    "rmdir /s /q D:\\\\old",
    "del /s /q C:\\\\Users\\\\x\\\\*",
    "erase /s /q C:\\\\old",
    # format 盘
    "format C:",
    "format d: /q",
    "Format-Volume -DriveLetter D",
    # 注册表删
    "reg delete HKLM\\\\SOFTWARE\\\\Key /f",
    "REG DELETE HKCU\\\\Run /v x /f",
    # 关机/重启
    "shutdown /s /t 0",
    "shutdown -h now",
    "shutdown now",
    "shutdown -r",
    # 卷影副本清除
    "vssadmin delete shadows /all",
)


@pytest.mark.parametrize("command", DESTRUCTIVE_COMMANDS)
def test_destructive_commands_are_redacted(command: str) -> None:
    """每一条在册破坏性命令都必须被整段换掉，且前后文保留（打码不吞句）。"""
    wrapped = f"你可以运行 {command} 试试"
    out = redact_destructive_commands(wrapped)
    assert command not in out, f"破坏性命令原样漏出：{out}"
    assert "我不能原样提供" in out, f"占位话术缺失：{out}"
    assert out.startswith("你可以运行 ") and out.endswith(" 试试"), f"前后文被误吞：{out}"


def test_notice_copy_is_served_for_callers() -> None:
    """话术常量在册且是「我不能提供」族（接线方按需附在回执尾）。"""
    assert "不能" in DESTRUCTIVE_COMMAND_NOTICE and "命令" in DESTRUCTIVE_COMMAND_NOTICE


def test_benign_lookalikes_pass() -> None:
    """防误伤锁：日常行文里这些形**一字不动**（误伤锁与形态锁同批在册）。"""
    benign_lines: tuple[str, ...] = (
        "rm.txt 是个文件名，不是命令",
        "请确认后按 r 键刷新页面",
        "我们 format 了文档的格式，没动磁盘",
        "用 formatter 库统一缩进",
        "register_shutdown_hook() 是框架钩子",
        "shutdown -a 可以取消已经排程的关机",
        "reg query HKLM\\\\SOFTWARE 只读不删",
        "del /q 只删单个文件，不递归",
        "rmdir 空目录不需要任何参数",
        "Remove-Item 单个文件、不带 -Recurse 时只删那一个",
        "把中间件 dd 进镜像前先看大小",
        "odd numbers 都跳过了",
    )
    for line in benign_lines:
        out = redact_destructive_commands(line)
        assert out == line, f"良性句被误伤：{line!r} → {out!r}"


def test_fenced_teaching_block_is_exempt() -> None:
    """教学语境豁免：围栏代码块（``` 与 ~~~）内一字不动。"""
    fenced = "教学示例：\n```bash\nrm -rf /tmp/x\nshutdown /s\n```\n照抄前想清楚。"
    assert redact_destructive_commands(fenced) == fenced
    tilde = "~~~\ndd if=/dev/zero of=/dev/sda\n~~~"
    assert redact_destructive_commands(tilde) == tilde


def test_inline_outside_fence_still_caught() -> None:
    """豁免只认围栏内：围栏外的行内命令照打（把 payload 藏在正文里照样拦）。"""
    text = "```\nrm -rf /a\n```\n然后运行 rm -rf /b"
    out = redact_destructive_commands(text)
    assert "rm -rf /a" in out, "围栏内教学示例被误伤"
    assert "rm -rf /b" not in out, "围栏外命令漏网"


def test_idempotent() -> None:
    """二次运行不再变化（占位话术不是任何腿的形态）。"""
    once = redact_destructive_commands("先跑 rm -rf /tmp/x 再 format C:")
    twice = redact_destructive_commands(once)
    assert once == twice


def test_stable_when_chained_with_secret_redaction_both_orders() -> None:
    """与 ``redact_local_secrets`` 同层不互踩：两种串联次序终态一致、各打各的。"""
    text = "先跑 sudo rm -rf C:/Users/x/data/db.sqlite3 再把 sk-abcdef123456 清掉"
    a = redact_local_secrets(redact_destructive_commands(text))
    b = redact_destructive_commands(redact_local_secrets(text))
    assert a == b, f"两种次序终态漂移：\nA={a!r}\nB={b!r}"
    assert "rm -rf" not in a
    assert "sk-abcdef123456" not in a


def test_empty_and_plain_text_passthrough() -> None:
    assert redact_destructive_commands("") == ""
    assert redact_destructive_commands("今天天气不错") == "今天天气不错"
