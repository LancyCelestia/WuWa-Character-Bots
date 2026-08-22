import re
from typing import Optional


# ————————————————————————————
# B站 UID，BV号，URL 自动解析
# ————————————————————————————

def parse_uid(text: str) -> Optional[str]:
    """
    从用户输入中提取 B站 UID
    支持：
    - 纯数字 UID：123456
    - 空间链接：https://space.bilibili.com/123456
    - 夹杂在其他文字中：UID 123456 / uid 123456 / 用户123456
    """
    # 匹配空间链接中的 UID
    match = re.search(r'space\.bilibili\.com/(\d+)', text)
    if match:
        return match.group(1)

    # 匹配 UID 关键词附近数字
    match = re.search(r'(?:uid|UID|用户|空间|UP主)[：:]*\s*(\d{5,})', text)
    if match:
        return match.group(1)

    # 匹配至少 5 个独立数字
    match = re.search(r'\b(\d{5,})\b', text)
    if match:
        return match.group(1)

    return None


def parse_bv(text: str) -> Optional[str]:
    """
    从用户输入中提取 B站 BV 号（BV + 10位字母数字），找不到返回 None
    """
    match = re.search(r'BV[0-9A-Za-z]{10}', text)
    return match.group(0) if match else None


def parse_b23_url(text: str) -> Optional[str]:
    """
    从用户输入中提取 b23.tv 短链接，找不到返回 None
    """
    match = re.search(r'https?://b23\.tv/[A-Za-z0-9]+|(?<![\w./])b23\.tv/[A-Za-z0-9]+', text)
    return match.group(0) if match else None


def parse_video_url(text: str) -> Optional[str]:
    """
    从用户输入中提取 B站视频完整 URL
    """
    match = re.search(r'https?://(?:www\.)?bilibili\.com/video/[^\s]+', text)
    return match.group(0) if match else None
