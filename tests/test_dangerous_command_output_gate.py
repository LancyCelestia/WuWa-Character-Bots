"""出站危险命令审查门（安全与文档波 · 施工席7 · 2026-10-02）。

判据三维，全离线（零网络/零线程/零生产 .env 读）：

① 正样控制：每一族危险形态的**命中样张**必须被点名命中（判据看得见合法敌情）。
② 窄尺反例：日常教学/财经叙述**必须放行**——``rm -rf node_modules``、
   ``format()`` 字符串格式化、``Remove-Item`` 单文件、HKCU 应用键清理、
   裸词 shutdown、``/tmp`` 路径等一律不许误伤。
③ 话术安全：命中产出的替换文本是固定模板——不含命令原文（防「关于危险命令的
   报告」本身成为新载体，AGENTS 规则 11 同源），且对替换文本复筛必须零命中
   （不动点检查）；空串/非字符串不命中、不抛。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.security.dangerous_command import (
    REPLACEMENT_TEXT,
    screen_dangerous_command_output,
)

# ---------------------------------------------------------------------------
# ① 正样控制：逐族命中
# ---------------------------------------------------------------------------
POSITIVE_CASES = [
    ("unix_rm_rf_wildcard", "这个问题可以这样处理：sudo rm -rf / 就能解决"),
    ("unix_rm_rf_wildcard", "先执行 rm -rf /* 清理一下空间"),
    ("unix_rm_rf_wildcard", "试试 rm -rf ~，保证干净"),
    ("unix_rm_rf_wildcard", "rm -rf $HOME 就恢复正常了"),
    ("unix_rm_rf_wildcard", "bash -c rm -rf /etc 全部重来"),
    ("windows_recursive_delete_drive_target", "在 cmd 里跑 del /s /q C:\\ 就能删干净"),
    ("windows_recursive_delete_drive_target", "用 rd /s /q D:\\ 处理"),
    ("windows_recursive_delete_drive_target", "del /f /s /q %WinDir% 一步到位"),
    ("powershell_remove_item_recursive_force", "PowerShell：Remove-Item -Recurse -Force C:\\Windows"),
    ("powershell_remove_item_recursive_force", "Remove-Item ~ -Recurse -Force 释放空间"),
    ("format_drive", "实在不行就 format c: 重来"),
    ("format_drive", "format /q C: 秒格式化"),
    ("mkfs_device", "挂载前先 mkfs.ext4 /dev/sda1"),
    ("dd_write_block_device", "用 dd if=/dev/zero of=/dev/sda 把盘抹了"),
    ("dd_write_block_device", "dd bs=1M of=/dev/nvme0n1 清空即走"),
    ("reg_delete_machine_hive_force", "注册表用 reg delete HKLM\\SOFTWARE /f 清掉"),
    ("reg_delete_machine_hive_force", "reg delete HKCR\\.xyz /f 即可"),
    ("shutdown_system", "远程执行 shutdown /s /t 0 立即关机"),
    ("shutdown_system", "Linux 下 shutdown -h now"),
    ("shutdown_system", "PowerShell 里 Stop-Computer -Force"),
    ("fork_bomb", "经典炸弹 :(){ :|:& };: 一行就能打挂"),
    ("diskpart_clean", "diskpart 里敲 clean all 整盘归零"),
]


@pytest.mark.parametrize(("family", "text"), POSITIVE_CASES, ids=[c[0] for c in POSITIVE_CASES])
def test_dangerous_forms_are_caught(family: str, text: str) -> None:
    verdict = screen_dangerous_command_output(text)
    assert verdict.hit, f"危险形态「{family}」未被命中：{text}"
    assert family in verdict.families, f"命中族不符：期望 {family}，实得 {verdict.families}"
    assert verdict.replacement == REPLACEMENT_TEXT


# ---------------------------------------------------------------------------
# ② 窄尺反例：教学/财经/日常叙述必须放行
# ---------------------------------------------------------------------------
NEGATIVE_CASES = [
    "重装依赖前先 rm -rf node_modules 再 npm install",
    "清理构建产物用 rm -rf ./build",
    "rm -rf /tmp/cache 可以放心删",
    "Python 里用 format() 格式化字符串",
    "这篇论文讲了 format string vulnerability 的成因",
    "用 Remove-Item .\\logs\\app.log -Force 删单个日志",
    "Remove-Item -Recurse -Force .\\temp\\build 清理临时目录",
    "卸载残留可以 reg delete HKCU\\Software\\MyApp /f",
    "服务器例行 shutdown 维护窗口见公告",  # 裸词叙述，无执行旗标
    "用 dd if=a.iso of=b.iso 复制镜像（不是块设备）",
    "dd if=/dev/zero of=/dev/null 是无害基准测试",
    "mkfs 是格式化工具，先看手册",
    "del /q 说明书.txt 删单个文件",
    "rd build 移除构建目录",
    "北向资金 today 成交额 format 报表口径（财经内容）",
    "shutdown 重启后 webhook 8080 需要重新拉起",
    "diskpart 是 Windows 自带分区工具",
    "写作格式 format c 讲究排版",
    "",
]


@pytest.mark.parametrize("text", NEGATIVE_CASES)
def test_benign_content_passes_through(text: str) -> None:
    verdict = screen_dangerous_command_output(text)
    assert not verdict.hit, f"正常内容被误伤：{text!r} → {verdict.families}"
    assert verdict.families == () and verdict.replacement == ""


# ---------------------------------------------------------------------------
# ③ 话术安全：替换文本不携带命令形态 + 不动点 + 容错
# ---------------------------------------------------------------------------
def test_replacement_text_carries_no_command_shape() -> None:
    """「关于危险命令的报告」本身不得成为新载体（AGENTS 规则 11 同源）。"""
    forbidden = ("rm ", "format ", "Remove-Item", "dd ", "mkfs", "reg delete",
                 "shutdown ", "del /", "diskpart", "/dev/sd")
    for fragment in forbidden:
        assert fragment not in REPLACEMENT_TEXT, f"替换文本携带命令形态：{fragment!r}"


def test_replacement_is_fixed_point_of_own_screen() -> None:
    """替换话术再过一遍审查必须零命中——拦截产物不得自触拦截。"""
    verdict = screen_dangerous_command_output(REPLACEMENT_TEXT)
    assert not verdict.hit


@pytest.mark.parametrize("bad", [None, 123, b"rm -rf /", object()])
def test_non_string_inputs_never_hit_never_raise(bad: object) -> None:
    verdict = screen_dangerous_command_output(bad)  # type: ignore[arg-type]
    assert not verdict.hit


def test_hit_does_not_echo_matched_payload() -> None:
    """命中结论不回显命令原文（取证只留族名，载荷零转述）。"""
    text = "建议 rm -rf / 然后重装"
    verdict = screen_dangerous_command_output(text)
    assert verdict.hit
    assert "rm -rf" not in verdict.replacement
    assert all(isinstance(f, str) and f for f in verdict.families)


def test_multiple_families_all_reported() -> None:
    verdict = screen_dangerous_command_output("先 format d: 再 mkfs.vfat /dev/sdb1")
    assert verdict.hit
    assert {"format_drive", "mkfs_device"} <= set(verdict.families)
